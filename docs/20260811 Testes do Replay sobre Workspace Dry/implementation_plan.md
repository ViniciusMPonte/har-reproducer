# Plano de Implementação — Testes do Replay sobre Workspace Dry

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.
>
> Todas as tasks são de teste: nenhum arquivo de `har_reproducer/` muda (restrição
> dura da spec §1) — os commits usam `test:` (exceto T05, `doc:`). Testes de
> caracterização de comportamento já correto passam no primeiro run (green
> imediato); a proteção é que qualquer regressão do item 2/8 os deixa vermelhos.

---

## [T01] — `dry_workspace` (conftest) + `test_run_dry_persists_extractor_scripts`: fixture do workspace `dry` e prova de que o `run --mode dry` grava os `.py` dos extractors

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/conftest.py` (nova fixture), `tests/test_cli_run.py` (novo teste; imports `json`).

**Contexto:**
Todo o cenário da lacuna (item 8) parte de um workspace que só rodou `run --mode dry`:
`.py` dos extractors gravados, `real_responses/` vazio, `original_responses/` populado.
Hoje a suíte só constrói workspace `dry` localmente dentro de cada `test_run_dry_*`
(`tests/test_cli_run.py`), sem nada compartilhável. Esta task cria a fixture
`dry_workspace` (reusada por T03) e, no mesmo commit, o teste fino 3.2 que a exercita
— sem um consumidor, a fixture não teria aceite verificável isolado (spec §3.3/§3.5).

**Estado atual:**
- `tests/conftest.py:39-65` tem `golden_dir`, `synthetic_flow_har` (materializa com
  `OFFLINE_PORT`), `minimal_flow_har`, `cli_invoker`, `golden_workspace_factory` —
  nenhum workspace `dry` compartilhado.
- `DryEngine._persist_response_step` é `no-op` (`har_reproducer/engines/dry_engine.py:14-15`)
  → `real_responses/` fica vazio; `_persist_original_response_step` popula
  `original_responses/` (`har_reproducer/engines/engine.py:93-97`).
- `Engine._process_entry` chama `self.token_resolver.resolve_all()` incondicionalmente
  (`engine.py:72-73`) — o gate do item 2; em dry, `TokenResolver._refresh_token`
  (`tracking/token_resolver.py:25-36`) chama `ExtractorRunner.run`, que grava o `.py`
  via `_write_extractor_script` (`reproduction/extractor_runner.py:33-44`).
- O golden `run_dry_default` já prova, por comparação de árvore, que o dry grava os
  `.py` — o teste fino apenas explicita a intenção e dá localização de falha imediata.

**Estado esperado depois:**
- Fixture `dry_workspace(cli_invoker: CliInvoker, synthetic_flow_har: Path, tmp_path: Path) -> Path`
  em `tests/conftest.py`:
  - invoca `["run", "--har", str(synthetic_flow_har), "--mode", "dry", "--output", str(tmp_path / "dry_ws")]`;
  - se `result.exception is not None`, `raise RuntimeError` com stdout/stderr (mesmo
    padrão de `main_workspace`, `tests/test_cli_replay.py:46-47`);
  - retorna `tmp_path / "dry_ws"`.
  - ⚠️ Função-escopo (default do pytest): `_record_observation` do replay muta os
    `.meta.json` (`valid_count`, `last_value`) — cada teste precisa de um `dry` fresco.
    Não tornar session-scoped.
  - ⚠️ O HAR usa `OFFLINE_PORT` (19999) — sem rede é irrelevante; o golden slow (T04)
    usa fixture própria na porta do canned server.
- Novo teste `test_run_dry_persists_extractor_scripts(dry_workspace: Path)` em
  `tests/test_cli_run.py`:
  - asserta que existe pelo menos um `extractors/extract_*.meta.json`;
  - para cada `extractors/extract_<token_id>.meta.json`, asserta que
    `extractors/extract_<token_id>.py` existe (extrair `token_id` via `json.loads` do
    meta, ou derivar do nome do arquivo).

**Critérios de aceite:**
- [x] `uv run pytest tests/test_cli_run.py::test_run_dry_persists_extractor_scripts -q` passa e verifica um `.py` para cada `.meta.json` do workspace `dry`.
- [x] A fixture segue o padrão `raise RuntimeError` de `main_workspace` para falha do dry (checagem por inspeção; o caminho feliz é o teste acima).
- [x] Não-regressão: `uv run pytest tests/test_cli_run.py -q` passa (os `test_run_dry_*` existentes seguem verdes).
- [x] `git diff` não toca em `har_reproducer/`.

---

## [T02] — `ReplayTokenResolver._resolve_one`: origem fora do schedule entrega `original_responses_dir` como override ao runner

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_replay_token_resolver.py` (novo teste; import de `RecordedRunCall`).

**Contexto:**
A tabela da lacuna §2 aponta que os testes puros de `_reference_dir_for_step`
(`test_replay_token_resolver.py:15-42`) não provam que o diretório escolhido **chega
ao `ExtractorRunner`** via `response_override_dir` — é o elo de decisão do fallback
(spec §3.1). Comportamento já correto em produção: teste de caracterização (green
imediato) que fica vermelho se o fallback para `original_responses/` quebrar.

**Estado atual:**
- `_resolve_one` (`har_reproducer/replay/replay_token_resolver.py:47-67`): origem no
  schedule → `replay_run_dir`; fora → `_reference_dir_for_step`; depois
  `self.extractor_runner.run_existing(token_id, override_dir)`.
- `FakeExtractorRunner` registra `run_existing_calls: List[RecordedRunCall(token_id, response_override_dir)]`
  (`tests/support/fake_extractor_runner.py:7-30`).
- O arquivo já importa `FakeExtractorRunner` e tem o helper `_resolver(runner, metadata_store)`
  (`test_replay_token_resolver.py:14-15`); falta importar `RecordedRunCall`.

**Estado esperado depois:**
- Novo teste `test_resolve_one_passes_original_dir_as_override_when_origin_outside_schedule`:
  ```python
  extractor_runner: FakeExtractorRunner = FakeExtractorRunner(run_existing_result="v")
  resolver: ReplayTokenResolver = _resolver(extractor_runner, FakeMetadataStore())
  status: TokenResolutionStatus = resolver._resolve_one(
      "t1", {"t1": 3}, schedule={4}, replay_run_dir=Path("/replay"),
      res_refer_dir=Path("/refer"), original_responses_dir=Path("/original"),
  )
  assert status == TokenResolutionStatus.RESOLVED
  assert extractor_runner.run_existing_calls == [RecordedRunCall("t1", Path("/original"))]
  ```
- ⚠️ Pré-condição do cenário: `Path("/refer")` não existe em disco (paths simbólicos),
  então `_reference_dir_for_step` cai em `/original` — espelha o workspace `dry` com
  `real_responses/` vazio.
- ⚠️ Usar o helper `_resolver` existente e `FakeMetadataStore` vazio (o valor "v"
  resolve → `_record_observation` retorna `False` com metadata vazio → `RESOLVED`).

**Critérios de aceite:**
- [x] O teste passa (green imediato — comportamento atual já é o correto).
- [x] `run_existing_calls == [RecordedRunCall("t1", Path("/original"))]` prova que o override entregue foi `original_responses_dir`.
- [x] Não-regressão: `uv run pytest tests/unit/test_replay_token_resolver.py -q` passa (demais testes do arquivo intactos).

---

## [T03] — `ReplayTokenResolver` (caminho real): resolução dos tokens do step 4 em workspace `dry` via `original_responses/`, sem rede

**Depende de:** T01 (usa a fixture `dry_workspace`).
**Arquivos envolvidos:** `tests/unit/test_replay_dry_resolution.py` (novo).

**Contexto:**
Núcleo da lacuna §3.1: provar offline que os tokens de um workspace `dry` real
resolvem lendo `original_responses/`, passando por `ExtractorRunner.run_existing` real
→ `ScriptExecutor` (subprocess `sys.executable`) → script do extrator com
`HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR` apontando para `original_responses/` (spec §3.2).
É o elo "execução": enquanto T02 prova a decisão, este prova que o `.py` existe e o
script roda e extrai o valor.

**Estado atual:**
- `run_existing` retorna `None` se o `.py` não existe (`har_reproducer/reproduction/extractor_runner.py:23-31`);
  `_build_env` seta `HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR` (`extractor_runner.py:71-76`).
- `_reference_dir_for_step` cai para `original_responses_dir` quando
  `real_responses/res_<origin>.json` não existe (`replay_token_resolver.py:84-94`).
- `curls/req_0004.curl.sh` do workspace `dry` tem os tokens
  `ade6a53080262635799eb7ec66e824e8` (origem 3) e `f04743b512e6241375b3226e7f7c69d3`
  (origem 0) — ambos fora do schedule `{4}`. Os scripts de extrator retornam `4242` e
  `scr_NONCE_2` contra `original_responses/` (verificado manualmente).
- `ScriptExecutor.run` roda `[sys.executable, script]` com timeout, sem rede
  (`har_reproducer/reproduction/script_executor.py:13-37`).

**Estado esperado depois:**
- Novo arquivo `tests/unit/test_replay_dry_resolution.py` com um teste:
  ```python
  resolver: ReplayTokenResolver = ReplayTokenResolver(
      SessionStore(),
      ExtractorRunner(Workspace(dry_workspace), ScriptExecutor()),
      CurlDependencyParser(),
      ExtractorMetadataStore(Workspace(dry_workspace)),
  )
  curl_text: str = (dry_workspace / "curls" / "req_0004.curl.sh").read_text(encoding="utf-8")
  static_ids: Set[str]
  fallback_ids: Set[str]
  static_ids, fallback_ids = resolver.resolve(
      curl_text, schedule={4}, replay_run_dir=tmp_path / "replay",
      res_refer_dir=dry_workspace / "real_responses",
      original_responses_dir=dry_workspace / "original_responses",
  )
  assert resolver.session_store.state.tokens == {
      "ade6a53080262635799eb7ec66e824e8": "4242",
      "f04743b512e6241375b3226e7f7c69d3": "scr_NONCE_2",
  }
  assert static_ids == set()
  assert fallback_ids == set()
  ```
- Asserts de pré-condição no teste: `list((dry_workspace / "real_responses").glob("res_*.json")) == []`
  (o valor só pôde vir de `original_responses/`); `CurlDependencyParser().parse(curl_text)`
  com todas as origens fora de `{4}`.
- ⚠️ `_record_observation` muta os `.meta.json` da cópia (incrementa `valid_count` para
  1, seta `last_value`) — a fixture função-escopo isola; não assertar `valid_count`.
- ⚠️ `Workspace(dry_workspace)` é reentrante (`har_reproducer/fs_io/workspace.py:9-10`,
  `mkdir(exist_ok=True)`) — instanciar sobre o dir já criado pelo dry é ok.
- ⚠️ Teste offline e rápido (subprocess `python` em scripts locais); não marcar `slow`.

**Critérios de aceite:**
- [x] `uv run pytest tests/unit/test_replay_dry_resolution.py -q` passa.
- [x] `session_store.state.tokens` tem exatamente `{"ade6a53080262635799eb7ec66e824e8": "4242", "f04743b512e6241375b3226e7f7c69d3": "scr_NONCE_2"}`.
- [x] Pré-condições assertadas no teste: `real_responses/` vazio; origens do curl fora do schedule.
- [x] Não-regressão: rodada padrão offline `uv run pytest -q` (sem `--runslow`) continua passando.

---

## [T04] — `ReplayRunner`: golden `slow` de replay ponta a ponta sobre workspace `dry`

**Depende de:** Nenhuma (fixture própria session-scope, na porta do canned server; não usa a `dry_workspace` do conftest).
**Arquivos envolvidos:** `tests/test_cli_replay.py` (fixture + teste), `tests/golden/replay_dry_ref_fallback/` (golden novo).

**Contexto:**
Cenário que reproduziria o item 8 se ele voltasse: replay `--mode list` de um único
step cujos tokens têm origem fora do schedule, sobre workspace `dry` (`real_responses/`
vazio), com o fallback para `original_responses/` resolvendo tudo e o curl real (via
proxy + `CannedHttpServer`) respondendo 200 (spec §3.4). Molde: `test_replay_ref_fallback`
(`tests/test_cli_replay.py:252-279`).

**Estado atual:**
- `main_workspace` (`test_cli_replay.py:33-49`) é fixture session-scope que roda
  `run --mode main` sobre HAR materializado com `canned_http_server.port`.
- Replay não escreve `real_requests/` — `CurlHttpTransport.send_request` lê a captura
  do mitmproxy (`har_reproducer/reproduction/curl_http_transport.py:37-43`); os
  `real_requests/` do golden vêm da cópia do workspace de origem.
- O golden de replay registra `replays/<RUN_ID>/res_*.json`, `curls/` (anotações de
  token), `extractors/*.meta.json` (mutado por `_record_observation`).

**Estado esperado depois:**
- Fixture session-scope `dry_workspace_network(canned_http_server: CannedHttpServer, network_session_dir: Path) -> Path`:
  - materializa `synthetic_flow.har` com `canned_http_server.port` (os curls do replay
    precisam apontar para o servidor canário);
  - roda `run --mode dry --output <network_session_dir>/dry_ws` via `CliInvoker()`;
  - `raise RuntimeError` se falhar (padrão de `main_workspace`).
- Teste `@pytest.mark.slow test_replay_dry_ref_fallback(cli_invoker, dry_workspace_network, golden_workspace_factory, golden_dir, tmp_path)`:
  - `ReplayScenario(cli_invoker, dry_workspace_network, tmp_path)`;
  - `steps.txt` com `4`; `scenario.run(["--mode", "list", "--steps-file", str(steps_file)])`;
  - asserts: `result.exception is None`; `"Failed to resolve" not in result.stdout`;
    `"using captured value" not in result.stdout`;
    `"Step 4 completed with status 200" in result.stdout`;
    `"Replay Validation Result: ✓ SUCCESS" in result.stdout`;
    `scenario.executed_steps(result.stdout) == [4]`; `len(scenario.replay_run_dirs()) == 1`;
    `TokenFailureGuard().assert_at_most_one_failure_per_step(result.stdout)`;
  - grava `stdout.txt` na cópia e compara golden:
    `golden_workspace_factory.create(scenario.workspace).assert_matches(golden_dir / "replay_dry_ref_fallback")`.
- Golden novo gravado com `HAR_REPRODUCER_UPDATE_GOLDEN=1 uv run pytest tests/test_cli_replay.py::test_replay_dry_ref_fallback --runslow`.
- ⚠️ Determinismo do golden: os `.meta.json` da cópia ganham `valid_count: 1` e
  `last_value` após resolver os 2 tokens do step 4 — valores fixos; `replays/<RUN_ID>`
  e a porta são normalizados por `GoldenNormalizer` (`tests/support/golden_normalizer.py:8-28`).
- ⚠️ `ReplayScenario._rewrite_stale_absolute_paths` reescreve paths absolutos dos
  `.meta.json` (`tests/support/replay_scenario.py:39-47`); os `.py` dos extractors não
  têm path absoluto (`Path(__file__).resolve().parent.parent`), então a cópia funciona.

**Critérios de aceite:**
- [x] Fase vermelha: sem o golden gravado, o teste falha com `Apenas no workspace atual: ...` no `assert_matches`.
- [x] `HAR_REPRODUCER_UPDATE_GOLDEN=1 uv run pytest tests/test_cli_replay.py::test_replay_dry_ref_fallback --runslow` grava `tests/golden/replay_dry_ref_fallback/`.
- [x] `uv run pytest tests/test_cli_replay.py::test_replay_dry_ref_fallback --runslow` passa (verde) sem o env de update.
- [x] stdout do replay: nenhuma linha `Failed to resolve token`; `Step 4 completed with status 200`; `✓ SUCCESS`.
- [x] Não-regressão: `uv run pytest --runslow -q` passa (goldens de rede existentes intactos).

---

## [T05] — `lacunas_de_testes.md`: marca o cenário como coberto

**Depende de:** T01, T02, T03, T04 (os testes já existem quando o inventário fecha).
**Arquivos envolvidos:** `docs/20260810 Correções de Defeitos Catalogados/lacunas_de_testes.md`.

**Contexto:**
O documento se declara "inventário para uma etapa futura de testes" (§1). Com os
testes implementados (T01–T04), fechar a lacuna — precedente no repo de etapa
posterior fechando inventário de etapa anterior (`99b468e`, `8074cbd`; spec §3.6).

**Estado atual:**
- `lacunas_de_testes.md` descreve o cenário sem cobertura (item 8) e propõe §3.1/3.2/3.3.

**Estado esperado depois:**
- Nota de fechamento no topo (logo após o blockquote das linhas 3-6) indicando a etapa
  que implementou a cobertura (`docs/20260811 Testes do Replay sobre Workspace Dry/`)
  e onde estão os testes (arquivos e nomes); os itens da seção 3 passam a status
  "implementado".
- Não apagar a §4 (procedimento manual) nem a §5 (referências) — o documento continua
  valendo como referência do cenário.

**Critérios de aceite:**
- [x] O documento indica de forma explícita que o cenário está coberto e onde estão os testes.
- [x] Nenhuma alteração além deste arquivo neste commit (`git diff --stat` só mostra o `lacunas_de_testes.md`).
