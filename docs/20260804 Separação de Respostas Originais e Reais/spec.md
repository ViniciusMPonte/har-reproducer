# Spec — Separação de Respostas Originais e Reais

> Fonte única de verdade para gerar o `implementation_plan.md` desta etapa. Assume que
> quem escreve o plano não participou da conversa que chegou a estas decisões — tudo
> que é necessário para entender o "porquê" e o "o quê" está aqui, sem depender de nada
> além do código-fonte atual do projeto (`har_reproducer/`), do `guia_de_estilo.md` e do
> `spec.md` de `docs/20260731 Ferramenta de Replay/` (mecanismo de replay, já
> implementado, reaproveitado e corrigido aqui).

## 1. Objetivo

Hoje existe um único diretório, `real_responses/` (`Workspace.real_responses`,
`fs_io/workspace_dir.py:6`), onde `Engine._persist_response_step`
(`engines/engine.py:112-113`) grava, para todo step do HAR, o arquivo
`res_{index:04d}.json` com a resposta obtida ao processar aquele step —
**independente do modo de execução**:

- `run --mode main` (`Engine.execute_step`, `engine.py:137-144`): a resposta é
  **real**, obtida via requisição HTTP de verdade (curl através do proxy mitmproxy).
- `run --mode dry` (`DryEngine.execute_step`, `engines/dry_engine.py:10-12`): a
  resposta é `step.response`, o valor **original do HAR**, montado por
  `HARParser.parse_entry` (`fs_io/har_parser.py:44-87`) — nenhuma rede é usada.

Como `_persist_response_step` grava sempre no mesmo path (`Workspace.response_file`,
`fs_io/workspace.py:64-67`) via `write_text` incondicional, **cada execução (de
qualquer modo) sobrescreve o que a execução anterior gravou ali**. Rodar `dry` depois
de um `main` bem-sucedido apaga a evidência da resposta real obtida; rodar `main`
depois de um `dry` mistura, no mesmo diretório, resultado real com resultado
simulado — sem qualquer jeito de saber, olhando só para `real_responses/`, qual dos
dois está ali agora.

Esse problema já foi identificado e deliberadamente adiado na spec anterior
(`docs/20260804 Desambiguação de Identidade de Token Dinâmico/spec.md:57-61`):

> "Separar respostas originais do HAR das respostas reais de execução
> (`real_responses/` hoje é sobrescrito a cada `run`). É um problema real, discutido
> separadamente, mas ortogonal a este: mesmo com respostas originais preservadas, a
> colisão de `token_id` aconteceria do mesmo jeito, porque a causa é a fórmula de
> identidade, não a fonte da resposta."

Esta spec resolve exatamente esse item adiado: **separar, em disco, a resposta
original do HAR (determinística, igual em qualquer modo) da resposta real obtida ao
executar o step — sem que uma sobrescreva a outra entre execuções.**

**Fora de escopo** (não implementar agora):

- Qualquer mudança em `real_requests/` — `Engine._persist_request_step`
  (`engine.py:109-110`) grava sempre `step.request`, o request **tal como parseado do
  HAR**, sempre antes de qualquer resolução de token/renderização de curl. Seu
  conteúdo já é determinístico e idêntico em qualquer modo — não existe, para
  requests, a mesma ambiguidade "original vs. real" que existe para responses.
- Unificar com o subcomando `parse` (`HARParser.split_har`, `har_parser.py:89-109`,
  despachado por `CliHandlers.handle_parse`, `cli/cli_handlers.py:79-85`). Esse
  subcomando já escreve request/response originais do HAR em
  `<output_dir>/parse/{req,res}_XXXX.json`, mas é uma feature standalone,
  desacoplada de `Workspace`/`WorkspaceDir` (usa `output_dir / "parse"` direto, sem
  passar por `Workspace.init`) e do pipeline de `run`/`dry`/`replay` — nada nesse
  pipeline lê de `parse/`. Permanece uma ferramenta separada de inspeção manual;
  unificá-la ao novo diretório desta spec é uma reestruturação maior e não
  necessária para resolver o problema de sobrescrita.
- Redesenhar `BaselineDiff`/`CandidateResolver`/qualquer mecânica de identidade de
  token — inalterados por esta spec (conforme já apontado como ortogonal na spec
  citada acima). Um único ponto pontual de `CandidateResolver` é corrigido (seção
  3.5), mas é uma correção de bug de "qual diretório informar ao extractor",
  não da lógica de identidade.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

- **`WorkspaceDir`** (`fs_io/workspace_dir.py:4-11`) — enum com os 7 diretórios do
  workspace (`curls`, `real_responses`, `real_requests`, `extractors`,
  `temp_extractors`, `mitm_capture`, `replays`). `Workspace.init` (abaixo) cria um
  subdiretório físico por membro.
- **`Workspace`** (`fs_io/workspace.py`) — classe de estado estático (nunca
  instanciada). `Workspace.init(output_dir)` (`workspace.py:18-25`) cria a raiz e,
  para cada `WorkspaceDir`, cria o subdiretório e faz `setattr(cls, ...)`. Helpers
  como `Workspace.response_file(index)` (`workspace.py:64-67`, retorna
  `cls.real_responses / f"res_{index:04d}.json"`) e `Workspace.request_file(index)`
  (`workspace.py:60-62`) dependem de `_ensure_initialized` (`27-32`). Chamado em
  `Engine.__init__` (`engine.py:37`, cobre `run`/`dry`) e
  `CliHandlers._prepare_replay_workspace` (`cli_handlers.py:104-110`, para `replay`,
  que exige o workspace já existir).
- **`Engine._process_entry`** (`engine.py:88-107`) — fluxo atual, compartilhado por
  `run --mode main` e `run --mode dry` (`DryEngine` herda de `Engine` e só
  sobrescreve `execute_step`):
  ```python
  def _process_entry(self, index, entry, first_entry) -> StepResponse:
      step: Step = HARParser.parse_entry(entry, index)
      self._persist_request_step(index, step.request)

      step.analysis = self.tracker.analyze_step(step, first_entry)
      self.token_resolver.resolve_all()

      response: StepResponse = self.execute_step(step)
      self._persist_response_step(index, response)
      print(f"Step {index} completed with status {response.status_code}")

      if response.status_code != 0:
          self._persist_template_curl(index, step.analysis.curl_template)

      return response

  def _persist_response_step(self, index: int, response: StepResponse) -> None:
      Workspace.response_file(index).write_text(response.model_dump_json(indent=2), encoding="utf-8")
  ```
  `step.response` (montado por `HARParser.parse_entry`, sempre disponível antes de
  `execute_step` rodar) já é a resposta original do HAR — ela só nunca é persistida
  separadamente porque, em modo `main`, é descartada em favor da resposta real
  (linha `response: StepResponse = self.execute_step(step)`).
- **`DryEngine`** (`engines/dry_engine.py`) — `USES_NETWORK: ClassVar[bool] = False`
  e:
  ```python
  def execute_step(self, step: Step) -> StepResponse:
      assert step.response is not None
      return step.response
  ```
  Ou seja, em modo `dry`, `response` (retornado a `_process_entry` e depois gravado
  por `_persist_response_step`) **é literalmente `step.response`** — a resposta do
  HAR, sem nenhuma diferença de conteúdo.
- **`TokenTracker`/`CandidateResolver`** (`tracking/token_tracker.py:16-27`,
  `tracking/candidate_resolver.py:33-44`) — recebem `responses_dir` no construtor.
  Hoje `Engine.__init__` sempre passa `Workspace.real_responses`
  (`engine.py:39,54`):
  ```python
  self.real_responses_dir: Path = Workspace.real_responses
  ...
  self.tracker: TokenTracker = TokenTracker(self.real_responses_dir, self.session_store, llm=llm)
  ```
  Esse `responses_dir` é usado por dois consumidores dentro de
  `CandidateResolver._process_candidate` (`candidate_resolver.py:49-69`):
  - `ResponseGrep.find(self.responses_dir, candidate.current_value)`
    (`candidate_resolver.py:50-52`) — varre (`grep -rlF --include=res_*.json`,
    `tracking/response_grep.py:57-78`) os arquivos já gravados **neste processo, step
    a step**, para achar em qual step um valor apareceu pela primeira vez
    (`origin_step`).
  - `CandidateResolver._load_response(step_index)` (`candidate_resolver.py:158-167`)
    — lê `self.responses_dir / f"res_{step_index:04d}.json"` para montar o
    `response_sample` usado pelos agents de extração
    (`_generate_new_extractor`/`_generate_extractor`, linhas 119-128, 169-195).
  - Um terceiro consumidor, **`CandidateResolver._check_persisted_slot`**
    (`candidate_resolver.py:102-112`), **não** usa `self.responses_dir` — chama
    `self.extractor_runner.run_existing(slot_id)` (linha 107) **sem** o parâmetro
    opcional `response_override_dir`. Isso já é uma inconsistência hoje (ver 3.5):
    o script do extractor, quando executado sem override explícito, cai no fallback
    hardcoded de `ExtractorTemplate.render_script`
    (`templates/extractor_template.py:52-56`):
    ```python
    override_dir = os.environ.get("HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR")
    if override_dir:
        response_file: Path = Path(override_dir) / "res_{step_index:04d}.json"
    else:
        response_file: Path = Path(__file__).resolve().parent.parent / "real_responses" / "res_{step_index:04d}.json"
    ```
    ou seja, sempre `real_responses/`, **mesmo quando `self.responses_dir` do
    `CandidateResolver` aponta para outro lugar**. Hoje isso não quebra nada porque
    `real_responses/` sempre tinha o conteúdo do step (não importa o modo). Deixa de
    ser inofensivo assim que `dry` parar de escrever ali (seção 3.3).
- **`ReplayTokenResolver`** (`replay/replay_token_resolver.py`) — resolve, por
  token, de onde ler a resposta de origem durante `replay`:
  ```python
  def _resolve_one(self, token_id, dependencies, schedule, replay_run_dir, res_refer_dir) -> bool:
      origin_step: Optional[int] = dependencies.get(token_id)
      override_dir: Path = replay_run_dir if origin_step in schedule else res_refer_dir
      value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
      ...
  ```
  `res_refer_dir` vem de `CliHandlers._resolve_response_reference_dir`
  (`cli_handlers.py:112-117`):
  ```python
  res_refer_dir: Path = project_config.response_reference_dir or Workspace.real_responses
  ```
  ou seja, hoje: config explícita (`ProjectConfig.response_reference_dir`,
  `models/config.py:21`) ou, por padrão, `Workspace.real_responses`.
- **`ReplayResultComparator`** (`replay/replay_result_comparator.py`) — compara,
  ao final do replay, o `status_code` do último `StepResponse` produzido contra o
  original daquele índice:
  ```python
  def matches_original(self, index: int, response: StepResponse) -> bool:
      try:
          original_text: str = Workspace.response_file(index).read_text(encoding="utf-8")
      except Exception as e:
          print(f"Could not read original response for step {index} to compare: {e}")
          return False
      ...
  ```
  Hardcoded para `Workspace.response_file` (`real_responses/`), **independente** de
  `res_refer_dir` — decisão já documentada e deliberada na spec do replay
  (`docs/20260731 Ferramenta de Replay/spec.md:386-392`): `response_reference_dir`
  só serve para resolver tokens de steps *anteriores* fora do schedule, sem garantia
  de cobrir o **último** step (o que está sendo validado aqui); `real_responses/`
  era, até hoje, a única fonte garantida a conter todo step de uma execução
  completa anterior.
- **`ReplayRunner`** (`replay/replay_runner.py:19-39,74-97`) — construído com
  `res_refer_dir: Path` fixo, repassado a cada chamada de
  `self.replay_token_resolver.resolve(curl_text, schedule, self.replay_run_dir, self.res_refer_dir)`
  (`replay_runner.py:78-80`).
- **`CliHandlers._build_replay_runner`** (`cli_handlers.py:119-146`) — monta
  `ReplayTokenResolver`/`ReplayRunner` para o comando `replay`, resolvendo
  `res_refer_dir` via `_resolve_response_reference_dir` (acima) antes de construir o
  runner.

## 3. Decisões de arquitetura

### 3.1 Novo diretório `original_responses/` no `Workspace`

- `WorkspaceDir` (`fs_io/workspace_dir.py`) ganha um novo membro:
  ```python
  ORIGINAL_RESPONSES = "original_responses"
  ```
  Passa a existir ao lado de `real_responses` — criado automaticamente por
  `Workspace.init` (mesmo loop `for workspace_dir in WorkspaceDir`, sem mudança
  nesse método).
- `Workspace` (`fs_io/workspace.py`) ganha o atributo de classe
  `original_responses: Path` (ao lado de `real_responses`) e o helper:
  ```python
  @classmethod
  def original_response_file(cls, index: int) -> Path:
      cls._ensure_initialized()
      return cls.original_responses / f"res_{index:04d}.json"
  ```
  Mesmo padrão de `response_file` (`workspace.py:64-67`) — mesmo nome de arquivo
  (`res_{index:04d}.json`), diretório diferente.

### 3.2 `Engine` passa a persistir a resposta original do HAR incondicionalmente

`_process_entry` já tem, em mãos, `step.response` (a resposta original do HAR,
montada por `HARParser.parse_entry` antes de qualquer execução) — hoje ele nunca é
gravado por si só. Passa a ser persistido em `original_responses/`, sempre, nos dois
modos, logo após o parse (mesmo ponto onde `_persist_request_step` já grava o
request original):

```python
def _process_entry(self, index, entry, first_entry) -> StepResponse:
    step: Step = HARParser.parse_entry(entry, index)
    self._persist_request_step(index, step.request)
    self._persist_original_response_step(index, step.response)

    step.analysis = self.tracker.analyze_step(step, first_entry)
    ...

def _persist_original_response_step(self, index: int, response: Optional[StepResponse]) -> None:
    assert response is not None
    Workspace.original_response_file(index).write_text(response.model_dump_json(indent=2), encoding="utf-8")
```

⚠️ Esse conteúdo é determinístico (vem só do HAR de entrada) — é reescrito a cada
execução (`main` ou `dry`), mas sempre com o mesmo valor para o mesmo HAR. Não há
"perda" possível aqui: sobrescrever com conteúdo idêntico é inofensivo. O ponto
central desta spec é parar de deixar esse conteúdo se misturar com o de
`real_responses/` — não impedir a reescrita em si.

### 3.3 `real_responses/` deixa de ser escrito em modo `dry`

`Engine._persist_response_step` (`engine.py:112-113`) permanece exatamente como
está — continua gravando em `real_responses/` a resposta retornada por
`execute_step`. Em modo `main`, essa resposta é genuinamente real (obtida via HTTP),
então o comportamento não muda.

`DryEngine` ganha um override que faz `_persist_response_step` virar no-op:

```python
class DryEngine(Engine):
    USES_NETWORK: ClassVar[bool] = False

    def execute_step(self, step: Step) -> StepResponse:
        assert step.response is not None
        return step.response

    def _persist_response_step(self, index: int, response: StepResponse) -> None:
        pass
```

Motivo: em modo `dry` não existe "resposta real de execução" — `response` aqui é,
por construção (`execute_step` acima), exatamente `step.response`, o mesmo conteúdo
já persistido em `original_responses/` pela 3.2. Gravar de novo em `real_responses/`
seria redundante e, pior, é exatamente a causa da sobrescrita destrutiva que esta
spec elimina. Com este override, `real_responses/` só é escrito quando uma execução
`main` realmente acontece — e continua vazio (o diretório existe, criado por
`Workspace.init`, mas sem arquivos) enquanto só houver rodado `dry` naquele
`output_dir`.

### 3.4 Diretório de leitura de `TokenTracker`/`CandidateResolver` passa a depender do modo

Hoje `Engine.__init__` sempre passa `Workspace.real_responses` para `TokenTracker`
(`engine.py:39,54`). Isso deixa de fazer sentido em modo `dry`, já que
`real_responses/` fica vazio (3.3) — o `ResponseGrep`/`_load_response` (seção 2)
precisam continuar enxergando, a cada step processado dentro do mesmo run, a
resposta que **esse run** acabou de "obter" (real, em `main`; original do HAR, em
`dry`).

```python
self.original_responses_dir: Path = Workspace.original_responses
self.tracking_responses_dir: Path = Workspace.real_responses if self.USES_NETWORK else Workspace.original_responses
...
self.tracker: TokenTracker = TokenTracker(self.tracking_responses_dir, self.session_store, llm=llm)
```

`self.USES_NETWORK` já é o discriminador polimórfico existente entre `Engine`
(`True`) e `DryEngine` (`False`) — reaproveitado aqui, nenhum flag novo é
necessário. O atributo `self.real_responses_dir` (hoje só lido nessas duas linhas)
é renomeado para `self.tracking_responses_dir` para não sugerir que é sempre
"resposta real" quando, em `dry`, passa a apontar para `original_responses/`.

⚠️ Isso não afeta `_persist_request_step`/`_persist_response_step`/
`_persist_original_response_step`, que continuam usando `Workspace.request_file`/
`Workspace.response_file`/`Workspace.original_response_file` diretamente (caminhos
fixos, não parametrizados por `responses_dir`).

### 3.5 Correção: `CandidateResolver._check_persisted_slot` passa o diretório explicitamente ao `ExtractorRunner`

Consequência direta da 3.3/3.4: com `dry` não escrevendo mais em `real_responses/`,
o fallback hardcoded do script gerado (`extractor_template.py:56`, sempre
`real_responses/`) passaria a **falhar silenciosamente** (arquivo inexistente) toda
vez que `_check_persisted_slot` reexecuta um extrator já persistido durante um run
`dry` — porque essa chamada específica (`candidate_resolver.py:107`) é a única, no
fluxo de `run`/`dry`, que não informa `response_override_dir`.

```python
def _check_persisted_slot(self, slot_id: str, candidate: DynamicToken) -> Tuple[SlotStatus, Optional[str]]:
    persisted: Optional[Extractor] = self.metadata_store.load(slot_id)
    if persisted is None:
        return SlotStatus.FREE, None

    result: Optional[str] = self.extractor_runner.run_existing(slot_id, self.responses_dir)
    ...
```

`self.responses_dir` já é exatamente o `tracking_responses_dir` passado pelo
`Engine` (via `TokenTracker`) — o mesmo diretório que `_load_response` (linha 159) já
usa para o mesmo propósito. Em `main`, `self.responses_dir` é `real_responses/`,
igual ao que o fallback hardcoded já resolvia — nenhuma mudança de comportamento
para `main`. `ExtractorTemplate.render_script`/o fallback hardcoded em si **não são
alterados**: continuam existindo como último recurso (ex.: alguém rodando o script
gerado manualmente, fora da aplicação), só deixam de ser alcançados por qualquer
caminho de produção depois desta correção.

### 3.6 Replay: fallback para `original_responses/` na resolução de tokens fora do schedule

`ReplayTokenResolver` passa a receber também o diretório de fallback
(`Workspace.original_responses`, fixo — não configurável, ao contrário de
`res_refer_dir`) e decide, por token e por step de origem, qual dos dois usar:

```python
def resolve(self, curl_text, schedule, replay_run_dir, res_refer_dir, original_responses_dir) -> Set[str]:
    ...
    for token_id in token_ids:
        if self._resolve_one(token_id, dependencies, schedule, replay_run_dir, res_refer_dir, original_responses_dir):
            static_token_ids.add(token_id)
    return static_token_ids

def _resolve_one(self, token_id, dependencies, schedule, replay_run_dir, res_refer_dir, original_responses_dir) -> bool:
    origin_step: Optional[int] = dependencies.get(token_id)
    if origin_step in schedule:
        override_dir: Path = replay_run_dir
    else:
        override_dir = self._reference_dir_for_step(origin_step, res_refer_dir, original_responses_dir)
    value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
    ...

@staticmethod
def _reference_dir_for_step(origin_step: Optional[int], res_refer_dir: Path, original_responses_dir: Path) -> Path:
    if origin_step is not None and (res_refer_dir / f"res_{origin_step:04d}.json").exists():
        return res_refer_dir
    return original_responses_dir
```

Prioridade: `res_refer_dir` (config explícita `response_reference_dir`, ou
`real_responses/` por padrão) vence quando tem o arquivo daquele step específico;
`original_responses/` é o fallback só quando `res_refer_dir` não tem esse step —
exatamente o caso de um workspace cujo `output_dir` só rodou `dry` até agora (onde
`real_responses/` está vazio). `origin_step is None` (dependência não resolvida)
mantém o comportamento atual (`res_refer_dir`, sem tentar montar filename).

### 3.7 Replay: fallback para `original_responses/` na comparação final

`ReplayResultComparator.matches_original` ganha o mesmo fallback de dois níveis:

```python
class ReplayResultComparator:
    STATUS_CODE_PATTERN: ClassVar[Pattern[str]] = re.compile(r'"status_code"\s*:\s*(\d+)')

    def matches_original(self, index: int, response: StepResponse) -> bool:
        original_text: Optional[str] = self._read_reference_text(index)
        if original_text is None:
            return False

        match: Optional[Match[str]] = self.STATUS_CODE_PATTERN.search(original_text)
        if match is None:
            print(f"Could not find status_code in original response for step {index} to compare.")
            return False
        return int(match.group(1)) == response.status_code

    @staticmethod
    def _read_reference_text(index: int) -> Optional[str]:
        for candidate in (Workspace.response_file(index), Workspace.original_response_file(index)):
            try:
                return candidate.read_text(encoding="utf-8")
            except Exception:
                continue
        print(f"Could not read reference response for step {index} to compare "
              f"(checked real_responses/ and original_responses/).")
        return None
```

Mesma prioridade da 3.6: tenta `real_responses/` primeiro (comportamento inalterado
para workspaces com `main` já rodado — continua sendo a fonte preferida, por ser a
resposta real obtida na última execução completa), cai para `original_responses/`
quando o arquivo daquele step específico não existir ali (workspace só com `dry`).

### 3.8 Fio de ligação: `CliHandlers`/`ReplayRunner` passam `Workspace.original_responses`

`ReplayRunner.__init__` ganha o parâmetro `original_responses_dir: Path`, guardado
como `self.original_responses_dir`, e `_run_step` passa a incluí-lo na chamada ao
resolver:

```python
static_token_ids: Set[str] = self.replay_token_resolver.resolve(
    curl_text, schedule, self.replay_run_dir, self.res_refer_dir, self.original_responses_dir
)
```

`CliHandlers._build_replay_runner` (`cli_handlers.py:119-146`) passa
`original_responses_dir=Workspace.original_responses` ao construir o `ReplayRunner` —
fixo, não vem de `ProjectConfig` (só `res_refer_dir`/`response_reference_dir`
continua configurável).

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `WorkspaceDir` | Novo membro `ORIGINAL_RESPONSES = "original_responses"` |
| `Workspace` | Novo atributo `original_responses: Path` + novo helper `original_response_file(index)` |
| `Engine` | Novo método `_persist_original_response_step`, chamado incondicionalmente em `_process_entry`; renomeia `self.real_responses_dir` → `self.tracking_responses_dir` (`Workspace.real_responses` em `main`, `Workspace.original_responses` em `dry`) |
| `DryEngine` | Override de `_persist_response_step` vira no-op (nunca escreve em `real_responses/`) |
| `CandidateResolver._check_persisted_slot` | Passa `self.responses_dir` explicitamente para `ExtractorRunner.run_existing` (corrige dependência implícita no fallback hardcoded) |
| `ReplayTokenResolver` | `resolve`/`_resolve_one` ganham parâmetro `original_responses_dir`; novo helper `_reference_dir_for_step` decide entre `res_refer_dir` e `original_responses_dir` por step |
| `ReplayResultComparator` | `matches_original` ganha fallback via novo `_read_reference_text` (`real_responses/` → `original_responses/`) |
| `ReplayRunner` | Novo parâmetro de construtor `original_responses_dir`, repassado à chamada de `resolve` |
| `CliHandlers._build_replay_runner` | Passa `original_responses_dir=Workspace.original_responses` ao construir `ReplayRunner` |

## 5. Casos de borda e comportamento de erro

- **`dry` seguido de `main` no mesmo `output_dir`**: `original_responses/` é
  reescrito com conteúdo idêntico (idempotente); `real_responses/` passa a existir
  pela primeira vez, populado pela execução `main`. Nenhuma perda de dado em
  nenhuma das duas execuções.
- **`main` seguido de `dry` no mesmo `output_dir`**: `original_responses/` é
  reescrito (idempotente); `real_responses/` **permanece intocado** — a resposta
  real da execução `main` anterior sobrevive à execução `dry` seguinte. Esse é o
  bug original, agora eliminado.
- **`output_dir` que só rodou `dry`, tentando `replay` depois**: com o fallback das
  seções 3.6/3.7, a resolução de tokens fora do schedule e a comparação final
  passam a usar `original_responses/` automaticamente — `replay` funciona mesmo sem
  nenhum `main` anterior. Se nem `real_responses/` nem `original_responses/`
  tiverem o arquivo do step em questão (ex.: `replay --mode slice` referenciando um
  índice que nenhuma execução anterior processou), o comportamento é o mesmo de
  hoje: `ReplayTokenResolver` imprime "Failed to resolve token ... extractor
  returned no value" e `ReplayResultComparator` imprime a mensagem de erro e reporta
  mismatch — não é um caso novo introduzido por esta spec.
- **Extractor gerado durante `dry` (a partir de `original_responses/`) reaproveitado
  depois durante `main` (que buscaria em `real_responses/`), ou vice-versa**: essa
  situação já existe hoje (reaproveitamento entre execuções é o assunto da spec
  `docs/20260803 Reaproveitamento de Extractores/`) e já é validada pelo mecanismo
  de `_check_slot`/`SlotStatus` da spec de Desambiguação
  (`candidate_resolver.py:86-117`): o extrator persistido só é aceito se, reexecutado
  contra a resposta atual, produzir exatamente o valor esperado; caso contrário
  cai em `MISMATCH` e um slot novo é criado (fork). Nenhuma mudança de
  comportamento aqui — a validação já é agnóstica a qual diretório a amostra veio.
- **`response_reference_dir` configurado explicitamente para um caminho custom**
  (`ProjectConfig.response_reference_dir`): continua tendo prioridade sobre
  `original_responses/` no fallback (seção 3.6), exatamente como já tinha prioridade
  sobre o default `Workspace.real_responses` antes desta spec.
- **`real_requests/`/`parse`**: fora de escopo (seção 1) — nenhum comportamento
  muda.

## 6. Referência

Todo código citado nesta spec e no `implementation_plan.md` gerado a partir dela
segue [[guia-de-estilo]] (`guia_de_estilo.md`) como padrão obrigatório de
implementação.
