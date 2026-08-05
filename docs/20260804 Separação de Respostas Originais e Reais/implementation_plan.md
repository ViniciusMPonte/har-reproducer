# Plano de Implementação — Separação de Respostas Originais e Reais

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## T01 — `Workspace`/`WorkspaceDir`: novo diretório `original_responses/`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/fs_io/workspace_dir.py` (enum `WorkspaceDir`), `har_reproducer/fs_io/workspace.py` (classe `Workspace`)

**Contexto:**
Todas as tasks seguintes (T02-T08) precisam de um diretório novo, paralelo a
`real_responses/`, para guardar a resposta original do HAR de cada step — hoje esse
conteúdo nunca é persistido isoladamente. Esta task só cria o diretório e o helper de
path; nenhum comportamento de execução muda ainda (spec seção 3.1).

**Estado atual:**
```python
# fs_io/workspace_dir.py
class WorkspaceDir(str, Enum):
    CURLS = "curls"
    REAL_RESPONSES = "real_responses"
    REAL_REQUESTS = "real_requests"
    EXTRACTORS = "extractors"
    TEMP_EXTRACTORS = "temp_extractors"
    MITM_CAPTURE = "mitm_capture"
    REPLAYS = "replays"
```
```python
# fs_io/workspace.py
class Workspace:
    _output_dir: Optional[Path] = None

    curls: Path
    real_responses: Path
    real_requests: Path
    extractors: Path
    temp_extractors: Path
    mitm_capture: Path
    replays: Path

    ...

    @classmethod
    def response_file(cls, index: int) -> Path:
        cls._ensure_initialized()
        return cls.real_responses / f"res_{index:04d}.json"
```

**Estado esperado depois:**
```python
# fs_io/workspace_dir.py
class WorkspaceDir(str, Enum):
    CURLS = "curls"
    REAL_RESPONSES = "real_responses"
    ORIGINAL_RESPONSES = "original_responses"
    REAL_REQUESTS = "real_requests"
    EXTRACTORS = "extractors"
    TEMP_EXTRACTORS = "temp_extractors"
    MITM_CAPTURE = "mitm_capture"
    REPLAYS = "replays"
```
```python
# fs_io/workspace.py
class Workspace:
    _output_dir: Optional[Path] = None

    curls: Path
    real_responses: Path
    original_responses: Path
    real_requests: Path
    extractors: Path
    temp_extractors: Path
    mitm_capture: Path
    replays: Path

    ...

    @classmethod
    def response_file(cls, index: int) -> Path:
        cls._ensure_initialized()
        return cls.real_responses / f"res_{index:04d}.json"

    @classmethod
    def original_response_file(cls, index: int) -> Path:
        cls._ensure_initialized()
        return cls.original_responses / f"res_{index:04d}.json"
```
`Workspace.init` (`workspace.py:18-25`) não precisa de nenhuma mudança de lógica — o
loop `for workspace_dir in WorkspaceDir` já cria o subdiretório físico e faz
`setattr(cls, workspace_dir.value, path)` para qualquer membro novo do enum
automaticamente.

⚠️ `original_response_file` usa o mesmo nome de arquivo (`res_{index:04d}.json`) que
`response_file` — só o diretório-base muda. Não introduzir prefixo/sufixo diferente.

**Critérios de aceite:**
- [x] `WorkspaceDir.ORIGINAL_RESPONSES.value == "original_responses"`.
- [x] Após `Workspace.init(tmp_path)`, `Workspace.original_responses == tmp_path / "original_responses"` e o diretório existe em disco.
- [x] `Workspace.original_response_file(3) == Workspace.original_responses / "res_0003.json"`.
- [x] Chamar `Workspace.original_response_file(0)` antes de `Workspace.init` levanta `RuntimeError` (mesmo comportamento de `_ensure_initialized` que `response_file`/`request_file` já têm).
- [x] Não regressão: `Workspace.response_file`/`Workspace.request_file`/demais helpers e os 7 diretórios já existentes continuam com os mesmos paths de antes.

## T02 — `Engine`: persistência incondicional da resposta original do HAR

**Depende de:** T01 (usa `Workspace.original_response_file`).
**Arquivos envolvidos:** `har_reproducer/engines/engine.py` (`Engine._process_entry`)

**Contexto:**
`_process_entry` já monta `step.response` (a resposta original do HAR, via
`HARParser.parse_entry`) antes de chamar `execute_step` — hoje esse valor nunca é
gravado isoladamente, só o retorno de `execute_step` é (que em modo `main` é outra
coisa: a resposta real). Esta task persiste `step.response` em
`original_responses/`, incondicionalmente, nos dois modos (spec seção 3.2).

**Estado atual:**
```python
def _process_entry(
        self,
        index: int,
        entry: Dict[str, Any],
        first_entry: Step,
) -> StepResponse:
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

def _persist_request_step(self, index: int, request: StepRequest) -> None:
    Workspace.request_file(index).write_text(request.model_dump_json(indent=2), encoding="utf-8")

def _persist_response_step(self, index: int, response: StepResponse) -> None:
    Workspace.response_file(index).write_text(response.model_dump_json(indent=2), encoding="utf-8")
```

**Estado esperado depois:**
```python
def _process_entry(
        self,
        index: int,
        entry: Dict[str, Any],
        first_entry: Step,
) -> StepResponse:
    step: Step = HARParser.parse_entry(entry, index)
    self._persist_request_step(index, step.request)
    self._persist_original_response_step(index, step.response)

    step.analysis = self.tracker.analyze_step(step, first_entry)
    self.token_resolver.resolve_all()

    response: StepResponse = self.execute_step(step)
    self._persist_response_step(index, response)
    print(f"Step {index} completed with status {response.status_code}")

    if response.status_code != 0:
        self._persist_template_curl(index, step.analysis.curl_template)

    return response

def _persist_request_step(self, index: int, request: StepRequest) -> None:
    Workspace.request_file(index).write_text(request.model_dump_json(indent=2), encoding="utf-8")

def _persist_original_response_step(self, index: int, response: Optional[StepResponse]) -> None:
    assert response is not None
    Workspace.original_response_file(index).write_text(response.model_dump_json(indent=2), encoding="utf-8")

def _persist_response_step(self, index: int, response: StepResponse) -> None:
    Workspace.response_file(index).write_text(response.model_dump_json(indent=2), encoding="utf-8")
```
O `assert response is not None` espelha o mesmo padrão já usado em
`DryEngine.execute_step` (`engines/dry_engine.py:11`) para o mesmo campo
(`step.response` é `Optional[StepResponse]` em `models/http.py:28`, mas sempre
populado por `HARParser.parse_entry` no fluxo real).

⚠️ `_persist_original_response_step` roda para **todo** step, nos dois modos —
`Engine`/`DryEngine` não sobrescrevem esse método (T03 só sobrescreve
`_persist_response_step`).

**Critérios de aceite:**
- [x] Rodando `run --mode dry` sobre um HAR de N entries, `original_responses/`
  contém `res_0000.json` .. `res_{N-1:04d}.json`, cada um com o conteúdo exato de
  `step.response` daquele índice (igual ao que `HARParser.parse_entry` monta a partir
  do HAR).
- [x] Rodando `run --mode main`, `original_responses/` é populado com o mesmo
  conteúdo (a resposta original do HAR), independente do resultado da chamada HTTP
  real.
- [x] Rodar `run` duas vezes seguidas sobre o mesmo `output_dir` e mesmo HAR não
  altera o conteúdo de `original_responses/` entre as duas execuções (idempotente).
- [x] Não regressão: `real_requests/`/`curls/` continuam sendo gravados exatamente
  como antes; `_persist_response_step`/`real_responses/` inalterados por esta task
  (a mudança de comportamento de `real_responses/` é da T03).

## T03 — `DryEngine`: `_persist_response_step` vira no-op

**Depende de:** T02 (a resposta original do HAR já está garantida em `original_responses/` antes de parar de gravá-la em `real_responses/`).
**Arquivos envolvidos:** `har_reproducer/engines/dry_engine.py` (`DryEngine`)

**Contexto:**
Em modo `dry`, `response` (retornado por `execute_step`) é sempre `step.response` —
não existe "resposta real de execução" nesse modo. Gravar esse valor em
`real_responses/` (comportamento atual) é o que causa a sobrescrita destrutiva
descrita na spec (seção 1): rodar `dry` depois de um `main` bem-sucedido apaga a
resposta real que o `main` tinha obtido. Esta task faz `dry` parar de escrever ali
de vez (spec seção 3.3).

**Estado atual:**
```python
from typing import ClassVar

from har_reproducer.engines.engine import Engine
from har_reproducer.models import Step, StepResponse


class DryEngine(Engine):
    USES_NETWORK: ClassVar[bool] = False

    def execute_step(self, step: Step) -> StepResponse:
        assert step.response is not None
        return step.response
```

**Estado esperado depois:**
```python
from typing import ClassVar

from har_reproducer.engines.engine import Engine
from har_reproducer.models import Step, StepResponse


class DryEngine(Engine):
    USES_NETWORK: ClassVar[bool] = False

    def execute_step(self, step: Step) -> StepResponse:
        assert step.response is not None
        return step.response

    def _persist_response_step(self, index: int, response: StepResponse) -> None:
        pass
```

⚠️ `_persist_response_step` de `Engine` (que grava em `real_responses/`) permanece
igual — é o `DryEngine` que sobrescreve para não-fazer-nada, não o inverso. Nenhuma
outra chamada a `_persist_response_step` (`engine.py:101`, dentro de
`_process_entry`) muda; o polimorfismo já resolve isso.

**Critérios de aceite:**
- [x] Rodando `run --mode dry` sobre um `output_dir` novo (ainda sem
  `real_responses/` populado), ao final `real_responses/` existe (criado por
  `Workspace.init`) mas está **vazio** — nenhum `res_XXXX.json` é criado ali.
- [x] Rodando `run --mode main` e, na sequência, `run --mode dry` sobre o mesmo
  `output_dir`, os arquivos em `real_responses/` gravados pelo `main` continuam
  presentes e com o mesmo conteúdo depois do `dry` rodar (não são apagados nem
  sobrescritos).
- [x] Não regressão: `run --mode main` continua gravando `real_responses/`
  normalmente (comportamento de `Engine._persist_response_step`, não tocado por
  esta task).

## T04 — `Engine`: diretório de tracking depende do modo (`tracking_responses_dir`)

**Depende de:** T01, T03 (a leitura precisa refletir que `dry` não escreve mais em `real_responses/`).
**Arquivos envolvidos:** `har_reproducer/engines/engine.py` (`Engine.__init__`)

**Contexto:**
`TokenTracker`/`CandidateResolver` recebem um `responses_dir` usado para localizar,
dentro do próprio run em andamento, a resposta de cada step já processado (via
`ResponseGrep.find` e `CandidateResolver._load_response`). Hoje esse diretório é
sempre `Workspace.real_responses`, o que deixa de fazer sentido em `dry` assim que
`real_responses/` fica vazio (T03) — o tracker precisa passar a olhar para
`original_responses/` nesse modo (spec seção 3.4).

**Estado atual:**
```python
def __init__(
        self,
        har_path: Path,
        output_dir: Path,
        config_path: Optional[Path] = None,
        proxy_port: Optional[int] = None,
        ca_cert_path: Optional[Path] = None,
) -> None:
    self.har_path: Path = har_path
    self.output_dir: Path = output_dir

    Workspace.init(output_dir)
    self.curls_dir: Path = Workspace.curls
    self.real_responses_dir: Path = Workspace.real_responses
    self.extractors_dir: Path = Workspace.extractors
    self.temp_extractors_dir: Path = Workspace.temp_extractors

    self.session_store: SessionStore = SessionStore()
    self.validator: Validator = Validator()
    self.retry_policy: StepRetryPolicy = StepRetryPolicy()

    project_config: ProjectConfig = ProjectConfigLoader.load(config_path)

    self.http_transport: Optional[CurlHttpTransport] = self._build_http_transport(proxy_port, ca_cert_path)
    self.token_resolver: TokenResolver = TokenResolver(self.session_store)

    self.success_criteria: List[SuccessCriterion] = project_config.success_criteria
    llm: Optional[BaseChatModel] = self._build_llm(project_config)
    self.tracker: TokenTracker = TokenTracker(self.real_responses_dir, self.session_store, llm=llm)
```

**Estado esperado depois:**
```python
def __init__(
        self,
        har_path: Path,
        output_dir: Path,
        config_path: Optional[Path] = None,
        proxy_port: Optional[int] = None,
        ca_cert_path: Optional[Path] = None,
) -> None:
    self.har_path: Path = har_path
    self.output_dir: Path = output_dir

    Workspace.init(output_dir)
    self.curls_dir: Path = Workspace.curls
    self.original_responses_dir: Path = Workspace.original_responses
    self.tracking_responses_dir: Path = Workspace.real_responses if self.USES_NETWORK else Workspace.original_responses
    self.extractors_dir: Path = Workspace.extractors
    self.temp_extractors_dir: Path = Workspace.temp_extractors

    self.session_store: SessionStore = SessionStore()
    self.validator: Validator = Validator()
    self.retry_policy: StepRetryPolicy = StepRetryPolicy()

    project_config: ProjectConfig = ProjectConfigLoader.load(config_path)

    self.http_transport: Optional[CurlHttpTransport] = self._build_http_transport(proxy_port, ca_cert_path)
    self.token_resolver: TokenResolver = TokenResolver(self.session_store)

    self.success_criteria: List[SuccessCriterion] = project_config.success_criteria
    llm: Optional[BaseChatModel] = self._build_llm(project_config)
    self.tracker: TokenTracker = TokenTracker(self.tracking_responses_dir, self.session_store, llm=llm)
```

⚠️ `self.real_responses_dir` é **renomeado** para `self.tracking_responses_dir` — é
o único lugar do arquivo onde esse atributo é lido (a busca por `real_responses_dir`
no restante de `engine.py` não retorna outras ocorrências), então não há mais nenhum
outro ponto para atualizar. `self.USES_NETWORK` já existe como `ClassVar` (`True` em
`Engine`, `False` em `DryEngine`, `engine.py:24`, `dry_engine.py:8`) — reaproveitado
aqui como discriminador, nenhum flag novo é criado. `_persist_request_step`/
`_persist_response_step`/`_persist_original_response_step` continuam usando
`Workspace.request_file`/`Workspace.response_file`/`Workspace.original_response_file`
diretamente — não são afetados por este atributo.

**Critérios de aceite:**
- [x] `Engine(...).tracking_responses_dir == Workspace.real_responses` (modo
  `main`).
- [x] `DryEngine(...).tracking_responses_dir == Workspace.original_responses` (modo
  `dry`).
- [x] Rodando `run --mode dry` sobre um HAR onde um valor dinâmico do step 2
  reaparece no step 5, a resolução do candidato no step 5 encontra `origin_step=2`
  corretamente (via `ResponseGrep.find` sobre `original_responses/`, que agora tem o
  conteúdo do step 2 graças à T02) — mesmo resultado de antes da mudança, só que
  lendo de outro diretório.
- [x] Não regressão: rodando `run --mode main`, a resolução de tokens continua
  encontrando `origin_step` normalmente via `real_responses/` (nenhuma mudança de
  comportamento para `main`).

## T05 — `CandidateResolver`: `_check_persisted_slot` passa diretório explícito ao `ExtractorRunner`

**Depende de:** T04 (`self.responses_dir` do `CandidateResolver` agora pode ser `original_responses/` em `dry`).
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (`CandidateResolver._check_persisted_slot`)

**Contexto:**
`_check_persisted_slot` reexecuta um extractor já persistido para validar se ainda
produz o valor esperado. Diferente de `_load_response` (que já usa
`self.responses_dir` explicitamente), essa chamada não informa
`response_override_dir` ao `ExtractorRunner.run_existing`, então o script gerado cai
no fallback hardcoded de `ExtractorTemplate.render_script`
(`templates/extractor_template.py:52-56`), que sempre aponta para `real_responses/`
— **mesmo quando `self.responses_dir` é `original_responses/`** (modo `dry`, a
partir da T04). Sem esta correção, todo `_check_persisted_slot` durante um run `dry`
passaria a falhar silenciosamente (arquivo inexistente em `real_responses/`, que a
T03 deixou vazio) assim que essa combinação acontecer (spec seção 3.5).

**Estado atual:**
```python
def _check_persisted_slot(self, slot_id: str, candidate: DynamicToken) -> Tuple[SlotStatus, Optional[str]]:
    persisted: Optional[Extractor] = self.metadata_store.load(slot_id)
    if persisted is None:
        return SlotStatus.FREE, None

    result: Optional[str] = self.extractor_runner.run_existing(slot_id)
    if result != candidate.current_value:
        return SlotStatus.MISMATCH, self._mismatch_error(result, candidate.current_value)

    self._accept_persisted_slot(slot_id, persisted, result)
    return SlotStatus.MATCH, None
```

**Estado esperado depois:**
```python
def _check_persisted_slot(self, slot_id: str, candidate: DynamicToken) -> Tuple[SlotStatus, Optional[str]]:
    persisted: Optional[Extractor] = self.metadata_store.load(slot_id)
    if persisted is None:
        return SlotStatus.FREE, None

    result: Optional[str] = self.extractor_runner.run_existing(slot_id, self.responses_dir)
    if result != candidate.current_value:
        return SlotStatus.MISMATCH, self._mismatch_error(result, candidate.current_value)

    self._accept_persisted_slot(slot_id, persisted, result)
    return SlotStatus.MATCH, None
```

⚠️ Em modo `main`, `self.responses_dir` é `Workspace.real_responses` — exatamente o
mesmo diretório que o fallback hardcoded já resolvia, então o comportamento em
`main` não muda. `ExtractorTemplate.render_script`/o fallback hardcoded em si **não
são alterados** por esta task — continuam existindo como último recurso para quem
rodar o script gerado manualmente fora da aplicação.

**Critérios de aceite:**
- [x] Rodando `run --mode dry` duas vezes seguidas sobre o mesmo `output_dir` e
  mesmo HAR (segunda vez reaproveitando extractors persistidos da primeira), a
  segunda execução resolve os mesmos tokens com `status="Resolved"` sem cair em
  `_generate_new_extractor` — ou seja, `_check_persisted_slot` consegue ler
  `original_responses/` corretamente e retorna `MATCH`.
- [x] Não regressão: o mesmo cenário rodando `run --mode main` duas vezes seguidas
  continua funcionando igual (reaproveitamento de extractors via `real_responses/`,
  comportamento inalterado).
- [x] `_load_response` (linha 158-167, não tocada por esta task) continua recebendo
  `self.responses_dir` do mesmo jeito que antes.

## T06 — `ReplayTokenResolver`: fallback para `original_responses/` na resolução de tokens fora do schedule

**Depende de:** T01 (usa `Workspace.original_responses` como diretório de fallback).
**Arquivos envolvidos:** `har_reproducer/replay/replay_token_resolver.py` (`ReplayTokenResolver`)

**Contexto:**
Durante `replay`, tokens cujo step de origem está fora do schedule desta execução
são resolvidos lendo a resposta desse step de `res_refer_dir` (config
`response_reference_dir`, ou `Workspace.real_responses` por padrão). Com a
separação desta spec, um `output_dir` que só rodou `dry` tem `real_responses/`
vazio — `res_refer_dir` (no default) não teria mais o arquivo desses steps. Esta
task adiciona um segundo diretório de fallback, `original_responses/`, sempre
disponível (populado por qualquer run, `main` ou `dry`, a partir da T02), consultado
quando `res_refer_dir` não tiver o arquivo daquele step específico (spec seção 3.6).

**Estado atual:**
```python
def resolve(
        self,
        curl_text: str,
        schedule: Set[int],
        replay_run_dir: Path,
        res_refer_dir: Path,
) -> Set[str]:
    dependencies: Dict[str, int] = self.dependency_parser.parse(curl_text)
    token_ids: Set[str] = set(SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text))
    static_token_ids: Set[str] = set()
    for token_id in token_ids:
        if self._resolve_one(token_id, dependencies, schedule, replay_run_dir, res_refer_dir):
            static_token_ids.add(token_id)
    return static_token_ids

def _resolve_one(
        self,
        token_id: str,
        dependencies: Dict[str, int],
        schedule: Set[int],
        replay_run_dir: Path,
        res_refer_dir: Path,
) -> bool:
    origin_step: Optional[int] = dependencies.get(token_id)
    override_dir: Path = replay_run_dir if origin_step in schedule else res_refer_dir
    value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
    if value is None:
        print(f"Failed to resolve token '{token_id}' during replay: extractor returned no value.")
        return False
    self.session_store.set_token(token_id, value)
    return self._record_observation(token_id, value)
```

**Estado esperado depois:**
```python
def resolve(
        self,
        curl_text: str,
        schedule: Set[int],
        replay_run_dir: Path,
        res_refer_dir: Path,
        original_responses_dir: Path,
) -> Set[str]:
    dependencies: Dict[str, int] = self.dependency_parser.parse(curl_text)
    token_ids: Set[str] = set(SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text))
    static_token_ids: Set[str] = set()
    for token_id in token_ids:
        if self._resolve_one(token_id, dependencies, schedule, replay_run_dir, res_refer_dir, original_responses_dir):
            static_token_ids.add(token_id)
    return static_token_ids

def _resolve_one(
        self,
        token_id: str,
        dependencies: Dict[str, int],
        schedule: Set[int],
        replay_run_dir: Path,
        res_refer_dir: Path,
        original_responses_dir: Path,
) -> bool:
    origin_step: Optional[int] = dependencies.get(token_id)
    if origin_step in schedule:
        override_dir: Path = replay_run_dir
    else:
        override_dir = self._reference_dir_for_step(origin_step, res_refer_dir, original_responses_dir)
    value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
    if value is None:
        print(f"Failed to resolve token '{token_id}' during replay: extractor returned no value.")
        return False
    self.session_store.set_token(token_id, value)
    return self._record_observation(token_id, value)

@staticmethod
def _reference_dir_for_step(
        origin_step: Optional[int],
        res_refer_dir: Path,
        original_responses_dir: Path,
) -> Path:
    if origin_step is not None and (res_refer_dir / f"res_{origin_step:04d}.json").exists():
        return res_refer_dir
    return original_responses_dir
```

⚠️ `origin_step is None` (dependência não resolvida pelo `CurlDependencyParser`)
mantém o comportamento atual — `_reference_dir_for_step` retorna `res_refer_dir`
sem tentar montar filename, igual ao `else res_refer_dir` de antes. A prioridade é
sempre `res_refer_dir` primeiro (config explícita ou `real_responses/`),
`original_responses_dir` só entra quando o arquivo daquele step específico não
existe em `res_refer_dir`.

**Critérios de aceite:**
- [x] `_reference_dir_for_step(2, res_refer_dir, original_responses_dir)` retorna
  `res_refer_dir` quando `res_refer_dir / "res_0002.json"` existe.
- [x] `_reference_dir_for_step(2, res_refer_dir, original_responses_dir)` retorna
  `original_responses_dir` quando `res_refer_dir / "res_0002.json"` **não** existe
  (ex.: `res_refer_dir == Workspace.real_responses` vazio, workspace só rodou
  `dry`).
- [x] `_reference_dir_for_step(None, res_refer_dir, original_responses_dir)` retorna
  `res_refer_dir` (não regressão do caso `origin_step` desconhecido).
- [x] Em um workspace que só rodou `dry` (portanto `real_responses/` vazio,
  `original_responses/` populado pela T02), `replay --mode smart` consegue resolver
  um token cujo `origin_step` está fora do schedule, lendo de `original_responses/`
  via este fallback.
- [x] Não regressão: em um workspace que rodou `main` (portanto `real_responses/`
  populado), o mesmo cenário continua resolvendo via `real_responses/`
  (`res_refer_dir`), sem cair no fallback.

## T07 — `ReplayResultComparator`: fallback para `original_responses/` na comparação final

**Depende de:** T01 (usa `Workspace.original_response_file`).
**Arquivos envolvidos:** `har_reproducer/replay/replay_result_comparator.py` (`ReplayResultComparator`)

**Contexto:**
Ao final do replay, `matches_original` compara o `status_code` do último response
produzido contra o original daquele índice, lido sempre de
`Workspace.response_file` (`real_responses/`) — decisão documentada na spec do
replay como a única fonte garantida a cobrir todo step de uma execução completa
anterior. Com a separação desta spec, essa garantia só vale depois de um `main`; um
workspace só com `dry` tem `real_responses/` vazio. Esta task adiciona o mesmo
fallback de dois níveis da T06, agora para a leitura de comparação (spec seção 3.7).

**Estado atual:**
```python
class ReplayResultComparator:
    STATUS_CODE_PATTERN: ClassVar[Pattern[str]] = re.compile(r'"status_code"\s*:\s*(\d+)')

    def matches_original(self, index: int, response: StepResponse) -> bool:
        try:
            original_text: str = Workspace.response_file(index).read_text(encoding="utf-8")
        except Exception as e:
            print(f"Could not read original response for step {index} to compare: {e}")
            return False

        match: Optional[Match[str]] = self.STATUS_CODE_PATTERN.search(original_text)
        if match is None:
            print(f"Could not find status_code in original response for step {index} to compare.")
            return False
        return int(match.group(1)) == response.status_code
```

**Estado esperado depois:**
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
        print(
            f"Could not read reference response for step {index} to compare "
            f"(checked real_responses/ and original_responses/)."
        )
        return None
```

⚠️ Mesma prioridade da T06: `real_responses/` é tentado primeiro (comportamento
inalterado para workspaces que já rodaram `main`), `original_responses/` só é usado
quando o arquivo daquele step não existe no primeiro.

**Critérios de aceite:**
- [x] Em um workspace com `real_responses/res_0005.json` presente,
  `matches_original(5, response)` lê exatamente esse arquivo — comportamento
  idêntico ao de antes desta task.
- [x] Em um workspace só com `dry` (portanto `real_responses/res_0005.json`
  ausente, mas `original_responses/res_0005.json` presente),
  `matches_original(5, response)` lê o conteúdo de `original_responses/` em vez de
  retornar `False` de imediato.
- [x] Em um workspace sem nenhum dos dois arquivos para o índice, `matches_original`
  retorna `False` e imprime a mensagem mencionando os dois diretórios checados
  (não regressão de "sempre falha de forma visível", só muda a mensagem).
- [x] Não regressão: `STATUS_CODE_PATTERN`/a lógica de comparação de `status_code`
  em si não mudam.

## T08 — `ReplayRunner`/`CliHandlers`: fio de ligação passando `original_responses_dir`

**Depende de:** T06, T07 (usa os novos parâmetros que essas tasks introduziram).
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py` (`ReplayRunner.__init__`, `ReplayRunner._run_step`), `har_reproducer/cli/cli_handlers.py` (`CliHandlers._build_replay_runner`)

**Contexto:**
T06 mudou a assinatura de `ReplayTokenResolver.resolve` para exigir
`original_responses_dir`. Esta task fecha o fio de ligação: `ReplayRunner` passa a
guardar esse diretório e repassá-lo na chamada ao resolver; `CliHandlers`, que
constrói o `ReplayRunner`, passa `Workspace.original_responses` — fixo, não vindo de
`ProjectConfig` (só `res_refer_dir`/`response_reference_dir` continua configurável)
(spec seção 3.8).

**Estado atual:**
```python
# replay/replay_runner.py
def __init__(
        self,
        dependency_parser: CurlDependencyParser,
        session_store: SessionStore,
        http_transport: CurlHttpTransport,
        replay_token_resolver: ReplayTokenResolver,
        retry_policy: StepRetryPolicy,
        comparator: ReplayResultComparator,
        run_id: str,
        replay_run_dir: Path,
        res_refer_dir: Path,
) -> None:
    self.dependency_parser: CurlDependencyParser = dependency_parser
    self.session_store: SessionStore = session_store
    self.http_transport: CurlHttpTransport = http_transport
    self.replay_token_resolver: ReplayTokenResolver = replay_token_resolver
    self.retry_policy: StepRetryPolicy = retry_policy
    self.comparator: ReplayResultComparator = comparator
    self.run_id: str = run_id
    self.replay_run_dir: Path = replay_run_dir
    self.res_refer_dir: Path = res_refer_dir

...

def _run_step(self, index: int, schedule: Set[int]) -> StepResponse:
    curl_text: str = Workspace.curl_file(index).read_text(encoding="utf-8")

    def attempt() -> StepResponse:
        static_token_ids: Set[str] = self.replay_token_resolver.resolve(
            curl_text, schedule, self.replay_run_dir, self.res_refer_dir
        )
        ...
```
```python
# cli/cli_handlers.py
@staticmethod
def _build_replay_runner(
        orchestrator: MitmProxyOrchestrator,
        run_id: str,
        res_refer_dir: Path,
) -> ReplayRunner:
    session_store: SessionStore = SessionStore()
    extractor_runner: ExtractorRunner = ExtractorRunner()
    dependency_parser: CurlDependencyParser = CurlDependencyParser()
    metadata_store: ExtractorMetadataStore = ExtractorMetadataStore()
    replay_token_resolver: ReplayTokenResolver = ReplayTokenResolver(
        session_store, extractor_runner, dependency_parser, metadata_store
    )
    retry_policy: StepRetryPolicy = StepRetryPolicy()
    comparator: ReplayResultComparator = ReplayResultComparator()
    http_transport: CurlHttpTransport = CurlHttpTransport(orchestrator.port, orchestrator.ca_cert_path)

    return ReplayRunner(
        dependency_parser=dependency_parser,
        session_store=session_store,
        http_transport=http_transport,
        replay_token_resolver=replay_token_resolver,
        retry_policy=retry_policy,
        comparator=comparator,
        run_id=run_id,
        replay_run_dir=Workspace.replay_run_dir(run_id),
        res_refer_dir=res_refer_dir,
    )
```

**Estado esperado depois:**
```python
# replay/replay_runner.py
def __init__(
        self,
        dependency_parser: CurlDependencyParser,
        session_store: SessionStore,
        http_transport: CurlHttpTransport,
        replay_token_resolver: ReplayTokenResolver,
        retry_policy: StepRetryPolicy,
        comparator: ReplayResultComparator,
        run_id: str,
        replay_run_dir: Path,
        res_refer_dir: Path,
        original_responses_dir: Path,
) -> None:
    self.dependency_parser: CurlDependencyParser = dependency_parser
    self.session_store: SessionStore = session_store
    self.http_transport: CurlHttpTransport = http_transport
    self.replay_token_resolver: ReplayTokenResolver = replay_token_resolver
    self.retry_policy: StepRetryPolicy = retry_policy
    self.comparator: ReplayResultComparator = comparator
    self.run_id: str = run_id
    self.replay_run_dir: Path = replay_run_dir
    self.res_refer_dir: Path = res_refer_dir
    self.original_responses_dir: Path = original_responses_dir

...

def _run_step(self, index: int, schedule: Set[int]) -> StepResponse:
    curl_text: str = Workspace.curl_file(index).read_text(encoding="utf-8")

    def attempt() -> StepResponse:
        static_token_ids: Set[str] = self.replay_token_resolver.resolve(
            curl_text, schedule, self.replay_run_dir, self.res_refer_dir, self.original_responses_dir
        )
        ...
```
```python
# cli/cli_handlers.py
@staticmethod
def _build_replay_runner(
        orchestrator: MitmProxyOrchestrator,
        run_id: str,
        res_refer_dir: Path,
) -> ReplayRunner:
    session_store: SessionStore = SessionStore()
    extractor_runner: ExtractorRunner = ExtractorRunner()
    dependency_parser: CurlDependencyParser = CurlDependencyParser()
    metadata_store: ExtractorMetadataStore = ExtractorMetadataStore()
    replay_token_resolver: ReplayTokenResolver = ReplayTokenResolver(
        session_store, extractor_runner, dependency_parser, metadata_store
    )
    retry_policy: StepRetryPolicy = StepRetryPolicy()
    comparator: ReplayResultComparator = ReplayResultComparator()
    http_transport: CurlHttpTransport = CurlHttpTransport(orchestrator.port, orchestrator.ca_cert_path)

    return ReplayRunner(
        dependency_parser=dependency_parser,
        session_store=session_store,
        http_transport=http_transport,
        replay_token_resolver=replay_token_resolver,
        retry_policy=retry_policy,
        comparator=comparator,
        run_id=run_id,
        replay_run_dir=Workspace.replay_run_dir(run_id),
        res_refer_dir=res_refer_dir,
        original_responses_dir=Workspace.original_responses,
    )
```

⚠️ `original_responses_dir` não é parâmetro de `_build_replay_runner` — vem direto
de `Workspace.original_responses` dentro do método, igual a como `replay_run_dir`
já vem direto de `Workspace.replay_run_dir(run_id)` na mesma chamada. Só
`res_refer_dir` continua sendo resolvido a partir de `ProjectConfig` (por
`_resolve_response_reference_dir`, não tocado por esta task).

**Critérios de aceite:**
- [x] `ReplayRunner(...).original_responses_dir == Workspace.original_responses`
  após construído via `CliHandlers._build_replay_runner`.
- [x] Um `replay --mode all` de ponta a ponta, sobre um workspace que só rodou
  `dry`, completa sem o erro "Failed to resolve token" para tokens cujo
  `origin_step` está fora do schedule (fallback da T06 alcançado através deste fio
  de ligação).
- [x] Não regressão: `replay` sobre um workspace que rodou `main` continua
  funcionando exatamente como antes (mesma resolução via `real_responses/`, mesma
  comparação final).
