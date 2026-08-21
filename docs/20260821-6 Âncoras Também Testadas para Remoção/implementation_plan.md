# Plano de Implementação — Âncoras Também Testadas para Remoção

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `ReplayOptimizer`: nova fase `_reduce_anchors` testa cada âncora interior para remoção

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py`
(`ReplayOptimizer.optimize`, `ReplayOptimizer._print_estimate`, novo método
`ReplayOptimizer._reduce_anchors`), `tests/unit/test_replay_optimizer.py`

**Contexto:**
`optimize` monta `final_list = sorted({from_index, *anchors, *kept})` — `anchors` entra
inteiro, sem nenhum teste de remoção, mesmo depois que a porta de admissão (item 11) já
reduziu bastante quantas âncoras existem. Medido na spec (§1.1) contra o servidor real,
código de hoje: `optimize --to 233` devolve `[0, 153, 233]`, mas `[233]` sozinho já passa
— a única âncora interior (`153`) é removível sem efeito. `ReplayTokenResolver._resolve_one`
já sabe resolver um token a partir da resposta congelada quando a origem não está no
schedule (`replay/replay_token_resolver.py:56-61`, não muda nesta task) — falta só
submeter as âncoras ao mesmo teste que a fase 2 já faz para os passos não-âncora.

**Estado atual:**
```python
# optimization/replay_optimizer.py:32-53
def optimize(self, workspace, run_id, from_index, to_index, success_criteria, output_path=None):
    anchors: List[int]
    backbone: List[int]
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

    destination: Path = output_path if output_path is not None else workspace.optimized_steps_file(run_id)
    ...
```
```python
# optimization/replay_optimizer.py:181-187
def _print_estimate(self, from_index: int, anchors: List[int]) -> None:
    estimate: int = self._estimate_worst_case_requests(from_index, anchors)
    print(
        f"ReplayOptimizer: worst-case estimate ≈ {estimate} requests (does NOT include reactive session "
        f"refreshes — unpredictable and disproportionately expensive, since each refresh re-runs the entire "
        f"backbone; calibrate --max-requests with headroom above this estimate when the backbone is large)."
    )
```

**Estado esperado depois:**
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

    destination: Path = output_path if output_path is not None else workspace.optimized_steps_file(run_id)
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
```python
def _print_estimate(self, from_index: int, anchors: List[int]) -> None:
    estimate: int = self._estimate_worst_case_requests(from_index, anchors)
    print(
        f"ReplayOptimizer: worst-case estimate ≈ {estimate} requests (does NOT include reactive session "
        f"refreshes or the anchor-removal pass — both unpredictable before phase 2 runs; calibrate "
        f"--max-requests with headroom above this estimate when the backbone is large)."
    )
```

⚠️ `from_index` e `to_index` nunca entram em `removable` — são os limites explícitos da
busca (o piso pedido via `--from`, o próprio alvo via `--to`), preservados exatamente como
`final_list` já preservava `from_index` antes desta task.
⚠️ `reversed(removable)` — mesma convenção de ordem de `_resolve_range`
(`for candidate in reversed(candidates)`, `:132-140`): remove primeiro a âncora mais
próxima do alvo. Não inverter a ordem.
⚠️ `_reduce_anchors` **não** lança `ReplayOptimizerAborted` — ao contrário de
`_resolve_range`, uma âncora que não pode ser removida simplesmente permanece em
`working`; não há "faixa sem candidato nenhum que funcione" aqui, porque `removable`
completo (a situação de hoje) já é sabido válido pela própria fase 2.
⚠️ **Nenhuma mudança em `_run_phase2`, `_resolve_range`, `_attempt`, `_confirm`,
`ReplayTokenResolver` ou `ReplayRunner.compute_smart_schedule`** — a task só adiciona
`_reduce_anchors` e as duas linhas em `optimize` que a chamam.

**Critérios de aceite (TDD — escrever os testes abaixo, confirmar que falham pelo motivo
certo contra o código atual, só então implementar):**
- [ ] `optimizer._reduce_anchors([0, 153, 233], 0, 233, [], SUCCESS_CRITERIA)` com um
  `FakeScheduleExecutor` cujo `default_response`/`responses_by_call` faz o step `233`
  responder `200` devolve `[]` (a âncora `153` foi removida) e registra exatamente 1
  chamada a `execute_schedule`, com `ordered_indexes == [0, 233]` — este é o cenário
  medido na spec (§1.1), reproduzido como teste.
- [ ] O mesmo cenário, mas com o step `233` respondendo `404` na única chamada, devolve
  `[153]` (a âncora não pôde ser removida) — não-remoção quando o alvo de fato depende
  dela.
- [ ] `optimizer._reduce_anchors([0, 9], 0, 9, [], SUCCESS_CRITERIA)` (nenhuma âncora
  interior, só os dois limites) devolve `[]` sem nenhuma chamada a `execute_schedule` —
  caso de borda §5.1 da spec.
- [ ] Teste de ponta a ponta via `optimizer.optimize(...)`, com
  `smart_schedule=([0, 153, 233], {0, 153, 233})`, `existing_indexes=[0, 153, 233]`,
  `default_response=_ok(200)`: `result == [0, 233]` (não `[0, 153, 233]`) — confirma que
  a integração entre `_run_phase2` e `_reduce_anchors` produz o resultado que a spec
  promete.
- [ ] Não-regressão: `test_optimize_end_to_end_success_writes_steps_file`,
  `test_optimize_confirmation_failure_writes_no_file_and_returns_none`,
  `test_optimize_final_list_has_no_duplicate_when_to_index_equals_from_index` e
  `test_optimize_range_abort_writes_no_file_and_returns_none` continuam passando **sem
  alterar `responses_by_call`** — nenhum desses cenários tem âncora interior
  (`smart_schedule` de cada um só tem `from_index`/`to_index`), então `_reduce_anchors`
  não deveria adicionar nenhuma chamada extra a `execute_schedule` em nenhum deles.
- [ ] Não-regressão: `test_run_phase2_*` (todos os que chamam `_run_phase2` diretamente,
  não `optimize`) continuam passando sem alteração — `_reduce_anchors` não é chamado por
  `_run_phase2`.

---

## [T02] — `README.md`: o parágrafo `⚠️` do `optimize` reflete que âncoras também são testadas

**Depende de:** T01 (o texto descreve o comportamento que T01 implementa).
**Arquivos envolvidos:** `README.md` (parágrafo `⚠️` da seção do comando `optimize`)

**Contexto:**
O item 1 (etapa de 21/08 anterior) corrigiu o parágrafo para dizer que "as âncoras em si
nunca são testadas para remoção" — verdade até esta etapa. Depois de T01, isso deixa de
ser verdade; o parágrafo precisa refletir a nova garantia (mínimo local sobre o intervalo
inteiro, exceto os dois limites explícitos) e a limitação nova que a busca gulosa introduz
(duas âncoras só dispensáveis juntas podem sobreviver ambas).

**Estado atual:**
```
⚠️ Cada requisição vai contra o servidor real (o mesmo risco de efeito colateral que já
existe em `run`/`replay`) e a busca pode reexecutar o mesmo passo várias vezes — não é
recomendado num fluxo com efeitos colaterais não-idempotentes (ex.: criar um recurso novo
a cada chamada). O resultado é um mínimo local **dentro de cada faixa entre âncoras
consecutivas** (nenhum candidato testado pode ser removido sem quebrar o alvo) — as
âncoras em si nunca são testadas para remoção, então não é o menor subconjunto
teoricamente possível do fluxo inteiro.
```

**Estado esperado depois:**
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

**Critérios de aceite:**
- [ ] O parágrafo `⚠️` do `optimize` no README não contém mais a frase "as âncoras em si
  nunca são testadas para remoção".
- [ ] O parágrafo passa a declarar a limitação da busca gulosa (âncoras interdependentes).
- [ ] Nenhum outro trecho do README é alterado.
