# Plano de Implementação — Steps Pulados Quebram o Schedule do Replay List

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `ReplayRunner`: `_schedule_list` valida os índices do `--steps-file` contra os steps que existem de verdade, reaproveitando o mesmo helper em `_schedule_smart`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py` (`ReplayRunner._schedule_list`, `ReplayRunner._schedule_smart`, novo `ReplayRunner._require_all_existing`)

**Contexto:**
`replay --mode list` reexecuta exatamente os índices listados em `--steps-file`, na
ordem em que aparecem no arquivo. `_schedule_list` lê esses índices e devolve o
schedule sem checar se cada um corresponde a um curl file real em disco — o único dos
quatro métodos `_schedule_*` que nunca consulta `_existing_step_indexes()`. Quando o
arquivo lista um índice pulado por `skip_rules` (ex.: step `ws://`) ou fora do
intervalo existente, o comando quebra com `FileNotFoundError` não tratado dentro do
loop de `_run_schedule` — e, pior que em `slice`/`smart`, qualquer step válido que
apareça **antes** do inválido no arquivo já dispara requisição HTTP real antes do
crash (spec seção 1, reproduzido com `1\n2\n78\n3` contra o workspace de
`progressofit.har`: steps 1 e 2 executam de verdade, quebra no 78, nunca chega no 3).

`_schedule_smart` já resolve exatamente este problema para o `target` de `--to`
(spec anterior, `docs/20260805 Steps Pulados Quebram o Schedule do Replay Smart/`,
commit `15beffa`): calcula `existing_set` e levanta `ValueError` claro antes de montar
qualquer schedule. Esta task aplica o mesmo princípio a `_schedule_list` — mas em vez
de duplicar o `if`/`raise` inline dentro dos dois métodos, extrai um `@staticmethod`
novo (`_require_all_existing`) dentro da própria classe `ReplayRunner`, reaproveitado
pelos dois pontos (spec seção 3.1/3.2).

**Estado atual:**
```python
def _schedule_smart(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
    existing: List[int] = self._existing_step_indexes()
    existing_set: Set[int] = set(existing)
    floor: int = from_index if from_index is not None else 0
    target: int = to_index if to_index is not None else max(existing)
    if target not in existing_set:
        raise ValueError(
            f"ReplayRunner: step alvo {target} não existe no workspace (nenhum curl file em disco) — "
            f"provavelmente foi pulado por skip_rules ou está fora do intervalo de steps existentes."
        )

    schedule: Set[int] = {target}
    pending: Set[int] = {target}
    while pending:
        current: int = pending.pop()
        self._expand_pending(current, floor, existing_set, schedule, pending)

    return sorted(schedule), schedule
```
```python
def _schedule_list(self, steps_file: Path) -> Tuple[List[int], Set[int]]:
    lines: List[str] = steps_file.read_text(encoding="utf-8").splitlines()
    ordered_indexes: List[int] = [int(line.strip()) for line in lines if line.strip()]
    return ordered_indexes, set(ordered_indexes)
```
- `_schedule_smart` já tem a checagem `if target not in existing_set: raise
  ValueError(...)` inline — único lugar do arquivo com essa lógica hoje.
- `_schedule_list` não calcula `existing_set`, não chama `_existing_step_indexes()`,
  e devolve `ordered_indexes` direto do arquivo, sem nenhuma validação.

**Estado esperado depois:**
- Novo método, dentro da classe `ReplayRunner` (sem função de módulo, sem arquivo
  novo — `guia_de_estilo.md`, "nada solto no módulo"), posicionado ao lado dos demais
  `_schedule_*`:
  ```python
  @staticmethod
  def _require_all_existing(indexes: Iterable[int], existing_set: Set[int]) -> None:
      missing: List[int] = sorted({index for index in indexes if index not in existing_set})
      if missing:
          raise ValueError(
              f"ReplayRunner: step(s) {missing} não existem no workspace (nenhum curl file em disco) — "
              f"provavelmente foram pulados por skip_rules ou estão fora do intervalo de steps existentes."
          )
  ```
- `_schedule_smart` troca o `if`/`raise` inline pela chamada ao helper, com
  `{target}` (um conjunto de um único elemento) — mesmo comportamento, mensagem
  reformulada de "step alvo X não existe..." para "step(s) [X] não existem...":
  ```python
  def _schedule_smart(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
      existing: List[int] = self._existing_step_indexes()
      existing_set: Set[int] = set(existing)
      floor: int = from_index if from_index is not None else 0
      target: int = to_index if to_index is not None else max(existing)
      self._require_all_existing({target}, existing_set)

      schedule: Set[int] = {target}
      pending: Set[int] = {target}
      while pending:
          current: int = pending.pop()
          self._expand_pending(current, floor, existing_set, schedule, pending)

      return sorted(schedule), schedule
  ```
- `_schedule_list` passa a calcular `existing_set` e validar `ordered_indexes` por
  completo, antes de devolver o schedule — nenhum step roda se qualquer índice do
  arquivo não existir:
  ```python
  def _schedule_list(self, steps_file: Path) -> Tuple[List[int], Set[int]]:
      existing_set: Set[int] = set(self._existing_step_indexes())
      lines: List[str] = steps_file.read_text(encoding="utf-8").splitlines()
      ordered_indexes: List[int] = [int(line.strip()) for line in lines if line.strip()]
      self._require_all_existing(ordered_indexes, existing_set)
      return ordered_indexes, set(ordered_indexes)
  ```
- `Iterable` precisa ser importado de `typing` no topo do arquivo (`from typing import
  ClassVar, Iterable, List, Optional, Set, Tuple`) — hoje não está na lista de imports.
- ⚠️ A validação em `_schedule_list` cobre **todos** os índices do arquivo de uma vez
  (não parcial/incremental) — é isso que evita que steps válidos antes de um índice
  inválido disparem requisição real (spec seção 3.1, agravante da seção 1).
- ⚠️ `_expand_pending` (expansão recursiva de dependências do `smart`) **não** muda
  e **não** passa a usar `_require_all_existing` — continua descartando
  silenciosamente um `origin_step` fora de `existing_set` (spec seção 5, decisão já
  tomada e implementada na spec anterior do smart). Só a checagem do `target` inicial
  em `_schedule_smart` passa a usar o helper novo.
- ⚠️ Não alterar `_schedule_all`, `_schedule_slice`, `_run_schedule`,
  `_existing_step_indexes` nem qualquer outro método deste arquivo — fora de escopo
  (spec seção 1).

**Critérios de aceite:**
- [ ] `replay --mode list --steps-file <arquivo com "78">` (step pulado, workspace de
      `progressofit.har`) levanta `ValueError` listando `[78]`, sem
      `FileNotFoundError` nem traceback de `pathlib`/`open`, e sem nenhum step
      executado (nenhuma linha `Step N completed with status ...` impressa).
- [ ] `replay --mode list --steps-file <arquivo com "9999">` (fora do intervalo
      existente) levanta o mesmo tipo de `ValueError`, citando `[9999]`.
- [ ] `replay --mode list --steps-file <arquivo com "1\n2\n78\n3">` levanta o
      `ValueError` **antes** de imprimir qualquer `Step N completed` — nenhuma
      requisição real dos steps 1/2/3 é disparada (verificação do agravante da spec
      seção 1, comparando com o comportamento atual que executa 1 e 2 antes de
      quebrar).
- [ ] `replay --mode list --steps-file <arquivo com "1\n78\n2\n166">` (múltiplos
      índices inexistentes) levanta um único `ValueError` citando `[78, 166]`
      (ordenados), não um erro por tentativa.
- [ ] Não-regressão: `replay --mode list --steps-file <arquivo com "0\n1\n2">`
      continua funcionando exatamente como antes (schedule `([0, 1, 2], {0, 1, 2})`,
      os três steps executam e o resultado final é impresso).
- [ ] Não-regressão: `replay --mode list --steps-file <arquivo com "5\n2\n1">`
      (ordem customizada) continua executando na ordem do arquivo, não ordenado.
- [ ] Não-regressão: `replay --mode list --steps-file <arquivo com "1\n1\n2">`
      (duplicatas) continua reexecutando a linha duplicada — comportamento
      inalterado por esta task.
- [ ] Não-regressão: `replay --mode smart --to 78` (step pulado) continua levantando
      `ValueError` (agora via `_require_all_existing`, mensagem "step(s) [78] não
      existem..." em vez de "step alvo 78 não existe...") — mesma classe de erro,
      texto ligeiramente reformulado, sem `FileNotFoundError`.
- [ ] Não-regressão: `replay --mode smart` sem `--to` (default, `target =
      max(existing)`) continua rodando sem erro contra o workspace de
      `progressofit.har` — o helper nunca levanta para o caminho default.
- [ ] Não-regressão: `replay --mode smart --to 222` e `--to 159` (índices existentes,
      com dependências recursivas via `_expand_pending`) continuam agendando
      exatamente o mesmo schedule de antes desta task — a mudança em `_schedule_smart`
      não altera `_expand_pending` nem a lógica de expansão, só a validação inicial do
      `target`.
