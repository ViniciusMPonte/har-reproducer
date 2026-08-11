# Etapa — Testes do Replay sobre Workspace Dry

## 1. Objetivo

Fechar a lacuna de teste inventariada em
`docs/20260810 Correções de Defeitos Catalogados/lacunas_de_testes.md`: **nenhum teste
cobre o cenário `replay` sobre um workspace que só rodou `run --mode dry`**, no qual
tokens dinâmicos cuja origem está fora do schedule resolvem lendo a resposta de
`original_responses/`.

O item 8 da `lista_de_bugs.md` deixou de existir **como bug** — o fix do item 2
(`4d5869f`) fez `TokenResolver.resolve_all()` rodar em `dry` (`engines/engine.py:72-73`),
o que passa a gravar o `.py` do extrator e reabilita o fallback do README para
`original_responses/`. Mas o cenário **não tem teste**: se o item 2 regredir (o `.py`
deixar de ser gravado em `dry`), o item 8 volta silenciosamente — `run_existing`
(`reproduction/extractor_runner.py:23-31`) retorna `None` antes de usar o
`response_override_dir`, e o replay emite `Failed to resolve token` para todos os
steps. Nada na suíte atual pega essa regressão.

Esta etapa implementa os três cenários propostos na lacuna (§3.1, §3.2, §3.3),
com a análise de viabilidade abaixo.

### 1.1 Veredito de viabilidade

**Viável, sem nenhuma mudança em `har_reproducer/`.** Os três cenários se apoiam em
código que já existe e é exercitável offline (para os dois unitários) ou com a mesma
infra `slow` já usada pelos demais golden de replay. Nenhum seam novo de produção é
necessário.

| Cenário (lacuna) | Nível | Rede? | Base | Verificado como |
|---|---|---|---|---|
| 3.1 — resolução de token em workspace `dry` via `original_responses/` | unitário | não | real (`ScriptExecutor` executa o `.py` do extrator) + fake | execução manual dos `.py` contra `original_responses/` (retorna `4242` e `scr_NONCE_2`) |
| 3.2 — `dry` grava o `.py` do extrator | unitário (CLI) | não | `run --mode dry` real via `CliInvoker` | golden `run_dry_default` já pina os `.py` por comparação de árvore; o teste fino deixa a intenção explícita |
| 3.3 — replay de ponta a ponta sobre workspace `dry` | golden `slow` | sim (proxy + servidor canário) | mesmo molde de `test_replay_ref_fallback` | `CannedHttpServer` serve `/item/4242` → `200`; tokens resolvem de `original_responses/` |

O fluxo inteiro do cenário já foi validado manualmente pela própria lacuna (seção 4):
`dry` grava os `.py`, `real_responses/` fica vazio, `original_responses/` fica
populado, e o replay de um step com origem fora do schedule resolve sem
`Failed to resolve token`. Confirmamos também que os scripts de extrator do golden
`run_dry_default` executam offline com `HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR`
apontando para `original_responses/` — a mesma mecânica que `ExtractorRunner._build_env`
(`reproduction/extractor_runner.py:71-76`) aciona no replay.

### Fora de escopo

- **Nenhum arquivo dentro de `har_reproducer/` muda** (restrição dura, mesmo padrão da
  etapa `20260809 Unitários Finos`). Se algum teste revelar a necessidade de um seam
  de produção, o alvo sai de escopo e vira assunto de outra spec.
- Não corrigir outros itens da `lista_de_bugs.md` (1, 3, 4, 5, 6, 9, 10) — esta etapa
  é só cobertura do cenário do item 8.
- Não mudar comportamento de produção nem o `README.md`.
- Não adicionar testes para os modos `all`/`slice`/`smart` sobre workspace `dry` — a
  lacuna pede só o `list`; os outros modos são combinações do mesmo fallback já
  cobertas pelo cenário escolhido.

## 2. Componentes existentes reaproveitados

- **`ExtractorRunner.run_existing`** (`har_reproducer/reproduction/extractor_runner.py:23-31`)
  — retorna `None` se `workspace.extractor_file(token_id)` não existe (o sintoma do
  item 8), senão executa o script com o `response_override_dir`; é o ponto onde a
  resolução do replay decide entre `None` (fallback para captured) e o valor extraído.
- **`ExtractorRunner._build_env`** (`extractor_runner.py:71-76`) — seta
  `HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR` a partir do `response_override_dir`. Os scripts
  gerados por `ExtractorTemplate.render_script` leem esse env para achar o
  `res_<origin>.json` (ex.: `tests/golden/run_dry_default/extractors/extract_ade6a...py:23-29`).
  É isso que torna o cenário 3.1 testável offline: `ScriptExecutor` (`script_executor.py:13-37`)
  roda `sys.executable` no script, sem rede.
- **`ReplayTokenResolver.resolve` / `_resolve_one`** (`har_reproducer/replay/replay_token_resolver.py:25-67`)
  — orquestra a resolução por token: origem no schedule → `replay_run_dir`; fora do
  schedule → `_reference_dir_for_step`.
- **`ReplayTokenResolver._reference_dir_for_step`** (`replay_token_resolver.py:84-94`)
  — devolve `res_refer_dir` quando `res_<origin>.json` existe ali, senão cai em
  `original_responses_dir`. É a decisão que o teste 3.1(a) precisa pinar com o
  `response_override_dir` registrado no dublê.
- **`Engine._process_entry`** (`har_reproducer/engines/engine.py:72-73`) — o gate do
  item 2: `self.token_resolver.resolve_all()` roda **incondicionalmente** (main e dry).
  `TokenResolver._refresh_token` (`tracking/token_resolver.py:25-36`) chama
  `ExtractorRunner.run`, que grava o `.py` via `_write_extractor_script`
  (`extractor_runner.py:33-44`). Em dry, `tracking_responses_dir` é
  `original_responses` (`engines/construction/engine_factory.py:61-63`).
- **`DryEngine`** (`har_reproducer/engines/dry_engine.py:7-15`) — `USES_NETWORK=False`
  (sem proxy), `execute_step` devolve a resposta do HAR, `_persist_response_step` é
  `no-op` → **`real_responses/` fica vazio** e `original_responses/` populado. É a
  pré-condição do cenário.
- **`Workspace`** (`har_reproducer/fs_io/workspace.py:12-19`) — materializa os 8
  subdiretórios; `real_responses` vs `original_responses` são os dois diretórios
  envolvidos no fallback.
- **`CliHandlers.handle_replay` / `_build_replay_runner`** (`har_reproducer/cli/cli_handlers.py:107-179`)
  — `res_refer_dir = response_reference_dir or workspace.real_responses`
  (`cli_handlers.py:139-143`); sem config, aponta para o `real_responses` **vazio** do
  workspace dry — o replay cai para `original_responses_dir` repassado por
  `workspace.original_responses` (`cli_handlers.py:178`).
- **`ReplayRunner._run_schedule` / `_run_step`** (`har_reproducer/replay/replay_runner.py:63-121`)
  — escreve `replays/<RUN_ID>/res_<index>.json`, imprime `Step N completed with status
  X` e o veredito; base para os asserts do 3.3.
- **`CurlDependencyParser`** (`har_reproducer/replay/curl_dependency_parser.py:12-16`)
  — parseia os comentários `# Token <id> comes from response of step <n>` dos curls;
  usado real no 3.1(b) para saber a origem de cada token.
- **`SessionStore`** (`har_reproducer/session/session_store.py:11-26`) — real nos
  testes; `state.tokens` é onde o 3.1(b) asserta os valores resolvidos.
- **Infra de teste existente**: `CliInvoker` (invoca `main()` in-process),
  `HarMaterializer` (substitui `__PORT__`), `CannedHttpServer`/`CannedHttpHandler`
  (servidor local que responde `/item/4242` com 200), `ReplayScenario` (copia o
  workspace e reescreve paths absolutos nos `.meta.json`), `GoldenWorkspaceFactory`,
  `FakeExtractorRunner` (registra `run_existing_calls` com o `response_override_dir`),
  fixtures `synthetic_flow_har`/`golden_dir`/`cli_invoker`/`golden_workspace_factory`
  (`tests/conftest.py:39-65`).
- **Cobertura atual que deixa a lacuna aberta** (referência da tabela da lacuna §2):
  `test_replay_token_resolver.py:15-42` cobre `_reference_dir_for_step` como função
  pura; `:92-103` cobre `_resolve_one` no caminho de falha com fake; `test_extractor_runner.py:22-29`
  prova que `run_existing` devolve `None` sem `.py`; o golden `replay_ref_fallback`
  (`test_cli_replay.py:245-272`) é sobre workspace **main**; os golden `run_dry_*` pinam
  o `run`, não o `replay` sobre ele.

## 3. Decisões de arquitetura

### 3.1 — 3.1(a): pinar a decisão de fallback com dublê (sem workspace real)

O gap mais barato de fechar: nenhum teste asserta que, para um token com origem fora
do schedule, `_resolve_one` entrega `original_responses_dir` como
`response_override_dir` ao runner. Um teste novo em `tests/unit/test_replay_token_resolver.py`
(estendendo o arquivo existente), no molde dos atuais:

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

Pré-condição do próprio teste: `Path("/refer")` não tem `res_0003.json`, então
`_reference_dir_for_step` cai em `/original`. Não exige `tmp_path` nem workspace.
Essa é a peça "decisão" que a tabela da lacuna §2 aponta como não coberta — os testes
puros de `_reference_dir_for_step` não provam que o valor escolhido **chega ao runner**.

### 3.2 — 3.1(b): caminho real offline — `ScriptExecutor` executa o `.py` contra `original_responses/`

O núcleo da lacuna: resolver tokens de um workspace `dry` **de verdade** (`.py` em
disco + `original_responses/` populado + `real_responses/` vazio), sem rede.

Nova fixture `dry_workspace` (função-escopo, em `tests/conftest.py`) que roda
`run --mode dry` sobre `synthetic_flow.har` via `CliInvoker` — mesmo jeito de
`test_cli_run.py:8-31`, offline e rápido (<1s, como os demais testes dry da suíte).

Novo arquivo `tests/unit/test_replay_dry_resolution.py` com o teste:

```python
resolver: ReplayTokenResolver = ReplayTokenResolver(
    SessionStore(),
    ExtractorRunner(Workspace(dry_workspace), ScriptExecutor()),
    CurlDependencyParser(),
    ExtractorMetadataStore(Workspace(dry_workspace)),
)
curl_text: str = (dry_workspace / "curls" / "req_0004.curl.sh").read_text(encoding="utf-8")
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

Razões da escolha por rodar `dry` de verdade (e não copiar o golden `run_dry_default/`):
(a) exercita o gate do item 2 (`engine.py:72-73`) de ponta a ponta — o cenário que
queremos proteger; (b) o golden tem conteúdo normalizado (`<WORKSPACE>`, `<PORT>`) e
não serve direto como workspace executável; (c) custo desprezível.
Alternativa descartada: `FakeExtractorRunner` aqui — esconderia justamente o que o
teste precisa provar (que o `.py` existe e o script roda).

Asserts de pré-condição dentro do teste: `real_responses/` vazio (garante que o valor
só pôde vir de `original_responses/`) e `dependencies` do curl com origem fora de
`{4}` (via `CurlDependencyParser`).

### 3.3 — 3.2: `dry` grava o `.py` do extrator (teste fino explícito)

Já há cobertura via golden (`tests/golden/run_dry_default/extractors/extract_*.py`
fazem parte da árvore comparada por `assert_matches`) — **honestidade: se o `.py`
deixasse de ser gravado, o golden `run_dry_default` já falharia**. O valor do teste
fino é explicitar a intenção e dar localização de falha imediata (qual token sem
`.py`), além de não depender da regeneração de golden.

Novo teste em `tests/test_cli_run.py`, reaproveitando a fixture `dry_workspace` do
conftest: para cada `extractors/extract_<id>.meta.json`, assertar que
`extractors/extract_<id>.py` existe. Não é um teste de engine com dublês — o caminho
`_process_entry → resolve_all → ExtractorRunner.run → _write_extractor_script` exige o
grafo inteiro do `EngineFactory`, que o `CliInvoker` monta de graça; recriar isso com
dublês em `test_engine.py` custaria mais e cobriria menos.

### 3.4 — 3.3: golden `slow` de ponta a ponta sobre workspace `dry`

Novo cenário `@pytest.mark.slow` em `tests/test_cli_replay.py`, análogo a
`test_replay_ref_fallback` (`test_cli_replay.py:245-272`):

1. Fixture session-escope `dry_workspace_network`: materializa `synthetic_flow.har`
   com `canned_http_server.port` (para os curls do replay apontarem para o servidor
   canário) e roda `run --mode dry --output <network_session_dir>/dry_ws`. `dry` não
   usa rede, então pode rodar com o servidor no ar.
2. `ReplayScenario(cli_invoker, dry_workspace_network, tmp_path)` + `steps.txt` com
   só `4` (cujos tokens vêm dos steps 3 e 0 — fora do schedule).
3. Asserts: sem `Failed to resolve token`; sem `could not be dynamically resolved`;
   `Step 4 completed with status 200`; `Replay Validation Result: ✓ SUCCESS`;
   `TokenFailureGuard().assert_at_most_one_failure_per_step`; golden da árvore em
   `tests/golden/replay_dry_ref_fallback/`.

Esse é o cenário que reproduziria o item 8 se ele voltasse. Determinismo do golden:
o replay resolve os dois tokens do step 4 uma vez, o que incrementa `valid_count`
para 1 e seta `last_value` nos `.meta.json` da cópia — valores fixos, capturáveis.

### 3.5 — Suporte novo: nada além do necessário

Mudanças em `tests/`:
- `tests/conftest.py`: nova fixture `dry_workspace` (função-escopo).
- `tests/unit/test_replay_token_resolver.py`: +1 teste (3.1a).
- `tests/unit/test_replay_dry_resolution.py`: novo arquivo (3.1b).
- `tests/test_cli_run.py`: +1 teste (3.2).
- `tests/test_cli_replay.py`: fixture `dry_workspace_network` + teste `slow` (3.3).
- `tests/golden/replay_dry_ref_fallback/`: golden novo (gravado com
  `HAR_REPRODUCER_UPDATE_GOLDEN=1 uv run pytest --runslow` durante a implementação).

Nenhum novo dublê em `tests/support/` é necessário: `FakeExtractorRunner` já registra
o `response_override_dir` (`tests/support/fake_extractor_runner.py:23-27`) e
`FakeMetadataStore` já serve para o 3.1(a). Se o 3.1(b) precisar do `Workspace` real
sobre o diretório já criado pelo dry, `Workspace(dry_workspace)` é reentrante
(`workspace.py:9-10`, `mkdir(exist_ok=True)`).

### 3.6 — Fechamento do inventário

Ao final, atualizar `docs/20260810 Correções de Defeitos Catalogados/lacunas_de_testes.md`
marcando o cenário como coberto (nota de fechamento na abertura e/ou checkboxes na
seção 3). O próprio documento se declara "inventário para uma etapa futura de testes"
(lacuna §1) — esta etapa é essa etapa, então fechá-lo é a conclusão natural, não um
extra. Precedente no repo de etapa posterior atualizando inventário de etapa anterior:
`99b468e` (`doc: definição de proximos passos`) reescreveu
`docs/20260629 Anotações/furutas_correcoes.md`, e `8074cbd` removeu
`docs/20260731 Ferramenta de Replay/anotações.md` (obsolescência) ao abrir a etapa
seguinte.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `tests/conftest.py` | + fixture `dry_workspace` (roda `run --mode dry` via `CliInvoker`, função-escopo) |
| `tests/unit/test_replay_token_resolver.py` | + teste 3.1(a): `_resolve_one` entrega `original_responses_dir` como override (fake registra `run_existing_calls`) |
| `tests/unit/test_replay_dry_resolution.py` | novo arquivo, teste 3.1(b): resolução real via `ScriptExecutor` em workspace `dry` |
| `tests/test_cli_run.py` | + teste 3.2: todo `.meta.json` de um `dry` tem seu `.py` |
| `tests/test_cli_replay.py` | + fixture `dry_workspace_network` (session) + teste `slow` 3.3 (golden) |
| `tests/golden/replay_dry_ref_fallback/` | golden novo da árvore do 3.3 |
| `har_reproducer/` | nenhuma mudança (restrição dura) |
| `docs/20260810 .../lacunas_de_testes.md` | fechamento do inventário (3.6) |

## 5. Casos de borda e comportamento de erro

- **Origem fora do schedule e `real_responses/` sem o arquivo** → `_reference_dir_for_step`
  devolve `original_responses_dir`; é o cenário-alvo. Se o `original_responses/`
  também não tiver o arquivo, `run_existing` roda o script contra um diretório sem o
  `res_<origin>.json` → script falha (exit ≠ 0) → `None` → fallback para
  `captured_value` (`replay_token_resolver.py:69-82`). O 3.3 asserta que isso **não**
  acontece (sem `Failed to resolve` / `using captured value`).
- **Regressão do item 2** (dry deixa de gravar `.py`): `run_existing` retorna `None`
  → tokens `UNRESOLVED` → `Failed to resolve token`. Detectar: 3.1(b) falha (tokens
  não resolvem), 3.2 falha (`.py` ausente), 3.3 falha (stdout). Limitação aceita:
  o sintoma aparece como falha de teste, não como diagnóstico nomeado — suficiente
  para a regressão.
- **`_record_observation` muta os `.meta.json`** (incrementa `valid_count`, seta
  `last_value`) durante o 3.1(b) e o 3.3. Fixture função-escopo isola o 3.1(b); no 3.3
  o replay roda sobre a cópia do `ReplayScenario`, e o golden captura os valores
  pós-resolução (determinísticos). Limitação aceita.
- **Porta do canned server vs porta materializada no HAR**: o 3.3 precisa que os curls
  apontem para a porta do servidor canário — por isso a fixture do 3.3 materializa o
  HAR com `canned_http_server.port`, como `main_workspace` já faz (`test_cli_replay.py:33-41`).
  O 3.1(b)/3.2 usam `OFFLINE_PORT` (sem rede, porta é irrelevante). Limitação aceita:
  dois fixtures de workspace `dry` com portas diferentes (função-escopo offline vs
  session-scope com rede).
- **`valid_count` cresce entre usos da mesma fixture**: função-escopo garante que cada
  teste roda um `dry` fresco; nenhum assert depende de `valid_count < 5` compartilhado.
  Se no futuro um teste resolver o mesmo token duas vezes na mesma fixture, `STATIC`
  não é atingido com `valid_count` inicial 0 (só no 5º valor igual) — sem interação.
- **Replay sobre workspace copiado**: `ReplayScenario` reescreve paths absolutos nos
  `.meta.json` (`tests/support/replay_scenario.py:39-47`); os `.py` dos extractors não
  têm path absoluto (`Path(__file__).resolve().parent.parent`), então a cópia funciona
  sem ajuste.

## 6. Suposições

Nenhuma decisão desta spec fica em aberto — as escolhas abaixo são decisões tomadas,
com a justificativa registrada.

- **Nome da etapa/pasta**: `20260811 Testes do Replay sobre Workspace Dry` / branch
  `20260811-testes-do-replay-sobre-workspace-dry` (já criados no Passo 0). Segue o
  padrão `AAAAMMDD Nome da Feature` do processo; a feature é o fechamento da lacuna.
- **3.2 é um teste CLI-level em `tests/test_cli_run.py`** (e não um unit de
  `test_engine.py` com dublês). Justificativa: o alvo real é o resultado observável
  "`.py` gravado", que só se prova com o grafo completo do `EngineFactory` — que o
  `CliInvoker` monta de graça; um teste de `_process_entry` com dublês exigiria um
  `FakeTracker` novo e provaria só "chamou `resolve_all()`", não "o `.py` existe".
- **3.1(a) estende `tests/unit/test_replay_token_resolver.py`** (arquivo existente)
  em vez de entrar no novo `test_replay_dry_resolution.py`. Justificativa: é o mesmo
  alvo (`ReplayTokenResolver`) com o mesmo estilo de dublê já usado no arquivo; o novo
  arquivo fica reservado ao caminho real com workspace.
- **Fechamento do inventário (3.6)**: atualizar `lacunas_de_testes.md` ao final —
  decidido (ver 3.6, com precedente no repo).
- **Golden do 3.3 gravado durante a implementação** com `HAR_REPRODUCER_UPDATE_GOLDEN=1
  uv run pytest --runslow` (pré-condição de ambiente: `mitmproxy` disponível, como os
  demais testes `slow`).
- Suíte atual como referência: `uv run pytest` → 220 passed, 11 skipped (offline);
  `uv run pytest --runslow` inclui os golden de rede.

## 7. Referência

Padrão de implementação obrigatório: `docs/20260724 Requisições via curl/guia_de_estilo.md`
(tipagem explícita, `ClassVar`, dublês como classes em `tests/support/`, nada solto no
módulo além de fixtures e funções `test_*`, sem comentários supérfluos). TDD na fase
vermelha sempre que houver comportamento a definir; testes novos devem passar na
rodada padrão (offline) salvo o 3.3 marcado `slow`.
