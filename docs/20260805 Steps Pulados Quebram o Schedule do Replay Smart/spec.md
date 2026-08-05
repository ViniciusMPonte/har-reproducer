# Spec — Steps Pulados Quebram o Schedule do Replay Smart

> Fonte única de verdade para gerar o `implementation_plan.md` desta etapa. Assume que
> quem escreve o plano não participou da conversa que chegou a estas decisões — tudo
> que é necessário para entender o "porquê" e o "o quê" está aqui, sem depender de nada
> além do código-fonte atual do projeto (`har_reproducer/`) e do `guia_de_estilo.md`.

## 1. Objetivo

Rodando `replay --mode smart` contra o workspace gerado por um `run` completo de
`arquivos-har/progressofit.har` (238 entries, steps 78/90/166 pulados por serem
upgrades de WebSocket — `StepSkipEvaluator`), qualquer `--to` que aponte para um
índice sem `curl file` quebra com um `FileNotFoundError` não tratado, propagado até o
topo do processo, sem nunca imprimir o resultado de validação final:

```
--to 78   → FileNotFoundError: .../curls/req_0078.curl.sh   (step pulado)
--to 999  → FileNotFoundError: .../curls/req_0999.curl.sh   (fora do intervalo existente)
--to -1   → FileNotFoundError: .../curls/req_-001.curl.sh   (negativo)
```

Reproduzido de fato (não é hipotético) rodando os três comandos acima contra esse
workspace nesta etapa de investigação.

**Causa raiz:** `ReplayRunner._schedule_smart` (`replay/replay_runner.py:131-142`)
usa `target` — vindo direto de `--to`, sem default nenhum quando informado — como
`schedule`/`pending` inicial, e `_expand_pending` (`replay/replay_runner.py:144-150`)
lê `Workspace.curl_file(current).read_text(...)` para qualquer `current` que entre
nessa fila, **sem nunca checar se esse índice de fato existe em disco**. Isso vale
tanto para o próprio `target` (primeiro `current` processado) quanto para qualquer
`origin_step` descoberto recursivamente via `CurlDependencyParser.parse`.

Esta é exatamente a mesma classe de bug já corrigida para `--mode slice` no commit
`6c6073e` (`docs/20260805 Steps Pulados Quebram o Schedule do Replay Slice/`) — mas
aquela spec **deixou `_schedule_smart` deliberadamente fora de escopo**, prevendo
textualmente este cenário (seção 5 daquele documento):

> "`--to` explícito aponta exatamente para um step pulado (ex.: `--to 78`) [...]
> `_schedule_smart` — não afetado [...] Um `--to` explícito apontando para um step
> pulado em `smart` ainda quebraria (mesma classe de erro, em `_expand_pending`), mas
> é um caso de uso diferente [...] e fora do escopo desta spec."

Esta spec fecha essa lacuna, já prevista mas nunca implementada.

Fora de escopo (não implementar agora):
- `_schedule_list` — usuário informa os índices manualmente via `--steps-file`; um
  índice inexistente ali já quebra hoje da mesma forma (`FileNotFoundError` em
  `_run_step`), comportamento pré-existente e não é a regressão relatada aqui (mesma
  decisão já tomada na spec do slice, seção 5, reafirmada nesta).
- A fragilidade do acoplamento entre `ReplayRunner._mark_token_static`
  (`replay_runner.py:110-118`, sufixo `" - probably static"`) e o `$` ancorado de
  `CurlDependencyParser.DEPENDENCY_PATTERN` (`curl_dependency_parser.py:7-10`) —
  achado durante a investigação desta etapa (uma dependência marcada como estática
  deixa de ser detectada pelo regex e por isso some do `schedule` de execuções
  `smart` futuras). É comportamento intencional e correto na prática, só implementado
  de um jeito implícito/frágil (qualquer mudança futura no formato do comentário
  quebraria essa exclusão silenciosamente, sem teste algum cobrindo isso). Não há bug
  observável hoje — registrar como dívida técnica conhecida, não corrigir agora.
- O padrão do projeto de não ter nenhum `try/except` de topo em `main.py` (toda
  exceção não tratada, em qualquer comando, imprime um traceback Python cru) — é o
  estilo de erro consistente em todo o CLI hoje, não uma particularidade do `smart`;
  fora de escopo.
- Validação antecipada na camada de CLI (`cli_handlers.py`) de que `--to`/`--from`
  correspondem a steps existentes — mesma decisão já tomada na spec do slice (seção
  1): o problema é a construção do schedule dentro de `ReplayRunner`, que já é o
  único lugar que conhece `_existing_step_indexes()`; a CLI só valida combinação de
  flags (`_validate_replay_mode_flags`), não overlap com o workspace.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

- **`ReplayRunner._schedule_smart`** (`replay/replay_runner.py:131-142`) — método
  alvo desta correção:
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
  ```
  Já calcula `existing` (a lista real de índices com curl file), mas só para achar o
  `max()` do default de `target` — nunca usa `existing` pra validar um `target`
  explícito.

- **`ReplayRunner._expand_pending`** (`replay/replay_runner.py:144-150`) — a BFS/DFS
  sobre o grafo de dependências:
  ```python
  def _expand_pending(self, current: int, floor: int, schedule: Set[int], pending: Set[int]) -> None:
      curl_text: str = Workspace.curl_file(current).read_text(encoding="utf-8")
      dependencies = self.dependency_parser.parse(curl_text)
      for origin_step in dependencies.values():
          if origin_step >= floor and origin_step not in schedule:
              schedule.add(origin_step)
              pending.add(origin_step)
  ```
  É chamado tanto para o `target` inicial (primeiro `current` retirado de `pending`)
  quanto para cada `origin_step` descoberto — ou seja, **os dois pontos de entrada
  do bug (target inválido e origin_step inválido) caem exatamente na mesma linha**
  (`Workspace.curl_file(current).read_text(...)`), o que permite uma correção única
  e uniforme (seção 3).

- **`ReplayRunner._schedule_slice`** (`replay/replay_runner.py:124-129`) — o padrão
  já corrigido a seguir, para o `target`:
  ```python
  def _schedule_slice(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
      existing: List[int] = self._existing_step_indexes()
      effective_from: int = from_index if from_index is not None else 0
      effective_to: int = to_index if to_index is not None else max(existing)
      ordered_indexes: List[int] = [index for index in existing if effective_from <= index <= effective_to]
      return ordered_indexes, set(ordered_indexes)
  ```
  ⚠️ O padrão do slice (filtrar silenciosamente um range contra `existing`) **não é
  o mesmo que esta spec adota para o `target` do smart** — ver seção 3.1 para a razão
  da diferença: no slice, `--to` é o limite de um intervalo que roda todos os índices
  existentes dentro dele (dropar um índice pulado do meio do intervalo preserva o que
  o usuário pediu); no smart, `--to` é o próprio step que o usuário quer reproduzir —
  não existe um "vizinho mais próximo" que preserve essa intenção.

- **`ReplayRunner._run_schedule`** (`replay/replay_runner.py:59-74`) — guard clause já
  existente no mesmo arquivo, referência de estilo para a nova validação:
  ```python
  if not ordered_indexes:
      raise ValueError("ReplayRunner: schedule vazio — nenhum step para processar.")
  ```

- **`ReplayTokenResolver._resolve_one`/`_reference_dir_for_step`**
  (`replay/replay_token_resolver.py:41-72`) — o mecanismo que já existe hoje para
  resolver um token cujo `origin_step` **não está** no `schedule` atual:
  ```python
  origin_step: Optional[int] = dependencies.get(token_id)
  if origin_step in schedule:
      override_dir: Path = replay_run_dir
  else:
      override_dir = self._reference_dir_for_step(origin_step, res_refer_dir, original_responses_dir)
  ```
  Esse caminho já é exercitado hoje sempre que um token foi marcado
  `" - probably static"` (seção 1, item fora de escopo) — `CurlDependencyParser` não
  retorna mais aquele `origin_step`, `dependencies.get(token_id)` vira `None`,
  `origin_step in schedule` é `False`, e o valor é resolvido a partir do diretório de
  referência em vez de exigir que o step de origem seja re-executado. É a mesma
  degradação que a seção 3.2 desta spec passa a aplicar também a um `origin_step` que
  não existe mais como curl file — nenhum caminho de código novo, só mais uma forma
  de cair num fallback já testado em produção (todo replay de hoje já passa por ele
  para tokens estáticos).

- **`StepSkipEvaluator.skip_reason`** (`reproduction/step_skip_evaluator.py:12-17`) e
  **`Engine._process_entry`/`_skip_entry`** (`engines/engine.py:93-126`) — por que,
  na prática, um `origin_step` recursivo quase nunca aponta para um step pulado:
  `_process_entry` retorna via `_skip_entry` **antes** de `_persist_template_curl`
  (linha 118) — nenhum step pulado gera `curls/req_XXXX.curl.sh` — e a resposta
  persistida para ele (`_skip_entry`, linha 123) é
  `StepResponse(status_code=0, skipped=True, skip_reason=reason)`, sem `body`,
  `headers` nem `cookies`. `ResponseGrep._eligible_response_files`
  (`tracking/response_grep.py:85-91`) inclui esse arquivo na busca (não sabe de skip,
  seção "Princípio de genericidade" do mapa de arquitetura), mas
  `_grep_single_pattern` (linha 62-82) faz um `grep -lF` literal sobre o conteúdo
  serializado — sem nenhum campo pesquisável que coincida com o valor de um token
  dinâmico real, `CandidateResolver` nunca escolhe um step pulado como origem.
  ⚠️ Isso é uma garantia **estrutural, não matemática** — um valor de token que por
  coincidência aparecesse dentro da string do `skip_reason` (ex.: literalmente o
  texto `"unsupported scheme 'ws'"`) ainda poderia, em teoria, casar. Por isso a
  seção 3.2 não assume que "nunca acontece" é o mesmo que "não precisa de proteção" —
  a proteção é barata e já existe como efeito colateral da correção do `target`.

- **`CliHandlers._validate_replay_mode_flags`** (`cli/cli_handlers.py:159-168`) —
  confirma que a única validação hoje sobre `--from`/`--to` é de combinação de flags
  (`from > to`, flags que não se aplicam ao modo); nenhuma validação verifica se os
  valores correspondem a steps que existem no workspace.

## 3. Decisões de arquitetura

### 3.1 `_schedule_smart` valida `target` contra `_existing_step_indexes()` antes de expandir

Estado atual (seção 2): `target` nunca é validado; a primeira chamada a
`_expand_pending(target, ...)` é onde o `FileNotFoundError` estoura quando `target`
não existe.

Estado esperado — falha rápida com uma mensagem clara (guard clause, mesmo padrão de
`_run_schedule`, seção 2), antes de montar qualquer schedule:
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

Por que `ValueError` explícito em vez de repetir o padrão silencioso do slice
(filtrar/pular o índice): no slice, `--to` delimita um intervalo — todos os índices
existentes dentro dele rodam, então um índice pulado no meio ou na ponta do intervalo
simplesmente não sobra nada de especial pra tratar (o intervalo continua fazendo
sentido sem ele). No smart, `target` **é** o pedido do usuário ("quero reproduzir o
step N e o que ele depende") — não existe um "vizinho mais próximo" que preserve essa
intenção sem silenciosamente testar um step diferente do que foi pedido. Uma mensagem
de erro clara (em vez do `FileNotFoundError` cru de hoje) é estritamente melhor: o
usuário sabe imediatamente que o índice pedido não existe, em vez de um traceback sem
contexto.

⚠️ `target` default (`--to` omitido → `max(existing)`) nunca dispara esse erro —
`max(existing)` é, por construção, sempre um membro de `existing_set`. Nenhuma
mudança observável no caminho default (o mesmo testado no início desta investigação).

### 3.2 `_expand_pending` ignora um `origin_step` que não existe no workspace

Estado atual (seção 2): qualquer `origin_step` retornado por
`CurlDependencyParser.parse` entra em `pending` sem checagem, e a expansão seguinte
(`Workspace.curl_file(origin_step).read_text(...)`) quebra se ele não existir.

Estado esperado — o mesmo `existing_set` calculado em `_schedule_smart` (3.1) é
propagado para `_expand_pending`, que passa a exigir também `origin_step in
existing_set` para agendar a expansão:
```python
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

Por que descartar silenciosamente aqui, ao contrário da 3.1 (que levanta erro): este
`origin_step` não veio de uma escolha explícita do usuário — veio de um comentário
gerado automaticamente por um `run` anterior, sobre um token que o próprio sistema
identificou como tendo uma origem. Se essa origem não existe mais como curl file (na
prática, um caso que a seção 2 mostra ser estruturalmente quase impossível, mas não
uma garantia matemática), o comportamento correto é o mesmo que já existe hoje para
qualquer `origin_step` fora do `schedule` (seção 2,
`ReplayTokenResolver._resolve_one`): resolver o token a partir do diretório de
referência em vez de exigir a reexecução do step. Levantar erro aqui seria
inconsistente com esse fallback já estabelecido, para um caminho que os dados reais
gerados pelo próprio projeto nunca produzem.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `har_reproducer/replay/replay_runner.py` (`ReplayRunner._schedule_smart`) | valida `target` contra `_existing_step_indexes()`; levanta `ValueError` claro se não existir, em vez de deixar o primeiro `FileNotFoundError` estourar dentro do loop |
| `har_reproducer/replay/replay_runner.py` (`ReplayRunner._expand_pending`) | ganha o parâmetro `existing_set: Set[int]`; só agenda um `origin_step` para expansão se ele também existir no workspace |

Nenhum outro arquivo muda.

## 5. Casos de borda e comportamento de erro

- **`--to` aponta para um step pulado** (ex.: `--to 78`, `--to 90`, `--to 166` neste
  HAR) — `ValueError` claro antes de qualquer schedule ser montado, em vez do
  `FileNotFoundError` de hoje.
- **`--to` fora do intervalo de steps existentes** (ex.: `--to 999`, `--to -1`) —
  mesmo `ValueError`; a mensagem não distingue "pulado" de "fora do range" (ambos
  produzem "sem curl file em disco"), o que é suficiente para o usuário entender o
  problema sem precisar de lógica adicional para diferenciar os dois casos.
- **`--to` omitido** — `target = max(existing)`, sempre válido; comportamento
  idêntico ao de hoje, já testado (roda só o último step, mais o que ele
  recursivamente ainda depende de forma "viva").
- **`--from` que não corresponde a nenhum step existente** (ex.: `--from 500`) — não
  afetado: `floor` é só um limite inferior de comparação (`origin_step >= floor`),
  nunca um índice lido do disco; continua não precisando existir como step, mesmo
  comportamento de hoje (`--from` alto o suficiente só faz a recursão não trazer
  nenhuma dependência, não quebra nada).
- **Dependência recursiva (`origin_step`) aponta para um step que não existe** —
  silenciosamente fora do `schedule`; a resolução do token cai no fallback de
  `ReplayTokenResolver._resolve_one` (diretório de referência), sem crash e sem
  mudança no resultado final do replay (o valor ainda é resolvido, só que sem exigir
  a reexecução daquele step). Caso estruturalmente quase impossível de ocorrer com
  dados reais (seção 2), mas coberto mesmo assim, sem custo extra de código.
- **HAR sem nenhum step pulado** (qualquer workspace de antes da feature de skip, ou
  de um HAR sem `ws`/`wss`/métodos pulados) — `existing_set` contém todo índice de
  `0` a `max(existing)`; `target in existing_set` e `origin_step in existing_set` são
  sempre verdadeiros para qualquer valor que já funcionava antes — nenhuma mudança
  observável para o caso comum de hoje (validado empiricamente nesta investigação:
  `--to 222`, `--to 159`, `--from 156 --to 159`, `--from 200`, todos com steps
  existentes, continuam produzindo exatamente o mesmo schedule que produziam antes
  desta correção).
- **`--mode list` com índice inexistente no `--steps-file`** — comportamento
  inalterado, fora de escopo (seção 1).

## 6. Referência

Implementação deve seguir `guia_de_estilo.md`: tipagem explícita em tudo (incluindo o
novo parâmetro `existing_set: Set[int]`), guard clauses, zero comentários/docstrings,
e nenhuma mudança desta spec deve alterar o comportamento observável de um `replay
--mode smart` que hoje já roda com sucesso (target e todas as dependências existentes
no workspace).
