# Plano de Implementação — Steps Pulados Quebram o Schedule do Replay Smart

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `ReplayRunner`: `_schedule_smart`/`_expand_pending` filtram target e dependências contra os steps que existem de verdade

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py` (`ReplayRunner._schedule_smart`, `ReplayRunner._expand_pending`)

**Contexto:**
`replay --mode smart` monta o schedule de execução a partir de um `target` (vindo de
`--to`, com default `max(existing)`) e expande recursivamente para os steps de origem
dos tokens usados nele (`_expand_pending`, via `CurlDependencyParser`). Nenhum dos dois
pontos (`target` inicial e `origin_step` recursivo) é validado contra
`_existing_step_indexes()` antes de `Workspace.curl_file(...).read_text(...)` — ambos
caem na mesma linha de leitura, dentro de `_expand_pending`. Quando o índice não tem
curl file (step pulado por `skip_rules`, ou fora do intervalo existente), o comando
quebra com `FileNotFoundError` não tratado, sem imprimir nenhum resultado (spec seção
1, reproduzido com `--to 78`, `--to 999`, `--to -1` contra o workspace de
`progressofit.har`).

**Estado atual:**
```python
def _schedule_smart(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
    existing: List[int] = self._existing_step_indexes()
    floor: int = from_index if from_index is not None else 0
    target: int = to_index if to_index is not None else max(existing)

    schedule: Set[int] = {target}
    pending: Set[int] = {target}
    while pending:
        current: int = pending.pop()
        self._expand_pending(current, floor, schedule, pending)

    return sorted(schedule), schedule

def _expand_pending(self, current: int, floor: int, schedule: Set[int], pending: Set[int]) -> None:
    curl_text: str = Workspace.curl_file(current).read_text(encoding="utf-8")
    dependencies = self.dependency_parser.parse(curl_text)
    for origin_step in dependencies.values():
        if origin_step >= floor and origin_step not in schedule:
            schedule.add(origin_step)
            pending.add(origin_step)
```
- `existing` já é calculado em `_schedule_smart`, mas só para achar o `max()` do
  default de `target` — nunca usado para validar um `target` explícito.
- `_expand_pending` não recebe `existing`/`existing_set` nenhum — não tem como saber
  se um `origin_step` é um índice real antes de tentar ler o arquivo dele.

**Estado esperado depois:**
- `_schedule_smart` calcula `existing_set: Set[int] = set(existing)` e levanta
  `ValueError` imediatamente se `target not in existing_set`, antes de montar
  `schedule`/`pending` — mensagem:
  `f"ReplayRunner: step alvo {target} não existe no workspace (nenhum curl file em disco) — provavelmente foi pulado por skip_rules ou está fora do intervalo de steps existentes."`
- `existing_set` passa a ser propagado para `_expand_pending` como novo parâmetro
  posicional (entre `floor` e `schedule`, mesma ordem dos demais parâmetros de
  contexto antes dos de acumulação).
- `_expand_pending` só agenda um `origin_step` para expansão (`schedule.add`/
  `pending.add`) se, além das duas condições já existentes (`>= floor` e `not in
  schedule`), ele também estiver em `existing_set`. Um `origin_step` fora de
  `existing_set` é descartado silenciosamente (sem erro) — a resolução daquele token
  cai no fallback já existente em `ReplayTokenResolver._resolve_one` (diretório de
  referência), o mesmo caminho já usado hoje para tokens marcados `"- probably
  static"` (spec seção 2/3.2).
- Código final completo esperado:
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

  def _expand_pending(
          self, current: int, floor: int, existing_set: Set[int], schedule: Set[int], pending: Set[int]
  ) -> None:
      curl_text: str = Workspace.curl_file(current).read_text(encoding="utf-8")
      dependencies = self.dependency_parser.parse(curl_text)
      for origin_step in dependencies.values():
          if origin_step >= floor and origin_step not in schedule and origin_step in existing_set:
              schedule.add(origin_step)
              pending.add(origin_step)
  ```
- ⚠️ `target` default (`--to` omitido → `max(existing)`) nunca dispara o `ValueError`
  — `max(existing)` é, por construção, sempre membro de `existing_set` (spec seção
  3.1). Não adicionar nenhuma lógica extra para esse caminho.
- ⚠️ `--from`/`floor` **não** precisa existir como step — continua sendo só um limite
  de comparação (`origin_step >= floor`), nunca um índice lido do disco. Não validar
  `floor` contra `existing_set` (spec seção 5).
- ⚠️ Não alterar `_schedule_slice`, `_schedule_all`, `_schedule_list` nem qualquer
  outro método deste arquivo — fora de escopo (spec seção 1).

**Critérios de aceite:**
- [x] `replay --mode smart --to 78` (step pulado, workspace de `progressofit.har`)
      levanta `ValueError` com a mensagem esperada, sem `FileNotFoundError` nem
      traceback de `pathlib`/`open`. Verificado.
- [x] `replay --mode smart --to 999` e `replay --mode smart --to -1` (fora do
      intervalo de steps existentes) levantam o mesmo `ValueError`, pela mesma razão.
      Verificado (as duas mensagens citam o índice pedido).
- [x] `replay --mode smart --to 222` (sem `--from`) continua agendando exatamente
      `{71, 222}` — mesmo resultado de antes da correção (dependência viva pra step
      71, demais dependências já `"- probably static"` continuam fora do schedule).
      ⚠️ Divergência observada e explicada: entre a escrita do plano e a validação, o
      token de dependência do step 71 cruzou o threshold de confirmação estática
      (`ReplayTokenResolver.STATIC_CONFIRMATION_THRESHOLD`, efeito colateral de uma
      execução anterior de `--to 222` feita durante a investigação desta mesma
      etapa) e passou a `"- probably static"` no `.curl.sh` em disco. Resultado real
      observado: agenda só `{222}`. Isso é o mecanismo funcionando como projetado
      (spec seção 3.2/2), não uma regressão desta task — o schedule para qualquer
      dependência que ainda exista continua idêntico ao que seria sem esta correção;
      só não há mais nenhuma dependência "viva" nesse workspace específico para
      demonstrar o caso.
- [x] `replay --mode smart --to 159` (sem `--from`) continua agendando exatamente
      `{155, 159}` — mesmo resultado de antes. Verificado sem divergência.
- [x] `replay --mode smart --from 156 --to 159` continua agendando exatamente
      `{159}` — dependência pro step 155 continua excluída pelo piso, não pela
      validação de existência. Verificado.
- [x] `replay --mode smart` sem `--to` (default) continua rodando sem erro contra o
      workspace de `progressofit.har` — `target = max(existing) = 237`, sempre
      válido. Verificado.
- [x] Não-regressão: nenhum destes comandos citados acima muda de comportamento
      observável em relação ao testado antes desta task, exceto os três primeiros
      itens (que trocam `FileNotFoundError`/traceback cru por `ValueError` com
      mensagem clara) e o quarto item (divergência de estado do workspace, não da
      lógica — ver nota acima).
