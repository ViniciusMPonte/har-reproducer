# Plano de Implementação — Skip de Steps Não Suportados e Estabilidade do Proxy mitmdump

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `ProjectConfig`/`SkipRulesConfig`: novo modelo de skip rules configurável

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/config.py` (`ProjectConfig`, novo `SkipRulesConfig`), `har_reproducer/models/__init__.py` (exports)

**Contexto:**
`ProjectConfig` (`models/config.py`) é o modelo Pydantic carregado de `config.json` via `ProjectConfigLoader`. Todo campo é opcional com default, permitindo que qualquer `config.json` existente continue funcionando sem alteração. Esta task introduz o campo `skip_rules`, que vai guiar a decisão de pular steps por método HTTP (T03/T05) — protocolo/scheme não entra aqui, é hardcoded (spec seção 3.1).

**Estado atual:**
- `models/config.py` define `LLMSettings` e `ProjectConfig`, sem nenhum conceito de skip.
- `models/__init__.py` reexporta `LLMSettings, ProjectConfig` de `models.config`.

**Estado esperado depois:**
- Novo `SkipRulesConfig(BaseModel)` em `models/config.py`:
  ```python
  class SkipRulesConfig(BaseModel):
      methods: List[str] = Field(default_factory=lambda: ["OPTIONS"])
  ```
- `ProjectConfig` ganha o campo:
  ```python
  skip_rules: SkipRulesConfig = Field(default_factory=SkipRulesConfig)
  ```
- `models/__init__.py` importa `SkipRulesConfig` de `har_reproducer.models.config` e adiciona `"SkipRulesConfig"` a `__all__` (ordem alfabética, mesmo padrão das demais entradas).
- ⚠️ Não alterar `ProjectConfigLoader` — o carregamento via `TypeAdapter(ProjectConfig).validate_json(...)` já lida com campos novos com default automaticamente, nenhuma mudança necessária lá.

**Critérios de aceite:**
- [ ] `ProjectConfig().skip_rules.methods == ["OPTIONS"]` (default sem nenhum `config.json`).
- [ ] `ProjectConfig.model_validate({"skip_rules": {"methods": ["OPTIONS", "HEAD"]}}).skip_rules.methods == ["OPTIONS", "HEAD"]`.
- [ ] `ProjectConfig.model_validate({"skip_rules": {"methods": []}}).skip_rules.methods == []`.
- [ ] `from har_reproducer.models import SkipRulesConfig` funciona.
- [ ] Um `config.json` sem a chave `skip_rules` (ex.: o `config.json` atual do projeto) continua carregando sem erro, com `skip_rules.methods == ["OPTIONS"]`.

## [T02] — `StepResponse`: novos campos `skipped`/`skip_reason`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/http.py` (`StepResponse`)

**Contexto:**
`StepResponse` hoje não tem como distinguir "step pulado intencionalmente" de "erro real de rede" — os dois cenários usam `status_code = 0`. Esta task adiciona os dois campos que `Engine._skip_entry` (T05) vai popular; `status_code` continua significando exclusivamente resultado real de rede (spec seção 3.4).

**Estado atual:**
```python
class StepResponse(BaseModel):
    status_code: int
    headers: Dict[str, str] = Field(default_factory=dict)
    cookies: Dict[str, str] = Field(default_factory=dict)
    body: Optional[Union[str, bytes]] = None
    body_mime: Optional[str] = None
    redirect_url: Optional[str] = None
```

**Estado esperado depois:**
```python
class StepResponse(BaseModel):
    status_code: int
    headers: Dict[str, str] = Field(default_factory=dict)
    cookies: Dict[str, str] = Field(default_factory=dict)
    body: Optional[Union[str, bytes]] = None
    body_mime: Optional[str] = None
    redirect_url: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None
```
- ⚠️ Não reordenar os campos existentes — só adicionar os dois novos ao final, para minimizar o diff e preservar compatibilidade posicional de qualquer serialização existente.
- ⚠️ Não tocar em `StepRequest` nesta task — `is_skippable` já existe lá (`models/http.py:13`) e continua como está; só passa a ser efetivamente escrito por `Engine` em vez de `HARParser` (T04/T05).

**Critérios de aceite:**
- [ ] `StepResponse(status_code=200).skipped is False` e `.skip_reason is None` (defaults).
- [ ] `StepResponse(status_code=0, skipped=True, skip_reason="unsupported scheme 'ws'").model_dump()` inclui as duas novas chaves.
- [ ] `StepResponse.model_validate_json('{"status_code": 200}')` continua funcionando (JSON antigo, sem as novas chaves, carrega com os defaults).
- [ ] Nenhum teste de serialização de um `StepResponse` já existente (ex.: um `res_XXXX.json` de uma run anterior) quebra ao ser recarregado.

## [T03] — `StepSkipEvaluator`: novo componente que decide se um step deve ser pulado

**Depende de:** T01 (usa `SkipRulesConfig`).
**Arquivos envolvidos:** `har_reproducer/reproduction/step_skip_evaluator.py` (novo arquivo), `har_reproducer/reproduction/__init__.py` (exports)

**Contexto:**
Hoje a decisão de "step pulável" vive, morta, dentro de `HARParser.parse_entry` (`SKIPPABLE_METHODS`, nunca lido — spec seção 2). Esta task cria o componente que efetivamente vai decidir isso, com duas regras independentes: scheme fora de `{http, https}` é sempre pulado (limitação técnica fixa do transporte `curl`, spec seção 3.1) e método HTTP em `skip_rules.methods` (configurável, vindo de T01).

**Estado atual:**
Não existe — `HARParser.SKIPPABLE_METHODS`/`is_skippable` (`fs_io/har_parser.py:12,58`) é o único ponto parecido, e é dead code (será removido em T04).

**Estado esperado depois:**
Novo arquivo `har_reproducer/reproduction/step_skip_evaluator.py`:
```python
class StepSkipEvaluator:
    ALLOWED_SCHEMES: ClassVar[Set[str]] = {"http", "https"}

    def __init__(self, skip_rules: SkipRulesConfig) -> None:
        self.skip_rules: SkipRulesConfig = skip_rules

    def skip_reason(self, request: StepRequest) -> Optional[str]:
        scheme: str = urlparse(request.url).scheme.lower()
        if scheme not in self.ALLOWED_SCHEMES:
            return f"unsupported scheme '{scheme}'"
        if request.method in self.skip_rules.methods:
            return f"skippable method '{request.method}'"
        return None
```
- `har_reproducer/reproduction/__init__.py` importa `StepSkipEvaluator` e adiciona `"StepSkipEvaluator"` a `__all__` (mesmo padrão das demais entradas, ex.: `CurlGenerator`, `StepRetryPolicy`).
- ⚠️ A checagem de scheme vem **antes** da checagem de método (spec seção 5, "entrada com método customizado que também tem scheme inválido") — se os dois motivos se aplicarem, só o de scheme é reportado.
- ⚠️ `skip_reason` retorna `None` (não pula) quando nem scheme nem método batem — esse é o caso comum (qualquer request `http`/`https` com método não listado em `skip_rules.methods`).

**Critérios de aceite:**
- [ ] `StepSkipEvaluator(SkipRulesConfig()).skip_reason(StepRequest(url="ws://x/y", method="GET"))` retorna `"unsupported scheme 'ws'"`.
- [ ] `StepSkipEvaluator(SkipRulesConfig()).skip_reason(StepRequest(url="https://x/y", method="OPTIONS"))` retorna `"skippable method 'OPTIONS'"`.
- [ ] `StepSkipEvaluator(SkipRulesConfig()).skip_reason(StepRequest(url="https://x/y", method="GET"))` retorna `None`.
- [ ] `StepSkipEvaluator(SkipRulesConfig(methods=[])).skip_reason(StepRequest(url="https://x/y", method="OPTIONS"))` retorna `None` (lista de métodos vazia desliga o skip por método, protocolo continua valendo).
- [ ] `StepSkipEvaluator(SkipRulesConfig()).skip_reason(StepRequest(url="wss://x/y", method="OPTIONS"))` retorna o motivo de **scheme**, não o de método.
- [ ] `from har_reproducer.reproduction import StepSkipEvaluator` funciona.

## [T04] — `HARParser`: remove cálculo morto de `is_skippable`

**Depende de:** T03 (a lógica é consolidada em `StepSkipEvaluator` antes de ser removida daqui).
**Arquivos envolvidos:** `har_reproducer/fs_io/har_parser.py` (`HARParser`)

**Contexto:**
`HARParser.parse_entry` calcula `is_skippable` usando `SKIPPABLE_METHODS`, mas esse valor nunca é lido em lugar nenhum do código (spec seção 2) — é dead code confirmado. Com `StepSkipEvaluator` (T03) assumindo essa responsabilidade de forma config-driven, este cálculo morto é removido do parser, que não tem (e não deveria precisar ter) acesso à configuração do projeto.

**Estado atual:**
```python
class HARParser:

    SKIPPABLE_METHODS: set[str] = {"OPTIONS"}
    ...
    @staticmethod
    def parse_entry(entry: Dict[str, Any], index: int) -> Step:
        ...
        is_skippable: bool = req_data["method"] in HARParser.SKIPPABLE_METHODS

        request: StepRequest = StepRequest(
            url=req_data["url"],
            method=req_data["method"],
            headers=req_headers,
            cookies=req_cookies,
            body=req_body,
            is_skippable=is_skippable
        )
        ...
```

**Estado esperado depois:**
```python
class HARParser:
    ...
    @staticmethod
    def parse_entry(entry: Dict[str, Any], index: int) -> Step:
        ...
        request: StepRequest = StepRequest(
            url=req_data["url"],
            method=req_data["method"],
            headers=req_headers,
            cookies=req_cookies,
            body=req_body,
        )
        ...
```
- Remove a constante de classe `SKIPPABLE_METHODS` inteira (linha 12) e a linha que calcula `is_skippable` (linha 58), e o argumento `is_skippable=is_skippable` da construção de `StepRequest`.
- `StepRequest.is_skippable` continua existindo no modelo (`models/http.py:13`, não tocado por esta task) com seu default `False` — passa a ser sobrescrito por `Engine._process_entry` (T05), não mais aqui.
- ⚠️ Não alterar nenhum outro método de `HARParser` (`load_har`, `get_entries`, `decode_body`, `split_har`) — mudança isolada a `parse_entry` e à constante removida.

**Critérios de aceite:**
- [ ] `HARParser` não tem mais o atributo `SKIPPABLE_METHODS`.
- [ ] `HARParser.parse_entry(entry, 0).request.is_skippable is False` para qualquer `entry` (default do modelo, já que o parser não seta mais esse campo) — incluindo uma entry com `method: "OPTIONS"`.
- [ ] `CurlHttpTransport._try_read_capture` (que chama `HARParser.parse_entry(entries[0], step_index)` só para ler `.response`) continua funcionando sem nenhuma mudança — garantia de não-regressão.
- [ ] `HARParser.split_har` continua produzindo `req_XXXX.json`/`res_XXXX.json` idênticos ao comportamento atual, exceto pela ausência de `is_skippable=True` em entries `OPTIONS` (que já era, na prática, um valor nunca consumido).

## [T05] — `Engine`: pula análise e execução de rede para steps skippable; validação final ignora respostas puladas

**Depende de:** T01, T02, T03, T04.
**Arquivos envolvidos:** `har_reproducer/engines/engine.py` (`Engine`)

**Contexto:**
Este é o ponto de integração: `Engine` passa a usar `StepSkipEvaluator` (T03, configurado com `project_config.skip_rules` de T01) para decidir, a cada step, se deve pular análise de tokens (`analyze_step`, que pode chamar LLM) e execução de rede (`execute_step`) — persistindo em vez disso uma resposta marcada como pulada (`StepResponse.skipped`, T02). A validação final (`_validate_final`) passa a ignorar respostas puladas ao decidir qual foi a "última resposta" da run (spec seção 3.7).

**Estado atual:**
```python
def __init__(self, ..., proxy_port=None, ca_cert_path=None) -> None:
    ...
    project_config: ProjectConfig = ProjectConfigLoader.load(config_path)

    self.http_transport: Optional[CurlHttpTransport] = self._build_http_transport(proxy_port, ca_cert_path)
    self.token_resolver: TokenResolver = TokenResolver(self.tracking_responses_dir, self.session_store)

    self.success_criteria: List[SuccessCriterion] = project_config.success_criteria
    llm: Optional[BaseChatModel] = self._build_llm(project_config)
    self.tracker: TokenTracker = TokenTracker(self.tracking_responses_dir, self.session_store, llm=llm)

def _reproduce(self) -> bool:
    entries: List[Dict[str, Any]] = HARParser.get_entries(self.har_path)
    first_entry: Step = HARParser.parse_entry(entries[0], 0)

    last_response: Optional[StepResponse] = None
    for index, entry in enumerate(entries):
        last_response = self._process_entry(index, entry, first_entry)

    return self._validate_final(last_response)

def _process_entry(self, index, entry, first_entry) -> StepResponse:
    step: Step = HARParser.parse_entry(entry, index)
    self._persist_request_step(index, step.request)
    self._persist_original_response_step(index, step.response)

    step.analysis = self.tracker.analyze_step(step, first_entry)
    if self.USES_NETWORK:
        self.token_resolver.resolve_all()

    response: StepResponse = self.execute_step(step)
    self._persist_response_step(index, response)
    print(f"Step {index} completed with status {response.status_code}")

    if response.status_code != 0:
        self._persist_template_curl(index, step.analysis.curl_template)

    return response
```

**Estado esperado depois:**
`__init__` ganha o evaluator (logo após `project_config` estar disponível):
```python
self.skip_evaluator: StepSkipEvaluator = StepSkipEvaluator(project_config.skip_rules)
```

`_reproduce` só atualiza `last_response` para respostas não puladas:
```python
def _reproduce(self) -> bool:
    entries: List[Dict[str, Any]] = HARParser.get_entries(self.har_path)
    first_entry: Step = HARParser.parse_entry(entries[0], 0)

    last_response: Optional[StepResponse] = None
    for index, entry in enumerate(entries):
        response: StepResponse = self._process_entry(index, entry, first_entry)
        if not response.skipped:
            last_response = response

    return self._validate_final(last_response)
```

`_process_entry` decide o skip logo após o parse, antes de persistir (para que `is_skippable` já esteja correto no `req_XXXX.json`) e antes de `analyze_step`/`resolve_all`/`execute_step`:
```python
def _process_entry(self, index, entry, first_entry) -> StepResponse:
    step: Step = HARParser.parse_entry(entry, index)
    skip_reason: Optional[str] = self.skip_evaluator.skip_reason(step.request)
    step.request.is_skippable = skip_reason is not None

    self._persist_request_step(index, step.request)
    self._persist_original_response_step(index, step.response)

    if skip_reason is not None:
        return self._skip_entry(index, skip_reason)

    step.analysis = self.tracker.analyze_step(step, first_entry)
    if self.USES_NETWORK:
        self.token_resolver.resolve_all()

    response: StepResponse = self.execute_step(step)
    self._persist_response_step(index, response)
    print(f"Step {index} completed with status {response.status_code}")

    if response.status_code != 0:
        self._persist_template_curl(index, step.analysis.curl_template)

    return response
```

Novo método privado:
```python
def _skip_entry(self, index: int, reason: str) -> StepResponse:
    response: StepResponse = StepResponse(status_code=0, skipped=True, skip_reason=reason)
    self._persist_response_step(index, response)
    print(f"Step {index} skipped ({reason})")
    return response
```

- ⚠️ `_skip_entry` chama `self._persist_response_step` (não `Engine._persist_response_step`) — em `DryEngine`, que sobrescreve esse método como no-op, isso preserva o comportamento já existente de não reescrever nada em `real_responses`/`original_responses` além do que `_persist_original_response_step` já grava.
- ⚠️ `_persist_template_curl` nunca é chamado para um step pulado — o `return self._skip_entry(...)` acontece antes de qualquer chance de chamá-lo, preservando o efeito colateral de hoje (entradas que já falham não geram `req_XXXX.curl.sh`, spec seção 2/3.3).
- ⚠️ `handle_recovery`/`execute_step`/`retry_policy` não são tocados por esta task — continuam exatamente como estão, só deixam de ser chamados para steps pulados.
- `DryEngine` não precisa de nenhuma mudança — herda o novo `_process_entry`/`_reproduce` da base sem overrides.

**Critérios de aceite:**
- [ ] Uma entry com `request.url` começando em `wss://` produz `Step {index} skipped (unsupported scheme 'wss')` no output e um `StepResponse` persistido com `skipped=True`, `skip_reason="unsupported scheme 'wss'"`, sem nenhuma chamada a `execute_step`/`tracker.analyze_step`.
- [ ] Uma entry com `method="OPTIONS"` (config default) produz o mesmo comportamento de skip, com `skip_reason="skippable method 'OPTIONS'"`.
- [ ] Com `config.json` definindo `"skip_rules": {"methods": []}`, a mesma entry `OPTIONS` **não** é pulada e segue o fluxo normal (`analyze_step`/`execute_step`).
- [ ] Nenhum `req_XXXX.curl.sh` é criado em `Workspace.curls` para um índice pulado.
- [ ] Se a **última** entry do HAR for pulada, `_validate_final` recebe a última resposta **não** pulada anterior (não o `StepResponse` de skip) — verificável rodando um HAR onde a última entry é `ws://` e checando que a validação final reflete o penúltimo step.
- [ ] Uma run completa contra um HAR sem nenhuma entry pulável produz exatamente o mesmo output (`Step N completed with status X` para todo N, mesmos arquivos persistidos) que a versão anterior a esta task — garantia de não-regressão.

## [T06] — `CurlHttpTransport`: corrige flag de TLS inválida (`--ssl-insecure` → `--insecure`)

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/reproduction/curl_http_transport.py` (`CurlHttpTransport._tls_flag`)

**Contexto:**
`_tls_flag` usa `--ssl-insecure` quando não há `ca_cert_path` configurado, mas essa flag não existe no `curl` (`curl: option --ssl-insecure: is unknown`, exit code 2 — confirmado neste ambiente com `curl 8.5.0`). A flag correta para ignorar verificação de certificado TLS é `-k`/`--insecure`.

**Estado atual:**
```python
def _tls_flag(self) -> str:
    if self.ca_cert_path is None:
        return "--ssl-insecure"

    return f"--cacert {shlex.quote(str(self.ca_cert_path))}"
```

**Estado esperado depois:**
```python
def _tls_flag(self) -> str:
    if self.ca_cert_path is None:
        return "--insecure"

    return f"--cacert {shlex.quote(str(self.ca_cert_path))}"
```
- ⚠️ Mudança de uma linha só — o branch `ca_cert_path is not None` (o caminho realmente usado hoje em toda run com o `MitmProxyOrchestrator`, que sempre popula `ca_cert_path`) não muda.

**Critérios de aceite:**
- [ ] `CurlHttpTransport(port=1234, ca_cert_path=None)._tls_flag() == "--insecure"`.
- [ ] `CurlHttpTransport(port=1234, ca_cert_path=Path("/tmp/x.pem"))._tls_flag() == "--cacert /tmp/x.pem"` (comportamento não mudou nesse branch).
- [ ] `bash -c "curl --insecure https://example.com -o /dev/null -sS"` retorna exit code 0 neste ambiente (validação manual de que a flag é reconhecida pelo `curl` instalado).

## [T07] — `Workspace`: novo `mitm_log_file()`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/fs_io/workspace.py` (`Workspace`)

**Contexto:**
`MitmProxyOrchestrator` (T08) precisa de um caminho de arquivo real em disco para redirecionar o stdout/stderr do `mitmdump`, em vez do `subprocess.PIPE` nunca drenado que causa o deadlock (spec seção 3.5). `Workspace` já tem um diretório dedicado a artefatos do `mitmdump` (`mitm_capture`, usado hoje só por `mitm_capture_file`); este novo método reaproveita o mesmo diretório.

**Estado atual:**
`Workspace` não tem nenhum método para um arquivo de log do `mitmdump`. Método existente equivalente, para referência de padrão:
```python
@classmethod
def mitm_capture_file(cls) -> Path:
    cls._ensure_initialized()
    return cls.mitm_capture / "capture.har"
```

**Estado esperado depois:**
Novo método, no mesmo bloco de métodos relacionados a `mitm_capture` (logo abaixo de `mitm_capture_file`):
```python
@classmethod
def mitm_log_file(cls) -> Path:
    cls._ensure_initialized()
    return cls.mitm_capture / "mitmdump.log"
```
- ⚠️ Não criar uma nova entrada em `WorkspaceDir` — reaproveita o diretório `mitm_capture` já existente, mesmo padrão de `mitm_capture_file`.

**Critérios de aceite:**
- [ ] Depois de `Workspace.init(output_dir)`, `Workspace.mitm_log_file() == output_dir / "mitm_capture" / "mitmdump.log"`.
- [ ] Chamar `Workspace.mitm_log_file()` antes de `Workspace.init(...)` levanta `RuntimeError` (mesmo comportamento de `_ensure_initialized` já usado por todo método equivalente, ex.: `mitm_capture_file`).
- [ ] `Workspace.mitm_capture_file()` continua retornando `mitm_capture/capture.har`, sem nenhuma mudança — garantia de não-regressão.

## [T08] — `MitmProxyOrchestrator`: redireciona stdout/stderr do `mitmdump` para arquivo em disco em vez de `subprocess.PIPE`

**Depende de:** T07 (usa `Workspace.mitm_log_file()`).
**Arquivos envolvidos:** `har_reproducer/reproduction/mitm_proxy_orchestrator.py` (`MitmProxyOrchestrator`)

**Contexto:**
Esta é a correção da Falha 2 (spec seção 1/3.5): `_start_process` sobe o `mitmdump` com `stdout=subprocess.PIPE, stderr=subprocess.STDOUT`, mas nada nunca lê esse pipe depois que o processo sobe. O `mitmdump` loga uma linha por request nesse stdout; depois de ~187 requests o buffer padrão do pipe no Linux (65536 bytes, confirmado ao vivo via `/proc/<pid>/fdinfo` durante a run travada) enche, a escrita do `mitmdump` bloqueia e, como ele roda num único loop assíncrono, todo o processo trava — nenhuma requisição nova é atendida até o `subprocess.run(timeout=30.0)` do lado do `curl` matar cada tentativa. Confirmado ao vivo: drenar manualmente esse pipe destravou o proxy instantaneamente. A correção troca o pipe por um arquivo real em disco, que nunca enche.

**Estado atual:**
```python
def __init__(self, proxy_port: Optional[int], project_root: Path) -> None:
    self.project_root: Path = project_root
    self.port: int = self._resolve_port(proxy_port)
    self.ca_cert_path: Path = self.project_root / self.CA_CERT_FILENAME
    self._process: Optional[subprocess.Popen] = None

def _start_process(self) -> subprocess.Popen:
    return subprocess.Popen(
        self._build_command(),
        env=self._build_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

def _build_early_exit_message(self) -> str:
    assert self._process is not None
    output: str = ""
    if self._process.stdout is not None:
        output = self._process.stdout.read().decode("utf-8", errors="replace")
    return f"mitmdump encerrou antes de ficar pronto (exit code {self._process.returncode}):\n{output}"

def _terminate(self) -> None:
    if self._process is None:
        return

    self._process.terminate()
    try:
        self._process.wait(timeout=self.TERMINATE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        self._process.kill()
        self._process.wait()
    self._process = None
```

**Estado esperado depois:**
`__init__` ganha o novo atributo:
```python
def __init__(self, proxy_port: Optional[int], project_root: Path) -> None:
    self.project_root: Path = project_root
    self.port: int = self._resolve_port(proxy_port)
    self.ca_cert_path: Path = self.project_root / self.CA_CERT_FILENAME
    self._process: Optional[subprocess.Popen] = None
    self._log_file: Optional[IO[str]] = None
```

`_start_process` abre o arquivo (truncando, modo `"w"`) e o usa como `stdout`/`stderr`:
```python
def _start_process(self) -> subprocess.Popen:
    self._log_file = open(Workspace.mitm_log_file(), "w", encoding="utf-8")
    return subprocess.Popen(
        self._build_command(),
        env=self._build_env(),
        stdout=self._log_file,
        stderr=subprocess.STDOUT,
    )
```

`_build_early_exit_message` lê o arquivo em disco em vez de `self._process.stdout` (que passa a ser sempre `None`, já que só é populado pelo Python quando `stdout=PIPE`):
```python
def _build_early_exit_message(self) -> str:
    assert self._process is not None
    log_path: Path = Workspace.mitm_log_file()
    output: str = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    return f"mitmdump encerrou antes de ficar pronto (exit code {self._process.returncode}):\n{output}"
```

`_terminate` fecha o arquivo depois do processo confirmadamente ter encerrado:
```python
def _terminate(self) -> None:
    if self._process is None:
        return

    self._process.terminate()
    try:
        self._process.wait(timeout=self.TERMINATE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        self._process.kill()
        self._process.wait()
    self._process = None

    if self._log_file is not None:
        self._log_file.close()
        self._log_file = None
```
- Import novo necessário: `IO` de `typing` (`from typing import IO, ...`).
- Import já existente `Workspace` (`from har_reproducer.fs_io import Workspace`, linha 10) é reaproveitado — nenhum import novo de módulo, só o novo símbolo `IO`.
- ⚠️ `stderr=subprocess.STDOUT` continua funcionando exatamente igual apontando para um arquivo real (não é uma feature exclusiva de `PIPE`) — o `subprocess` faz `dup2` do fd de stderr para o mesmo fd de stdout, seja ele um pipe ou um arquivo.
- ⚠️ O arquivo é reaberto (truncado) a cada `_start_process` — cada `run`/`replay` novo começa com um `mitmdump.log` limpo, mesmo sem `--reset` (mesmo padrão que `mitm_addon.py` já usa para `capture.har`).

**Critérios de aceite:**
- [ ] Depois de `orchestrator.run(callback)` completar (ou falhar) normalmente, `Workspace.mitm_log_file()` existe em disco e contém a saída do `mitmdump` daquela execução.
- [ ] Rodar mais de 187 requests sequenciais através do proxy (o volume que travava o pipe antes desta task) não produz nenhum "timed out after 30.0 seconds" — reproduzir com o HAR `arquivos-har/progressofit.har` completo e confirmar zero ocorrências de timeout de rede não relacionadas a `ws`/`wss`.
- [ ] Se o `mitmdump` morrer antes de ficar pronto (ex.: porta já ocupada por outro processo não-mitmproxy), a mensagem de erro (`_build_early_exit_message`) ainda inclui a saída relevante do `mitmdump`, lida do arquivo de log.
- [ ] `_terminate()` chamado duas vezes seguidas (idempotência, já garantida hoje por `self._process = None` na primeira chamada) não levanta exceção mesmo com o `_log_file` já fechado.
- [ ] O restante do fluxo de `run --mode main`/`replay` (captura de resposta via `Workspace.mitm_capture_file()`, health check via `_wait_until_ready`) continua funcionando sem nenhuma mudança de comportamento — garantia de não-regressão.

## [T09] — `README.md`: documenta o novo campo `skip_rules`

**Depende de:** T01 (precisa do shape final do campo).
**Arquivos envolvidos:** `README.md`

**Contexto:**
A seção "Configuração (`config.json`)" do `README.md` documenta todo campo de `ProjectConfig` com um exemplo de JSON e uma descrição em bullet point. `skip_rules` (T01) é um campo novo e precisa do mesmo tratamento, para que qualquer pessoa configurando o projeto saiba que pode personalizar quais métodos HTTP são pulados.

**Estado atual (`README.md`, seção "Configuração (`config.json`)"):**
```json
{
  "llm": {
    "provider": "google",
    "model": "gemini-3.1-flash-lite",
    "temperature": 0.0,
    "extra": {}
  },
  "success_criteria": [
    { "type": "status_code", "expected": 200 }
  ],
  "proxy_port": null,
  "ca_cert_path": null,
  "response_reference_dir": null
}
```
seguido da lista de bullets `**llm**`, `**success_criteria**`, `**proxy_port**`, `**ca_cert_path**`, `**response_reference_dir**`.

**Estado esperado depois:**
- Bloco de exemplo JSON ganha a chave `skip_rules`:
  ```json
  {
    "llm": { "...": "..." },
    "success_criteria": [
      { "type": "status_code", "expected": 200 }
    ],
    "proxy_port": null,
    "ca_cert_path": null,
    "response_reference_dir": null,
    "skip_rules": {
      "methods": ["OPTIONS"]
    }
  }
  ```
- Novo bullet, mesmo estilo dos demais, ao final da lista:
  ```markdown
  - **`skip_rules`** — regras de steps que são pulados (sem análise de tokens nem tentativa de requisição). `methods`: lista de métodos HTTP pulados; padrão `["OPTIONS"]`. Steps cujo protocolo não é `http`/`https` (ex.: `ws`/`wss`, capturados de upgrades de WebSocket) são sempre pulados, independente desta configuração — o transporte via `curl` não tem como executá-los.
  ```
- ⚠️ Não alterar nenhuma outra parte do `README.md` — mudança isolada à seção "Configuração (`config.json`)".

**Critérios de aceite:**
- [ ] O bloco de exemplo JSON da seção "Configuração (`config.json`)" inclui `skip_rules` com o mesmo shape aceito por `ProjectConfig` (T01).
- [ ] O novo bullet de `skip_rules` menciona explicitamente que o skip por protocolo (`ws`/`wss`) não é configurável.
- [ ] Nenhum outro trecho do `README.md` (seções de `run`/`replay`/instalação) é alterado.
