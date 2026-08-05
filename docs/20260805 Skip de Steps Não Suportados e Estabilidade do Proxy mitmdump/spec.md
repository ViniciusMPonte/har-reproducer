# Spec — Skip de Steps Não Suportados e Estabilidade do Proxy mitmdump

> Fonte única de verdade para gerar o `implementation_plan.md` desta etapa. Assume que
> quem escreve o plano não participou da conversa que chegou a estas decisões — tudo
> que é necessário para entender o "porquê" e o "o quê" está aqui, sem depender de nada
> além do código-fonte atual do projeto (`har_reproducer/`) e do `guia_de_estilo.md`.

## 1. Objetivo

Rodando `run --mode main` contra um HAR real de 238 entries
(`arquivos-har/progressofit.har`), duas falhas foram observadas e diagnosticadas:

**Falha 1 — steps de WebSocket quebram com erro de curl.** O HAR contém entradas com
`request.url` em `ws://`/`wss://` (upgrade de WebSocket capturado pelo navegador). O
pipeline atual trata essas entradas como se fossem HTTP normal e monta um comando
`curl` para elas, que falha com `curl: (1) Protocol "ws" not supported or disabled in
libcurl` (3 ocorrências nesta run: steps 78, 90, 166). Isso não é uma falha de rede —
é uma impossibilidade técnica permanente do transporte atual (`curl` via
`--proxy`/HTTP), então a reprodução tentar essas entradas produz sempre o mesmo erro,
gastando um ciclo completo de análise de tokens (potencialmente com chamada de LLM) por
nada.

**Falha 2 — todo o proxy trava por ~13 steps seguidos, cada um pagando 30s de
timeout.** Verificado ao vivo durante a mesma execução: o `mitmdump` é iniciado via
`subprocess.Popen(..., stdout=subprocess.PIPE, stderr=subprocess.STDOUT)`
(`mitm_proxy_orchestrator.py:61-62`) e **nada nunca lê esse pipe** depois que o processo
sobe. Por padrão o `mitmdump` loga uma linha por request nesse stdout; depois de ~187
requests essa saída enche o buffer padrão do pipe no Linux (65536 bytes — confirmado via
`/proc/<pid>/fdinfo` durante a run travada). Quando o buffer enche, a escrita do
`mitmdump` bloqueia e, como ele roda num único loop assíncrono, **todo o processo trava**
— nenhuma requisição nova é atendida. Cada request golpeada por isso fica pendurada até
o `subprocess.run(..., timeout=30.0)` do lado do `curl` matar o processo
(`curl_http_transport.py:12,27`), daí o padrão observado no log: erro de rede idêntico
("timed out after 30.0 seconds") em ~13 steps consecutivos (188 a ~200), sem relação
alguma com o servidor de destino (testado: `127.0.0.1:8080` direto responde em ~1ms).
**Confirmado por intervenção ao vivo**: drenar manualmente o pipe interno do `mitmdump`
via `/proc/<pid>/fd/3` destravou o proxy instantaneamente (resposta em 9ms logo em
seguida) e o restante da run (steps ~200 a 237) completou normalmente sem nenhum outro
timeout.

**Achado adicional (mesma investigação, bug separado) — flag de TLS inválida.**
`CurlHttpTransport._tls_flag` (`curl_http_transport.py:52-56`) retorna `--ssl-insecure`
quando `ca_cert_path is None`. `--ssl-insecure` não é uma flag válida do `curl`
(`curl: option --ssl-insecure: is unknown`, exit code 2) — a flag correta para ignorar
verificação de certificado é `-k`/`--insecure`. Não se manifestou nesta run porque
`ca_cert_path` estava configurado (branch `--cacert` foi usada), mas quebra
imediatamente qualquer execução sem CA cert configurado.

Fora de escopo (não implementar agora):
- Qualquer suporte real a WebSocket (proxy/replay de tráfego `ws`/`wss`) — a decisão
  aqui é **pular** essas entradas de forma limpa, não reproduzi-las.
- Paralelização da execução dos steps (`Engine._reproduce`/`ReplayRunner._run_schedule`
  continuam sequenciais) — fora do escopo desta etapa, que trata de uma trava, não da
  velocidade de execução em si.
- Adicionar `--max-time`/`--connect-timeout` ao comando `curl` gerado — o timeout de
  30s do `subprocess.run` (`curl_http_transport.py:12,27`) já é suficiente depois que a
  causa raiz do travamento (Falha 2) é eliminada; sem a trava do pipe, nenhuma
  requisição contra um servidor saudável deveria se aproximar desse limite.
- Tornar o skip de protocolo (`ws`/`wss`) configurável — ver seção 3.1: é tratado como
  limitação técnica permanente do transporte, não como preferência de política.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

- **`HARParser.parse_entry`** (`fs_io/har_parser.py:44-67`) — método estático, chamado a
  cada step tanto pelo `Engine` (`engines/engine.py:81,95`) quanto por
  `CurlHttpTransport._try_read_capture` (`reproduction/curl_http_transport.py:76`, para
  ler a captura do `mitmdump` depois de um `curl` bem-sucedido). Hoje calcula:
  ```python
  is_skippable: bool = req_data["method"] in HARParser.SKIPPABLE_METHODS
  ```
  usando a constante `SKIPPABLE_METHODS: set[str] = {"OPTIONS"}` (linha 12). **Esse
  valor nunca é lido em lugar nenhum do código** — `StepRequest.is_skippable`
  (`models/http.py:13`) só é escrito aqui e nunca consultado por `Engine`,
  `ReplayRunner` ou qualquer outro componente. É código morto: mesmo uma entrada
  `OPTIONS` hoje passa pelo fluxo completo de análise e execução como qualquer outra.

- **`StepRequest`/`StepResponse`** (`models/http.py`) — modelos Pydantic simples, sem
  lógica. `StepResponse` hoje não distingue "erro real de rede" de nenhum outro estado
  além do `status_code` (`0` é usado hoje só para erro de rede, ver
  `CurlHttpTransport._build_error_response`, linha 82-94).

- **`Engine._process_entry`** (`engines/engine.py:89-110`) — laço por step:
  ```python
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
  `tracker.analyze_step` (`tracking/token_tracker.py:30-43`) pode acionar agentes de
  detecção de token e, na ausência deles, fallback de LLM (`candidate_resolver.py`) —
  custo real (tempo e possivelmente chamada de API) mesmo para uma entrada que nunca vai
  ser executada de verdade.
  `_persist_template_curl` (`engine.py:122-123`) só grava o arquivo `req_XXXX.curl.sh`
  quando `response.status_code != 0` — por isso uma entrada que já falha hoje (como
  `ws://`, que sempre retorna status 0 via `_build_error_response`) **já não gera** curl
  file. Esse efeito colateral precisa ser preservado quando o skip passar a ser
  intencional.

- **`ReplayRunner._existing_step_indexes`** (`replay/replay_runner.py:157-163`) — lista
  os steps disponíveis para replay varrendo `req_*.curl.sh` em `Workspace.curls`. Como
  nenhum step pulado (nem hoje, por acidente, nem depois desta mudança, por design) gera
  esse arquivo, `ReplayRunner` **nunca precisa saber sobre skip** — ele simplesmente não
  vê esses índices. Nenhuma mudança necessária em `ReplayRunner` por causa desta spec.

- **`ProjectConfig`/`ProjectConfigLoader`** (`models/config.py`,
  `config/project_config_loader.py`) — `ProjectConfig` é um `BaseModel` Pydantic
  carregado de `config.json` via `TypeAdapter(ProjectConfig).validate_json(...)`
  (`project_config_loader.py:26-27`); todo campo é opcional com default, e um erro de
  parsing já cai em `ProjectConfig()` (defaults) com aviso impresso — nenhuma mudança
  necessária nesse mecanismo de carregamento, só um novo campo no modelo.

- **`MitmProxyOrchestrator`** (`reproduction/mitm_proxy_orchestrator.py`) — usado tanto
  por `run --mode main` (`cli_handlers.py:56-70`, `_run_with_proxy`) quanto por
  `replay` (`cli_handlers.py:87-101`, `handle_replay`). `_start_process`
  (linhas 57-63) sobe o `mitmdump`:
  ```python
  def _start_process(self) -> subprocess.Popen:
      return subprocess.Popen(
          self._build_command(),
          env=self._build_env(),
          stdout=subprocess.PIPE,
          stderr=subprocess.STDOUT,
      )
  ```
  O único ponto que hoje lê `self._process.stdout` é `_build_early_exit_message`
  (linhas 109-114), e só no caminho de erro de `_wait_until_ready` (processo morreu
  antes de ficar pronto) — nunca durante operação normal.
  `_terminate` (linhas 157-167) já existe para encerrar o processo (`terminate()` →
  `wait()` com timeout → `kill()` se necessário) e é o lugar natural para fechar
  qualquer recurso adicional (ex.: arquivo de log) associado ao processo.

- **`Workspace`** (`fs_io/workspace.py`, `fs_io/workspace_dir.py`) — já tem um diretório
  dedicado a artefatos do `mitmdump`, `WorkspaceDir.MITM_CAPTURE` (`"mitm_capture"`),
  usado hoje só para o arquivo de captura (`Workspace.mitm_capture_file()`, linha 76-78,
  sempre `mitm_capture/capture.har`). É inicializado (`Workspace.init`, linha 20-26)
  antes de `MitmProxyOrchestrator.run`/`_start_process` rodar em ambos os fluxos que o
  usam (`Engine.__init__` chama `Workspace.init` antes de `orchestrator.run(engine.run)`
  em `_run_with_proxy`; `handle_replay` chama `Workspace.init` via
  `_prepare_replay_workspace` antes de construir o `orchestrator`) — não precisa de
  nenhuma mudança de ordem de inicialização para reaproveitar esse diretório.

- **`CurlHttpTransport._tls_flag`** (`reproduction/curl_http_transport.py:52-56`):
  ```python
  def _tls_flag(self) -> str:
      if self.ca_cert_path is None:
          return "--ssl-insecure"
      return f"--cacert {shlex.quote(str(self.ca_cert_path))}"
  ```
  Único ponto do projeto que decide a flag de TLS do `curl` de reprodução.

## 3. Decisões de arquitetura

### 3.1 Escopo do skip: protocolo é limitação técnica fixa; método é configurável

Duas categorias de "step que não deve ser executado", com naturezas diferentes:

- **Protocolo/scheme fora de `http`/`https`** (`ws`, `wss`, ou qualquer outro) — o
  transporte atual (`curl` com `--proxy`/`-o`/`-sS`, `curl_http_transport.py:43-50`) não
  tem como executar isso hoje, ponto. Não é uma preferência de configuração — é sempre
  pulado, hardcoded, sem chave em `config.json` para desligar esse comportamento.
- **Método HTTP** (hoje só `OPTIONS`, via `HARParser.SKIPPABLE_METHODS`, dead code
  — seção 2) — isso já é uma escolha de política (times diferentes podem querer pular
  `OPTIONS`, ou não, ou pular outros métodos também) e passa a ser configurável via
  `config.json`, com default idêntico ao comportamento hardcoded atual
  (`["OPTIONS"]`) — nenhuma mudança observável para quem não tocar no `config.json`.

Novo modelo em `models/config.py` (mesmo arquivo de `LLMSettings`/`ProjectConfig`, que já
agrupa modelos de configuração relacionados):
```python
class SkipRulesConfig(BaseModel):
    methods: List[str] = Field(default_factory=lambda: ["OPTIONS"])
```

`ProjectConfig` ganha:
```python
skip_rules: SkipRulesConfig = Field(default_factory=SkipRulesConfig)
```

Exemplo em `config.json` (todo o bloco é opcional — omitir `skip_rules` inteiro
preserva o comportamento de hoje):
```json
{
  "skip_rules": {
    "methods": ["OPTIONS", "HEAD"]
  }
}
```

### 3.2 Novo `StepSkipEvaluator` consolida a decisão de skip (substitui o dead code)

`HARParser.SKIPPABLE_METHODS` e o cálculo de `is_skippable` dentro de `parse_entry`
(seção 2) são removidos — a decisão de skip deixa de existir dentro do parser (que não
tem, e não deveria precisar ter, acesso à configuração do projeto) e passa a viver num
componente novo e dedicado, com acesso ao `SkipRulesConfig` carregado do
`config.json`.

Novo arquivo `reproduction/step_skip_evaluator.py`:
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

`HARParser.parse_entry` continua construindo `StepRequest` normalmente, só sem passar
`is_skippable` (o campo mantém o default `False` do modelo, `models/http.py:13`, até o
`Engine` decidir e sobrescrever — seção 3.3). O segundo call site de `parse_entry`
(`CurlHttpTransport._try_read_capture`, que só lê `.response` da captura do `mitmdump`)
não é afetado — nunca usou `is_skippable`.

### 3.3 `Engine._process_entry` pula análise e execução de rede para steps skippable

Estado atual (`engine.py:89-110`, ver seção 2).

Estado esperado — `Engine.__init__` ganha um `StepSkipEvaluator`:
```python
self.skip_evaluator: StepSkipEvaluator = StepSkipEvaluator(project_config.skip_rules)
```

`_process_entry` passa a decidir o skip logo depois do parse, antes de persistir (para
que `is_skippable` já esteja correto no `req_XXXX.json` persistido) e antes de
`analyze_step`/`resolve_all`/`execute_step`:
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

⚠️ `_persist_template_curl` nunca é chamado para um step pulado (o `return` acontece
antes) — preserva exatamente o efeito colateral que já existe hoje por acidente (seção
2: entradas que já falham não geram curl file), agora de forma intencional. Isso
também significa que `ReplayRunner` continua nunca vendo esses índices, sem nenhuma
mudança nele (seção 2).

⚠️ `tracker.analyze_step`, `token_resolver.resolve_all()` e `execute_step` (com seu
`retry_policy`/`handle_recovery`) **não rodam** para um step pulado — nenhuma chamada de
LLM, nenhum `curl` disparado, nenhuma tentativa de retry. É esse o ganho de custo
descrito na seção 1 (Falha 1).

`DryEngine` (`engines/dry_engine.py`) não sobrescreve `_process_entry`, só
`execute_step`/`_persist_response_step` — herda o novo comportamento de skip
automaticamente. Como `DryEngine.execute_step` nunca chama `curl` (retorna
`step.response` direto), o skip em modo `dry` só evita o custo de `analyze_step`
(potencial LLM) para essas entradas — não havia erro de protocolo para evitar nesse
modo, já que nenhum comando `curl` é montado nele.

### 3.4 `StepResponse` ganha marcação explícita de skip

Estado atual (`models/http.py:16-22`):
```python
class StepResponse(BaseModel):
    status_code: int
    headers: Dict[str, str] = Field(default_factory=dict)
    cookies: Dict[str, str] = Field(default_factory=dict)
    body: Optional[Union[str, bytes]] = None
    body_mime: Optional[str] = None
    redirect_url: Optional[str] = None
```

Estado esperado — dois novos campos, ambos com default que preserva compatibilidade
com qualquer `StepResponse` já persistido em runs anteriores (JSON sem essas chaves
continua carregando normalmente):
```python
skipped: bool = False
skip_reason: Optional[str] = None
```

`status_code` continua significando exclusivamente "resultado real de uma tentativa de
rede" (`0` = erro real, via `CurlHttpTransport._build_error_response`, ou o código HTTP
de fato recebido) — nunca mais overloaded para significar "pulado". Isso mantém
`Validator`/`ReplayResultComparator` funcionando sem nenhuma mudança neles: nenhum dos
dois lê `skipped`/`skip_reason`, então o comportamento de validação/comparação para
qualquer step **não pulado** é idêntico ao atual.

### 3.5 `mitmdump` para de escrever em um pipe nunca drenado

Estado atual (`mitm_proxy_orchestrator.py:57-63`, ver seção 1/2 — causa raiz da Falha
2). Alternativas descartadas:
- Só suprimir o log do `mitmdump` (`-q`/`--quiet`) — reduz o volume, mas não elimina a
  causa: o addon (`mitm_addon.py:106-107`) também usa `print(...)` para avisos de falha
  de escrita da captura, que vai para o mesmo stdout/pipe; qualquer saída não drenada
  ainda pode, em tese, encher o buffer de novo em uma run grande o suficiente.
- Thread dedicada drenando `self._process.stdout` continuamente — funciona, mas
  descarta o conteúdo (ou exige acumular em memória sem limite) e adiciona
  gerenciamento de thread/lock para um problema que um arquivo em disco resolve sem
  nenhuma concorrência.

Escolha: redirecionar `stdout`/`stderr` do `mitmdump` para um arquivo real em disco
(nunca enche, e fica disponível para inspeção depois). Novo método em `Workspace`
(`fs_io/workspace.py`, ao lado de `mitm_capture_file`):
```python
@classmethod
def mitm_log_file(cls) -> Path:
    cls._ensure_initialized()
    return cls.mitm_capture / "mitmdump.log"
```

`MitmProxyOrchestrator` passa a abrir esse arquivo antes de subir o processo e usá-lo
como `stdout` (com `stderr=subprocess.STDOUT` continuando a redirecionar para o mesmo
arquivo — funciona com qualquer file-like, não só com `PIPE`):
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

Novo atributo `self._log_file: Optional[IO[str]] = None` no `__init__`.

`_build_early_exit_message` (linhas 109-114) para de ler `self._process.stdout` (que
passa a ser sempre `None`, já que só é populado pelo Python quando `stdout=PIPE`) e lê o
arquivo de log do disco:
```python
def _build_early_exit_message(self) -> str:
    assert self._process is not None
    log_path: Path = Workspace.mitm_log_file()
    output: str = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    return f"mitmdump encerrou antes de ficar pronto (exit code {self._process.returncode}):\n{output}"
```

`_terminate` (linhas 157-167) fecha o arquivo depois de o processo confirmadamente ter
encerrado:
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

⚠️ O arquivo é aberto em modo `"w"` (trunca) a cada `_start_process` — cada execução de
`run`/`replay` começa com um `mitmdump.log` limpo, mesmo sem `--reset` (mesmo padrão
que `mitm_addon.py:105` já usa para `capture.har`, que também é sobrescrito a cada
resposta dentro da mesma run).

### 3.6 `--ssl-insecure` (flag de curl inválida) vira `--insecure`

Estado atual (`curl_http_transport.py:52-56`, seção 1/2).

Estado esperado:
```python
def _tls_flag(self) -> str:
    if self.ca_cert_path is None:
        return "--insecure"
    return f"--cacert {shlex.quote(str(self.ca_cert_path))}"
```

Mudança de uma linha, sem nenhum efeito colateral em outro lugar — único call site é
`_build_curl_command` (linha 44-50), já coberto pela seção 2.

Confirmado empiricamente neste ambiente: `curl --ssl-insecure ...` retorna
`curl: option --ssl-insecure: is unknown` (exit code 2); `curl -k`/`--insecure` retorna
exit code 0 para o mesmo destino.

### 3.7 Validação final ignora resposta de steps pulados

Estado atual (`engine.py:79-87`, `_reproduce`):
```python
def _reproduce(self) -> bool:
    entries: List[Dict[str, Any]] = HARParser.get_entries(self.har_path)
    first_entry: Step = HARParser.parse_entry(entries[0], 0)

    last_response: Optional[StepResponse] = None
    for index, entry in enumerate(entries):
        last_response = self._process_entry(index, entry, first_entry)

    return self._validate_final(last_response)
```
`last_response` é sempre a resposta do último índice do laço, pulado ou não. Se o
último entry do HAR for skippable, `_validate_final` (`engine.py:125-131`) receberia o
`StepResponse(status_code=0, skipped=True, ...)` de `_skip_entry` (seção 3.3), e
qualquer `StatusCodeCriterion` esperando um código diferente de `0` falharia mesmo que
o restante da reprodução tenha ido bem.

Estado esperado — `last_response` só é atualizado quando a resposta do step **não** foi
pulada, então a validação final sempre compara contra a última resposta real de rede
(ou original, em `dry`), varrendo pra trás qualquer sequência de steps pulados no final
do HAR:
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

`_validate_final` (`engine.py:125-131`) não muda — continua recebendo
`Optional[StepResponse]` e já trata `None` (`if not last_response or not
self.success_criteria: return True`, linha 126). Esse `None` agora também cobre o caso
de **todos** os entries do HAR serem pulados — mesmo comportamento que já existe hoje
para um HAR sem nenhum entry processado, sem necessidade de tratamento adicional.

`DryEngine` reaproveita esse `_reproduce` sem overrides (seção 3.3) — mesmo
comportamento nos dois engines.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `models/config.py` | novo `SkipRulesConfig` (`methods: List[str]`, default `["OPTIONS"]`); `ProjectConfig` ganha `skip_rules: SkipRulesConfig` |
| `models/http.py` | `StepResponse` ganha `skipped: bool = False` e `skip_reason: Optional[str] = None` |
| `reproduction/step_skip_evaluator.py` (novo arquivo) | `StepSkipEvaluator.skip_reason(request) -> Optional[str]` — scheme fora de `{http, https}` (hardcoded) ou método em `skip_rules.methods` (configurável) |
| `fs_io/har_parser.py` | remove `SKIPPABLE_METHODS` e o cálculo de `is_skippable` em `parse_entry` (dead code consolidado no `StepSkipEvaluator`) |
| `engines/engine.py` | `Engine.__init__` instancia `self.skip_evaluator`; `_process_entry` decide skip antes de `analyze_step`/`resolve_all`/`execute_step`; novo `_skip_entry` |
| `fs_io/workspace.py` | novo `Workspace.mitm_log_file()` (`mitm_capture/mitmdump.log`) |
| `reproduction/mitm_proxy_orchestrator.py` | `_start_process` usa um arquivo real (`Workspace.mitm_log_file()`) como `stdout`/`stderr` em vez de `subprocess.PIPE`; `_build_early_exit_message` lê o arquivo em vez de `self._process.stdout`; `_terminate` fecha o arquivo |
| `reproduction/curl_http_transport.py` | `_tls_flag` retorna `--insecure` em vez de `--ssl-insecure` |
| `README.md` | documenta o novo campo `skip_rules` na seção "Configuração (`config.json`)" |

## 5. Casos de borda e comportamento de erro

- **Último step do HAR é skippable** — `_reproduce` (seção 3.7) só atualiza
  `last_response` para respostas não puladas, então a validação final compara contra a
  última resposta real de rede (ou original, em `dry`) mesmo que o HAR termine com uma
  ou mais entradas puladas.
- **Todos os steps do HAR são skippable** — `last_response` permanece `None`;
  `_validate_final` já trata isso como sucesso (mesmo comportamento hoje para um HAR sem
  nenhum entry processado, `engine.py:126`).
- **`config.json` sem a chave `skip_rules`** — `Field(default_factory=SkipRulesConfig)`
  entrega `methods=["OPTIONS"]`, idêntico ao `SKIPPABLE_METHODS` hardcoded de hoje.
  Nenhuma mudança de comportamento para configs existentes.
- **`config.json` com `skip_rules.methods: []`** — nenhum método é pulado por conta
  própria; só o filtro de protocolo (sempre ativo) continua valendo.
- **Entrada com método customizado que também tem scheme inválido** (ex.: um hipotético
  `PROPFIND wss://...`) — `skip_reason` retorna o motivo de protocolo primeiro (checagem
  de scheme vem antes da checagem de método em `StepSkipEvaluator.skip_reason`); a
  mensagem de log reflete só o primeiro motivo encontrado, não os dois.
- **`response_reference_dir`/`replay` referenciando um índice que foi pulado no `run`
  original** — já não existe `req_XXXX.curl.sh` para esse índice (seção 3.3), então
  `ReplayRunner` nunca tenta agendá-lo; nenhuma mudança de comportamento necessária.
- **Modo `dry` (`DryEngine`)** — skip por protocolo continua sendo avaliado e reportado
  (é uma propriedade da própria entrada do HAR, independente do modo), mas como nenhum
  `curl` é montado em `dry`, o único efeito prático é pular `analyze_step` para essas
  entradas (seção 3.3).
- **`mitmdump.log` crescendo indefinidamente numa run muito longa** — arquivo em disco,
  sem limite de tamanho imposto por esta mudança (o problema que existia era o pipe de
  64KB, não espaço em disco). Fora de escopo — nenhuma run observada até hoje chega
  perto de um volume de log que seria um problema de espaço em disco real.

## 6. Referência

Implementação deve seguir `guia_de_estilo.md`: tipagem explícita em tudo (incluindo o
novo `StepSkipEvaluator`, `SkipRulesConfig`), guard clauses, zero comentários/docstrings,
um conceito por arquivo, e nenhuma mudança desta spec deve alterar o comportamento
observável de nenhum step que hoje já é executado com sucesso (`status_code != 0`).
