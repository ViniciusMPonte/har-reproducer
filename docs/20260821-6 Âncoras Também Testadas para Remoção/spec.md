# Spec — Âncoras Também Testadas para Remoção

## 0. Sumário

`ReplayOptimizer` (comando `optimize`) só testa a remoção dos passos que ficam **entre**
âncoras consecutivas; as âncoras em si — passos de onde algum token do alvo tem origem —
entram no resultado por construção e nunca são desafiadas. Isso mistura duas garantias
diferentes sob o mesmo nome: uma âncora garante **proveniência** (o valor foi confirmado
vindo daquele passo, em algum momento), não **necessidade** (que esse passo precise ser
executado de novo agora para o alvo passar). `ReplayTokenResolver._resolve_one` já sabe
resolver um token a partir de uma resposta congelada em disco quando a origem não está no
schedule — o mecanismo para tratar uma âncora removida com segurança já existe e já é
usado para os passos não-âncora; falta só submeter as âncoras ao mesmo teste. Medido nesta
spec, com o código atual (pós itens 9/10/11 do backlog de 17/08, que já reduziram bastante
o problema): `optimize --to 233` ainda devolve `[0, 153, 233]` (3 steps) quando `[233]`
sozinho já passa — **2 das 3 entradas continuam sendo proveniência pura**, zero
necessidade.

### Glossário

| termo | significado nesta spec |
|---|---|
| **âncora** | Um índice de step que `compute_smart_schedule` inclui no schedule por ser origem (direta ou transitiva) de algum token consumido pelo alvo (`ReplayRunner._expand_pending`, via `CurlTokenComment.parse_anchors`). Hoje, todo `anchors` sai do phase 1 e entra no resultado final sem nenhum teste de remoção. |
| **proveniência** | Garantia de que o valor de um token *foi* confirmado como vindo de um determinado step, em algum momento (na criação do extrator, ou na última vez que ele foi executado). Não diz nada sobre se esse step precisa ser executado de novo. |
| **necessidade** | Garantia de que, **sem** executar um determinado step agora, o alvo deixaria de responder de acordo com `success_criteria`. É isso que a fase 2 de hoje já testa para os passos não-âncora, e que esta spec estende às âncoras. |
| **época** | Reaproveitado das etapas de 21/08 anteriores (porta de admissão, item 11): "época do HAR" é a gravação original (`original_responses/`); "época da execução" é uma resposta real obtida rodando o fluxo (`real_responses/` ou a resposta do próprio `optimize` em andamento). |

---

## 1. Objetivo

### 1.1 O problema, com medição fresca

`optimize` (`optimization/replay_optimizer.py:32-59`) monta `final_list = sorted({from_index,
*anchors, *kept})` — `anchors` entra inteiro, sem teste. Isso já foi medido no relatório de
17/08 (§3.5): para o alvo `233`, o resultado tinha 7 steps quando 1 já bastava. Mas aquela
medição é de **antes** dos itens 9 (extrator literal não vira âncora), 10 (mojibake do
corpo comprimido) e 11 (porta de admissão por mudança entre épocas) — todos já mergeados.
Esta spec remediu o mesmo alvo, com o código de hoje:

**Procedência:** `run --mode main` fresco contra `arquivos-har/progressofit.har` (324
entries do HAR, 320 `.curl.sh` gerados — 4 pulados por scheme `ws://`), servidor real em
`127.0.0.1:8080`, branch `master` em 21/08/2026 (itens 1, 2, 3, 6, 7, 9, 10, 11 já
mergeados). Workspace em
`/tmp/.../scratchpad/ws_item4_fresh` (efêmero, não commitado).

```
$ cat curls/req_0233.curl.sh
# [Token 9076b01104d18abe4f35b2dd287286b3 comes from response of step 0153]
# [Static 3] url←0059; header:Content-Type←0023; header:Origin←0075
# [Unresolved 2] header:Accept; header:Referer
```

Confirmação de que a porta de admissão (item 11) já eliminou a aresta invertida do relato
de 17/08 §3.8 (o header `Origin` que "vinha" do eco CORS `Access-Control-Allow-Origin` do
step 75): ela aparece agora em `[Static 3]`, não como `[Token ...]` — não é mais âncora.
Restou **uma única** dependência real: origin_step `153`.

```
$ uv run python -m har_reproducer.main optimize --output ws_item4_fresh --to 233 \
    --success-criteria '[{"type":"status_code","expected":200}]'
...
Optimization SUCCESSFUL: 3 step(s) written to .../optimize_233.txt
$ cat optimize_233.txt
0
153
233

$ echo 233 > steps_233_only.txt
$ uv run python -m har_reproducer.main replay --output ws_item4_fresh --mode list --steps-file steps_233_only.txt
Step 233 completed with status 200
Replay step results:
  Step 233: ✓ matched (200 vs original 200)
Replay Validation Result: ✓ SUCCESS (step 233 status code vs. original)
```

**A porta de admissão reduziu o problema (7→3), não o eliminou: `[233]` sozinho ainda
passa, então tanto `0` (piso explícito, não é âncora) quanto `153` (a única âncora
restante) são removíveis sem efeito observável — 2 das 3 entradas, zero necessidade,
igual à proporção de 17/08.** A porta decide, na criação do extrator, se o valor mudou
entre a época do HAR e a época da execução — uma pergunta diferente de "esse passo
precisa ser executado de novo **agora**, neste `optimize`", que é o que falta responder.

### 1.2 Por que a porta de admissão (item 11) não resolve isso

A porta (`CandidateResolver._admission_gate_rejects`) decide, **uma vez, na criação do
extrator**, se o valor mudou entre a época do HAR e a época da execução que criou aquele
workspace. Se mudou, o candidato se torna um extrator de verdade — e vira âncora
**para sempre**, em todo `optimize` futuro sobre esse workspace, mesmo que **este**
`optimize` em particular não precise executar aquele step de novo (porque
`ReplayTokenResolver._resolve_one` já sabe ler o valor de uma resposta congelada quando a
origem não está no schedule). São perguntas diferentes: a porta pergunta "este token é
genuinamente dinâmico?" (uma vez, na criação); o `optimize` precisa perguntar "preciso
executar a origem deste token de novo, **agora**, para este alvo passar?" (a cada
chamada, porque a resposta pode depender de quão fresco o `real_responses/` daquele step
ainda está). Reaproveitar a porta para responder a segunda pergunta exigiria assumir que
"mudou uma vez" implica "sempre vai precisar ser reexecutado" — o que não é verdade (ex.:
um token de sessão pode ficar válido por horas; nesse intervalo, a resposta congelada
ainda serve).

### 1.3 Custo de não corrigir

Cosmético para a correção do alvo (o resultado ainda passa), mas caro para o propósito do
`optimize`: menos remoção de passos supérfluos significa mais requisições reais
desperdiçadas a cada rodada futura, e o README (corrigido pelo item 1 desta mesma
investigação) já precisa ser corrigido de novo — item 1 documentou a limitação como
definitiva ("as âncoras em si nunca são testadas para remoção"), mas o objetivo sempre foi
que essa frase deixasse de ser verdade assim que esta etapa existisse (backlog, item 4:
"entrega o item 1 de verdade — o item 1 é o remendo textual até esta correção existir").

### 1.4 Fora de escopo

- Qualquer classificação estática de "proveniência × necessidade" comparando época do HAR
  × época de execução **antes** de tentar remover uma âncora — descartada em favor de
  testar a remoção empiricamente (§3.1), pelo motivo explicado ali.
- O mecanismo `ever_changed`/`valid_count`/`STATIC_CONFIRMATION_THRESHOLD` de
  `ReplayTokenResolver` (usado hoje só para anotar `[Token ...] probably static` no
  `.curl.sh` de um `replay`) — não é tocado nem reaproveitado; é uma classificação por
  acúmulo de observações ao longo de várias execuções, não serve para decidir dentro de
  uma única chamada de `optimize`.
- Item 6 (`403` sinaliza falha de auth) e item 8 (coincidência de baixa entropia) — já
  fechados, sem relação de código com esta etapa.
- Redescoberta reativa — continua fora de escopo, sem spec própria.

---

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `ReplayOptimizer.optimize`/`_confirm` — `optimization/replay_optimizer.py:32-65`

```python
def optimize(self, workspace, run_id, from_index, to_index, success_criteria, output_path=None):
    anchors, backbone = self._run_phase1(from_index, to_index)
    try:
        kept: List[int] = self._run_phase2(from_index, to_index, anchors, backbone, success_criteria)
    except ReplayOptimizerAborted as aborted:
        print(f"ReplayOptimizer: aborted — {aborted.reason}")
        return None

    final_list: List[int] = sorted({from_index, *anchors, *kept})
    if not self._confirm(final_list, to_index, success_criteria):
        print("ReplayOptimizer: aborted — final confirmation failed after all ranges passed individually.")
        return None
    ...

def _confirm(self, final_list: List[int], to_index: int, success_criteria: List[SuccessCriterion]) -> bool:
    results: List[Tuple[int, StepResponse]] = self._execute(final_list, set(final_list))
    target_response: StepResponse = next(response for index, response in results if index == to_index)
    return Validator.validate(target_response, success_criteria)
```
`_confirm` já é exatamente o teste que decide se um `final_list` candidato ainda faz o
alvo passar — executa a lista inteira com `schedule = set(final_list)` e valida a resposta
de `to_index`. É reaproveitado tal como está: a nova fase desta spec só chama `_confirm`
várias vezes, com listas candidatas menores, antes da chamada final que já existe.

### `ReplayOptimizer._resolve_range`/`_attempt` — `optimization/replay_optimizer.py:119-157`

```python
def _resolve_range(self, left, right, to_index, backbone, kept_so_far, success_criteria):
    if self._attempt(left, right, [], backbone, kept_so_far, to_index, success_criteria):
        return []
    candidates: List[int] = self._candidates_between(left, right)
    if not candidates or not self._attempt(left, right, candidates, backbone, kept_so_far, to_index, success_criteria):
        raise ReplayOptimizerAborted(...)
    working: List[int] = list(candidates)
    for candidate in reversed(candidates):
        trial: List[int] = [c for c in working if c != candidate]
        if self._attempt(left, right, trial, backbone, kept_so_far, to_index, success_criteria):
            working = trial
    return working
```
Este é o padrão de remoção — "greedy, um candidato por vez, do mais próximo do alvo para o
mais distante (`reversed`), mantém a remoção só se o alvo ainda passa" — que a spec estende
das âncoras (§3.1), reaproveitando a mesma ideia (`reversed`, remover um, testar, manter se
ainda passa), sem alterar este método.

### `ReplayTokenResolver._resolve_one`/`_reference_dir_for_step` — `replay/replay_token_resolver.py:47-94`

```python
def _resolve_one(self, token_id, dependencies, schedule, replay_run_dir, res_refer_dir, original_responses_dir):
    origin_step: Optional[int] = dependencies.get(token_id)
    if origin_step in schedule:
        override_dir: Path = replay_run_dir
    else:
        override_dir = self._reference_dir_for_step(origin_step, res_refer_dir, original_responses_dir)
    value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
    ...

@staticmethod
def _reference_dir_for_step(origin_step, res_refer_dir, original_responses_dir):
    if origin_step is None:
        return res_refer_dir
    if (res_refer_dir / f"res_{origin_step:04d}.json").exists():
        return res_refer_dir
    return original_responses_dir
```
Este é o mecanismo que já torna seguro remover uma âncora do schedule: quando o
`origin_step` de um token não está no `schedule`, o extrator roda contra a resposta
congelada (`res_refer_dir`, senão `original_responses_dir`) em vez de exigir uma execução
nova. Nenhuma mudança aqui — é o que já garante que testar a remoção de uma âncora (§3.1)
é seguro pelo mesmo motivo que testar a remoção de um candidato não-âncora já é.

### `ReplayRunner.compute_smart_schedule`/`_expand_pending` — `replay/replay_runner.py:163-186`

```python
def compute_smart_schedule(self, from_index, to_index):
    ...
    schedule: Set[int] = {target}
    pending: Set[int] = {target}
    while pending:
        current: int = pending.pop()
        self._expand_pending(current, floor, existing_set, schedule, pending)
    return sorted(schedule), schedule

def _expand_pending(self, current, floor, existing_set, schedule, pending):
    curl_text: str = self.workspace.curl_file(current).read_text(encoding="utf-8")
    dependencies: Dict[str, int] = self.curl_token_comment.parse_anchors(curl_text)
    for origin_step in dependencies.values():
        if origin_step >= floor and origin_step not in schedule and origin_step in existing_set:
            schedule.add(origin_step)
            pending.add(origin_step)
```
Fonte de `anchors` — BFS reverso a partir do alvo, seguindo toda linha `[Token ...]`
(`parse_anchors`, que **não** casa `[Static N]`/`[Unresolved N]`, confirmado pelo item 9).
`to_index` é sempre o maior elemento de `anchors` (é a semente do BFS); `from_index` pode
ou não estar presente, dependendo se ele mesmo é origem de algum token. Nenhuma mudança
aqui — esta spec só consome `anchors` depois que `_run_phase1` já o calculou.

---

## 3. Decisões de arquitetura

### 3.1 — Nova fase 3: testar cada âncora interior para remoção, com o mesmo mecanismo empírico da fase 2

**Por que testar empiricamente, e não classificar por época antes de tentar (a alternativa
descartada):** a alternativa seria replicar a lógica da porta de admissão — comparar
`original_responses/`/`real_responses/` do `origin_step` de cada âncora e decidir de
antemão se ela é "proveniência" (nunca testar remoção) ou "necessidade" (sempre incluir).
Descartada porque (a) já existe um mecanismo que resolve exatamente esse problema sem
precisar prever nada — `_resolve_one` já executa a âncora "de verdade" no primeiro
`_confirm` que a inclui e cai para a referência congelada só se ela for removida e o teste
passar mesmo assim; tentar prever isso por comparação de época adicionaria uma segunda
fonte de verdade que pode discordar do teste empírico (§1.2 já mostra que "mudou uma vez"
não implica "sempre vai precisar de novo"); e (b) o teste empírico é o mesmo raciocínio
que a fase 2 já usa para os passos não-âncora — generalizar em vez de inventar um
mecanismo paralelo.

**Estado esperado:**
```python
def optimize(self, workspace, run_id, from_index, to_index, success_criteria, output_path=None):
    anchors, backbone = self._run_phase1(from_index, to_index)
    try:
        kept: List[int] = self._run_phase2(from_index, to_index, anchors, backbone, success_criteria)
    except ReplayOptimizerAborted as aborted:
        print(f"ReplayOptimizer: aborted — {aborted.reason}")
        return None

    reduced_anchors: List[int] = self._reduce_anchors(anchors, from_index, to_index, kept, success_criteria)
    final_list: List[int] = sorted({from_index, to_index, *reduced_anchors, *kept})
    if not self._confirm(final_list, to_index, success_criteria):
        print("ReplayOptimizer: aborted — final confirmation failed after all ranges passed individually.")
        return None
    ...

def _reduce_anchors(
        self,
        anchors: List[int],
        from_index: int,
        to_index: int,
        kept: List[int],
        success_criteria: List[SuccessCriterion],
) -> List[int]:
    removable: List[int] = [anchor for anchor in anchors if anchor not in (from_index, to_index)]
    working: List[int] = list(removable)
    for anchor in reversed(removable):
        trial: List[int] = [a for a in working if a != anchor]
        trial_final_list: List[int] = sorted({from_index, to_index, *trial, *kept})
        if self._confirm(trial_final_list, to_index, success_criteria):
            working = trial
    return working
```
`from_index` e `to_index` nunca entram em `removable` — são o piso explícito da chamada
(`--from`) e o próprio alvo (`--to`), preservados por serem os limites explícitos da busca,
exatamente como `final_list` já força `from_index` hoje. `reversed(removable)` remove
primeiro a âncora mais próxima do alvo, mesma convenção de ordem já usada em
`_resolve_range` para candidatos não-âncora.

⚠️ **A ordem de remoção pode afetar qual subconjunto sobra quando duas âncoras
interagem** (ex.: âncora A só é dispensável se B também for removida, e vice-versa, mas
nem toda ordem de teste descobre isso) — é uma limitação aceita, a mesma que já existe
hoje na fase 2 para candidatos não-âncora (busca gulosa local, não exaustiva). O README
(§3.2) já vai declarar isso.
⚠️ **Custo em requisições**: cada âncora testada custa até `len(trial_final_list)`
requisições reais (um `_confirm` inteiro). Para N âncoras interiores, o pior caso soma
`O(N × len(final_list))` requisições adicionais — já limitado pelo mesmo teto
`max_requests` que `_execute_raw` já aplica (`ValueError` se excedido). Nenhuma mudança
necessária em `_execute_raw`.

### 3.2 — README: o parágrafo `⚠️` do `optimize` precisa mudar de novo

**Estado atual** (já corrigido pelo item 1, 21/08):
```
⚠️ Cada requisição vai contra o servidor real (...) O resultado é um mínimo local
**dentro de cada faixa entre âncoras consecutivas** (nenhum candidato testado pode ser
removido sem quebrar o alvo) — as âncoras em si nunca são testadas para remoção, então
não é o menor subconjunto teoricamente possível do fluxo inteiro.
```
**Estado esperado:**
```
⚠️ Cada requisição vai contra o servidor real (o mesmo risco de efeito colateral que já
existe em `run`/`replay`) e a busca pode reexecutar o mesmo passo várias vezes — não é
recomendado num fluxo com efeitos colaterais não-idempotentes (ex.: criar um recurso novo
a cada chamada). O resultado é um mínimo local (nenhum passo isolado — âncora ou não —
pode ser removido sem quebrar o alvo), exceto o piso `--from` e o próprio alvo (`--to`),
sempre mantidos por serem os limites explícitos da busca. Ainda não é necessariamente o
menor subconjunto teoricamente possível: a busca é gulosa (testa remoções uma a uma, na
ordem do alvo para o início) e não exaustiva sobre combinações — duas âncoras que só são
dispensáveis juntas podem sobreviver ambas.
```

### 3.3 — `_estimate_worst_case_requests`/`_print_estimate`: declarar a nova fase como custo não incluído

**Estado atual:**
```python
def _print_estimate(self, from_index: int, anchors: List[int]) -> None:
    estimate: int = self._estimate_worst_case_requests(from_index, anchors)
    print(
        f"ReplayOptimizer: worst-case estimate ≈ {estimate} requests (does NOT include reactive session "
        f"refreshes — unpredictable and disproportionately expensive, since each refresh re-runs the entire "
        f"backbone; calibrate --max-requests with headroom above this estimate when the backbone is large)."
    )
```
**Estado esperado:** a mensagem passa a declarar também a fase 3 como custo fora da
estimativa (ela só pode ser calculada depois que `kept`/`final_list` existem, que é depois
de `_print_estimate` já ter sido chamado em `_run_phase1`):
```python
print(
    f"ReplayOptimizer: worst-case estimate ≈ {estimate} requests (does NOT include reactive session "
    f"refreshes or the anchor-removal pass — both unpredictable before phase 2 runs; calibrate "
    f"--max-requests with headroom above this estimate when the backbone is large)."
)
```

---

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `optimization/replay_optimizer.py` → `ReplayOptimizer.optimize` | chama `_reduce_anchors` entre a fase 2 e a confirmação final (§3.1) |
| `optimization/replay_optimizer.py` → `ReplayOptimizer` (novo método) | `_reduce_anchors`: testa cada âncora interior para remoção, mesmo padrão de `_resolve_range` (§3.1) |
| `optimization/replay_optimizer.py` → `ReplayOptimizer._print_estimate` | mensagem passa a citar a fase de redução de âncoras como custo não incluído na estimativa (§3.3) |
| `README.md` | reescreve de novo o parágrafo `⚠️` do `optimize` (§3.2) |

Nenhuma mudança em `ReplayTokenResolver`, `ReplayRunner.compute_smart_schedule`,
`CandidateResolver` ou `CurlTokenComment` — todos reaproveitados como estão (§2).

---

## 5. Casos de borda e comportamento de erro

**5.1 Nenhuma âncora interior (`anchors` só tem `from_index`/`to_index`, ou só `to_index`
quando `from_index` não é âncora).** `removable` fica vazio, `_reduce_anchors` devolve `[]`
sem chamar `_confirm` nenhuma vez extra — comportamento idêntico ao de hoje (`reversed([])`
não itera).

**5.2 `_confirm` falha para toda remoção tentada.** `working` nunca muda do valor inicial
(`removable` completo) — `final_list` sai igual ao que sairia sem esta etapa, e a
confirmação final (já existente) segue passando pelo mesmo motivo que sempre passou. Sem
regressão possível: o pior caso desta fase é "não remover nada".

**5.3 Remover uma âncora expõe uma resposta ausente (`res_refer_dir`/`original_responses_dir`
sem o arquivo do `origin_step`).** `ReplayTokenResolver._fallback_to_captured` já trata isso
hoje (cai para `captured_value` ou `TokenResolutionStatus.UNRESOLVED`) — se isso fizer
`_confirm` falhar, a âncora simplesmente não é removida (mesmo caminho de 5.2). Nenhum
tratamento novo necessário.

**5.4 Teto de requisições (`max_requests`) atingido durante a fase 3.** `_confirm` →
`_execute` → `_execute_raw` já levanta `ValueError` ao exceder — comportamento idêntico ao
de hoje para a fase 2, sem tratamento novo.

**5.5 Duas âncoras interdependentes (só dispensáveis juntas).** Ver ⚠️ em §3.1 — limitação
aceita, documentada no README (§3.2), não é um defeito a corrigir nesta etapa.

---

## 6. Referência

Toda alteração de código desta spec segue [[guia-de-estilo]]. A decisão de testar
remoção empiricamente em vez de classificar por comparação de época (§3.1) segue o
princípio de reaproveitar o mecanismo mais simples que já existe em vez de duplicar uma
segunda fonte de verdade — mesmo raciocínio já aplicado na etapa anterior deste mesmo dia
("Proveniência Confiável no Cache Hit"), que preferiu ler `Extractor.agent_type` em vez de
duplicar a mesma informação em `DynamicToken.origin_location`.
