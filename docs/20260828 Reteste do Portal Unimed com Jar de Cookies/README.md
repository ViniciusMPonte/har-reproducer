# Reteste do Portal Unimed com Jar de Cookies

Nesta captura real, o jar de cookies é **indiferente** para o `JSESSIONID` (H1 confirmada,
0 divergências em 105 steps comparados) e mantém corretamente os dois escopos de mesmo
nome em paths diferentes sem contaminação (H2 confirmada) — mas a integração do jar em
`Engine._attempt_step` (`har_reproducer/engines/engine.py:155`) introduziu uma **regressão
real e determinística**: o comando `run` trava com exceção não tratada e sai com código 1
antes de terminar a reprodução, algo que não acontecia na verificação de 25/08 contra o
mesmo HAR.

## Procedência

| Item | Valor |
|---|---|
| Repositório | `/home/viniciuspontes/Documentos/Trabalho/har-reproducer` |
| Branch | `master` |
| Commit no momento da investigação | `7f689a03b511c3406043eb5b7802e93967459247` (2026-08-28 17:01:27 -0300) |
| Commit que introduziu `CookieJar` | `ad9ac19` — "feat: T05 — CookieJar: estrutura em memória por escopo de domínio/porta/path" |
| HAR usado | `/home/viniciuspontes/Documentos/Trabalho/har-files/teste-unimed/captura_20260825_184021_reduzido.har` (107 entradas, a mesma da verificação de 25/08) |
| Config | `/home/viniciuspontes/Documentos/Trabalho/har-reproducer/config.json` |
| Comando exato | `uv run python -m har_reproducer.main run --har .../captura_20260825_184021_reduzido.har --config .../config.json --mode main --output <diretório novo>` |
| Diretório de saída (execução 1) | `/home/viniciuspontes/Documentos/Trabalho/har-files/teste-unimed/output-com-jar/` |
| Diretório de saída (execução 2, repetição para confirmar determinismo) | `/home/viniciuspontes/Documentos/Trabalho/har-files/teste-unimed/output-com-jar-run2/` |
| Baseline "antes" (sem jar, 25/08) | `/home/viniciuspontes/Documentos/Trabalho/har-files/teste-unimed/output/` |
| Rede real alcançada? | **Sim** — `autorizador.unimedriopreto.com.br` respondeu (verificado com `curl` antes de rodar: `HTTP_CODE:301`), e as duas execuções fizeram tráfego real, gravando `real_requests`/`real_responses` até o step 104 em ambas. |

## H1 — o jar é indiferente aqui (JSESSIONID já era corretamente rastreado via `CookieAgent`)?

**Confirmada, com evidência de comparação direta step a step.**

Os dois `CookieAgent` continuam sendo gerados, idênticos aos de 25/08:

| `token_id` | `agent_type` | `origin_step` | `captured_value` |
|---|---|---|---|
| `f41911849a637da03174142e36746942` | `CookieAgent` | 0 | `9760F3F75532F8765755431F77C8B31B` |
| `4366abcaced3482b036c0cde39ec3fd3` | `CookieAgent` | 14 | `60C24DDABF08B692114B40B5B7198304` |

Comparando `real_requests/req_*.json` (campo `cookies['JSESSIONID']`) e `real_responses/res_*.json`
(campo `status_code`) para os 105 steps que as duas execuções têm em comum (0 a 104):

- **0 divergências** no valor de `JSESSIONID` enviado.
- **0 divergências** no dicionário completo de cookies enviados (`cookies`).
- **0 divergências** em `status_code`.

O jar aplica, por cima do curl resolvido, exatamente o mesmo valor que o `CookieAgent`/
`session_store.render` já aplicava via placeholder — resultado observável idêntico. A única
diferença aditiva é o campo novo `cookie_attributes`, populado em `real_responses/res_0000.json`
e `res_0014.json`:

```
res_0000.json: {'JSESSIONID': {'domain': None, 'path': '/PlanodeSaude', 'expired': False}, ...}
res_0014.json: {'JSESSIONID': {'domain': None, 'path': '/Wheb_Config', 'expired': False}}
```

(`original_responses/res_0000.json`, por vir do parse do HAR original — não da captura mitm ao
vivo —, guarda `path: '/'` para o mesmo cookie; isso é inofensivo porque o jar só é alimentado
pela via viva (`real_responses`), nunca por `original_responses`, conforme já registrado na
seção 3.1/⚠️ da spec.)

## H2 — dois `JSESSIONID` de mesmo nome em paths não sobrepostos: o jar mantém os escopos separados?

**Confirmada nesta captura**, por segmento de URL:

| Segmento de URL | `JSESSIONID` enviado | Steps com valor ausente (esperado) |
|---|---|---|
| `/PlanodeSaude/...` | sempre `9760F3F75532F8765755431F77C8B31B` (42 requests) | step 0 (antes do primeiro `Set-Cookie`) |
| `/Wheb_Config/...` | sempre `60C24DDABF08B692114B40B5B7198304` (4 requests) | steps 5, 13, 14 (antes do `Set-Cookie` do próprio step 14, que é a origem) |

Nenhuma mistura entre os dois segmentos foi observada nos 105 steps que rodaram. Isso é
consistente com `CookieJar._matches` (`har_reproducer/session/cookie_jar.py`) casando por
prefixo de path (`request_path.startswith(scope.path)`) sobre dois escopos (`/PlanodeSaude`,
`/Wheb_Config`) que, neste site, não têm prefixo um do outro — não há ambiguidade a resolver.

⚠️ **Isto não é garantia geral.** É um fato verificado nesta amostra específica, com dois
paths que não se sobrepõem por acaso da estrutura do site (duas aplicações Java distintas,
`/PlanodeSaude` e `/Wheb_Config`, cada uma emitindo seu próprio `JSESSIONID`). A limitação
aceita na spec (seção 1, item 1 — sem precedência determinística entre escopos que colidem
no mesmo nome) continua sem cobertura de teste real, porque este HAR não contém esse cenário
mais difícil (paths que sobrepõem, ex. `/` e `/admin`).

## H3 — algum cookie real deste portal expõe o buraco original que motivou o jar (cookie estabelecido antes da gravação, nunca com `Set-Cookie` na própria captura)?

**Encontrado um caso real, mas o jar genuinamente não ajuda nele — como a própria spec prevê.**

O cookie `tamFonte` aparece pela primeira vez em `real_requests/req_0068.json`
(`tamFonte=0`) e é enviado em requests subsequentes, mas **nenhuma resposta da captura**
(nem `original_responses/`, nem `real_responses/`) tem `set-cookie: tamFonte=...` no
header. O comentário do próprio `.curl.sh` gerado (ex. `curls/req_0072.curl.sh`) já lista
`cookie:tamFonte` como `[Unresolved]` — ou seja, hoje é tratado como valor estático/literal
copiado do HAR, exatamente o padrão que a spec da feature descreve como motivador (seção 1,
"Objetivo").

Isso **não é regressão**: é o caso de borda "cookie nunca definido" já documentado na
seção 5 da spec — "jar não ajuda, comportamento idêntico ao atual". Confirmado lendo
`CookieJar.feed` (`har_reproducer/session/cookie_jar.py`): o jar só aprende de um
`Set-Cookie` real observado **dentro da própria execução** (via `feed()`, chamado a partir
de `response.cookies`/`response.cookie_attributes` em `Engine._attempt_step`); como
`tamFonte` nunca chega via `Set-Cookie` nesta captura, o jar nunca tem o que alimentar para
esse nome, e o comportamento seguiu idêntico ao pipeline sem jar (o valor estático do HAR
continuou sendo usado normalmente nos 105 steps executados).

`DWRSESSIONID` também é enviado, mas não foi possível confirmar se tem `Set-Cookie` real na
captura dentro do tempo desta investigação — não muda a conclusão de H3, que já está
confirmada com `tamFonte` como exemplo suficiente.

## Antes/depois (resumo)

| Aspecto | Antes (25/08, sem jar) | Depois (28/08, com jar) |
|---|---|---|
| `CookieAgent` gerados para `JSESSIONID` | 2 (`origin_step` 0 e 14) | 2, idênticos |
| Valor `JSESSIONID` por segmento de path | correto, sem mistura | idêntico, sem mistura (0 diffs em 105 steps) |
| `cookie_attributes` em `real_responses` | campo não existia | populado corretamente (`domain`, `path`, `expired`) nos steps 0 e 14 |
| `status_code` por step (0–104) | — | 0 divergências vs. baseline |
| **Execução completa até o fim (step 106)** | **sim** — `Reproduction SUCCESSFUL`, 107/107 steps | **não** — trava no step 104 com `ValueError` não tratada, processo sai com código 1 |
| Steps efetivamente executados | 107 | 105 (0–104) nas duas repetições |

## Bug real encontrado — regressão causada pela integração do jar

**Resumo**: `Engine._attempt_step` (`har_reproducer/engines/engine.py:152-159`) calcula o
escopo do cookie a partir de `step.request.url` — mas esse campo, para qualquer step cuja
URL real (capturada no HAR) seja *idêntica ao valor já extraído de um token dinâmico*, foi
mutado **em memória, in-place**, para conter o placeholder não resolvido
`{{extractor:<token_id>}}` em vez da URL real. Isso é comportamento pré-existente e
inofensivo até agora (serve só para montar o `curl_template`, que é resolvido de volta via
`session_store.render()` antes de virar tráfego real) — mas o jar é o primeiro código a
rodar `urlparse` sobre esse campo *antes* da resolução, e quebra.

**Cadeia causal exata**:

1. `har_reproducer/tracking/token_tracker.py:32` — `analyze_step` chama
   `self.placeholder_applier.apply(step.request, tokens)`, que **muta `step.request` no
   próprio objeto**, não uma cópia.
2. `har_reproducer/tracking/placeholder_applier.py:45-46` (`_replace_in_url`) —
   `request.url = request.url.replace(value, placeholder)`: qualquer substring da URL igual
   ao `extracted_value` de qualquer token verificado vira `{{extractor:<token_id>}}`.
3. Para o step 104 (`GET https://autorizador.unimedriopreto.com.br/Bibliotecas/bibliotecas/js/menuSlide/menuSlide.js`),
   o extrator `1ffddbb23226d78793a396c2f6044705` (`origin_step=98`, `agent_type=CSSAgent`)
   tem `captured_value = "/Bibliotecas/bibliotecas/js/menuSlide/menuSlide.js"` — exatamente
   o path da própria URL do step 104. `_replace_in_url` troca esse trecho, e
   `step.request.url` em memória passa a ser literalmente
   `"https://autorizador.unimedriopreto.com.br{{extractor:1ffddbb23226d78793a396c2f6044705}}"`
   (confirmado: é o mesmo texto gravado em `output/curls/req_0104.curl.sh`, que é montado a
   partir desse mesmo `request.url` por `CurlGenerator._curl_parts`,
   `har_reproducer/reproduction/curl_generator.py:24`).
4. `har_reproducer/engines/engine.py:90` roda `analyze_step` (passo 1–3 acima) **antes** de
   `execute_step` (linha 92) — a mutação já aconteceu quando `_attempt_step` roda.
5. `har_reproducer/engines/engine.py:155` — `RequestUrlScope.parts(step.request.url)` recebe
   essa string templada (não a versão resolvida `curl_literal` da linha 154, que já passou
   por `session_store.render()`).
6. `har_reproducer/reproduction/request_url_scope.py:16` —
   `parsed.port` (property de `urlparse`) tenta interpretar o trecho depois do último `:`
   dentro do netloc como porta. Como a URL virou
   `.../autorizador.unimedriopreto.com.br{{extractor:1ffddbb23226d78793a396c2f6044705}}`
   (sem `/` separando host do placeholder — o path viria do próprio placeholder expandido),
   `urlparse` interpreta `extractor` como parte do host e
   `1ffddbb23226d78793a396c2f6044705}}` como valor de porta, e `int(port)` explode:
   ```
   ValueError: Port could not be cast to integer value as '1ffddbb23226d78793a396c2f6044705}}'
   ```
7. `har_reproducer/reproduction/step_retry_policy.py:9-21` (`StepRetryPolicy.execute`) **não
   tem nenhum `try/except`** ao redor de `attempt_fn()` — a exceção sobe sem ser capturada
   até `main()`, o processo termina com traceback e código de saída 1. Nenhum step depois do
   104 roda; `_validate_final` nunca é chamado; não há veredito final de sucesso/falha.

**Reprodução**: rodar exatamente o comando da tabela de procedência contra o mesmo HAR
produz esse traceback de forma determinística — confirmado em duas execuções independentes
(`output-com-jar/` e `output-com-jar-run2/`), ambas param exatamente em
`real_requests/req_0104.json` (105 arquivos, de 0 a 104) com o mesmo `ValueError` sobre o
mesmo token.

**Por que isso é regressão e não só "efeito colateral aditivo esperado"**: antes da
integração do jar, `step.request.url` também já era mutado do mesmo jeito por
`PlaceholderApplier` — mas nada no pipeline de execução chamava `urlparse`/`.port` sobre
esse campo. A baseline de 25/08 completou os 107/107 steps com esse mesmo HAR sem erro. A
única mudança de código relevante entre as duas execuções é a chamada nova em
`engine.py:155`.

**Não proponho correção nesta investigação** — conforme pedido, isto é investigação, não
spec/plano de mudança. O ponto de correção mais provável seria calcular `host`/`port`/`path`
a partir da URL já resolvida (`curl_literal`, ou de `step.request.url` só depois de
`session_store.render` também ser aplicado a esse campo, ou extraindo o escopo diretamente
do curl resolvido) em vez de `step.request.url` bruto — mas isso é decisão de spec, e fica
para o usuário decidir se quer abrir uma nova investigação/spec para o conserto.

## O que não foi corrigido / continua sendo risco estrutural

- A limitação aceita de precedência entre escopos de cookie colidentes no mesmo nome
  (spec, seção 1, item 1) continua sem teste real — este HAR não expõe esse cenário.
- O casamento de path por prefixo simples (`startswith`, não RFC 6265 exato) continua sem
  teste adversarial real neste HAR (não achamos, nesta captura, dois paths onde um é
  prefixo textual do outro sem ser um subcaminho genuíno, ex. `/PlanodeSaude` vs.
  `/PlanodeSaudeXYZ`).
- O bug de `step.request.url` mutado in-place por `PlaceholderApplier` sendo lido depois
  como se fosse uma URL "real" é, possivelmente, mais amplo do que só a chamada nova do
  jar — qualquer código futuro que leia `step.request.url` esperando a URL de fato usada
  corre o mesmo risco. Não investigado se há outro ponto do pipeline com esse mesmo
  pressuposto quebrado.

## Limites desta verificação

- **Rede real foi alcançada e usada** nas duas execuções — não foi preciso cair para
  análise estática (H2 foi validada com tráfego real, não com um `CookieJar.feed()` ad hoc
  isolado).
- A execução **não completou** (parou no step 104 de 107) — não há veredito de
  `Reproduction SUCCESSFUL`/`FAILED` para comparar diretamente com o de 25/08 nesta
  reprodução. A comparação de H1/H2 cobre só os 105 steps que rodaram (0–104), não os 107.
- Não foi possível confirmar, dentro do tempo desta investigação, se `DWRSESSIONID` tem ou
  não `Set-Cookie` real nesta captura — não muda a conclusão de H3 (já demonstrada com
  `tamFonte`), mas fica como lacuna.
- Não foi testado nenhum HAR com paths de cookie genuinamente sobrepostos (ex. `/` e
  `/admin` com o mesmo nome de cookie) — a limitação aceita da spec continua sem evidência
  real a favor ou contra, só o comportamento portado do `stickycookie` do mitmproxy como
  referência de design.
- Nenhum código de produção foi alterado nesta investigação. Nenhuma branch foi criada.
