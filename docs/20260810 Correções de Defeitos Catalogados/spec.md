# Spec — Item 9: Token irresolvível interpola placeholder cru no `curl`, mas `replay` reporta sucesso mesmo assim

> Fonte: `lista_de_bugs.md` item 9 (dois defeitos, ambos "ainda existem"). Origem
> primária: `docs/20260806 Rede de Caracterização Golden/spec.md` §6.9.
> Os itens 1–6 já foram corrigidos nesta branch; esta spec cobre só o item 9.

## 1. Objetivo

O item 9 cataloga dois defeitos do comando `replay`:

1. **9a — token irresolvível degrada silenciosamente para texto literal cru.**
   `ReplayTokenResolver._resolve_one` (`har_reproducer/replay/replay_token_resolver.py:55-58`)
   retorna `False` quando o extrator não produz valor; `SessionStore.render`
   (`har_reproducer/session/session_store.py:22-26`) devolve o placeholder cru
   `{{extractor:...}}` no curl, e o curl quebra com `curl: (3) nested brace in URL`
   (`status_code: 0`) — o `test_replay_list_out_of_order` (`tests/test_cli_replay.py:232-236`)
   congelou exatamente esse sintoma.
2. **9b — o veredito final ignora o status dos steps intermediários.**
   `ReplayRunner._run_schedule` (`har_reproducer/replay/replay_runner.py:62-77`)
   roda todos os steps do schedule (o fluxo já vai até o fim), mas compara **apenas o
   último** com a resposta original (`ReplayResultComparator.matches_original`,
   `har_reproducer/replay/replay_result_comparator.py:15-24`) e imprime `✓ SUCCESS`
   mesmo com um step quebrado no meio do caminho.

A proposta, alinhada ao princípio de genericidade do projeto ("extrator literal como
fallback, não como padrão"): **nenhum token deve ficar sem solução no replay** — se a
extração dinâmica falha, o valor capturado no HAR original é passado de forma
**estática** (a mesma ideia de `LiteralAgent`/`LiteralFallbackAgent` do caminho de
`run`, `har_reproducer/tracking/candidate_resolver.py:176-187`). E o fluxo **sempre
chega ao fim** (o objetivo é a última requisição), mas o veredito final passa a
**informar quais steps falharam** em comparação às respostas originais e a refletir
steps que quebraram no meio do caminho.

Escopo: os dois defeitos (9a + 9b) no pipeline de `replay`. Fica **fora**:
- Itens 2 e 8 (persistência do `.py` do extrator em `dry` e o exemplo de README) —
  já tratados nesta branch (fix do item 2: commit `4d5869f`; lacunas de teste
  documentadas em `lacunas_de_testes.md`).
- Itens 5, 6, 10 da lista (código morto, nomes que mentem, acoplamento
  nome-de-classe↔`AgentType`).
- Mudança de semântica do `Validator` do `run` (`success_criteria`) — escopo do replay.
- Reordenar o schedule em modo `list` fora de ordem: o fluxo segue a ordem dada e o
  reporte aponta a divergência, mas não reordena steps.

## 2. Componentes existentes reaproveitados (estado atual)

### 2.1 `Extractor` — `har_reproducer/models/session.py:26-35`

```python
class Extractor(BaseModel):
    token_id: str
    code: str
    verified: bool = False
    agent_type: AgentType
    origin_step: Optional[int] = None
    temp_file_path: Optional[str] = None
    valid_count: int = 0
    last_value: Optional[str] = None
    ever_changed: bool = False
```

- Não persiste o **valor capturado** (o literal do HAR na posição do token).
  `last_value` é observação de replay (atualizado por `ReplayTokenResolver._record_observation`,
  `replay_token_resolver.py:74-83`) e pode ser `None` num workspace que nunca
  reexecutou o replay.
- `model_dump_json()` serializa campos `None` explicitamente (os `.meta.json` no
  golden mostram `"last_value": null`) — um campo novo aparece em todos os metas.

### 2.2 `CandidateResolver` — `har_reproducer/tracking/candidate_resolver.py`

- `_register_extractor` (`:145-157`) registra no `session_store.registry` e persiste
  via `metadata_store.save(new_extractor)` — é o ponto único onde todo extrator novo
  nasce (seja de um `Agent` dinâmico, seja `LiteralAgent`/`LiteralFallbackAgent`).
- `_accept_persisted_slot` (`:115-118`) aceita um extrator persistido (slot `MATCH`)
  e seta o token no `SessionStore`.
- `_build_literal_extractor` (`:190-197`) já embute o literal no `code`
  (`return {candidate.current_value!r}`) — o mesmo `candidate.current_value` que esta
  spec passa a persistir como `captured_value`.

### 2.3 `ReplayTokenResolver` — `har_reproducer/replay/replay_token_resolver.py`

```python
def _resolve_one(self, token_id, dependencies, schedule, replay_run_dir, res_refer_dir, original_responses_dir) -> bool:
    origin_step: Optional[int] = dependencies.get(token_id)
    if origin_step in schedule:
        override_dir: Path = replay_run_dir
    else:
        override_dir = self._reference_dir_for_step(origin_step, res_refer_dir, original_responses_dir)
    value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
    if value is None:
        print(f"Failed to resolve token '{token_id}' during replay: extractor returned no value.")
        return False
    self.session_store.set_token(token_id, value)
    return self._record_observation(token_id, value)
```

- `resolve` (`:25-39`) extrai os `token_id` do curl via
  `SessionStore.TOKEN_PLACEHOLDER_PATTERN` e itera `_resolve_one`; o retorno
  (`Set[str]` de tokens "provavelmente estáticos") alimenta a anotação
  ` - probably static` em `ReplayRunner._annotate_static_tokens`
  (`replay_runner.py:104-121`).
- `_reference_dir_for_step` (`:62-72`) decide entre `replay_run_dir` (origem no
  schedule, resposta fresca) e `res_refer_dir`/`original_responses_dir` (origem fora
  do schedule, resposta de referência).

### 2.4 `SessionStore.render` — `har_reproducer/session/session_store.py:18-26`

`_resolve_token_placeholder` (`:22-26`) devolve `match.group(0)` (o placeholder cru)
quando o token não está no `state.tokens` — é o que vira `curl: (3) nested brace`.

### 2.5 `ReplayRunner._run_schedule` — `har_reproducer/replay/replay_runner.py:62-77`

```python
last_index: int = ordered_indexes[0]
last_response: StepResponse = self._run_step(last_index, schedule)
for index in ordered_indexes[1:]:
    last_response = self._run_step(index, schedule)
    last_index = index

is_match: bool = self.comparator.matches_original(last_index, last_response)
print(
    f"\nReplay Validation Result: {'✓ SUCCESS' if is_match else '✗ MISMATCH'} "
    f"(step {last_index} status code vs. original)"
)
return is_match
```

- `_run_step` (`:79-102`) resolve tokens, renderiza, envia, aplica
  `StepRetryPolicy`, persiste a resposta no `replay_run_dir` e imprime
  `Step N completed with status X`.

### 2.6 `ReplayResultComparator` — `har_reproducer/replay/replay_result_comparator.py:15-24`

`matches_original(index, response)` lê a referência (`real_responses/` ou
`original_responses/`, via `_read_reference_text` `:26-36`), extrai o
`"status_code"` com regex e devolve `bool`. Não expõe o status original para o
relatório.

## 3. Decisões de arquitetura

### 3.1 Persistir o valor capturado no `Extractor` (`captured_value`)

Para que o fallback estático do §3.2 exista no replay, o valor capturado tem que
estar **no disco no momento do replay** — e hoje não está: o curl só tem o
placeholder (o literal original não é gravado em lugar nenhum para tokens
dinâmicos; o `.meta.json` do golden de `replay_list_out_of_order` mostra
`"last_value": null` para o token `ade6a...`). A geração de `run` é o único lugar
que conhece `candidate.current_value`.

Estado atual — `models/session.py:26-35` (sem o campo):

```python
class Extractor(BaseModel):
    token_id: str
    code: str
    verified: bool = False
    agent_type: AgentType
    origin_step: Optional[int] = None
    temp_file_path: Optional[str] = None
    valid_count: int = 0
    last_value: Optional[str] = None
    ever_changed: bool = False
```

Estado esperado — novo campo `captured_value`:

```python
class Extractor(BaseModel):
    token_id: str
    code: str
    verified: bool = False
    agent_type: AgentType
    origin_step: Optional[int] = None
    temp_file_path: Optional[str] = None
    valid_count: int = 0
    last_value: Optional[str] = None
    ever_changed: bool = False
    captured_value: Optional[str] = None
```

População (em `tracking/candidate_resolver.py`):

1. **Extratores novos** — em `_register_extractor` (`:145-157`), antes do
   `metadata_store.save(new_extractor)`:
   ```python
   new_extractor.captured_value = candidate.current_value
   ```
   Isso cobre os dois caminhos de `_generate_extractor` (`:170-187`): o extrator do
   `Agent` dinâmico e o `LiteralAgent`/`LiteralFallbackAgent` (que passa por
   `_build_literal_extractor`, `:190-197`, onde o literal já está no `code` — o
   campo passa a guardá-lo também explicitamente).
2. **Extratores reaproveitados** — em `_accept_persisted_slot` (`:115-118`), quando
   `persisted.captured_value is None`, fazer backfill com o valor aceito e persistir:
   ```python
   if persisted.captured_value is None:
       persisted.captured_value = result
       self.metadata_store.save(persisted)
   ```
   Em `MATCH` vale `result == candidate.current_value`, então o backfill é exato.
   Isso faz um `run` (inclusive `dry`) sobre um workspace antigo popular o campo nos
   reuses — sem exigir regenerar extratores.

Racional: um campo por extrator, junto do dado que ele já descreve, é o mesmo padrão
de `last_value`/`valid_count`. Alternativa descartada: derivar o literal do `code`
com `ast.literal_eval` — só funciona para extractores literais, é frágil com aspas
no valor, e não resolve tokens dinâmicos (o caso do golden `ade6a...`, um
`JSONPathAgent`).

### 3.2 Fallback estático no replay quando a extração não produz valor

Estado atual — `replay/replay_token_resolver.py:50-60`:

```python
value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
if value is None:
    print(f"Failed to resolve token '{token_id}' during replay: extractor returned no value.")
    return False
self.session_store.set_token(token_id, value)
return self._record_observation(token_id, value)
```

Estado esperado — quando `run_existing` devolve `None`, cair para o valor capturado
antes de desistir. O desfecho de cada token passa a ser um **status explícito**: o
`bool` de hoje não distingue "extração dinâmica sem confirmação estática" de
"fallback usado" — distinção que o §3.4 precisa para anotar o curl.

```python
class TokenResolutionStatus(str, Enum):
    STATIC = "static"
    RESOLVED = "resolved"
    CAPTURED_FALLBACK = "captured_fallback"
    UNRESOLVED = "unresolved"
```

`_resolve_one`:

```python
value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
if value is None:
    return self._fallback_to_captured(token_id)
self.session_store.set_token(token_id, value)
return (
    TokenResolutionStatus.STATIC
    if self._record_observation(token_id, value)
    else TokenResolutionStatus.RESOLVED
)
```

Método novo:

```python
def _fallback_to_captured(self, token_id: str) -> TokenResolutionStatus:
    persisted: Optional[Extractor] = self.metadata_store.load(token_id)
    if persisted is not None and persisted.captured_value is not None:
        self.session_store.set_token(token_id, persisted.captured_value)
        print(
            f"Token '{token_id}' could not be dynamically resolved during replay; "
            f"using captured value instead."
        )
        return TokenResolutionStatus.CAPTURED_FALLBACK
    print(
        f"Failed to resolve token '{token_id}' during replay: "
        f"extractor returned no value and no captured value is available."
    )
    return TokenResolutionStatus.UNRESOLVED
```

Semântica do desfecho:

- `STATIC` — extração dinâmica **e** confirmação estática (`_record_observation`
  chegou ao threshold); anota o curl com ` - probably static`.
- `RESOLVED` — extração dinâmica sem confirmação estática; sem anotação.
- `CAPTURED_FALLBACK` — fallback com `captured_value`; o curl é anotado (§3.4) e
  `_record_observation` **não** roda (o maquinário `valid_count`/`last_value`/
  `ever_changed` fica intocado por resoluções degradadas).
- `UNRESOLVED` — falha total: placeholder cru → `curl: (3) nested brace` → `status 0`.

`resolve` passa a devolver `Tuple[Set[str], Set[str]]` — `(static_token_ids,
fallback_token_ids)` — para o runner anotar os dois conjuntos (§3.4):

```python
def resolve(self, ...) -> Tuple[Set[str], Set[str]]:
    dependencies: Dict[str, int] = self.dependency_parser.parse(curl_text)
    token_ids: Set[str] = set(SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text))
    static_token_ids: Set[str] = set()
    fallback_token_ids: Set[str] = set()
    for token_id in token_ids:
        status: TokenResolutionStatus = self._resolve_one(
            token_id, dependencies, schedule, replay_run_dir, res_refer_dir, original_responses_dir
        )
        if status is TokenResolutionStatus.STATIC:
            static_token_ids.add(token_id)
        elif status is TokenResolutionStatus.CAPTURED_FALLBACK:
            fallback_token_ids.add(token_id)
    return static_token_ids, fallback_token_ids
```

A mensagem de falha total mantém o prefixo `Failed to resolve token '<id>' during
replay:` — é o padrão que `tests/support/token_failure_guard.py:7` monitora.

### 3.3 Relatório por step e veredito híbrido no `ReplayRunner._run_schedule`

Estado atual — `replay/replay_runner.py:62-77` (fluxo já vai até o fim; compara só o
último). Estado esperado: roda todos os steps (inalterado), coleta o resultado de
cada um e imprime um bloco final de reporte + veredito.

```python
def _run_schedule(self, ordered_indexes: List[int], schedule: Set[int]) -> bool:
    if not ordered_indexes:
        raise ValueError("ReplayRunner: schedule vazio — nenhum step para processar.")

    results: List[Tuple[int, StepResponse, bool]] = []
    for index in ordered_indexes:
        response: StepResponse = self._run_step(index, schedule)
        results.append((index, response, self.comparator.matches_original(index, response)))

    self._print_step_report(results)

    target_index: int = results[-1][0]
    target_matched: bool = results[-1][2]
    intermediate_broken: bool = any(response.status_code == 0 for _, response, _ in results[:-1])
    is_match: bool = target_matched and not intermediate_broken
    failed_steps: List[int] = [index for index, _, matched in results if not matched]

    print(
        f"\nReplay Validation Result: {'✓ SUCCESS' if is_match else '✗ FAILURE'}"
        f"{' (step ' + str(target_index) + ' status code vs. original)' if is_match else ' (steps diverged: ' + ', '.join(str(s) for s in failed_steps) + ')'}"
    )
    return is_match
```

Método novo `_print_step_report` — imprime o status de cada step em ordem de
execução, comparado com a resposta original:

```
Replay step results:
  Step 4: ✓ matched (200 vs original 200)
  Step 3: ✓ matched (200 vs original 200)

Replay Validation Result: ✓ SUCCESS (step 3 status code vs. original)
```

Para comparação, `ReplayResultComparator` ganha um método que expõe o status
original sem repetir o parse:

```python
def original_status_code(self, index: int) -> Optional[int]:
    original_text: Optional[str] = self._read_reference_text(index)
    if original_text is None:
        return None
    match: Optional[Match[str]] = self.STATUS_CODE_PATTERN.search(original_text)
    if match is None:
        return None
    return int(match.group(1))

def matches_original(self, index: int, response: StepResponse) -> bool:
    original: Optional[int] = self.original_status_code(index)
    if original is None:
        print(f"Could not find status_code in original response for step {index} to compare.")
        return False
    return original == response.status_code
```

(`matches_original` continua devolvendo `False` quando não há referência/status — os
testes existentes de `tests/unit/test_replay_result_comparator.py` seguem verdes.)

Veredito híbrido (decisão confirmada pelo usuário):

> `✓ SUCCESS` **só se** o último step (target) casar com a resposta original **e**
> nenhum step intermediário "quebrou" (`status_code == 0`). Divergência de status em
> step intermediário (ex.: `404` vs `200`) é reportada no bloco `Replay step
> results:` mas **não derruba** o veredito — o objetivo do replay é a última
> requisição.

A linha do veredito preserva o prefixo `Replay Validation Result: ✓ SUCCESS` /
`✗ FAILURE`, que o `test_cli_replay.py` e o golden `stdout.txt` comparam.

### 3.4 Anotar no curl em disco que o valor não foi extraído do response

Ao cair no fallback, o **comentário do extrator no `.curl.sh` em disco** ganha um
sufixo explícito informando que a extração do response falhou e o valor capturado
foi usado (decisão do usuário). O placeholder em si permanece no arquivo — só a
versão renderizada (enviada) é substituída; a anotação é o registro persistente do
que aconteceu naquela rodada e não altera o comportamento do curl (é só comentário).

Estado atual — `ReplayRunner._run_step` (`replay_runner.py:79-102`) anota apenas os
tokens estáticos, via `static_token_ids` que `ReplayTokenResolver.resolve` devolve
(`:25-39`). Como o fallback não é `STATIC`, o §3.2 já fez `resolve` devolver também
`fallback_token_ids`. Estado esperado — `_run_step` anota os dois conjuntos com
sufixos distintos:

```python
static_token_ids: Set[str]
fallback_token_ids: Set[str]
static_token_ids, fallback_token_ids = self.replay_token_resolver.resolve(
    curl_text, schedule, replay_run_dir, res_refer_dir, original_responses_dir,
)
if static_token_ids:
    self._annotate_static_tokens(index, static_token_ids)
if fallback_token_ids:
    self._annotate_fallback_tokens(index, fallback_token_ids)
```

Sufixo novo (ao lado de `STATIC_WARNING_SUFFIX = " - probably static"`):

```python
CAPTURED_FALLBACK_SUFFIX: ClassVar[str] = " - could not extract value from response, using captured value"
```

O comentário final fica, por exemplo:

```
# Token ade6a53080262635799eb7ec66e824e8 comes from response of step 3 - could not extract value from response, using captured value
```

A anotação é generalizada: a lógica de `_mark_token_static`
(`replay_runner.py:106-118`) vira `_mark_token(text, token_id, suffix)`, e
`_annotate_static_tokens`/`_annotate_fallback_tokens` chamam o mesmo helper com o
sufixo respectivo. Mantém-se a idempotência (não duplicar o sufixo se o token já
está anotado em reruns do replay).

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `Extractor` (`models/session.py:26-35`) | Novo campo `captured_value: Optional[str] = None` |
| `CandidateResolver` (`tracking/candidate_resolver.py:145-157`, `:115-118`) | `_register_extractor` seta `captured_value = candidate.current_value`; `_accept_persisted_slot` faz backfill quando `None` |
| `ReplayTokenResolver` (`replay/replay_token_resolver.py:50-60`) | Novo `_fallback_to_captured`; `_resolve_one` devolve `TokenResolutionStatus`; `resolve` devolve `Tuple[Set[str], Set[str]]` (static, fallback) |
| `ReplayResultComparator` (`replay/replay_result_comparator.py:15-24`) | Novo `original_status_code`; `matches_original` delega para ele |
| `ReplayRunner._run_schedule` + `_run_step` (`replay/replay_runner.py:62-77`, `:79-102`) | Coleta `(index, response, matched)` por step; novo `_print_step_report`; veredito híbrido (target casa **e** nenhum intermediário `status_code == 0`); `_mark_token_static` vira `_mark_token(text, token_id, suffix)`; novo `_annotate_fallback_tokens` + `CAPTURED_FALLBACK_SUFFIX` |
| `tests/unit/test_replay_token_resolver.py` | Novos testes de fallback (com/sem `captured_value`) e de `TokenResolutionStatus`/`resolve` |
| `tests/unit/test_replay_runner.py` | Novos testes do veredito híbrido (intermediário quebrado, mismatch suave, tudo ok) e da anotação `CAPTURED_FALLBACK_SUFFIX`/idempotência |
| `tests/unit/test_candidate_resolver.py` | Testes de `captured_value` na geração e no backfill de reuse |
| `tests/unit/test_replay_result_comparator.py` | Teste de `original_status_code` |
| `tests/test_cli_replay.py` + `tests/golden/replay_list_out_of_order/` | Atualizar asserts do `test_replay_list_out_of_order` (some `nested brace`/`status 0`; step 4 casa via fallback); regenerar golden |
| Golden (metas de extractor) | Todos os `.meta.json` ganham `"captured_value": ...` — regeneração com `HAR_REPRODUCER_UPDATE_GOLDEN=1` e revisão do diff |

## 5. Casos de borda e comportamento de erro

| # | Caso | Comportamento esperado |
|---|---|---|
| 1 | Extrator falha no replay e `captured_value` existe | Fallback: token setado com o literal capturado, warning impresso, curl bem-formado, `_record_observation` **não** roda, sem anotação `probably static`, **com** sufixo ` - could not extract value from response, using captured value` no comentário do curl |
| 2 | Extrator falha e `captured_value` é `None` (workspace anterior ao fix, sem rerun) | `Failed to resolve token ...` (prefixo preservado), placeholder cru → `curl: (3) nested brace` → `status 0`; reporte aponta o step |
| 3 | Schedule fora de ordem (`--mode list` `[4, 3]`, token do step 4 originado no step 3) | No momento do step 4 a resposta do step 3 ainda não existe no `replay_run_dir` → extrator devolve `None` → fallback com o valor capturado; o step sai bem-formado e o reporte decide (no cenário golden, `GET /item/4242` casa → `SUCCESS`, com o warning do fallback no stdout) |
| 4 | Step intermediário com `status_code == 0` | Veredito `✗ FAILURE` mesmo que o target case — é o "quebrou" do híbrido |
| 5 | Step intermediário com mismatch suave de status (`404` vs `200`) | Reportado no bloco `Replay step results:`; veredito continua `✓ SUCCESS` se o target casar |
| 6 | Target (último step) com mismatch ou `status 0` | `target_matched = False` → `✗ FAILURE` |
| 7 | Schedule de um step só | `results[:-1]` vazio → veredito = `matches_original` do próprio step (mesmo comportamento de hoje) |
| 8 | Sem referência para um step (nem `real_responses/` nem `original_responses/`) | `original_status_code` → `None`; linha do step vira `✗ MISMATCH` e entra em `steps diverged` |
| 9 | Extrator literal (`LiteralAgent`/`LiteralFallbackAgent`) em workspace `main` | `.py` existe e roda (devolve a constante) → caminho dinâmico normal, sem fallback |
| 10 | `Extractor.model_dump_json` serializa o campo novo | Todos os `.meta.json` existentes (88 no golden) mudam — regeneração prevista no plano |
| 11 | Replay roda de novo sobre o mesmo workspace (rerun) | Sufixo do fallback não é duplicado no comentário (`_mark_token` idempotente); placeholder permanece e a versão renderizada volta a ser resolvida |
| 12 | Fallback de token que **também** é static confirmado em rodada anterior | `_record_observation` não roda no fallback (maquinário de confirmação intocado), mas o token não volta a ser `STATIC` nesta rodada — a anotação reflete só o desfecho atual |

## 6. Suposições e pontos a confirmar

1. **Veredito híbrido** (confirmado pelo usuário): `✓ SUCCESS` exige target casado
   **e** nenhum intermediário com `status_code == 0`; mismatch suave de intermediário
   não derruba. O fluxo sempre vai até o fim.
2. **Fallback usa sempre o valor capturado no HAR original**, mesmo para tokens
   dinâmicos — é obsoleto por natureza (o valor pode ter mudado no servidor). O
   warning imprime o `token_id`, não o valor (pode ser credencial); a divergência
   aparece no reporte de status e, **de forma persistente**, no sufixo do comentário
   do curl (§3.4) — a anotação deixa explícito que aquele valor não veio do response
   daquela rodada. Alternativa descartada: tentar a resposta de referência
   (`res_refer_dir`/`original_responses_dir`) antes do fallback estático quando a
   origem está no schedule — é mais máquina para o mesmo desfecho do caso 3 da
   tabela acima e depende de diretórios que podem estar vazios.
3. **Workspaces criados antes do fix** só ganham `captured_value` quando o mesmo HAR
   rodar de novo (backfill em `_accept_persisted_slot`). Sem rerun, o caso 2 da
   tabela acima se aplica (falha clara, reportada) — limitação aceita, não um
   caminho silencioso.
4. **`matches_original` segue retornando `bool`** com a mesma semântica dos testes
   existentes; `original_status_code` é adição não-destrutiva.
5. **Golden**: a mensagem exata do veredito/relatório é pinada pelos arquivos
   regenerados; o plano define as tasks de atualização do `test_replay_list_out_of_order`
   e dos `.meta.json`.

## 7. Referência

Todo código desta etapa, inclusive em `tests/`, segue
`.claude/skills/guia-de-estilo/SKILL.md`: tipagem explícita, `ClassVar` para
constantes, `Path` para caminhos, zero comentários/docstrings, guard clauses,
dependências por construtor. Fórmula de tarefa e formato de commit seguem
`.claude/skills/spec-e-plano/SKILL.md`.
