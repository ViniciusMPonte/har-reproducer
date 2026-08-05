# Spec — Overhead Redundante de Resolução de Tokens no Modo Main

> Fonte única de verdade para gerar o `implementation_plan.md` desta etapa. Assume que
> quem escreve o plano não participou da conversa que chegou a estas decisões — tudo
> que é necessário para entender o "porquê" e o "o quê" está aqui, sem depender de nada
> além do código-fonte atual do projeto (`har_reproducer/`), do `guia_de_estilo.md` e
> da spec anterior, `docs/20260805 Redução de Overhead em Resolução Redundante de
> Tokens/spec.md` (referida abaixo como "spec anterior").

## 1. Objetivo

A spec anterior identificou e corrigiu dois pontos de overhead O(n²) no fluxo de
tracking de tokens (custo proporcional ao histórico acumulado da run, não só ao step
atual), mas limitou o Ponto 1 (`TokenResolver.resolve_all()` chamado incondicionalmente
a cada step) exclusivamente ao `DryEngine`. A justificativa registrada lá (seção 1,
"Fora de escopo") foi: **não havia evidência, naquele momento, de que um response já
persistido em `real_responses/` nunca é afetado por captura assíncrona do proxy
`mitm` fora do loop principal** — e por isso o Ponto 1 não foi tocado para `run --mode
main` (`Engine` base, `USES_NETWORK = True`).

Rodando exatamente o comando reportado como lento —
```
uv run python -m har_reproducer.main run --har arquivos-har/progressofit.har \
    --config config.json --mode main
```
— contra uma run anterior já persistida deste mesmo HAR (238 entries,
`arquivos-har/output/`), a investigação desta spec **confirma, com evidência de
código e dados empíricos dessa run**, que a mesma redundância do Ponto 1 também ocorre
em `main`, e que a incerteza que motivou excluí-lo está resolvida:

**A captura do mitmproxy nunca escreve em `real_responses/`.** O addon
(`reproduction/mitm_addon.py:103-107`) escreve exclusivamente em um arquivo separado e
sobrescrito a cada request, `Workspace.mitm_capture_file()`
(`fs_io/workspace.py:76-78`, `<output_dir>/mitm_capture/capture.har`), sempre com uma
única entry (`_build_envelope`, `mitm_addon.py:33-34`). Quem grava
`real_responses/res_{index:04d}.json` é exclusivamente
`Engine._persist_response_step` (`engines/engine.py:135-136`), chamado de forma
síncrona dentro do laço principal (`_process_entry`, `engine.py:114`), **depois** que
`CurlHttpTransport.send_request` já terminou (subprocess bloqueante,
`curl_http_transport.py:24-28`) e já leu a captura via polling síncrono
(`_read_captured_response`, `curl_http_transport.py:62-68`). Não existe thread,
callback ou processo separado que escreva em `real_responses/` — busca no projeto
inteiro confirma que os únicos escritores de `Workspace.response_file(...)` são
`engine.py:136` (grava) e `dry_engine.py:14` (no-op). A garantia de "append-only" que a
spec anterior já registrava na seção 2 para os dois engines (`engine.py:128-137`) se
aplica **sem ressalva** a `main`: um `res_XXXX.json` já escrito nunca é reescrito por
nenhum caminho assíncrono do proxy.

**Confirmação empírica.** Na run anterior deste HAR em `arquivos-har/output/`
(`real_responses/`: 238 arquivos, `extractors/`: 55 extractors distintos gerados), o
intervalo entre requests sucessivas (mtime de `real_requests/req_XXXX.json`) cresce de
~0.1s nos primeiros steps para ~1.4-1.5s nos últimos — um fator de ~15×. Os 55 arquivos
de extractor em `extractors/*.py` têm mtime **todos dentro de uma janela de ~1.4s,
imediatamente após o timestamp do último request** — ou seja, o **último**
`resolve_all()` da run reescreveu os 55 arquivos de extractor de uma vez (cada chamada
a `ExtractorRunner.run()` reescreve o `.py` do extractor incondicionalmente via
`_write_extractor_script`, `extractor_runner.py:31-42`, mesmo quando o conteúdo não
muda). Um benchmark neste mesmo ambiente mede spawn de subprocess Python em **~15-16ms**
— compatível com o custo de `~55 × 15ms ≈ 825ms` extras só de `resolve_all()` no último
step, o que bate com o salto observado de ~0.1s para ~1.4-1.5s por step ao longo da
run. Esse crescimento acompanha o tamanho do registry, não a rede: é o mesmo padrão
O(n²) do Ponto 1 da spec anterior, agora confirmado também em `main`.

**Por que `resolve_all()` não pode simplesmente ser removido de `main` (diferença do
Ponto 1 original).** Em `DryEngine.execute_step` (`engines/dry_engine.py:10-12`), o
`step.response` é devolvido direto — o `curl_template` nunca é renderizado, então um
token sem valor em `session_store.state.tokens` não tem efeito observável, e por isso a
spec anterior pôde remover a chamada inteira para `dry`. Em `main`,
`Engine._attempt_step` (`engine.py:163-167`) chama
`self.session_store.render(step.analysis.curl_template)` — e `SessionStore.render`
(`session/session_store.py:22-24,36-41`) deixa o placeholder `{{extractor:token_id}}`
**literal** no comando se `token_id` não estiver em `self.state.tokens`. Ou seja, para
`main`, `resolve_all()` continua sendo necessário sempre que um token **novo** foi
registrado neste step e ainda não tem valor — só o re-processamento de tokens **já
resolvidos** é redundante.

Fora de escopo (não implementar agora):
- Qualquer mudança em `handle_recovery` (`engine.py:149-158`) — continua chamando
  `resolve_all()` de forma incondicional/completa na recuperação de 400/401,
  independente da mudança desta spec (seção 3.1, ver justificativa).
- Otimizar o polling de leitura da captura do mitm em `CurlHttpTransport`
  (`curl_http_transport.py:62-68`, até 5 tentativas de 0.1s) — é um custo fixo por
  step, não cresce com o histórico da run, e os deltas observados no início da run
  (~0.1s) mostram que não é a fonte do crescimento investigado aqui.
- Custo de startup do `mitmdump` (`MitmProxyOrchestrator._wait_until_ready`,
  `mitm_proxy_orchestrator.py:87-105`) — custo único por run, não por step.
- Geração de extractor via LLM — custo esperado e conhecido, já excluído
  explicitamente pelo usuário na spec anterior.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

- **`Engine._process_entry`** (`engine.py:93-120`) — trecho relevante:
  ```python
  step.analysis = self.tracker.analyze_step(step, first_entry)
  if self.USES_NETWORK:
      self.token_resolver.resolve_all()

  response: StepResponse = self.execute_step(step)
  ```
  Em `main` (`Engine.USES_NETWORK = True`, `engine.py:24`), `resolve_all()` roda em
  **todo** step, sempre — o `if` introduzido pela spec anterior só afeta `dry`.

- **`TokenResolver.resolve_all`** (`tracking/token_resolver.py:15-34`):
  ```python
  def resolve_all(self) -> None:
      for token_id, extractor in self.session_store.state.registry.items():
          if self._should_refresh_token(extractor):
              self._refresh_token(token_id, extractor)

  def _should_refresh_token(self, extractor: Extractor) -> bool:
      return extractor.verified and extractor.origin_step is not None

  def _refresh_token(self, token_id: str, extractor: Extractor) -> None:
      if not (self.responses_dir / f"res_{extractor.origin_step:04d}.json").exists():
          return
      try:
          value: Optional[str] = self.extractor_runner.run(extractor, self.responses_dir)
      except Exception as e:
          print(f"Failed to refresh token '{token_id}': {e}")
          return
      if value:
          self.session_store.set_token(token_id, value)
  ```
  Itera **todo** `session_store.state.registry` (só cresce ao longo da run — 55
  entries na run de referência). Nenhum filtro por "já resolvido"; todo extractor
  `verified` com `origin_step` é reexecutado, sempre, mesmo quando
  `session_store.state.tokens` já tem um valor válido para aquele `token_id` de uma
  chamada anterior.

- **`ExtractorRunner.run`** (`reproduction/extractor_runner.py:16-19,31-42`):
  ```python
  def run(self, extractor: Extractor, response_override_dir: Optional[Path] = None) -> Optional[str]:
      extractor_file: Path = self._write_extractor_script(extractor)
      self._cleanup_temp_file(extractor)
      return self._execute_extractor_script(extractor_file, response_override_dir)
  ```
  `_write_extractor_script` (linhas 31-42) **sempre** regrava
  `Workspace.extractor_file(token_id)` no disco, mesmo quando `extractor.code` e
  `origin_step` são idênticos ao já escrito — e `_execute_extractor_script`
  (linhas 52-71) sempre spawna um `subprocess.run` novo (`sys.executable`, o
  interpretador do `.venv` do projeto). Nenhum cache de resultado por
  `(token_id, origin_step)` existe aqui.

- **`SessionStore`** (`session/session_store.py`):
  ```python
  def set_token(self, token_id: str, value: str) -> None:
      self.state.tokens[token_id] = value

  def render(self, template: str) -> str:
      return self.TOKEN_PLACEHOLDER_PATTERN.sub(self._resolve_token_placeholder, template)

  def _resolve_token_placeholder(self, match: Match[str]) -> str:
      token_id: str = match.group(1)
      if token_id not in self.state.tokens:
          return match.group(0)
      return self.state.tokens[token_id]
  ```
  `self.state.tokens` é o dicionário de valores **já resolvidos**, disjunto do
  `registry` (que guarda os `Extractor`, não os valores). Um `token_id` presente em
  `state.tokens` já tem um valor pronto para `render` — não precisa de nova chamada a
  `resolve_all()` para continuar tendo esse valor, porque nada reescreve
  `res_XXXX.json` depois de criado (seção 1).

- **`CandidateResolver._accept_persisted_slot`** (`tracking/candidate_resolver.py:120-123`):
  ```python
  def _accept_persisted_slot(self, slot_id: str, persisted: Extractor, result: str) -> None:
      self.session_store.state.registry[slot_id] = persisted
      self.session_store.set_token(slot_id, result)
      self._validated_values[slot_id] = result
  ```
  Quando um token é resolvido a partir de um extractor **já persistido em disco** de
  uma run anterior (reaproveitamento, spec `20260803 Reaproveitamento de
  Extractores`), `set_token` já é chamado aqui, na hora — o valor já está em
  `session_store.state.tokens` antes de `resolve_all()` rodar pela primeira vez para
  esse `token_id` no step atual.

- **`CandidateResolver._register_extractor`** (`candidate_resolver.py:150-162`):
  ```python
  def _register_extractor(self, candidate: DynamicToken, response_sample, initial_error=None) -> None:
      new_extractor: Optional[Extractor] = self._generate_extractor(candidate, response_sample, initial_error)
      if new_extractor is not None:
          self.session_store.state.registry[candidate.token_id] = new_extractor
          self.metadata_store.save(new_extractor)
          candidate.status = "Resolved"
      else:
          candidate.status = "Unresolved"
  ```
  Este é o **único** caminho que adiciona um `Extractor` ao `registry` sem chamar
  `set_token` — é exatamente por causa desse caminho (extractor **recém-gerado** via
  agente/LLM ou fallback literal, `_generate_extractor`, `candidate_resolver.py:175-201`)
  que `resolve_all()` continua sendo necessário em `main`: é o único jeito de popular
  `session_store.state.tokens` para um `token_id` que acabou de entrar no `registry`
  neste step.

- **Persistência de responses durante `run`/`dry`** (`engine.py:128-137`) — já
  documentado na spec anterior como append-only para os dois engines; esta spec
  confirma isso com leitura de `mitm_addon.py` e `curl_http_transport.py` (seção 1) —
  não há mais incerteza sobre captura assíncrona do proxy afetar `real_responses/`.

## 3. Decisões de arquitetura

### 3.1 `TokenResolver.resolve_all()` só reprocessa tokens ainda sem valor resolvido

Estado atual (`token_resolver.py:15-18`):
```python
def resolve_all(self) -> None:
    for token_id, extractor in self.session_store.state.registry.items():
        if self._should_refresh_token(extractor):
            self._refresh_token(token_id, extractor)
```

Estado esperado — novo parâmetro `force`, `False` por padrão:
```python
def resolve_all(self, force: bool = False) -> None:
    for token_id, extractor in self.session_store.state.registry.items():
        if not force and token_id in self.session_store.state.tokens:
            continue
        if self._should_refresh_token(extractor):
            self._refresh_token(token_id, extractor)
```

Os dois pontos de chamada de `resolve_all()` passam a se diferenciar:
- `Engine._process_entry` (chamada por step, `engine.py:110-111`) passa a chamar
  `self.token_resolver.resolve_all()` **sem argumento** (`force=False`, novo
  comportamento) — só processa tokens que ainda não estão em
  `session_store.state.tokens` (ou seja, os recém-adicionados ao `registry` neste
  step, seção 2, `_register_extractor`).
- `Engine.handle_recovery` (`engine.py:157`) passa a chamar
  `self.token_resolver.resolve_all(force=True)` — preserva **exatamente** o
  comportamento atual (reprocessa tudo, incondicional) na recuperação de 400/401.

Por que isso é seguro para `main`: um `token_id` já presente em
`session_store.state.tokens` só chegou lá por (a) `_accept_persisted_slot`
(`candidate_resolver.py:122`) ou (b) uma chamada anterior de `_refresh_token`
bem-sucedida (`token_resolver.py:34`) — em ambos os casos, o valor foi lido de
`res_{origin_step:04d}.json`, que a seção 1 confirma nunca é reescrito depois de
criado. Reexecutar o mesmo extractor sobre o mesmo arquivo produziria, de forma
determinística, o mesmo valor — pular essa reexecução não muda nenhum valor
observável em `session_store`, só remove trabalho redundante (subprocess +
reescrita do `.py` do extractor em `ExtractorRunner._write_extractor_script`,
`extractor_runner.py:31-42`).

Por que `handle_recovery` mantém `force=True`: dispara raramente (só em 400/401,
`retry_policy.RECOVERABLE_STATUS_CODES`, `step_retry_policy.py:8`) e o objetivo desta
spec é o overhead por-step que cresce com o histórico da run — o custo de um
`resolve_all(force=True)` ocasional na recuperação não é o problema relatado. Manter
o comportamento atual aqui elimina qualquer risco de mudança observável num caminho
que já lida com falha de autenticação/sessão, sem ganho relevante em troca (é
exatamente a mesma cautela que a spec anterior aplicou ao não tocar
`handle_recovery` para o `Ponto 1` original).

### 3.2 Nenhuma mudança em `DryEngine`

`DryEngine` (`dry_engine.py`) já não chama `resolve_all()` por step, desde a spec
anterior (`engine.py:110-111`, `if self.USES_NETWORK`). A mudança da seção 3.1 é
transparente para `dry`: como o `if self.USES_NETWORK` continua existindo e
`DryEngine.USES_NETWORK = False`, o `dry` continua sem nenhuma chamada por step,
`force=False` ou não. `handle_recovery` também não é alcançável em `dry`
(`DryEngine.execute_step` não usa `retry_policy`, `dry_engine.py:10-12`, spec
anterior seção 2) — o novo argumento `force=True` ali nunca é exercitado nesse
engine.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `TokenResolver.resolve_all` | novo parâmetro `force: bool = False`; quando `False`, pula `token_id` já presente em `session_store.state.tokens` antes de chamar `_should_refresh_token`/`_refresh_token` |
| `Engine._process_entry` | chamada a `self.token_resolver.resolve_all()` permanece condicionada a `if self.USES_NETWORK:` (inalterado desde a spec anterior), mas agora roda com `force=False` (comportamento padrão do novo parâmetro — nenhuma mudança de código nesse call site além do já existente) |
| `Engine.handle_recovery` | chamada a `self.token_resolver.resolve_all()` passa a ser `self.token_resolver.resolve_all(force=True)`, preservando o comportamento atual (reprocessa tudo) |

## 5. Casos de borda e comportamento de erro

- **Token recém-registrado via `_register_extractor` no step N**: não está em
  `session_store.state.tokens` ainda — `resolve_all()` (mesmo com `force=False`)
  processa normalmente, popula o valor, disponível para `render()` no mesmo step.
  Comportamento idêntico ao atual.
- **Token resolvido via `_accept_persisted_slot` (extractor reaproveitado de run
  anterior)**: já está em `session_store.state.tokens` no momento em que
  `resolve_all()` roda neste step — passa a ser pulado. Resultado observável idêntico
  (o valor já estava correto e presente), só evita uma reexecução redundante do
  extractor que `_check_persisted_slot` já rodou (`candidate_resolver.py:113`) para
  validar o slot.
- **`_refresh_token` que falhou silenciosamente numa chamada anterior** (exceção
  capturada em `token_resolver.py:29-31`, ou `res_{origin_step:04d}.json` inexistente,
  `token_resolver.py:24-25`): o `token_id` **não** entra em
  `session_store.state.tokens` nesse caso (só `_refresh_token` bem-sucedido chama
  `set_token`, linha 34) — então continua sendo reprocessado em todo step seguinte
  até ter sucesso ou a run terminar. Comportamento idêntico ao atual (a spec não muda
  a lógica de retry implícito de uma falha).
- **`handle_recovery` acionado (400/401) no meio da run**: `resolve_all(force=True)`
  reprocessa **todo** o registry, exatamente como hoje — nenhuma mudança observável
  nesse caminho.
- **HAR pequeno (poucos tokens dinâmicos)**: ganho da seção 3.1 é proporcionalmente
  pequeno (registry nunca cresce o suficiente para pesar), mas correto e sem custo de
  manutenção adicional — mesma lógica de "não é uma otimização condicionada a tamanho
  de HAR" já usada na spec anterior.
- **`--mode dry`**: nenhuma mudança de comportamento ou de custo — seção 3.2.

## 6. Referência

Implementação deve seguir `guia_de_estilo.md`: tipagem explícita em tudo (incluindo o
novo parâmetro `force: bool`), guard clauses, zero comentários/docstrings, e a
garantia de que nenhuma mudança desta spec altera qualquer valor resolvido em
`session_store.state.tokens` — só elimina reprocessamento cujo resultado já era
garantidamente idêntico ao anterior (seção 3.1).
