# Plano de Implementação — Cache de Respostas do Backbone na Otimização de Replay

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `ReplayOptimizer`: cache de respostas do backbone em `_execute_raw`, admissão por `_remember` e reexecução forçada em `_execute`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py` (`ReplayOptimizer.__init__`,
`ReplayOptimizer._execute`, `ReplayOptimizer._execute_raw`, novo método privado
`ReplayOptimizer._remember`), `tests/unit/test_replay_optimizer.py` (novos testes; nenhum teste
existente muda de asserção)

**Contexto:**
`ReplayOptimizer.optimize()` reexecuta contra o servidor real um prefixo fixo de steps (o
"backbone", `self.backbone: List[int]`) como pré-requisito de toda tentativa de busca —
inclusive `from_index`, presente em **todo** `final_list` que `_confirm` recebe (chamado uma
vez por âncora testada para remoção em `_reduce_anchors`, mais uma vez ao final de
`optimize()`). Contra um site cujo `from_index` inicia uma sessão nova a cada hit real, cada
uma dessas reexecuções sobrescreve, em disco, a única cópia da resposta daquele step — e um
login mais adiante na sequência autentica a sessão que existia no momento em que ele rodou,
não a sessão mais recente que uma reexecução posterior de `from_index` acabou de emitir.
Quando o alvo roda, seu extrator de cookie de sessão lê a sessão errada e a busca falha de
forma que nenhum subconjunto de candidatos resolve (spec §0, §1.1).

Esta task implementa a correção inteira num só commit — as três decisões de arquitetura que a
compõem (§3.2 atributo novo, §3.3 leitura/escrita do cache em `_execute_raw`, §3.4 regra de
admissão em `_remember`) mais o único ponto de invalidação (§3.5, `force_refresh=True` na
chamada de refresh dentro de `_execute`) **não são independentemente entregáveis**: se o cache
de `_execute_raw` (§3.3) for implementado sem que a chamada de refresh em `_execute` (§3.5)
passe `force_refresh=True` no mesmo commit, essa chamada — que hoje é
`self._execute_raw(self.backbone, set(self.backbone))`, sem esse parâmetro — passaria a
consultar o cache como qualquer outra chamada, e a recuperação reativa deixaria de bater na
rede quando deveria. Isso quebra testes que já existem e continuam no mesmo estado depois
desta task: `test_execute_gives_up_after_two_refreshes_and_returns_last_result` (espera 5
chamadas reais a `execute_schedule` — 3 para o índice fora do backbone, 2 refreshes forçados
do backbone) passaria a fazer só 4, porque o segundo refresh encontraria o índice do backbone
já no cache (admitido pelo primeiro refresh, cuja resposta é "saudável" porque
`needs_recovery` não tem referência para aquele índice neste cenário de teste) e pularia a
rede. Por isso as quatro decisões viram uma task só: qualquer subconjunto delas deixaria a
suíte existente vermelha entre commits, o que a skill não permite. `§3.6` (efeito colateral em
`requests_made`) é uma consequência automática de §3.3, não uma decisão separada a implementar.

**Estado atual:**
```python
# :20-30
def __init__(
        self,
        schedule_executor: ScheduleExecutor,
        metadata_store: SilentExtractorMetadataStore,
        max_requests: int = 500,
) -> None:
    self.schedule_executor: ScheduleExecutor = schedule_executor
    self.metadata_store: SilentExtractorMetadataStore = metadata_store
    self.max_requests: int = max_requests
    self.requests_made: int = 0
    self.backbone: List[int] = []
```
```python
# :96-107
def _execute(self, ordered_indexes: List[int], schedule: Set[int]) -> List[Tuple[int, StepResponse]]:
    refreshes: int = 0
    results: List[Tuple[int, StepResponse]] = self._execute_raw(ordered_indexes, schedule)
    while self._needs_reactive_refresh(results) and refreshes < self.MAX_REACTIVE_REFRESHES:
        refreshes += 1
        print(
            f"ReplayOptimizer: detected recoverable status in schedule — refreshing backbone before "
            f"retrying (attempt {refreshes}/{self.MAX_REACTIVE_REFRESHES})..."
        )
        self._execute_raw(self.backbone, set(self.backbone))
        results = self._execute_raw(ordered_indexes, schedule)
    return results
```
```python
# :109-119
def _execute_raw(self, ordered_indexes: List[int], schedule: Set[int]) -> List[Tuple[int, StepResponse]]:
    results: List[Tuple[int, StepResponse]] = self.schedule_executor.execute_schedule(
        ordered_indexes, schedule, annotate=False
    )
    self.requests_made += len(ordered_indexes)
    if self.requests_made > self.max_requests:
        raise ValueError(
            f"ReplayOptimizer: teto de requisições atingido ({self.requests_made}/{self.max_requests}) — "
            f"abortando a busca."
        )
    return results
```
`_execute_raw` bate na rede para **todo** índice em `ordered_indexes`, sempre, e conta cada um
contra `requests_made`. Não existe `_remember`, nem noção de cache — cada chamada é
independente da anterior, mesmo quando reexecuta o mesmo índice do backbone.

**Estado esperado depois:**
```python
# __init__
def __init__(
        self,
        schedule_executor: ScheduleExecutor,
        metadata_store: SilentExtractorMetadataStore,
        max_requests: int = 500,
) -> None:
    self.schedule_executor: ScheduleExecutor = schedule_executor
    self.metadata_store: SilentExtractorMetadataStore = metadata_store
    self.max_requests: int = max_requests
    self.requests_made: int = 0
    self.backbone: List[int] = []
    self._backbone_response_cache: Dict[int, StepResponse] = {}
```
```python
# _execute — único ajuste: force_refresh=True na chamada de refresh do backbone
def _execute(self, ordered_indexes: List[int], schedule: Set[int]) -> List[Tuple[int, StepResponse]]:
    refreshes: int = 0
    results: List[Tuple[int, StepResponse]] = self._execute_raw(ordered_indexes, schedule)
    while self._needs_reactive_refresh(results) and refreshes < self.MAX_REACTIVE_REFRESHES:
        refreshes += 1
        print(
            f"ReplayOptimizer: detected recoverable status in schedule — refreshing backbone before "
            f"retrying (attempt {refreshes}/{self.MAX_REACTIVE_REFRESHES})..."
        )
        self._execute_raw(self.backbone, set(self.backbone), force_refresh=True)
        results = self._execute_raw(ordered_indexes, schedule)
    return results
```
```python
# _execute_raw — consulta/alimenta o cache, executa só os índices ausentes (ou todos, se forçado)
def _execute_raw(
        self, ordered_indexes: List[int], schedule: Set[int], force_refresh: bool = False
) -> List[Tuple[int, StepResponse]]:
    missing: List[int] = [
        index for index in ordered_indexes
        if force_refresh or index not in self._backbone_response_cache
    ]
    fresh_by_index: Dict[int, StepResponse] = {}
    if missing:
        fresh: List[Tuple[int, StepResponse]] = self.schedule_executor.execute_schedule(
            missing, schedule, annotate=False
        )
        self.requests_made += len(missing)
        if self.requests_made > self.max_requests:
            raise ValueError(
                f"ReplayOptimizer: teto de requisições atingido ({self.requests_made}/{self.max_requests}) — "
                f"abortando a busca."
            )
        fresh_by_index = dict(fresh)
        self._remember(fresh)
    return [
        (index, fresh_by_index[index] if index in fresh_by_index else self._backbone_response_cache[index])
        for index in ordered_indexes
    ]

def _remember(self, fresh: List[Tuple[int, StepResponse]]) -> None:
    for index, response in fresh:
        if index in self.backbone and not self.schedule_executor.needs_recovery(index, response):
            self._backbone_response_cache[index] = response
```

Regras de negócio novas:
- Um índice só é lido do cache se **não** houver `force_refresh` e ele já estiver em
  `self._backbone_response_cache`. Índices fora do backbone nunca são admitidos por
  `_remember` (guarda `index in self.backbone`), então nunca aparecem no cache — a checagem
  em `_execute_raw` já os trata como sempre ausentes, sem precisar de uma checagem adicional
  de pertencimento ao backbone ali (spec §3.1, §3.3).
- `_remember` só admite uma resposta cujo `self.schedule_executor.needs_recovery(index,
  response)` é `False` — mesmo predicado que já decide recuperação reativa, reaproveitado sem
  redefinição (spec §3.4). `status_code == 0` nunca entra no cache, porque `needs_recovery` já
  trata transporte falho como recuperável incondicionalmente.
- `requests_made` passa a somar só `len(missing)` — o número de índices que de fato bateram na
  rede — nunca mais `len(ordered_indexes)`. É estritamente `<=` ao valor de hoje para a mesma
  busca (spec §3.6); a mensagem de erro do teto não muda de texto, só o valor reportado.
- `⚠️` A chamada de refresh dentro de `_execute` (`:105` hoje) é o único lugar do arquivo que
  passa `force_refresh=True` — todas as outras chamadas a `_execute_raw` (via `_execute`
  normal, chamado por `_confirm`/`_attempt`) usam o default `False`. Não espalhar
  `force_refresh=True` para nenhuma outra chamada.
- `⚠️` Não adicionar reset explícito de `self._backbone_response_cache` em nenhum ponto — a
  mesma convenção de `self.backbone`/`self.requests_made` (instância vive só para uma chamada
  de `optimize()`, spec §3.2).

**Critérios de aceite (TDD — escrever os testes abaixo, confirmar que falham pelo motivo certo
contra o código atual, só então implementar):**
- [ ] `test_execute_raw_serves_second_call_for_same_backbone_index_from_cache_without_hitting_network`:
  `optimizer.backbone = [0]`; `FakeScheduleExecutor` com
  `responses_by_call=[{0: _ok(200)}, {0: _ok(999)}]`. Duas chamadas seguidas a
  `optimizer._execute_raw([0], {0})` (sem `force_refresh`) retornam `status_code == 200` nas
  duas vezes, e `len(executor.calls) == 1` (a segunda nunca bate na rede).
- [ ] `test_execute_raw_force_refresh_ignores_cache_and_overwrites_it`: mesma configuração;
  primeira chamada sem `force_refresh` (cacheia 200); segunda chamada com
  `force_refresh=True` retorna `999` e sobrescreve o cache (`len(executor.calls) == 2`); uma
  terceira chamada sem `force_refresh` volta a servir do cache — `999`, sem novo hit de rede
  (`len(executor.calls)` continua `2`).
- [ ] `test_execute_raw_requests_made_counts_only_network_calls_not_cache_hits`: duas chamadas
  a `optimizer._execute_raw([0], {0})` sem `force_refresh` deixam `optimizer.requests_made ==
  1`, não `2` (spec §3.6).
- [ ] `test_execute_raw_does_not_cache_response_that_needs_recovery`:
  `reference_status_codes={0: 200}`, `responses_by_call=[{0: _ok(500)}, {0: _ok(200)}]`.
  Primeira chamada retorna `500` (diverge da referência, `needs_recovery` é `True`) e **não**
  fica em cache; segunda chamada sem `force_refresh` ainda bate na rede e retorna `200`
  (`len(executor.calls) == 2`).
- [ ] `test_execute_raw_does_not_cache_transport_failure_status_zero`:
  `responses_by_call=[{0: _ok(0)}, {0: _ok(200)}]`. Mesmo padrão do teste acima — `0` nunca
  fica congelado, segunda chamada bate na rede de novo (`len(executor.calls) == 2`).
- [ ] `test_execute_raw_caches_response_when_index_has_no_reference_status_code` (spec §5.2,
  caso residual aceito): sem `reference_status_codes` para o índice,
  `responses_by_call=[{0: _ok(500)}, {0: _ok(999)}]`. `needs_recovery` devolve `False` (sem
  referência conhecida) mesmo para `500`, então a primeira resposta **é** admitida no cache; a
  segunda chamada sem `force_refresh` continua servindo `500` do cache
  (`len(executor.calls) == 1`).
- [ ] `test_execute_raw_never_caches_indexes_outside_backbone` (spec §3.1):
  `optimizer.backbone = [0]`; duas chamadas a `optimizer._execute_raw([5], {5})` com respostas
  diferentes por chamada batem na rede as duas vezes (`len(executor.calls) == 2`), porque `5`
  nunca é elegível ao cache.
- [ ] `test_execute_raw_caches_multiple_backbone_indexes_independently` (spec §5.5):
  `optimizer.backbone = [0, 1]`; `optimizer._execute_raw([0, 1], {0, 1})` executado duas vezes
  seguidas sem `force_refresh` faz só uma chamada real (`len(executor.calls) == 1`) e devolve
  os mesmos dois valores nas duas vezes.
- [ ] `test_execute_reactive_refresh_forces_real_reexecution_ignoring_cache` (spec §3.5): com
  `optimizer.backbone = [0]` e `optimizer._backbone_response_cache[0]` pré-semeado com uma
  resposta obsoleta antes de rodar `optimizer._execute([5], {5})` sobre um
  `FakeScheduleExecutor` cuja primeira resposta de `5` é recuperável
  (`reference_status_codes={5: 200}`, `responses_by_call=[{5: _ok(401)}, {0: _ok(200)}, {5:
  _ok(200)}]`) — o refresh dentro de `_execute` bate na rede para o índice `0` mesmo com o
  cache pré-semeado (`executor.calls[1].ordered_indexes == [0]`) e sobrescreve
  `optimizer._backbone_response_cache[0]` com a resposta nova (`status_code == 200`).
- [ ] `test_execute_reactive_refresh_final_diverging_response_is_never_cached` (spec §5.3):
  `optimizer.backbone = [0]`, `reference_status_codes={0: 200, 5: 200}`,
  `default_response=_ok(401)` para tudo. `optimizer._execute([5], {5})` esgota
  `MAX_REACTIVE_REFRESHES` e devolve `401` (mesmo resultado de hoje,
  `len(executor.calls) == 5` — não-regressão de
  `test_execute_gives_up_after_two_refreshes_and_returns_last_result`), e
  `0 not in optimizer._backbone_response_cache` — a resposta ruim do backbone nunca fica
  congelada, porque diverge da própria referência.
- [ ] `test_optimize_end_to_end_executes_backbone_index_only_once_across_reduce_and_confirm`
  (spec §0/§1.1, a demonstração fim a fim do bug corrigido): `optimize(workspace, "run-1", 0,
  233, SUCCESS_CRITERIA)` com `smart_schedule=([0, 153, 233], {0, 153, 233})`,
  `existing_indexes=[0, 153, 233]`, `default_response=_ok(200)` — cenário que hoje já existe em
  `test_optimize_end_to_end_reduces_interior_anchor_not_needed_by_target`, estendido com a
  asserção nova: `sum(1 for call in executor.calls if 0 in call.ordered_indexes) == 1`. O
  índice `0` (que está em todo `final_list` de `_reduce_anchors` e da confirmação final) só é
  executado de verdade uma vez, na fase 1 — é exatamente o cenário do site cujo `from_index`
  muda de sessão a cada hit real, com a diferença de que agora a segunda/terceira reexecução
  nunca acontece.
- [ ] Não-regressão — `uv run pytest tests/unit/test_replay_optimizer.py -q` continua 100%
  verde sem nenhuma asserção existente alterada (em particular
  `test_run_phase1_calls_execute_schedule_once_with_backbone_and_annotate_false`,
  `test_run_phase1_increments_requests_made_by_backbone_size`,
  `test_execute_retries_once_after_recoverable_status_then_succeeds`,
  `test_execute_gives_up_after_two_refreshes_and_returns_last_result`,
  `test_execute_treats_transport_failure_status_zero_as_recoverable`,
  `test_run_phase2_elimination_restores_candidate_after_refreshes_exhausted`,
  `test_execute_does_not_refresh_when_status_matches_reference`,
  `test_optimize_confirmation_failure_writes_no_file_and_returns_none`,
  `test_optimize_final_list_has_no_duplicate_when_to_index_equals_from_index` (spec §5.4 — o
  resultado continua `[5]`, sem nenhuma requisição de rede extra na confirmação final, ainda
  que nenhum teste conte isso explicitamente) e todos os testes de `_reduce_anchors` — que
  nunca setam `optimizer.backbone`, então continuam com `self.backbone == []` e o cache nunca
  ativa para eles, preservando exatamente o comportamento de hoje).
- [ ] Não-regressão geral — `uv run pytest -q` (suíte completa do projeto) passa sem quebrar
  nenhum outro teste fora de `test_replay_optimizer.py` (nenhum outro arquivo constrói
  `ReplayOptimizer` diretamente além dele e do código de produção em `cli_handlers.py`, que
  não muda nesta task).
