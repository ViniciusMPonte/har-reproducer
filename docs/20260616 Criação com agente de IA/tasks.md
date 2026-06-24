# HAR Flow Reproducer — Tasks de Implementação

> Projeto gerenciado com **uv**. Todas as tarefas assumem `.venv` local ao projeto.
> Comandos uv relevantes: `uv init`, `uv add <dep>`, `uv run pytest`, `uv run har-reproducer`.

---

## Fase 0 — Setup do projeto

### 0.1 Inicializar estrutura com uv
- [ ] Rodar `uv init har-reproducer` (cria `pyproject.toml`, `.python-version`, `hello.py`)
- [ ] Remover `hello.py` gerado pelo init
- [ ] Criar `.venv` local: `uv venv .venv`
- [ ] Adicionar `.venv/` ao `.gitignore`

### 0.2 Configurar dependências
- [ ] Adicionar dependências principais: `uv add httpx pydantic beautifulsoup4 jsonpath-ng`
- [ ] Adicionar dependências de dev: `uv add --dev pytest pytest-httpx`
- [ ] Verificar que `pyproject.toml` contém as dependências corretamente

### 0.3 Estrutura de diretórios
- [ ] Criar pacote principal: `mkdir -p har_reproducer/agents`
- [ ] Criar `har_reproducer/__init__.py` vazio
- [ ] Criar `har_reproducer/agents/__init__.py` vazio
- [ ] Criar estrutura de testes: `mkdir -p tests/fixtures`
- [ ] Criar `tests/__init__.py` e `tests/conftest.py` vazios
- [ ] Criar `pytest.ini` com `testpaths = tests` e `pythonpath = .`

### 0.4 Configurar entry point da CLI
- [ ] Adicionar `[project.scripts]` no `pyproject.toml`: `har-reproducer = "har_reproducer.cli:main"`
- [ ] Criar `har_reproducer/cli.py` com função `main()` que imprime `"har-reproducer OK"` (stub)
- [ ] Verificar que `uv run har-reproducer` executa sem erro

---

## Fase 1 — HAR Parser

### 1.1 Modelos de dados do parser
- [ ] Criar `har_reproducer/models.py` com modelo Pydantic `HarEntry` (campos: `method`, `url`, `headers`, `cookies`, `body`, `body_mime`, `status_code`, `response_headers`, `response_cookies`, `response_body`, `response_mime`, `redirect_url`, `skip`)
- [ ] Adicionar modelo `ParsedStep` com campos `index`, `request` e `response` (ambos dicts serializáveis)

### 1.2 Função de leitura do HAR
- [ ] Criar `har_reproducer/parser.py`
- [ ] Implementar `load_har(har_path: str) -> list[dict]` — lê o arquivo `.har` e retorna a lista `entries` crua
- [ ] Implementar `decode_body(entry: dict) -> str | None` — decodifica bodies em base64 quando `encoding == "base64"`

### 1.3 Lógica de parsing por entry
- [ ] Implementar `parse_entry(entry: dict, index: int) -> ParsedStep` — extrai request e response de uma entry
- [ ] Marcar `skip: True` em entries com método `OPTIONS`
- [ ] Extrair headers, cookies, query params, body e mime type do request
- [ ] Extrair status, headers, cookies, body, mime type e redirect url da response

### 1.4 Geração de arquivos de steps
- [ ] Implementar `split_har(har_path: str, output_dir: str) -> int` — orquestra o parse de todas as entries
- [ ] Salvar `steps/req_{N:04d}.json` para cada entry (apenas dados do request)
- [ ] Salvar `steps/res_{N:04d}.json` para cada entry (apenas dados da response)
- [ ] Garantir índices com padding de 4 dígitos (sort lexicográfico correto)
- [ ] Retornar número total de steps gerados

### 1.5 Fixtures e testes do parser
- [ ] Criar `tests/fixtures/simple_flow.har` com 3 entries (GET, POST com JSON, GET com redirect)
- [ ] Criar `tests/fixtures/complex_flow.har` com 8+ entries variadas (inclui OPTIONS, bodies base64, cookies)
- [ ] Criar `tests/parser/test_load_har.py` — testa leitura correta do JSON, número de entries
- [ ] Criar `tests/parser/test_decode_body.py` — testa decodificação base64, body texto puro, body vazio
- [ ] Criar `tests/parser/test_parse_entry.py` — testa cada campo extraído para GET e POST
- [ ] Criar `tests/parser/test_options_skip.py` — testa que entries OPTIONS têm `skip: True`
- [ ] Criar `tests/parser/test_split_har.py` — testa arquivos gerados em disco para `simple_flow.har`
- [ ] Criar `tests/parser/test_complex_flow.py` — testa que `complex_flow.har` gera steps corretos para todas as entries

### 1.6 Comando CLI `parse`
- [ ] Implementar subcomando `har-reproducer parse --har <path> --output <dir>` no `cli.py`
- [ ] Integrar com `split_har()`
- [ ] Imprimir número de steps gerados e caminho de saída
- [ ] Testar manualmente com `uv run har-reproducer parse --har tests/fixtures/simple_flow.har --output /tmp/steps`

---

## Fase 2 — Token Tracker, Request Engine, Session Store e Success Validator

> As tarefas desta fase seguem a ordem de dependência: modelos → session store → tracker (análise) → tracker (extratores) → engine → validator.

### 2.1 Modelos de dados do Token Tracker
- [ ] Adicionar ao `models.py`: dataclass `Candidate` (campos: `step_index`, `location`, `name`, `value`)
- [ ] Adicionar `TokenOrigin` (campos: `step_index`, `location`, `header_name`, `cookie_name`, `json_path`, `selector`, `attribute`, `regex`, `real_matched_value`, `grep_line` — todos opcionais exceto `step_index` e `location`)
- [ ] Adicionar `Extractor` (campos: `token_id`, `origin`, `extractor_type`, `code`, `test_code`, `expected_value`, `verified`)
- [ ] Adicionar `CurlTemplate` (campos: `step_index`, `method`, `url`, `static_headers`, `dynamic_headers`, `static_cookies`, `dynamic_cookies`, `static_body_fields`, `dynamic_body_fields`, `body_mime`)
- [ ] Adicionar `StepAnalysis` (campos: `step_index`, `curl_template`, `extractors`, `unresolved`, `static_values`)
- [ ] Adicionar `GrepMatch` (campos: `filename`, `step_index`, `line_number`, `line_content`)
- [ ] Converter todos os modelos para Pydantic `BaseModel` (validação automática)
- [ ] Escrever teste `tests/test_models.py` — instancia cada modelo com dados mínimos válidos

### 2.2 Session Store
- [ ] Criar `har_reproducer/session.py`
- [ ] Implementar `SessionStore` como classe com `values: dict[str, str]` interno
- [ ] Implementar `store.set(token_id: str, value: str) -> None`
- [ ] Implementar `store.get(token_id: str) -> str | None`
- [ ] Implementar `store.render(template: str) -> str` — substitui `{{token_id}}` por valores reais
- [ ] Implementar `store.render_dict(d: dict[str, str]) -> dict[str, str]` — renderiza todos os valores de um dict
- [ ] Implementar `store.all() -> dict[str, str]` — retorna cópia do estado atual
- [ ] Criar `tests/test_session.py` com testes unitários para cada método (incluindo `render` com múltiplos placeholders e placeholder sem valor no store)

### 2.3 Busca com grep (utilitário do tracker)
- [ ] Criar `har_reproducer/grep_utils.py`
- [ ] Implementar `grep_in_real_responses(value: str, real_responses_dir: str, max_step: int) -> list[GrepMatch]`
- [ ] Usar `subprocess` com `grep -Frn --include=res_*.json -m 1`
- [ ] Implementar `parse_grep_output(stdout: str, max_step: int) -> list[GrepMatch]` — parseia a saída linha a linha
- [ ] Implementar `grep_variants(value: str, ...) -> list[GrepMatch]` — tenta também com o valor URL-decoded e base64-decoded
- [ ] Criar `tests/test_grep_utils.py` — cria arquivos temporários em disco e testa as funções

### 2.4 Comparação baseline (etapas 1–3 do pipeline)
- [ ] Criar `har_reproducer/tracker.py`
- [ ] Implementar `load_step(steps_dir: str, index: int) -> dict` — lê `req_{N:04d}.json`
- [ ] Implementar `extract_all_values(step: dict) -> dict[str, str]` — extrai headers, cookies, body fields, query params em um dict plano `name → value`
- [ ] Implementar `ALWAYS_DYNAMIC_PATTERNS: list[str]` — lista de padrões regex (`.*token.*`, `.*csrf.*`, `.*jwt.*`, `.*auth.*`, `.*session.*`, etc.)
- [ ] Implementar `is_always_dynamic(name: str) -> bool` — verifica se o nome do campo bate com algum padrão
- [ ] Implementar `compare_with_baseline(step_values: dict, baseline_values: dict) -> tuple[list[Candidate], list[Candidate]]` — retorna `(candidates, statics)`
- [ ] Criar `tests/tracker/test_compare_baseline.py` — testa classificação de estáticos vs candidatos, e que nomes conhecidos nunca são estáticos

### 2.5 Identificação de origem (etapas 4–5 do pipeline)
- [ ] Implementar `find_origin_in_headers(response: dict, value: str) -> TokenOrigin | None` — verifica `Set-Cookie` e outros headers
- [ ] Implementar `find_origin_in_json_body(response: dict, value: str) -> TokenOrigin | None` — usa `jsonpath-ng` para encontrar o caminho
- [ ] Implementar `find_origin_in_html_body(response: dict, value: str) -> TokenOrigin | None` — usa BeautifulSoup para encontrar elemento e atributo
- [ ] Implementar `find_origin_in_redirect(response: dict, value: str) -> TokenOrigin | None` — verifica `redirect_url`
- [ ] Implementar `find_origin_in_script(response: dict, value: str) -> TokenOrigin | None` — busca em conteúdo `<script>`
- [ ] Implementar `resolve_origin(candidate: Candidate, grep_match: GrepMatch, responses_dir: str) -> TokenOrigin | None` — chama as funções acima na ordem correta conforme `body_mime`
- [ ] Criar `tests/tracker/test_find_origin.py` — testa cada função com response fixtures mínimas

### 2.6 Geração do CurlTemplate (etapas 4 e 7 do pipeline)
- [ ] Implementar `build_curl_template(step: dict, candidates: list[Candidate], statics: list[Candidate]) -> CurlTemplate`
- [ ] Substituir candidatos por `{{token_id_provisório}}` e preencheer estáticos diretamente
- [ ] Implementar `finalize_curl_template(template: CurlTemplate, resolved: dict[Candidate, TokenOrigin], unresolved: list[Candidate], har_step: dict) -> CurlTemplate` — substitui provisórios por `token_id` definitivos e reverte unresolveds para valor estático do HAR com comentário
- [ ] Implementar `render_curl_file(template: CurlTemplate) -> str` — gera o conteúdo `.curl.sh` com comentários de cabeçalho
- [ ] Criar `tests/tracker/test_curl_template.py` — testa geração do template e renderização do arquivo shell

### 2.7 Agentes especializados — base
- [ ] Criar `har_reproducer/agents/base.py`
- [ ] Implementar classe abstrata `BaseAgent` com método `generate(context: dict) -> str` (retorna código Python)
- [ ] Implementar `run_tdd_loop(agent: BaseAgent, test_code: str, context: dict, max_attempts: int = 5) -> tuple[str, bool]` — executa o loop TDD: gera código, roda teste, devolve erro ao agente se falhar, retorna `(code, verified)`
- [ ] Implementar `run_pytest_in_memory(test_code: str, extractor_code: str, expected_value: str) -> tuple[bool, str]` — cria arquivos temp, roda `pytest` via subprocess, retorna `(passed, output)`
- [ ] Criar `tests/agents/test_base.py` — testa `run_pytest_in_memory` com código correto e incorreto

### 2.8 Agentes especializados — implementações
- [ ] Criar `har_reproducer/agents/cookie_agent.py` — agente que gera extratores de `Set-Cookie`; usa chamada à API Anthropic
- [ ] Criar `har_reproducer/agents/header_agent.py` — agente que gera extratores de headers simples
- [ ] Criar `har_reproducer/agents/jsonpath_agent.py` — agente que gera extratores com `jsonpath-ng`
- [ ] Criar `har_reproducer/agents/css_agent.py` — agente que gera extratores com BeautifulSoup
- [ ] Criar `har_reproducer/agents/regex_agent.py` — agente para caso geral e `<script>`
- [ ] Implementar `select_agent(origin: TokenOrigin) -> BaseAgent` — retorna o agente correto para cada tipo de origem
- [ ] Criar `tests/agents/test_cookie_agent.py` — fixture com response real contendo `Set-Cookie`, valida que o extrator gerado passa no teste TDD
- [ ] Criar `tests/agents/test_jsonpath_agent.py` — idem para body JSON
- [ ] Criar `tests/agents/test_css_agent.py` — idem para `<input>` em HTML
- [ ] Criar `tests/agents/test_regex_agent.py` — idem para `<script>var token=...`

### 2.9 Registry de extratores e função principal do tracker
- [ ] Implementar `generate_extractor(candidate: Candidate, origin: TokenOrigin, response_file: str) -> Extractor` — gera teste TDD, ativa agente, roda loop, retorna `Extractor`
- [ ] Implementar `generate_token_id(candidate: Candidate) -> str` — deriva `token_id` do nome do campo (ex: `Authorization` → `jwt_main`)
- [ ] Implementar `analyze_step(step_index: int, steps_dir: str, real_responses_dir: str, extractor_registry: dict[str, Extractor]) -> StepAnalysis` — função principal do módulo, orquestra etapas 1–8
- [ ] Implementar `save_extractor(extractor: Extractor, output_dir: str) -> None` — salva `extractors/extract_<token_id>.py`
- [ ] Implementar `save_curl(template: CurlTemplate, output_dir: str) -> None` — salva `curls/req_NNNN.curl.sh`
- [ ] Implementar log de diagnóstico por step (formato definido na seção 11 do plano)

### 2.10 Fixtures e testes do Token Tracker
- [ ] Criar `tests/fixtures/tracker/tracker_jwt_body/` com steps e real_responses simulando JWT em JSON body
- [ ] Criar `tests/fixtures/tracker/tracker_set_cookie/` — Set-Cookie de sessão
- [ ] Criar `tests/fixtures/tracker/tracker_csrf_html/` — CSRF em `<input>` HTML
- [ ] Criar `tests/fixtures/tracker/tracker_redirect_param/` — token em `Location:` header
- [ ] Criar `tests/fixtures/tracker/tracker_script_token/` — token em `<script>`
- [ ] Criar `tests/fixtures/tracker/tracker_static_headers/` — User-Agent e Accept-Language iguais ao baseline
- [ ] Criar `tests/fixtures/tracker/tracker_unknown_origin/` — header dinâmico sem origem nas responses
- [ ] Criar `tests/fixtures/tracker/tracker_ambiguous/` — valor aparece em duas responses
- [ ] Criar `tests/fixtures/tracker/tracker_complex_flow/` — 8+ steps com combinação de todos os casos
- [ ] Criar `tests/tracker/test_jwt_body.py` — valida `StepAnalysis` com asserções exatas
- [ ] Criar `tests/tracker/test_set_cookie.py`
- [ ] Criar `tests/tracker/test_csrf_html.py`
- [ ] Criar `tests/tracker/test_redirect_param.py`
- [ ] Criar `tests/tracker/test_script_token.py` — valida aviso gerado para `<script>`
- [ ] Criar `tests/tracker/test_static_headers.py`
- [ ] Criar `tests/tracker/test_unknown_origin.py` — valida que candidato vai para `unresolved`
- [ ] Criar `tests/tracker/test_ambiguous.py` — valida escolha do menor índice
- [ ] Criar `tests/tracker/test_complex_flow.py` — integração: todos os extratores com `verified = True`

### 2.11 Success Validator
- [ ] Criar `har_reproducer/validator.py`
- [ ] Implementar `SuccessCriteria` como modelo Pydantic com campo `type` e campos opcionais por tipo
- [ ] Implementar `check_url_match(response: dict, pattern: str) -> bool`
- [ ] Implementar `check_status_code(response: dict, expected: int) -> bool`
- [ ] Implementar `check_body_contains(response: dict, text: str) -> bool`
- [ ] Implementar `check_html_element_present(response: dict, selector: str) -> bool` — usa BeautifulSoup
- [ ] Implementar `validate(response: dict, criteria: SuccessCriteria) -> bool` — despacha para o tipo correto
- [ ] Implementar `composite` — valida uma lista de critérios com operador `AND`
- [ ] Criar `tests/test_validator.py` — testa cada tipo de critério com responses fake

### 2.12 Request Engine
- [ ] Criar `har_reproducer/engine.py`
- [ ] Implementar `build_request_from_curl_template(template: CurlTemplate, session: SessionStore) -> httpx.Request`
- [ ] Implementar `save_real_response(response: httpx.Response, index: int, output_dir: str) -> None` — salva `real_responses/res_{N:04d}.json`
- [ ] Implementar `apply_extractors(extractors: list[Extractor], response: dict, session: SessionStore) -> None` — roda cada extrator e alimenta o session store
- [ ] Implementar regras de recovery determinísticas: `recovery_401_403(session: SessionStore) -> dict | None`, `recovery_redirect(response: dict) -> str | None`, `recovery_csrf_400(response: dict, session: SessionStore) -> dict | None`
- [ ] Implementar `execute_step(step_index: int, ...) -> dict` — executa um único step com retry após recovery
- [ ] Implementar `run(har_path: str, config: dict) -> bool` — loop principal de execução (parse → step 0 → steps N ≥ 1 → validator)
- [ ] Criar `tests/engine/test_build_request.py` — testa construção de request com session store preenchido
- [ ] Criar `tests/engine/test_apply_extractors.py` — testa que extratores alimentam o session store corretamente
- [ ] Criar `tests/engine/test_recovery.py` — testa cada regra de recovery com responses mock
- [ ] Criar `tests/engine/test_run_simple_flow.py` — usa `pytest-httpx` para mockar servidor e executar `simple_flow.har` completo até critério de sucesso

### 2.13 Modo `--dry-run` no tracker
- [ ] Adicionar parâmetro `dry_run: bool = False` ao `analyze_step()`
- [ ] Quando `dry_run=True`, usar `steps/res_{N:04d}.json` (do HAR) como responses em vez de `real_responses/`
- [ ] Ajustar `expected_value` dos testes para usar valor do HAR
- [ ] Implementar `dry_run_report(har_path: str, steps_dir: str) -> str` — roda tracker em todos os steps e retorna relatório legível
- [ ] Criar `tests/tracker/test_dry_run.py` — valida relatório gerado contra `complex_flow.har`

### 2.14 Comando CLI `run`
- [ ] Implementar subcomando `har-reproducer run --har <path>` no `cli.py`
- [ ] Adicionar flag `--dry-run` que executa `dry_run_report()` e imprime o relatório
- [ ] Integrar com `run()` do engine para execução real
- [ ] Testar manualmente com `uv run har-reproducer run --har tests/fixtures/simple_flow.har --dry-run`

---

## Fase 3 — LLM Agent

### 3.1 Estrutura do agente de diagnóstico
- [ ] Criar `har_reproducer/agent.py`
- [ ] Implementar `FailureContext` como Pydantic model (campos: `step_index`, `request_attempted`, `response_received`, `session_state`, `extractors_used`, `error_message`)
- [ ] Implementar `Patch` como Pydantic model (campos: `type`, `token_id`, `value`, `extractor_code`, `description`)
- [ ] Definir interface das tools do agente: `read_step_file`, `search_in_steps`, `get_session_state`, `propose_extraction_rule`, `propose_injection`, `propose_token_override`

### 3.2 Implementação das tools do agente
- [ ] Implementar `tool_read_step_file(step_index: int, file_type: str, steps_dir: str) -> str` — lê `req_NNNN.json` ou `res_NNNN.json`
- [ ] Implementar `tool_search_in_steps(query: str, steps_dir: str) -> list[str]` — grep nos steps
- [ ] Implementar `tool_get_session_state(session: SessionStore) -> dict`
- [ ] Implementar `tool_propose_extraction_rule(token_id: str, location: str, rule: str) -> Patch`
- [ ] Implementar `tool_propose_injection(token_id: str, value: str) -> Patch`
- [ ] Implementar `tool_propose_token_override(token_id: str, extractor_code: str) -> Patch`

### 3.3 Loop de diagnóstico e aplicação de patch
- [ ] Implementar `diagnose(context: FailureContext, steps_dir: str, real_responses_dir: str) -> Patch | None` — chama API Anthropic com tools, retorna patch proposto
- [ ] Implementar `apply_patch(patch: Patch, session: SessionStore, extractor_registry: dict) -> None` — aplica o patch no estado atual
- [ ] Integrar com o engine: após recovery determinístico falhar, chamar `diagnose()` → `apply_patch()` → retry
- [ ] Limite de 1 tentativa LLM por step (evitar loop infinito)

### 3.4 Fixture e teste do LLM Agent
- [ ] Criar `tests/fixtures/jwt_in_html.har` — token JWT dentro de `<script>var token="..."</script>` em resposta HTML
- [ ] Criar `tests/agent/test_diagnose_jwt_html.py` — usa mock do servidor para simular falha, verifica que o agente propõe patch correto e que o re-run com patch tem sucesso
- [ ] Criar `tests/agent/test_apply_patch.py` — testa aplicação de cada tipo de patch no session store

### 3.5 Comando CLI `diagnose`
- [ ] Implementar subcomando `har-reproducer diagnose --steps <dir> --real-responses <dir>` no `cli.py`
- [ ] Chamar `diagnose()` para o último step que falhou e imprimir o relatório do patch proposto

---

## Fase 4 — Teste ponta a ponta

### 4.1 Preparar HAR real para teste
- [ ] Capturar `real.har` em janela anônima com fluxo completo (login → página autenticada)
- [ ] Verificar que `req[0]` é de fato a primeira requisição sem cookies ou tokens
- [ ] Rodar `uv run har-reproducer parse --har real.har --output ./steps` e inspecionar steps gerados

### 4.2 Dry-run do HAR real
- [ ] Rodar `uv run har-reproducer run --har real.har --dry-run`
- [ ] Revisar relatório: candidatos detectados, origens identificadas, unresolveds
- [ ] Ajustar `ALWAYS_DYNAMIC_PATTERNS` se necessário com base nos tokens encontrados

### 4.3 Execução real
- [ ] Rodar `uv run har-reproducer run --har real.har`
- [ ] Acompanhar log de diagnóstico step a step
- [ ] Verificar que o Success Validator confirma critério atingido na última page

### 4.4 Diagnóstico de falhas (se houver)
- [ ] Para cada step que falhar, rodar `uv run har-reproducer diagnose --steps ./steps --real-responses ./real_responses`
- [ ] Ajustar critério de sucesso se necessário
- [ ] Corrigir extratores `unresolved` manualmente se o LLM Agent não resolver

### 4.5 Critérios de conclusão do projeto
- [ ] `uv run pytest` passa 100% (todas as fases)
- [ ] `uv run har-reproducer run --har real.har` chega na última página com critério de sucesso validado
- [ ] Todos os arquivos em `curls/` são sintaticamente válidos (`bash -n curls/req_NNNN.curl.sh`)
- [ ] Todos os extratores em `extractors/` têm `verified = True` nos logs
- [ ] `uv run har-reproducer run --har real.har --dry-run` gera relatório legível sem erros

---

## Referência rápida de comandos

```bash
# Setup inicial
uv init har-reproducer && cd har-reproducer
uv venv .venv
uv add httpx pydantic beautifulsoup4 jsonpath-ng
uv add --dev pytest pytest-httpx

# Desenvolvimento
uv run pytest                          # roda toda a suite
uv run pytest tests/parser/            # roda só os testes do parser
uv run pytest -k test_jwt_body         # roda um teste específico

# CLI
uv run har-reproducer parse  --har arquivo.har --output ./steps
uv run har-reproducer run    --har arquivo.har
uv run har-reproducer run    --har arquivo.har --dry-run
uv run har-reproducer diagnose --steps ./steps --real-responses ./real_responses
```
