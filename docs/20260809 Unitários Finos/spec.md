# Etapa C — Unitários Finos

## Objetivo

Adicionar uma camada de testes unitários em `tests/` (fora da rede golden) que exercite, com dublês, as classes e métodos que já receberam costuras de testabilidade na Etapa B — sem tocar em `har_reproducer/`.

Critério de sucesso: cada alvo listado abaixo tem ao menos um teste que isola a unidade por injeção de construtor (costuras B) ou por função/estático puro, e o portão `uv run pytest --runslow` segue verde com os 39 golden intactos.

### Restrição dura

**Nenhum arquivo dentro de `har_reproducer/` muda nesta etapa.** Se um teste precisar de uma costura nova, o alvo sai do escopo (ver "Fora de escopo") e vira assunto de outra spec. Arquivos permitidos de mudar/adição: `tests/` e, se aprovado, `pyproject.toml`/`pytest.ini` (ver Decisão D.8).

## Componentes existentes reaproveitados

- **Costuras da Etapa B** — cada classe de produção tem todos os colaboradores injetados no `__init__`:
  - `Workspace(output_dir)` materializa os 8 subdiretórios sob um `tmp_path` (`har_reproducer/fs_io/workspace.py:8-24`), sem rede — serve de FS real para os testes que precisam de arquivo.
  - `ExtractorRunner(workspace, script_executor)` (`har_reproducer/reproduction/extractor_runner.py:14-16`), `ExtractorMetadataStore(workspace)` (`har_reproducer/reproduction/extractor_metadata_store.py:9-10`), `TokenResolver(responses_dir, session_store, extractor_runner)` (`har_reproducer/tracking/token_resolver.py:10-13`), `TokenTracker(baseline_diff, candidate_resolver, placeholder_applier, curl_generator)` (`har_reproducer/tracking/token_tracker.py:12-22`), `CandidateResolver(responses_dir, session_store, extractor_runner, metadata_store, agent_factory)` (`har_reproducer/tracking/candidate_resolver.py:24-38`), `ReplayRunner` (atribuição pura, `har_reproducer/replay/replay_runner.py:20-44`), `ReplayTokenResolver(session_store, extractor_runner, dependency_parser, metadata_store)` (`har_reproducer/replay/replay_token_resolver.py:13-23`).
  - `Sleeper.sleep` é `@staticmethod` (`har_reproducer/reproduction/sleeper.py:6-8`) — dublê por subclasse com método de instância (a costura B permite sobrescrever o staticmethod).
  - `HttpTransport` é `Protocol` (`har_reproducer/contracts/http_transport.py:6-7`) — qualquer objeto com `send_request(curl_literal, step_index) -> StepResponse` qualifica.
- **Modelos pydantic reais** em asserts e dublês: `StepRequest`/`StepResponse`/`Step` (`har_reproducer/models/http.py:7-31`), `Extractor`/`DynamicToken`/`TokenLocation`/`AgentType`/`SessionState` (`har_reproducer/models/session.py:7-51`), `StepAnalysis` (`har_reproducer/models/analysis.py:8-12`), `ScriptExecutionResult` (`har_reproducer/models/execution.py:4-8`), `ProjectConfig`/`SkipRulesConfig` (`har_reproducer/models/config.py:16-26`).
- **Infra de testes existente**: `tmp_path`, fixtures do `tests/conftest.py` (não reutilizamos `golden_*` para os novos testes, apenas o padrão de fixtures já registrado); estilo de suporte em `tests/support/` (classes com `ClassVar`, tipagem explícita — ver `tests/support/golden_workspace.py:11-21`).

## Decisões de arquitetura

- **D.1 — Local**: novos arquivos em `tests/unit/` (`test_<alvo>.py`), dublês compartilhados em `tests/support/` (módulos novos, sem tocar nos existentes). Nada solto no módulo de teste além de `@pytest.fixture` e funções `test_*` (guia de estilo); qualquer helper vai para `tests/support/` como classe.
- **D.2 — Dublês manuais**: classes pequenas em `tests/support/` (ex.: `FakeScriptExecutor`, `FakeSleeper`, `StubHttpTransport`, `FakeExtractorRunner`, `FakeMetadataStore`). Prioridade: injeção por construtor. `monkeypatch` é aceito pontualmente onde a injeção não alcança (ex.: `CurlHttpTransport._read_captured_response` stubando `_try_read_capture`); não usar `pytest-httpx` (nenhuma unidade alvo usa `httpx`).
- **D.3 — Falsos custosos**: não dublar pydantic; `SessionStore` é puro e entra real nos testes (incluindo dentro de `PlaceholderApplier` e `CandidateResolver._check_persisted_slot`).
- **D.4 — Sem golden**: unitários não invocam `main()`, não comparam árvore de diretório nem usam `GoldenWorkspace`/`CliInvoker`.
- **D.5 — Escopo por prioridade** (reclassifica por ordem de execução os mesmos arquivos já listados na tabela "Resumo" — não é um segundo conjunto de alvos; ex.: "`Workspace.__init__`+helpers" abaixo é o mesmo alvo de `test_workspace.py` na tabela, só priorizado como P0). O plano escalona nesta ordem:
  - **P0 — puras e orquestrações simples** (custo baixo, valor alto): `SessionStore`, `BaselineDiff`, `PlaceholderApplier`, `CurlGenerator`, `CurlDependencyParser`, `StepSkipEvaluator`, `StepRetryPolicy`, `TokenLocationDetector`, helpers de `ResponseGrep`, `ExtractorMetadataStore`, `ExtractorRunner`, `Workspace.__init__`+helpers, `Validator` (sem `__init__`, só `@staticmethod` sobre modelos pydantic), `HARParser.decode_body`/`parse_entry` (idem, `load_har`/`get_entries`/`split_har` ficam fora por dependerem de FS real sem ganho adicional de cobertura sobre o que os 39 golden já exercitam via `main()`).
  - **P1 — orquestrações com dublês**: `CandidateResolver._find_slot/_check_slot/_check_cached_slot/_check_persisted_slot/_accept_persisted_slot` (alvo prioritário apontado pela spec da Etapa A §3.9), `TokenTracker.analyze_step`, `TokenResolver`, `ReplayTokenResolver`, `ReplayResultComparator`, `ReplayRunner` (scheduling + `_mark_token_static` + `_run_step` com fakes), `ScriptExecutor` (integração fina com subprocess real), `BaseAgent` + estratégias determinísticas dos 5 agents, `AgentFactory.create`.
  - **P2 — fiação de grafos**: `EngineFactory.resolve_class/create` (Dry e Main com transport dummy), `Engine`/`DryEngine` (pontos simples: `handle_recovery`, `_skip_entry`, `_validate_final`, `DryEngine.execute_step`/`_persist_response_step`), `CurlHttpTransport` (helpers `_build_curl_command`, `_tls_flag`, `_decode_stderr`, `_build_error_response`, `_read_captured_response`), `MitmProxyOrchestrator` (helpers `_build_command`, `_build_env`, `_prepend_package_root`, `_resolve_port`, `_find_free_port`, `_build_port_conflict_message`, `_build_early_exit_message`, `_terminate`).
- **D.6 — Regra de não-regressão**: o portão é `uv run pytest --runslow` (39 golden, ~32s). Unitários rodam também sem `--runslow` (nenhum marcado `slow`). Nenhum arquivo em `tests/golden/` muda e nenhum `tests/test_cli_*.py` é alterado.
- **D.7 — `Workspace.get_mitmproxy_ca_path` fora de escopo** (cria `.mitmproxy/` no pai do pacote — `har_reproducer/fs_io/workspace.py:30-34`; efeito colateral no repo). `_build_early_exit_message` entra (usa só `workspace.mitm_log_file()` + `self._process.returncode` — `har_reproducer/reproduction/mitm_proxy_orchestrator.py:112-116`). `_terminate` também entra (`mitm_proxy_orchestrator.py:159-173`): opera só sobre `self._process`/`self._log_file`, ambos atribuíveis diretamente no teste (`orchestrator._process = FakeProcess()`, sem chamar `_start_process`) — mesmo raciocínio de "só toca atributo de instância opaco" usado para aceitar `_build_early_exit_message`, então não faz sentido tratá-lo como sem seam.
- **D.8 — Defect §6.7 da spec da Etapa A (`pytest`/`pytest-httpx` em `dependencies` no `pyproject.toml:17-18`, sem grupo dev): **adiar**. Motivos: (a) não é pré-requisito desta etapa — o marker `slow` já é registrado em runtime no `tests/conftest.py:27`; (b) mover para `[dependency-groups]` implica `uv sync` + mudança de lockfile, risco que não compensa o ganho aqui. Registrar como débito para uma etapa futura de higiene do projeto.

## Resumo

Alvo por arquivo de teste (nome de arquivo em `tests/unit/`), com âncora do método principal:

| Arquivo | Alvo | Âncora | Técnica |
|---|---|---|---|
| `test_session_store.py` | `set_token/get_token/render/render_dict` | `har_reproducer/session/session_store.py:14-41` | direto |
| `test_baseline_diff.py` | `compare`, `_diff_*`, `detect_candidates`, `_determine_location`, `extract_static_values` | `har_reproducer/tracking/baseline_diff.py:9-84` | direto |
| `test_placeholder_applier.py` | `apply` (ordenação por tamanho), substituições em url/header/cookie/body (str e bytes) | `har_reproducer/tracking/placeholder_applier.py:12-80` | `SessionStore` real |
| `test_curl_generator.py` | `generate`, `_curl_parts`, `_token_comments` (3 variantes de comentário) | `har_reproducer/reproduction/curl_generator.py:9-75` | direto |
| `test_curl_dependency_parser.py` | `parse` | `har_reproducer/replay/curl_dependency_parser.py:12-16` | direto |
| `test_step_skip_evaluator.py` | `skip_reason` (schemes, métodos, caixa) | `har_reproducer/reproduction/step_skip_evaluator.py:13-19` | `SkipRulesConfig` real |
| `test_step_retry_policy.py` | `execute` (retry, sem retry, último attempt) | `har_reproducer/reproduction/step_retry_policy.py:10-23` | fakes `attempt_fn`/`recovery_fn` |
| `test_response_grep_helpers.py` | `try_decode`, `value_variants`, `_deduplicate`, `_extract_step_index` | `har_reproducer/tracking/response_grep.py:23-59,93-100` | direto |
| `test_token_location_detector.py` | `find` + heurísticas (headers/cookies/redirect/json/html/script) | `har_reproducer/tracking/token_location_detector.py:11-115` | direto sobre `response_sample` dict |
| `test_extractor_metadata_store.py` | `load`/`save`, arquivo ausente, json inválido | `har_reproducer/reproduction/extractor_metadata_store.py:12-24` | `Workspace` tmp real |
| `test_extractor_runner.py` | `run` (ValueError sem `origin_step`), `run_existing` (arquivo ausente → None), `_execute_extractor_script`, `_build_env` | `har_reproducer/reproduction/extractor_runner.py:18-76` | `Workspace` tmp + `FakeScriptExecutor` |
| `test_workspace.py` | `__init__` cria 8 subdirs; helpers de path | `har_reproducer/fs_io/workspace.py:8-69` | `tmp_path` |
| `test_script_executor.py` | `run` com script real (`sys.executable`), timeout → `TIMEOUT_RETURN_CODE=-1` | `har_reproducer/reproduction/script_executor.py:13-37` | subprocess fino (~1s) |
| `test_candidate_resolver.py` | `_find_slot` (fork), `_check_slot`, `_check_cached_slot`, `_check_persisted_slot`, `_accept_persisted_slot`, `_derive_token_id`, `_fork_token_id`, `_mismatch_error`, `_build_literal_extractor` | `har_reproducer/tracking/candidate_resolver.py:72-143,189-198` | dublês `FakeExtractorRunner`/`FakeMetadataStore` + `SessionStore` real |
| `test_token_resolver.py` | `resolve_all`, `_should_refresh_token`, `_refresh_token` (res ausente; run ok; run falha) | `har_reproducer/tracking/token_resolver.py:15-36` | `SessionStore` real + `FakeExtractorRunner` |
| `test_token_tracker.py` | `analyze_step` orquestra compare→detect→resolve→apply→generate→static | `har_reproducer/tracking/token_tracker.py:24-37` | fakes dos 4 colaboradores |
| `test_replay_token_resolver.py` | `resolve`, `_resolve_one`, `_reference_dir_for_step`, `_record_observation` (threshold `STATIC_CONFIRMATION_THRESHOLD=5`) | `har_reproducer/replay/replay_token_resolver.py:25-84` | dublês runner/metadata + parsers reais |
| `test_replay_result_comparator.py` | `matches_original` (match, status ausente, sem referência), `_read_reference_text` (fallback original) | `har_reproducer/replay/replay_result_comparator.py:15-36` | `Workspace` tmp real |
| `test_replay_runner.py` | `_schedule_all/slice/smart/list`, `_expand_pending`, `_require_all_existing`, `_existing_step_indexes`, `_mark_token_static`, `_annotate_static_tokens`, `_run_step` | `har_reproducer/replay/replay_runner.py:79-181` | `Workspace` tmp com `curls/` + fakes |
| `test_curl_http_transport.py` | `_build_curl_command`, `_tls_flag`, `_decode_stderr`, `_build_error_response`, `_read_captured_response` (monkeypatch `_try_read_capture`) | `har_reproducer/reproduction/curl_http_transport.py:45-95` | dublês + `FakeSleeper` |
| `test_mitm_proxy_orchestrator.py` | `_build_command`, `_build_env`, `_prepend_package_root`, `_resolve_port`, `_find_free_port`, `_build_port_conflict_message`, `_build_early_exit_message`, `_terminate` | `har_reproducer/reproduction/mitm_proxy_orchestrator.py:34-116,151-173` | `Workspace` tmp + fake de processo (`_process`/`_log_file` atribuídos direto, sem `_start_process`) |
| `test_base_agent.py` | `key`, `value_char_class`, `lazy_value_char_class`, `generate_code`, `_extract_code_block`, `_response_to_text`, `run_tdd_loop` | `har_reproducer/agents/base_agent.py:45-201` | dublês workspace/script/sleeper |
| `test_agents_strategies.py` | `deterministic_strategies` e padrões dos 5 agents (Cookie/Header/JSONPath/CSS/Regex) | `har_reproducer/agents/cookie_agent.py:10-64`, `header_agent.py:10-80`, `jsonpath_agent.py:9-63`, `css_agent.py:16-112`, `regex_agent.py:10-56` | dublês + parsers reais (json/bs4) |
| `test_agent_factory.py` | `create` mapeia `TokenLocation` → agent, fallback `DEFAULT_AGENT=RegexAgent` | `har_reproducer/agents/construction/agent_factory.py:17-51` | dublês |
| `test_engine_factory.py` | `resolve_class`, `create` Dry (sem transport, dir `original_responses`) e Main (com transport dummy), grafo `_build_tracker` | `har_reproducer/engines/construction/engine_factory.py:29-94` | dublês + `ProjectConfig()` default |
| `test_engine.py` | `handle_recovery`, `_skip_entry`, `_validate_final`, `DryEngine.execute_step`/`_persist_response_step` | `har_reproducer/engines/engine.py:85-128`, `dry_engine.py:10-15` | fakes por construtor |
| `test_validator.py` | `validate`/`_check_criterion` (4 tipos de `SuccessCriterion` + fallback `False`) | `har_reproducer/validation/validator.py:18-47` | direto, sem dublê (classe sem `__init__`, só `@staticmethod` sobre modelos pydantic) |
| `test_har_parser.py` | `decode_body` (vazio, base64 ok, base64 corrompido), `parse_entry` (monta `Step` a partir de um dict HAR mínimo) | `har_reproducer/fs_io/har_parser.py:27-82` | direto, dict Python cru simulando uma `entry` de HAR |

### Fora de escopo (limites reais, sem seam — registrar, não testar)

- `ResponseGrep.find`/`_grep_single_pattern` — subprocess `grep` real (`har_reproducer/tracking/response_grep.py:11-21,61-82`).
- `CandidateResolver._process_candidate`/`_find_origin`/`_load_response` — usam `ResponseGrep.find` e leitura direta de `res_{i:04d}.json` (`candidate_resolver.py:43-70,159-168`).
- `CurlHttpTransport.send_request` — `["bash", "-c", curl]` real (`har_reproducer/reproduction/curl_http_transport.py:26-30`).
- `MitmProxyOrchestrator._start_process`/`_wait_until_ready`/`_probe_proxy`/`_can_connect`/`_classify_response`/`_fetch_server_header` — subprocess mitmdump e sockets (`mitm_proxy_orchestrator.py:59-149`). `_terminate` **não** está nesta lista — ver D.7, entra no escopo.
- `Workspace.get_mitmproxy_ca_path` — escreve `.mitmproxy/` no repo (D.7).
- `HARParser.load_har`/`get_entries`/`split_har` — I/O real sobre `.har`/diretório de saída, já exercitado pelos 39 golden via `main()`; sem ganho adicional em isolar aqui (`har_parser.py:12-25,84-104`).
- Ponto cego já coberto pela rede golden e **não** entram aqui: `_build_early_exit_message` entrou (D.7); `ReplayRunner._annotate_static_tokens`/`_mark_token_static` entram; `Validator` e `HARParser.decode_body`/`parse_entry` entram (ver tabela "Resumo") — nenhum dos dois ficou de fora nesta versão da spec.
- Redundância evitada: `CliHandlers._validate_replay_mode_flags` já coberto por `tests/test_cli_errors.py` — não duplicar.

## Casos de borda

- `SessionStore.render` com token ausente no estado → placeholder preservado (`session_store.py:39-40`).
- `BaselineDiff._diff_body` com `body` None de um lado (`baseline_diff.py:41`); `body` bytes não-UTF8 → `errors="replace"` (`baseline_diff.py:46-49`).
- `PlaceholderApplier`: token não verificado não substitui; valor vazio é pulado; body bytes indecodável permanece intacto (`placeholder_applier.py:21,34-38,72-79`).
- `CurlGenerator._token_comments`: `origin_step` None; origem determinada mas `extraction_exhausted` (`curl_generator.py:58-71`).
- `StepSkipEvaluator`: scheme maiúsculo; `urlparse` de URL sem scheme (`step_skip_evaluator.py:14-16`).
- `StepRetryPolicy`: `MAX_STEP_ATTEMPTS=2` garante no máximo 2 chamadas a `attempt_fn` (`step_retry_policy.py:7,16-22`).
- `ResponseGrep.try_decode`: valor sem codificação alguma permanece idêntico (`response_grep.py:24-39`).
- `ReplayTokenResolver._record_observation`: `ever_changed=True` depois de uma divergência faz a função retornar `False` para sempre, mesmo re-atingindo 5 observações (`replay_token_resolver.py:74-84`).
- `ReplayRunner._mark_token_static`: linha já anotada não recebe sufixo duplicado; texto sem a linha do token não muda (`replay_runner.py:113-121`); `_run_schedule` com lista vazia levanta `ValueError` (`replay_runner.py:63-64`).
- `ReplayResultComparator._read_reference_text`: `real_responses` ausente cai para `original_responses`; ambos ausentes → `None` → `matches_original` False (`replay_result_comparator.py:26-36`).
- `CandidateResolver._find_slot`: primeiro slot `MISMATCH` força fork (`_fork_token_id`), `FREE` retorna com o `last_error` acumulado (`candidate_resolver.py:72-85`).
- `ExtractorRunner._write_extractor_script`: `origin_step=None` → `ValueError` (`extractor_runner.py:33-35`).
- `ExtractorMetadataStore.load`: json corrompido → `None` + aviso (`extractor_metadata_store.py:16-20`).
- `CurlHttpTransport._tls_flag`: `ca_cert_path=None` → `--insecure` (`curl_http_transport.py:54-58`).
- `MitmProxyOrchestrator._build_early_exit_message`: arquivo de log inexistente → corpo vazio, mensagem com exit code (`mitm_proxy_orchestrator.py:112-116`).
- `BaseAgent.value_char_class`: valor com espaços → `.+?`; `lazy_*` converte `+` em `?` (`base_agent.py:53-62`).
- Agents: `CookieAgent._context_pattern`/`HeaderAgent._context_pattern` com valor no fim (sufixo vazio → `$`) (`cookie_agent.py:40-43`, `header_agent.py:52-55`); `JSONPathAgent._find_value_paths` com body não-JSON → `[]` (`jsonpath_agent.py:13-18`); `CSSAgent._rank_candidates` com `id` não único é descartado (`css_agent.py:63-65`); `RegexAgent._key_pattern` com `key == "body"` → `None` (`regex_agent.py:20-23`).
- `Validator._check_criterion`: `return False` final (`validator.py:47`) é código morto observável — `SuccessCriterion` é `Union` discriminado por `type` com exatamente os 4 branches já cobertos (`models/criteria.py:26-32`), então nenhum valor do tipo real cai no fallback. Cobrir só os 4 branches reais; não escrever teste para o fallback (não há como construir um `SuccessCriterion` que caia nele) e não remover a linha — isso é decisão de produção, fora de escopo desta etapa (guia de estilo: avisar, não simplificar em silêncio).
- `HARParser.decode_body`: `body_content=""` → `""` sem checar `encoding` (`har_parser.py:30-31`); `encoding="base64"` com payload inválido → `except Exception` amplo, `print` de aviso, retorna `body_content` original intacto (`har_parser.py:34-38`).

## Suposições

- Testes rodam offline: sem mitmproxy, sem curl real, sem rede; `tmp_path` cobre todo o FS.
- `ScriptExecutor` é a única unidade que executa subprocess real (`sys.executable`), e é rápido (<1s por caso).
- Dependências já disponíveis no ambiente bastam: `pytest` (`pyproject.toml:17`), `beautifulsoup4` (`pyproject.toml:8`, usada por `CSSAgent`), `pydantic`. Não usaremos `pytest-httpx`.
- O comportamento de produção é o contrato: nenhum teste corrige semântica — se um teste revelar comportamento claramente errado, documentar no plano como achado para o usuário decidir (produção não pode mudar aqui).
- Nada de `HAR_REPRODUCER_UPDATE_GOLDEN=1`; nenhum arquivo em `tests/golden/` ou `tests/test_cli_*.py` muda (D.6).

## Referência ao guia de estilo

Vale integralmente dentro de `tests/` (spec da Etapa B §3.7): tipagem explícita em assinaturas e variáveis; constantes como `ClassVar` em classes; nada solto no módulo além de `@pytest.fixture` e funções `test_*`; dublês são classes em `tests/support/`, não funções soltas; sem comentários supérfluos; decompor em métodos pequenos; nomes de testes em `test_<comportamento>`.
