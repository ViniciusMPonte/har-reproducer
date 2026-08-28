# Plano de Implementação — Correção do Bug de `request.url` Templado no `CookieJar`

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `Engine`: reproduzir o crash com um teste vermelho

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_engine.py` (novo teste)

**Contexto:**
Antes de tocar em `Engine._attempt_step`, esta task só escreve o teste que
reproduz o `ValueError` documentado em `docs/20260828 Reteste do Portal Unimed
com Jar de Cookies/README.md` — a URL de um step idêntica ao valor já
extraído de outro token vira, em memória, uma string com
`{{extractor:<token_id>}}` embutido sem separador `/`, e
`RequestUrlScope.parts` explode ao tentar interpretar parte do placeholder
como porta. O teste precisa falhar pelo motivo certo (red) antes de T02
corrigir o código.

**Estado atual:**
- `_step_with_curl` (`tests/unit/test_engine.py:189-195`) constrói um `Step`
  com `request.url` já limpo — nenhum teste existente simula uma URL
  templada chegando em `_attempt_step`.
- `Engine._attempt_step` (`engine.py:152-159`) chama
  `RequestUrlScope.parts(step.request.url)` (linha 155) — se `step.request.url`
  já contiver um placeholder de extractor sem separador `/` antes dele, essa
  chamada levanta `ValueError` (não capturada em nenhum ponto da cadeia).

**Estado esperado depois:**
- Um novo teste, por exemplo `test_attempt_step_crashes_when_request_url_is_templated_without_separator`,
  constrói um `Step` cujo `request.url` já simula o efeito de
  `PlaceholderApplier._replace_in_url` (`placeholder_applier.py:45-46`) —
  algo como `_step_with_curl(0, "https://exemplo.com{{extractor:abc123}}", "curl https://exemplo.com/pagina")`
  — e confirma que, no estado atual do código, `engine._attempt_step(step)`
  levanta `ValueError`. Sem persistir `workspace.request_file(0)` antes (essa
  é justamente a condição atual, insegura).
- ⚠️ Este teste fica **vermelho de propósito** neste commit — ele existe para
  provar que o bug é real e reproduzível em teste unitário, não só no HAR
  real do portal Unimed. Roda com `pytest.raises(ValueError)` para deixar
  claro que o comportamento atual (o bug) é o que está sendo capturado — não
  é um teste que "falha", é um teste que documenta o estado atual antes da
  correção.

**Critérios de aceite:**
- [ ] `pytest tests/unit/test_engine.py -k test_attempt_step_crashes_when_request_url_is_templated_without_separator -v` passa (o teste confirma que `ValueError` é levantado hoje).
- [ ] O teste usa `pytest.raises(ValueError)` ao redor de `engine._attempt_step(step)`, não um `try/except` manual.
- [ ] Nenhum outro teste de `tests/unit/test_engine.py` foi alterado nesta task.

---

## [T02] — `Engine`: `_attempt_step` usa `RequestUrlScope.parts_for_step` em vez de `parts(step.request.url)`

**Depende de:** T01 (o teste vermelho precisa existir e falhar pelo motivo certo antes desta correção).
**Arquivos envolvidos:** `har_reproducer/engines/engine.py` (`Engine._attempt_step`), `tests/unit/test_engine.py` (teste de T01 vira verde e ganha um caso positivo)

**Contexto:**
Correção central da spec (seção 3.1). `Engine._attempt_step` é o único dos
três pontos de integração do jar (`Engine`, `ReplayRunner`, `ReplayOptimizer`)
que lê `step.request.url` em memória — um campo que
`PlaceholderApplier._replace_in_url` já pode ter mutado para conter um
placeholder de extractor não resolvido antes de `_attempt_step` rodar. A
correção troca a fonte para `Workspace.request_file(step.index)`, sempre a
URL real do HAR, usando o mesmo utilitário que `ReplayRunner`/`ReplayOptimizer`
já usam para o mesmo propósito.

**Estado atual** (`engine.py:152-159`):
```python
def _attempt_step(self, step: Step) -> StepResponse:
    assert self.http_transport is not None
    curl_literal: str = self.session_store.render(step.analysis.curl_template)
    host, port, path = RequestUrlScope.parts(step.request.url)
    curl_with_jar: str = self.cookie_jar_curl_override.apply(curl_literal, host, port, path)
    response: StepResponse = self.http_transport.send_request(curl_with_jar, step.index)
    self.cookie_jar.feed(host, port, response.cookies, response.cookie_attributes)
    return response
```

**Estado esperado depois:**
```python
def _attempt_step(self, step: Step) -> StepResponse:
    assert self.http_transport is not None
    curl_literal: str = self.session_store.render(step.analysis.curl_template)
    host, port, path = RequestUrlScope.parts_for_step(self.workspace, step.index)
    curl_with_jar: str = self.cookie_jar_curl_override.apply(curl_literal, host, port, path)
    response: StepResponse = self.http_transport.send_request(curl_with_jar, step.index)
    self.cookie_jar.feed(host, port, response.cookies, response.cookie_attributes)
    return response
```
- Única linha alterada: `RequestUrlScope.parts(step.request.url)` →
  `RequestUrlScope.parts_for_step(self.workspace, step.index)`.
- `self.workspace` já é atributo existente de `Engine` (`engine.py:35`) —
  nenhuma dependência nova, nenhuma mudança de assinatura de construtor.
- `RequestUrlScope`, `PlaceholderApplier`, `ReplayRunner`, `ReplayOptimizer`:
  **sem alteração** (spec seção 4 — confirmado seguro nas seções 3.2/3.3 da
  spec).
- ⚠️ Não capturar `FileNotFoundError`/adicionar fallback aqui — em produção
  o arquivo sempre existe no momento em que `_attempt_step` roda (garantido
  pela ordem de `_process_entry`, ver T03). Um `try/except` aqui mascararia
  silenciosamente uma violação real dessa garantia, o mesmo raciocínio que a
  spec usa para descartar tornar `RequestUrlScope.parts` tolerante a
  `ValueError` (spec seção 3.1).

**Critérios de aceite:**
- [ ] O teste de T01 (`test_attempt_step_crashes_when_request_url_is_templated_without_separator`) é atualizado: em vez de `pytest.raises(ValueError)`, agora persiste `workspace.request_file(0)` com a URL real (`https://exemplo.com/pagina`) antes de chamar `_attempt_step`, e confirma que `engine._attempt_step(step)` **não** levanta exceção e resolve `host`/`port`/`path` a partir da URL persistida, não da templada em memória — ex.: `assert transport.calls[0].curl_literal` contém a URL/porta esperada, coerente com `https://exemplo.com/pagina`, mesmo com `step.request.url` ainda templado no objeto em memória.
- [ ] Os 4 testes existentes citados na spec (`test_attempt_step_overrides_curl_cookie_with_jar_state_before_sending`, `test_attempt_step_feeds_jar_from_response_set_cookie`, `test_attempt_step_adds_cookie_flag_when_curl_has_none_but_jar_has_cookie`, `test_execute_step_retry_feeds_jar_from_first_attempt_before_second_attempt_sends`) **ainda falham** neste ponto do plano (vão passar a falhar com `FileNotFoundError`, não mais o comportamento atual) — isso é esperado e fica coberto por T03, não por esta task. Rodar `pytest tests/unit/test_engine.py -v` aqui só para confirmar que as falhas são exatamente essas 4 e pelo motivo esperado (`FileNotFoundError` de `workspace.request_file`), não outra coisa.
- [ ] `git grep "RequestUrlScope.parts(step.request.url)"` não retorna nenhuma ocorrência em `har_reproducer/` depois desta task.

---

## [T03] — `tests/unit/test_engine.py`: persistir `request_file` antes de chamar `_attempt_step`/`execute_step` diretamente

**Depende de:** T02.
**Arquivos envolvidos:** `tests/unit/test_engine.py`

**Contexto:**
Os 4 testes citados na spec (seção 5) chamam `engine._attempt_step(step)`/
`engine.execute_step(step)` diretamente, pulando `_process_entry` — e por
isso nunca persistem `workspace.request_file(step.index)`, algo que a
produção sempre garante antes de `_attempt_step` rodar (`_persist_request_step`,
`engine.py:87`, antes de `analyze_step`, `engine.py:93`, antes de
`execute_step`, `engine.py:96`). Depois de T02, esses 4 testes passam a
levantar `FileNotFoundError` em `RequestUrlScope.parts_for_step`. Esta task
não é um efeito colateral indesejado — torna explícito, no próprio teste, o
invariante que a produção já garante.

**Estado atual** (exemplo, `tests/unit/test_engine.py:198-211`):
```python
def test_attempt_step_overrides_curl_cookie_with_jar_state_before_sending(tmp_path: Path) -> None:
    jar: CookieJar = CookieJar()
    jar.feed("exemplo.com", 443, {"sess": "abc"}, {})
    transport: StubHttpTransport = StubHttpTransport(StepResponse(status_code=200))
    engine: Engine = _engine(
        tmp_path, FakeTokenResolver(), [], http_transport=transport, cookie_jar=jar,
    )
    step: Step = _step_with_curl(0, "https://exemplo.com/login", "curl --cookie 'sess=old' https://exemplo.com/login")

    engine._attempt_step(step)

    assert "sess=abc" in transport.calls[0].curl_literal
    assert "sess=old" not in transport.calls[0].curl_literal
```

**Estado esperado depois:**
- Um novo helper, ao lado de `_step_with_curl` (`tests/unit/test_engine.py:189-195`):
```python
def _step_with_curl(index: int, url: str, curl_template: str, workspace: Optional[Workspace] = None) -> Step:
    step: Step = Step(
        index=index,
        request=StepRequest(url=url, method="GET"),
        response=StepResponse(status_code=200),
        analysis=StepAnalysis(step_index=index, curl_template=curl_template),
    )
    if workspace is not None:
        workspace.request_file(index).write_text(step.request.model_dump_json(), encoding="utf-8")
    return step
```
  ⚠️ `workspace` é `Optional` e opcional por padrão para não quebrar nenhum
  outro chamador de `_step_with_curl` fora dos 4 testes desta task (confirmar
  com `git grep "_step_with_curl("` antes de fechar a task — se existir
  algum outro uso hoje, ele continua funcionando sem o parâmetro novo).
- Os 4 testes citados passam a chamar `_step_with_curl(0, "https://exemplo.com/login", "...", workspace=engine.workspace)`
  (ou, alternativamente, uma chamada explícita de
  `engine.workspace.request_file(0).write_text(...)` logo antes de `_attempt_step`/`execute_step` —
  escolher uma das duas formas e aplicar consistentemente nas 4; o helper com
  parâmetro opcional é a forma preferida por evitar repetição).

**Critérios de aceite:**
- [ ] `pytest tests/unit/test_engine.py -v` — todos os testes do arquivo passam, incluindo os 4 citados e o de T01/T02.
- [ ] `test_attempt_step_overrides_curl_cookie_with_jar_state_before_sending`: `"sess=abc" in transport.calls[0].curl_literal` e `"sess=old" not in transport.calls[0].curl_literal` continuam verdadeiros (não-regressão do comportamento já coberto).
- [ ] `test_attempt_step_feeds_jar_from_response_set_cookie`: `jar.current("exemplo.com", 443, "/") == {"sess": "abc"}` continua verdadeiro.
- [ ] `test_attempt_step_adds_cookie_flag_when_curl_has_none_but_jar_has_cookie`: `"--cookie" in transport.calls[0].curl_literal` e `"sess=abc" in transport.calls[0].curl_literal` continuam verdadeiros.
- [ ] `test_execute_step_retry_feeds_jar_from_first_attempt_before_second_attempt_sends`: `len(transport.calls) == 2` e `"sess=abc" in transport.calls[1].curl_literal` continuam verdadeiros — inclusive confirmando que persistir o `request_file` uma única vez (antes da primeira tentativa) é suficiente para as duas tentativas de `StepRetryPolicy` (spec seção 5, "Retry de step").
- [ ] Nenhum outro teste de `tests/unit/test_engine.py` (os que não usam `_step_with_curl`) foi alterado nesta task.

---

## [T04] — Teste de regressão de ordem: `_persist_request_step` sempre roda antes de `analyze_step`

**Depende de:** T02.
**Arquivos envolvidos:** `tests/unit/test_engine.py`

**Contexto:**
Spec seção 6 ("Suposições e pontos a confirmar"): a correção de T02 depende
inteiramente de `Workspace.request_file(index)` já existir no disco quando
`_attempt_step` roda — garantia que vem da ordem atual de `_process_entry`
(`engine.py:87` antes de `engine.py:93` antes de `engine.py:96`), não de
nenhuma trava explícita. Se uma refatoração futura reordenar isso, a
garantia quebra silenciosamente (o arquivo não existiria ainda, e
`RequestUrlScope.parts_for_step` levantaria `FileNotFoundError`). Esta task
adiciona um teste que trava essa ordem via `_reproduce`/`_process_entry`
real (não via `_attempt_step` isolado, que já não exercita `_process_entry`).

**Estado atual:**
- Nenhum teste de `tests/unit/test_engine.py` verifica, via `_process_entry`
  ou `_reproduce`, que `workspace.request_file(index)` existe no disco com a
  URL real (não templada) no momento em que a resposta HTTP é enviada.
  `test_reproduce_keeps_returning_the_final_validation_result` e vizinhos
  (`tests/unit/test_engine.py:161-186`) usam `SilentEngine`, que sobrescreve
  `_process_entry` inteiro e não exercita esse caminho.

**Estado esperado depois:**
- Um novo teste de integração leve, montando um HAR mínimo de 1-2 entries
  (reaproveitando o padrão de `_har_with_bodyless_entries`,
  `tests/unit/test_engine.py:136-146`, ou um helper equivalente que já
  inclua corpo de resposta) e rodando `Engine._reproduce()` de ponta a ponta
  com um `http_transport` stub — confirmando, ao final, que
  `workspace.request_file(0).exists()` é verdadeiro e que o conteúdo
  persistido bate com a URL real do HAR (não um placeholder), mesmo quando
  o HAR contém um token dinâmico cujo valor colide com a URL de outro step
  (reproduzindo o cenário do step 104 do portal Unimed em miniatura, com
  duas entries: uma que estabelece um token cujo `captured_value` é igual à
  URL — ou parte dela — da segunda entry).
- ⚠️ Este teste é sobre a **ordem de execução** (persistência antes de
  mutação), não sobre o resultado do jar em si — os 4 testes de T03 já
  cobrem o comportamento do jar isoladamente. Evitar duplicar asserções de
  cookie aqui; o foco é `request_file(index).exists()` e seu conteúdo bater
  com a URL real.

**Critérios de aceite:**
- [ ] O novo teste falha (`FileNotFoundError` ou URL templada persistida) se `_persist_request_step` for movido, no código de produção, para depois de `analyze_step` (validar manualmente reordenando as duas linhas em `_process_entry` durante a implementação da task, confirmando o teste pega a quebra, e desfazendo a mudança antes de commitar).
- [ ] `pytest tests/unit/test_engine.py -v` passa com o código de produção no estado correto (ordem atual, inalterada).
- [ ] O teste não duplica nenhuma asserção já coberta por T01-T03 sobre o comportamento do jar (cookies aplicados/alimentados) — só verifica a ordem/conteúdo de `request_file`.

---

## Verificação final (não é uma task, é o fechamento do plano)

Antes de marcar o plano como concluído (Passo 4 da skill `spec-e-plano`),
confirmar a garantia de não-regressão de ponta a ponta que a spec pede
(seção 6, "pontos a confirmar"):

```bash
uv run python -m har_reproducer.main run \
  --har /home/viniciuspontes/Documentos/Trabalho/har-files/teste-unimed/captura_20260825_184021_reduzido.har \
  --config /home/viniciuspontes/Documentos/Trabalho/har-reproducer/config.json \
  --mode main \
  --output /home/viniciuspontes/Documentos/Trabalho/har-files/teste-unimed/output-fix-verificacao/
```

Critério: os 107/107 steps completam sem `ValueError`, e o resultado final
(status/validação) é consistente com o baseline de
`docs/20260825 Verificação do Fechamento — Token de Login/README.md` e
`docs/20260828 Reteste do Portal Unimed com Jar de Cookies/README.md` (0
divergências de `JSESSIONID`/`status_code` nos steps 0-104, e agora também
sucesso nos steps 105-106, que antes nunca rodavam). Isso depende de o
portal `autorizador.unimedriopreto.com.br` estar acessível no momento da
verificação — se não estiver, registrar a limitação (mesmo critério já usado
nos dois relatórios anteriores) em vez de simular o resultado.

Rodar também a suíte completa não-`--runslow` como sanity check rápido antes
dessa verificação de rede:

```bash
uv run pytest tests/unit -v
```
