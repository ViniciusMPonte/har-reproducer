# Correção de Extractores via CRUD no Portal Unimed

Nesta verificação, testei se o comando novo `extractor` (CRUD de extratores, spec
[[20260829 CRUD de Extractors]]) permite corrigir um fluxo de reprodução quebrado **sem
rodar `run` de novo** — usando um workspace já existente do portal Unimed. Resultado:
sim, com ressalvas. Consegui corrigir, só com `extractor list/get/test/unbind/delete`,
um bug sistêmico que fazia **toda** a sessão da reprodução ser inválida desde o
primeiro passo — e o `replay --mode all` passou a bater **byte a byte** com a resposta
esperada do HAR original. O `optimize`, porém, expôs um segundo problema (rotação de
`JSESSIONID` no login) que o CRUD **não** consegue terminar de corrigir — limite
estrutural da ferramenta, documentado abaixo, não falta de tentativa.

## Procedência

| Item | Valor |
|---|---|
| Repositório do projeto | `/home/viniciuspontes/Documentos/Trabalho/har-reproducer` |
| Branch / commit do projeto no início desta verificação | `master` / `dee6dea` (2026-08-29 17:35:46 -0300) |
| Workspace verificado | `/home/viniciuspontes/Documentos/Trabalho/har-files/teste-unimed/output-fix-verificacao` |
| Repositório git criado no workspace (checkpoint) | `git init` local, só para esta verificação — 7 commits, `80338c9`→`647c5de` |
| Config usado | `config.json` do projeto, depois copiado para dentro do workspace e reforçado (ver Achado 3) |
| Nenhum `run --mode main` foi executado nesta verificação | Só `replay`, `optimize` e `extractor <ação>` — nenhum tráfego de descoberta novo |
| Nenhum código de produção (`har_reproducer/`) foi alterado | Confirmado — todas as correções são no workspace de dados |

Estado inicial do workspace (commit `80338c9`): 107 `curls/req_*.curl.sh`, 16
extratores em `extractors/`, `real_requests`/`real_responses`/`original_responses`
com 107 respostas cada — herdado de uma execução anterior de `run --mode main` contra
`autorizador.unimedriopreto.com.br`, já com a correção do bug de `request.url`
templado no `CookieJar` aplicada (spec [[20260828-2 Correção do Bug de request.url
Templado no CookieJar]]).

## Achado 1 — extrator do header `priority` era falso positivo (extrator inútil)

`optimize --to 106` acusou: `Token '3d273c98bc4fa1a7c26268392ce1ed35' could not be
dynamically resolved during replay; using captured value instead.`

- `extractor get --token-id 3d273c98...` mostrou um `RegexAgent` (`origin_step=84`)
  cujo regex nem batia contra a própria amostra de origem (`extractor test` confirmou:
  `"error": "ERROR: Token not found via regex"` contra `res_0084.json`).
- O token estava vinculado ao header `priority` de `req_0085.curl.sh`
  (`priority: {{extractor:3d273c98...}} i`), com `captured_value = "u=1,"`.
- `grep` em todos os `.curl.sh` mostrou que `priority` varia (`u=0`, `u=1`, `u=2`, `i`,
  `u=0, i`...) conforme o **tipo de recurso** da requisição (comportamento padrão do
  Chrome, decidido no cliente) — não é um valor extraído de resposta do servidor. A
  descoberta automática (`BaselineDiff`) classificou como dinâmico algo que na
  verdade é estático por design.

**Correção (CRUD, sem rodar `run`):**

```bash
uv run python -m har_reproducer.main extractor unbind --output <workspace> \
  --token-id 3d273c98bc4fa1a7c26268392ce1ed35 --curl req_0085.curl.sh --value "u=1,"
uv run python -m har_reproducer.main extractor delete --output <workspace> \
  --token-id 3d273c98bc4fa1a7c26268392ce1ed35
```

Resultado: `priority: u=1, i` (literal, correto). Commit `5baa021`.

## Achado 2 — bug sistêmico: header `cookie:` duplicado suprimia `--cookie` (o achado principal)

Depois do Achado 1, `replay --mode all` reportava `Reproduction SUCCESSFUL` (107/107,
status code batendo) — mas **comparar o corpo da resposta, não só o status code**,
mostrou que o passo alvo (106) caía numa página de **sessão expirada**
(`alert("A sua sessão foi expirada, por ficar inativo por mais de 30 minutos!...")`,
4076 bytes) em vez da página esperada (`original_responses/res_0106.json`,
`<title>Página principal prestador</title>`, 19660 bytes). `status_code: 200` sozinho
mascarava essa falha porque o servidor responde 200 com o alerta embutido, não com
redirect.

**Causa raiz, confirmada com teste isolado de `curl`:** todo `.curl.sh` gerado tinha
dois lugares carregando cookie ao mesmo tempo:

```
-H 'cookie: {{extractor:7302a98b561eb9e2213aa8196378b81d}}' \    # sempre só SERVERID
--cookie 'JSESSIONID={{extractor:...}}; DWRSESSIONID={{extractor:...}}; tamFonte=0; SERVERID=ms1'
```

`curl`, quando recebe um header `-H 'Cookie: ...'` explícito **e** `--cookie` na
mesma chamada, **descarta silenciosamente o `--cookie`** e só envia o header
explícito — testado e confirmado com um servidor HTTP local (`Cookie` recebido:
só `SERVERID=ms1`; `JSESSIONID`/`DWRSESSIONID` nunca chegavam ao servidor, em
**nenhum** dos 107 passos, desde sempre). Rastreando `Set-Cookie` de `JSESSIONID` ao
longo da execução: no HAR original (sessão real do navegador) o valor muda só 2 vezes
em todo o fluxo (steps 0 e 14) e nunca mais; na reprodução, o servidor reemitia um
`JSESSIONID` novo repetidamente (steps 12, 15, 35, 88 a 98...) — sinal de que a sessão
nunca "grudava", porque o cookie de sessão nunca era de fato enviado.

Origem do header duplicado: `CurlGenerator._header_parts`
(`har_reproducer/reproduction/curl_generator.py:36-41`) emite `-H` para **todo**
header capturado do HAR, inclusive um eventual `Cookie` literal — e
`CurlGenerator._cookie_part` (linhas 44-50) **também** monta `--cookie` a partir de
`request.cookies`, de forma independente. Isso é código de produção, fora do escopo
do CRUD alterar — mas o **efeito** (o header/curl já persistidos no workspace) é
100% editável via `extractor unbind`.

**Correção (CRUD, 104 curls, sem rodar `run`):** para cada curl com esse padrão, extraí
o texto bruto (com placeholders) do argumento `--cookie` e usei `unbind` para fazer o
header `cookie:` **espelhar exatamente esse texto**:

```bash
uv run python -m har_reproducer.main extractor unbind --output <workspace> \
  --token-id 7302a98b561eb9e2213aa8196378b81d --curl req_NNNN.curl.sh \
  --value "<mesmo texto do --cookie, com os mesmos placeholders>"
```

Como `session_store.render()` resolve `{{extractor:...}}` sobre o texto inteiro do
curl (não importa sob qual flag), os dois lugares passam a resolver para o mesmo
valor, sempre. Script usado: 104/104 curls corrigidos, 3 pulados (sem esse token).
Commit `7f1e3cf`.

**Verificação:** `replay --mode all` → 107/107 passos, e o corpo do step 106 bateu
**byte a byte** com `original_responses/res_0106.json` (única diferença: o próprio
valor dinâmico do `JSESSIONID` embutido num trecho de JS — esperado, é por-sessão).
`JSESSIONID` passou a mudar só nos steps 0 e 14, igual ao HAR original. Commit
`1a8e182`.

## Achado 3 — `success_criteria` só com `status_code` mascara o problema

O `optimize --to 106` (config padrão, só `status_code: 200`) reportava
`Optimization SUCCESSFUL` com o schedule mínimo `[0, 106]` — mas rodar esse schedule
**isolado** (`replay --mode list`, fora do processo de busca do `optimize`) mostrou
que ele **não** reproduz o sucesso real: cai na mesma página de sessão expirada. O
`optimize` "passava" só porque reaproveita cache de cookies/backbone estabelecido
durante a própria busca — não é um resultado que se sustenta sozinho.

**Correção:** copiei `config.json` para dentro do workspace e reforcei
`success_criteria` com um segundo critério:

```json
{
  "success_criteria": [
    { "type": "status_code", "expected": 200 },
    { "type": "body_contains", "expected": "Página principal prestador" }
  ]
}
```

Com esse critério, `optimize` passou a **recusar corretamente** um schedule que não
alcança a página real, em vez de reportar um falso positivo. Commit `647c5de`.

## Achado 4 — 2 extratores de paths estáticos frágeis durante `optimize`

Com o critério reforçado, `optimize` acusou fallback em mais 2 tokens
(`1ffddbb23226d78793a396c2f6044705`, `e9167622be000ffc8cd3cde776e3d1d6`) — extratores
`CSSAgent` que extraem os paths de `menuSlide.js`/`MenuSlide.css` do corpo do step 98.
Esses paths são ativos estáticos do site (mesma URL sempre, confirmado via `grep`) —
frágeis porque dependem de `res_0098.json` estar disponível exatamente no contexto de
execução parcial do `optimize`. Corrigidos com o mesmo padrão do Achado 1 (`unbind` +
`delete`). Commit `9d1fa18`.

## Achado 5 — rotação de `JSESSIONID` no login: limite real do CRUD

Com todos os achados 1-4 corrigidos, `optimize --to 106` (critério reforçado) ainda
falha de forma **intermitente**: às vezes `Optimization SUCCESSFUL` com conteúdo
correto, às vezes `aborted — faixa (87, 106) falhou mesmo com todos os candidatos
incluídos`.

**Causa raiz, isolada comparando um run bom com um run ruim (mesmo workspace, mesmos
fixes):** o ponto de divergência é sempre o step 92 (`POST
/PlanodeSaude/login.action`, envio de usuário/senha):

- **Run bom:** login não dispara `Set-Cookie` — a sessão pré-login segue sendo a
  sessão autenticada depois.
- **Run ruim:** login dispara `Set-Cookie: JSESSIONID=<novo>` — o servidor
  **rotaciona a sessão no login** (proteção padrão contra session fixation), e a
  partir daí o `JSESSIONID` é reemitido a cada passo seguinte, até cair na página de
  sessão expirada no 106.

O `CookieJar` **aprende** essa rotação corretamente (`feed()` roda depois de toda
resposta, `har_reproducer/replay/replay_runner.py:118`) e a aplicaria via
`--cookie` (`CookieJarCurlOverride.apply`, que sobrescreve só a flag `--cookie`) — mas
o header `cookie:` corrigido no Achado 2 só **espelha o valor estático do extrator**
(congelado no `origin_step=0`) — ele nunca é tocado pelo jar. Quando o login **não**
rotaciona (sorte), o valor estático continua válido; quando rotaciona, o header `-H`
volta a mandar o `JSESSIONID` pré-login, e a sessão nova nunca chega ao servidor.

**Por que o CRUD não resolve isso:** testei diretamente com `curl` — um header
`-H 'Cookie: ...'` explícito **sempre** vence `--cookie`, em qualquer ordem, mesmo com
valor vazio. A única forma de dar prioridade real ao `--cookie` (que o jar mantém
atualizado) é remover a linha `-H 'cookie: ...'` inteira do curl. `bind`/`unbind`
(`ExtractorCurlBinder`, `har_reproducer/reproduction/extractor_curl_binder.py`)
operam só trocando o **conteúdo de um placeholder já existente** dentro de um token
via `str.replace()` — nunca removem, renomeiam ou fundem uma flag (`-H`) inteira com
seu argumento, e o texto literal `cookie: ` ao redor do placeholder fica fora do
alcance de qualquer ação do CRUD. Confirmado tentando várias abordagens (valor vazio,
sintaxe `-H 'cookie;'` do próprio curl) — `curl` sempre trata isso como header
explícito.

**Correção real, fora de escopo do CRUD:** um ajuste em
`har_reproducer/reproduction/curl_generator.py` (`_header_parts`) para não emitir o
header `Cookie` literal quando o mesmo request já tem cookies representados via
`--cookie` — não aplicado nesta verificação (é investigação, não spec de correção de
pipeline).

## Antes/depois (resumo)

| Aspecto | Antes desta verificação | Depois (CRUD aplicado) |
|---|---|---|
| `JSESSIONID` (escopo `/PlanodeSaude`) | reemitido ~12 vezes em 107 passos (sessão nunca gruda) | muda só 2 vezes (steps 0 e 14), igual ao HAR original — **quando o servidor não rotaciona no login** |
| Corpo da resposta do step 106 | página de "sessão expirada" (4076 bytes) mesmo com `status_code: 200` | idêntico byte a byte ao HAR original (19660 bytes, `Página principal prestador`) — no caso bom |
| `replay --mode all` | `Reproduction SUCCESSFUL` (falso positivo — só status code) | `Reproduction SUCCESSFUL` com conteúdo real verificado |
| `optimize --to 106` (critério padrão) | `Optimization SUCCESSFUL` com `[0, 106]` (falso positivo, não se sustenta isolado) | com critério reforçado, recusa corretamente quando o schedule não é suficiente |
| Extratores no workspace | 16 (3 incorretos: 1 header estático mal classificado + 2 paths estáticos frágeis) | 13, todos referenciados e validados via `extractor test`/`list` |
| Código de produção alterado | — | nenhum |

## O que a ferramenta de CRUD resolveu bem

- `extractor get`/`test` deram evidência objetiva e imediata (regex não bate nem na
  própria amostra de origem) sem precisar ler `.py` manualmente.
- `extractor unbind`+`delete` corrigiram 106 arquivos (104 curls + 2 extratores
  órfãos) sem gerar nenhum tráfego de descoberta novo, sem subir proxy/mitm.
- A saída em JSON (`{"ok": bool, ...}`) tornou trivial escriptar a correção em massa
  (loop sobre 104 curls) — a mesma correção via edição manual seria proibitivamente
  lenta.

## O que a ferramenta de CRUD não resolve (limite estrutural, não falta de tentativa)

- `bind`/`unbind` só trocam o conteúdo de um placeholder já existente; nunca removem,
  renomeiam ou fundem uma flag/header inteira com seu argumento — texto literal ao
  redor de um placeholder é imutável via CRUD.
- Nada no CRUD aponta proativamente "isso parece estático" ou "isso conflita com
  outra flag" — os Achados 1, 2 e 4 foram encontrados comparando conteúdo real
  (`grep`, diff byte a byte, teste isolado de `curl`) manualmente, não por sugestão
  da ferramenta.
- Correções que dependem de comportamento **em tempo de execução** (qual header tem
  precedência no `curl`, o que o `CookieJar` sabia no momento exato de uma requisição)
  não são visíveis nem editáveis via CRUD, que só enxerga arquivos já persistidos.

## Limites desta verificação

- O Achado 5 não foi corrigido — decisão consciente, pedida como investigação, não
  spec de correção de pipeline.
- A rotação de `JSESSIONID` no login parece ser uma decisão do servidor não
  totalmente determinística a partir do que observei (dois runs, mesmo workspace,
  resultados diferentes) — não investiguei mais a fundo o que a decide (headers,
  fingerprint, estado de um balanceador de carga).
- Nenhuma branch foi criada no repositório do projeto; todas as correções vivem no
  git local criado dentro do workspace de dados (`output-fix-verificacao/.git`), que
  não é versionado junto com `har-reproducer`.
