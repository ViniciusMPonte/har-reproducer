# Plano de Implementação — Isolamento do Cookie Jar no Reduce Anchors do Optimize

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `ReplayOptimizer`: adiciona parâmetro opcional de filtro do backbone a `_feed_cookie_jar_from_backbone_cache`/`_execute`/`_confirm`, sem mudar nenhum chamador

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py` (`ReplayOptimizer._feed_cookie_jar_from_backbone_cache`, `ReplayOptimizer._execute`, `ReplayOptimizer._confirm`)

**Contexto:**
`_feed_cookie_jar_from_backbone_cache` hoje não recebe parâmetro nenhum e sempre
itera `self.backbone` inteiro, alimentando o `CookieJar` com todo índice cacheado do
backbone, independente de qual `ordered_indexes`/`schedule` a chamada de `_execute`
que a invocou está de fato testando. `_execute` chama esse método (duas vezes no pior
caso: antes da primeira tentativa e de novo depois de um refresh reativo) e `_confirm`
chama `_execute`. Nenhum dos três métodos hoje tem como um chamador pedir "alimente só
estes índices do backbone". Esta task muda só a **assinatura e o encanamento interno**
dos três métodos — o comportamento observável de todo chamador existente
(`_run_phase1`, `_attempt`, a confirmação final de `optimize()`, e todos os testes que
chamam esses métodos sem o novo argumento) permanece idêntico, porque o novo parâmetro
é opcional com default `None` e, quando `None`, o filtro não se aplica (spec seção 3.1).

**Estado atual:**
```python
def _execute(self, ordered_indexes: List[int], schedule: Set[int]) -> List[Tuple[int, StepResponse]]:
    self.cookie_jar.reset()
    self._feed_cookie_jar_from_backbone_cache()
    refreshes: int = 0
    results: List[Tuple[int, StepResponse]] = self._execute_raw(ordered_indexes, schedule)
    while self._needs_reactive_refresh(results) and refreshes < self.MAX_REACTIVE_REFRESHES:
        refreshes += 1
        print(...)
        self._execute_raw(self.backbone, set(self.backbone), force_refresh=True)
        self.cookie_jar.reset()
        self._feed_cookie_jar_from_backbone_cache()
        results = self._execute_raw(ordered_indexes, schedule)
    return results

def _feed_cookie_jar_from_backbone_cache(self) -> None:
    for index in sorted(self.backbone):
        response: Optional[StepResponse] = self._backbone_response_cache.get(index)
        if response is None:
            continue
        host, port, _ = RequestUrlScope.parts_for_step(self.workspace, index)
        self.cookie_jar.feed(host, port, response.cookies, response.cookie_attributes)

def _confirm(self, final_list: List[int], to_index: int, success_criteria: List[SuccessCriterion]) -> bool:
    results: List[Tuple[int, StepResponse]] = self._execute(final_list, set(final_list))
    target_response: StepResponse = next(response for index, response in results if index == to_index)
    return Validator.validate(target_response, success_criteria)
```
- Nenhum dos três métodos tem como restringir quais índices do backbone são
  efetivamente alimentados no jar.
- `_reduce_anchors` (`replay_optimizer.py:69-84`) chama `_confirm` sem nenhum
  parâmetro extra — é o único chamador que, na próxima task (T02), vai precisar de um
  comportamento diferente do default.

**Estado esperado depois:**
```python
def _feed_cookie_jar_from_backbone_cache(self, restrict_to: Optional[Set[int]] = None) -> None:
    for index in sorted(self.backbone):
        if restrict_to is not None and index not in restrict_to:
            continue
        response: Optional[StepResponse] = self._backbone_response_cache.get(index)
        if response is None:
            continue
        host, port, _ = RequestUrlScope.parts_for_step(self.workspace, index)
        self.cookie_jar.feed(host, port, response.cookies, response.cookie_attributes)

def _execute(
        self, ordered_indexes: List[int], schedule: Set[int],
        restrict_backbone_feed_to: Optional[Set[int]] = None,
) -> List[Tuple[int, StepResponse]]:
    self.cookie_jar.reset()
    self._feed_cookie_jar_from_backbone_cache(restrict_backbone_feed_to)
    refreshes: int = 0
    results: List[Tuple[int, StepResponse]] = self._execute_raw(ordered_indexes, schedule)
    while self._needs_reactive_refresh(results) and refreshes < self.MAX_REACTIVE_REFRESHES:
        refreshes += 1
        print(...)
        self._execute_raw(self.backbone, set(self.backbone), force_refresh=True)
        self.cookie_jar.reset()
        self._feed_cookie_jar_from_backbone_cache(restrict_backbone_feed_to)
        results = self._execute_raw(ordered_indexes, schedule)
    return results

def _confirm(
        self, final_list: List[int], to_index: int, success_criteria: List[SuccessCriterion],
        restrict_backbone_feed_to: Optional[Set[int]] = None,
) -> bool:
    results: List[Tuple[int, StepResponse]] = self._execute(final_list, set(final_list), restrict_backbone_feed_to)
    target_response: StepResponse = next(response for index, response in results if index == to_index)
    return Validator.validate(target_response, success_criteria)
```
- Nenhum chamador existente (`_run_phase1:95`, `_attempt:210`, `optimize():59`) muda
  de código nesta task — continuam chamando com a assinatura antiga, agora resolvida
  pelo valor default (`restrict_backbone_feed_to=None`), que preserva o comportamento
  atual (alimentar `self.backbone` inteiro).
- `_reduce_anchors` (`replay_optimizer.py:82`) também **não muda nesta task** — ainda
  chama `_confirm(trial_final_list, to_index, success_criteria)` sem o novo parâmetro.
  Isso é intencional: o filtro é passado a existir, mas ninguém o aciona ainda. O
  teste vermelho de referência (`test_reduce_anchors_does_not_remove_an_anchor_whose_cookie_the_target_genuinely_needs`)
  continua falhando depois desta task, pelo mesmo motivo de antes — é a T02 que o
  torna verde.
- ⚠️ Repassar `restrict_backbone_feed_to` às **duas** chamadas de
  `_feed_cookie_jar_from_backbone_cache` dentro de `_execute` (a inicial e a que roda
  depois do refresh reativo) — não só a primeira. Se só a primeira for filtrada, um
  refresh reativo dentro de um trial de `_reduce_anchors` (T02) reintroduziria o
  mesmo vazamento que a task inteira existe para fechar (spec seção 5, caso "refresh
  reativo dentro de `_execute`").

**Critérios de aceite:**
- [ ] `uv run pytest -q tests/unit/test_replay_optimizer.py -k does_not_remove_an_anchor` continua falhando (red preservado) — o motivo da falha é o mesmo de antes desta task: `reduced == []` em vez de `[50]` (a assinatura mudou, mas nenhum chamador ainda usa o filtro).
- [ ] `optimizer._feed_cookie_jar_from_backbone_cache()` chamado sem argumento continua populando o jar com todo `self.backbone` cacheado — comportamento idêntico ao atual (não-regressão: `test_feed_cookie_jar_from_backbone_cache_populates_jar_for_cached_backbone_indexes` e `test_feed_cookie_jar_from_backbone_cache_skips_indexes_without_cached_response` continuam passando sem alteração).
- [ ] `optimizer._execute([5], {5})` chamado sem o novo parâmetro continua alimentando o jar com o backbone inteiro antes de chamar `execute_schedule` — não-regressão: `test_execute_feeds_jar_from_backbone_cache_before_calling_execute_raw` continua passando.
- [ ] Refresh reativo sem o novo parâmetro continua repovoando o jar a partir do backbone recém-atualizado depois da reexecução forçada — não-regressão: `test_execute_reactive_refresh_refeeds_jar_from_newly_refreshed_backbone_before_final_retry` continua passando.
- [ ] `uv run pytest -q tests/unit/test_replay_optimizer.py` roda com a mesma contagem de falhas de antes desta task (1 falha — só o teste vermelho de `_reduce_anchors`; nenhuma das ~43 asserções restantes regride).
- [ ] `python -m py_compile har_reproducer/optimization/replay_optimizer.py` sem erros.

## [T02] — `ReplayOptimizer._reduce_anchors`: restringe o feed do jar ao `trial_final_list` sendo testado, fechando o vazamento do backbone cache

**Depende de:** T01 (assinaturas de `_feed_cookie_jar_from_backbone_cache`/`_execute`/`_confirm` já aceitam o filtro opcional).
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py` (`ReplayOptimizer._reduce_anchors`)

**Contexto:**
`_reduce_anchors` é o único método de `ReplayOptimizer` cujo `trial_final_list` pode
excluir um índice que é, ele mesmo, membro de `self.backbone` (spec seção 2.4) — é
exatamente esse caso que o vazamento do backbone cache mascara: o jar é alimentado com
o cookie daquele índice mesmo quando o trial está testando a hipótese de que ele *não*
está presente. Esta task fecha o vazamento acionando, só aqui, o filtro que a T01
deixou pronto.

**Estado atual:**
```python
def _reduce_anchors(
        self, anchors: List[int], from_index: int, to_index: int,
        kept: List[int], success_criteria: List[SuccessCriterion],
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
- `_confirm(trial_final_list, to_index, success_criteria)` é chamado sem o filtro —
  `_execute` interno alimenta o jar com `self.backbone` inteiro via cache, mesmo
  quando `trial_final_list` exclui um índice do backbone que está sendo testado para
  remoção.
- Com o `_CookieGatedScheduleExecutor` de teste (`tests/unit/test_replay_optimizer.py:441-466`),
  isso faz `_reduce_anchors([0, 50, 100], 0, 100, [], SUCCESS_CRITERIA)` retornar `[]`
  em vez de `[50]` — a âncora 50, única fonte do cookie `auth` que o alvo (step 100)
  exige, é removida por engano.

**Estado esperado depois:**
```python
def _reduce_anchors(
        self, anchors: List[int], from_index: int, to_index: int,
        kept: List[int], success_criteria: List[SuccessCriterion],
) -> List[int]:
    removable: List[int] = [anchor for anchor in anchors if anchor not in (from_index, to_index)]
    working: List[int] = list(removable)
    for anchor in reversed(removable):
        trial: List[int] = [a for a in working if a != anchor]
        trial_final_list: List[int] = sorted({from_index, to_index, *trial, *kept})
        if self._confirm(trial_final_list, to_index, success_criteria, restrict_backbone_feed_to=set(trial_final_list)):
            working = trial
    return working
```
- Único ponto de mudança: a chamada a `_confirm` agora passa
  `restrict_backbone_feed_to=set(trial_final_list)` — o jar, dentro desse `_confirm`,
  só é alimentado com os índices do backbone que também estão em `trial_final_list`.
  Se o índice sendo testado para remoção não está em `trial_final_list` (é exatamente
  o caso: ele foi excluído do `trial`), o cookie que só ele estabelece não entra no
  jar, e o teste de remoção passa a refletir a dependência real.
- Nenhum outro método muda nesta task — `_run_phase1`, `_attempt`, e a confirmação
  final de `optimize()` continuam chamando `_confirm`/`_execute` sem o novo
  parâmetro (spec seção 3.2: a confirmação final não precisa do filtro porque, depois
  de `_reduce_anchors` decidir corretamente, todo índice do backbone presente em
  `final_list` roda de verdade nessa própria chamada).
- ⚠️ Não generalizar o filtro para outros chamadores "por consistência" — a spec
  descarta explicitamente essa alternativa (seção 3.1, "Alternativa descartada"):
  amarrar o filtro a `schedule` ou aplicá-lo em `_attempt`/`_run_phase1` quebraria
  `test_execute_feeds_jar_from_backbone_cache_before_calling_execute_raw`, que trava o
  comportamento "alimenta tudo por default" de que essas duas fases dependem.

**Critérios de aceite:**
- [ ] `optimizer._reduce_anchors([0, 50, 100], 0, 100, [], SUCCESS_CRITERIA) == [50]` no cenário do teste `test_reduce_anchors_does_not_remove_an_anchor_whose_cookie_the_target_genuinely_needs` (`tests/unit/test_replay_optimizer.py:469-499`) — `uv run pytest -q tests/unit/test_replay_optimizer.py -k does_not_remove_an_anchor` passa (green).
- [ ] Âncora genuinamente desnecessária continua sendo removida: `test_reduce_anchors_removes_interior_anchor_when_target_alone_still_passes` continua passando (`optimizer.backbone == []` nesse teste, então o filtro não altera nada ali — spec seção 5).
- [ ] `test_reduce_anchors_keeps_interior_anchor_when_target_alone_fails` e `test_reduce_anchors_with_no_interior_anchor_makes_no_extra_call` continuam passando sem alteração.
- [ ] `test_optimize_end_to_end_reduces_interior_anchor_not_needed_by_target` e `test_optimize_end_to_end_executes_backbone_index_only_once_across_reduce_and_confirm` continuam passando — o fluxo ponta a ponta de `optimize()` não regride.
- [ ] `uv run pytest -q tests/unit/test_replay_optimizer.py` termina com 0 falhas (as ~43 asserções que já passavam antes de T01 continuam passando, mais o teste antes vermelho agora verde — total do arquivo, sem nenhum `-k`).
- [ ] `uv run pytest -q` (suíte completa do repositório, sem filtro de arquivo) não introduz nenhuma falha nova em relação ao estado da branch antes desta etapa — nenhum teste fora de `tests/unit/test_replay_optimizer.py` referencia `_reduce_anchors`/`_feed_cookie_jar_from_backbone_cache`/`_execute`/`_confirm` de `ReplayOptimizer` com uso posicional que quebraria com o novo parâmetro opcional (`grep -rn "_reduce_anchors\|_feed_cookie_jar_from_backbone_cache\|optimizer\._execute\|optimizer\._confirm" tests/` para confirmar o raio de impacto antes de rodar).
- [ ] `python -m py_compile har_reproducer/optimization/replay_optimizer.py` sem erros.
