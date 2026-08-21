# Plano de Implementação — Recuperação por Divergência da Referência

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## Decisões dos pontos abertos da spec (§6)

1. **Posição do parâmetro `comparator` em `Engine.__init__`**: depois de `validator`,
   antes de `success_criteria` — como a spec propôs.
2. **`StepRetryPolicy.RECOVERABLE_STATUS_CODES` é removido** (T05) — confirmado por busca
   que fica sem nenhum uso depois de T02/T03/T04.

## Nota de execução

`pytest tests/unit -q` depois de cada task. Nenhuma task toca fixtures de rede — a suíte
inteira roda rápida em todas.

---

## [T01] — `ReplayResultComparator`: método novo `needs_recovery`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/replay/replay_result_comparator.py`, `tests/unit/test_replay_result_comparator.py`

**Contexto:**
Base de toda a etapa. `matches_original` já existe e não muda — ele é usado hoje para o
veredito final de um replay, onde "sem referência" corretamente significa "não confirmado".
`needs_recovery` é um método **novo**, com semântica diferente e deliberada: incerteza não
é divergência. Sem essa distinção, reaproveitar `matches_original` como gatilho de
recuperação faria qualquer step sem referência gravada (comum em fixture de teste, e
possível em produção) disparar recuperação por engano — verificado contra os testes
existentes de `ReplayRunner` antes desta task ser escrita (nenhum grava
`original_responses/`, e nenhum deveria passar a exercitar recuperação por causa disso).

**Estado atual:**
```python
class ReplayResultComparator:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace: Workspace = workspace

    def matches_original(self, index: int, response: StepResponse) -> bool:
        original: Optional[int] = self.original_status_code(index)
        if original is None:
            print(f"Could not find status_code in original response for step {index} to compare.")
            return False
        return original == response.status_code

    def original_status_code(self, index: int) -> Optional[int]:
        ...
```

**Estado esperado depois:**
```python
def needs_recovery(self, index: int, response: StepResponse) -> bool:
    if response.status_code == 0:
        return True
    reference: Optional[int] = self.original_status_code(index)
    if reference is None:
        return False
    return response.status_code != reference
```

⚠️ `status_code == 0` é o **primeiro** teste, explícito, e não depende de
`original_status_code` ser chamado — falha de transporte é sempre recuperável mesmo que
não exista referência nenhuma para aquele step.
⚠️ `matches_original`/`original_status_code`/`_read_reference_text` **não mudam** — nem uma
linha. `needs_recovery` reaproveita `original_status_code`, não `matches_original`.

**Critérios de aceite:**
- [x] `needs_recovery(5, StepResponse(status_code=0))`, sem nenhuma referência gravada:
      `True`.
- [x] `needs_recovery(5, StepResponse(status_code=200))`, sem nenhuma referência gravada:
      `False` — é o caso que a spec corrige em relação à primeira versão.
- [x] Com `original_responses/res_0005.json` gravado com `status_code=200`:
      `needs_recovery(5, StepResponse(status_code=401))` → `True` (diverge).
- [x] Mesmo cenário: `needs_recovery(5, StepResponse(status_code=200))` → `False` (bate).
- [x] Com `original_responses/res_0005.json` gravado com `status_code=403`:
      `needs_recovery(5, StepResponse(status_code=403))` → `False` — é o caso central da
      spec (§1.1): um `403` legítimo não deve disparar recuperação.
- [x] Não-regressão: todos os testes existentes de `matches_original`/`original_status_code`
      passam sem alteração — nenhuma linha deles muda.

---

## [T02] — `ScheduleExecutor` + `ReplayRunner`: contrato e implementação de `needs_recovery`

**Depende de:** T01.
**Arquivos envolvidos:** `har_reproducer/contracts/schedule_executor.py`, `har_reproducer/replay/replay_runner.py`, `tests/support/fake_schedule_executor.py`, `tests/unit/test_replay_runner.py`

**Contexto:**
`ScheduleExecutor` é o contrato que `ReplayOptimizer` usa para falar com `ReplayRunner`
sem conhecê-lo diretamente (`cli_handlers.py:152`, `schedule_executor=runner` — é sempre um
`ReplayRunner` de verdade). Ganha o método que a T04 (`ReplayOptimizer`) vai consumir.
`ReplayRunner._run_step`'s `recover()` já tem `index` na closure e `self.comparator` como
atributo — só troca o corpo do `if`.

**Estado atual:**
```python
class ScheduleExecutor(Protocol):
    def execute_schedule(self, ordered_indexes, schedule, annotate=True) -> List[Tuple[int, StepResponse]]: ...
    def compute_smart_schedule(self, from_index, to_index) -> Tuple[List[int], Set[int]]: ...
    def existing_step_indexes(self) -> List[int]: ...
```
```python
def recover(response: StepResponse) -> bool:
    if response.status_code not in StepRetryPolicy.RECOVERABLE_STATUS_CODES:
        return False
    print(f"Detected {response.status_code}. Attempting deterministic recovery (token refresh)...")
    return True
```

**Estado esperado depois:**
```python
class ScheduleExecutor(Protocol):
    ...
    def needs_recovery(self, index: int, response: StepResponse) -> bool: ...
```
```python
# ReplayRunner
def needs_recovery(self, index: int, response: StepResponse) -> bool:
    return self.comparator.needs_recovery(index, response)
```
```python
def recover(response: StepResponse) -> bool:
    if not self.comparator.needs_recovery(index, response):
        return False
    print(f"Detected {response.status_code} (reference expects a different status). "
          f"Attempting deterministic recovery (token refresh)...")
    return True
```

⚠️ Nenhuma mudança de construtor em `ReplayRunner` — `comparator` já é injetado
(`replay_runner.py:27,39`).

`tests/support/fake_schedule_executor.py` ganha `needs_recovery`, para servir T04
(`ReplayOptimizer` usa `FakeScheduleExecutor` em seus testes, não `ReplayRunner`):
```python
def __init__(self, ..., reference_status_codes: Optional[Dict[int, int]] = None) -> None:
    ...
    self.reference_status_codes: Dict[int, int] = reference_status_codes or {}

def needs_recovery(self, index: int, response: StepResponse) -> bool:
    if response.status_code == 0:
        return True
    if index not in self.reference_status_codes:
        return False
    return response.status_code != self.reference_status_codes[index]
```

⚠️ **Novo parâmetro por palavra-chave com default `None`, ao final da lista** — todos os
`FakeScheduleExecutor(...)` existentes usam argumentos nomeados (verificado: nenhuma
chamada posicional em `tests/unit/test_replay_optimizer.py`), então nenhuma chamada
existente precisa mudar por causa da assinatura — só as que T04 identifica precisando de
`reference_status_codes` explícito.

**Critérios de aceite:**
- [x] `ReplayRunner.needs_recovery(index, response)` delega exatamente a
      `self.comparator.needs_recovery(index, response)` (teste com um comparator fake ou
      real gravando a chamada).
- [x] `_run_step` com uma resposta cujo status bate com a referência gravada em
      `original_responses/`: uma única tentativa, sem a mensagem de recuperação impressa.
- [x] `_run_step` com uma resposta cujo status diverge de uma referência gravada: duas
      tentativas (a mensagem de recuperação aparece), respeitando
      `StepRetryPolicy.MAX_STEP_ATTEMPTS`.
- [x] `FakeScheduleExecutor.needs_recovery`: `status_code=0` é sempre `True`,
      independente de `reference_status_codes`.
- [x] `FakeScheduleExecutor.needs_recovery`: índice sem entrada em `reference_status_codes`
      é sempre `False` — é o que preserva os testes de `test_replay_optimizer.py` que usam
      `404`/`200` para exercitar validação, não recuperação (ver T04).
- [ ] Não-regressão: os 15 testes existentes de `test_replay_runner.py` que chamam
      `_run_step`/`execute_schedule`/`run_all`/`run_slice` sem gravar
      `original_responses/` passam sem alteração — nenhum precisa de fixture nova, porque
      "sem referência" agora significa "sem recuperação" (T01).
      **Não confirmado literalmente**: `test_run_schedule_hybrid_verdict_fails_when_intermediate_step_broken`
      precisou de um ajuste de fixture (uma resposta extra no `StubHttpTransport`) porque
      `status_code == 0` ser sempre recuperável — também em `ReplayRunner`, não só no
      `ReplayOptimizer` — faz a retentativa consumir a resposta que o teste reservava para
      o step seguinte. Efeito colateral real do design (intencional, ver spec §5.2), não
      antecipado neste critério; ajuste de fixture confirmado com o usuário durante a T02,
      nenhuma linha de produção mudou por causa disso.

---

## [T03] — `ReplayOptimizer`: `_needs_reactive_refresh` usa `needs_recovery`; remove a lista fixa

**Depende de:** T02.
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py`, `tests/unit/test_replay_optimizer.py`

**Contexto:**
É aqui que a maior parte da migração de teste mora. Levantamento completo do arquivo (23
testes): **3** usam `401`/`0` para exercitar recuperação de propósito e precisam de
`reference_status_codes` explícito para continuar significando o mesmo depois da mudança;
os outros **20** usam `200`/`404` para exercitar validação/eliminação, nunca recuperação, e
continuam passando sem tocar — porque "sem referência configurada" agora é "sem
recuperação" (T01/T02), que é exatamente o que eles já assumiam meio que por acidente sob
a lista fixa antiga (`404` nunca esteve na lista).

**Estado atual:**
```python
class ReplayOptimizer:
    RECOVERABLE_STATUS_CODES: ClassVar[Set[int]] = StepRetryPolicy.RECOVERABLE_STATUS_CODES | {0}
    ...
    @classmethod
    def _needs_reactive_refresh(cls, results: List[Tuple[int, StepResponse]]) -> bool:
        return any(response.status_code in cls.RECOVERABLE_STATUS_CODES for _, response in results)
```

**Estado esperado depois:**
```python
class ReplayOptimizer:
    # RECOVERABLE_STATUS_CODES removido
    ...
    def _needs_reactive_refresh(self, results: List[Tuple[int, StepResponse]]) -> bool:
        return any(self.schedule_executor.needs_recovery(index, response) for index, response in results)
```

⚠️ **Os três testes que precisam de `reference_status_codes` explícito, e o valor exato:**

| teste | linha atual (aprox.) | status usado | acrescentar |
|---|---|---|---|
| `test_execute_retries_once_after_recoverable_status_then_succeeds` | 178 | `401` no step `5` | `reference_status_codes={5: 200}` |
| `test_execute_gives_up_after_two_refreshes_and_returns_last_result` | 199 | `401` (default) no step `5` | `reference_status_codes={5: 200}` |
| `test_run_phase2_elimination_restores_candidate_after_refreshes_exhausted` | 234 | `401` (default), alvo `9` | `reference_status_codes={9: 200}` |

`test_execute_treats_transport_failure_status_zero_as_recoverable` (linha ~215) **não**
precisa de nenhuma mudança — `status_code=0` é sempre recuperável por construção (T01),
sem depender de referência.

**Critérios de aceite:**
- [ ] Os três testes da tabela passam com `reference_status_codes` acrescentado, e falham
      (pelo motivo certo — `needs_recovery` devolvendo `False` por falta de referência) se
      revertidos para o estado atual sem o parâmetro — confirmar isso antes de comitar.
      **Confirmado parcialmente**: `test_execute_retries_once_after_recoverable_status_then_succeeds`
      e `test_execute_gives_up_after_two_refreshes_and_returns_last_result` falham pelo
      motivo certo sem `reference_status_codes`. `test_run_phase2_elimination_restores_candidate_after_refreshes_exhausted`
      **não** discrimina — passa com ou sem o parâmetro, porque sua asserção só verifica
      `ReplayOptimizerAborted`, que ocorre de qualquer forma já que a validação final
      (`401 != 200`) falha independente de a recuperação disparar. Contagem do
      levantamento também não fechou: o arquivo tem 20 testes antes desta task (21 depois
      de somar o novo), não 23 como o parágrafo de contexto desta task afirma.
- [x] Novo teste: `test_execute_does_not_refresh_when_status_matches_reference` — step com
      `reference_status_codes={5: 403}`, resposta `403`: `_needs_reactive_refresh` devolve
      `False`, nenhuma tentativa extra. É o teste que demonstra o objetivo central da spec
      (§1.1): um `403` legítimo não dispara recuperação.
- [x] Não-regressão: os 20 testes restantes do arquivo (incluindo todos os que usam `404`
      como resposta de falha de validação) passam sem qualquer alteração de código.
- [x] `ReplayOptimizer.RECOVERABLE_STATUS_CODES` não existe mais — `grep` confirma.

---

## [T04] — `Engine.handle_recovery`: ganha `step_index`, usa `ReplayResultComparator`

**Depende de:** T01.
**Arquivos envolvidos:** `har_reproducer/engines/engine.py`, `tests/unit/test_engine.py`

**Contexto:**
As duas premissas antigas ("500 nunca é recuperável", "401 sempre é") deixam de valer — a
única pergunta passa a ser "este status bate com o que este step produziu quando passou?".
Os dois testes existentes tinham nome e corpo desenhados em torno da lista fixa; são
substituídos por dois que refletem a semântica nova, mais um cobrindo o caso central.

**Estado atual:**
```python
def handle_recovery(self, response: StepResponse) -> bool:
    if response.status_code not in self.retry_policy.RECOVERABLE_STATUS_CODES:
        return False
    print(f"Detected {response.status_code}. Attempting deterministic recovery (token refresh)...")
    self.token_resolver.resolve_all(force=True)
    return True

def execute_step(self, step: Step) -> StepResponse:
    return self.retry_policy.execute(step.index, lambda: self._attempt_step(step), self.handle_recovery)
```
`Engine.__init__` (`engine.py:17-38`) não tem `comparator`.

**Estado esperado depois:**
```python
def handle_recovery(self, step_index: int, response: StepResponse) -> bool:
    if not self.comparator.needs_recovery(step_index, response):
        return False
    print(f"Detected {response.status_code} (reference expects a different status). "
          f"Attempting deterministic recovery (token refresh)...")
    self.token_resolver.resolve_all(force=True)
    return True

def execute_step(self, step: Step) -> StepResponse:
    return self.retry_policy.execute(
        step.index, lambda: self._attempt_step(step), lambda response: self.handle_recovery(step.index, response)
    )
```
`Engine.__init__` ganha `comparator: ReplayResultComparator`, entre `validator` e
`success_criteria` (posição decidida em §6 da spec).

⚠️ `StepRetryPolicy.execute`'s `recovery_fn: Callable[[StepResponse], bool]` **não muda** —
a lambda em `execute_step` absorve `step.index` antes de chamar `handle_recovery`.

**Estado atual dos dois testes que mudam de premissa:**
```python
def test_handle_recovery_does_nothing_for_non_recoverable_status(tmp_path: Path) -> None:
    ...
    handled: bool = engine.handle_recovery(StepResponse(status_code=500))
    assert handled is False
    assert token_resolver.calls == []

def test_handle_recovery_forces_token_refresh_for_recoverable_status(tmp_path: Path) -> None:
    ...
    handled: bool = engine.handle_recovery(StepResponse(status_code=401))
    assert handled is True
    assert token_resolver.calls == [RecordedResolveAllCall(True)]
```

**Estado esperado dos testes** — substituídos (não só ajustados: a premissa "500 nunca
recupera, 401 sempre recupera" some) por:
```python
def _write_original_response(tmp_path: Path, index: int, status_code: int) -> None:
    Workspace(tmp_path).original_response_file(index).write_text(
        StepResponse(status_code=status_code).model_dump_json(), encoding="utf-8"
    )

def test_handle_recovery_does_nothing_when_status_matches_reference(tmp_path: Path) -> None:
    _write_original_response(tmp_path, 5, status_code=403)
    token_resolver: FakeTokenResolver = FakeTokenResolver()
    engine: Engine = _engine(tmp_path, token_resolver, [])

    handled: bool = engine.handle_recovery(5, StepResponse(status_code=403))

    assert handled is False
    assert token_resolver.calls == []

def test_handle_recovery_forces_token_refresh_when_status_diverges_from_reference(tmp_path: Path) -> None:
    _write_original_response(tmp_path, 5, status_code=200)
    token_resolver: FakeTokenResolver = FakeTokenResolver()
    engine: Engine = _engine(tmp_path, token_resolver, [])

    handled: bool = engine.handle_recovery(5, StepResponse(status_code=401))

    assert handled is True
    assert token_resolver.calls == [RecordedResolveAllCall(True)]

def test_handle_recovery_forces_token_refresh_for_transport_failure_without_any_reference(tmp_path: Path) -> None:
    token_resolver: FakeTokenResolver = FakeTokenResolver()
    engine: Engine = _engine(tmp_path, token_resolver, [])

    handled: bool = engine.handle_recovery(5, StepResponse(status_code=0))

    assert handled is True
```

`_engine()` (helper de teste, `test_engine.py:29-45`) ganha um `ReplayResultComparator(Workspace(tmp_path))`
real no construtor — é I/O leve (lê arquivo), consistente com o `Workspace(tmp_path)` real
que o helper já usa.

**Critérios de aceite:**
- [x] Os três testes novos acima passam.
- [x] `test_handle_recovery_does_nothing_for_non_recoverable_status` e
      `test_handle_recovery_forces_token_refresh_for_recoverable_status` são **removidos**
      (não "ajustados" — a premissa que os nomeava não existe mais).
- [x] Não-regressão: os demais testes de `test_engine.py`
      (`test_skip_entry_persists_skipped_response`, `test_validate_final_true_when_no_success_criteria`,
      os de `DryEngine`, os de `_warn_missing_response_bodies`, `test_reproduce_keeps_returning_the_final_validation_result`)
      passam sem alteração — nenhum chama `handle_recovery` nem depende do construtor de
      `Engine` na posição afetada além de precisar do novo argumento posicional (ajustar
      só a chamada, não a lógica do teste).

---

## [T05] — `EngineFactory`: injeta o `ReplayResultComparator`; remove código morto

**Depende de:** T03, T04 (só depois dos três call sites migrados, `RECOVERABLE_STATUS_CODES` fica genuinamente sem uso).
**Arquivos envolvidos:** `har_reproducer/engines/construction/engine_factory.py`, `har_reproducer/reproduction/step_retry_policy.py`, `tests/unit/test_engine_factory.py`, `tests/unit/test_step_retry_policy.py`

**Contexto:**
Fecha a etapa: liga o `Engine` ao `ReplayResultComparator` de verdade, e remove a constante
que nenhum código de produção ou teste mais lê (confirmado por busca no repositório inteiro
antes de propor esta task — spec §6).

**Estado atual:**
```python
return engine_cls(
    har_path,
    self.workspace,
    session_store,
    self._build_tracker(...),
    TokenResolver(token_resolver_responses_dir, session_store, extractor_runner),
    StepSkipEvaluator(self.project_config.skip_rules),
    StepRetryPolicy(),
    Validator(),
    self.project_config.success_criteria,
    transport,
)
```
```python
# step_retry_policy.py
class StepRetryPolicy:
    MAX_STEP_ATTEMPTS: ClassVar[int] = 2
    RECOVERABLE_STATUS_CODES: ClassVar[Set[int]] = {400, 401}
```

**Estado esperado depois:**
```python
return engine_cls(
    har_path,
    self.workspace,
    session_store,
    self._build_tracker(...),
    TokenResolver(token_resolver_responses_dir, session_store, extractor_runner),
    StepSkipEvaluator(self.project_config.skip_rules),
    StepRetryPolicy(),
    Validator(),
    ReplayResultComparator(self.workspace),
    self.project_config.success_criteria,
    transport,
)
```
Import novo: `from har_reproducer.replay.replay_result_comparator import ReplayResultComparator`
(precedente já existe — `engine_factory.py:14` já importa `CurlTokenComment` de
`har_reproducer.replay`).
```python
# step_retry_policy.py
class StepRetryPolicy:
    MAX_STEP_ATTEMPTS: ClassVar[int] = 2
    # RECOVERABLE_STATUS_CODES removido
```

**Critérios de aceite:**
- [x] `EngineFactory.create(EngineMode.MAIN, ...)`:
      `engine.comparator` é uma instância de `ReplayResultComparator` apontando para o
      `workspace` correto.
- [x] `EngineFactory.create(EngineMode.DRY, ...)`: idem — `comparator` é injetado
      igualmente (não é condicional a `USES_NETWORK`; a comparação faz sentido nos dois
      modos, mesmo que `handle_recovery` raramente dispare em dry).
- [x] `StepRetryPolicy.RECOVERABLE_STATUS_CODES` não existe mais — `grep` no repositório
      inteiro confirma zero ocorrências, em produção e teste.
- [x] Não-regressão: `test_resolve_class_maps_modes_to_engine_classes`,
      `test_create_dry_ignores_http_transport`,
      `test_create_dry_uses_original_responses_directory`,
      `test_create_main_passes_through_transport_and_uses_real_responses_directory`,
      `test_llm_is_none_when_project_config_has_no_llm_settings` passam sem alteração de
      asserção.
- [x] Não-regressão: `pytest tests/unit -q` inteiro verde.
