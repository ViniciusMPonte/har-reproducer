# Spec — Steps Pulados Quebram o Schedule do Replay List

> Fonte única de verdade para gerar o `implementation_plan.md` desta etapa. Assume que
> quem escreve o plano não participou da conversa que chegou a estas decisões — tudo
> que é necessário para entender o "porquê" e o "o quê" está aqui, sem depender de nada
> além do código-fonte atual do projeto (`har_reproducer/`) e do `guia_de_estilo.md`.

## 1. Objetivo

Rodando `replay --mode list` contra o workspace gerado por um `run` completo de
`arquivos-har/progressofit.har` (238 entries, steps 78/90/166 pulados por serem
upgrades de WebSocket — `StepSkipEvaluator`), qualquer `--steps-file` que contenha um
índice sem `curl file` quebra com um `FileNotFoundError` não tratado, propagado até o
topo do processo, sem nunca imprimir o resultado de validação final:

```
--steps-file com "78"   → FileNotFoundError: .../curls/req_0078.curl.sh   (step pulado)
--steps-file com "9999" → FileNotFoundError: .../curls/req_9999.curl.sh   (fora do intervalo existente)
```

Reproduzido de fato (não é hipotético) rodando os dois comandos acima contra esse
workspace nesta etapa de investigação. Um agravante específico de `list`, que nem
`slice` nem `smart` têm: como o schedule não é validado antes de `_run_schedule`
começar a executar, **qualquer step válido que apareça antes do inválido no arquivo já
dispara requisição HTTP real** antes do crash — ex. um `--steps-file` com `1\n2\n78\n3`
executa os steps 1 e 2 de verdade (proxy já ligado, `curl` real disparado) e só então
quebra no 78, sem nunca chegar no 3 nem imprimir `Replay Validation Result`.

**Causa raiz:** `ReplayRunner._schedule_list` (`replay/replay_runner.py:160-163`) lê
os índices direto do `--steps-file` informado pelo usuário e devolve como schedule sem
checar se cada um corresponde a um curl file real em disco:

```python
def _schedule_list(self, steps_file: Path) -> Tuple[List[int], Set[int]]:
    lines: List[str] = steps_file.read_text(encoding="utf-8").splitlines()
    ordered_indexes: List[int] = [int(line.strip()) for line in lines if line.strip()]
    return ordered_indexes, set(ordered_indexes)
```

Esta é exatamente a mesma classe de bug já corrigida para `--mode slice` (commit
`6c6073e`, `docs/20260805 Steps Pulados Quebram o Schedule do Replay Slice/`) e para
`--mode smart` (commit `15beffa`, `docs/20260805 Steps Pulados Quebram o Schedule do
Replay Smart/`) — mas as duas specs anteriores **deixaram `_schedule_list`
deliberadamente fora de escopo**, cada uma reafirmando a mesma decisão. Da spec do
slice (seção 2):

> "`ReplayRunner._schedule_list` [...] Se o usuário listar manualmente um índice
> pulado, o comportamento [...] é idêntico ao de pedir replay de qualquer índice que
> nunca existiu — pré-existente, não é uma regressão introduzida pela feature de skip,
> e está fora do escopo desta correção."

E da spec do smart (seção 1, "Fora de escopo"):

> "`_schedule_list` — usuário informa os índices manualmente via `--steps-file`; um
> índice inexistente ali já quebra hoje da mesma forma [...], comportamento
> pré-existente e não é a regressão relatada aqui [...]."

Ambas as decisões estavam certas sobre o fato ("não é regressão nova, é
comportamento pré-existente") — mas isso nunca implicou "não vale a pena corrigir",
só "fora do escopo daquela spec específica". Esta spec fecha a lacuna que sobrou: a
mesma classe de bug, no terceiro (e último) dos quatro modos de schedule que ainda não
valida os índices contra o que existe de verdade no workspace.

Fora de escopo (não implementar agora):
- Qualquer mudança em `_schedule_all` ou `_schedule_slice` — já corretos (o primeiro
  desde antes da feature de skip, o segundo desde `6c6073e`).
- A fragilidade do acoplamento entre `_mark_token_static`/`DEPENDENCY_PATTERN`, e o
  padrão do projeto de não ter `try/except` de topo em `main.py` — já registrados
  como dívida técnica conhecida na spec do smart (seção 1), não repetidos aqui.
- Validação antecipada na camada de CLI (`cli_handlers.py`) de que os índices do
  `--steps-file` existem no workspace — mesma decisão já tomada nas duas specs
  anteriores: o problema é a construção do schedule dentro de `ReplayRunner`, que já é
  o único lugar que conhece `_existing_step_indexes()`; a CLI só valida combinação de
  flags (`_validate_replay_mode_flags`), não overlap com o workspace.
- Deduplicar ou normalizar duplicatas dentro do `--steps-file` (ex.: `1\n1\n2`) — já
  funciona hoje (reexecuta a linha duplicada de novo, sobrescrevendo o
  `res_XXXX.json` daquele run) e não é o bug relatado; comportamento inalterado por
  esta spec.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

- **`ReplayRunner._schedule_list`** (`replay/replay_runner.py:160-163`) — método alvo
  desta correção, código na seção 1. Não faz nenhuma checagem contra
  `_existing_step_indexes()` — o único dos quatro `_schedule_*` que nunca chama esse
  método.

- **`ReplayRunner._schedule_smart`** (`replay/replay_runner.py:131-140`) — padrão a
  seguir, já corrigido na spec anterior (`docs/20260805 Steps Pulados Quebram o
  Schedule do Replay Smart/spec.md`, seção 3.1):
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
      ...
  ```
  A razão para `smart` levantar `ValueError` explícito em vez de filtrar
  silenciosamente (como `slice` faz) é a mesma que se aplica a `list`, com ainda mais
  força — ver seção 3.1.

- **`ReplayRunner._run_schedule`** (`replay/replay_runner.py:59-74`) — consome
  `ordered_indexes` (lista, ordem de execução) e `schedule` (set, usado por
  `ReplayTokenResolver.resolve` para decidir se um token dependency está "dentro do
  schedule atual"). Já levanta
  `ValueError("ReplayRunner: schedule vazio — nenhum step para processar.")`
  (linha 60-61) quando `ordered_indexes` é vazio. Não muda — depois da correção desta
  spec, todo `index` que chega em `_run_step` (linha 76) já é garantidamente um índice
  existente, pelo mesmo motivo que já vale hoje para `all`, `slice` e `smart`.

- **`ReplayRunner._existing_step_indexes`** (`replay/replay_runner.py:165-171`) —
  varre `Workspace.curls.glob("req_*.curl.sh")` e retorna a lista ordenada de índices
  que de fato têm curl file. Fonte de verdade de "quais steps existem para replay",
  já usada por `_schedule_all`, `_schedule_slice` e `_schedule_smart`.

- **`CliHandlers._validate_replay_mode_flags`** (`cli/cli_handlers.py:159-173`) —
  confirma que a única validação hoje sobre `list` é de combinação de flags
  (`--steps-file` obrigatório, `--from`/`--to` não se aplicam); nenhuma validação
  verifica se os índices do arquivo correspondem a steps que existem no workspace.

## 3. Decisões de arquitetura

### 3.1 `_schedule_list` valida todos os índices do arquivo contra `_existing_step_indexes()` antes de executar qualquer step

Estado atual (seção 1/2): nenhuma validação; o primeiro índice inexistente do arquivo
só é descoberto dentro do loop de `_run_schedule`, depois que todos os índices
anteriores a ele já rodaram de verdade (seção 1, agravante específico de `list`).

Estado esperado — a mesma checagem de `_schedule_smart` (seção 2), adaptada para uma
lista completa de índices em vez de um único `target`, e feita **antes** de qualquer
`ordered_indexes` ser devolvido para `_run_schedule`:

```python
def _schedule_list(self, steps_file: Path) -> Tuple[List[int], Set[int]]:
    existing_set: Set[int] = set(self._existing_step_indexes())
    lines: List[str] = steps_file.read_text(encoding="utf-8").splitlines()
    ordered_indexes: List[int] = [int(line.strip()) for line in lines if line.strip()]
    self._require_all_existing(ordered_indexes, existing_set)
    return ordered_indexes, set(ordered_indexes)
```

Por que `ValueError` explícito (fail-fast, aborta antes do primeiro step rodar) em
vez do padrão silencioso de `_schedule_slice` (filtrar índices inexistentes do
range): a razão já usada na spec do smart (seção 3.1) para descartar esse mesmo
padrão vale aqui com ainda mais força. No `slice`, `--to` delimita um *intervalo* —
dropar um buraco do meio ainda preserva a intenção ("roda tudo que existe nesse
range"). Em `list`, **cada linha do arquivo é uma escolha explícita e individual do
usuário** — não existe intervalo, só uma sequência exata de índices que o usuário
decidiu, um por um, que queria reproduzir (o próprio contrato documentado no README:
"reexecuta exatamente os passos listados [...], na ordem em que aparecem no
arquivo"). Silenciosamente pular um deles seria ainda menos justificável do que em
`smart` (que pelo menos tem só um único `target` explícito por execução) — aqui
seriam N escolhas explícitas, e dropar qualquer uma sem avisar violaria o "exatamente"
do contrato documentado.

⚠️ A validação cobre **todos** os índices do arquivo de uma vez, não índice por
índice conforme a execução avança — é isso que elimina o agravante da seção 1 (steps
válidos antes do inválido não devem disparar requisição real nenhuma se o arquivo tem
qualquer índice inexistente, em qualquer posição).

### 3.2 Extrair `_require_all_existing` como helper compartilhado, reaproveitando a mensagem de `_schedule_smart`

Estado atual: a checagem "índice não existe no workspace → `ValueError` com a mesma
frase explicativa" já existe em `_schedule_smart` (seção 2) para um único `target`.
Repetir a mesma frase inline em `_schedule_list`, agora para uma lista de índices,
duplicaria a lógica que o `guia_de_estilo.md` pede para virar helper compartilhado
("Duplicação de lógica vira constante/coleção").

Estado esperado — um método privado novo **dentro da própria classe `ReplayRunner`**
(`replay/replay_runner.py`, ao lado de `_schedule_all`/`_schedule_slice`/
`_schedule_smart`/`_existing_step_indexes` — nenhum arquivo novo, nenhuma função fora
de classe, seguindo `guia_de_estilo.md`: "Nada solto no módulo — sem função ou
constante fora de classe"), reaproveitado pelos dois pontos que hoje fariam a mesma
checagem em duplicidade:

```python
class ReplayRunner:
    ...

    @staticmethod
    def _require_all_existing(indexes: Iterable[int], existing_set: Set[int]) -> None:
        missing: List[int] = sorted({index for index in indexes if index not in existing_set})
        if missing:
            raise ValueError(
                f"ReplayRunner: step(s) {missing} não existem no workspace (nenhum curl file em disco) — "
                f"provavelmente foram pulados por skip_rules ou estão fora do intervalo de steps existentes."
            )
```

`@staticmethod` porque não usa `self` — mesmo critério que o `guia_de_estilo.md` já
descreve ("`@staticmethod` para métodos sem estado de instância") e que o próprio
arquivo já aplica em outro lugar (`_mark_token_static`, `@classmethod` por precisar de
`cls.STATIC_WARNING_SUFFIX`). Chamado como `self._require_all_existing(...)`, nunca
como função de módulo importada separadamente.

`_schedule_smart` passa a chamar `self._require_all_existing({target}, existing_set)`
no lugar do `if target not in existing_set: raise ValueError(...)` atual (mesmo texto,
agora gerado pelo helper — `missing` vira `[target]` quando o único elemento não
existe), e `_schedule_list` chama
`self._require_all_existing(ordered_indexes, existing_set)` (seção 3.1). A mensagem
deixa de falar em "step alvo" (singular, específico de `smart`) e passa a falar em
"step(s)" com a lista completa dos índices que faltam — mais informativa que a de
`smart` hoje (que só reporta um índice por vez, mesmo quando teoricamente mais de um
poderia estar errado — não é o caso do `smart`, que só tem um único `target`, mas é
exatamente o caso do `list`, onde vários índices do arquivo podem não existir ao mesmo
tempo).

⚠️ Isso muda o texto exato da mensagem de erro que `_schedule_smart` levanta hoje
(de "step alvo 78 não existe [...] provavelmente foi pulado [...]" para "step(s) [78]
não existem [...] provavelmente foram pulados [...]") — o projeto não tem suíte de
testes automatizados hoje (`pytest.ini` aponta para `testpaths = tests`, mas o
diretório `tests/` não existe no repo; toda verificação de comportamento até aqui foi
manual/empírica, inclusive a desta própria investigação), então não há nenhum teste
que faça match exato desse texto e possa quebrar — é só uma mensagem de erro
ligeiramente diferente para o mesmo cenário, sem nenhuma garantia automatizada em
jogo.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `har_reproducer/replay/replay_runner.py` (`ReplayRunner._schedule_list`) | calcula `existing_set` e valida todos os índices do `--steps-file` contra ele via `_require_all_existing`, antes de devolver o schedule — em vez de nenhuma validação |
| `har_reproducer/replay/replay_runner.py` (`ReplayRunner._schedule_smart`) | a checagem inline do `target` (`if target not in existing_set: raise ValueError(...)`) passa a chamar o novo `_require_all_existing({target}, existing_set)` — mesmo comportamento, mensagem ligeiramente reformulada (seção 3.2) |
| `har_reproducer/replay/replay_runner.py` (novo `ReplayRunner._require_all_existing`) | novo `@staticmethod` — valida um conjunto de índices contra `existing_set`, levanta `ValueError` único listando todos os que faltam |

Nenhum outro arquivo muda.

## 5. Casos de borda e comportamento de erro

- **`--steps-file` contém um índice de step pulado** (ex.: `78`, `90` ou `166` neste
  HAR) — `ValueError` claro antes de qualquer schedule ser montado ou qualquer step
  rodar, em vez do `FileNotFoundError` de hoje.
- **`--steps-file` contém um índice fora do intervalo de steps existentes** (ex.:
  `9999`) — mesmo `ValueError`.
- **`--steps-file` contém múltiplos índices inexistentes** (ex.: `1\n78\n2\n166`) — um
  único `ValueError`, listando `[78, 166]` juntos (ordenados), não um erro por
  tentativa — o usuário corrige o arquivo de uma vez, sem precisar rodar de novo a
  cada índice inválido descoberto.
- **Índice inexistente no meio ou fim do arquivo, com steps válidos antes** (ex.:
  `1\n2\n78\n3`, o caso da seção 1) — depois da correção, nenhum dos steps 1/2/3
  dispara requisição real: a validação acontece antes de `_run_schedule` começar,
  eliminando o agravante descrito na seção 1.
- **`--steps-file` só com índices existentes** (caso comum, já testado hoje com
  sucesso: `0\n1\n2`, ordem customizada `5\n2\n1`, duplicatas `1\n1\n2`) — `missing`
  fica vazio, `_require_all_existing` não levanta nada, comportamento idêntico ao de
  hoje — nenhuma mudança observável no caminho feliz.
- **Linhas em branco/espaços no `--steps-file`** — já tratado hoje (`line.strip()`,
  filtro `if line.strip()`), sem mudança.
- **Linha não-numérica no `--steps-file`** (ex.: `"abc"`) — continua quebrando com
  `ValueError: invalid literal for int()...` na list comprehension existente, antes
  mesmo de `existing_set` ser consultado — comportamento pré-existente, fora do
  escopo desta spec (não é a classe de bug endereçada aqui).
- **`_schedule_smart` com `target` default** (`--to` omitido → `max(existing)`) —
  `_require_all_existing({target}, existing_set)` nunca levanta, pelo mesmo motivo já
  documentado na spec do smart (seção 5) — `max(existing)` é por construção membro de
  `existing_set`. Nenhuma mudança observável no caminho default de `smart`.
- **`_expand_pending`** (dependências recursivas do `smart`) — não usa
  `_require_all_existing`; continua descartando silenciosamente um `origin_step` fora
  de `existing_set` (spec do smart, seção 3.2) — essa parte não muda, só a checagem do
  `target` inicial passa a usar o helper novo.

## 6. Referência

Implementação deve seguir `guia_de_estilo.md`: tipagem explícita em tudo (incluindo o
novo helper `_require_all_existing`), guard clause de falha rápida em vez de
propagar `FileNotFoundError` sem contexto, zero comentários/docstrings, e nenhuma
mudança desta spec deve alterar o comportamento observável de um `replay --mode list`
ou `--mode smart` que hoje já roda com sucesso (todos os índices envolvidos existentes
no workspace).
