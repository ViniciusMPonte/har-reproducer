# Plano de Implementação — Steps Pulados Quebram o Schedule do Replay Slice

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `ReplayRunner`: `_schedule_slice` filtra o range contra os steps que existem de verdade

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py` (`ReplayRunner._schedule_slice`)

**Contexto:**
`replay --mode slice` quebra com `FileNotFoundError` sempre que o intervalo `[--from,
--to]` (ou o default, do primeiro ao último step existente) atravessa um índice
pulado por `StepSkipEvaluator` (protocolo `ws`/`wss` ou método em
`skip_rules.methods`) — esses índices nunca têm `curls/req_XXXX.curl.sh`, mas
`_schedule_slice` monta o range com `range()` puro, sem checar quais índices de fato
existem em disco (spec seção 1). `_schedule_all` já resolve isso corretamente usando
`_existing_step_indexes()` como fonte de verdade (spec seção 2) — esta task aplica o
mesmo princípio a `_schedule_slice`.

**Estado atual:**
```python
def _schedule_slice(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
    existing: List[int] = self._existing_step_indexes()
    effective_from: int = from_index if from_index is not None else 0
    effective_to: int = to_index if to_index is not None else max(existing)
    ordered_indexes: List[int] = list(range(effective_from, effective_to + 1))
    return ordered_indexes, set(ordered_indexes)
```
- `existing` só é usado para achar `max(existing)` (o `--to` default) — o range em si
  ignora `existing` e assume contiguidade total entre `effective_from` e
  `effective_to`.

**Estado esperado depois:**
```python
def _schedule_slice(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
    existing: List[int] = self._existing_step_indexes()
    effective_from: int = from_index if from_index is not None else 0
    effective_to: int = to_index if to_index is not None else max(existing)
    ordered_indexes: List[int] = [index for index in existing if effective_from <= index <= effective_to]
    return ordered_indexes, set(ordered_indexes)
```
- `ordered_indexes` passa a ser um subconjunto de `existing` (a lista real de índices
  com curl file), filtrado pelo intervalo `[effective_from, effective_to]`, em vez de
  uma sequência aritmética que pode incluir índices inexistentes.
- ⚠️ Não alterar `_existing_step_indexes` nem a lógica de `effective_from`/
  `effective_to` — a única mudança é a linha que constrói `ordered_indexes` (spec
  seção 3.1).
- ⚠️ `existing` já vem ordenado (`_existing_step_indexes`, `sorted(indexes)`) — a list
  comprehension preserva essa ordem crescente, não precisa de `sorted()` adicional.
- ⚠️ Um intervalo sem nenhum índice existente (ex.: fora do range do HAR, ou cobrindo
  só steps pulados) produz `ordered_indexes = []`, que já cai no `ValueError`
  existente em `_run_schedule` (linha 60-61, "schedule vazio") — nenhum tratamento
  adicional necessário (spec seção 5).

**Critérios de aceite:**
- [ ] Com um workspace onde `curls/` tem os índices `{0, 1, 2}` (sem buraco),
  `_schedule_slice(None, None)` retorna `([0, 1, 2], {0, 1, 2})` — idêntico ao
  comportamento anterior à mudança (garantia de não-regressão para o caso comum).
- [ ] Com um workspace onde `curls/` tem os índices `{0, 1, 3, 4}` (índice 2
  pulado/inexistente), `_schedule_slice(None, None)` retorna `([0, 1, 3, 4], {0, 1, 3,
  4})` — o índice 2 nunca aparece em `ordered_indexes` nem em `schedule`.
- [ ] Mesmo workspace, `_schedule_slice(0, 2)` retorna `([0, 1], {0, 1})` — o índice 2
  (dentro do intervalo pedido, mas sem curl file) é filtrado, sem lançar exceção.
- [ ] Mesmo workspace, `_schedule_slice(3, 4)` retorna `([3, 4], {3, 4})`.
- [ ] Mesmo workspace, `_schedule_slice(10, 20)` (intervalo fora de qualquer índice
  existente) retorna `([], set())` — `run_slice` propaga isso para `_run_schedule`,
  que levanta `ValueError("ReplayRunner: schedule vazio — nenhum step para
  processar.")`, sem `FileNotFoundError`.
- [ ] Reprodução ponta a ponta: rodando `replay --mode slice` (sem `--from`/`--to`)
  contra o workspace de `arquivos-har/progressofit.har` (steps 78, 90, 166 pulados
  por serem `ws://`), o comando percorre todos os steps existentes até o 237 sem
  lançar `FileNotFoundError`, e imprime o resultado final de `Replay Validation
  Result`.
