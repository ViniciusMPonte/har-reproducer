# Spec — Ferramenta de Replay a partir de Curls Salvos

> Fonte única de verdade para gerar o `implementation_plan.md` desta etapa. Assume que
> quem escreve o plano não participou da conversa que chegou a estas decisões — tudo
> que é necessário para entender o "porquê" e o "o quê" está aqui, sem depender de nada
> além do código-fonte atual do projeto (`har_reproducer/`) e do `guia_de_estilo.md`.

## 1. Objetivo

Construir uma ferramenta que reexecuta o fluxo **a partir dos curls já salvos em disco**
(`req_XXXX.curl.sh`, com placeholders `{{extractor:token_id}}`), em vez de rodar o
`Engine` inteiro contra o `.har` original. A ferramenta suporta quatro modos de
execução (seção 4). Não há reanálise de HAR nem chamada ao `TokenTracker`/LLM em nenhum
modo — os templates de curl e os extractors já existem prontos em disco, de uma
execução anterior de `har-reproducer run`.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

Resumo do que já existe e é relevante para o replay. Comportamento descrito aqui é o
comportamento **atual**, antes de qualquer mudança proposta neste spec.

- **`CurlGenerator.generate(request, tokens)`** — formata `StepRequest` em texto de
  curl. Quando `tokens` tem itens com `origin_step` não-nulo, prefixa o bloco com
  linhas de comentário (uma por token, via `_token_comments`):
  `# Token {token.token_id} comes from response of step {token.origin_step}`.
  **Importante:** essas linhas de comentário são só uma declaração de origem — a
  substituição de fato acontece no corpo do curl, em cada lugar exato onde o valor era
  usado (URL, header, cookie, body), sempre como `{{extractor:token_id}}`. Um mesmo
  `token_id` pode aparecer **mais de uma vez** no mesmo curl (ex.: uma vez no path da
  URL, outra vez num header). Exemplo real de `req_XXXX.curl.sh`:
  ```
  #!/bin/bash
  # Token b774bbe7479e9c91042c3f09a2aea7b7 comes from response of step 0
  curl -X GET \
       'http://127.0.0.1:8080/src/{{extractor:b774bbe7479e9c91042c3f09a2aea7b7}}s/bootstrap/bootstrap.css' \
       -H 'Accept: text/css,*/*;q=0.1' \
       ...
       -H 'Sec-Fetch-Dest: {{extractor:b774bbe7479e9c91042c3f09a2aea7b7}}' \
       ...
  ```
  Isso confirma que a extração de tokens referenciados (seção 3.2) precisa escanear o
  **texto inteiro** do curl via `SessionStore.TOKEN_PLACEHOLDER_PATTERN`, não só as
  linhas de comentário — os comentários servem só para descobrir o `origin_step`
  (seção 3.5), não para descobrir quais tokens estão em uso.

- **`SessionStore`** — guarda `state.tokens: Dict[str, str]` (token_id → valor atual).
  `render(texto)` resolve todo `{{extractor:token_id}}` via
  `TOKEN_PLACEHOLDER_PATTERN = re.compile(r"\{\{extractor:([a-f0-9]+)\}\})"`. Se o
  `token_id` não estiver em `state.tokens`, a ocorrência é deixada como está (não lança
  erro) — comportamento a preservar. `state.registry` existe mas **não é usado pelo
  replay** (ver 3.2).

- **`ExtractorRunner.run_existing(token_id)`** — executa
  `Workspace.extractor_file(token_id)` (`extract_{token_id}.py`, autocontido, já embute
  `step_index` e o código do extractor) via subprocess, retorna `Optional[str]`
  (`None` em qualquer falha). Não depende de `Extractor`/registry em memória.

- **`ExtractorTemplate.render_script(safe_token_id, code, step_index)`** — gera o
  conteúdo de `extract_{token_id}.py`. `_load_response()` embutido no script resolve o
  caminho da resposta de forma fixa: `Path(__file__).resolve().parent.parent / "real_responses" / "res_{step_index:04d}.json"`.

- **`CurlHttpTransport`** (código atual, já atualizado pelo usuário do projeto) —
  `send_request(self, curl_literal: str, step_index: int) -> StepResponse` **já recebe
  a string de curl pronta** (não recebe mais `StepRequest`, não usa mais
  `CurlGenerator` internamente para montá-la). Acrescenta flags de proxy
  (`--proxy`, `--cacert`/`--ssl-insecure`, `-o /dev/null`, `-sS`), roda via
  `subprocess.run(["bash", "-c", ...])`, lê a resposta capturada pelo mitmproxy
  (`Workspace.mitm_capture_file()`, retry de leitura: 5 tentativas, 0.1s). Em erro,
  `_build_error_response(step_index, error_message)` imprime
  `f"Network error while executing step {step_index} message: {error_message}"` —
  **não referencia mais `method`/`url`**. **Conclusão: `CurlHttpTransport` já é
  exatamente o que o replay precisa, sem nenhuma alteração** — basta chamar
  `send_request(curl_resolvido, step_index)` com o curl já resolvido pelo
  `SessionStore.render`.

- **`Engine`** (`har_reproducer/engines/engine.py`, código atual) —
  `RECOVERABLE_STATUS_CODES: ClassVar[Set[int]] = {400, 401}`,
  `MAX_STEP_ATTEMPTS: ClassVar[int] = 2`. Não tem mais `RequestBuilder`/
  `self.request_builder` — foi removido. Fluxo por step (`_process_entry`):
  1. `step = HARParser.parse_entry(entry, index)`.
  2. `_persist_request_step(index, step.request)` — persiste o `StepRequest`
     **original, cru, vindo do HAR** (antes de qualquer análise ou substituição de
     token — não é o request "final"/resolvido).
  3. `step.analysis = tracker.analyze_step(step, first_entry)` — gera
     `step.analysis.curl_template` (curl com placeholders, mesmo formato do
     `req_XXXX.curl.sh` persistido).
  4. `token_resolver.resolve_all()`.
  5. `response = self.execute_step(step)` — **retorna só `StepResponse`** (não é mais
     uma tupla `(StepRequest, StepResponse)`).
  6. `_persist_response_step(index, response)`.
  7. `print(f"Step {index} completed with status {response.status_code}")`.
  8. Se `response.status_code != 0`: persiste `step.analysis.curl_template` em
     `Workspace.curl_file(index)` — **ou seja, `curl_file(index)` só existe para steps
     que não tiveram erro de rede (`status_code != 0`) na execução original**;
     `response_file(index)` é sempre persistido, com ou sem erro.

  `execute_step(step) -> StepResponse`: laço de até `MAX_STEP_ATTEMPTS` tentativas,
  chama `_attempt_step(step)` (`curl_literal = session_store.render(step.analysis.curl_template)`;
  `http_transport.send_request(curl_literal, step.index)`); se não for a última
  tentativa e `handle_recovery(response)` retornar `True`, imprime
  `f"Deterministic recovery successful for step {step.index}. Retrying request..."` e
  tenta de novo. Se esgotar as tentativas, lança
  `RuntimeError(f"execute_step exhausted {self.MAX_STEP_ATTEMPTS} attempts for step {step.index}")`.
  `handle_recovery(response)`: se `response.status_code not in RECOVERABLE_STATUS_CODES`,
  retorna `False`; senão imprime
  `f"Detected {response.status_code}. Attempting deterministic recovery (token refresh)..."`,
  chama `token_resolver.resolve_all()`, retorna `True`.

- **`CliHandlers`** — `handle_run`/`handle_parse` sempre chamam
  `_reset_output_dir(output_dir)` (apaga e recria o diretório) antes de rodar.

- **`Workspace`** — `Workspace.init(output_dir)` idempotente. Métodos já existentes:
  `curl_file(index)`, `response_file(index)`, `request_file(index)`,
  `extractor_file(token_id)`, `mitm_capture_file()`.

- **`MitmProxyOrchestrator.run(callback: Callable[[], bool]) -> bool`** — genérico, sem
  necessidade de mudança.

- **Models relevantes** (`har_reproducer/models/`):
  - `StepRequest`: `url`, `method`, `headers`, `cookies`, `body`, `is_skippable`.
  - `StepResponse`: `status_code`, `headers`, `cookies`, `body`, `body_mime`,
    `redirect_url`.
  - `Step`: `index`, `request: StepRequest`, `response: Optional[StepResponse]`,
    `analysis: Optional[StepAnalysis]`.
  - `StepAnalysis`: `step_index`, `static_values`, `dynamic_tokens: List[DynamicToken]`,
    `curl_template: str`.
  - `Extractor`: `token_id`, `code`, `verified`, `agent_type`,
    `origin_step: Optional[int]`, `temp_file_path`.
  - `DynamicToken`: `token_id`, `path`, `current_value`, `destination_location`,
    `origin_location`, `origin_step: Optional[int]`, `status`.
  - `ProjectConfig`: `llm`, `success_criteria`, `proxy_port`, `ca_cert_path` (campos
    atuais). O replay usa `proxy_port`/`ca_cert_path` (mesmo uso que `Engine` já faz) e
    precisa de um campo novo, `response_reference_dir` (seção 3.4) — `success_criteria`
    e `llm` não são usados pelo replay (a validação final do replay não usa
    `success_criteria`, ver 3.9).
  - `ProjectConfigLoader.load(config_path) -> ProjectConfig`: sem config path ou arquivo
    inexistente, retorna `ProjectConfig()` (defaults). Parse via
    `TypeAdapter(ProjectConfig).validate_json(...)`, com fallback pra `ProjectConfig()`
    em qualquer exceção (print de erro + traceback, não propaga). `_apply_defaults`
    hoje só resolve `ca_cert_path` (via `Workspace.get_mitmproxy_ca_path()`, que não
    depende de `Workspace.init` já ter sido chamado) — **não precisa de alteração** para
    o campo novo (ver 3.4, a resolução do default de `response_reference_dir` fica fora
    dessa classe).

## 3. Decisões de arquitetura

### 3.1 Persistência do resultado do replay

- **Só a resposta é persistida** (`res_XXXX.json`), nunca a requisição
  (`req_XXXX.json`). O replay não constrói nenhum `StepRequest` em nenhum momento — só
  trabalha com texto de curl e `StepResponse`.
- **Diretório paralelo, identificado por timestamp** — preserva `real_responses/`,
  `real_requests/`, `curls/` originais intocados. Formato do `run_id`:
  `%Y%m%d_%H%M%S` (ex. `20260730_143210`), gerado uma vez no início do comando
  `replay`, usado para todos os steps executados naquela chamada.
- Caminhos resolvidos via `Workspace` (seção 3.6).

### 3.2 Resolução de tokens no replay — sem `TokenResolver`/registry

`TokenResolver.resolve_all()` (usado pelo `Engine`) itera
`session_store.state.registry.items()`, populado durante a análise de cada step
(`TokenTracker.analyze_step`). O replay não roda análise, então esse registry nunca é
populado — `TokenResolver` como está não pode ser reaproveitado.

**Novo componente: `ReplayTokenResolver`.** Resolve, para um texto de curl específico,
todos os tokens nele referenciados, decidindo individualmente (por token) de onde ler a
resposta de origem:

```python
class ReplayTokenResolver:
    def __init__(
        self,
        session_store: SessionStore,
        extractor_runner: ExtractorRunner,
        dependency_parser: CurlDependencyParser,
    ) -> None:
        self.session_store = session_store
        self.extractor_runner = extractor_runner
        self.dependency_parser = dependency_parser

    def resolve(
        self,
        curl_text: str,
        schedule: Set[int],
        replay_run_dir: Path,
        res_refer_dir: Path,
    ) -> None:
        dependencies: Dict[str, int] = self.dependency_parser.parse(curl_text)
        token_ids: Set[str] = set(SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text))
        for token_id in token_ids:
            self._resolve_one(token_id, dependencies, schedule, replay_run_dir, res_refer_dir)

    def _resolve_one(self, token_id, dependencies, schedule, replay_run_dir, res_refer_dir) -> None:
        origin_step: Optional[int] = dependencies.get(token_id)
        override_dir: Path = replay_run_dir if origin_step in schedule else res_refer_dir
        value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
        if value is None:
            print(f"Failed to resolve token '{token_id}' during replay: extractor returned no value.")
            return
        self.session_store.set_token(token_id, value)
```

`schedule` é o conjunto de índices de step que **esta execução de replay** vai
processar (seção 4) — é o mesmo conceito em todos os modos, só muda como é calculado.
`replay_run_dir` e `res_refer_dir` vêm de `ReplayRunner` (seções 3.3/3.4).

Note que `override_dir` **nunca é `None`** — o replay sempre passa um diretório
explícito para `ExtractorRunner.run_existing` (seção 3.3), seja o do run atual, seja o
de referência. O fallback interno do script gerado (ler direto de `real_responses/`
quando a env var não está setada) só é exercitado hoje pelo `Engine` — o replay nunca
depende desse fallback.

### 3.3 Override de resposta para extractors — mecanismo (env var)

Quando um step que é origem de um token também está no `schedule` desta execução (ou
seja, foi/será reexecutado via HTTP nesta mesma run de replay), a resposta nova dele é
persistida em `replays/<run_id>/`, não em `real_responses/`. O script gerado por
`ExtractorTemplate.render_script` precisa poder ler dali.

**Mudança em `ExtractorTemplate.render_script`:**

```python
import os
...
def _load_response() -> Dict:
    override_dir = os.environ.get("HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR")
    if override_dir:
        response_file: Path = Path(override_dir) / "res_{step_index:04d}.json"
    else:
        response_file: Path = Path(__file__).resolve().parent.parent / "real_responses" / "res_{step_index:04d}.json"
    return json.loads(response_file.read_text(encoding="utf-8"))
```

**Mudança em `ExtractorRunner`:** `run_existing` e `_execute_extractor_script` passam a
aceitar `response_override_dir: Optional[Path] = None`. Quando presente, é setado como
env var `HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR` no subprocess
(`env = {**os.environ, "HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR": str(response_override_dir)}`).

**Garantia de não regressão:** o `Engine` nunca passa `response_override_dir` (fica
`None`), então o script cai no `else` — comportamento idêntico ao de hoje.

### 3.4 Diretório de referência para responses fora do schedule — campo do config

Não é mais uma flag de CLI — vem do arquivo de configuração (`--config`, já usado por
`run`/`replay`), carregado via `ProjectConfigLoader.load` (mesma classe existente, sem
alterações nela — só no model). **Novo campo em `ProjectConfig`**
(`har_reproducer/models/config.py`):

```python
class ProjectConfig(BaseModel):
    llm: Optional[LLMSettings] = None
    success_criteria: List[SuccessCriterion] = Field(default_factory=list)
    proxy_port: Optional[int] = None
    ca_cert_path: Optional[Path] = None
    response_reference_dir: Optional[Path] = None
```

Usado como `res_refer_dir` em `ReplayTokenResolver.resolve` (3.2) — a fonte de resposta
para qualquer token cujo `origin_step` **não** esteja no `schedule` desta execução.

**Resolução do default não fica em `ProjectConfigLoader._apply_defaults`** (diferente de
`ca_cert_path`, que é resolvido lá) — fica em `ReplayRunner`/`CliHandlers.handle_replay`,
no momento de montar as dependências do replay:
`res_refer_dir = project_config.response_reference_dir or Workspace.real_responses`.
Motivo de não colocar em `_apply_defaults`: esse método é compartilhado com `run`/`parse`,
que não têm noção de `Workspace.real_responses` nesse ponto do fluxo (hoje
`ProjectConfigLoader.load` é chamado **antes** de `Workspace.init` em `_run_with_proxy`)
— manter a resolução local ao replay evita depender dessa ordem.

Se `response_reference_dir` estiver setado no config e o diretório não existir: erro,
antes de subir o proxy.

### 3.5 Descoberta de dependências entre steps

**Novo componente: `CurlDependencyParser`.** Método
`parse(curl_text: str) -> Dict[str, int]`, extraindo o mapa `token_id → origin_step` a
partir das linhas de comentário (seção 2):

```python
class CurlDependencyParser:
    DEPENDENCY_PATTERN: ClassVar[Pattern[str]] = re.compile(
        r"^# Token (?P<token_id>[a-f0-9]+) comes from response of step (?P<origin_step>\d+)$",
        re.MULTILINE,
    )

    def parse(self, curl_text: str) -> Dict[str, int]:
        return {
            match.group("token_id"): int(match.group("origin_step"))
            for match in self.DEPENDENCY_PATTERN.finditer(curl_text)
        }
```

Se um `token_id` referenciado no curl (via `TOKEN_PLACEHOLDER_PATTERN`) não tiver
comentário correspondente, ele simplesmente não aparece no dicionário — tratado como
"origem desconhecida" em `ReplayTokenResolver._resolve_one` (`dependencies.get(token_id)`
retorna `None`, `None in schedule` é sempre `False`, cai no `res_refer_dir`).

### 3.6 `Workspace` — novo diretório para replay

Novo membro em `WorkspaceDir` (ex. `REPLAYS = "replays"`), criado em `Workspace.init()`
como os demais.

Novos métodos:

- `replay_run_dir(run_id: str) -> Path` — retorna `<output_dir>/replays/<run_id>`,
  cria o diretório (`mkdir(parents=True, exist_ok=True)`) na primeira chamada — diferente
  dos métodos de path fixo existentes, que assumem o diretório-pai já criado no `init()`;
  aqui o subdiretório é dinâmico por `run_id`.
- `replay_response_file(run_id: str, index: int) -> Path` — retorna
  `replay_run_dir(run_id) / f"res_{index:04d}.json"`.

### 3.7 Retry — `StepRetryPolicy` extraída

Como `Engine.execute_step` agora retorna só `StepResponse` (não mais uma tupla), a
extração fica simples, sem precisar de `Any` ou `TypeVar`:

```python
class StepRetryPolicy:
    MAX_STEP_ATTEMPTS: ClassVar[int] = 2
    RECOVERABLE_STATUS_CODES: ClassVar[Set[int]] = {400, 401}

    def execute(
        self,
        step_index: int,
        attempt_fn: Callable[[], StepResponse],
        recovery_fn: Callable[[StepResponse], bool],
    ) -> StepResponse:
        for attempt in range(self.MAX_STEP_ATTEMPTS):
            response: StepResponse = attempt_fn()
            is_last_attempt: bool = attempt == self.MAX_STEP_ATTEMPTS - 1
            if not is_last_attempt and recovery_fn(response):
                print(f"Recovery successful for step {step_index}. Retrying request...")
                continue
            return response
        raise RuntimeError(f"execute exhausted {self.MAX_STEP_ATTEMPTS} attempts for step {step_index}")
```

`recovery_fn` continua encapsulando, como hoje, tanto a checagem de
`response.status_code in RECOVERABLE_STATUS_CODES` quanto a ação de recuperação — a
interface de `execute` não faz essa checagem sozinha.

**`Engine` precisa ser alterado** para compor essa classe (pedido explícito — "extrair a
lógica para um arquivo separado" implica que o `Engine` deixa de ter a lógica inline):

- `Engine.__init__` ganha `self.retry_policy: StepRetryPolicy = StepRetryPolicy()`.
- `Engine.execute_step(step)` passa a ser
  `return self.retry_policy.execute(step.index, lambda: self._attempt_step(step), self.handle_recovery)`.
- `Engine.handle_recovery` continua igual, só troca `self.RECOVERABLE_STATUS_CODES` por
  `self.retry_policy.RECOVERABLE_STATUS_CODES`.
- `Engine.RECOVERABLE_STATUS_CODES`/`Engine.MAX_STEP_ATTEMPTS` (os `ClassVar` na própria
  classe) deixam de ser necessários e devem ser removidos — a fonte de verdade passa a
  ser só `StepRetryPolicy`. **Sinalizar essa remoção no plano** (não é código morto por
  acaso, é consequência direta da extração, mas ainda assim é uma remoção de atributos
  públicos de classe que vale confirmar antes de aplicar).

**Localização:** `har_reproducer/reproduction/step_retry_policy.py` — não no pacote
`replay/` novo (seção 5), porque é compartilhada com o `Engine`, que não deveria
depender conceitualmente de um pacote chamado "replay".

`ReplayRunner` usa a mesma classe, passando seu próprio `attempt_fn`/`recovery_fn` por
step (seção 4).

### 3.8 Flag de reset condicional para `run`/`parse`

Novo requisito: `run` e `parse` ganham uma flag para controlar se o diretório de saída
é apagado e recriado antes de rodar (hoje isso sempre acontece, sem opção).

- `run_parser.add_argument("--no-reset", dest="reset_output_dir", action="store_false", default=True, help="Não apagar/recriar o diretório de saída antes de rodar (default: apaga e recria)")`
- Mesma flag em `parse_parser`.
- `CliHandlers.handle_run`/`handle_parse` só chamam `_reset_output_dir(output_dir)` se
  `args.reset_output_dir` for `True`. Default mantém o comportamento atual (reset
  sempre) — a mudança é estritamente aditiva.
- O comando `replay` **nunca** expõe essa flag e **nunca** chama
  `_reset_output_dir` — depende do workspace de uma execução anterior existir intacto.

### 3.9 Validação final do replay — comparação de status code

Substitui a ideia original de reaproveitar `Validator`/`success_criteria` do `Engine`.
Ao final da execução (qualquer modo), o replay compara o **último `StepResponse` que
produziu** (o último step processado, na ordem de iteração do modo — seção 4) com o
`res_XXXX.json` **original** daquele mesmo índice, verificando só o `status_code`. A
leitura do original é uma regex simples sobre o texto bruto do arquivo, sem parsear o
JSON inteiro — decisão explícita para não complicar agora; comparação mais completa
(corpo, headers) fica para depois.

**Importante:** essa comparação sempre lê de `Workspace.response_file(index)` — que já
é hardcoded para `real_responses/` — **independente** do `response_reference_dir`
configurado (3.4). Nunca usa `res_refer_dir`. Motivo: `response_reference_dir` existe
para servir de referência a respostas de steps *anteriores* durante a resolução de
token; não há garantia de que ele contenha o response do **último** step do schedule
(o que está sendo validado aqui), então usar sempre o `real_responses/` original é a
única fonte confiável para essa comparação.

**Novo componente: `ReplayResultComparator`.**

```python
class ReplayResultComparator:
    STATUS_CODE_PATTERN: ClassVar[Pattern[str]] = re.compile(r'"status_code"\s*:\s*(\d+)')

    def matches_original(self, index: int, response: StepResponse) -> bool:
        original_text: str = Workspace.response_file(index).read_text(encoding="utf-8")
        match: Optional[Match[str]] = self.STATUS_CODE_PATTERN.search(original_text)
        if match is None:
            print(f"Could not read original status code for step {index} to compare.")
            return False
        return int(match.group(1)) == response.status_code
```

`ReplayRunner` chama isso ao final, com o índice/response do último step processado, e
imprime um resultado no mesmo espírito de `Engine._validate_final`
(`f"\nReplay Validation Result: {'✓ SUCCESS' if matches else '✗ MISMATCH'} (step {index} status code vs. original)"`),
retornando o booleano — é o valor usado pelo `callback` passado a
`MitmProxyOrchestrator.run` e por `CliHandlers._print_result`.

### 3.10 CLI — subcomando `replay`

Novo subcomando (não uma flag dentro de `run`). `Workspace.init(output_dir)` é chamado
(idempotente), mas **`_reset_output_dir` nunca é chamado**.

Argumentos:

- `--output` (obrigatório) — diretório de um workspace já existente.
- `--mode` (obrigatório, choices: `all`, `slice`, `smart`, `list`).
- `--from` / `--to` (opcionais, `int`) — só válidos com `--mode slice` ou `--mode smart`.
- `--steps-file` (opcional, `Path`) — só válido com `--mode list` (obrigatório nesse
  modo).
- `--config` (opcional) — mesmo formato do `run`; é de onde vem
  `response_reference_dir` agora (seção 3.4), não existe flag própria pra isso.

Validações em `CliHandlers.handle_replay` (antes de subir o proxy):

- `--mode all`: erro se `--from`, `--to` ou `--steps-file` forem passados.
- `--mode slice` / `--mode smart`: erro se `--steps-file` for passado; erro se
  `--from`/`--to` forem ambos passados e `from_index > to_index`.
- `--mode list`: erro se `--steps-file` **não** for passado; erro se `--from`/`--to`
  forem passados.
- Se `response_reference_dir` estiver setado no config carregado, precisa existir como
  diretório — senão, erro (ver 3.4).
- `--output` precisa existir e ter ao menos um `req_XXXX.curl.sh` em
  `Workspace.curls` — senão, erro.

**Ordem de inicialização específica de `handle_replay`:** `Workspace.init(output_dir)`
precisa ser chamado **antes** de `ProjectConfigLoader.load(config_path)`, porque a
resolução do default de `response_reference_dir` (3.4) depende de
`Workspace.real_responses` já estar setado. Isso é diferente da ordem usada hoje em
`_run_with_proxy` (config carregado antes do `Workspace.init`, que só acontece dentro do
`Engine.__init__`) — `handle_replay` não pode seguir esse mesmo padrão de chamada.

"Replay de um step isolado" é só `--mode slice --from N --to N` — não precisa de flag
própria.

## 4. Modos de execução

Todos os modos calculam um `schedule: Set[int]` e uma ordem de iteração
`ordered_indexes: List[int]` (seções 4.1–4.4), e então rodam, **para cada índice `S` em
`ordered_indexes`, na ordem**, a mesma sequência de trabalho:

1. `curl_text = Workspace.curl_file(S).read_text(encoding="utf-8")`.
2. `attempt_fn`: `replay_token_resolver.resolve(curl_text, schedule, replay_run_dir, res_refer_dir)`
   (mutação em `session_store`), depois `curl_resolvido = session_store.render(curl_text)`,
   depois `http_transport.send_request(curl_resolvido, S)` — retorna `StepResponse`.
3. `recovery_fn`: se `response.status_code not in StepRetryPolicy.RECOVERABLE_STATUS_CODES`,
   retorna `False`; senão imprime aviso de recuperação (mesmo texto de
   `Engine.handle_recovery`, seção 2) e retorna `True` — a nova tentativa em `attempt_fn`
   já vai re-rodar a resolução de tokens do zero (passo 2).
4. `response = step_retry_policy.execute(S, attempt_fn, recovery_fn)`.
5. `Workspace.replay_response_file(run_id, S).write_text(response.model_dump_json(indent=2), encoding="utf-8")`.
6. `print(f"Step {S} completed with status {response.status_code}")`.
7. Atualiza `last_index, last_response = S, response`.

Steps que não entram em `ordered_indexes` (relevante nos modos `smart` e `list`) **não
são tocados de nenhuma forma** — nada é lido, executado, persistido ou impresso para
eles.

Depois de processar todo `ordered_indexes`, chama
`ReplayResultComparator.matches_original(last_index, last_response)` (seção 3.9) e
retorna o resultado.

### 4.1 Modo `all`

`ordered_indexes` = todos os índices com `Workspace.curl_file(index)` existente, em
ordem ascendente (scan do diretório `Workspace.curls`, extraindo o índice do nome
`req_{index:04d}.curl.sh`). `schedule = set(ordered_indexes)`.

### 4.2 Modo `slice`

- `effective_from = from_index if from_index is not None else 0`
- `effective_to = to_index if to_index is not None else <maior índice existente>`
- `ordered_indexes = list(range(effective_from, effective_to + 1))`,
  `schedule = set(ordered_indexes)`.
- Se algum índice do range não tiver `curl_file` correspondente: erro, propaga (workspace
  incompleto para o range pedido).

### 4.3 Modo `smart`

- `floor = from_index if from_index is not None else 0`
- `target = to_index if to_index is not None else <maior índice existente>`
- O alvo real é só `target` — `floor` é o limite inferior da busca de dependência.
- Cálculo do `schedule` (fecho transitivo, BFS/DFS — ordem de visita não importa):
  1. `schedule = {target}`, `pending = {target}`.
  2. Enquanto `pending` não vazio: remove um `S`; lê `Workspace.curl_file(S)`; usa
     `CurlDependencyParser.parse` para achar `(token_id, origin_step)`; para cada
     `origin_step >= floor` ainda não em `schedule`, adiciona a `schedule` e a `pending`.
  3. `ordered_indexes = sorted(schedule)` — ordem ascendente é sempre correta porque
     `origin_step` é sempre menor que o índice que o consome (invariante do sistema de
     tracking existente, não uma decisão nova deste spec).
- Steps entre `floor` e `target` fora do `schedule` computado: **nada é feito, nada é
  impresso**.
- Se `Workspace.curl_file` de algum step do `schedule` computado não existir: erro,
  propaga (mesma regra do `slice`).

### 4.4 Modo `list` (novo)

- `--steps-file` aponta para um `.txt` com uma lista de índices inteiros, **um por
  linha**; linhas em branco são ignoradas. Parsing:
  `[int(line.strip()) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]`.
- `ordered_indexes` = exatamente essa lista, **na ordem em que aparece no arquivo** (não
  ordenada, duplicatas permitidas — se um índice aparecer mais de uma vez, é executado
  mais de uma vez, e `replay_response_file(run_id, index)` fica só com o resultado da
  última execução daquele índice, já que é um único arquivo por índice por run).
  `schedule = set(ordered_indexes)`.
- Se o arquivo estiver vazio (nenhum índice válido): erro de validação na CLI, antes de
  subir o proxy.
- Se algum índice da lista não tiver `curl_file` correspondente: erro, propaga.
- Não há cálculo de dependência — é execução literal da lista dada, na ordem dada. A
  regra de override de resposta (3.2/3.3) usa esse `schedule` normalmente (um índice
  fora da lista sempre cai no `res_refer_dir`, mesmo que seja dependência de algum
  índice presente).

## 5. Novos componentes e alterações — resumo

| Componente | Tipo | Pacote | Responsabilidade |
|---|---|---|---|
| `ReplayRunner` | novo | `har_reproducer/replay/` | Orquestra os 4 modos, calcula `schedule`/`ordered_indexes`, roda a sequência de trabalho da seção 4 por step, chama o comparador no final. |
| `ReplayTokenResolver` | novo | `har_reproducer/replay/` | Resolve tokens referenciados num curl sob demanda, decidindo override por token (seção 3.2). |
| `CurlDependencyParser` | novo | `har_reproducer/replay/` | Extrai `token_id → origin_step` dos comentários de um curl template (seção 3.5). |
| `ReplayResultComparator` | novo | `har_reproducer/replay/` | Compara status code do último response do replay com o original (seção 3.9). |
| `StepRetryPolicy` | novo | `har_reproducer/reproduction/` | Loop de tentativas + recuperação, extraído de `Engine` — compartilhado entre `Engine` e `ReplayRunner` (seção 3.7). |
| `Engine` | alteração | (existente) | Passa a compor `StepRetryPolicy`; remove `RECOVERABLE_STATUS_CODES`/`MAX_STEP_ATTEMPTS` próprios. |
| `ExtractorTemplate` | alteração | (existente) | `render_script` suporta override de caminho de resposta via env var (seção 3.3). |
| `ExtractorRunner` | alteração | (existente) | `run_existing`/`_execute_extractor_script` aceitam `response_override_dir` opcional (seção 3.3). |
| `Workspace` | alteração | (existente) | Novo `WorkspaceDir.REPLAYS`; novos métodos `replay_run_dir`/`replay_response_file` (seção 3.6). |
| `cli_parser.py` | alteração | (existente) | Novo subparser `replay`; flag `--no-reset` em `run`/`parse` (seções 3.8/3.10). |
| `cli_handlers.py` | alteração | (existente) | Novo `handle_replay`; reset condicional em `handle_run`/`handle_parse` (seções 3.8/3.10). |
| `CurlHttpTransport` | **sem alteração** | (existente) | Já aceita curl resolvido via `send_request(curl_literal, step_index)` — reaproveitado como está. |
| `MitmProxyOrchestrator` | **sem alteração** | (existente) | `run(callback)` já é genérico o bastante. |

## 6. Estrutura de diretórios de saída do replay

```
<output_dir>/
  curls/                       (já existe, só lido)
  real_requests/                (já existe, só lido)
  real_responses/                (já existe, só lido — ou outro dir via response_reference_dir do config)
  extractors/                    (já existe, só lido)
  replays/                       (novo, criado no Workspace.init)
    20260730_143210/             (um por execução de `replay`)
      res_0003.json
      res_0005.json
```

## 7. Casos de borda e comportamento de erro

- **Workspace inexistente ou incompleto** (`--output` sem nenhum `curl_file`): erro
  antes de subir o `mitmdump`.
- **`response_reference_dir` do config apontando para diretório inexistente**: erro,
  antes de subir o `mitmdump` (ver 3.4/3.10).
- **Índice do schedule sem `curl_file` correspondente** (`slice`/`smart`/`list`): erro,
  propaga — não pula silenciosamente.
- **`--steps-file` vazio ou ausente com `--mode list`**: erro de validação na CLI.
- **Extractor falha ao resolver um token** (`ExtractorRunner.run_existing` retorna
  `None`): não propaga exceção; placeholder correspondente fica sem substituição no
  curl final (`SessionStore.render` já suporta isso); imprime aviso.
- **Todas as tentativas de um step se esgotam** (`StepRetryPolicy`): `RuntimeError`
  propaga e derruba o comando.
- **Combinações inválidas de flags por modo** (seção 3.10): erro de validação na CLI,
  nada é executado.

## 8. Suposições e pontos a confirmar antes do plano

1. **Texto da exceção em `StepRetryPolicy.execute`**: mudou de
   `"execute_step exhausted..."` (texto atual do `Engine`) para
   `"execute exhausted..."` (seção 3.7) — mudança de string observável, mínima mas
   real, por causa do método não se chamar mais `execute_step` nesse novo local.
2. **Texto do print de recuperação bem-sucedida**: movido para dentro de
   `StepRetryPolicy.execute` com wording genérico
   (`f"Recovery successful for step {step_index}. Retrying request..."`), diferente do
   texto atual do `Engine`
   (`f"Deterministic recovery successful for step {step.index}. Retrying request..."`).
3. **Formato do arquivo de `--steps-file`** (seção 4.4): assumi "um inteiro por linha,
   linhas em branco ignoradas" — não foi especificado o formato exato.
4. **Remoção de `Engine.RECOVERABLE_STATUS_CODES`/`Engine.MAX_STEP_ATTEMPTS`** como
   `ClassVar` próprios da classe, movendo a fonte de verdade para `StepRetryPolicy`
   (seção 3.7) — é consequência direta do pedido de extração, mas ainda assim uma
   remoção de atributos públicos existentes, vale confirmar.

## 9. Referência

Implementação deve seguir `guia_de_estilo.md`: tipagem explícita em tudo, `ClassVar`
para constantes de classe, um conceito por arquivo, guard clauses, zero
comentários/docstrings, `except Exception` amplo só em bordas de I/O/subprocess (sempre
com print de aviso + degradação, nunca crash silencioso), e o processo de "propor
decomposição → aprovação → gerar arquivo → compile-check" para cada task do plano.
