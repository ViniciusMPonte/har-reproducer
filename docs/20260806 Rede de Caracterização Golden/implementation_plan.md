# Plano de Implementação — Rede de Caracterização Golden

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## Estrutura em dois blocos, com checkpoint

- **Bloco A1 — offline (T01 a T09).** Fixtures, harness, e os 25 cenários que não
  usam rede, proxy nem porta livre.
- **CHECKPOINT** entre T09 e T10: a suíte de A1 é demonstrada rodando verde antes de
  qualquer task de A2 começar.
- **Bloco A2 — rede (T10 a T12).** Servidor falso, guarda do invariante, e os 11
  cenários de rede, todos marcados `slow`.

## Restrições que valem para todas as tasks

- **Nenhuma alteração fora de `tests/`** (spec §3.7). Nem `har_reproducer/`, nem
  `pyproject.toml`, nem `pytest.ini`. Se uma task parecer exigir isso, parar e
  reportar — a resposta certa é registrar a limitação, não relaxar a restrição.
- **Todo commit é `feat:`**, porque a etapa adiciona comportamento (testes) sem
  alterar comportamento de produção.
- Guia de estilo (`.claude/skills/guia-de-estilo/SKILL.md`) vale integralmente para
  `tests/support/`, que deve ser todo em classes com tipagem explícita, sem
  comentários e sem docstrings. Fixtures de `pytest` e funções `test_*` são a única
  exceção — são funções de módulo por exigência do framework.
- **Nenhum cenário reusa `--output`.** O modo `dry` não é idempotente (spec §6.2):
  uma segunda rodada no mesmo diretório dobra os extratores.

---

## [T01] — `synthetic_flow.har` / `minimal_flow.har`: as duas fixtures de HAR

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/fixtures/synthetic_flow.har` (novo), `tests/fixtures/minimal_flow.har` (novo)

**Contexto:**
Toda a rede golden se apoia em dois arquivos HAR commitados. O de 10 entries é o único
que exercita análise de token, skip e replay; o de 1 entry é o único que exercita
validação de `success_criteria` (spec §3.2 e §3.2.1). A divisão existe porque a fixture
principal paga `time.sleep(5)` por causa do defeito §6.1, e usá-la nos 8 cenários de
critério custaria ~45 s para testar algo sem relação com token.

**Estado atual:**
- Não existe diretório `tests/`.
- O HAR usado para validação manual vive fora do repositório, em `arquivos-har/`.

**Estado esperado depois:**

`synthetic_flow.har` — 10 entries, com o literal `__PORT__` no lugar da porta em toda
URL (a materialização com a porta real é responsabilidade de T05):

| # | Requisição | Resposta |
|---|---|---|
| 0 | `GET http://127.0.0.1:__PORT__/login`, header `Accept: text/html` | 200, headers `Content-Type: text/html` e `Set-Cookie: SESSIONID=abc123sess; Path=/`, cookie `SESSIONID=abc123sess`, corpo `<html><body><div id="marker">tok_CSS_1</div><script>var nonce = "scr_NONCE_2";</script></body></html>`, mime `text/html` |
| 1 | `OPTIONS wss://127.0.0.1:__PORT__/ws`, sem headers | 204, vazio |
| 2 | `OPTIONS http://127.0.0.1:__PORT__/api/do`, sem headers | 204, vazio |
| 3 | `POST http://127.0.0.1:__PORT__/api/do`, headers `Accept: text/html`, `Content-Type: application/json`, `X-Csrf: tok_CSS_1`, cookie `SESSIONID=abc123sess`, `postData.text` = `{"csrf": "tok_CSS_1"}` | 200, header `Content-Type: application/json`, corpo `{"id": 4242, "ok": true}`, mime `application/json` |
| 4 | `GET http://127.0.0.1:__PORT__/item/4242`, headers `Accept: text/html`, `X-Trace: 4242`, `nonce: scr_NONCE_2`, **sem cookie** | 200, `Content-Type: text/html`, corpo `<html><body><h1>item 4242</h1></body></html>` |
| 5 | `GET http://127.0.0.1:__PORT__/plain`, header `Accept: text/html` | 200, `Content-Type: text/plain`, corpo `PLAINVAL777`, mime `text/plain` |
| 6 | `GET http://127.0.0.1:__PORT__/use-plain`, headers `Accept: text/html`, `X-Plain: PLAINVAL777` | 200, `Content-Type: text/html`, corpo `<html><body>ok</body></html>` |
| 7 | `GET http://127.0.0.1:__PORT__/prefs`, header `Accept: text/html` | 200, `Content-Type: text/html`, **cookie `PREFS=xyz789` sem header `Set-Cookie`**, corpo `<html><body>prefs</body></html>` |
| 8 | `GET http://127.0.0.1:__PORT__/use-prefs`, header `Accept: text/html`, cookie `PREFS=xyz789` | 200, `Content-Type: text/html`, corpo `<html><body>ok</body></html>` |
| 9 | `POST http://127.0.0.1:__PORT__/submit`, headers `Accept: text/html`, `Content-Type: application/json`, `postData.text` = `{"a": 1}` | 200, `Content-Type: text/html`, corpo `<html><body>done</body></html>` |

Formato HAR: `{"log": {"version": "1.2", "entries": [...]}}`; cada entry tem
`request{method,url,headers[],cookies[]}` mais `postData{text}` quando houver, e
`response{status,headers[],cookies[],content{text,mimeType}}`. `headers` e `cookies`
são listas de `{"name":…,"value":…}`.

`minimal_flow.har` — 1 entry: `GET http://127.0.0.1:__PORT__/only`, header
`Accept: text/html`; resposta 200, `Content-Type: text/html`, corpo
`<html><body><div id="marker">pronto</div></body></html>`, mime `text/html`, e
`redirectUrl` = `http://127.0.0.1:__PORT__/done?ok=1`.

⚠️ **O par 7+8 é obrigatoriamente um par, e o par 5+6 também.** Um cookie só se torna
candidato quando uma requisição **posterior** o envia (`BaselineDiff._diff_cookies`,
`tracking/baseline_diff.py:31-37`), e `ResponseGrep._eligible_response_files`
(`tracking/response_grep.py:89`) só considera respostas de step **< o atual** — um
token com origem na última resposta nunca vira candidato.

⚠️ **O header da entry 4 tem que se chamar `nonce`, minúsculo, não `X-Nonce`.**
`RegexAgent._key_pattern` (`agents/regex_agent.py:20-24`) monta
`{key}['\"]?\s*[:=]\s*['\"]?(…)`; com `nonce` casa direto em `var nonce = "scr_NONCE_2"`
na primeira estratégia. Com `X-Nonce` a primeira falha, e a rodada paga **+5 s** de
`time.sleep`.

⚠️ **Só a entry 3 envia `SESSIONID`.** Cada step adicional que reenvia o mesmo cookie
forka um slot novo (defeito §6.2) e paga outro `sleep`. Medido: com as entries 3 e 4
enviando, `dry` custa 10,7 s e gera dois `LiteralFallbackAgent`; com só a entry 3,
5,7 s e um.

⚠️ **A entry 7 é deliberadamente irrealista** (cookie sem `Set-Cookie`). É o único
jeito de alcançar `CookieAgent`, porque `TokenLocationDetector.find`
(`tracking/token_location_detector.py:13-27`) testa headers antes de cookies e uma
captura real sempre traz o header (spec §2.2). Não "consertar" para parecer realista.

⚠️ **Não adicionar `postData` à entry 0.** Candidato de corpo é o corpo **inteiro**
(`tracking/baseline_diff.py:39-50`) e o grep procura esse texto inteiro nas respostas
anteriores — sempre `NotFound` (defeito §6.4). A cobertura de substituição em corpo vem
da entry 3, cujo token de `X-Csrf` resolve e é substituído também no corpo.

**Critérios de aceite:**
- [ ] `uv run python -m har_reproducer.main run --har <synthetic com __PORT__ trocado por 9999> --mode dry --output <dir virgem>` termina com `Reproduction SUCCESSFUL` e gera **exatamente 7** arquivos `extractors/*.meta.json`.
- [ ] Os 7 pares `token_id` → `agent_type`/`origin_step` são exatamente: `cd0419ee5764374946a627cd3912b819` → `CookieAgent`/7; `47ee3e04bc14c64ddd36aae983d6cb84` → `CSSAgent`/0; `3a2dd5b363bd0701c13a2da19b03abc9` → `HeaderAgent`/3; `ade6a53080262635799eb7ec66e824e8` → `JSONPathAgent`/3; `19ca0711b31b0813fdab80694bdc28b1` → `LiteralAgent`/5; `b3defec11e606afd97c5430602861f32` → `LiteralFallbackAgent`/0; `f04743b512e6241375b3226e7f7c69d3` → `RegexAgent`/0.
- [ ] O `stdout` contém **exatamente uma** linha `Attempt 1 failed for b3defec11e606afd97c5430602861f32. Retrying...` (um `sleep`, rodada em ~5,7 s).
- [ ] O `stdout` contém `Step 1 skipped (unsupported scheme 'wss')` — e **não** `skippable method`, provando que esquema vence método em `StepSkipEvaluator.skip_reason` (`reproduction/step_skip_evaluator.py:14-18`).
- [ ] O `stdout` contém `Step 2 skipped (skippable method 'OPTIONS')` e a linha `[AVISO] Não foi possível determinar a origem do token 'PLAINVAL777...'.`
- [ ] `curls/req_0003.curl.sh` contém `--data-binary '{"csrf": "{{extractor:47ee3e04bc14c64ddd36aae983d6cb84}}"}'` (substituição em corpo).
- [ ] `curls/req_0004.curl.sh` contém `/item/{{extractor:ade6a53080262635799eb7ec66e824e8}}` (substituição em URL).
- [ ] `curls/` tem 8 arquivos (steps 1 e 2 ausentes); `original_responses/` e `real_requests/` têm 10 cada; `real_responses/` está **vazio**.
- [ ] Duas rodadas em `--output` virgens produzem 48 arquivos/dirs cada (`rglob` cru) e são idênticas exceto o campo `temp_file_path` dos `.meta.json`.
- [ ] `run --mode dry` sobre `minimal_flow.har` com config `{"success_criteria":[{"type":"status_code","expected":200}]}` imprime `Final Validation Result: ✓ SUCCESS`, e com `expected: 500` imprime `✗ FAILURE` — e nos dois casos `extractors/` fica **vazio** e a rodada custa <1 s.

---

## [T02] — `GoldenNormalizer`: as máscaras de conteúdo e as sentinelas

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/support/golden_normalizer.py` (novo)

**Contexto:**
A árvore do workspace e o `stdout` têm sete fontes de não-determinismo (spec §2.1).
Cinco são neutralizadas por substituição textual; duas não são desta classe (o
`run_id`, tratado por caminho em T03, e o número de dígitos da porta, tratado por
restrição no servidor em T10). Esta task concentra as substituições textuais num só
lugar, porque elas se aplicam tanto a arquivos quanto a `stdout`.

**Estado atual:**
- Não existe. As máscaras hoje só existem num script descartável de scratchpad.

**Estado esperado depois:**
Classe `GoldenNormalizer`, construída com o `Path` do workspace do cenário, com um
método que recebe texto e devolve texto normalizado. Substituições, todas por regex de
conteúdo:

| Fonte | Substituição |
|---|---|
| Caminho absoluto do workspace | ocorrências do `str(workspace)` → `<WORKSPACE>` |
| Caminho absoluto do `tmp_path` do teste | → `<TMP>` |
| Porta | `127\.0\.0\.1:\d+` → `127.0.0.1:<PORT>` |
| `Date` | `"Date": "…"` **e** `'Date': '…'` → sentinela `<DATE>` |
| `Server` | `"Server": "…"` **e** `'Server': '…'` → sentinela `<SERVER>` |
| Segmento de `run_id` em texto | `replays/\d{8}_\d{6}` → `replays/<RUN_ID>` |

⚠️ **As duas formas de `Date`/`Server` são obrigatórias.** A forma JSON aparece nos
`res_*.json`; a forma `repr` de dict Python aparece dentro de `temp_extractors/*.py`,
que embutem `repr(response_sample)` via `ExtractorTemplate.render_temp_script` e
**sobrevivem** em modo `dry` (defeito §6.3). A forma `repr` é **defensiva e sem gatilho
conhecido hoje** — medido: zero ocorrências nos `temp_extractors/*.py` da fixture, e em
`main` esse diretório fica vazio. Implementar, mas não caçar um caso que não existe.

⚠️ **Nenhuma máscara genérica de hexadecimal.** Apagaria os `token_id`, que são
`md5(path:origin_step)` (`tracking/candidate_resolver.py:138-140`) e são justamente o
que se quer congelar. Uma máscara ampla aqui tornaria a rede cega para o tipo de
regressão que já gerou spec própria (`20260804 Desambiguação de Identidade de Token
Dinâmico`).

⚠️ O `run_id` aparece **em texto** (dentro de mensagens) e **em caminho** (o diretório
`replays/<run_id>/`). Esta task cobre só o primeiro; o segundo é T03.

**Critérios de aceite:**
- [ ] `normalize('.../out1/temp_extractors/x.py')` com workspace `.../out1` devolve `<WORKSPACE>/temp_extractors/x.py`.
- [ ] `normalize('http://127.0.0.1:34005/login')` devolve `http://127.0.0.1:<PORT>/login`, e o mesmo para uma porta de 4 dígitos.
- [ ] `normalize('"Date": "Thu, 06 Aug 2026 15:28:28 GMT"')` e `normalize("'Date': 'Thu, 06 Aug 2026 15:28:28 GMT'")` produzem, os dois, um texto com `<DATE>` e sem a data original.
- [ ] `normalize('"Server": "BaseHTTP/0.6 Python/3.12.3"')` produz `<SERVER>` — garantindo que um upgrade de patch do Python não quebre a suíte.
- [ ] `normalize('replays/20260806_122833/res_0000.json')` devolve `replays/<RUN_ID>/res_0000.json`.
- [ ] Um texto contendo `b3defec11e606afd97c5430602861f32` sai **inalterado** — nenhum hexadecimal é mascarado.
- [ ] Texto sem nenhuma das fontes sai byte-idêntico à entrada.

---

## [T03] — `GoldenWorkspace`: snapshot da árvore, comparação e regravação

**Depende de:** T02 (usa `GoldenNormalizer` no conteúdo de cada arquivo).
**Arquivos envolvidos:** `tests/support/golden_workspace.py` (novo)

**Contexto:**
O contrato golden compara dois artefatos por cenário: a árvore do workspace e o
`stdout` (spec §3.4). Esta task entrega a captura e a comparação da árvore, mais o
mecanismo de regravação.

**Estado atual:**
- Não existe.

**Estado esperado depois:**
Classe `GoldenWorkspace` que:

1. **Captura** um mapa de caminho relativo → conteúdo normalizado, percorrendo o
   workspace de forma **ordenada** (nunca confiando na ordem de `glob`/`rglob`).
2. **Inclui diretórios vazios** no mapa, com um marcador. `real_responses/` vazio em
   modo `dry` é parte do contrato (`engines/dry_engine.py:14-15`).
3. **Trata por caminho**, não por conteúdo: renomeia o segmento `<run_id>` de
   `replays/<AAAAMMDD_HHMMSS>/` para `<RUN_ID>`, e **exclui o conteúdo** dos arquivos
   sob `mitm_capture/` — mantendo a verificação de que o diretório existe.
4. **Compara** contra a referência gravada em `tests/golden/<cenário>/`, reportando
   arquivos só num lado, só no outro, e divergências de conteúdo com o diff de linhas.
5. **Regrava** a referência quando `HAR_REPRODUCER_UPDATE_GOLDEN=1` está no ambiente.

⚠️ **`mitm_capture/` é excluído porque é ruído** (`mitmdump.log` é log de processo
externo; `capture.har` guarda só o último response), mas ele é o **canal load-bearing
do modo `main`** — `CurlHttpTransport._try_read_capture`
(`reproduction/curl_http_transport.py:70-79`) lê `entries[0]` desse arquivo de slot
único. Excluir da comparação não é dizer que é irrelevante.

⚠️ **Toda contagem de arquivos precisa dizer sob qual régua foi feita.** O snapshot
desta classe exclui o *conteúdo* de `mitm_capture/`, então conta **2 menos** que um
`rglob` cru: após `run --mode main` são 60 aqui e 62 no `rglob`; após `+ replay all`,
69 aqui e 71 no `rglob`. Uma task que asserte o número do `rglob` usando esta classe
concluiria que quebrou.

⚠️ **Regravar golden destrói silenciosamente o valor da suíte.** Não faz parte do
fluxo de nenhuma task da Etapa B: se uma task de refatoração faz o golden divergir, a
task está errada, não o golden. A variável existe para mudanças deliberadas de
comportamento.

**Critérios de aceite:**
- [ ] Sobre um workspace de `run --mode dry` da fixture, o snapshot tem 48 entradas e inclui `real_responses/` como diretório vazio.
- [ ] Dois workspaces de `run --mode dry` gerados em `--output` diferentes comparam **iguais** (o `temp_file_path` absoluto é neutralizado por T02).
- [ ] Dois workspaces de rede gerados com **portas e `run_id` diferentes** comparam iguais, e o snapshot tem 69 entradas após `run main` + `replay all`.
- [ ] O snapshot contém a chave do diretório `mitm_capture/` mas **nenhuma** chave de arquivo sob ele.
- [ ] Um `replays/20260806_122833/res_0000.json` aparece no snapshot como `replays/<RUN_ID>/res_0000.json`.
- [ ] Com `HAR_REPRODUCER_UPDATE_GOLDEN=1`, a referência é escrita e uma comparação subsequente passa; sem a variável, uma divergência artificial (um byte alterado num `.meta.json`) **falha** e o relatório nomeia o arquivo.
- [ ] Percorrer o mesmo workspace duas vezes produz a mesma ordem de chaves.

---

## [T04] — `CliInvoker`: invocação in-process do CLI

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/support/cli_invoker.py` (novo)

**Contexto:**
Os cenários invocam `har_reproducer.main.main()` com `sys.argv` substituído, e não
`CliHandlers` direto — é o que faz o golden cobrir também o parsing de argumentos, os
defaults do `argparse` e o despacho (spec §3.5).

**Estado atual:**
- Não existe.

**Estado esperado depois:**
Classe `CliInvoker` com um método que recebe a lista de argumentos (sem o nome do
programa), e:

1. Substitui `sys.argv` por `["har-reproducer"] + argv` e o **restaura num `finally`**.
2. Captura `stdout` **e `stderr`**.
3. **Captura e devolve** a exceção em vez de deixá-la propagar.
4. Trata `SystemExit` **separadamente** de `Exception`.

Devolve um objeto com `stdout`, `stderr`, e a exceção (ou `None`).

⚠️ **`SystemExit` não é subclasse de `Exception`.** `parse_args` chama `sys.exit(2)`
para `--mode` inválido ou `--har` ausente; um `except Exception` não o pega. Capturar
`BaseException` ou tratar `SystemExit` num ramo próprio.

⚠️ **Todo o texto útil do `argparse` vai para `stderr`.** A "mensagem" de um
`SystemExit(2)` é o inteiro `2`; `usage:` e `invalid choice` só existem em `stderr`.
Sem capturá-lo, os cenários de T09 congelariam apenas "saiu com código 2".

⚠️ Invocação in-process é decisão, mas **não pelo custo**: o interpretador novo de um
`uv run python -m …` custa 0,455 s medidos, não "vários segundos". A razão é capturar
as saídas e pagar o import uma vez por sessão.

⚠️ `main()` chama `load_dotenv()` (`har_reproducer/main.py:11`), que lê o `.env` real
do diretório de trabalho e muta `os.environ` pelo resto do processo do pytest. É
entrada não controlada, aceita como risco (spec §7.1) porque nenhum cenário configura
`llm`. Não tentar isolar nesta etapa — isolar exigiria mexer fora de `tests/`.

**Critérios de aceite:**
- [ ] Uma invocação de `parse` bem-sucedida devolve exceção `None` e um `stdout` contendo `Parsed HAR into 10 steps.`
- [ ] `sys.argv` volta ao valor original depois da invocação, inclusive quando a invocação levanta exceção.
- [ ] Invocar com `--mode` inválido devolve um `SystemExit` (não `None`, não `ValueError`) e um `stderr` contendo `invalid choice`.
- [ ] Invocar `replay --output <dir inexistente> --mode all` devolve um `ValueError` cuja mensagem começa com `Workspace directory does not exist:`.
- [ ] Duas invocações seguidas no mesmo processo funcionam, e a segunda não vê `stdout` da primeira.

---

## [T05] — `conftest.py`: fixtures de HAR materializado, workspace, e o opt-in `--runslow`

**Depende de:** T01, T02, T03, T04.
**Arquivos envolvidos:** `tests/conftest.py` (novo)

**Contexto:**
As fixtures de HAR guardam `__PORT__` como placeholder; alguém precisa materializá-las
num `tmp_path` com a porta real. E o golden de rede fica na suíte permanentemente, mas
fora da rodada padrão (spec §3.3) — o que exige três hooks, porque `pytest.ini` não
pode ser tocado.

**Estado atual:**
- Não existe. `pytest.ini` já declara `testpaths = tests` e `pythonpath = .`, e
  `pyproject.toml` já traz `pytest>=9.1.0` — nada precisa ser configurado.

**Estado esperado depois:**
Fixtures que materializam cada HAR num `tmp_path` substituindo `__PORT__` por uma porta
recebida (ou por um valor fixo de 5 dígitos nos cenários offline), e fixtures que
entregam `GoldenWorkspace` e `CliInvoker` prontos.

Mais os **três** hooks do opt-in:

1. `pytest_addoption` — cria a flag `--runslow`.
2. `pytest_configure` + `addinivalue_line` — registra o marcador `slow`. Sem isso sai
   `PytestUnknownMarkWarning`.
3. `pytest_collection_modifyitems` — pula os itens marcados `slow` quando a flag está
   ausente.

⚠️ **Os três são necessários.** `pytest_addoption` sozinho cria a flag mas não pula
nada; sem `pytest_configure` o marcador é desconhecido; e a alternativa canônica
(`addopts = -m "not slow"` em `pytest.ini`) está vedada por §3.7.

⚠️ **A suíte não pode rodar em paralelo nem com ordem aleatória** (spec §7.2).
`Workspace` é singleton de atributo de classe (`fs_io/workspace.py:19-26`) e `parse`
**nunca** o reinicializa — `handle_parse` (`cli/cli_handlers.py:79-85`) usa
`HARParser.split_har`, que não toca `Workspace`. Nenhum teste pode tocar `Workspace`
sem passar pelo CLI. Não adicionar `pytest-xdist` nem plugin de ordem aleatória.

⚠️ Mesmo nos cenários offline a porta materializada deve ter **5 dígitos** — ver a
restrição de T10, que vale para qualquer golden que congele mensagem de erro de `curl`.

**Critérios de aceite:**
- [ ] A fixture do HAR sintético devolve um `Path` dentro do `tmp_path` cujo conteúdo não contém mais `__PORT__` e é JSON válido com 10 entries.
- [ ] `uv run pytest` (sem flag) **pula** os testes marcados `slow` e não emite `PytestUnknownMarkWarning`.
- [ ] `uv run pytest --runslow` coleta e executa os testes marcados `slow`.
- [ ] `uv run pytest -q` termina sem warnings.
- [ ] Nenhum arquivo fora de `tests/` aparece em `git status` depois de rodar a suíte — exceto `.mitmproxy/`, que é gitignored e criado por `ProjectConfigLoader._apply_defaults` (`config/project_config_loader.py:35-38`) em todo `run`/`replay`, inclusive `dry` (spec §3.7).

---

## [T06] — `test_cli_parse.py`: os 3 cenários de `parse`

**Depende de:** T05.
**Arquivos envolvidos:** `tests/test_cli_parse.py` (novo), `tests/golden/parse_*/` (novos)

**Contexto:**
`parse` decompõe o HAR em `req_XXXX.json`/`res_XXXX.json` sob `<output>/parse/`, sem
executar nada (README:51-63).

**Estado atual:**
- Sem cobertura.

**Estado esperado depois:**
Três cenários: padrão com `--output` explícito; `--output` **omitido**, exercitando o
default `<pasta-do-har>/output` (`cli/cli_handlers.py:176-177`); e `--reset`.

⚠️ **O cenário do default copia o HAR para um `tmp_path` antes de invocar**, senão o
teste escreve dentro de `tests/fixtures/`.

⚠️ **O cenário de `--reset` precisa de um arquivo-sentinela fora de `parse/`.**
`HARParser.split_har` (`fs_io/har_parser.py:87-90`) já faz `rmtree` incondicional de
`<output>/parse`, então `parse --reset` e `parse` sem `--reset` produzem árvore
**idêntica** a menos que exista conteúdo fora de `parse/`. Criar `<output>/lixo.txt`
antes e afirmar que desapareceu é a única coisa que distingue os dois.

⚠️ **`parse` é idempotente**, ao contrário de `run` — pelo mesmo `rmtree`. Vale um
cenário que rode duas vezes e compare com o mesmo golden.

**Critérios de aceite:**
- [ ] `parse --har <fixture> --output <tmp>` imprime `Parsed HAR into 10 steps.` e gera `parse/req_0000.json`..`req_0009.json` e `parse/res_0000.json`..`res_0009.json` — 20 arquivos, e **nenhum** dos oito diretórios de workspace.
- [ ] `parse --har <tmp>/flow.har` sem `--output` grava em `<tmp>/output/parse/`.
- [ ] Com `<output>/lixo.txt` presente, `parse --reset` remove o arquivo e `parse` sem `--reset` o preserva — os dois goldens diferem exatamente nessa entrada.
- [ ] Rodar `parse` duas vezes no mesmo `--output` compara igual ao golden nas duas.
- [ ] Os goldens de `parse` não contêm nenhum caminho absoluto nem porta literal.

---

## [T07] — `test_cli_run.py`: `run --mode dry` e `skip_rules` customizado

**Depende de:** T05.
**Arquivos envolvidos:** `tests/test_cli_run.py` (novo), `tests/golden/run_dry*/`, `tests/golden/skip_rules_*/` (novos)

**Contexto:**
`run --mode dry` analisa tokens usando as respostas gravadas no HAR, sem rede
(README:74). É o pipeline offline completo, e o cenário mais valioso do bloco A1.

**Estado atual:**
- Sem cobertura.

**Estado esperado depois:**
Três cenários: `run --mode dry` padrão; `run --mode dry --reset`; e `run --mode dry`
com config `{"skip_rules": {"methods": ["OPTIONS", "POST"]}}`.

⚠️ **O cenário de `skip_rules` congela um encadeamento não óbvio.** Com `POST` na
lista, a entry 3 é pulada — e ela é a única que envia `SESSIONID`, então desaparecem o
`HeaderAgent` falhando, o `LiteralFallbackAgent` **e o `sleep`**: custa **0,08 s** e
gera **quatro** extratores. Mas o `JSONPathAgent` **sobrevive**, apesar de sua origem
(step 3) ter sido pulada, porque `original_responses/res_0003.json` guarda a resposta
**do HAR** e não um stub de skip — `Engine._process_entry`
(`engines/engine.py:103-107`) persiste request e response original **antes** de avaliar
o skip, e em `dry` o tracking lê `original_responses/`. **Sem este aviso, alguém
"corrige" o golden achando que é bug.**

⚠️ Os dois primeiros cenários pagam `time.sleep(5)` cada um (defeito §6.1), a 5,7 s por
rodada. É esperado e não deve ser "otimizado" mexendo na fixture.

**Critérios de aceite:**
- [ ] `run --mode dry` compara igual ao golden, que contém os 7 `.meta.json` com os `agent_type`/`origin_step` listados em T01, `real_responses/` vazio, e `curls/` com 8 arquivos.
- [ ] O golden de `stdout` do cenário padrão contém, na ordem: `Step 0 completed with status 200`, `Step 1 skipped (unsupported scheme 'wss')`, `Step 2 skipped (skippable method 'OPTIONS')`, `Attempt 1 failed for b3defec11e606afd97c5430602861f32. Retrying...`, `Step 3 completed with status 200`, e mais adiante `[AVISO] Não foi possível determinar a origem do token 'PLAINVAL777...'.`
- [ ] O cenário `--reset` remove um `<output>/lixo.txt` pré-criado.
- [ ] O cenário de `skip_rules` gera **exatamente 4** extratores — `CookieAgent`, `JSONPathAgent`, `LiteralAgent`, `RegexAgent` — **zero** linhas `Attempt … failed`, e `stdout` com `Step 3 skipped (skippable method 'POST')` e `Step 9 skipped (skippable method 'POST')`.
- [ ] No golden de `skip_rules`, `original_responses/res_0003.json` tem `status_code: 200` e corpo `{"id": 4242, "ok": true}`, e `real_requests/req_0003.json` tem `is_skippable: true` — é o que sustenta a sobrevivência do `JSONPathAgent`.
- [ ] Não-regressão: os três cenários usam `--output` virgem, e nenhum reusa diretório de outro.

---

## [T08] — `test_cli_config.py`: os 8 cenários de `success_criteria`

**Depende de:** T05.
**Arquivos envolvidos:** `tests/test_cli_config.py` (novo), `tests/golden/criteria_*/` (novos)

**Contexto:**
`success_criteria` valida o último step não pulado do fluxo, com quatro tipos
(README:140-146). O ramo de reprovação é o único que alcança duas mensagens
documentadas: `Final Validation Result: ✗ FAILURE` e
`Reproduction FAILED: Target state not reached.`

**Estado atual:**
- Sem cobertura.

**Estado esperado depois:**
Oito cenários sobre `minimal_flow.har` — cada um dos quatro tipos em sucesso e em
falha, via `run --mode dry`:

| Tipo | Sucesso | Falha |
|---|---|---|
| `status_code` | `200` | `500` |
| `body_contains` | `pronto` | `ausente` |
| `url_match` | `done\?ok=1` | `nunca` |
| `html_element_present` | `#marker` | `#nada` |

⚠️ **Usar `minimal_flow.har`, nunca a fixture de 10 entries.** A principal pagaria
`time.sleep(5)` por cenário — ~45 s para testar algo sem relação com análise de token.
A mínima não gera candidato nenhum (baseline e step são o mesmo), então nenhum agent
roda: medido, <1 s por cenário e `extractors/` vazio.

⚠️ `url_match` lê `response.redirect_url` (`validation/validator.py:32-34`) e
`html_element_present` roda `soup.select_one` (`:40-45`) — é por isso que
`minimal_flow.har` tem `redirectUrl` e corpo HTML com `<div id="marker">`.

⚠️ Nenhum cenário configura `llm` — o campo está fora de escopo (spec §1), e assim
nenhum teste faz chamada a provedor.

**Critérios de aceite:**
- [ ] Os 4 cenários de sucesso imprimem `Final Validation Result: ✓ SUCCESS` e `Reproduction SUCCESSFUL: Target state reached.`
- [ ] Os 4 cenários de falha imprimem `Final Validation Result: ✗ FAILURE` e `Reproduction FAILED: Target state not reached.`
- [ ] Em todos os 8, `extractors/` está vazio e a rodada custa <1 s.
- [ ] Um cenário adicional com `success_criteria: []` (ou sem `--config`) imprime `Reproduction SUCCESSFUL` **sem** nenhuma linha `Final Validation Result` — `Engine._validate_final` (`engines/engine.py:141-147`) retorna `True` sem imprimir quando a lista está vazia.
- [ ] Os goldens dos 8 diferem entre si apenas nas linhas de veredito.

---

## [T09] — `test_cli_errors.py`: os 11 cenários de erro offline

**Depende de:** T05.
**Arquivos envolvidos:** `tests/test_cli_errors.py` (novo)

**Contexto:**
Onze cenários de erro não usam rede: três do `argparse` e oito do `replay` que
levantam antes de o proxy existir. Eles são a cobertura mais barata da suíte e por isso
ficam em A1, na rodada padrão.

**Estado atual:**
- Sem cobertura.

**Estado esperado depois:**
Três cenários de `argparse` (`--mode` inválido; `--har` ausente; `--mode` ausente no
`replay`) asserindo `SystemExit` e o `stderr`.

Oito cenários de `replay` asserindo o tipo da exceção e a mensagem normalizada: as
cinco validações de flag de `_validate_replay_mode_flags`
(`cli/cli_handlers.py:160-173`) — `--from/--to/--steps-file` com `--mode all`;
`--steps-file` com `slice`; `--steps-file` com `smart`; `--from > --to`;
`--mode list` sem `--steps-file`; `--from/--to` com `list` — mais
`Workspace directory does not exist` (`:105-106`), `Workspace has no curl files`
(`:109-110`) e `response_reference_dir does not exist` (`:115-116`).

⚠️ **Estes oito são offline e ficam em A1**, não em A2. Medido: as validações de flag
saem em `cli_handlers.py:89` e os três `ValueError` de workspace/referência em
`:105-106`, `:109-110`, `:115-116` — **todos antes** da construção do
`MitmProxyOrchestrator` na linha 96. Deixá-los em A2 os tiraria da rodada padrão.

⚠️ **Só o §5.5 (`_require_all_existing`) precisa de proxy** e por isso vai para T12:
ele roda dentro do callback de `orchestrator.run`.

⚠️ **Contrato de asserção**: tipo da exceção + mensagem normalizada + `stderr`. As
quatro mensagens de `ValueError` embutem caminho absoluto, e no caso de
`Workspace directory does not exist` o caminho **não é** um workspace — a sentinela
`<WORKSPACE>` não se aplica. Normalizar o `tmp_path` para `<TMP>`.

⚠️ Estes cenários **não produzem árvore nem `stdout` útil** — o contrato (a)/(b) do
golden não se aplica a eles.

**Critérios de aceite:**
- [ ] `run --mode inexistente` devolve `SystemExit` e `stderr` contendo `invalid choice: 'inexistente'`.
- [ ] `run` sem `--har` devolve `SystemExit` e `stderr` contendo `the following arguments are required: --har`.
- [ ] `replay --output <dir>` sem `--mode` devolve `SystemExit` e `stderr` contendo `--mode`.
- [ ] `replay --mode all --from 0` devolve `ValueError("--from/--to/--steps-file não se aplicam a --mode all")`.
- [ ] `replay --mode slice --steps-file x.txt` e `replay --mode smart --steps-file x.txt` devolvem `ValueError` com `--steps-file não se aplica a --mode slice` e `… smart`, respectivamente.
- [ ] `replay --mode slice --from 5 --to 2` devolve `ValueError("--from não pode ser maior que --to")`.
- [ ] `replay --mode list` sem `--steps-file` devolve `ValueError("--mode list exige --steps-file")`, e `replay --mode list --steps-file x.txt --from 0` devolve `ValueError("--from/--to não se aplicam a --mode list")`.
- [ ] `replay --output <dir inexistente> --mode all` devolve `ValueError` cuja mensagem normalizada é `Workspace directory does not exist: <TMP>/...`.
- [ ] `replay` sobre diretório existente e vazio devolve `ValueError` com `Workspace has no curl files:`.
- [ ] `replay` com `response_reference_dir` apontando para diretório inexistente devolve `ValueError` com `response_reference_dir does not exist:`.
- [ ] Todos os 11 rodam na rodada padrão (sem `--runslow`) e somam <1 s.

---

## ⏸ CHECKPOINT — demonstrar A1 antes de começar A2

Ao terminar T09, **parar** e demonstrar: `uv run pytest -q` verde, com a contagem de
testes, o tempo total (esperado ~12 s) e a árvore de `tests/golden/` gerada. Só seguir
para T10 depois disso.

---

## [T10] — `CannedHttpServer`: servidor de respostas canned, com as duas restrições de porta

**Depende de:** T05.
**Arquivos envolvidos:** `tests/support/canned_http_server.py` (novo)

**Contexto:**
O ramo `replay` **não tem modo `dry`** — sempre passa por `CurlHttpTransport` e
`MitmProxyOrchestrator`. Um servidor HTTP falso local é o que torna `run --mode main` e
os 4 modos de `replay` caracterizáveis sem nenhum seam de produção (spec §3.3).

**Estado atual:**
- Não existe. `run --mode main` e todo o ramo `replay` só rodam contra servidor real.

**Estado esperado depois:**
Classe `CannedHttpServer` que sobe um servidor HTTP em `127.0.0.1` numa porta livre,
servindo por `(método, caminho)` exatamente as respostas das entries da fixture — nove
rotas: `GET /login`, `OPTIONS /api/do`, `POST /api/do`, `GET /item/4242`,
`GET /plain`, `GET /use-plain`, `GET /prefs`, `GET /use-prefs`, `POST /submit`.

A entry 1 é `wss://` e nunca chega ao servidor (é pulada por esquema). Rota
desconhecida devolve 404.

Serve **HTTP puro**, não HTTPS.

⚠️ **Restrição 1: nenhum corpo canned pode embutir a porta.** `real_responses/*.json`
grava `Content-Length` (medido: `"77"` para a entry 0), e uma porta de 4 vs 5 dígitos
mudaria o comprimento enquanto a máscara `127.0.0.1:<PORT>` esconderia a causa.

⚠️ **Restrição 2: a porta tem que ter 5 dígitos** — asserir `port >= 10000` na
construção. Motivo: o cenário de `list` fora de ordem (T12) congela a mensagem
`curl: (3) nested brace in URL position N:`, e `N` é um offset em caracteres que
depende do tamanho da porta. Medido: porta 9999 → `position 29`, porta 40001 →
`position 30`, e **as duas sobrevivem à máscara de porta**. A faixa efêmera do Linux já
garante 5 dígitos (medido: `ip_local_port_range = 32768 60999`), então a asserção nunca
deve disparar — ela existe para transformar um golden silenciosamente flaky num erro
alto e nomeado.

⚠️ **HTTP puro é decisão, não descuido.** `CurlHttpTransport._tls_flag`
(`reproduction/curl_http_transport.py:52-56`) **sempre** emite `--cacert <path>` e
nunca `--insecure`, porque `ca_cert_path` nunca é `None` — `_apply_defaults`
(`config/project_config_loader.py:35-38`) sempre o preenche. Com HTTP o `curl` não lê
o CA, então o campo é irrelevante para a suíte e fica **declarado irrelevante**, não
coberto.

⚠️ O servidor precisa emitir `Set-Cookie` nas rotas `/login` e `/prefs` — não existe
outro jeito de setar cookie em HTTP. É por isso que `CookieAgent` desaparece em modo
`main` (spec §2.2, fato 11), e isso é comportamento esperado, não bug da task.

**Critérios de aceite:**
- [ ] Construir com porta < 10000 levanta erro; com porta da faixa efêmera, sobe normalmente.
- [ ] `curl http://127.0.0.1:<porta>/login` devolve 200, `Content-Type: text/html`, `Set-Cookie: SESSIONID=abc123sess; Path=/`, e o corpo com `<div id="marker">tok_CSS_1</div>` e o bloco `<script>`.
- [ ] `curl -X POST http://127.0.0.1:<porta>/api/do` devolve 200 e `{"id": 4242, "ok": true}` com mime `application/json`.
- [ ] `curl http://127.0.0.1:<porta>/plain` devolve `Content-Type: text/plain` e corpo `PLAINVAL777`.
- [ ] `curl http://127.0.0.1:<porta>/prefs` devolve `Set-Cookie: PREFS=xyz789`.
- [ ] `curl http://127.0.0.1:<porta>/rota-inexistente` devolve 404.
- [ ] Nenhum corpo servido contém a porta.
- [ ] O servidor não escreve nada em `stdout` (o log padrão do `http.server` está silenciado, senão poluiria a captura do `CliInvoker`).

---

## [T11] — `TokenFailureGuard`: asserção do invariante de ordem de resolução

**Depende de:** Nenhuma (só interpreta texto de `stdout`).
**Arquivos envolvidos:** `tests/support/token_failure_guard.py` (novo)

**Contexto:**
A 7ª fonte de não-determinismo mais perigosa é a ordem de iteração de `Set[str]`:
`ReplayTokenResolver.resolve` (`replay/replay_token_resolver.py:34`) itera
`token_ids: Set[str]` e imprime na linha `:57` a cada falha. Hash de `str` é
randomizado **por processo** — medido: 6 processos novos produziram 6 ordens diferentes
com os 7 `token_id` da fixture; com `PYTHONHASHSEED` fixo, sempre a mesma. Dentro de
**uma** sessão do pytest a ordem é estável, o que significa que a suíte pode passar mil
vezes e quebrar quando o golden gravado numa sessão é comparado noutra.

`PYTHONHASHSEED` não é corrigível de dentro do `conftest.py` — precisa preceder o
interpretador.

**Estado atual:**
- Não existe. A spec §3.4 define o invariante: **em nenhum cenário golden dois ou mais
  tokens podem falhar resolução no mesmo curl.**

**Estado esperado depois:**
Classe `TokenFailureGuard` que recebe o `stdout` de um cenário de replay, agrupa as
linhas `Failed to resolve token '<id>' during replay: …` pelo `Step N completed with
status …` que as sucede, e assere **no máximo uma por grupo**. Ao falhar, nomeia o step
e os token ids.

⚠️ **Agrupar por step é essencial.** Duas falhas em curls **diferentes** são
inofensivas — cada uma é a única do seu grupo, e a ordem relativa entre grupos é fixada
pela ordem dos steps. Uma checagem que só contasse o total de linhas rejeitaria
cenários válidos.

⚠️ **Por que uma asserção e não uma convenção.** O invariante é *auto-evidente* — a
informação está no golden de `stdout` — mas **nada assere nada**: depende de alguém
olhar, e de agrupar corretamente. Se ninguém olhar, a consequência é um teste ~50%
flaky numa **sessão futura**, que é exatamente o modo de falha que o invariante existe
para evitar.

⚠️ Cenários excluídos por violarem o invariante, medidos: `list` com `4\n3\n0` (4
falhas, duas no mesmo curl) e `replay` sobre workspace `dry` (7 falhas). Nenhum dos
dois entra na suíte.

⚠️ Ordenar as linhas antes de comparar foi **descartado**: esconderia uma reordenação
real introduzida pela Etapa B.

**Critérios de aceite:**
- [ ] Um `stdout` sem nenhuma linha `Failed to resolve` passa.
- [ ] O `stdout` do cenário `list 4\n3` — uma falha (`ade6a530…`) antes de `Step 4 completed with status 0` — passa, e o guard reporta o agrupamento `{4: ['ade6a53080262635799eb7ec66e824e8']}`.
- [ ] Um `stdout` sintético com **duas** linhas `Failed to resolve` antes do mesmo `Step 4 completed` **falha**, e a mensagem nomeia o step 4 e os dois ids.
- [ ] Um `stdout` sintético com uma falha antes de `Step 3 completed` e outra antes de `Step 4 completed` **passa** — grupos diferentes.
- [ ] O guard não confunde `Failed to resolve token` com `Failed to refresh token` (a mensagem do ramo `run`, em `tracking/token_resolver.py:32`, que itera um **dict** e portanto é determinística).

---

## [T12] — `test_cli_replay.py`: os 11 cenários de rede

**Depende de:** T10, T11.
**Arquivos envolvidos:** `tests/test_cli_replay.py` (novo), `tests/golden/run_main/`, `tests/golden/replay_*/` (novos)

**Contexto:**
Último bloco: `run --mode main` e os 4 modos de `replay`, contra o servidor falso, com
`mitmdump` e `curl` reais. Todos marcados `slow`.

**Estado atual:**
- Sem cobertura. É o ramo com maior densidade de bugs recentes — três das specs de
  05/08 são o mesmo defeito em `ReplayRunner._schedule_*`.

**Estado esperado depois:**
Onze cenários. Um `run --mode main` **por sessão** constrói o workspace; cada cenário de
replay **copia** essa árvore.

| Cenário | `argv` de replay |
|---|---|
| `run_main` | (constrói o workspace; é também o cenário de `proxy_port`) |
| `replay_all` | `--mode all` |
| `replay_slice_full` | `--mode slice` |
| `replay_slice_0_3` | `--mode slice --from 0 --to 3` |
| `replay_smart_noflag` | `--mode smart` |
| `replay_smart_to_4` | `--mode smart --to 4` |
| `replay_smart_from_3` | `--mode smart --from 3 --to 4` |
| `replay_list_asc` | `--mode list --steps-file` com `0\n3\n4` |
| `replay_list_out_of_order` | `--mode list --steps-file` com `4\n3` |
| `replay_ref_fallback` | `--mode list --steps-file` com `4`, e `response_reference_dir` = cópia de `real_responses/` **sem** `res_0003.json` |
| `replay_missing_step` | `--mode list --steps-file` com `0\n1` (step 1 foi pulado) |

⚠️ **A cópia por cenário é funcionalmente obrigatória, não otimização.** `replay`
**muta o workspace de origem**: `ReplayRunner._annotate_static_tokens`
(`replay/replay_runner.py:101-108`) reescreve `curls/req_NNNN.curl.sh`, e
`ReplayTokenResolver._record_observation` (`replay/replay_token_resolver.py:74-84`)
reescreve `extractors/*.meta.json` (`valid_count`, `last_value`, `ever_changed`). Sem
cópia os cenários se contaminam independentemente de tempo.

⚠️ **`proxy_port` não ganha cenário próprio.** O `run --mode main` pede uma porta livre
e a passa no config como se fosse fixa, exercitando
`MitmProxyOrchestrator._resolve_port` (`:33-37`) no ramo `proxy_port is not None`. Um
segundo `run --mode main` custaria 11,2 s para congelar a mesma árvore.

⚠️ **Em `main`, `CookieAgent` desaparece** e o golden tem **6** tipos de extrator, não
7: a entry 7 degrada porque o servidor emite `Set-Cookie`, resultando em **dois**
`LiteralFallbackAgent` (origens 0 e 7) e **dois** `sleep`. É contrato, não bug.

⚠️ **`replay_list_out_of_order` é o único cenário que cobre a característica definidora
do modo** (README:102, "na ordem em que aparecem no arquivo") — um `list` ascendente é
indistinguível de um `slice`. A escolha de `4\n3` e **não** `4\n3\n0` é deliberada: as
duas executam fora de ordem, mas `4\n3` produz **uma** falha de token e `4\n3\n0`
produz quatro, duas no mesmo curl, violando o invariante de T11.

⚠️ **`replay_ref_fallback` não usa o exemplo do README.** README:149 sugere "workspace
que só rodou `dry`", mas esse caminho é inalcançável (defeito §6.8): sem
`extractors/*.py`, `ExtractorRunner.run_existing`
(`reproduction/extractor_runner.py:26-28`) sai no guard `exists()` **antes** de usar o
`override_dir`, e os dois ramos de `_reference_dir_for_step` devolvem `None`. O cenário
usa workspace `main` com referência incompleta, que exercita os dois ramos de verdade.

⚠️ Rodar `mitmdump` numa máquina sem `.mitmproxy/` populado paga a geração de
certificado, que pode passar dos `HEALTH_CHECK_TIMEOUT_SECONDS = 10.0` e cair no
`RuntimeError` de `_wait_until_ready` (spec §7.4). Se acontecer, é falha de ambiente e
deve dar erro claro — não regravar golden.

⚠️ Os replays têm que ser **serializados**: `run_id` tem precisão de segundo
(`cli/cli_handlers.py:95`) e dois no mesmo segundo colidiriam. O golden assere
**exatamente um** diretório sob `replays/`.

**Critérios de aceite:**
- [ ] `run --mode main` compara igual ao golden: **6** tipos de extrator (dois `LiteralFallbackAgent`, origens 0 e 7; **nenhum** `CookieAgent`), os 7 `extract_*.py` escritos, `temp_extractors/` **vazio**, `real_responses/` com 10 arquivos — incluindo `res_0001.json` e `res_0002.json` com `status_code: 0` e `skipped: true`.
- [ ] O `stdout` de `run --mode main` tem **duas** linhas `Attempt 1 failed` (tokens `b3defec1…` e `cd0419ee…`) e termina em `Reproduction SUCCESSFUL`.
- [ ] Os steps executados por cenário são exatamente: `all` e `slice_full` → `[0,3,4,5,6,7,8,9]`; `slice_0_3` → `[0,3]`; `smart_noflag` → `[0,3,9]`; `smart_to_4` → `[0,3,4]`; `smart_from_3` → `[3,4]`; `list_asc` → `[0,3,4]`; `list_out_of_order` → `[4,3]`; `ref_fallback` → `[4]`.
- [ ] Os 9 cenários de replay bem-sucedidos imprimem `Replay Validation Result: ✓ SUCCESS`, e `TokenFailureGuard` passa em **todos** os 11.
- [ ] `replay_list_out_of_order` congela os três comportamentos do defeito §6.9: `Failed to resolve token 'ade6a53080262635799eb7ec66e824e8'`, `curl: (3) nested brace in URL position 30:`, `Step 4 completed with status 0` — **e ainda assim** `Replay Validation Result: ✓ SUCCESS (step 3 status code vs. original)` e `Reproduction SUCCESSFUL`.
- [ ] `replay_ref_fallback` termina com `✓ SUCCESS` e **zero** falhas de token, provando que o token de origem 3 foi resolvido via `original_responses/` (fallback) e o de origem 0 via a referência.
- [ ] `replay_missing_step` devolve `ValueError` cuja mensagem contém `step(s) [1] não existem no workspace` — o comportamento estabelecido pelas três specs de 05/08.
- [ ] Cada golden de replay tem **exatamente um** diretório sob `replays/`, normalizado como `<RUN_ID>`.
- [ ] Duas execuções da suíte com `--runslow`, em processos diferentes, comparam iguais aos mesmos goldens — a prova de que as sete fontes de não-determinismo estão neutralizadas.
- [ ] `uv run pytest -q` (sem `--runslow`) continua verde e **não** executa nenhum destes 11.
- [ ] Não-regressão: nenhum arquivo fora de `tests/` mudou; `git status` limpo exceto `tests/` e o `.mitmproxy/` gitignored.

---

## Fechamento

Depois de T12 e da verificação de todos os critérios de aceite: marcar os checkboxes
deste plano e commitar como `doc: marcando tasks concluídas`; então
`git checkout master` e `git merge --no-ff 20260806-rede-de-caracterizacao-golden`.

A Etapa B (refatoração, corte "nível 2" da spec §3.8) começa de uma branch nova a
partir da `master`, com esta suíte verde como pré-condição de cada task.
