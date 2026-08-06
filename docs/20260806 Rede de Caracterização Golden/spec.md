# Spec — Rede de Caracterização Golden

## 1. Objetivo

### O problema

O projeto não tem nenhum teste — `pytest.ini` aponta `testpaths = tests` para um
diretório inexistente. E o histórico recente é quase todo correção: `docs/` tem
**onze** pastas datadas 04 e 05/08/2026, e **três delas são o mesmo defeito no
mesmo componente** (`ReplayRunner._schedule_*`), descoberto três vezes em modos
diferentes — `Steps Pulados Quebram o Schedule do Replay {List,Slice,Smart}`.

Descobrir o mesmo bug três vezes é a assinatura de um sistema sem rede de
proteção: cada correção é validada à mão, num modo, e as outras variações só
aparecem quando alguém topa com elas.

O passo seguinte natural é refatorar para tornar o código testável — hoje o grafo
de objetos não é construível sem estado global (`Workspace` é singleton
materializado por `setattr`, `fs_io/workspace.py:19-26`), disco, subprocessos e
rede. **Mas fazer essa refatoração antes de ter detecção automática de regressão
colocaria a maior mudança do projeto exatamente no ponto de maior cegueira.**

### O arco: três etapas

| Etapa | Entrega | Toca `har_reproducer/`? |
|---|---|---|
| **A — esta** | Rede de caracterização golden sobre os 3 comandos, comparando a árvore do workspace **e** o `stdout` integralmente | **Não. Zero linhas.** |
| **B** | Refatoração de testabilidade, corte "nível 2" (§3.8) | Sim |
| **C** | Unitários finos, usando as costuras de B | Não |

### Escopo desta etapa

Um ciclo de spec/plano/branch, com o plano em dois blocos e **checkpoint explícito
entre eles** — as tasks de A1 são entregues e demonstradas antes de começar A2.

- **A1 — offline.** Fixtures, harness golden, e cobertura de `parse`,
  `run --mode dry` e `success_criteria`. Sem rede, proxy ou porta livre.
- **A2 — rede.** Servidor HTTP falso local, `run --mode main` e os 4 modos de
  `replay`.

### Fora de escopo

- **Qualquer alteração fora de `tests/`** — nem para corrigir os defeitos da §6.
  Ver §3.7.
- A refatoração (B) e os unitários (C).
- O campo `llm` do config. Nenhum teste configura LLM, logo nenhum teste chama
  provedor.

---

## 2. Fatos medidos e ancorados no código

Tudo abaixo foi **executado** ou **lido no código na linha citada**. Uma versão
anterior desta spec errou nove afirmações por reaproveitar medições de um protótipo
em vez de reler o código; cada afirmação comportamental daqui em diante carrega sua
âncora.

| # | Fato | Medida |
|---|---|---|
| 1 | `run --mode dry` é determinístico | Duas rodadas em `--output` virgens sobre a fixture de 10 entries: **48 arquivos/dirs, zero divergência**. **5,7 s** por rodada |
| 2 | A fixture de 10 entries cobre **os 5 agents do README** | Medido: `CookieAgent`, `CSSAgent`, `HeaderAgent`, `JSONPathAgent`, `RegexAgent`, mais `LiteralAgent` e `LiteralFallbackAgent` |
| 3 | `run --mode main` sobre a **fixture de 10 entries**, via servidor falso | **11,2 s**, dois `sleep`, os 7 `extract_*.py` escritos e `temp_extractors/` limpo. Árvore: **62** por `rglob` cru, **60** pela régua do snapshot de §3.4 (que exclui o conteúdo de `mitm_capture/`) |
| 4 | Normalização iguala duas rodadas de rede **completas** (`run main` + `replay all`) da fixture de 10 entries | Portas e `run_id` diferentes: **zero divergência**, e `stdout` idêntico (27 linhas). Árvore: **71** por `rglob` cru, **69** pela régua do snapshot |
| 5 | Os 4 modos de `replay` sobre workspace construído em `main` | **7 de 7** cenários, **0,83–1,02 s cada**, soma **6,38 s**, e **zero** falhas de resolução de token em todos |
| 6 | `list` apontando para step pulado | `ValueError` de `_require_all_existing` (`replay/replay_runner.py:163-170`) — o comportamento das 3 specs de 05/08 |
| 7 | `token_id` é puro | `md5(f"{path}:{origin_step}")`, `tracking/candidate_resolver.py:138-140`. Sem uuid, sem timestamp |
| 8 | Os 4 tipos de `success_criteria` em sucesso **e** falha, mais o caso de lista vazia | **9 de 9** com o veredito esperado, **<1 s cada**, `extractors/` vazio (nenhum agent roda). Com `success_criteria: []` — ou sem `--config` — saem **zero** linhas `Final Validation Result` e o desfecho é `SUCCESSFUL`, como o README:146 promete |
| 9 | Substituição de placeholder em corpo e URL | Medido em `curls/`: `--data-binary '{"csrf": "{{extractor:47ee…}}"}'` e `/item/{{extractor:ade6…}}` |
| 10 | O fallback de `response_reference_dir` redesenhado (§3.6) | `replay --mode list` do step 4 sobre workspace `main`, com referência sem `res_0003.json`: **os dois ramos** de `_reference_dir_for_step` exercitados, **zero** falhas de token, 0,78 s |
| 11 | Em `main`, `CookieAgent` **também** é inalcançável | Medido: 7 extratores, mas dois `LiteralFallbackAgent` (origens 0 e 7) e **nenhum** `CookieAgent`. Ver §2.2 |
| 12 | `list` **fora de ordem** (`--steps-file` = `4\n3`) é determinístico e revela comportamento não documentado | 0,87 s, **exatamente uma** falha de token nas duas rodadas. O placeholder cru vai para o `curl`, que morre com `curl: (3) nested brace in URL`, o step 4 fica com `status 0` — e o replay reporta `✓ SUCCESS` de qualquer forma. Ver §6.9 |
| 13 | O cenário de `skip_rules` customizado é **barato e sem `sleep`** | `methods: ["OPTIONS","POST"]`: **0,08 s, zero `sleep`**, 4 extratores (`CookieAgent`, `JSONPathAgent`, `LiteralAgent`, `RegexAgent`) |

⚠️ **Toda contagem de arquivos precisa dizer sob qual régua foi feita.** Há duas —
`rglob` cru e o snapshot de §3.4, que exclui o *conteúdo* de `mitm_capture/` — e elas
diferem em 2. Uma task que asserte "62" usando `GoldenWorkspace` mediria 60 e
concluiria que quebrou. Uma versão anterior desta spec já havia misturado réguas assim
(citando "34" do protótipo ao lado de números da fixture).

### 2.1 As sete fontes de não-determinismo

| Fonte | Onde | Máscara |
|---|---|---|
| `Extractor.temp_file_path` | Caminho **absoluto** do `--output`, gravado em `extractors/*.meta.json` por `agents/base_agent.py:149-156` | Prefixo → `<WORKSPACE>` |
| Porta do servidor falso | URLs em `real_requests/` e `curls/` — **não** em `original_responses/`: `StepResponse` (`models/http.py:16-24`) não tem campo de URL, e nenhum corpo da fixture embute a porta | `127\.0\.0\.1:\d+` → `127.0.0.1:<PORT>` |
| `run_id` do replay | `datetime.now()` com precisão de segundo, `cli/cli_handlers.py:95` | Segmento de caminho → `<RUN_ID>` |
| Headers voláteis | `Date` e `Server` — **em `real_responses/` E em `replays/<run_id>/`**, os dois gravam `StepResponse` com headers reais | Valor → sentinela |
| `mitm_capture/` | `mitmdump.log` (log de processo externo) e `capture.har` (só o último response) | Conteúdo excluído; existência do diretório verificada |
| **Ordem de iteração de `Set[str]`** | `replay/replay_token_resolver.py:34` itera `token_ids: Set[str]`; a falha imprime na linha `:57`. Hash de `str` é randomizado por processo | Ver §3.4 |
| **Nº de dígitos da porta**, via o offset na mensagem do `curl` | `curl: (3) nested brace in URL position N:` e a linha do caret com `N-1` espaços. `N` é o offset em caracteres, logo depende do tamanho da porta na URL. Sai no `print` de `curl_http_transport.py:83-86` **e** vai para `body` em `_build_error_response`, persistido em `replays/<run_id>/res_NNNN.json` | **Restrição no servidor**, não máscara — ver §3.3 |

⚠️ A primeira é a menos óbvia: contamina um arquivo que o golden **precisa**
comparar, e não é ignorável em bloco — os outros oito campos do mesmo `.meta.json`
são o alvo.

⚠️ A quarta quase virou bug de task: a versão anterior desta spec dizia "headers
voláteis em `real_responses/`", e uma task implementada literalmente deixaria
**todos** os goldens de replay flaky.

⚠️ A sexta atinge o `stdout`, não o disco, e é **traiçoeira porque só se manifesta
entre processos**. Medido com os 7 `token_id` reais da fixture: **6 processos novos
produziram 6 ordens diferentes**; com `PYTHONHASHSEED` fixo, sempre a mesma. Dentro
de **uma** sessão do pytest a ordem é estável — o que significa que uma suíte pode
passar mil vezes na mesma sessão e quebrar quando o golden gravado numa sessão é
comparado noutra. `PYTHONHASHSEED` não é corrigível de dentro do `conftest.py`
(precisa preceder o interpretador). Mitigação em §3.4.

⚠️ A sétima foi **introduzida por um cenário desta própria spec** — o do fato 12 — e
é a mesma categoria que a restrição de `Content-Length` da §3.3 já antecipava: a
máscara `127.0.0.1:<PORT>` esconde a porta, mas não os efeitos **derivados** dela.
Registrado como aviso de método: cada cenário novo pode reabrir esta lista, e a
pergunta "que efeito derivado da porta isso congela?" tem que ser feita ao adicionar
qualquer cenário.

⚠️ Nenhuma máscara genérica de hexadecimal — apagaria os `token_id`, que são o
alvo (fato 7).

### 2.2 `CookieAgent` é inalcançável para HAR realista, nos dois modos

`TokenLocationDetector.find` (`tracking/token_location_detector.py:13-27`) testa
`_find_in_headers` **antes** de `_find_in_cookies`. Uma captura real — de browser
ou do `mitm_addon` — inclui o header cru `Set-Cookie: SESSIONID=…`. Então o valor é
achado num **header** → `TokenLocation.HEADER` → `HeaderAgent`, que procura um
header chamado `SESSIONID` (o `key` vem do `path` `cookie:SESSIONID`) e encontra
`Set-Cookie`. `_by_name` falha, `_context_pattern` também (não existe header com
esse nome), as estratégias determinísticas esgotam, e sem LLM o resultado é
`LiteralFallbackAgent` (`tracking/candidate_resolver.py:202-203`): valor
**hardcoded** em vez de extrator.

Medido: com `Set-Cookie` na entry 0, tanto `dry` quanto `main` produzem
`LiteralFallbackAgent`. Para cookie setado na mesma resposta — o caso mais comum —
a ferramenta emite valor congelado, contrariando seu propósito.

⚠️ Correção de uma afirmação anterior desta spec: **não existe divergência
`dry` vs `main` aqui.** A divergência medida antes era artefato de um protótipo cuja
entry 0 omitia `Set-Cookie` — irrealista. Consequência: este defeito é visível já no
bloco A1, e a afirmação "só o golden dos dois modos revela" era falsa.

⚠️ Consequência para a fixture: alcançar `CookieAgent` exige uma entry
deliberadamente **irrealista**, com o cookie em `cookies[]` e sem `Set-Cookie`
(entry 7 da §3.2). Ela existe só para dar cobertura ao agent; o caminho realista é a
entry 0.

⚠️ **E essa cobertura só existe em `dry`.** O servidor falso não tem como setar
cookie sem emitir `Set-Cookie` — o protocolo não oferece outro jeito. Medido em
`main` (fato 11): a entry 7 degrada pelo mesmo mecanismo, o resultado são **dois**
`LiteralFallbackAgent` (origens 0 e 7) e **nenhum** `CookieAgent`, e a rodada paga
**dois** `sleep` em vez de um. Portanto o golden de A1 congela 7 tipos de extrator e
o de A2 congela 6 — a diferença é parte do contrato, não um erro.

---

## 3. Decisões

### 3.1 Caracterização antes da refatoração

Um teste de caracterização não valida que o comportamento está *correto* — valida
que não *mudou*. É a única garantia obtenível **antes** de existirem costuras para
testar unidades isoladas.

Escrever unitários primeiro exigiria as costuras, que exigiriam a refatoração, que
é o que se quer proteger: circular.

**Alternativa descartada:** refatorar validando à mão com `replay --mode slice`
após cada task. É o método que deixou o defeito de `_schedule_*` passar três vezes.

### 3.2 A fixture principal — 10 entries, construída e medida

Fixture escrita à mão em `tests/fixtures/`. Esta tabela **não é uma proposta**: ela
foi gerada, executada em `dry`, e os agents da coluna direita foram lidos dos
`extractors/*.meta.json` produzidos.

| # | Entry | Cobre |
|---|---|---|
| 0 | `GET /login` → 200, `Content-Type: text/html`, **`Set-Cookie: SESSIONID=…`**, corpo com `<div id="marker">tok_CSS_1</div>` e `<script>var nonce = "scr_NONCE_2";</script>` | Baseline. Origem de `CSSAgent` (HTML simples) e de `RegexAgent` (dentro de `<script>`) |
| 1 | `OPTIONS wss://…/ws` → 204 | Skip por esquema **e a precedência sobre método** — `step_skip_evaluator.py:14-18` testa esquema primeiro. Medido: reporta `unsupported scheme 'wss'`, não o método |
| 2 | `OPTIONS /api/do` → 204 | Skip por `skip_rules.methods` |
| 3 | `POST /api/do`, cookie `SESSIONID`, headers `Content-Type: application/json` e `X-Csrf: tok_CSS_1`, corpo `{"csrf": "tok_CSS_1"}` → 200 JSON `{"id": 4242, "ok": true}` | **`CSSAgent`** (via `X-Csrf`, origem 0); **`LiteralFallbackAgent`** (o defeito §2.2); substituição em **corpo** (`placeholder_applier.py:61-69`) e em cookie |
| 4 | `GET /item/4242`, headers `X-Trace: 4242` e `nonce: scr_NONCE_2`, **sem cookie** | **`JSONPathAgent`** (origem 3); **`RegexAgent`** (origem 0); substituição em **URL** (`placeholder_applier.py:45-46`) |
| 5 | `GET /plain` → 200 `Content-Type: text/plain`, corpo `PLAINVAL777` | Origem que `_find_in_body` não classifica — cai no `return None` de `token_location_detector.py:53-67` |
| 6 | `GET /use-plain`, header `X-Plain: PLAINVAL777` | **`LiteralAgent`** (`candidate_resolver.py:183-184`), e a linha `[AVISO] Não foi possível determinar a origem do token 'PLAINVAL777...'` |
| 7 | `GET /prefs` → 200, cookie `PREFS=xyz789` em `cookies[]` **sem** `Set-Cookie` | Origem classificável como `COOKIE` — construção irrealista, ver §2.2 |
| 8 | `GET /use-prefs`, enviando cookie `PREFS` | **`CookieAgent`** |
| 9 | `POST /submit`, header `Content-Type: application/json`, corpo `{"a": 1}` | **`HeaderAgent` com sucesso** — origem 3, cujo *response* tem o header `Content-Type: application/json`; `_by_name` acha e casa |

Também coberto, sem entry dedicada: `status = "NotFound"` (todo candidato `url` e o
candidato `body`), e substituição em header.

⚠️ **O par 7+8 é obrigatoriamente um par**, e o par 5+6 também. Um cookie só vira
candidato quando uma requisição **posterior** o envia — `BaselineDiff._diff_cookies`
(`tracking/baseline_diff.py:31-37`) compara os cookies da *requisição* contra o
baseline. E `ResponseGrep._eligible_response_files` só considera respostas de step
**< o atual** (`tracking/response_grep.py:89`), então um token cuja origem seria a
**última** resposta nunca vira candidato.

⚠️ **Nenhuma entry pode ser simultaneamente origem de `RegexAgent` e `CSSAgent`
para o mesmo valor.** `_locate_in_html` (`token_location_detector.py:82-88`)
devolve `SCRIPT` só se o valor estiver exclusivamente dentro de `<script>`, e
`BODY_HTML` caso contrário — é XOR por valor. Daí dois valores distintos na entry 0
(`tok_CSS_1` e `scr_NONCE_2`).

⚠️ **O header da entry 4 tem que se chamar `nonce`, não `X-Nonce`.**
`RegexAgent._key_pattern` (`agents/regex_agent.py:20-24`) monta
`{key}['\"]?\s*[:=]\s*['\"]?(…)`. Com `nonce`, casa direto em
`var nonce = "scr_NONCE_2"`. Com `X-Nonce`, a primeira estratégia falha, o
`_context_pattern` só acerta na segunda, e a rodada paga **+5 s** de
`time.sleep` (`agents/base_agent.py:161`).

⚠️ **Só a entry 3 envia `SESSIONID`.** Cada step adicional que reenvia o mesmo
cookie forka um slot novo (defeito §6.2) e paga outro `time.sleep(5)`. Medido: com
as entries 3 e 4 enviando, `dry` custava **10,7 s** e gerava dois
`LiteralFallbackAgent`; com só a entry 3, **5,7 s** e um.

⚠️ **A fixture não tem token de corpo resolvível, e isso é impossível de mudar.**
`BaselineDiff._diff_body` (`tracking/baseline_diff.py:39-50`) emite o path `"body"`
com o **corpo inteiro** como valor, e `_find_origin`
(`tracking/candidate_resolver.py:70-77`) faz grep desse texto inteiro nas respostas
anteriores — nunca casa. Ver §6.4. A substituição em corpo é coberta por outra via:
o token de `X-Csrf` resolve e `_replace_in_body` o substitui também no corpo.

**Alternativa descartada:** commitar a captura de localhost. Rejeitada por levar
cookie de sessão e corpo de resposta de ambiente real para o histórico permanente do
git, e porque uma captura cobre os caminhos que por acaso contém.

### 3.2.1 A fixture mínima, para `success_criteria`

A fixture principal paga 5 s de `sleep` — consequência do defeito §2.2 e do preço
de ser realista. Usá-la nos 8 cenários de critério custaria ~45 s para testar algo
sem relação com análise de token.

Então os cenários de `success_criteria` usam uma segunda fixture de **uma entry
só**: `GET /only` → 200, `Content-Type: text/html`, corpo com `<div id="marker">`, e
`redirectUrl`. Baseline e step são o mesmo, `BaselineDiff` não acha diff, nenhum
agent roda. Medido (fato 8): 8 cenários, veredito esperado em todos, <1 s cada,
`extractors/` vazio.

Precisa de `redirectUrl` porque `Validator._check_criterion`
(`validation/validator.py:32-34`) lê `response.redirect_url` para `url_match`, e de
corpo HTML porque `html_element_present` roda `soup.select_one`
(`validator.py:40-45`).

⚠️ Divisão estrita: a fixture principal é a única que exercita análise de token,
skip e replay; a mínima é a única que exercita validação de critério. **Nenhum
cenário usa as duas.** Corolário: a entry 9 da fixture principal **não** precisa de
`redirectUrl` — uma versão anterior desta spec exigia isso da última entry e se
contradizia com esta subseção.

### 3.3 Servidor HTTP falso local, e o golden de rede é permanente

Classe de respostas canned em `tests/support/`, em `127.0.0.1` numa porta livre; o
HAR é materializado no teste com a porta interpolada.

É o que torna o ramo `replay` — o de maior densidade de bugs recentes, e que **não
tem modo `dry`** — caracterizável antes da refatoração, sem nenhum seam.

O golden de rede **fica na suíte permanentemente**, marcado `slow` e fora da rodada
padrão. O opt-in exige **três** hooks em `tests/conftest.py`, porque `pytest.ini` não
pode ser tocado (§3.7): `pytest_addoption` para criar `--runslow`,
`pytest_configure` + `addinivalue_line` para registrar o marcador (senão sai
`PytestUnknownMarkWarning`), e `pytest_collection_modifyitems` para de fato pular.

⚠️ **Duas restrições sobre o `CannedHttpServer`, ambas sobre a porta não escapar para
o conteúdo comparado.** As duas são da mesma categoria: a máscara
`127.0.0.1:<PORT>` esconde a porta, mas não esconde os **efeitos derivados** dela.

1. **Nenhum corpo canned pode embutir a porta.** `real_responses/*.json` grava
   `Content-Length` (medido: `"77"`), e uma porta de 4 vs 5 dígitos mudaria o
   comprimento enquanto a máscara esconderia a causa.
2. **A porta tem que ter 5 dígitos** — `CannedHttpServer` assere `port >= 10000`.
   Motivo: o cenário do fato 12 congela a mensagem
   `curl: (3) nested brace in URL position N:`, e `N` é um offset em caracteres que
   depende do tamanho da porta. Medido: porta 9999 → `position 29`, porta 40001 →
   `position 30`, e **as duas sobrevivem à máscara de porta** — a normalização não as
   iguala.

⚠️ A faixa efêmera do Linux já garante 5 dígitos (medido neste kernel:
`ip_local_port_range = 32768 60999`), então a asserção nunca deve disparar. Ela existe
para transformar um golden silenciosamente flaky num erro alto e nomeado, caso a
faixa mude ou alguém fixe uma porta pequena à mão. Mascarar `position \d+:` e a linha
do caret foi a alternativa descartada: esconderia parte do comportamento que o fato 12
existe para congelar.

**Alternativa descartada:** golden gravado contra o localhost real. Não seria
commitável, só funcionaria numa máquina com o site no ar, e invalidaria a cada
mudança do site.

### 3.4 O contrato golden

Dois artefatos por cenário, mais um terceiro para cenários de erro.

**(a) A árvore do workspace** — todos os arquivos por caminho relativo e conteúdo,
**incluindo diretórios vazios** (`real_responses/` vazio em `dry` é parte do
contrato, `engines/dry_engine.py:14-15`).

**(b) O `stdout` integral**, linha a linha, na ordem.

**(c) Para cenários de erro** (§5 casos 2-5 e as 5 validações de flag de
`cli/cli_handlers.py:160-173`): o **tipo** da exceção, a **mensagem normalizada**, e
o **`stderr`**. Esses cenários propagam `ValueError` para fora de `main()` e não
produzem árvore nem `stdout` útil — o contrato (a)/(b) não se aplica.

⚠️ `stderr` é obrigatório no contrato (c), não opcional: os 3 cenários de erro do
`argparse` levantam `SystemExit(2)`, cuja "mensagem" é o inteiro `2`. Todo o texto
útil (`usage:`, `invalid choice`) vai para `stderr`. Sem capturá-lo, esses cenários
congelariam apenas "saiu com código 2" e não caracterizariam nada.

⚠️ **Regra de normalização das mensagens de `ValueError`:** as quatro mensagens
embutem caminho absoluto (`Workspace directory does not exist: /tmp/…`), e no caso
§5.2 o caminho **não é** um workspace — a sentinela `<WORKSPACE>` não se aplica.
Regra: substituir o caminho do `tmp_path` do teste por `<TMP>`, em qualquer posição
da mensagem, antes de comparar.

**Como as máscaras se aplicam.** Por **conteúdo**, via regex, sobre todo texto
comparado — não por caminho. Duas consequências que precisam estar na task:

- A máscara de `Date`/`Server` tem que casar **duas formas**: JSON
  (`"Date": "…"`) nos `res_*.json`, e `repr` de dict Python (`'Date': '…'`) dentro
  de `temp_extractors/*.py`, que embutem `repr(response_sample)` via
  `ExtractorTemplate.render_temp_script` e **sobrevivem** em `dry` (defeito §6.3).
  ⚠️ A forma `repr` é **defensiva e sem gatilho conhecido hoje**: em `dry` os headers
  vêm do HAR e a fixture não tem `Date`/`Server` (medido: zero ocorrências nos
  `temp_extractors/*.py`), e em `main` o diretório fica vazio. A task deve
  implementá-la, mas não sair caçando um caso que não existe se ele não aparecer.
- O segmento `replays/<run_id>` é tratado por **caminho** (renomeado no snapshot),
  não por conteúdo, e o conteúdo de `mitm_capture/` é excluído.

**Sentinelas, fixadas:** `<WORKSPACE>`, `<PORT>`, `<RUN_ID>`, `<DATE>`, `<SERVER>`.

**A 6ª fonte de não-determinismo (§2.1) é resolvida por um invariante de cenário,
não por máscara nem pela fixture.**

**O invariante: em nenhum cenário golden dois ou mais tokens podem falhar resolução
no mesmo curl.** É exatamente a condição para a ordem de iteração do `Set[str]` ser
inobservável — com zero ou uma linha `Failed to resolve token` por curl, não há ordem
a variar.

Contagem de falhas medida, **nos 11 cenários de A2**:

| Cenário | Falhas de token | Ordem observável? |
|---|---|---|
| `all`, `slice` (2 variações), `smart` (3 variações), `list` ascendente | **0** em todos | Não |
| fallback de `response_reference_dir` (fato 10) | **0** | Não |
| `list` fora de ordem, `4\n3` (fato 12) | **1**, agrupada no curl do step 4 | Não |
| `run --mode main` | **0** — estruturalmente imune: a mensagem só existe em `ReplayTokenResolver`. O ramo `run` usa `TokenResolver.resolve_all`, que itera um **dict** (`registry.items()`, ordem de inserção) e imprime outra mensagem, `Failed to refresh token` | Não |
| erro §5.5 | **0** — estruturalmente imune: o `ValueError` sai antes de qualquer step rodar | Não |

⚠️ **O invariante é auto-evidente, mas não se auto-verifica** — e a distinção importa.
A informação está no golden de `stdout` (as linhas `Failed to resolve` precedem o
`Step N completed` do seu step, então dá para reagrupar por curl só a partir dele), mas
**nada assere nada**: depende de alguém olhar, e de agrupar por step, porque duas falhas
em curls **diferentes** são inofensivas.

Por isso o invariante vira **asserção no helper de replay**, não convenção: ele agrupa
as linhas `Failed to resolve` pelo `Step N completed` seguinte e assere **máximo 1 por
grupo**. São poucas linhas, e convertem "o autor precisa notar" em "falha na hora, com
nome" — o modo de falha alternativo é um teste ~50% flaky numa **sessão futura**, que é
exatamente o que o invariante existe para evitar.

⚠️ **Duas formulações anteriores desta spec estavam erradas.** A primeira atribuía a
propriedade à *fixture* ("no máximo um token por curl pode falhar") — falsa,
`curls/req_0003.curl.sh` e `req_0004.curl.sh` carregam **dois** tokens cada. A
segunda atribuía ao *modo do workspace* ("todo cenário parte de `main`, logo nenhum
token falha") — também falsa, e o contraexemplo foi medido: `list` com `4\n3\n0`
sobre workspace `main` produz **quatro** falhas, duas no mesmo curl. O `.py` existir
é **necessário, não suficiente**: `ExtractorRunner.run_existing` também devolve `None`
quando o script sai com código 1, e ele sai com 1 quando `_load_response` não acha
`res_{origin:04d}.json` no `override_dir` — que é `replays/<run_id>/` sempre que
`origin_step in schedule` (`replay/replay_token_resolver.py:51-52`). Um `list` que
roda um step **antes** da origem dele não acha nada lá.

⚠️ Cenários excluídos por violarem o invariante: `list` com `4\n3\n0` (4 falhas) e
`replay` sobre workspace `dry` (7 falhas — este último também não caracterizava nada,
§6.8).

⚠️ Ordenar as linhas antes de comparar foi descartado: esconderia uma reordenação
real introduzida pela Etapa B. Se alguma task precisar violar o invariante, a decisão
volta para a mesa — não ordenar em silêncio.

**Regravação** sob `HAR_REPRODUCER_UPDATE_GOLDEN=1`.

⚠️ Regravar golden destrói silenciosamente o valor da suíte. Não faz parte do fluxo
de nenhuma task da Etapa B: se uma task de refatoração faz o golden divergir, **a
task está errada, não o golden**.

### 3.5 Layout, e por que a cópia por cenário é obrigatória

```
tests/
├── conftest.py                  fixtures + os 3 hooks de --runslow
├── support/
│   ├── canned_http_server.py    CannedHttpServer
│   ├── golden_workspace.py      GoldenWorkspace — captura, normaliza, compara, regrava
│   └── cli_invoker.py           CliInvoker — invoca main(), captura stdout e exceção
├── fixtures/
│   ├── synthetic_flow.har       10 entries — análise de token, skip, replay
│   └── minimal_flow.har         1 entry — só success_criteria
├── golden/<cenário>/            árvore + stdout esperados
└── test_cli_{parse,run,replay,config}.py
```

Os cenários de `replay` constroem o workspace com **um** `run --mode main` por
sessão e **copiam** a árvore por cenário.

⚠️ A cópia é **funcionalmente obrigatória**, não otimização: `replay` **muta o
workspace de origem**. `ReplayRunner._annotate_static_tokens`
(`replay/replay_runner.py:101-108`) reescreve `curls/req_NNNN.curl.sh`, e
`ReplayTokenResolver._record_observation` (`replay/replay_token_resolver.py:74-84`)
reescreve `extractors/*.meta.json` (`valid_count`, `last_value`, `ever_changed`).
Sem cópia, os cenários se contaminam independentemente de tempo.

**Contrato de `CliInvoker`:** recebe a lista de `argv`, substitui `sys.argv`,
executa `har_reproducer.main.main()`, captura `stdout` **e `stderr`**, **captura e
devolve a exceção** em vez de deixá-la propagar (para o contrato (c)), e **restaura
`sys.argv` num `finally`**. Invocar `main()` — e não `CliHandlers` direto — é o que
faz o golden cobrir também o parsing de argumentos, os defaults do `argparse` e o
despacho.

⚠️ Invocação **in-process** é decisão, mas **não pelo custo**: o interpretador novo de
um `uv run python -m …` custa **0,455 s medidos**, não "vários segundos". A razão é
capturar `stdout`/`stderr` e pagar o import uma vez por sessão.

⚠️ O que **de fato** faz um cenário de replay custar 4 s em vez de 0,9 s é a
**ausência de servidor upstream**, não o método de invocação. Sem servidor, o
`mitmdump` nunca dispara o hook `response`, `capture.har` nunca é escrito, e
`CurlHttpTransport._read_captured_response`
(`reproduction/curl_http_transport.py:62-68`) queima
`CAPTURE_READ_ATTEMPTS = 5 × 0,1 s` **por step** — 4,0 s num replay de 8 steps.
Registrado aqui porque quem investigar uma suíte lenta no futuro vai começar por esta
seção, e a atribuição errada custaria a investigação inteira.

⚠️ `CliInvoker` tem que tratar `SystemExit` separado de `Exception`:
`parse_args` chama `sys.exit(2)` para `--mode` inválido ou `--har` ausente, e
`SystemExit` não é subclasse de `Exception`.

### 3.6 Cenários

O plano enumera cada cenário com nome e `argv` exato. Contagem-alvo:

| Bloco | Grupo | Cenários | Custo medido |
|---|---|---|---|
| A1 | `parse` | 3 — padrão; `--output` omitido; `--reset` | ~0 s |
| A1 | `run --mode dry` | 2 — padrão; `--reset` | 5,7 s cada |
| A1 | `success_criteria` | 9 — os 4 tipos em sucesso e falha, mais o caso de **lista vazia** (README:146: "o fluxo é considerado bem-sucedido sem validação adicional") | <1 s cada |
| A1 | `skip_rules.methods` customizado | 1 — config com `methods: ["OPTIONS", "POST"]`, que passa a pular as entries 3 e 9 | **0,08 s** (fato 13) |
| A1 | erros de `argparse` | 3 — `--mode` inválido; `--har` ausente; `--mode` ausente no replay | ~0 s |
| A1 | erros **offline** de `replay` | 8 — as 5 validações de flag + §5.2/§5.3/§5.4 | ~0 s |
| **A1** | | **26** | **~12 s** |
| A2 | `run --mode main` | 1 — constrói o workspace de todos os replays, **e já é o cenário de `proxy_port`** | 11,2 s |
| A2 | `replay` | 7 — `all`; `slice` sem flags e com `--from`/`--to`; `smart` sem flags, com `--to`, e com `--from`; `list` ascendente | 0,83–1,02 s cada |
| A2 | `replay --mode list` **fora de ordem** | 1 — `--steps-file` = `4\n3` (fato 12) | 0,87 s |
| A2 | `replay`, fallback de `response_reference_dir` | 1 — o redesenhado (fato 10) | 0,78 s |
| A2 | erro de `replay` que exige proxy | 1 — §5.5, o único que roda dentro do callback do orchestrator | ~1 s |
| **A2** | | **11** | **~20 s** |

⚠️ **Os 8 cenários de erro de `replay` ficam em A1, não em A2.** Medido: as 5
validações de flag saem em `cli_handlers.py:89` e os casos §5.2/§5.3/§5.4 em
`:105-106`, `:109-110`, `:115-116` — **todos antes** da construção do
`MitmProxyOrchestrator` na linha 96. São offline, custam ~0 s, e são a cobertura mais
barata da suíte. Deixá-los em A2 os tiraria da rodada padrão. Só o §5.5 precisa do
proxy, porque `_require_all_existing` roda dentro do callback de `orchestrator.run`.

⚠️ **`proxy_port` não ganha cenário próprio.** O `run --mode main` que constrói o
workspace **é** o cenário: ele pede uma porta livre e a passa no config como se fosse
fixa, o que exercita `MitmProxyOrchestrator._resolve_port` (`:33-37`) no ramo
`proxy_port is not None`. Fixar um número no arquivo colidiria com o §5.9, e um
segundo `run --mode main` custaria 11,2 s para congelar a mesma árvore. Este cenário
**não** passa `ca_cert_path` — esse campo continua fora da cobertura (ver a ressalva
no fim desta seção).

⚠️ **O cenário de `skip_rules` congela um encadeamento não óbvio, e vale dizer isso na
task.** Com `methods: ["OPTIONS","POST"]` a entry 3 é pulada — e ela é a única que
envia `SESSIONID` (⚠ acima), então desaparecem o `HeaderAgent` falhando, o
`LiteralFallbackAgent` **e o `sleep`**: 0,08 s, quatro extratores. Mas o
`JSONPathAgent` **sobrevive**, apesar de sua origem (step 3) ter sido pulada, porque
`original_responses/res_0003.json` guarda a resposta **do HAR** e não um stub de skip
(`engines/engine.py:103-107` persiste antes de avaliar o skip), e em `dry` o tracking
lê `original_responses/`. É o §5.7 sendo load-bearing. Sem esse aviso, alguém
"corrige" o golden achando que é bug.

⚠️ **O cenário de `list` fora de ordem é o único que cobre a característica
definidora do modo.** README:102 promete "na ordem em que aparecem no arquivo"; um
`list` ascendente é indistinguível de um `slice`. A escolha de `4\n3` — e não de
`4\n3\n0` — é deliberada: as duas executam fora de ordem, mas `4\n3` produz **uma**
falha de token e `4\n3\n0` produz **quatro, duas no mesmo curl**, violando o
invariante de §3.4. Medido nas duas.

⚠️ O cenário do default de `--output` copia o HAR para um `tmp_path` **antes** de
invocar, senão o teste escreve dentro de `tests/fixtures/`.

⚠️ **Como os cenários `--reset` populam o diretório.** Precisa ser explícito porque
muda o golden: eles criam um arquivo-sentinela **fora** dos subdiretórios do
workspace (ex.: `<output>/lixo.txt`) e afirmam que ele desapareceu. Para `run` isso
distingue `--reset` do default. Para `parse`, é a **única** coisa que distingue:
`HARParser.split_har` (`fs_io/har_parser.py:87-90`) já faz `rmtree` incondicional de
`<output>/parse`, então `parse --reset` e `parse` sem `--reset` produzem árvore
idêntica a menos que exista conteúdo fora de `parse/`.

Cobertura do `README.md`: os 3 comandos, as **14** flags (3 em `parse`, 5 em `run`,
6 em `replay` — `cli/cli_parser.py:27-35,40-55,60-79`), os 4 modos de `replay`, os 5
agents, e os campos `success_criteria`, `proxy_port`, `response_reference_dir` e
`skip_rules`.

⚠️ Duas ressalvas honestas nessa frase de cobertura:
- **Os 5 agents são cobertos só em `dry`.** Em `main` são 6 tipos, sem `CookieAgent`
  (§2.2, fato 11).
- **`ca_cert_path` não é coberto, é declarado irrelevante** (§5.8): a fixture é HTTP
  puro e `curl` só lê o CA em TLS. Não está na lista acima de propósito.
- O campo `llm` fica fora por escopo (§1).

### 3.7 Zero alteração fora de `tests/`

O diff desta etapa adiciona `tests/` e esta pasta de `docs/`. Nada mais.

É o que garante que a rede mede o comportamento que a Etapa B vai preservar. Se um
teste parecer exigir mudança fora de `tests/`, a resposta é **registrar a limitação
na §6 e deixar o caso sem cobertura**, não relaxar a restrição.

⚠️ A promessa vale para o **diff**, não para a **execução**: rodar a suíte cria
`<repo>/.mitmproxy/` em todo `run`/`replay`, inclusive `dry`, porque
`ProjectConfigLoader._apply_defaults` (`config/project_config_loader.py:35-38`)
chama `Workspace.get_mitmproxy_ca_path()`, que faz `mkdir`
(`fs_io/workspace.py:40-43`). O diretório é gitignored, então o diff se sustenta.

⚠️ Consequência aceita: nenhum teste substitui `CurlHttpTransport`, `time.sleep` ou
`subprocess`. Orçamento, somando os custos medidos da tabela §3.6:

| | Cenários | Tempo |
|---|---|---|
| A1 (rodada padrão) | 26 | **~12 s** — dominado por **dois** dos três `run --mode dry` a 5,7 s, cada um pagando um `sleep` de 5 s. O terceiro (`skip_rules`) custa 0,08 s e **não** paga `sleep` (fato 13) |
| A2 (só com `--runslow`) | 11 | **~20 s** — 11,2 s do `run --mode main` (dois `sleep`) + ~9 s dos 10 replays |
| **Total com `--runslow`** | **37** | **~32 s** |

Ou seja: **~20 s dos ~32 s são `time.sleep`** do defeito §6.1. A Etapa B derruba isso
com o seam de espera (§3.8, item 3) — não otimizando a suíte, mas removendo a espera
real.

### 3.8 Esboço da Etapa B (não implementar agora)

Corte "nível 2": as costuras que desbloqueiam teste, e nada além.

1. `Workspace` deixa de ser singleton e vira instância injetada, com atributos
   explícitos em vez de `setattr`. **Dez** arquivos o referenciam: `base_agent`,
   `cli_handlers`, `project_config_loader`, `engine`, `replay_result_comparator`,
   `replay_runner`, `curl_http_transport`, `extractor_metadata_store`,
   `extractor_runner`, `mitm_proxy_orchestrator`.
2. Seam de transporte HTTP, para `replay` rodar offline.
3. Seam de espera, para os `time.sleep` de `BaseAgent` e `CurlHttpTransport` não
   custarem tempo real.
4. `ScriptExecutor` encapsulando o `subprocess.run([sys.executable, ...])`
   duplicado em `agents/base_agent.py:181-200` e
   `reproduction/extractor_runner.py:52-71`. ⚠️ Os dois tratam exceção de forma
   **diferente** (`BaseAgent` captura só `TimeoutExpired`; `ExtractorRunner` captura
   `Exception`) e a divergência precisa ser preservada.
5. Injeção de colaboradores no ramo `run`: `TokenTracker`, `CandidateResolver` e
   `TokenResolver` recebem o que hoje constroem internamente, mais um
   `AgentFactory`. O ramo `replay` **já** segue esse padrão
   (`cli/cli_handlers.py:119-147`) — é o formato-alvo.

⚠️ **`StepRequest.is_skippable` não pode ser removido em B.** Ele é código morto
como leitura (§6.5), mas é **serializado** em `real_requests/*.json` — medido:
`false` no step 0, `true` no step pulado. Faz parte do contrato golden.

Fora do corte, para etapa posterior: `DryEngine` como estratégia injetada,
factories como raízes de composição, `ProjectPaths`, `Reporter` no lugar dos 31
`print`, quebra dos arquivos multi-classe.

### 3.9 Esboço da Etapa C (não implementar agora)

Unitários por classe, priorizados pela densidade histórica de bugs:
`ReplayRunner._schedule_*`, `CandidateResolver._find_slot`/`_check_slot`,
`ReplayTokenResolver`, `BaselineDiff`, `TokenLocationDetector`,
`ResponseGrep.value_variants`, `BaseAgent.run_tdd_loop` e as estratégias
determinísticas de cada agent.

---

## 4. Componentes novos

| Componente | Bloco |
|---|---|
| `tests/fixtures/synthetic_flow.har` — 10 entries (§3.2), com placeholder de porta | A1 |
| `tests/fixtures/minimal_flow.har` — 1 entry (§3.2.1) | A1 |
| `tests/support/golden_workspace.py` → `GoldenWorkspace` | A1 |
| `tests/support/cli_invoker.py` → `CliInvoker` | A1 |
| `tests/conftest.py` — fixtures + os 3 hooks de `--runslow` | A1 |
| `tests/test_cli_parse.py`, `test_cli_run.py`, `test_cli_config.py` | A1 |
| `tests/support/canned_http_server.py` → `CannedHttpServer` | A2 |
| `tests/test_cli_replay.py` | A2 |
| `tests/golden/**` | A1+A2 |
| Tudo fora de `tests/` — **nenhuma alteração** (§3.7) | — |

---

## 5. Casos de borda

| # | Caso | Comportamento congelado |
|---|---|---|
| 1 | Vários testes no mesmo processo | `run` e `replay` chamam `Workspace.init()`, que sobrescreve os atributos de classe. ⚠️ Mas **`parse` não chama** — `handle_parse` (`cli/cli_handlers.py:79-85`) usa `HARParser.split_har`, que não toca `Workspace` e faz seu próprio `rmtree`+`mkdir` de `<output>/parse` (`fs_io/har_parser.py:84-104`). E no caso 2 abaixo o `ValueError` é levantado **antes** do `init`. Logo o singleton pode apontar para o `--output` de um teste anterior. Nenhum teste pode tocar `Workspace` sem passar pelo CLI |
| 2 | `replay` sobre diretório inexistente | `ValueError("Workspace directory does not exist: …")` (`cli_handlers.py:105-106`), **antes** de qualquer `mkdir` |
| 3 | `replay` sobre workspace sem `req_*.curl.sh` | `ValueError("Workspace has no curl files: …")` (`cli_handlers.py:109-110`) |
| 4 | `response_reference_dir` inexistente | `ValueError("response_reference_dir does not exist: …")` (`cli_handlers.py:115-116`) |
| 5 | `smart`/`list` referenciando step pulado | `ValueError` de `_require_all_existing`. **Medido** (fato 6) |
| 6 | Segunda rodada de `run` no mesmo `--output` | **Não é idempotente** (§6.2). Todo cenário usa `--output` virgem. `parse`, ao contrário, **é** idempotente |
| 7 | Steps pulados | Em `main`, `real_responses/res_0001.json` e `res_0002.json` **existem**, com `status_code: 0` e `skipped: true` (`engine.py:122-126`). Em `dry`, `real_responses/` fica vazio. `original_responses/` e `real_requests/` recebem **todos** os steps nos dois modos (`engine.py:103-107`) |
| 8 | `ca_cert_path` | `_apply_defaults` põe o **diretório** `<repo>/.mitmproxy`; `MitmProxyOrchestrator.__init__:29` deriva `<confdir>/mitmproxy-ca-cert.pem`, que **existe** (gerado pelo mitmdump). E `CurlHttpTransport._tls_flag` (`curl_http_transport.py:52-56`) **nunca** emite `--insecure`, porque `ca_cert_path` nunca é `None`. Irrelevante para a fixture, que é HTTP puro |
| 9 | `mitmdump` não sobe / porta ocupada | `RuntimeError` de `_wait_until_ready` (`mitm_proxy_orchestrator.py:96-105`). Não é cenário golden — é falha de ambiente, e deve dar erro claro em vez de golden divergente |
| 10 | HAR com zero entries | `IndexError` em `engine.py:83` (`entries[0]`). Congelado (§6.5). Sem teste — golden de traceback é frágil |
| 11 | Dois `replay` no mesmo segundo | `run_id` colide (`cli_handlers.py:95`). Inócuo porque cada cenário tem sua própria cópia; o golden afirma **exatamente um** diretório de run por cenário |

---

## 6. Dívida catalogada — defeitos congelados

Esta etapa **não corrige nada**. São nove itens: **6.1 a 6.4, 6.8 e 6.9 verificados
por execução**; **6.5, 6.6 e 6.7 por grep e leitura**.

**6.1 Cookie de sessão vira literal, nos dois modos.** Detalhado em §2.2. Para
cookie setado na mesma resposta — o caso mais comum — `CookieAgent` é inalcançável e
a ferramenta emite valor hardcoded. É de onde vêm o `Attempt 1 failed` e os 5 s de
`time.sleep` medidos.

**6.2 `run` não é idempotente em `dry`, e infla os extratores mesmo numa rodada
só.** Causa raiz única: em `dry`, `extractors/*.meta.json` é gravado mas
`extractors/extract_*.py` **nunca** é —
`ExtractorRunner._write_extractor_script` (`reproduction/extractor_runner.py:31-42`)
só roda via `ExtractorRunner.run`, alcançado apenas sob `if self.USES_NETWORK`
(`engines/engine.py:110-111`). Então `CandidateResolver._check_persisted_slot`
(`tracking/candidate_resolver.py:110-120`) não acha o `.py`, recebe `None`,
classifica o slot como `Mismatch`, e `_find_slot` (`:79-92`) forka um `token_id`
novo. Medido: com dois steps reenviando o mesmo cookie, `dry` gera **dois**
`LiteralFallbackAgent` e paga 10,7 s; numa segunda rodada no mesmo `--output`, os
extratores **dobram** e os curls são reescritos com ids diferentes. Em `main`, onde o
`.py` é escrito, não forka.

**6.3 `temp_extractors/` nunca é limpo em `dry`** — mesma causa raiz: a limpeza está
em `ExtractorRunner._cleanup_temp_file` (`extractor_runner.py:44-50`), no caminho não
percorrido. Consequência para o golden: esses arquivos fazem parte da árvore, e
embutem `repr(response_sample)` (§3.4).

**6.4 Token de corpo de requisição é irresolvível por construção.**
`BaselineDiff._diff_body` (`tracking/baseline_diff.py:39-50`) emite o path `"body"`
com o **corpo inteiro** como valor; `_find_origin` faz grep desse texto inteiro nas
respostas anteriores. Só casaria se um corpo de requisição inteiro aparecesse
literalmente numa resposta anterior. Verificado por A/B: com e sem `postData` na
entry 0, o `stdout` é byte-idêntico e os extratores são os mesmos.

**6.5 Código morto, confirmado por grep.** `Engine.curls_dir`, `.extractors_dir` e
`.temp_extractors_dir` (`engines/engine.py:38,41,42`) — atribuídos, nunca lidos;
`.original_responses_dir` (`:39`) é morto **como atributo de `Engine`**, mas o nome é
vivo em `ReplayRunner:41,81` e `ReplayTokenResolver:31-72`. Também: o `TypeAlias`
`contracts.StepExecutor` (`contracts/types.py:9`, cuja assinatura nem corresponde ao
`execute_step` atual); `SessionStore.get_token` (`session/session_store.py:18`) e
`render_dict` (`:26`); o `raise RuntimeError` final de `StepRetryPolicy.execute`
(`reproduction/step_retry_policy.py:23`), inalcançável porque na última tentativa o
`return` sempre ocorre; `engine.py:83` acessando `entries[0]` sem guarda.
`StepRequest.is_skippable` (`models/http.py:13`) é morto como leitura mas **está no
contrato golden** (§3.8).

**6.6 Nomes que mentem e efeitos colaterais fora de lugar.**
`MitmProxyOrchestrator.project_root` (`mitm_proxy_orchestrator.py:26-27`) recebe o
`ca_cert_path`, que é o `confdir` do mitmproxy — e é um **diretório**, não o arquivo
que o nome sugere. `ProjectConfigLoader._apply_defaults` cria `.mitmproxy/` como
efeito colateral de carregar config, inclusive em `dry`, que nunca usa proxy.
`BaseAgent.run_tdd_loop` (`agents/base_agent.py:139-161`) dorme 5 s mesmo quando a
estratégia que falhou foi determinística e mesmo depois da última tentativa.

**6.7 `pytest` e `pytest-httpx` estão em `dependencies`, não num grupo dev**
(`pyproject.toml:17-18`). `pytest-httpx` está declarado e não é usado por nada. Mover
é fora de escopo por §3.7.

**6.8 O exemplo que o README dá para `response_reference_dir` é inalcançável.**
README:149 descreve o fallback assim: "quando a resposta de um passo específico não
existir ali (ex.: **workspace que só rodou `dry`**), o `replay` cai automaticamente
para `<output>/original_responses/`". Mas num workspace `dry` não existe nenhum
`extractors/extract_*.py` (defeito §6.2 — medido: 7 `.meta.json`, zero `.py`), e
`ExtractorRunner.run_existing` (`reproduction/extractor_runner.py:26-28`) sai em
`if not extractor_file.exists(): return None` **antes** de usar o
`response_override_dir`. Então `_reference_dir_for_step` é chamado, mas o diretório
que ele devolve nunca é lido: os dois ramos produzem `None`. Medido: `replay` sobre
workspace `dry` emite **sete** `Failed to resolve token` e resolve zero.

O recurso **funciona** — só não pelo caminho que o README documenta. É por isso que o
cenário de §3.6 usa workspace `main` com uma referência incompleta (fato 10), e não o
exemplo do README. Corrigir o README, ou corrigir §6.2 para que o exemplo passe a
valer, é decisão de outra etapa.

**6.9 Token não resolvido vira placeholder cru no `curl`, e o `replay` reporta
sucesso.** Medido (fato 12) com `replay --mode list --steps-file` = `4\n3`: o token
`ade6a530` tem origem no step 3, que está no schedule mas roda **depois** do step 4,
então `replays/<run_id>/res_0003.json` ainda não existe e a resolução falha. O
`{{extractor:…}}` literal é interpolado no comando e o `curl` morre com
`curl: (3) nested brace in URL`. O step 4 fica com `status_code: 0` — e o replay ainda
imprime `✓ SUCCESS` e `Reproduction SUCCESSFUL`, porque
`ReplayResultComparator.matches_original` compara apenas o **último step da lista**
(step 3, status 200) contra a referência dele.

Dois problemas independentes: um token irresolvível degrada para texto literal no
comando em vez de abortar o step com erro claro, e o veredito final do `replay`
ignora o status dos steps intermediários. Comportamento congelado pelo cenário; a
decisão de corrigir é de outra etapa.

---

## 7. Riscos aceitos

1. **`load_dotenv()` em `main.py:11`** lê o `.env` real do CWD em toda invocação e
   muta `os.environ` pelo resto do processo do pytest;
   `ExtractorRunner._build_env` (`extractor_runner.py:73-78`) propaga isso para todo
   subprocesso de extrator. O repo tem `.env` real (gitignored) → dev e CI divergem.
   Inócuo hoje porque nenhum cenário configura `llm`, mas é entrada não controlada
   numa suíte golden.
2. **A suíte não pode rodar em paralelo nem com ordem aleatória.** `Workspace` é
   singleton de atributo de classe e `parse` nunca o reinicializa (§5.1). Restrição
   explícita até a Etapa B.
3. **`mitm_capture/capture.har` é arquivo de slot único** —
   `MitmAddon._write_envelope` sobrescreve a cada response, e
   `CurlHttpTransport._try_read_capture` (`curl_http_transport.py:70-79`) lê
   `entries[0]` com 5 tentativas de 0,1 s. Qualquer tráfego concorrente pelo proxy
   devolve silenciosamente a resposta do step errado. A §3.4 exclui `mitm_capture/`
   da comparação, mas ele é o canal load-bearing do modo `main`.
4. **Primeira rodada em máquina limpa pode ser flaky.** Sem `.mitmproxy/` populado,
   o primeiro cenário de rede paga a geração de certificado, que pode passar dos
   `HEALTH_CHECK_TIMEOUT_SECONDS = 10.0` e cair no `RuntimeError` do §5.9.

---

## 8. Referência

Todo código desta etapa, inclusive em `tests/`, segue
`.claude/skills/guia-de-estilo/SKILL.md`: tipagem explícita em toda variável,
parâmetro, retorno e atributo; `ClassVar` para constantes de classe; `Path` para
caminhos; uma classe por arquivo; nenhum comentário e nenhuma docstring; guard
clauses e no máximo dois níveis de indentação.

⚠️ Exceção inevitável: fixtures de `pytest` e funções `test_*` são funções de
módulo por exigência do framework. A regra vale integralmente para
`tests/support/`, que deve ser todo em classes.
