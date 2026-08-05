# Spec — Steps Pulados Quebram o Schedule do Replay Slice

> Fonte única de verdade para gerar o `implementation_plan.md` desta etapa. Assume que
> quem escreve o plano não participou da conversa que chegou a estas decisões — tudo
> que é necessário para entender o "porquê" e o "o quê" está aqui, sem depender de nada
> além do código-fonte atual do projeto (`har_reproducer/`) e do `guia_de_estilo.md`.

## 1. Objetivo

Rodando `replay --mode slice` (sem `--from`/`--to`, ou seja, o range default "do
primeiro ao último passo existente") contra o workspace gerado por um `run` completo
de `arquivos-har/progressofit.har` (238 entries), o comando quebra com:

```
FileNotFoundError: [Errno 2] No such file or directory: '.../curls/req_0078.curl.sh'
```

O comando processa os steps 0–77 normalmente e trava ao chegar no 78, sem nunca
imprimir o resultado de validação final. Não é um erro de rede nem de token — é um
`FileNotFoundError` não tratado, propagado até o topo do processo.

**Causa raiz:** os steps 78, 90 e 166 desse HAR são upgrades de WebSocket
(`ws://127.0.0.1:8080//ws`, `ws://127.0.0.1:8080/login//ws`,
`ws://127.0.0.1:8080/dashboard//ws`) — pulados intencionalmente por
`StepSkipEvaluator` (`reproduction/step_skip_evaluator.py`, feature entregue em
`docs/20260805 Skip de Steps Não Suportados e Estabilidade do Proxy mitmdump/`).
Steps pulados nunca geram `curls/req_XXXX.curl.sh` (`Engine._process_entry` retorna
antes de `_persist_template_curl`, ver seção 2) — é assim, por design, desde aquela
mudança.

`ReplayRunner._schedule_slice` (`replay/replay_runner.py:124-129`) monta o range do
slice com `range(effective_from, effective_to + 1)`, um `range()` puro do Python que
**assume que todo índice nesse intervalo tem um curl file**. Essa suposição já era
falsa antes da feature de skip (um HAR poderia, em tese, ter um "buraco" de índices por
outro motivo), mas a feature de skip a tornou uma ocorrência normal e esperada em
qualquer HAR real capturado de uma aplicação com upgrade de WebSocket — não é mais um
caso exótico.

A spec que introduziu o skip (`docs/20260805 Skip de Steps Não
Suportados.../spec.md`, seção 2 e seção 5, "casos de borda") afirma explicitamente:

> **`ReplayRunner._existing_step_indexes`** ... Como nenhum step pulado ... gera esse
> arquivo, `ReplayRunner` **nunca precisa saber sobre skip** — ele simplesmente não vê
> esses índices. Nenhuma mudança necessária em `ReplayRunner` por causa desta spec.

Essa afirmação é verdadeira para `_schedule_all` (usa `_existing_step_indexes()`
diretamente, seção 2) mas **falsa para `_schedule_slice`** — o único dos quatro modos
de schedule que monta o range por aritmética pura em vez de filtrar contra os índices
que de fato existem em disco. Essa é a lacuna que este documento fecha.

Fora de escopo (não implementar agora):
- Qualquer mudança em `_schedule_smart` ou `_schedule_list` — avaliado em detalhe na
  seção 5 (Casos de borda): nenhum dos dois compartilha a mesma causa raiz, então
  nenhuma mudança neles é necessária para esta correção.
- Validação antecipada (na CLI, antes de chamar `runner.run_slice`) de que
  `--from`/`--to` fazem sentido — o problema é a construção do schedule dentro de
  `ReplayRunner`, não a camada de CLI (`cli_handlers.py`), que já valida `--from` >
  `--to` (`_validate_replay_mode_flags`) e não precisa de mudança.
- Suporte real a replay de tráfego `ws`/`wss` — segue fora de escopo, como já
  decidido na spec de skip original.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

- **`ReplayRunner._schedule_slice`** (`replay/replay_runner.py:124-129`) — método
  alvo desta correção:
  ```python
  def _schedule_slice(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
      existing: List[int] = self._existing_step_indexes()
      effective_from: int = from_index if from_index is not None else 0
      effective_to: int = to_index if to_index is not None else max(existing)
      ordered_indexes: List[int] = list(range(effective_from, effective_to + 1))
      return ordered_indexes, set(ordered_indexes)
  ```
  Já calcula `existing` (a lista real de índices com curl file) só para achar o
  `max()` do range default — o valor não é reaproveitado para filtrar o range em si.

- **`ReplayRunner._schedule_all`** (`replay/replay_runner.py:120-122`) — padrão a
  seguir, já correto:
  ```python
  def _schedule_all(self) -> Tuple[List[int], Set[int]]:
      ordered_indexes: List[int] = self._existing_step_indexes()
      return ordered_indexes, set(ordered_indexes)
  ```
  `ordered_indexes` é exatamente `_existing_step_indexes()` — nenhum índice fora do
  que existe em disco jamais entra no schedule.

- **`ReplayRunner._existing_step_indexes`** (`replay/replay_runner.py:157-163`) —
  varre `Workspace.curls.glob("req_*.curl.sh")` e retorna a lista ordenada de índices
  que de fato têm curl file. É a fonte de verdade de "quais steps existem para
  replay" — usada hoje por `_schedule_all`, `_schedule_smart` (só para achar o
  `target` default) e (parcialmente) por `_schedule_slice`.

- **`ReplayRunner._run_schedule`** (`replay/replay_runner.py:59-74`) — consome
  `ordered_indexes` (lista, ordem de execução) e `schedule` (set, usado por
  `ReplayTokenResolver.resolve` para decidir se um token dependency está "dentro do
  schedule atual" ou precisa de referência externa). Já levanta
  `ValueError("ReplayRunner: schedule vazio — nenhum step para processar.")`
  (linha 60-61) quando `ordered_indexes` é vazio — guard clause que a correção desta
  spec reaproveita sem alteração (seção 5).

- **`ReplayRunner._run_step`** (`replay/replay_runner.py:76-99`) — linha 77,
  `Workspace.curl_file(index).read_text(...)`, é onde o `FileNotFoundError` da spec
  estoura hoje. Não muda — depois da correção em `_schedule_slice`, todo `index` que
  chega aqui já é garantidamente um índice existente.

- **`ReplayRunner._schedule_smart`/`_expand_pending`**
  (`replay/replay_runner.py:131-150`) — `target` default vem de
  `max(existing)` (sempre um índice válido); a expansão recursiva
  (`_expand_pending`, linha 144-150) segue `dependencies` retornadas por
  `CurlDependencyParser.parse`, que só existem para tokens com origem detectada por
  `CandidateResolver._find_origin` (`tracking/candidate_resolver.py:70-77`). Essa
  busca usa `ResponseGrep.find` (`tracking/response_grep.py:12-21`) sobre
  `real_responses/` — para um step pulado, `real_responses/res_XXXX.json` contém o
  `StepResponse` sintético de skip (`status_code=0, body=None, headers={},
  cookies={}`, gravado por `Engine._skip_entry`, `engines/engine.py:122-126`), que
  não tem nenhum conteúdo pesquisável por `grep -lF`. Na prática, **nenhum
  `origin_step` gerado por um `run` real aponta para um step pulado** — confirmado
  também empiricamente no workspace usado para reproduzir este bug (nenhum arquivo em
  `curls/` referencia os steps 78/90/166 como origem). Por isso `_schedule_smart` não
  compartilha a causa raiz desta spec e não precisa de mudança (detalhado na seção 5).

- **`ReplayRunner._schedule_list`** (`replay/replay_runner.py:152-155`) — lê
  índices diretamente de um arquivo fornecido pelo usuário (`--steps-file`), sem
  nenhum cálculo de range. Se o usuário listar manualmente um índice pulado, o
  comportamento (mesmo `FileNotFoundError` de `_run_step`) é idêntico ao de pedir
  replay de qualquer índice que nunca existiu — pré-existente, não é uma regressão
  introduzida pela feature de skip, e está fora do escopo desta correção (seção 5).

## 3. Decisões de arquitetura

### 3.1 `_schedule_slice` filtra o range contra `_existing_step_indexes()`

Estado atual (seção 2):
```python
ordered_indexes: List[int] = list(range(effective_from, effective_to + 1))
```

Estado esperado — o range vira um filtro sobre `existing`, no lugar da aritmética
pura, mesmo padrão que `_schedule_all` já usa como fonte de verdade:
```python
def _schedule_slice(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
    existing: List[int] = self._existing_step_indexes()
    effective_from: int = from_index if from_index is not None else 0
    effective_to: int = to_index if to_index is not None else max(existing)
    ordered_indexes: List[int] = [index for index in existing if effective_from <= index <= effective_to]
    return ordered_indexes, set(ordered_indexes)
```

Por que filtrar contra `existing` em vez de, por exemplo, tentar capturar a exceção em
`_run_step`: o schedule (`Set[int]`) também é consumido por
`ReplayTokenResolver.resolve` (seção 2) para decidir se um token dependency está
"dentro do range que vai rodar" — incluir um índice pulado no `schedule` mesmo sem
executá-lo geraria um `Set[int]` inconsistente com `ordered_indexes` (o índice estaria
no set mas nunca seria de fato processado). Filtrar na origem, como `_schedule_all` já
faz, mantém `ordered_indexes` e `schedule` sempre coerentes entre si — a mesma
garantia que já vale para `all`.

⚠️ `existing` já vem ordenado (`_existing_step_indexes`, seção 2, usa
`sorted(indexes)`) — a list comprehension preserva essa ordem, então
`ordered_indexes` continua em ordem crescente de execução, como antes.

⚠️ Efeito colateral desejado: um `--from`/`--to` cujo intervalo não contenha nenhum
índice existente (ex.: `--from 500 --to 600` num HAR de 238 entries, ou um intervalo
que contenha só steps pulados) produz `ordered_indexes = []`, que já cai no guard
clause existente de `_run_schedule` (`ValueError("... schedule vazio ...")`, seção 2)
— nenhuma mudança adicional necessária para tratar esse caso.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `har_reproducer/replay/replay_runner.py` (`ReplayRunner._schedule_slice`) | range aritmético (`range(from, to+1)`) vira filtro de `existing` (`_existing_step_indexes()`) pelo intervalo `[effective_from, effective_to]` |

Nenhum outro arquivo muda.

## 5. Casos de borda e comportamento de erro

- **Slice default (sem `--from`/`--to`) num HAR com steps pulados no meio** — caso
  que reproduz o bug relatado. Depois da correção, `ordered_indexes` pula
  automaticamente os índices sem curl file (78, 90, 166 neste HAR), do mesmo jeito
  que `all` já faz hoje.
- **`--from`/`--to` explícitos que incluem um step pulado no meio do intervalo** —
  mesmo comportamento: o índice pulado simplesmente não entra em `ordered_indexes`,
  sem erro.
- **`--from`/`--to` explícitos que apontam para um intervalo sem nenhum step
  existente** — `ordered_indexes = []`, cai no `ValueError` já existente em
  `_run_schedule` (mensagem clara, sem stack trace) — comportamento inalterado por
  esta correção, só passa a ser alcançável por um caminho novo (antes, um intervalo
  assim com todos os índices "existindo em teoria" via `range()` puro só falharia
  depois, dentro de `_run_step`, com `FileNotFoundError`; um intervalo que hoje já não
  contém nenhum índice real de fato — ex.: `--from 500 --to 600` — já cai nesse
  `ValueError` mesmo sem a correção).
- **`--to` explícito aponta exatamente para um step pulado** (ex.: `--to 78`) — o
  índice pulado não entra em `ordered_indexes`; o último índice executado é o
  existente mais próximo abaixo de 78. Comportamento consistente com "slice reexecuta
  os passos existentes no intervalo", não uma mudança que precise de tratamento
  especial.
- **`_schedule_smart`** — não afetado (seção 2): `origin_step` nunca aponta para um
  step pulado, porque a resposta persistida de um step pulado
  (`Engine._skip_entry`) não tem conteúdo pesquisável por `ResponseGrep.find`. Um
  `--to` explícito apontando para um step pulado em `smart` ainda quebraria (mesma
  classe de erro, em `_expand_pending`), mas é um caso de uso diferente (usuário
  pedindo explicitamente para reproduzir um índice que não existe) e fora do escopo
  desta spec — não é a regressão relatada, que ocorre no range **default** do slice
  sem nenhuma escolha explícita do usuário apontar para um step pulado.
- **`_schedule_list`** — não afetado; comportamento pré-existente e fora de escopo
  (seção 1/2).
- **HAR sem nenhum step pulado** (qualquer workspace gerado antes da feature de skip,
  ou de um HAR sem `ws`/`wss`/métodos pulados) — `existing` é uma sequência contígua
  de `0` a `max(existing)`; o filtro `[index for index in existing if from <= index
  <= to]` produz exatamente o mesmo resultado que `list(range(from, to+1))` produzia
  antes — nenhuma mudança observável para o caso comum de hoje.

## 6. Referência

Implementação deve seguir `guia_de_estilo.md`: tipagem explícita em tudo, guard
clauses, zero comentários/docstrings, e nenhuma mudança desta spec deve alterar o
comportamento observável de um `replay --mode slice` que hoje já roda com sucesso
(HAR sem steps pulados).
