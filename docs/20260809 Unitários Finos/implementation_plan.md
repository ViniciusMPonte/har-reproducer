# Plano de Implementação — Etapa C: Unitários Finos

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

Convenção usada em todas as tasks: arquivos de teste vivem em `tests/unit/test_<alvo>.py`
(spec D.1); dublês compartilhados em `tests/support/` (spec D.2); nenhuma task altera
`har_reproducer/`. Nenhum teste desta etapa é marcado `slow` (roda sem `--runslow`).

## [T01] — Dublês compartilhados: criar `FakeScriptExecutor`, `FakeSleeper`, `StubHttpTransport`, `FakeExtractorRunner`, `FakeMetadataStore`, `FakeProcess`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/support/fake_script_executor.py`, `tests/support/fake_sleeper.py`, `tests/support/stub_http_transport.py`, `tests/support/fake_extractor_runner.py`, `tests/support/fake_metadata_store.py`, `tests/support/fake_process.py` (novos).

**Contexto:**
Várias tasks P1/P2 (T13, T17, T18, T19, T20, T22, T23, T24, T25, T26, T27, T28, T29) precisam
de dublês dos colaboradores injetados pelas costuras da Etapa B (`ScriptExecutor`, `Sleeper`,
`HttpTransport`, `ExtractorRunner`, `ExtractorMetadataStore`, e um `subprocess.Popen` fake para
`MitmProxyOrchestrator`). Escrever esses dublês uma vez, como classes reutilizáveis, evita
duplicar a mesma classe fake em vários arquivos de teste (spec D.2).

**Estado atual:**
- `tests/support/` não tem nenhum dublê para as costuras da Etapa B — só suporte para a rede
  golden (`CliInvoker`, `GoldenWorkspace`, etc., spec §"Infra de testes existente").
- `ScriptExecutor.run(script_path, timeout_seconds, env=None) -> ScriptExecutionResult`
  (`har_reproducer/reproduction/script_executor.py:13-37`); `Sleeper.sleep(seconds) -> None` é
  `@staticmethod` (`har_reproducer/reproduction/sleeper.py:6-8`); `HttpTransport` é `Protocol`
  com `send_request(curl_literal, step_index) -> StepResponse`
  (`har_reproducer/contracts/http_transport.py:6-7`); `ExtractorRunner.run`/`run_existing`
  retornam `Optional[str]`; `ExtractorMetadataStore.load`/`save` operam sobre `Extractor`.

**Estado esperado depois:**
- `FakeScriptExecutor(ClassVar ou atributo de instância para resultado configurável)`:
  construtor recebe o `ScriptExecutionResult` (ou uma sequência deles, um por chamada) a
  devolver; grava as chamadas recebidas (`script_path`, `timeout_seconds`, `env`) numa lista
  para inspeção do teste; `run(...)` devolve o próximo resultado configurado.
- `FakeSleeper`: subclasse de `Sleeper` que sobrescreve `sleep` como método de instância (não
  `@staticmethod`), registra `seconds` de cada chamada numa lista `calls: List[float]`, não
  dorme de verdade.
- `StubHttpTransport`: construtor recebe uma `StepResponse` (ou lista/callable) a devolver;
  `send_request(curl_literal, step_index)` grava `(curl_literal, step_index)` recebidos e
  devolve a resposta configurada.
- `FakeExtractorRunner`: construtor recebe um mapa `token_id -> Optional[str]` (ou callable)
  para `run_existing`, e idem para `run`; grava as chamadas recebidas.
- `FakeMetadataStore`: dict interno `token_id -> Extractor`; `load`/`save` operam sobre esse
  dict, sem tocar disco — permite ao teste inspecionar o que foi salvo.
- `FakeProcess`: dublê de `subprocess.Popen` com `terminate()`, `wait(timeout=None)`, `kill()`,
  `poll()`, `returncode` configuráveis (para `MitmProxyOrchestrator._terminate`/
  `_process_died_early`), registrando quantas vezes cada método foi chamado.
- ⚠️ Cada dublê é uma classe com tipagem explícita em todo atributo/parâmetro/retorno (guia de
  estilo) — nada de `Dict`/`List` soltos sem tipo, nada de função solta no módulo.

**Critérios de aceite:**
- [ ] `FakeScriptExecutor(ScriptExecutionResult(timed_out=False, return_code=0, stdout="x", stderr="")).run(Path("a.py"), 5)` devolve esse resultado e registra a chamada em `.calls`.
- [ ] `FakeSleeper().sleep(5)` não bloqueia (retorna imediatamente) e `sleeper.calls == [5]` após a chamada.
- [ ] `StubHttpTransport(StepResponse(status_code=200)).send_request("curl ...", 0)` devolve a resposta configurada e `transport.calls == [("curl ...", 0)]`.
- [ ] `FakeExtractorRunner(run_existing_result="abc").run_existing("tok", None)` devolve `"abc"`.
- [ ] `FakeMetadataStore().save(extractor)` seguido de `.load(extractor.token_id)` devolve o mesmo objeto (por igualdade de campos, não identidade).
- [ ] `FakeProcess(returncode=None).poll()` devolve `None`; após `terminate()` + definir `returncode=0`, `poll()` devolve `0`.
- [ ] Nenhum destes arquivos é importado por `har_reproducer/` (só por `tests/`).

---

## [T02] — `SessionStore`: `set_token`/`get_token`/`render`/`render_dict`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_session_store.py` (novo).

**Contexto:**
`SessionStore` (`har_reproducer/session/session_store.py:8-41`) é o ponto único onde um
`token_id` (hash) vira valor literal num template de curl — usado real (não dublado) em quase
todos os outros testes desta etapa (spec D.3), então merece cobertura direta própria primeiro.

**Estado atual:**
- `set_token`/`get_token` leem/escrevem `self.state.tokens` (`session_store.py:14-20`).
- `render(template)` substitui `{{extractor:<hex>}}` via `TOKEN_PLACEHOLDER_PATTERN.sub`
  (`session_store.py:22-24,36-40`); se `token_id` não está em `self.state.tokens`, o
  placeholder original é preservado (`match.group(0)`, linha 40).
- `render_dict(data)` percorre recursivamente dict/list/str e chama `render` em cada string
  folha; outros tipos (int, None, ...) retornam sem alteração (`session_store.py:26-34`).

**Estado esperado depois:**
- Teste cobre: `set_token`+`get_token` round-trip; `render` com token presente (substitui) e
  ausente (placeholder preservado); `render_dict` em dict aninhado com listas, strings e um
  valor não-string (ex.: `int`) misturados.

**Critérios de aceite:**
- [ ] `store.set_token("abc123", "v1"); store.get_token("abc123") == "v1"`.
- [ ] `store.render("Bearer {{extractor:abc123}}")` após `set_token("abc123", "tok")` devolve `"Bearer tok"`.
- [ ] `store.render("{{extractor:naoexiste}}")` sem `set_token` prévio devolve a string idêntica (placeholder preservado).
- [ ] `store.render_dict({"a": ["{{extractor:x}}", 3], "b": {"c": "{{extractor:x}}"}})` após `set_token("x", "V")` devolve `{"a": ["V", 3], "b": {"c": "V"}}` (o `3` não é tocado).

---

## [T03] — `BaselineDiff`: `compare`, `_diff_*`, `detect_candidates`, `_determine_location`, `extract_static_values`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_baseline_diff.py` (novo).

**Contexto:**
`BaselineDiff` é o ponto de partida da descoberta de tokens dinâmicos — compara o `Step` atual
contra o baseline (primeira entry do HAR) e não assume nada sobre o que é "token de sessão"
(princípio de genericidade, `arquitetura-e-fundamentos`). É puro (sem I/O, sem colaborador),
então testável direto com `StepRequest`/`Step` construídos à mão.

**Estado atual:**
- `compare` funde `_diff_url`/`_diff_headers`/`_diff_cookies`/`_diff_body` num único dict
  `path -> value` (`baseline_diff.py:9-15`).
- `_diff_url` só reporta `{"url": ...}` se a URL mudou (linhas 17-21); `_diff_headers`/
  `_diff_cookies` reportam `header:<k>`/`cookie:<k>` para toda chave cujo valor mudou ou não
  existe no baseline (linhas 23-37); `_diff_body` devolve `{}` se qualquer um dos dois bodies é
  falsy ou se são iguais, senão decodifica bytes com `errors="replace"` (linhas 39-50).
- `detect_candidates` mapeia cada `(path, value)` para um `DynamicToken` via `_build_candidate`,
  com `token_id` provisório = `md5(path)`, `status="UnderReview"`, `origin_step=None` (linhas
  52-66).
- `_determine_location` decide `TokenLocation` só pelo prefixo textual do `path`
  (`url`/`header:`/`cookie:`), com `BODY_JSON` como fallback (linhas 68-76).
- `extract_static_values` é o espelho de `_diff_headers`, mas para headers que **não** mudaram
  (linhas 78-84).

**Estado esperado depois:**
- Teste cobre cada `_diff_*` isoladamente (via `compare`, já que são privados) e os dois casos
  de borda documentados na spec (`body=None` de um lado; `body` bytes não-UTF8).

**Critérios de aceite:**
- [ ] Dois `Step` com URLs diferentes → `compare(...)` inclui `{"url": <url do step>}`.
- [ ] Header presente só no step atual (ausente no baseline) → aparece em `compare` como `header:<nome>`; header idêntico em ambos → não aparece.
- [ ] `step.request.body=None`, `baseline.request.body="x"` (ou vice-versa) → `_diff_body` não contribui nenhuma chave (via `compare`).
- [ ] `body=b"\xff\xfe"` (bytes não-UTF8) → `compare()["body"]` é uma `str` decodificada com `errors="replace"`, sem lançar exceção.
- [ ] `detect_candidates({"cookie:sid": "abc"})` devolve uma lista com um `DynamicToken` de `destination_location=TokenLocation.COOKIE`, `status="UnderReview"`, `origin_step=None`.
- [ ] `extract_static_values`: header igual em `step` e `baseline` aparece no retorno; header que mudou não aparece (comportamento oposto de `_diff_headers`).

---

## [T04] — `PlaceholderApplier`: ordenação por tamanho e substituição em url/headers/cookies/body

**Depende de:** Nenhuma (usa `SessionStore` real, já implementado em produção).
**Arquivos envolvidos:** `tests/unit/test_placeholder_applier.py` (novo).

**Contexto:**
`PlaceholderApplier` substitui o valor literal de um token pelo placeholder `{{extractor:<id>}}`
no `StepRequest` antes de gerar o curl — só para tokens cujo extractor já foi verificado
(`session_store.state.registry`). Recebe `SessionStore` por construtor (costura B); a spec (D.3)
decide usar `SessionStore` real nos testes em vez de dublê.

**Estado atual:**
- `apply` ordena os tokens por tamanho decrescente de `current_value` antes de substituir
  (`placeholder_applier.py:12-18`) — evita que um valor curto seja substituído "dentro" de um
  valor maior que o contém.
- `_apply_token`: pula token com `current_value` vazio (linha 21-22) e token sem extractor
  verificado no registry (`_verified_extractor`, linhas 24-26,34-38).
- `_replace_in_body`: bytes indecodáveis (`UnicodeDecodeError`) permanecem intactos (linhas
  72-79); string decodificável e contendo o valor é substituída e recodificada para bytes.

**Estado esperado depois:**
- Teste monta `SessionStore` real, registra um `Extractor(verified=True)` para um `token_id`, e
  chama `apply` com uma lista de `DynamicToken`. Cobre: substituição em url/header/cookie;
  ordenação por tamanho (dois tokens onde um valor é substring do outro); token não verificado
  não é tocado; valor vazio é pulado; body `str` substituído; body `bytes` UTF-8 substituído;
  body `bytes` não-UTF8 permanece idêntico.

**Critérios de aceite:**
- [ ] Token com `current_value="abc"` e extractor `verified=True` no registry → aparece como `{{extractor:<token_id>}}` na URL/header/cookie que continha `"abc"`.
- [ ] Dois tokens, `"abc"` e `"abcdef"` (um contém o outro) → depois de `apply`, nenhuma ocorrência de `"abcdef"` sobra parcialmente substituída (o mais longo é processado primeiro).
- [ ] Token sem entrada em `session_store.state.registry` (nunca registrado) → valor original permanece intacto no request.
- [ ] Token com `current_value=""` → `_apply_token` não altera nada (sem erro).
- [ ] `request.body = b"\xff\xfe"` (não decodifica em UTF-8) com token cujo valor "aparece" só depois de decodificado → body permanece `b"\xff\xfe"` inalterado.

---

## [T05] — `CurlGenerator`: `generate`, `_curl_parts`, `_token_comments`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_curl_generator.py` (novo).

**Contexto:**
`CurlGenerator.generate` monta o texto do template de curl (ainda com placeholders, resolvidos
depois por `SessionStore.render`) e os comentários de proveniência de cada token — os
comentários são o que `CurlDependencyParser` (T06) e `ReplayRunner._mark_token_static` (T22)
consomem depois.

**Estado atual:**
- `generate` prefixa o bloco de curl com uma linha de comentário por token com `origin_step`
  não `None`; sem tokens comentáveis, devolve só o `curl_block` (`curl_generator.py:9-15`).
- `_token_comments`: pula token com `origin_step is None` (linha 61-62); adiciona uma segunda
  linha "origin location undetermined" se `origin_location is None` (linhas 64-65), ou "origin
  location determined but extraction exhausted" se `extraction_exhausted=True` (linhas 66-70) —
  as três variantes de comentário citadas na spec.
- `_curl_parts`: request line + URL quotado + headers (`-H`) + cookies (`--cookie`, só se houver
  cookies) + body (`--data-binary`, só se houver body) (linhas 17-26).

**Estado esperado depois:**
- Teste cobre as 3 variantes de comentário (nenhum, "undetermined", "exhausted") e a montagem do
  curl (headers múltiplos, cookies ausentes vs. presentes, body ausente vs. presente).

**Critérios de aceite:**
- [ ] `DynamicToken(origin_step=None, ...)` → nenhuma linha de comentário é gerada para ele.
- [ ] `DynamicToken(origin_step=2, origin_location=None, ...)` → gera duas linhas: a de proveniência e a de "origin location undetermined".
- [ ] `DynamicToken(origin_step=2, origin_location=TokenLocation.COOKIE, extraction_exhausted=True, ...)` → gera a linha de proveniência e a de "extraction exhausted".
- [ ] `StepRequest` sem cookies → `generate(...)` não contém `--cookie` na saída.
- [ ] `StepRequest` com `body="payload"` → saída contém `--data-binary` com o payload quotado (`shlex.quote`).
- [ ] Nenhum token comentável → primeira linha da saída começa com `curl -X`.

---

## [T06] — `CurlDependencyParser.parse`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_curl_dependency_parser.py` (novo).

**Contexto:**
`CurlDependencyParser.parse` lê de volta os comentários que `CurlGenerator._token_comments`
escreve (T05) para reconstruir `token_id -> origin_step` num `.curl.sh` já persistido — usado
pelo `replay` para saber de onde reler a resposta de origem de cada token.

**Estado atual:**
`DEPENDENCY_PATTERN` (`curl_dependency_parser.py:7-10`) casa exatamente
`# Token <id> comes from response of step <n>`, com `re.MULTILINE`; `parse` devolve um dict
`{token_id: origin_step}` para cada match (linhas 12-16). Só a primeira linha de cada token
(a de proveniência) casa — as linhas extras ("undetermined"/"exhausted") não têm esse formato e
são ignoradas naturalmente pela regex.

**Estado esperado depois:**
Teste cobre: texto com uma dependência; texto com múltiplas; texto sem nenhuma linha de
comentário (dict vazio); texto com uma linha "extraction exhausted" extra (não deve virar uma
entrada espúria no dict).

**Critérios de aceite:**
- [ ] `parse("# Token abc123 comes from response of step 4\ncurl ...")` devolve `{"abc123": 4}`.
- [ ] `parse("curl -X GET ...")` (sem comentários) devolve `{}`.
- [ ] Texto com duas linhas de proveniência de tokens diferentes → dict com as duas entradas.
- [ ] Texto com a linha extra `# Token abc123 origin location determined but extraction exhausted — using literal captured value` logo abaixo da linha de proveniência → o dict tem só a entrada de `abc123: <step>`, sem entrada espúria para a segunda linha.

---

## [T07] — `StepSkipEvaluator.skip_reason`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_step_skip_evaluator.py` (novo).

**Contexto:**
Decide, por step, se ele deve ser pulado (scheme inválido ou método configurado em
`SkipRulesConfig.methods`) antes de qualquer descoberta de token rodar para aquele step.

**Estado atual:**
`ALLOWED_SCHEMES = {"http", "https"}` (`step_skip_evaluator.py:8`); `skip_reason` normaliza o
scheme via `urlparse(...).scheme.lower()` antes de comparar (linha 14) — então `"HTTPS://..."`
não é pulado por scheme; devolve `"unsupported scheme '<scheme>'"` só se o scheme normalizado
não está no set; senão devolve `"skippable method '<method>'"` se `request.method` está em
`skip_rules.methods`; senão `None` (linhas 13-19).

**Estado esperado depois:**
Teste com `SkipRulesConfig` real (não dublê, é modelo pydantic simples) cobrindo: scheme válido
minúsculo; scheme válido maiúsculo (`HTTPS`); scheme inválido (`ftp`); URL sem scheme
(`urlparse("").scheme == ""`); método presente em `skip_rules.methods`; método ausente.

**Critérios de aceite:**
- [ ] `skip_reason(StepRequest(url="https://x", method="GET"))` com `SkipRulesConfig()` padrão devolve `None`.
- [ ] `skip_reason(StepRequest(url="HTTPS://x", method="GET"))` devolve `None` (case-insensitive).
- [ ] `skip_reason(StepRequest(url="ftp://x", method="GET"))` devolve `"unsupported scheme 'ftp'"`.
- [ ] `skip_reason(StepRequest(url="/relative/path", method="GET"))` (sem scheme) devolve `"unsupported scheme ''"`.
- [ ] `skip_reason(StepRequest(url="https://x", method="OPTIONS"))` com `SkipRulesConfig()` padrão (`methods=["OPTIONS"]`) devolve `"skippable method 'OPTIONS'"`.

---

## [T08] — `StepRetryPolicy.execute`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_step_retry_policy.py` (novo).

**Contexto:**
Controla o loop de retentativa de um step (até `MAX_STEP_ATTEMPTS=2`) chamando `attempt_fn` e,
se a última tentativa não foi a final, `recovery_fn` para decidir se tenta de novo — usado tanto
por `Engine.execute_step` quanto por `ReplayRunner._run_step`.

**Estado atual:**
`execute` (`step_retry_policy.py:10-23`) itera `range(MAX_STEP_ATTEMPTS)`; se não é a última
tentativa e `recovery_fn(response)` devolve `True`, continua o loop (chama `attempt_fn` de
novo); senão retorna a `response` da tentativa atual. Se todas as tentativas forem consumidas
sem retornar (não deveria acontecer no fluxo normal, já que a última iteração sempre retorna),
levanta `RuntimeError`.

**Estado esperado depois:**
Teste com `attempt_fn`/`recovery_fn` como funções fake locais (lambdas ou closures simples, sem
precisar dos dublês de T01) cobrindo: sem necessidade de retry (recovery sempre `False`); um
retry bem-sucedido (recovery `True` na primeira, `False`/não-chamado na segunda); nunca mais de
`MAX_STEP_ATTEMPTS` chamadas a `attempt_fn`, mesmo que `recovery_fn` sempre devolva `True`.

**Critérios de aceite:**
- [ ] `attempt_fn` que sempre devolve `StepResponse(status_code=200)`, `recovery_fn` sempre `False` → `execute` chama `attempt_fn` uma vez e devolve a resposta 200.
- [ ] `attempt_fn` que devolve `401` na 1ª chamada e `200` na 2ª, `recovery_fn` que devolve `True` para `401` → `execute` devolve a resposta `200`, com `attempt_fn` chamado exatamente 2 vezes.
- [ ] `attempt_fn` sempre devolve `401`, `recovery_fn` sempre `True` → `attempt_fn` é chamado exatamente `MAX_STEP_ATTEMPTS=2` vezes (a última tentativa é devolvida mesmo com `recovery_fn` ainda dizendo `True`, porque `is_last_attempt` bloqueia mais uma volta).

---

## [T09] — `ResponseGrep`: `try_decode`, `value_variants`, `_deduplicate`, `_extract_step_index`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_response_grep_helpers.py` (novo).

**Contexto:**
Só a parte pura de `ResponseGrep` entra aqui — `find`/`_grep_single_pattern` rodam `grep` de
verdade e ficam fora de escopo (spec, "Fora de escopo"). Estes 4 métodos preparam as variantes
de um valor (URL-decodificado, URL-encodado, base64) que `find` tenta casar, e são puros sobre
strings.

**Estado atual:**
- `try_decode` (`response_grep.py:23-39`): tenta `unquote` e, se mudar, usa o resultado; depois
  tenta decodificar como base64 estrito (`validate=True`) — só aceita se o resultado for UTF-8
  válido e "printable"; qualquer falha (não é base64 válido, decode falha, não é printable) é
  engolida por um `except Exception: pass` e o valor não muda.
- `value_variants` (linhas 41-49): monta `[value, try_decode(value), quote(value), b64encode(value)]`
  e deduplica preservando ordem via `_deduplicate` (linhas 51-59), que descarta strings vazias
  também.
- `_extract_step_index` (linhas 93-100): extrai o índice de `res_0007.json` → `7`; nome de
  arquivo fora do padrão (`IndexError`/`ValueError`) devolve `None` com `print` de aviso.

**Estado esperado depois:**
Teste cobre um valor sem nenhuma codificação especial (todas as variantes distintas do
original, exceto quando coincidem), um valor URL-encoded, um valor base64 válido, e a extração
de índice válida/inválida.

**Critérios de aceite:**
- [ ] `try_decode("valor-simples")` devolve `"valor-simples"` (nenhuma decodificação muda o valor).
- [ ] `try_decode("valor%20com%20espaco")` devolve `"valor com espaco"`.
- [ ] `try_decode(base64.b64encode(b"segredo").decode())` devolve `"segredo"`.
- [ ] `value_variants("abc")` não contém strings duplicadas nem vazias.
- [ ] `_extract_step_index("res_0007.json")` devolve `7`; `_extract_step_index("nomeinvalido.json")` devolve `None`.

---

## [T10] — `TokenLocationDetector.find` e heurísticas

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_token_location_detector.py` (novo).

**Contexto:**
Decide em qual `TokenLocation` um valor foi encontrado dentro de uma resposta amostrada — só
depois de checar a evidência real (headers → cookies → redirect → body), nunca por suposição de
`content-type` (princípio de genericidade). É `@classmethod` puro sobre um dict
`response_sample`, sem I/O.

**Estado atual:**
`find` tenta, em ordem, `_find_in_headers` → `_find_in_cookies` → `_find_in_redirect_url` →
`_find_in_body`, devolvendo o primeiro `TokenLocation` não-`None` (`token_location_detector.py:11-30`);
sem nenhum achado, `print` de aviso e `None`. Dentro do body: `SCRIPT` se o mime indica
javascript (linha 70-71); `BODY_JSON` se mime indica json OU o body é JSON válido (linha 73-75);
`BODY_HTML`/`SCRIPT` se mime indica html OU o body "parece" HTML por regex (linhas 77-79,90-92)
— `_locate_in_html` prefere `BODY_HTML` a menos que o valor só apareça dentro de um bloco
`<script>` (linhas 82-88).

**Estado esperado depois:**
Teste cobre pelo menos um `response_sample` por branch: header, cookie, redirect_url, body JSON
(por mime e por conteúdo sem mime), body HTML (valor fora de `<script>`), body em `<script>`
(valor só dentro do bloco), e nenhuma correspondência (→ `None`).

**Critérios de aceite:**
- [ ] `find("tok", {"headers": {"X-Csrf": "tok"}})` devolve `TokenLocation.HEADER`.
- [ ] `find("tok", {"cookies": {"sid": "tok"}})` devolve `TokenLocation.COOKIE`.
- [ ] `find("tok", {"redirect_url": "https://x?tok=tok"})` devolve `TokenLocation.URL_PARAM`.
- [ ] `find("tok", {"body": '{"csrf":"tok"}', "body_mime": None})` devolve `TokenLocation.BODY_JSON` (detectado por conteúdo, sem depender do mime).
- [ ] `find("tok", {"body": "<html><body>tok</body></html>", "body_mime": "text/html"})` devolve `TokenLocation.BODY_HTML`.
- [ ] `find("tok", {"body": "<html><script>var x='tok';</script></html>", "body_mime": "text/html"})` devolve `TokenLocation.SCRIPT` (valor só aparece dentro do `<script>`).
- [ ] `find("tok", {})` (nenhum campo) devolve `None`.

---

## [T11] — `Workspace`: construção e helpers de caminho

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_workspace.py` (novo).

**Contexto:**
Costura central da Etapa B — `Workspace(output_dir)` deixou de ser singleton; cada teste que
precisa de FS real constrói sua própria instância sob `tmp_path`, sem interferência entre
instâncias.

**Estado atual:**
`__init__` (`workspace.py:8-20`) cria `output_dir` e materializa eagerly 8 subdiretórios
(`curls`, `real_responses`, `original_responses`, `real_requests`, `extractors`,
`temp_extractors`, `mitm_capture`, `replays`) como atributos `Path`. Os 11 métodos de caminho
(`temp_extractor_file`, `extractor_file`, `extractor_meta_file`, `request_file`,
`response_file`, `original_response_file`, `mitm_capture_file`, `mitm_log_file`, `curl_file`,
`replay_run_dir`, `replay_response_file`) formatam nomes com zero-padding de 4 dígitos
(`f"res_{index:04d}.json"`) onde aplicável; `replay_run_dir` cria o diretório na hora
(`path.mkdir(parents=True, exist_ok=True)`, linha 65).

**Estado esperado depois:**
Teste cobre: os 8 subdiretórios existem após `__init__`; duas instâncias com `tmp_path`
diferentes não compartilham estado; cada método de path devolve o `Path` esperado com
zero-padding correto; `replay_run_dir` cria o diretório de fato.

**Critérios de aceite:**
- [ ] `Workspace(tmp_path)` — todos os 8 atributos (`.curls`, `.real_responses`, etc.) existem em disco (`Path.is_dir()`) logo após a construção.
- [ ] `Workspace(tmp_path_a)` e `Workspace(tmp_path_b)` (dois `tmp_path` distintos) não compartilham nenhum arquivo — escrever em um não afeta o outro.
- [ ] `workspace.response_file(7) == workspace.real_responses / "res_0007.json"`.
- [ ] `workspace.curl_file(3) == workspace.curls / "req_0003.curl.sh"`.
- [ ] `workspace.replay_run_dir("run-1").is_dir()` é `True` (diretório criado na chamada, não só o path calculado).

---

## [T12] — `ExtractorMetadataStore`: `load`/`save`, arquivo ausente, JSON inválido

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_extractor_metadata_store.py` (novo).

**Contexto:**
Persiste/recupera o `Extractor` (metadados de um token já resolvido) em
`extractor_meta_file(token_id)`; usado por `CandidateResolver` (T17) para decidir se um slot já
tem extractor persistido.

**Estado atual:**
`load` (`extractor_metadata_store.py:12-20`): arquivo ausente → `None` sem erro; JSON inválido
ou incompatível com `Extractor` → `except Exception` amplo, `print` de aviso, `None`. `save`
(linhas 22-24) sobrescreve o arquivo sempre, sem merge.

**Estado esperado depois:**
Teste usa `Workspace(tmp_path)` real (sem dublê — é I/O do próprio alvo). Cobre: `load` sem
arquivo; `save` seguido de `load` (round-trip); arquivo com JSON corrompido/incompatível.

**Critérios de aceite:**
- [ ] `store.load("naoexiste")` devolve `None` sem lançar exceção.
- [ ] `store.save(Extractor(token_id="t1", code="...", agent_type=AgentType.REGEX)); store.load("t1")` devolve um `Extractor` com os mesmos campos.
- [ ] Escrever texto não-JSON diretamente em `workspace.extractor_meta_file("t2")` e depois chamar `store.load("t2")` devolve `None` (sem propagar a exceção de parse).

---

## [T13] — `ExtractorRunner`: `run`, `run_existing`, `_execute_extractor_script`, `_build_env`

**Depende de:** T01 (usa `FakeScriptExecutor`).
**Arquivos envolvidos:** `tests/unit/test_extractor_runner.py` (novo).

**Contexto:**
Escreve o script Python do extractor em disco e delega a execução ao `ScriptExecutor` injetado
— a costura B que permite testar sem `subprocess` real.

**Estado atual:**
`run` (`extractor_runner.py:18-21`) escreve o script via `_write_extractor_script`, que levanta
`ValueError` se `extractor.origin_step is None` (linhas 33-35); depois limpa o arquivo temp
(`_cleanup_temp_file`) e executa via `_execute_extractor_script`. `run_existing` (linhas 23-31)
devolve `None` direto se o arquivo do extractor não existe em disco, sem tentar executar.
`_execute_extractor_script` (linhas 54-69): qualquer exceção do `script_executor.run(...)` é
engolida (`except Exception: return None`); `return_code != 0` → `None`; senão devolve
`stdout.strip()`. `_build_env` injeta `HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR` no ambiente só se
`response_override_dir` não é `None` (linhas 71-76).

**Estado esperado depois:**
Teste usa `Workspace(tmp_path)` real (precisa dos diretórios `extractors`/`temp_extractors`) e
`FakeScriptExecutor` (T01) para controlar o resultado da execução sem `subprocess` real.

**Critérios de aceite:**
- [ ] `run(Extractor(origin_step=None, ...))` levanta `ValueError`.
- [ ] `run_existing("token-sem-arquivo")` devolve `None` sem chamar `script_executor.run` (verificar `fake_script_executor.calls == []`).
- [ ] `FakeScriptExecutor` configurado com `return_code=0, stdout="  valor  \n"` → `run(...)` devolve `"valor"` (stripped).
- [ ] `FakeScriptExecutor` configurado com `return_code=1` → `run(...)` devolve `None`.
- [ ] `FakeScriptExecutor` configurado para lançar exceção em `.run(...)` → `_execute_extractor_script` não propaga, devolve `None`.
- [ ] `_build_env(None)` não contém `HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR`; `_build_env(Path("/x"))` contém essa chave com valor `"/x"`.

---

## [T14] — `ScriptExecutor.run`: subprocess real, timeout e retorno

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_script_executor.py` (novo).

**Contexto:**
Única unidade desta etapa que roda `subprocess` de verdade (spec, Suposições) — é a própria
unidade sob teste, então não faz sentido dublar. Scripts de teste são triviais (`print` e
`sys.exit`), então a suíte continua rápida (<1s por caso).

**Estado atual:**
`run` (`script_executor.py:13-37`) executa `[sys.executable, script_path]` capturando
stdout/stderr como texto; em `subprocess.TimeoutExpired`, devolve
`ScriptExecutionResult(timed_out=True, return_code=TIMEOUT_RETURN_CODE=-1, stdout="", stderr="")`;
caso contrário devolve o resultado real com `timed_out=False`.

**Estado esperado depois:**
Teste escreve scripts Python triviais em `tmp_path` (`print("ok")`, `import sys; sys.exit(3)`,
`import time; time.sleep(5)`) e chama `run` de verdade.

**Critérios de aceite:**
- [ ] Script `print("hello")` com `timeout_seconds=5` → `result.return_code == 0`, `result.stdout.strip() == "hello"`, `result.timed_out is False`.
- [ ] Script `import sys; sys.exit(3)` → `result.return_code == 3`.
- [ ] Script `import time; time.sleep(2)` com `timeout_seconds=0.1` → `result.timed_out is True`, `result.return_code == ScriptExecutor.TIMEOUT_RETURN_CODE == -1`.
- [ ] `env={"MY_VAR": "x"}` passado a um script que faz `import os; print(os.environ.get("MY_VAR"))` → `result.stdout.strip() == "x"`.

---

## [T15] — `Validator`: `validate`/`_check_criterion`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_validator.py` (novo).

**Contexto:**
Checa os `success_criteria` do `config.json` contra a última resposta não pulada de um `run`.
Classe sem `__init__`, só `@staticmethod`s sobre modelos pydantic — puro, sem I/O nem
colaborador, então mais simples que vários alvos já no escopo P0 (spec, achado da auditoria).

**Estado atual:**
`validate` (`validator.py:18-24`) é um AND lógico de `_check_criterion` sobre a lista de
critérios (curto-circuita no primeiro `False`). `_check_criterion` (linhas 26-47) despacha por
`isinstance` entre os 4 tipos de `SuccessCriterion` (`StatusCodeCriterion`, `UrlMatchCriterion`,
`BodyContainsCriterion`, `HtmlElementPresentCriterion`), cada um comparando um campo diferente
de `StepResponse`; `UrlMatchCriterion` usa `re.search` sobre `response.redirect_url or ""`;
`BodyContainsCriterion` usa substring simples só se `response.body` é `str`;
`HtmlElementPresentCriterion` usa `BeautifulSoup(...).select_one(criterion.expected)`.

**Estado esperado depois:**
Teste cobre os 4 tipos de critério (caso verdadeiro e falso cada) e `validate` com lista mista
(um critério falso já barra o resultado, independente dos outros).

**Critérios de aceite:**
- [ ] `StatusCodeCriterion(type="status_code", expected=200)` com `StepResponse(status_code=200)` → `True`; com `status_code=404` → `False`.
- [ ] `UrlMatchCriterion(type="url_match", expected="dashboard")` com `redirect_url="https://x/dashboard"` → `True`; com `redirect_url=None` → `False` (compara contra string vazia).
- [ ] `BodyContainsCriterion(type="body_contains", expected="ok")` com `body="status: ok"` → `True`; com `body=b"status: ok"` (bytes, não `str`) → `False` (guard explícito do código).
- [ ] `HtmlElementPresentCriterion(type="html_element_present", expected="#success")` com `body="<div id='success'></div>"` → `True`; com body sem esse elemento → `False`.
- [ ] `validate(response, [criterio_verdadeiro, criterio_falso])` devolve `False` (não avalia importância de ordem, só que basta um falso).
- [ ] ⚠️ Não escrever teste para o `return False` final de `_check_criterion` (linha 47) — é inalcançável dado que `SuccessCriterion` é um `Union` discriminado com exatamente os 4 tipos acima (`models/criteria.py:26-32`); registrar isso como comentário de spec, não como caso de teste (spec, Casos de borda).

---

## [T16] — `HARParser`: `decode_body`, `parse_entry`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_har_parser.py` (novo).

**Contexto:**
Transforma uma `entry` crua de um `.har` (dict Python) num `Step`/`StepRequest`/`StepResponse`
tipado. `load_har`/`get_entries`/`split_har` (I/O real de arquivo) ficam fora de escopo — já
exercitados pelos 39 golden via `main()` — mas `decode_body`/`parse_entry` são puros sobre
dicts e não têm motivo para ficar de fora (spec, achado da auditoria).

**Estado atual:**
`decode_body` (`har_parser.py:27-40`): `body_content` falsy → `""` sem checar `encoding`;
`encoding == "base64"` tenta decodificar, e qualquer falha (`except Exception`) devolve o
`body_content` original intacto com `print` de aviso; qualquer outro `encoding` (incluindo
`None`) devolve `body_content` sem alteração. `parse_entry` (linhas 42-82) monta
`StepRequest`/`StepResponse`/`Step` a partir dos dicts `request`/`response` de uma entry HAR,
usando `decode_body` para o body da resposta.

**Estado esperado depois:**
Teste monta dicts mínimos simulando uma `entry` de HAR (sem precisar de arquivo `.har` real) e
chama `parse_entry`/`decode_body` diretamente.

**Critérios de aceite:**
- [ ] `decode_body("", encoding=None)` devolve `""`.
- [ ] `decode_body(base64.b64encode(b"ok").decode(), encoding="base64")` devolve `"ok"`.
- [ ] `decode_body("!!!not-base64!!!", encoding="base64")` devolve o próprio `"!!!not-base64!!!"` (fallback ao original, sem lançar exceção).
- [ ] `parse_entry({"request": {"url": "https://x", "method": "GET", "headers": [], "cookies": []}, "response": {"status": 200, "headers": [], "cookies": [], "content": {"text": "body", "mimeType": "text/plain"}}}, index=3)` devolve um `Step(index=3, ...)` com `request.url == "https://x"`, `response.status_code == 200`, `response.body == "body"`.
- [ ] `entry["request"]["postData"] = {"text": "payload"}` → `parse_entry(...).request.body == "payload"`.

---

## [T17] — `CandidateResolver`: cadeia `_find_slot`/`_check_slot`/`_check_cached_slot`/`_check_persisted_slot`/`_accept_persisted_slot` e helpers puros

**Depende de:** T01 (usa `FakeExtractorRunner`, `FakeMetadataStore`).
**Arquivos envolvidos:** `tests/unit/test_candidate_resolver.py` (novo).

**Contexto:**
Alvo prioritário apontado pela spec da Etapa A (§3.9) e reafirmado pela spec desta etapa: só
esta fatia de `CandidateResolver` é testável sem disco/grep reais, porque só toca colaboradores
injetados (`extractor_runner`, `metadata_store`, `session_store`) — nunca `ResponseGrep` nem
leitura direta de `res_NNNN.json`. `_process_candidate`/`_find_origin`/`_load_response` ficam
fora de escopo (spec, "Fora de escopo").

**Estado atual:**
- `_find_slot` (`candidate_resolver.py:72-85`): tenta `base_token_id` primeiro; em `MISMATCH`,
  faz fork (`_fork_token_id(base_token_id, attempt)`) e tenta de novo, acumulando o último
  `error` em `last_error`; em `FREE`, retorna o slot atual junto com `last_error` acumulado (não
  `None`, mesmo que o slot atual seja livre) — é o comportamento citado na spec como caso de
  borda; em `MATCH`, retorna sem erro.
- `_check_slot` → `_check_cached_slot` (dict em memória `_validated_values`) primeiro; se não
  achar, cai para `_check_persisted_slot` (usa `metadata_store.load` + `extractor_runner.run_existing`).
- `_check_cached_slot` (linhas 93-101): sem entrada em cache → `None` (delega ao persisted);
  valor em cache igual ao candidato → `MATCH`; diferente → `MISMATCH` com `_mismatch_error`.
- `_check_persisted_slot` (linhas 103-113): sem extractor persistido → `FREE`; extractor
  persistido mas `run_existing` não bate com `candidate.current_value` → `MISMATCH`; bate →
  `_accept_persisted_slot` (grava no registry, `session_store.set_token`, cache local) e
  `MATCH`.
- `_mismatch_error` (linhas 139-143): `result is None` → mensagem de "failed to execute";
  senão mensagem com `repr` de got/expected.

**Estado esperado depois:**
Teste constrói `CandidateResolver(responses_dir=tmp_path, session_store=SessionStore(),
extractor_runner=FakeExtractorRunner(...), metadata_store=FakeMetadataStore(),
agent_factory=<não usado nesta fatia>)` e chama os métodos privados diretamente (aceitável em
teste unitário: são o alvo documentado pela spec da Etapa A).

**Critérios de aceite:**
- [ ] `_check_cached_slot` com `_validated_values={"t1": "v1"}` e `candidate.current_value="v1"` → `(MATCH, None)`.
- [ ] Idem com `candidate.current_value="v2"` → `(MISMATCH, <mensagem com repr de "v1" e "v2">)`.
- [ ] `_check_persisted_slot` com `FakeMetadataStore` sem nenhum extractor salvo para o slot → `(FREE, None)`.
- [ ] `_check_persisted_slot` com extractor persistido e `FakeExtractorRunner.run_existing` devolvendo o mesmo valor do candidato → `(MATCH, None)`, e depois disso `session_store.get_token(slot_id)` devolve esse valor (efeito de `_accept_persisted_slot`).
- [ ] `_check_persisted_slot` com `run_existing` devolvendo `None` → `(MISMATCH, "Persisted extractor failed to execute (no output).")`.
- [ ] `_find_slot`: forçar `_check_slot` a devolver `MISMATCH` na primeira chamada e `FREE` na segunda (via `FakeMetadataStore`/`FakeExtractorRunner` configurados por chamada) → o `slot_id` final é o "forkado" (`_fork_token_id`), e o `last_error` devolvido é o erro do `MISMATCH` da primeira tentativa (não `None`).
- [ ] `_derive_token_id("cookie:sid", 2)` é determinístico (mesmo input → mesmo hash) e difere de `_derive_token_id("cookie:sid", 3)`.
- [ ] `_build_literal_extractor`: `Extractor.verified is True`, `agent_type` é o passado, `code` contém `return <repr do current_value>`.

---

## [T18] — `TokenResolver`: `resolve_all`, `_should_refresh_token`, `_refresh_token`

**Depende de:** T01 (usa `FakeExtractorRunner`).
**Arquivos envolvidos:** `tests/unit/test_token_resolver.py` (novo).

**Contexto:**
Resolve os tokens pendentes de um step populando `SessionStore.state.tokens`, chamado depois de
`TokenTracker.analyze_step` e de novo (com `force=True`) em `Engine.handle_recovery`.

**Estado atual:**
`resolve_all(force=False)` (`token_resolver.py:15-20`) itera `session_store.state.registry`;
sem `force`, pula token já presente em `state.tokens` (já resolvido nesta rodada);
`_should_refresh_token` exige `extractor.verified and extractor.origin_step is not None`
(linhas 22-23); `_refresh_token` (linhas 25-36) primeiro checa se o arquivo de resposta de
origem existe em `responses_dir` (sem I/O real na costura — usa `Path.exists()` sobre
`responses_dir` que o teste controla via `tmp_path`), sem ele retorna sem tentar; senão chama
`extractor_runner.run(...)`, engolindo qualquer exceção (`print` + `return`); se o valor
retornado é truthy, `session_store.set_token(...)`.

**Estado esperado depois:**
Teste usa `SessionStore` real e `FakeExtractorRunner` (T01); `responses_dir` é um `tmp_path`
onde o teste cria (ou não) o arquivo `res_NNNN.json` esperado.

**Critérios de aceite:**
- [ ] Registry com um extractor `verified=False` → `resolve_all()` não chama `extractor_runner.run` (token não é candidato a refresh).
- [ ] Registry com extractor `verified=True, origin_step=2`, mas `responses_dir` sem `res_0002.json` → `_refresh_token` não chama `extractor_runner.run` (retorna cedo).
- [ ] Registry com extractor válido, `res_0002.json` existente (criado vazio no `tmp_path`), `FakeExtractorRunner.run` devolvendo `"novo-valor"` → depois de `resolve_all()`, `session_store.get_token(token_id) == "novo-valor"`.
- [ ] `FakeExtractorRunner.run` configurado para lançar exceção → `resolve_all()` não propaga a exceção.
- [ ] `force=False` e o token já está em `state.tokens` → `extractor_runner.run` não é chamado (pulado antes mesmo de checar `_should_refresh_token`); `force=True` com o mesmo estado → é chamado.

---

## [T19] — `TokenTracker.analyze_step`: orquestração dos 4 colaboradores

**Depende de:** T01 (padrão de dublê reaproveitado; os fakes específicos de `BaselineDiff`/`CandidateResolver`/`PlaceholderApplier`/`CurlGenerator` são pequenos o bastante para ficar locais ao teste, mas seguem a mesma convenção de T01).
**Arquivos envolvidos:** `tests/unit/test_token_tracker.py` (novo).

**Contexto:**
Testa só a orquestração (ordem de chamadas e propagação de retorno entre colaboradores) sem
descer a nenhum deles de verdade — os 4 colaboradores são 100% injetados por construtor
(costura B), então dublês totais bastam.

**Estado atual:**
`analyze_step` (`token_tracker.py:24-37`) executa, em ordem fixa:
`baseline_diff.compare` → `baseline_diff.detect_candidates` → `candidate_resolver.resolve` →
`placeholder_applier.apply` (efeito colateral em `step.request`, sem retorno usado) →
`curl_generator.generate` → `baseline_diff.extract_static_values`, montando um `StepAnalysis`
com os resultados de `candidate_resolver.resolve` e `curl_generator.generate`.

**Estado esperado depois:**
Teste com 4 dublês manuais (classes locais no arquivo de teste ou em `tests/support/`, decisão
livre desde que sigam o guia de estilo) que registram se foram chamados e com quê, e devolvem
valores fixos configuráveis.

**Critérios de aceite:**
- [ ] `analyze_step` chama `baseline_diff.compare(step, baseline_step)` exatamente uma vez, com esses dois argumentos exatos.
- [ ] O retorno de `baseline_diff.detect_candidates(...)` é passado como `candidates` para `candidate_resolver.resolve(candidates, step.index)`.
- [ ] O retorno de `candidate_resolver.resolve(...)` é passado para `placeholder_applier.apply(step.request, tokens)` e também vira `StepAnalysis.dynamic_tokens`.
- [ ] `StepAnalysis.curl_template` é exatamente o que `curl_generator.generate(...)` devolveu (dublê configurado com uma string fixa).
- [ ] `StepAnalysis.static_values` é exatamente o que `baseline_diff.extract_static_values(...)` devolveu.

---

## [T20] — `ReplayTokenResolver`: `resolve`, `_resolve_one`, `_reference_dir_for_step`, `_record_observation`

**Depende de:** T01 (`FakeExtractorRunner`, `FakeMetadataStore`).
**Arquivos envolvidos:** `tests/unit/test_replay_token_resolver.py` (novo).

**Contexto:**
Decide, durante um replay, de qual diretório reler a resposta de origem de cada token
(`replay_run_dir` se o step de origem está no `schedule` atual, senão `res_refer_dir`/
`original_responses_dir`) e acumula a heurística de "token provavelmente estático"
(`STATIC_CONFIRMATION_THRESHOLD=5` observações válidas seguidas).

**Estado atual:**
- `resolve` (`replay_token_resolver.py:25-39`) extrai todos os `token_id` presentes no
  `curl_text` via `SessionStore.TOKEN_PLACEHOLDER_PATTERN` (não via `dependency_parser` — este
  só dá o `origin_step` de cada um) e devolve o subconjunto que `_resolve_one` marcou como
  "estático confirmado".
- `_resolve_one` (linhas 41-60): `origin_step in schedule` → usa `replay_run_dir`; senão
  `_reference_dir_for_step` decide entre `res_refer_dir` (se o arquivo de origem existe lá) e
  `original_responses_dir` (fallback); `extractor_runner.run_existing` devolvendo `None` →
  `False` sem chamar `_record_observation`; senão `session_store.set_token(...)` e delega a
  decisão de "estático" para `_record_observation`.
- `_record_observation` (linhas 74-84): sem extractor persistido (`metadata_store.load` →
  `None`) → `False`. Com extractor: `last_value is None` (primeira observação) OU igual ao novo
  valor → incrementa `valid_count`; senão marca `ever_changed=True` (permanente — uma vez
  `True`, `_record_observation` **nunca mais** devolve `True` para esse token, mesmo que
  `valid_count` volte a acumular 5, porque o retorno é `not ever_changed and valid_count >= 5`).
  `last_value` é sempre atualizado e `metadata_store.save` é sempre chamado.

**Estado esperado depois:**
Teste usa `SessionStore` real, `FakeExtractorRunner`/`FakeMetadataStore` (T01),
`CurlDependencyParser` real (é puro, sem custo).

**Critérios de aceite:**
- [ ] `_reference_dir_for_step(None, res_refer_dir, original_dir)` devolve `res_refer_dir`.
- [ ] `_reference_dir_for_step(2, res_refer_dir, original_dir)` com `res_refer_dir/res_0002.json` existente devolve `res_refer_dir`; sem esse arquivo devolve `original_dir`.
- [ ] `_record_observation`: extractor persistido com `valid_count=4, last_value="v", ever_changed=False`, nova observação `value="v"` → `valid_count` vira 5 e o retorno é `True` (threshold atingido, `STATIC_CONFIRMATION_THRESHOLD=5`).
- [ ] `_record_observation`: mesma configuração, mas nova observação `value="outro"` → `ever_changed=True`, retorno `False`.
- [ ] `_record_observation` chamado de novo depois de `ever_changed=True` já ter sido marcado, mesmo com `valid_count` voltando a acumular 5+ → retorno continua `False` sempre (`ever_changed` não é revertido).
- [ ] `_resolve_one` com `extractor_runner.run_existing` devolvendo `None` → devolve `False` e `metadata_store.load` não é chamado (retorno antecipado antes de `_record_observation`).

---

## [T21] — `ReplayResultComparator`: `matches_original`, `_read_reference_text`

**Depende de:** Nenhuma (usa `Workspace(tmp_path)` real).
**Arquivos envolvidos:** `tests/unit/test_replay_result_comparator.py` (novo).

**Contexto:**
Compara a última resposta de um replay com uma resposta de referência gravada num `run`
anterior — usado no lugar do `Validator`/`success_criteria` porque o replay não tem acesso ao
`config.json` original.

**Estado atual:**
`_read_reference_text` (`replay_result_comparator.py:26-36`) tenta ler
`workspace.response_file(index)` (dir `real_responses/`) primeiro; se falhar (`except
Exception`, tipicamente arquivo ausente), tenta `workspace.original_response_file(index)`
(`original_responses/`); se ambos falharem, `print` de aviso e `None`. `matches_original`
(linhas 15-24): sem texto de referência → `False`; texto sem `"status_code"` casável pelo regex
→ `print` de aviso e `False`; senão compara o inteiro extraído com `response.status_code`.

**Estado esperado depois:**
Teste usa `Workspace(tmp_path)` real, escrevendo manualmente o conteúdo de
`real_responses/res_NNNN.json` e/ou `original_responses/res_NNNN.json` conforme o cenário.

**Critérios de aceite:**
- [ ] Escrever `'{"status_code": 200}'` em `real_responses/res_0000.json` → `matches_original(0, StepResponse(status_code=200))` é `True`.
- [ ] Mesmo cenário com `StepResponse(status_code=404)` → `False`.
- [ ] `real_responses/res_0001.json` ausente, mas `original_responses/res_0001.json` com `'{"status_code": 200}'` → `matches_original(1, StepResponse(status_code=200))` é `True` (fallback).
- [ ] Nenhum dos dois arquivos existe → `matches_original(2, ...)` é `False`, sem lançar exceção.
- [ ] Arquivo existe mas o conteúdo não contém `"status_code"` (ex.: `"{}"`) → `False`.

---

## [T22] — `ReplayRunner`: scheduling (`_schedule_*`), `_mark_token_static`, `_annotate_static_tokens`, `_run_step`

**Depende de:** T01 (`StubHttpTransport`, `FakeSleeper` se necessário para `retry_policy`, `FakeExtractorRunner`/`FakeMetadataStore` via `ReplayTokenResolver` real ou dublê direto do próprio `ReplayTokenResolver`).
**Arquivos envolvidos:** `tests/unit/test_replay_runner.py` (novo).

**Contexto:**
`ReplayRunner.__init__` é atribuição pura (`replay_runner.py:20-44`) — todos os 11 colaboradores
entram por construtor. Este teste cobre scheduling (os 4 modos) e o único caminho que reescreve
`curls/` durante um replay (`_annotate_static_tokens`/`_mark_token_static`, "ponto cego" citado
na spec).

**Estado atual:**
- `_schedule_all` = todos os `.curl.sh` existentes, ordenados (linhas 123-125).
- `_schedule_slice(from, to)`: usa `0`/`max(existing)` como default de `from`/`to` ausentes;
  filtra por intervalo fechado (linhas 127-132).
- `_schedule_smart(from, to)`: começa do `target` (`to` ou `max(existing)`), expande
  recursivamente via `_expand_pending` seguindo as dependências (`dependency_parser.parse`) até
  o `floor` (`from` ou `0`), sem incluir dependências fora de `existing_set` ou abaixo do floor
  (linhas 134-157); levanta `ValueError` via `_require_all_existing` se `target` não existe.
- `_schedule_list(steps_file)`: lê índices de um arquivo texto, um por linha; levanta
  `ValueError` se algum não existe no workspace (linhas 159-164,166-173).
- `_run_schedule` com lista vazia levanta `ValueError` explícito (linha 63-64, mensagem
  "schedule vazio").
- `_mark_token_static` (linhas 113-121): acha a linha de comentário `# Token <id> comes from
  response of step ` (prefixo, sem o número) e, se ainda não termina com o sufixo
  `" - probably static"`, anexa o sufixo; linha já anotada não recebe sufixo duplicado (o `if`
  checa `not line.endswith(...)`); texto sem essa linha para o `token_id` não muda (`break`
  nunca ocorre, retorno é o texto original com `\n` final).
- `_annotate_static_tokens` (linhas 104-111) só reescreve o arquivo em disco se o texto mudou
  (`if updated != text`).
- `_run_step` (linhas 79-102): lê o `.curl.sh`, resolve tokens via `replay_token_resolver.resolve`,
  anota estáticos se houver algum, renderiza via `session_store.render`, chama
  `http_transport.send_request`, tudo dentro do `retry_policy.execute`; persiste a resposta em
  `replay_response_file`.

**Estado esperado depois:**
Teste usa `Workspace(tmp_path)` real com arquivos `.curl.sh` escritos manualmente (incluindo os
comentários de proveniência gerados pelo formato de T05), `StubHttpTransport` (T01), um
`ReplayTokenResolver` real com `FakeExtractorRunner`/`FakeMetadataStore` ou um dublê direto do
`ReplayTokenResolver` — decisão de implementação, desde que a assinatura de
`resolve(curl_text, schedule, ...) -> Set[str]` seja respeitada.

**Critérios de aceite:**
- [ ] `_schedule_all()` com `.curl.sh` para steps 0, 2, 5 no workspace → `([0, 2, 5], {0, 2, 5})`.
- [ ] `_schedule_slice(1, 4)` com steps existentes 0,2,5 → só o 2 sobra (`([2], {2})`).
- [ ] `_schedule_smart(None, 5)` com step 5 dependendo do step 2 (comentário de proveniência no `.curl.sh` do step 5) e step 2 sem dependência → schedule final inclui `{2, 5}`.
- [ ] `_schedule_list(steps_file)` com uma linha referenciando um step inexistente no workspace → `ValueError`.
- [ ] `_run_schedule([], set())` → `ValueError` com a mensagem "schedule vazio".
- [ ] `_mark_token_static("# Token abc comes from response of step 2\ncurl ...", "abc")` termina com a linha sufixada `" - probably static"`; chamado de novo sobre o resultado não duplica o sufixo.
- [ ] `_mark_token_static(texto, "token-que-nao-aparece")` devolve o texto igual (só normaliza a quebra de linha final).
- [ ] `_annotate_static_tokens`: se `replay_token_resolver.resolve` devolve um `token_id` presente no `.curl.sh`, o arquivo em disco é reescrito com o sufixo; se devolve conjunto vazio, o arquivo não é reescrito (comparar mtime ou conteúdo antes/depois).
- [ ] `_run_step` com `StubHttpTransport` devolvendo `StepResponse(status_code=200)` → o arquivo `replay_response_file(run_id, index)` é criado com esse conteúdo.

---

## [T23] — `BaseAgent`: `key`, `value_char_class`, `lazy_value_char_class`, `generate_code`, `_extract_code_block`, `_response_to_text`, `run_tdd_loop`

**Depende de:** T01 (`FakeScriptExecutor`, `FakeSleeper`).
**Arquivos envolvidos:** `tests/unit/test_base_agent.py` (novo).

**Contexto:**
`run_tdd_loop` é o coração do loop de tentativa-e-erro de todo `Agent` — tenta estratégias
determinísticas antes de LLM, valida cada tentativa executando o código de verdade (via
`script_executor` injetado), e só dorme entre tentativas via `sleeper` injetado (T06 da Etapa B).
Testar aqui com `BaseAgent` diretamente (sem subclasse concreta) usando
`deterministic_strategies` sobrescrito por uma subclasse mínima de teste, já que a base devolve
`[]` por padrão (linha 65).

**Estado atual:**
- `key` (linhas 45-51): `path=None` → `None`; path com `:` → parte depois do primeiro `:`; sem
  `:` → o path inteiro.
- `value_char_class` (linhas 53-56): valor "seguro" (`\w`, `-`, `.`) → `[\w\-.]+`; valor com
  outros caracteres (ex.: espaço) → `.+?`.
- `lazy_value_char_class` (linhas 58-62): se a char class termina com `+`, vira `+?`; senão
  devolve igual (já é lazy, ex. `.+?` já termina em `?`, não `+`).
- `generate_code` (linhas 77-85): itera as estratégias (determinísticas, depois `MAX_LLM_ATTEMPTS=5`
  repetições de `_llm_strategy`) a partir de `_attempt_index` (estado incremental entre
  chamadas), devolvendo o primeiro código não-`None`; esgotadas todas, `None`.
- `_extract_code_block` (linhas 122-129): extrai o conteúdo de um bloco ```` ```python ... ``` ````
  (ou ```` ``` ... ``` ```` sem a palavra `python`) se presente; senão devolve o texto inteiro
  stripped.
- `_response_to_text` (linhas 99-110): `AIMessage.content` string → devolve direto; lista →
  concatena só as partes que são string ou dict com `"text"`.
- `run_tdd_loop` (linhas 131-167): para cada tentativa, gera código, executa
  (`_verify_code`→`_execute_script`), aceita no primeiro sucesso (monta `Extractor`), senão
  acumula o erro como `last_error` da próxima tentativa e chama `sleeper.sleep(RETRY_DELAY_SECONDS=5)`
  entre tentativas (não depois da última, pois o loop já terminou); esgotadas as tentativas,
  limpa o arquivo temp e devolve `None`.
- `_execute_script` (linhas 184-197): timeout → `(False, "Timeout during verification")`;
  `return_code != 0` → `(False, stderr ou mensagem padrão)`; saída bate com `expected_value` →
  `(True, None)`; saída não bate → `(False, mensagem de mismatch com repr)`.

**Estado esperado depois:**
Teste constrói uma subclasse mínima de `BaseAgent` só para o teste (ex. em
`tests/support/recording_agent.py` ou local ao arquivo) que permite injetar estratégias
determinísticas configuráveis, com `Workspace(tmp_path)`, `FakeScriptExecutor`, `FakeSleeper`.

**Critérios de aceite:**
- [ ] `key` com `path="header:X-Csrf"` devolve `"X-Csrf"`; com `path="url"` devolve `"url"`; com `path=None` devolve `None`.
- [ ] `value_char_class()` com `expected_value="abc-123.x"` devolve `r"[\w\-.]+"`; com `expected_value="a b"` devolve `r".+?"`.
- [ ] `lazy_value_char_class()` sobre `r"[\w\-.]+"` devolve `r"[\w\-.]+?"`.
- [ ] `generate_code`: uma estratégia determinística que devolve `None` seguida de outra que devolve código válido → `generate_code()` devolve o código da segunda, sem tentar LLM.
- [ ] `_extract_code_block("texto\n```python\ndef f(): pass\n```\nfim")` devolve `"def f(): pass"`.
- [ ] `_extract_code_block("sem bloco de codigo")` devolve o texto stripped original.
- [ ] `run_tdd_loop`: `FakeScriptExecutor` configurado para falhar na 1ª tentativa (`return_code=1`) e ter sucesso na 2ª (`return_code=0`, `stdout=expected_value`) → devolve um `Extractor(verified=True)`, e `fake_sleeper.calls` tem exatamente 1 entrada (dormiu entre a 1ª e a 2ª, não depois da 2ª).
- [ ] `run_tdd_loop` com todas as tentativas falhando → devolve `None`, e o arquivo temp (`workspace.temp_extractor_file(...)`) não existe mais depois (foi limpo por `_cleanup_script`).

---

## [T24] — Agents concretos: `deterministic_strategies` de `CookieAgent`/`HeaderAgent`/`JSONPathAgent`/`CSSAgent`/`RegexAgent`

**Depende de:** T01, T23 (reaproveita o padrão de subclasse de `BaseAgent` para construir cada agent concreto com dublês).
**Arquivos envolvidos:** `tests/unit/test_agents_strategies.py` (novo).

**Contexto:**
Cada `Agent` concreto implementa só `deterministic_strategies` e os helpers de construção de
código — funções puras sobre `self.response_sample`/`self.expected_value`/`self.key`. O teste
não executa o código gerado (isso é `run_tdd_loop`, já coberto em T23) — só verifica que o
código certo (ou `None`) foi gerado para cada padrão.

**Estado atual (por agent, ver spec e leitura de código completa nesta task):**
- `CookieAgent._context_pattern` (`cookie_agent.py:30-43`): sem `key`/cookie ausente/valor não
  contém `expected_value` → `None`; valor no fim do cookie (`suffix` vazio) → padrão termina em
  `$` em vez de lookahead de caractere.
- `HeaderAgent`: mesma lógica de `_context_pattern`, mas com fallback case-insensitive de nome
  de header em `_header_value`/`_by_name` (`header_agent.py:34-43`).
- `JSONPathAgent._find_value_paths` (`jsonpath_agent.py:13-24`): body não é JSON válido (nem
  `str` parseável nem já é `dict`/`list`) → `[]`; body válido → lista de paths ordenada por
  profundidade crescente (`matches.sort(key=len)`).
- `CSSAgent._rank_candidates` (`css_agent.py:20-42`): body vazio ou não-string → `[]`; um
  atributo/classe/id que não é único no documento (`_is_unique` via `soup.select(...)`) é
  descartado da lista de candidatos.
- `RegexAgent._key_pattern` (`regex_agent.py:20-24`): `key is None` ou `key == "body"` → `None`
  (evita um padrão degenerado quando o "campo" é o body inteiro).

**Estado esperado depois:**
Um teste por agent (ou seções claramente separadas no mesmo arquivo, desde que sigam o guia de
estilo de decomposição), com `response_sample` dict construído à mão por cenário.

**Critérios de aceite:**
- [ ] `CookieAgent` com `path="cookie:sid"`, `response_sample={"cookies": {"sid": "prefixTOKEN"}}`, `expected_value="TOKEN"` → `_context_pattern()` não é `None` e termina em `$` (`TOKEN` está no fim do valor do cookie).
- [ ] `HeaderAgent` com `response_sample={"headers": {"X-Token": "abc"}}` e `path="header:x-token"` (case diferente) → `_by_name` gera código que localiza o header via fallback lowercase.
- [ ] `JSONPathAgent` com `response_sample={"body": "não é json"}` → `_find_value_paths()` devolve `[]`.
- [ ] `JSONPathAgent` com `response_sample={"body": '{"data":{"token":"X"}}'}`, `expected_value="X"` → `_find_value_paths()` inclui o path `[("key","data"),("key","token")]`.
- [ ] `CSSAgent` com HTML tendo dois elementos com a mesma classe (`class="tok"`) e o valor esperado presente em ambos → o seletor `.tok` **não** aparece nos candidatos (não é único).
- [ ] `RegexAgent` com `path="body"` → `_key_pattern()` é `None`; com `path="foo:bar"` (`key="bar"`) → `_key_pattern()` não é `None` e contém `"bar"` escapado.

---

## [T25] — `AgentFactory.create`: mapeamento `TokenLocation` → agent e fallback

**Depende de:** T01.
**Arquivos envolvidos:** `tests/unit/test_agent_factory.py` (novo).

**Contexto:**
Ponto único de despacho `TokenLocation → Agent` concreto (`LOCATION_AGENTS`, costura da Etapa
B) — troca um `if/elif` por uma coleção, conforme guia de estilo.

**Estado atual:**
`create` (`agent_factory.py:38-51`) busca `LOCATION_AGENTS.get(candidate.origin_location,
DEFAULT_AGENT=RegexAgent)` e instancia passando todos os campos do `candidate` +
`workspace`/`script_executor`/`sleeper`/`llm` do próprio factory. `LOCATION_AGENTS` mapeia
`COOKIE→CookieAgent`, `HEADER→HeaderAgent`, `BODY_JSON→JSONPathAgent`, `BODY_HTML→CSSAgent`,
`SCRIPT→RegexAgent` (linhas 17-23); `URL_PARAM` não está no dict — cai no fallback
`RegexAgent`.

**Estado esperado depois:**
Teste com `Workspace(tmp_path)`, `FakeScriptExecutor`, `FakeSleeper`, `llm=None`.

**Critérios de aceite:**
- [ ] `create(DynamicToken(origin_location=TokenLocation.COOKIE, ...), {})` devolve uma instância de `CookieAgent`.
- [ ] `create(DynamicToken(origin_location=TokenLocation.BODY_HTML, ...), {})` devolve uma instância de `CSSAgent`.
- [ ] `create(DynamicToken(origin_location=TokenLocation.URL_PARAM, ...), {})` devolve uma instância de `RegexAgent` (fallback, location sem mapeamento explícito).
- [ ] `create(DynamicToken(origin_location=None, ...), {})` devolve `RegexAgent` (mesmo fallback).
- [ ] O agent devolvido tem `.token_id`, `.expected_value`, `.path` iguais aos do `candidate` passado.

---

## [T26] — `EngineFactory`: `resolve_class`, `create` (Dry e Main), `_build_tracker`

**Depende de:** T01.
**Arquivos envolvidos:** `tests/unit/test_engine_factory.py` (novo).

**Contexto:**
Raiz de composição do ramo `run` (pós-Etapa B) — monta o grafo inteiro sem nenhuma
`@classmethod`. O teste verifica a fiação (quem recebe o quê, qual diretório por modo) sem
rodar `Engine.run()`.

**Estado atual:**
- `resolve_class(mode)` (`engine_factory.py:47-48`) é um dict lookup simples
  (`EngineMode.MAIN→Engine`, `EngineMode.DRY→DryEngine`).
- `create` (linhas 50-79): `tracking_responses_dir` é `workspace.real_responses` se
  `engine_cls.USES_NETWORK` (modo `MAIN`), senão `workspace.original_responses` (modo `DRY`);
  `transport` só é repassado ao `Engine` se `USES_NETWORK`, senão `None` mesmo que
  `http_transport` tenha sido passado; monta uma única `SessionStore`, um único
  `ExtractorRunner`/`ExtractorMetadataStore` compartilhados entre `TokenTracker` (via
  `_build_tracker`) e `TokenResolver`.
- `_build_tracker` (linhas 81-94): monta `AgentFactory` com `self.llm` (construído no
  `__init__` a partir de `project_config.llm`, com `print` de fallback se configurado — linhas
  96-106), `CandidateResolver` com o `tracking_responses_dir` recebido, `TokenTracker` com
  `BaselineDiff()`/`PlaceholderApplier(session_store)`/`CurlGenerator()` novos.

**Estado esperado depois:**
Teste com `Workspace(tmp_path)`, `ProjectConfig()` (sem `llm` configurado → `self.llm is
None`, evita precisar de dublê de `BaseChatModel`), `FakeScriptExecutor`, `FakeSleeper`.

**Critérios de aceite:**
- [ ] `resolve_class(EngineMode.MAIN) is Engine`; `resolve_class(EngineMode.DRY) is DryEngine`.
- [ ] `create(EngineMode.DRY, har_path, http_transport=StubHttpTransport(...))` → o `Engine` resultante tem `http_transport is None` (ignorado porque `DryEngine.USES_NETWORK is False`).
- [ ] `create(EngineMode.DRY, har_path)` → o `TokenResolver`/`CandidateResolver` internos usam `workspace.original_responses` como `responses_dir` (inspecionar via atributo, já que são atribuições diretas).
- [ ] `create(EngineMode.MAIN, har_path, http_transport=StubHttpTransport(...))` → `engine.http_transport` é exatamente o `StubHttpTransport` passado, e o diretório usado é `workspace.real_responses`.
- [ ] `ProjectConfig(llm=None)` → `EngineFactory(...).llm is None` (nenhuma tentativa de construir `BaseChatModel`).

---

## [T27] — `Engine`/`DryEngine`: `handle_recovery`, `_skip_entry`, `_validate_final`, `DryEngine.execute_step`/`_persist_response_step`

**Depende de:** T01.
**Arquivos envolvidos:** `tests/unit/test_engine.py` (novo).

**Contexto:**
`Engine.__init__` é atribuição pura (`engine.py:17-39`) — todos os 10 colaboradores entram por
construtor. O teste cobre só os pontos simples citados na spec, sem rodar `_reproduce`/`run()`
inteiro (isso é o papel dos 39 golden).

**Estado atual:**
- `handle_recovery` (linhas 116-125): `response.status_code` fora de
  `retry_policy.RECOVERABLE_STATUS_CODES={400,401}` → `False` sem chamar
  `token_resolver.resolve_all`; dentro do set → chama `resolve_all(force=True)` e devolve
  `True`.
- `_skip_entry` (linhas 85-89): monta `StepResponse(status_code=0, skipped=True,
  skip_reason=reason)`, persiste via `_persist_response_step`, devolve a response.
- `_validate_final` (linhas 108-114): `last_response is None` OU `success_criteria` vazia →
  `True` sem chamar `validator.validate`; senão delega a `validator.validate(...)`.
- `DryEngine.execute_step` (`dry_engine.py:10-12`): devolve `step.response` direto (assume não
  `None` via `assert`), sem chamar `http_transport`. `DryEngine._persist_response_step` (linhas
  14-15) é um no-op (`pass`) — sobrescreve o `Engine._persist_response_step` real, que grava em
  disco.

**Estado esperado depois:**
Teste constrói `Engine`/`DryEngine` com fakes por construtor (`workspace`, `token_resolver`,
`retry_policy=StepRetryPolicy()` real — é puro —, `validator` fake ou real, `success_criteria`).

**Critérios de aceite:**
- [ ] `handle_recovery(StepResponse(status_code=500))` devolve `False`; `token_resolver.resolve_all` (fake) não foi chamado.
- [ ] `handle_recovery(StepResponse(status_code=401))` devolve `True`; `token_resolver` fake registra uma chamada com `force=True`.
- [ ] `_skip_entry(3, "unsupported scheme 'ftp'")` devolve `StepResponse(status_code=0, skipped=True, skip_reason="unsupported scheme 'ftp'")`, e o arquivo `workspace.response_file(3)` é criado com esse conteúdo.
- [ ] `_validate_final(None)` e `_validate_final(StepResponse(...), success_criteria=[])` (via engine construído com `success_criteria=[]`) devolvem `True` sem chamar `validator.validate`.
- [ ] `DryEngine.execute_step(Step(index=0, request=..., response=StepResponse(status_code=200)))` devolve exatamente esse `StepResponse`, sem tocar `http_transport`.
- [ ] `DryEngine()._persist_response_step(0, StepResponse(status_code=200))` não cria nenhum arquivo em `workspace.real_responses` (no-op confirmado).

---

## [T28] — `CurlHttpTransport`: `_build_curl_command`, `_tls_flag`, `_decode_stderr`, `_build_error_response`, `_read_captured_response`

**Depende de:** T01 (`FakeSleeper`).
**Arquivos envolvidos:** `tests/unit/test_curl_http_transport.py` (novo).

**Contexto:**
`send_request` em si roda `curl` real via proxy (fora de escopo, spec). Os helpers testáveis
são construção de comando (puro) e a lógica de retry de leitura de captura, isolável com
`monkeypatch` sobre `_try_read_capture` (D.2 — ponto documentado onde a injeção de construtor
não alcança, já que `_try_read_capture` lê `workspace.mitm_capture_file()` via `HARParser`
real).

**Estado atual:**
- `_build_curl_command` (`curl_http_transport.py:45-52`) concatena o curl literal + flags de
  proxy/TLS/`-o /dev/null`/`-sS`.
- `_tls_flag` (linhas 54-58): `ca_cert_path is None` → `"--insecure"`; senão `--cacert
  <path quotado>`.
- `_decode_stderr` (linhas 60-62): decodifica bytes com `errors="replace"`, stripped.
- `_build_error_response` (linhas 82-95): monta `StepResponse(status_code=0, body=<mensagem de
  erro>, ...)` e faz `print` do erro.
- `_read_captured_response` (linhas 64-70): tenta `_try_read_capture` até
  `CAPTURE_READ_ATTEMPTS=5` vezes, dormindo `CAPTURE_READ_RETRY_INTERVAL_SECONDS=0.1` (via
  `sleeper.sleep`, injetado) entre tentativas; primeira tentativa não-`None` interrompe o loop;
  todas `None` → `None`.

**Estado esperado depois:**
Teste constrói `CurlHttpTransport(workspace, port, ca_cert_path, FakeSleeper())` e usa
`monkeypatch.setattr(transport, "_try_read_capture", ...)` para controlar `_read_captured_response`
sem tocar `HARParser`/arquivo de captura real.

**Critérios de aceite:**
- [ ] `_tls_flag()` com `ca_cert_path=None` devolve `"--insecure"`.
- [ ] `_tls_flag()` com `ca_cert_path=Path("/tmp/ca.pem")` devolve `"--cacert /tmp/ca.pem"` (ou quotado, se o path tem espaço).
- [ ] `_build_curl_command("curl -X GET https://x")` contém a flag `f"--proxy http://127.0.0.1:{port}"` e termina com `-sS`.
- [ ] `_decode_stderr(CompletedProcess(..., stderr=b"erro\n"))` devolve `"erro"` (stripped).
- [ ] `_build_error_response(3, "timeout")` devolve `StepResponse(status_code=0, body="timeout")`.
- [ ] `_read_captured_response`: `monkeypatch` fazendo `_try_read_capture` devolver `None` nas 2 primeiras chamadas e uma `StepResponse` na 3ª → `_read_captured_response` devolve essa response, e `fake_sleeper.calls` tem exatamente 2 entradas (uma por tentativa falha).
- [ ] `_read_captured_response`: `_try_read_capture` sempre `None` → devolve `None` depois de exatamente `CAPTURE_READ_ATTEMPTS=5` tentativas.

---

## [T29] — `MitmProxyOrchestrator`: helpers puros + `_build_early_exit_message` + `_terminate`

**Depende de:** T01 (`FakeProcess`).
**Arquivos envolvidos:** `tests/unit/test_mitm_proxy_orchestrator.py` (novo).

**Contexto:**
Dois "pontos cegos" documentados na spec (não exercitados por nenhum dos 39 golden):
`_build_early_exit_message` (só roda quando `mitmdump` morre antes de ficar pronto) e, agora
também no escopo, `_terminate` (encerramento do processo) — ambos tocam só `self._process`/
`self._log_file`, atribuíveis direto no teste sem passar por `_start_process`/subprocess real.

**Estado atual:**
- `_build_command`/`_build_env`/`_prepend_package_root` (`mitm_proxy_orchestrator.py:34-40,73-82`)
  são funções puras sobre atributos de instância e `os.environ`.
- `_resolve_port`/`_find_free_port` (linhas 33-40): `proxy_port` explícito é usado direto; `None`
  abre um socket `bind(("127.0.0.1", 0))` para achar uma porta livre do SO.
- `_build_port_conflict_message` (linhas 151-157) é uma f-string pura sobre `self.port`.
- `_build_early_exit_message` (linhas 112-116): lê `workspace.mitm_log_file()` se existir (senão
  corpo vazio) e formata com `self._process.returncode` (requer `assert self._process is not
  None` — o teste precisa atribuir um `_process` fake antes de chamar).
- `_terminate` (linhas 159-173): `self._process is None` → no-op; senão `terminate()` +
  `wait(timeout=TERMINATE_TIMEOUT_SECONDS=5.0)`; em `TimeoutExpired`, `kill()` + `wait()` sem
  timeout; sempre zera `self._process = None` no fim; se `self._log_file` não é `None`, fecha e
  zera.

**Estado esperado depois:**
Teste constrói `MitmProxyOrchestrator(Workspace(tmp_path), proxy_port=<porta fixa, evita
`_find_free_port` real>, project_root=tmp_path)` e atribui `orchestrator._process`/
`orchestrator._log_file` diretamente com `FakeProcess`/arquivo real ou `io.StringIO`-like fake,
sem nunca chamar `run`/`_start_process`.

**Critérios de aceite:**
- [ ] `_build_command()` contém `str(self.port)` e o caminho do addon (`ADDON_PATH`).
- [ ] `_build_env()` inclui `MitmEnv.CAPTURE_PATH_ENV_VAR` apontando para `workspace.mitm_capture_file()`.
- [ ] `_prepend_package_root(None)` devolve só `str(PACKAGE_ROOT)`; `_prepend_package_root("/outro")` devolve `f"{PACKAGE_ROOT}{os.pathsep}/outro"`.
- [ ] `_resolve_port(8080)` devolve `8080` sem abrir socket algum.
- [ ] `_build_early_exit_message()` com `workspace.mitm_log_file()` inexistente e `orchestrator._process = FakeProcess(returncode=1)` → mensagem contém `"exit code 1"` e corpo vazio (sem lançar exceção por arquivo ausente).
- [ ] `_terminate()` com `orchestrator._process = FakeProcess()` que responde a `wait()` sem lançar → `FakeProcess.terminate` foi chamado uma vez, `FakeProcess.kill` **não** foi chamado, e `orchestrator._process is None` no final.
- [ ] `_terminate()` com `FakeProcess` cujo `wait()` lança `subprocess.TimeoutExpired` na primeira chamada → `FakeProcess.kill` é chamado, seguido de um segundo `wait()` sem timeout.
- [ ] `_terminate()` com `orchestrator._process = None` → não lança exceção, é um no-op.

---

## Cobertura fora deste plano (registrada, não implementada)

Conforme spec, seção "Fora de escopo": `ResponseGrep.find`/`_grep_single_pattern`,
`CandidateResolver._process_candidate`/`_find_origin`/`_load_response`,
`CurlHttpTransport.send_request`, `MitmProxyOrchestrator._start_process`/`_wait_until_ready`/
`_probe_proxy`/`_can_connect`/`_classify_response`/`_fetch_server_header`,
`Workspace.get_mitmproxy_ca_path`, `HARParser.load_har`/`get_entries`/`split_har`. Nenhuma task
deste plano cobre esses pontos — permanecem sem seam ou já cobertos pelos golden.
