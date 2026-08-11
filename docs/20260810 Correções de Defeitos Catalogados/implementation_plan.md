# Plano de Implementação — Correções de Defeitos Catalogados (itens 6 e 9)

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.
>
> T01–T03 (item 6) já foram implementados e commitados (`feat: T01/T02`, `refactor:
> T03`). Este plano estende o arquivo com as tasks T04+ do item 9 (spec reescrita
> para o item 9).

## [T01] — `MitmProxyOrchestrator`: renomear `project_root` → `confdir`

**Depende de:** Nenhuma (Contexto de pré-requisito).
**Arquivos envolvidos:** `har_reproducer/reproduction/mitm_proxy_orchestrator.py` (MitmProxyOrchestrator), `tests/unit/test_mitm_proxy_orchestrator.py`

**Contexto:**
O parâmetro/atributo `project_root` de `MitmProxyOrchestrator` é um nome que mente:
os chamadores passam `project_config.ca_cert_path` (o `confdir` do mitmproxy, um
diretório de config) e o próprio `_build_command` o usa como `confdir`. O nome
sugere a raiz do projeto e esconde o papel real. A correção é só de nomenclatura —
nenhum comportamento muda (spec seção 3.1).

**Estado atual:**
- `mitm_proxy_orchestrator.py:26-30`:
  ```python
  def __init__(self, workspace: Workspace, proxy_port: Optional[int], project_root: Path) -> None:
      self.workspace: Workspace = workspace
      self.project_root: Path = project_root
      self.port: int = self._resolve_port(proxy_port)
      self.ca_cert_path: Path = self.project_root / self.CA_CERT_FILENAME
  ```
- `mitm_proxy_orchestrator.py:73`: `"--set", f"confdir={self.project_root}"`.
- `tests/unit/test_mitm_proxy_orchestrator.py:13` usa o keyword `project_root=tmp_path`.
- Os chamadores em produção (`cli_handlers.py:81-85,116-118`) passam posicionalmente — não mudam.

**Estado esperado depois:**
- Parâmetro e atributo viram `confdir`: `self.confdir: Path = confdir`, `self.ca_cert_path: Path = self.confdir / self.CA_CERT_FILENAME`.
- `_build_command` emite `f"confdir={self.confdir}"`.
- `self.ca_cert_path` mantém o nome (é o arquivo do certificado, nome honesto).
- `tests/unit/test_mitm_proxy_orchestrator.py:13` atualiza para `confdir=tmp_path`.
- Novos testes: (a) `_build_command()` contém o flag `confdir` com o valor passado; (b) `ca_cert_path` é `confdir / CA_CERT_FILENAME`.
- ⚠️ Não renomear `ProjectConfig.ca_cert_path` (chave do `config.json`, breaking change — spec §3.1).

**Critérios de aceite:**
- [x] `test_build_command_sets_confdir_to_confdir_argument`: `orchestrator._build_command()` contém `f"confdir={tmp_path}"`.
- [x] `test_ca_cert_path_is_derived_from_confdir`: `orchestrator.ca_cert_path == tmp_path / MitmProxyOrchestrator.CA_CERT_FILENAME`.
- [x] `grep -r "project_root" har_reproducer/` não retorna nada (a menos do README/docs, que não estão no escopo do grep de código).
- [x] Não-regressão: todos os testes de `tests/unit/test_mitm_proxy_orchestrator.py` passam.

## [T02] — `Workspace`/`MitmProxyOrchestrator`: mover criação de `.mitmproxy/` do load de config para o start do proxy

**Depende de:** Nenhuma (Contexto de pré-requisito).
**Arquivos envolvidos:** `har_reproducer/fs_io/workspace.py` (Workspace), `har_reproducer/reproduction/mitm_proxy_orchestrator.py` (MitmProxyOrchestrator), `tests/unit/test_workspace.py`, `tests/unit/test_mitm_proxy_orchestrator.py`

**Contexto:**
Carregar config cria `<repo>/.mitmproxy/` em disco como efeito colateral
(`ProjectConfigLoader._apply_defaults` → `Workspace.get_mitmproxy_ca_path()`, que
faz `mkdir`), mesmo em `dry` — que nunca sobe proxy. O `mkdir` sai do resolvedor de
caminho e vai para o `MitmProxyOrchestrator`, no momento em que o proxy realmente
sobe (spec seção 3.2).

**Estado atual:**
- `fs_io/workspace.py:30-34`:
  ```python
  @staticmethod
  def get_mitmproxy_ca_path() -> Path:
      path: Path = Workspace.get_root_path().parent / ".mitmproxy"
      path.mkdir(parents=True, exist_ok=True)
      return path
  ```
- `mitm_proxy_orchestrator.py:59-66`: `_start_process` abre o log e faz `Popen` do mitmdump sem garantir o confdir (a garantia hoje vem do load de config).
- `ProjectConfigLoader._apply_defaults` (`project_config_loader.py:35-38`) não muda de código — só deixa de ter efeito colateral.

**Estado esperado depois:**
- `get_mitmproxy_ca_path` vira só resolução de caminho (sem `mkdir`).
- `MitmProxyOrchestrator` ganha:
  ```python
  def _ensure_confdir(self) -> None:
      self.confdir.mkdir(parents=True, exist_ok=True)
  ```
  chamado na primeira linha de `_start_process`, antes de abrir o log/`Popen`.
- ⚠️ Criar em `_start_process`, não em `__init__`: o construtor deve continuar sem I/O (testável — spec §3.2).
- ⚠️ `mkdir(parents=True, exist_ok=True)` para confdir aninhado e já existente.

**Critérios de aceite:**
- [x] `test_get_mitmproxy_ca_path_does_not_create_directory` (`test_workspace.py`): gravar `exists()` antes de chamar; chamar `Workspace.get_mitmproxy_ca_path()`; `exists()` continua igual ao valor antes.
- [x] `test_init_does_not_create_confdir`: `MitmProxyOrchestrator(Workspace(tmp_path), proxy_port=8080, confdir=tmp_path / "nested" / "confdir")`; após o `__init__`, o diretório **não** existe.
- [x] `test_ensure_confdir_creates_directory`: mesmo orchestrator; após `_ensure_confdir()`, o diretório existe (`is_dir()`).
- [x] Não-regressão: `uv run pytest tests/ -q` passa — em particular os golden `run_dry_*` (que deixam de escrever no repo) e `run_main`/`replay` (que continuam criando `.mitmproxy/` via `_start_process`).

## [T03] — `BaseAgent.run_tdd_loop`: não dormir após o último attempt

**Depende de:** Nenhuma (Contexto de pré-requisito).
**Arquivos envolvidos:** `har_reproducer/agents/base_agent.py` (BaseAgent), `tests/unit/test_base_agent.py`

**Contexto:**
`run_tdd_loop` dorme 5s (`RETRY_DELAY_SECONDS`) após **toda** verificação que
falha, inclusive depois da última tentativa — quando não existe próximo attempt e o
loop termina falhando de qualquer forma. O sleep só faz sentido **entre** attempts
(spec seção 3.3).

**Estado atual:**
- `agents/base_agent.py:162-164`:
  ```python
  last_error = error
  print(f"Attempt {attempt + 1} failed for {self.token_id}. Retrying...")
  self.sleeper.sleep(self.RETRY_DELAY_SECONDS)
  ```
- `total` é `len(strategies)` ou `max_attempts` (`:139`); o `print` "Retrying..." permanece inalterado (contrato golden).

**Estado esperado depois:**
- `self.sleeper.sleep(...)` guardado por `if attempt < total - 1:` — dorme só se há próximo attempt.
- ⚠️ Não tocar no `print` (stdout golden dos `run_dry_*`) nem no `break` quando `generate_code` retorna `None`.

**Critérios de aceite:**
- [x] `test_run_tdd_loop_sleeps_only_between_failed_attempts`: agent com 3 estratégias que sempre falham (FakeScriptExecutor com 3 resultados de erro); `run_tdd_loop(origin_step=0)` retorna `None` e `len(sleeper.calls) == 2`. (Antes do fix: 3 calls.)
- [x] `test_run_tdd_loop_single_attempt_does_not_sleep`: agent com 1 estratégia que falha; `len(sleeper.calls) == 0`.
- [x] Não-regressão: `test_run_tdd_loop_succeeds_on_second_attempt_and_sleeps_once_between_attempts` (`test_base_agent.py:122-138`) continua com `len(sleeper.calls) == 1`; suíte completa passa.

## [T04] — `Extractor`: novo campo `captured_value`

**Depende de:** Nenhuma (Contexto de pré-requisito).
**Arquivos envolvidos:** `har_reproducer/models/session.py` (Extractor), `tests/unit/test_extractor_metadata_store.py`

**Contexto:**
Para o fallback do item 9a (spec §3.1), o extrator precisa persistir o valor que ele
capturou no HAR original — é esse literal que resolve o token quando a extração
dinâmica falha no replay. Sem o campo, o valor só existe no `DynamicToken`
(`current_value`), que não é persistido.

**Estado atual:**
- `models/session.py:26-35` — `Extractor` não tem nenhum campo de valor capturado; só `code`, `verified`, `valid_count`, `last_value`, `ever_changed`.
- `model_dump_json()` serializa campos `None` explicitamente (os `.meta.json` do golden mostram `"last_value": null`) — um campo novo aparece em todos os metas.

**Estado esperado depois:**
- Novo campo ao final da classe:
  ```python
  captured_value: Optional[str] = None
  ```
- `Optional` já importado em `models/session.py:2`.
- Nenhum outro código muda (o campo é opcional; tudo que constrói `Extractor` hoje continua válido).
- ⚠️ Posicionar **após** `ever_changed` para manter a ordem atual dos campos no JSON (os `.meta.json` existentes preservam a ordem dos campos anteriores).

**Critérios de aceite:**
- [x] `test_extractor_serializes_captured_value_field`: `Extractor(token_id="t1", code="...", agent_type=AgentType.REGEX).model_dump_json()` contém `"captured_value": null`.
- [x] `test_extractor_round_trips_captured_value`: criar `Extractor` com `captured_value="x"`, `save`/`load` via `ExtractorMetadataStore` (padrão de `test_save_then_load_round_trips_extractor`), e `loaded.captured_value == "x"`.
- [x] Não-regressão: `test_save_then_load_round_trips_extractor` e demais testes de `tests/unit/test_extractor_metadata_store.py` seguem verdes (construtor sem o novo campo continua válido).

## [T05] — `CandidateResolver`: setar `captured_value` na geração e backfill no reuse

**Depende de:** T04 (o campo `Extractor.captured_value` precisa existir).
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (`_register_extractor`, `_accept_persisted_slot`), `tests/unit/test_candidate_resolver.py`

**Contexto:**
O `captured_value` precisa ser gravado no momento em que o extrator é criado/reusado
(spec §3.1). Hoje `_register_extractor` gera o extrator e o salva sem o valor
capturado; `_accept_persisted_slot` reusa um slot persistido (workspace anterior ao
fix) sem preencher o valor.

**Estado atual:**
- `_register_extractor` (`candidate_resolver.py:145-157`): gera `new_extractor`, registra no `session_store.state.registry` e salva via `metadata_store.save(new_extractor)`.
- `_accept_persisted_slot` (`candidate_resolver.py:115-118`): registra `persisted` no registry, seta o token e guarda no cache `_validated_values` — não grava de volta no store.

**Estado esperado depois:**
- Em `_register_extractor`, após gerar `new_extractor` e antes do `save`:
  ```python
  new_extractor.captured_value = candidate.current_value
  ```
- Em `_accept_persisted_slot`, backfill quando `None` (workspace anterior ao fix):
  ```python
  if persisted.captured_value is None:
      persisted.captured_value = result
      self.metadata_store.save(persisted)
  ```
  (é o mesmo `result` já validado pelo `run_existing` — `candidate.current_value`).
- ⚠️ Não sobrescrever `captured_value` existente no backfill (só quando `None`).
- ⚠️ O `_register_extractor` continua salvando **uma** vez (o `save` existente) — só mudar o objeto antes.

**Critérios de aceite:**
- [x] `test_register_extractor_persists_captured_value`: via `_register_extractor` com um candidato `current_value="segredo"` (caminho literal, como em `_generate_extractor` com `origin_location=None`), `metadata_store.load(token_id).captured_value == "segredo"`.
- [x] `test_accept_persisted_slot_backfills_captured_value_when_none`: slot persistido com `captured_value=None`; `_check_persisted_slot` com `run_existing_result="v1"`; após `MATCH`, `metadata_store.load(slot).captured_value == "v1"`.
- [x] `test_accept_persisted_slot_keeps_existing_captured_value`: slot persistido com `captured_value="antigo"` e `run_existing_result="v1"`; após `MATCH`, `captured_value` continua `"antigo"` (não vira `"v1"`).
- [x] Não-regressão: `test_check_persisted_slot_matches_and_accepts_when_rerun_output_equals_candidate` continua passando; suíte completa verde.

## [T06] — `ReplayTokenResolver`: `TokenResolutionStatus` e fallback para o `captured_value`

**Depende de:** T04 (o campo `Extractor.captured_value` precisa existir).
**Arquivos envolvidos:** `har_reproducer/replay/replay_token_resolver.py` (`_resolve_one`, `resolve`, novo `_fallback_to_captured`), `har_reproducer/models/session.py` (novo enum), `tests/unit/test_replay_token_resolver.py`

**Contexto:**
Hoje `_resolve_one` devolve `bool` e `resolve` devolve `Set[str]` de tokens estáticos.
O runner precisa distinguir o desfecho do fallback (spec §3.2 e §3.4): o token que
caiu no fallback **não** é estático (não anota `probably static`) e precisa vir num
conjunto separado para a anotação do curl. O enum `TokenResolutionStatus` carrega esse
desfecho.

**Estado atual:**
- `_resolve_one` (`replay_token_resolver.py:41-60`) devolve `bool`; quando `run_existing` devolve `None`, imprime o erro e retorna `False`.
- `resolve` (`:25-39`) agrega `static_token_ids` quando `_resolve_one` é `True`.
- O teste `test_resolve_one_returns_false_without_calling_record_observation_when_extractor_yields_none` (`test_replay_token_resolver.py:92-103`) espera `False`.

**Estado esperado depois:**
- Novo enum em `har_reproducer/models/session.py` (ao lado de `AgentType`/`TokenLocation`), exportado em `models/__init__.py`:
  ```python
  class TokenResolutionStatus(str, Enum):
      STATIC = "static"
      RESOLVED = "resolved"
      CAPTURED_FALLBACK = "captured_fallback"
      UNRESOLVED = "unresolved"
  ```
- `_resolve_one` devolve `TokenResolutionStatus`:
  - `value is None` → `self._fallback_to_captured(token_id)`.
  - valor extraído → `_record_observation` decide: `STATIC` se confirmou, senão `RESOLVED`.
- Método novo:
  ```python
  def _fallback_to_captured(self, token_id: str) -> TokenResolutionStatus:
      persisted: Optional[Extractor] = self.metadata_store.load(token_id)
      if persisted is not None and persisted.captured_value is not None:
          self.session_store.set_token(token_id, persisted.captured_value)
          print(
              f"Token '{token_id}' could not be dynamically resolved during replay; "
              f"using captured value instead."
          )
          return TokenResolutionStatus.CAPTURED_FALLBACK
      print(
          f"Failed to resolve token '{token_id}' during replay: "
          f"extractor returned no value and no captured value is available."
      )
      return TokenResolutionStatus.UNRESOLVED
  ```
- `resolve` passa a devolver `Tuple[Set[str], Set[str]]` — `(static_token_ids, fallback_token_ids)`:
  ```python
  status: TokenResolutionStatus = self._resolve_one(...)
  if status is TokenResolutionStatus.STATIC:
      static_token_ids.add(token_id)
  elif status is TokenResolutionStatus.CAPTURED_FALLBACK:
      fallback_token_ids.add(token_id)
  ```
- `_fallback_to_captured` **não** chama `_record_observation` (o maquinário `valid_count`/`last_value`/`ever_changed` fica intocado).
- A mensagem de falha total mantém o prefixo `Failed to resolve token '<id>' during replay:` (contrato de `tests/support/token_failure_guard.py:7`).
- ⚠️ Os chamadores de `resolve` precisam acompanhar a nova assinatura: `ReplayRunner._run_step` (`replay_runner.py:83`) e o `FakeReplayTokenResolver` em `test_replay_runner.py:18-31`.

**Critérios de aceite:**
- [x] `test_fallback_to_captured_uses_captured_value_when_extractor_yields_none`: metadata com `Extractor(captured_value="capturado")`, `run_existing_result=None`; `_resolve_one` retorna `TokenResolutionStatus.CAPTURED_FALLBACK` e `session_store.state.tokens["t1"] == "capturado"`.
- [x] `test_fallback_to_captured_does_not_record_observation`: mesmo cenário; `metadata_store.saved` fica intocado (nenhum `save` de observação) e `valid_count` não muda.
- [x] `test_fallback_to_captured_unresolved_without_captured_value`: metadata vazia, `run_existing_result=None`; retorna `TokenResolutionStatus.UNRESOLVED`; mensagem começa com `Failed to resolve token`.
- [x] `test_resolve_returns_static_and_fallback_sets`: token `a` confirmado estático (via `_record_observation`) → entra em `static`; token `b` com fallback → entra em `fallback`; `resolve` retorna `({a}, {b})`.
- [x] Atualizar `test_resolve_one_returns_false_without_calling_record_observation_when_extractor_yields_none` para o novo retorno `TokenResolutionStatus.UNRESOLVED` (metadata vazia).
- [x] Não-regressão: `_record_observation` continua devolvendo `bool` e os testes de threshold/ever_changed seguem verdes.

## [T07] — `ReplayResultComparator`: expor `original_status_code`

**Depende de:** Nenhuma (Contexto de pré-requisito).
**Arquivos envolvidos:** `har_reproducer/replay/replay_result_comparator.py`, `tests/unit/test_replay_result_comparator.py`

**Contexto:**
O reporte por step (spec §3.3) precisa mostrar o status original ao lado do status do
replay (`Step 4: ✓ matched (200 vs original 200)`). Hoje o parse do status original
vive dentro de `matches_original` (`replay_result_comparator.py:15-24`), que devolve
só `bool`.

**Estado atual:**
- `matches_original` (`:15-24`) lê a referência via `_read_reference_text` (`:26-36`), extrai `"status_code"` com `STATUS_CODE_PATTERN` (`:10`) e compara com `response.status_code`; devolve `False` quando não há referência ou status.

**Estado esperado depois:**
- Método novo que expõe o status original sem repetir o parse:
  ```python
  def original_status_code(self, index: int) -> Optional[int]:
      original_text: Optional[str] = self._read_reference_text(index)
      if original_text is None:
          return None
      match: Optional[Match[str]] = self.STATUS_CODE_PATTERN.search(original_text)
      if match is None:
          return None
      return int(match.group(1))
  ```
- `matches_original` delega para ele:
  ```python
  def matches_original(self, index: int, response: StepResponse) -> bool:
      original: Optional[int] = self.original_status_code(index)
      if original is None:
          print(f"Could not find status_code in original response for step {index} to compare.")
          return False
      return original == response.status_code
  ```
- ⚠️ Manter a mesma semântica de `bool` e as mesmas mensagens — os testes existentes de `test_replay_result_comparator.py` seguem verdes.

**Critérios de aceite:**
- [x] `test_original_status_code_returns_int_when_reference_has_status`: `workspace.response_file(0)` com `{"status_code": 200}`; `original_status_code(0) == 200`.
- [x] `test_original_status_code_returns_none_without_reference`: sem `real_responses/`/`original_responses/`; `original_status_code(2) is None`.
- [x] `test_original_status_code_returns_none_when_reference_has_no_status`: `workspace.response_file(0)` com `{}`; `original_status_code(0) is None`.
- [x] Não-regressão: os 5 testes existentes de `test_replay_result_comparator.py` passam sem alteração.

## [T08] — `ReplayRunner`: generalizar `_mark_token_static` → `_mark_token` e anotar o fallback no curl

**Depende de:** T06 (`resolve` devolve `(static, fallback)`).
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py` (`_run_step`, `_annotate_static_tokens`, `_mark_token_static`), `tests/unit/test_replay_runner.py`

**Contexto:**
Spec §3.4 — quando um token cai no fallback, o comentário do extrator no `.curl.sh`
em disco ganha o sufixo ` - could not extract value from response, using captured
value`. Hoje só existe anotação para tokens estáticos (`STATIC_WARNING_SUFFIX =
" - probably static"`, `replay_runner.py:18`) via `_mark_token_static`
(`:113-121`).

**Estado atual:**
- `_run_step` (`:79-102`): `static_token_ids = self.replay_token_resolver.resolve(...)`; se não-vazio, `_annotate_static_tokens(index, static_token_ids)`.
- `_annotate_static_tokens` (`:104-111`) chama `_mark_token_static(updated, token_id)`.
- `_mark_token_static` (`:113-121`) é `@classmethod`, anexa `STATIC_WARNING_SUFFIX` à linha do token, idempotente (não duplica se já termina com o sufixo).

**Estado esperado depois:**
- `_mark_token_static` vira `_mark_token(text, token_id, suffix)`:
  ```python
  @classmethod
  def _mark_token(cls, text: str, token_id: str, suffix: str) -> str:
      prefix: str = f"# Token {token_id} comes from response of step "
      lines: List[str] = text.splitlines()
      for i, line in enumerate(lines):
          if line.startswith(prefix) and not line.endswith(suffix):
              lines[i] = line + suffix
              break
      return "\n".join(lines) + "\n"
  ```
- Nova constante ao lado de `STATIC_WARNING_SUFFIX`:
  ```python
  CAPTURED_FALLBACK_SUFFIX: ClassVar[str] = " - could not extract value from response, using captured value"
  ```
- `_annotate_static_tokens` chama `_mark_token(updated, token_id, cls.STATIC_WARNING_SUFFIX)`; novo método `_annotate_fallback_tokens(index, token_ids)` faz o mesmo com `CAPTURED_FALLBACK_SUFFIX`.
- `_run_step.attempt` passa a desempacotar e anotar os dois conjuntos:
  ```python
  static_token_ids: Set[str]
  fallback_token_ids: Set[str]
  static_token_ids, fallback_token_ids = self.replay_token_resolver.resolve(
      curl_text, schedule, self.replay_run_dir, self.res_refer_dir, self.original_responses_dir
  )
  if static_token_ids:
      self._annotate_static_tokens(index, static_token_ids)
  if fallback_token_ids:
      self._annotate_fallback_tokens(index, fallback_token_ids)
  ```
- ⚠️ O `FakeReplayTokenResolver` em `test_replay_runner.py:18-31` passa a devolver a tupla — adaptar o fake e os testes que o usam.

**Critérios de aceite:**
- [x] `test_mark_token_appends_suffix_once` (renomear de `test_mark_token_static_appends_suffix_once`): `_mark_token(text, "abc", CAPTURED_FALLBACK_SUFFIX)` anexa o sufixo; chamar de novo não duplica.
- [x] `test_mark_token_leaves_text_unchanged_for_absent_token` (renomeado): com um token que não existe no texto, retorna o texto inalterado.
- [x] `test_annotate_fallback_tokens_rewrites_file_only_when_text_changes`: padrão do `test_annotate_static_tokens_rewrites_file_only_when_text_changes` (`test_replay_runner.py:134-149`) mas com o novo sufixo.
- [x] `test_run_step_annotates_fallback_token_in_curl`: curl com `# Token abc comes from response of step 2`; fake devolve `fallback={"abc"}`; após `_run_step`, o `.curl.sh` em disco contém `CAPTURED_FALLBACK_SUFFIX` na linha do token.
- [x] Não-regressão: anotação estática continua funcionando (testes renomeados acima + `test_annotate_static_tokens_rewrites_file_only_when_text_changes`).

## [T09] — `ReplayRunner`: reporte por step e veredito híbrido no `_run_schedule`

**Depende de:** T07 (`original_status_code` para o reporte); T08 (`_run_step` com o desempacotamento novo, já que `_run_schedule` chama `_run_step`).
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py` (`_run_schedule`, novo `_print_step_report`), `tests/unit/test_replay_runner.py`

**Contexto:**
Spec §3.3 — o veredito atual compara só o último step (`replay_runner.py:62-77`) e
imprime `✓ SUCCESS`/`✗ MISMATCH`. O novo comportamento roda todos os steps, coleta
`(index, response, matched)` de cada um, imprime um bloco `Replay step results:` e
aplica o veredito híbrido: `✓ SUCCESS` **só se** o último step casar **e** nenhum
intermediário tiver `status_code == 0`.

**Estado atual:**
- `_run_schedule` (`:62-77`): loop roda `_run_step`, guarda só o último, e faz `matches_original(last_index, last_response)`.
- `test_run_schedule_raises_on_empty_schedule` (`test_replay_runner.py:108-113`) espera `ValueError("schedule vazio")`.

**Estado esperado depois:**
- `_run_schedule` coleta todos os resultados e aplica o híbrido:
  ```python
  results: List[Tuple[int, StepResponse, bool]] = []
  for index in ordered_indexes:
      response: StepResponse = self._run_step(index, schedule)
      results.append((index, response, self.comparator.matches_original(index, response)))

  self._print_step_report(results)

  target_index: int = results[-1][0]
  target_matched: bool = results[-1][2]
  intermediate_broken: bool = any(response.status_code == 0 for _, response, _ in results[:-1])
  is_match: bool = target_matched and not intermediate_broken
  failed_steps: List[int] = [index for index, _, matched in results if not matched]

  print(
      f"\nReplay Validation Result: {'✓ SUCCESS' if is_match else '✗ FAILURE'}"
      f"{' (step ' + str(target_index) + ' status code vs. original)' if is_match else ' (steps diverged: ' + ', '.join(str(s) for s in failed_steps) + ')'}"
  )
  return is_match
  ```
- Método novo `_print_step_report(results)` — imprime cada step em ordem de execução:
  ```
  Replay step results:
    Step 4: ✓ matched (200 vs original 200)
    Step 3: ✓ matched (200 vs original 200)
  ```
  Para mismatch, `✗ MISMATCH (status vs original X)`; quando `original_status_code` é `None`, exibir `original ?` (sem crash) e o step entra em `steps diverged`.
- ⚠️ A linha do veredito preserva o prefixo `Replay Validation Result: ✓ SUCCESS` / `✗ FAILURE` — é o que o `test_cli_replay.py` e os goldens `stdout.txt` comparam.
- ⚠️ Manter o `ValueError` do schedule vazio (primeira linha do método).

**Critérios de aceite:**
- [x] `test_run_schedule_hybrid_verdict_fails_when_intermediate_step_broken`: 2 steps; step 1 (intermediário) com `status 0`, step 2 casa com original; veredito `✗ FAILURE` e bloco `steps diverged`.
- [x] `test_run_schedule_hybrid_verdict_succeeds_with_soft_intermediate_mismatch`: step 1 com `404` vs original `200` (mismatch suave), step 2 casa; veredito `✓ SUCCESS`.
- [x] `test_run_schedule_hybrid_verdict_all_ok`: todos os steps casam; `✓ SUCCESS`.
- [x] `test_print_step_report_prints_each_step`: `_print_step_report` com `[(4, resp200, True), (3, resp200, True)]` imprime `Step 4: ✓ matched` e `Step 3: ✓ matched` na ordem.
- [x] Não-regressão: `test_run_schedule_raises_on_empty_schedule` e `test_run_step_persists_stub_transport_response` seguem verdes; `test_replay_ref_fallback` e demais goldens de replay continuam `✓ SUCCESS`.

## [T10] — Golden e `test_cli_replay`: atualizar asserts e regenerar goldens do item 9

**Depende de:** T04, T05, T06, T07, T08, T09 (comportamento novo no pipeline completo).
**Arquivos envolvidos:** `tests/test_cli_replay.py` (`test_replay_list_out_of_order`), `tests/golden/replay_list_out_of_order/`, todos os `tests/golden/*/extractors/*.meta.json` (88 no total)

**Contexto:**
Com o item 9 implementado, o cenário fora de ordem muda de sintoma: o step 4 deixa de
quebrar com `nested brace`/`status 0` e passa a casar via fallback com o valor
capturado (spec §5, caso 3). O veredito continua `✓ SUCCESS (step 3 status code vs.
original)` — preservando o prefixo que os testes comparam — mas o stdout ganha o
bloco `Replay step results:`, o warning do fallback e o `.meta.json`/curl anotado.

**Estado atual:**
- `test_replay_list_out_of_order` (`test_cli_replay.py:219-242`) espera:
  - `"Failed to resolve token 'ade6a53080262635799eb7ec66e824e8'" in result.stdout`
  - `"curl: (3) nested brace in URL position 30:" in result.stdout`
  - `"Step 4 completed with status 0" in result.stdout`
  - `"Replay Validation Result: ✓ SUCCESS (step 3 status code vs. original)" in result.stdout`
- `tests/golden/replay_list_out_of_order/stdout.txt` congela o sintoma antigo.
- Nenhum `.meta.json` do golden tem `captured_value`.

**Estado esperado depois:**
- `test_replay_list_out_of_order` passa a esperar o comportamento novo:
  - `"could not be dynamically resolved during replay; using captured value instead." in result.stdout`
  - `"curl: (3) nested brace" not in result.stdout` e `"Step 4 completed with status 0" not in result.stdout`
  - `"Step 4 completed with status 200" in result.stdout`
  - `"Replay step results:" in result.stdout` e `"Replay Validation Result: ✓ SUCCESS (step 3 status code vs. original)" in result.stdout`
  - mantém `executed_steps == [4, 3]`, `len(replay_run_dirs()) == 1`, `TokenFailureGuard().assert_at_most_one_failure_per_step`.
- Curl do step 4 no workspace: `curls/req_0004.curl.sh` contém `CAPTURED_FALLBACK_SUFFIX` na linha do token `ade6a...`.
- Regenerar goldens com `HAR_REPRODUCER_UPDATE_GOLDEN=1` (rodar `test_replay_list_out_of_order` e `test_run_main` com `--runslow`):
  - `tests/golden/replay_list_out_of_order/stdout.txt` ganha o bloco de steps e o warning do fallback.
  - Todos os `.meta.json` (88) ganham `"captured_value": ...` (alguns com `null` quando o valor nunca foi capturado, ex.: extractores literais que ainda não rodaram) — revisar o diff e confirmar que os valores correspondem ao HAR.
  - Curls de replays de `replay_list_out_of_order` ganham o sufixo de fallback quando aplicável.

**Critérios de aceite:**
- [x] `uv run pytest tests/test_cli_replay.py::test_replay_list_out_of_order --runslow -q` passa com os novos asserts.
- [x] Golden `replay_list_out_of_order` regenerado: `stdout.txt` contém `Replay step results:` e o warning `using captured value instead.`; `req_0004.curl.sh` tem o sufixo de fallback.
- [x] `grep -r '"captured_value"' tests/golden/ | wc -l` == 88 (todo `.meta.json` serializa o campo).
- [x] Não-regressão: `uv run pytest tests/ -q` (unidades) e `uv run pytest tests/ -q --runslow` (goldens de replay e run) passam; em particular `test_replay_ref_fallback`, `test_replay_all` e `test_run_main` continuam verdes.
