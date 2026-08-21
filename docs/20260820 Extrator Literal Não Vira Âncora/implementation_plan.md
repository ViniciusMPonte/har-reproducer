# Plano de Implementação — Extrator Literal Não Vira Âncora

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## Decisões dos pontos abertos da spec (§6)

Fechados aqui para que as tasks sejam executáveis; se algum estiver errado, é o momento de
dizer, porque as tasks o assumem:

1. **Nome do método:** `parse_anchors`. Fica em `CurlTokenComment`, que é o dono do formato.
2. **Cenário golden novo:** usa o **alvo 6 do fixture atual** (`synthetic_flow.har`), que é o
   único alvo que exercita o defeito hoje. **Não** entra fixture novo com cadeia mais longa —
   isso cobriria também "expansão transitiva atravessando um literal congelado", que é um caso
   que o fixture atual não produz, mas custaria uma task de fixture e um `run` a mais para
   cobrir um caminho que a mudança não distingue do já coberto.
3. **Teste do `optimize`:** **fica de fora.** Os dois testes atuais têm alvo 9, cujo schedule
   não muda (medido), e um teste novo de `optimize` custa uma execução lenta contra o servidor
   canned para exercitar uma mudança de custo, não de resultado. A mudança de regime do
   `optimize` está declarada na spec §3.5; se ela vier a incomodar, vira etapa própria.

## Nota de execução

Todas as tasks mexem em código coberto por testes rápidos (`tests/unit/`), exceto a T03, que
é `@pytest.mark.slow` e sobe o servidor canned. Rodar a suíte inteira com `--runslow` antes do
commit da T03.

---

## [T01] — `CurlTokenComment`: método que devolve só as dependências que ancoram

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/replay/curl_token_comment.py` (`CurlTokenComment`), `tests/unit/test_curl_token_comment.py`

**Contexto:**
`CurlTokenComment` é o dono do formato dos comentários do `.curl.sh`. Ele já sabe escrever a
linha de dependência com frases de status (`format_dependency_line`), já sabe separar a
cláusula do sufixo (`_split_clause_and_status`) e já sabe classificar cada frase do sufixo em
`OriginStatusPhrase` ou `ReplayStatusPhrase` (`_categorize`). O que não existe é uma leitura
que devolva **só** as dependências cujo extrator é recalculável — hoje `parse` devolve todas,
descartando o sufixo, e é isso que faz o schedule do `replay --mode smart` ancorar em step de
origem de extrator literal congelado.

Esta task só **acrescenta** a leitura nova. Nada passa a usá-la ainda (isso é a T02), então
nenhum comportamento observável muda.

**Estado atual:**
- `parse(curl_text)` (`:66-70`) usa `DEPENDENCY_PATTERN.finditer` sobre o texto inteiro e
  devolve `{token_id: origin_step}` de **toda** linha de dependência, sem olhar o sufixo:
  ```python
  def parse(self, curl_text: str) -> Dict[str, int]:
      return {
          match.group("token_id"): int(match.group("origin_step"))
          for match in self.DEPENDENCY_PATTERN.finditer(curl_text)
      }
  ```
- `_split_clause_and_status` (`:72-76`) devolve `(cláusula, texto_do_sufixo)` cortando no
  primeiro `CLAUSE_CLOSING_MARKER` (`"]"`).
- `_categorize` (`:78-88`) quebra o sufixo por `CATEGORY_SEPARATOR` (`"; "`) e devolve a tupla
  `(OriginStatusPhrase | None, ReplayStatusPhrase | None)`.
- Não existe nenhum método que filtre dependências por tipo de extrator.

**Estado esperado depois:**
- Método público novo `parse_anchors(curl_text: str) -> Dict[str, int]`, que devolve as
  dependências cuja linha **não** carrega nenhuma `OriginStatusPhrase`.
- Implementação: itera as linhas do texto; para cada linha que casa `DEPENDENCY_PATTERN`,
  chama `_split_clause_and_status` e `_categorize`; inclui a dependência no resultado só
  quando a parte `OriginStatusPhrase` da classificação é `None`.
- `parse` **não muda** — continua devolvendo todas as dependências, porque
  `ReplayTokenResolver` depende disso (spec §3.4).
- ⚠️ **Iterar linha a linha, não `finditer` sobre o texto inteiro.** `DEPENDENCY_PATTERN` é
  `re.MULTILINE` e casa no início da linha; para olhar o sufixo é preciso ter a linha isolada.
- ⚠️ **`ReplayStatusPhrase` NÃO exclui a dependência.** `probably static` e
  `could not extract value from response, using captured value` são observações do replay
  sobre um extrator que pode ser perfeitamente recalculável. Testar "o sufixo está vazio"
  seria errado — é por isso que a implementação usa `_categorize`, que separa as duas
  categorias, em vez de olhar o sufixo cru.
- ⚠️ Uma linha pode carregar **as duas** frases, na ordem `origin_status; replay_status`
  (`_compose`, `:103-109`), e é a forma que aparece depois de um replay.
- ⚠️ A regra é "qualquer `OriginStatusPhrase` exclui", derivada do enum e não de uma lista
  literal de frases. Vale escrever um comentário curto junto do enum registrando a invariante:
  toda `OriginStatusPhrase` existente significa "caiu para literal", e uma frase de origem
  futura que **não** signifique isso quebraria esta leitura em silêncio.

**Critérios de aceite:**
- [ ] `parse_anchors` de um texto com `# [Token abc comes from response of step 0002]` (sem
      sufixo) devolve `{"abc": 2}`.
- [ ] `parse_anchors` de uma linha com `OriginStatusPhrase.UNDETERMINED` no sufixo devolve
      `{}`.
- [ ] `parse_anchors` de uma linha com `OriginStatusPhrase.EXTRACTION_EXHAUSTED` no sufixo
      devolve `{}`.
- [ ] `parse_anchors` de uma linha com **só** `ReplayStatusPhrase.PROBABLY_STATIC` no sufixo
      devolve a dependência (é extrator recalculável que o replay observou estável).
- [ ] `parse_anchors` de uma linha com as duas frases
      (`origin location undetermined …; probably static`, construída com
      `format_dependency_line` + `with_replay_status`) devolve `{}`.
- [ ] `parse_anchors` de um texto com várias linhas, mistas, devolve exatamente as
      recalculáveis — inclusive quando a linha de literal vem antes da recalculável.
- [ ] `parse_anchors` de um curl sem nenhuma linha de dependência devolve `{}`.
- [ ] Garantia de não-regressão: `parse` continua devolvendo **todas** as dependências nos
      mesmos textos acima, e os testes existentes de `tests/unit/test_curl_token_comment.py`
      passam sem alteração.

---

## [T02] — `ReplayRunner._expand_pending`: expandir o schedule só pelo que ancora

**Depende de:** T01 (o método que esta task passa a chamar).
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py` (`ReplayRunner._expand_pending`), `tests/unit/test_replay_runner.py`

**Contexto:**
`compute_smart_schedule` parte do alvo e expande transitivamente pelas dependências de cada
curl que já está no schedule. Como ele usa `parse`, que devolve toda linha de dependência,
um extrator literal congelado — cujo código é `return '<valor>'` e que devolve o mesmo valor
independentemente de qual resposta esteja em disco — arrasta seu step de origem para o
replay. Medido no workspace de referência: 96% das 254 linhas de dependência são desse tipo, e
213 dos 320 alvos possíveis têm o schedule inflado por isso.

**Estado atual:**
```python
def _expand_pending(
        self, current: int, floor: int, existing_set: Set[int], schedule: Set[int], pending: Set[int]
) -> None:
    curl_text: str = self.workspace.curl_file(current).read_text(encoding="utf-8")
    dependencies: Dict[str, int] = self.curl_token_comment.parse(curl_text)
    for origin_step in dependencies.values():
        if origin_step >= floor and origin_step not in schedule and origin_step in existing_set:
            schedule.add(origin_step)
            pending.add(origin_step)
```
- `test_compute_smart_schedule_expands_through_dependency_chain` (`tests/unit/test_replay_runner.py:85-98`)
  cobre a expansão por uma linha sem sufixo.
- `test_compute_smart_schedule_still_expands_after_dependency_annotated_as_static` (`:100-114`)
  cobre que uma linha anotada com `ReplayStatusPhrase.PROBABLY_STATIC` **continua** ancorando.
  É a garantia de não-regressão mais importante desta task.

**Estado esperado depois:**
- A linha `dependencies = self.curl_token_comment.parse(curl_text)` passa a chamar
  `parse_anchors`. **Nada mais muda** em `_expand_pending` nem em `compute_smart_schedule`: o
  piso `--from`, o teste `origin_step in existing_set` e a expansão transitiva continuam
  idênticos.
- ⚠️ Não trocar `parse` por `parse_anchors` em nenhum outro lugar. `ReplayTokenResolver.resolve`
  (`replay/replay_token_resolver.py:33`) precisa do step de origem de **todo** token, inclusive
  dos literais, para escolher o diretório de resposta; trocar lá faria o token literal cair em
  `_fallback_to_captured` com aviso no stdout, entregando o mesmo valor com mais ruído (spec
  §3.4).
- ⚠️ `--mode all`, `--mode slice` e `--mode list` não passam por aqui e não mudam.

**Critérios de aceite:**
- [ ] Com `curl_file(2)` sem dependências e `curl_file(5)` contendo
      `format_dependency_line("abc", 2, OriginStatusPhrase.UNDETERMINED)`,
      `compute_smart_schedule(None, 5)` devolve schedule `{5}` — hoje devolve `{2, 5}`.
- [ ] Idem com `OriginStatusPhrase.EXTRACTION_EXHAUSTED`: schedule `{5}`.
- [ ] Cadeia transitiva atravessando um literal: `curl_file(9)` depende de `5` por linha
      recalculável e `curl_file(5)` depende de `2` por linha de literal →
      `compute_smart_schedule(None, 9)` devolve `{5, 9}` (entra o 5, não entra o 2).
- [ ] Não-regressão: `test_compute_smart_schedule_expands_through_dependency_chain` continua
      passando (linha sem sufixo ancora).
- [ ] Não-regressão: `test_compute_smart_schedule_still_expands_after_dependency_annotated_as_static`
      continua passando — dependência anotada só com `probably static` **continua** ancorando.
- [ ] Não-regressão: `pytest tests/unit -q` verde, e os 27 cenários golden passam
      byte-idênticos (`pytest --runslow -q`), conforme medido na spec §5.1.

---

## [T03] — Cenário golden de `replay --mode smart` que exercita o defeito

**Depende de:** T02 (antes dela o cenário não pode ser gravado, porque o comportamento é o antigo).
**Arquivos envolvidos:** `tests/test_cli_replay.py` (teste novo), `tests/golden/replay_smart_to_6/` (árvore de referência nova)

**Contexto:**
Medido, **nenhum dos 27 cenários golden exercita o defeito que esta etapa corrige**: o fixture
`tests/fixtures/synthetic_flow.har` produz exatamente uma linha de dependência de extrator
literal congelado — em `req_0006.curl.sh`, token `LiteralAgent` com origem no step 5 (valor
`PLAINVAL777`) — e os três cenários de smart existentes têm alvo 9, 4 e 9, nenhum passando
pelo step 6. Por isso os 27 passam byte-idênticos depois da T02, e por isso a cobertura nova
é o coração desta etapa e não um acessório: sem ela, nada em `tests/` distingue o antes do
depois no caminho ponta a ponta.

**Estado atual:**
- `tests/test_cli_replay.py` tem `test_replay_smart_noflag` (`:151-168`, alvo implícito 9),
  `test_replay_smart_to_4` (`:172-189`) e `test_replay_smart_from_3` (`:192-209`), todos no
  mesmo formato: `ReplayScenario(...).run([...])`, asserções de comportamento
  (`scenario.executed_steps(result.stdout)`), gravação de `stdout.txt` no workspace e
  `golden_workspace_factory.create(...).assert_matches(golden_dir / "<nome>")`.
- Não existe cenário com alvo 6.

**Estado esperado depois:**
- Teste novo `test_replay_smart_to_6`, marcado `@pytest.mark.slow`, no mesmo formato dos três
  existentes, rodando `["--mode", "smart", "--to", "6"]`.
- Asserção central: `scenario.executed_steps(result.stdout) == [6]`. **Antes da T02 este teste
  falha com `[5, 6]`** — é ele que demonstra a etapa.
- Árvore de referência `tests/golden/replay_smart_to_6/` gravada com
  `HAR_REPRODUCER_UPDATE_GOLDEN=1` **depois** de a T02 estar aplicada, e conferida à mão antes
  do commit: o `stdout.txt` tem que mostrar só o step 6 executado, e o diretório `replays/`
  tem que conter uma única execução.
- ⚠️ Gravar o golden com o comportamento antigo e "corrigir depois" está proibido: a árvore de
  referência não deve nunca registrar o defeito.
- ⚠️ Manter as mesmas asserções auxiliares dos cenários vizinhos —
  `"Replay Validation Result: ✓ SUCCESS" in result.stdout`,
  `len(scenario.replay_run_dirs()) == 1` e
  `TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)` — para o cenário
  novo não ser mais fraco que os que já existem.
- ⚠️ O step 6 do fixture consome o token literal com origem no step 5. Com a T02 aplicada, o
  step 5 **não** roda, então o extrator literal é executado com o diretório de referência do
  replay e devolve o literal do mesmo jeito. Se o stdout do cenário trouxer aviso de
  `could not be dynamically resolved`, é sinal de que a spec §3.4 foi violada em algum lugar
  (alguém trocou `parse` por `parse_anchors` no `ReplayTokenResolver`) — checar antes de
  gravar o golden.

**Critérios de aceite:**
- [ ] `test_replay_smart_to_6` passa com a T02 aplicada e falha sem ela (verificável com
      `git stash` da T02, ou conferindo que a asserção é `== [6]`).
- [ ] `scenario.executed_steps(result.stdout) == [6]`.
- [ ] `tests/golden/replay_smart_to_6/stdout.txt` mostra exatamente um `Step 6 completed`, e
      nenhum `Step 5 completed`.
- [ ] O stdout do cenário **não** contém `could not be dynamically resolved during replay`.
- [ ] Não-regressão: `pytest --runslow -q` verde, com os 27 cenários golden anteriores
      byte-idênticos (nenhum deles usa o alvo 6).
