# Medições da investigação

Versão **corrigida**. A original tinha erros que as revisões adversariais acharam; cada
correção está marcada com ⚠️ **CORRIGIDO** e diz o que era antes. O detalhe de cada revisão
está em `revisões-adversariais.md`.

Convenção de atribuição: **[eu]** = medido e reverificado por mim; **[rev]** = medido por uma
das revisões e não reverificado — tratar como forte, não como confirmado.

## Procedência

| item | valor |
|---|---|
| gravação atual | `arquivos-har/progressofit.har` — 5.232.351 bytes, 17/08/2026 21:14, **324 entries** |
| gravação anterior | `progressofit(antigo).har` — 2.445.615 bytes, 30/06/2026, **238 entries** |
| workspace de referência | `arquivos-har/ws_20260817_main` (persistente) |
| workspaces auxiliares | gerados em `/tmp` contra o servidor real; **não** no repositório (10 MB e 16 MB). Comando de regeração no `README.md` desta pasta |
| código | `master` em `07028f4` (antes de qualquer etapa desta investigação) |
| datas | 20/08/2026 |
| scripts | `medições/` nesta pasta — recebem caminhos por argumento |

⚠️ **Uma gravação não generaliza, e este documento é a prova.** Quase todo critério que
zerava falsos positivos na gravação atual falhou na anterior. Onde uma conclusão vale só para
uma gravação, está dito.

⚠️ **O `run` não é determinístico.** [eu] Duas execuções do mesmo HAR deram conjuntos
diferentes de extrator — `{HeaderAgent 4, CSSAgent 3, RegexAgent 4, LiteralAgent 4,
LiteralFallbackAgent 2}` e `{HeaderAgent 4, RegexAgent 4, LiteralAgent 4,
LiteralFallbackAgent 5}` — porque o laço TDD dos agentes usa LLM. Três valores que uma
execução aprendeu a extrair, a outra congelou. Números que dependem de quantos extratores são
literais variam alguns pontos percentuais entre execuções.

---

## Como reproduzir

Da raiz do projeto, com `D='docs/20260820 Investigação da Porta de Admissão/medições'` e
`W=../arquivos-har/ws_20260817_main`, `H=../arquivos-har/progressofit.har`:

| medição | comando |
|---|---|
| M1 | `uv run python "$D/descoberta.py" --har $H --workspace $W --estrategia inteiro` |
| M4 | idem com `--estrategia lcs --porta` e `--estrategia ancora --porta` |
| M6 | idem com `--porta --cache definitivo` \| `--cache misses` \| `--cache provisorio` |
| M7 | `--sem-vocabulario --piso 0 --ubiquidade 1.0` combinado com `--cache` |
| M8, M9 | ablação por `--piso`, `--ubiquidade`, `--sem-vocabulario`, `--cobertura` |
| M12, M14, M16 | `uv run python "$D/epocas.py" --workspace $W --har $H` |
| M13 | `uv run python "docs/20260820 Extrator Literal Não Vira Âncora/medir_ancoras.py" $W` |

Saída verificada da linha de base (M1), para conferir que o arnês está fiel:

```
entries=324 steps pulados=[81, 155, 240, 251] tempo=1,6s
   1256  ocorrências de candidato
     15  casou inteiro
  origens distintas: 15 inteiras + 0 fragmentos
  ocorrências que receberam extrator: 254      <- as 254 linhas de dependência do workspace
```

⚠️ O arnês devolve **16** slots onde o workspace tem 17 extratores: ele não reimplementa o
fork de slot do `CandidateResolver` (`_find_slot`/`_fork_token_id`), que desempata dois
candidatos que caem no mesmo `(path, origin_step)`. Diferença conhecida e irrelevante para
as conclusões — todas elas são sobre ordens de grandeza, não sobre o 17º slot.

⚠️ `descoberta.py` **não** implementa a busca da peça restante nem o registro das categorias
informativas no `.curl.sh`: mede a descoberta e a porta, que é o que a investigação variou.

---

## M1 — Universo de candidatos [eu]

`medições/descoberta.py`, estratégia `inteiro`, sobre a gravação atual:

```
entries ......................................... 324
steps pulados (esquema não http/https) .......... 4  -> 81, 155, 240, 251
ocorrências de candidato ........................ 1256
valores distintos ............................... 122
pares (path, value) distintos ................... 157
valores com origem por valor inteiro ............ 15
valores sem origem .............................. 107
ocorrências sem origem .......................... 1002 / 1256
tempo da descoberta ............................. 1,84 s
```

Estado do workspace de referência:

```
320 curls | 17 extratores | 254 linhas de dependência
âncoras: 0, 1, 4, 14, 23, 37, 75, 154   |  219/320 curls arrastam pelo menos uma
```

15 valores distintos e 17 extratores porque o slot é derivado de `(path, origin_step)`.

## M2 — Os 15 casamentos de valor inteiro são todos estáticos [eu]

Origem em `original_responses/`, mesmo texto procurado em `real_responses/` no mesmo step:

| ocorrências | origem | valor |
|---:|---:|---|
| 266 | 75 | `http://127.0.0.1:8080` |
| 16 | 23 | `application/json` |
| 8 | 37 | URL de CDN (font-awesome) |
| 4 | 0 | URL de CDN (bootstrap) |
| 4 | 1 | URL de CDN (google fonts, com query) |
| 4 | 14 | URL de CDN (gstatic) |
| 4 | 1 | `https://fonts.googleapis.com/` |
| 2 | 154 | `https://apifreellm.com/apifree.min.js` |
| 2 | 75 | `no-cache` |
| 1 | 154 | `https://cdn.jsdelivr.net/npm/chart.js` |
| 1 | 0 | `keep-alive` |
| 1 | 75 | `127.0.0.1:8080` |
| 1 | 0 | `document` |
| 1 | 14 | `same-origin` |
| 1 | 4 | `?1` |

**15 de 15 idênticos entre as épocas.** Inspeção manual confirma que rejeitá-los é correto.

Onde casaram: `'?1'` dentro de bytes binários de um corpo; `'same-origin'` dentro de
`cross-origin-opener-policy: same-origin-allow-popups`; `'application/json'` dentro de código
JS; `'document'` dentro de `document.getElementsByTagName(...)`; `'127.0.0.1:8080'` dentro de
`access-control-allow-origin`. **Casar o valor inteiro já é busca por substring num blob** —
`searchable_text` concatena headers, cookies, `redirect_url` e o corpo cru.

## M3 — O `Authorization` [eu]

```
13 curls com Bearer literal: steps 224, 226-229, 231-233, 236, 309, 311, 312, 314
login: step 153, POST /auth/login, corpo {"token":"eyJ…"} (185 bytes) gravado
find('Bearer eyJ…', 0, 224) -> None        find('eyJ…', 0, 224) -> step 153
JWT do HAR e da execução: 173 chars cada, 123 de prefixo comum (divergem no exp)
valor do request 'Bearer <jwt>': 180 chars
  fragmento na época do HAR ....... 173/180 = 96%
  fragmento na época da execução .. 123/180 = 68%
```

⚠️ **CORRIGIDO** — a revisão reportou 116/180 = 64% para a época da execução. O número certo
é 123/180 = 68%, e ele **reforça** o ponto: 68% passa por qualquer limiar de cobertura
plausível, então a cobertura não protege desse erro; só a escolha da época protege.

⚠️ **CORRIGIDO** — a versão original afirmava que `replay --mode list [23,75,153,224]` dá
`Step 224 → 403`. **Dá 200.** O JWT congelado ainda autentica (`exp` 2027-02-13):
`GET /auth/check` com ele devolve 200. A frase foi herdada da spec de 17/08 sem
reverificação. O fluxo não está quebrado; ele quebra quando o token expirar.

## M4 — As três estratégias de casamento parcial convergem [eu]

`medições/descoberta.py`, gravação atual, porta de época ligada:

| estratégia | fragmentos aceitos | extratores | tempo |
|---|---:|---:|---:|
| só valor inteiro (hoje) | — | 0 (não acha o JWT) | 1,8 s |
| maior substring + restante obrigatoriamente literal | 24 | **1** | 14,3 s |
| âncora fixa `valor[16:32]`, piso 32 | 2 | **1** | 2,2 s |
| maior substring sem piso, sem regra do restante | 108 | **1** | 5,2 s |

Quem filtra é a porta, não a regra do restante: sem a porta, ela deixa passar 20 valores,
19 coincidências (`*/*` cobre como `'*/'`+`'*'`, `navigate` como `'navigat'`+`'e'`).

## M5 — A regra do "restante literal" é frágil [eu]

`'Bearer '` só tem origem porque o JavaScript do cliente é servido como resposta e contém
`` headers['Authorization'] = `Bearer ${token}` `` (steps 23, 100, 174). Contrafactual:

```
'Bearer ' <jwt> -> origem no step 23      'bearer ' <jwt> -> SEM ORIGEM, token descartado
'JWT '    <jwt> -> SEM ORIGEM             'Bearer: '<jwt> -> SEM ORIGEM
```

Como veto, a regra condicionaria a recuperação do único token dinâmico a uma coincidência de
bundle. Nos 122 valores do fluxo, **nenhuma peça restante muda entre as épocas** — o caso
multi-peça que a composição resolveria não ocorre.

## M6 — Preempção temporal e a política de cache [eu]

A busca é causal: só respostas de steps anteriores. Rastro de
`header:Origin = 'http://127.0.0.1:8080'` (266 ocorrências):

```
1ª ocorrência: step 6 -> janela [0, 6), 6 respostas, valor inteiro AUSENTE
maior substring na janela: 'http://' (7 chars), step 1
valor inteiro só existe a partir do step 75 (access-control-allow-origin)
```

⚠️ **CORRIGIDO / o achado decisivo.** A spec descartada respondia a isso gravando
`_origin_misses` no acerto de fragmento, o que **exclui o step do login da janela seguinte** e
entrega o extrator do `Authorization` a 1 de 13 curls. Contando ocorrências:

```
grava _origin_misses no acerto de fragmento .....  8,5 s   Authorization  1/13
não grava (refaz o LCS toda ocorrência) ......... 29,4 s   Authorization 13/13
cache provisório + repasse do passe barato ......  5,6 s   Authorization 13/13
cache definitivo (comportamento de hoje) ........  2,8 s   Authorization 13/13
```

As duas últimas dão resultado **idêntico** (1 extrator, 13 linhas): a maquinaria de promoção
custa +23% e a única promoção em 3.143 ocorrências é lixo. **A correção é uma linha:** não
gravar `_origin_misses` quando o fragmento é admitido. Com os critérios corrigidos o caso do
`Origin` se resolve sozinho — `'http://'` tem cobertura 33% e morre na poda.

## M7 — Matriz cache × piso, sem critérios de admissão [eu]

| cache positivo | piso | tempo | origens: inteiras + fragmentos | extratores |
|---|---|---:|---|---:|
| guarda fragmento | — | 5,3 s | 14 + 92 | 1 |
| guarda fragmento | 32 | 2,0 s | 15 + 2 | 1 |
| só valor inteiro (janela estreitada) | — | 15,5 s | 15 + **923** | **19** |
| só valor inteiro (janela estreitada) | 32 | 1,9 s | 15 + 5 | 1 |
| só valor inteiro (janela do zero) | — | 67,5 s | 15 + 93 | 1 |
| só valor inteiro (janela do zero) | 32 | 3,3 s | 15 + 5 | 1 |

Guardar fragmento **esconde** o problema em vez de evitá-lo; parar de guardar sem filtro
explode para 923 origens e 19 extratores.

## M8 — Os falsos positivos são vocabulário de HTTP [eu]

Critério objetivo, sem lista de palavras: **ubiquidade** = fração das 321 respostas do corpus
que contêm o fragmento. Cenário "só valor inteiro, sem piso":

| | total | ubíquo (≥50%) | comum (10–50%) | raro (<10%) |
|---|---:|---:|---:|---:|
| origens de fragmento | 923 | 268 (29%) | 228 (25%) | 427 (46%) |
| viram extrator | 19 | **16 (84%)** | 0 | 3 |

Tamanhos: das 923, 533 têm ≤8 chars; dos 19 extratores, 16 têm ≤8. Reincidentes:
`'/'` 320/321 (182 origens), `'*/'` 21% (57), `'ht'` 63% (33), `'control'` 99% (15),
`'.js'` 57% (8), `'age'` 99% (4).

`'control'` vem do nome do header `cache-control` e "muda entre as épocas" porque em alguns
steps a resposta do HAR o carrega e a da execução não — verificado no step 24: mesmo status,
mesmo tamanho, header presente numa época e ausente na outra.

⚠️ **CORRIGIDO** — a versão original fixava `MAX_UBIQUITY = 0.5`, que rejeita **zero**
fragmentos. Com **0,20** rejeita 57 (a classe `'*/'` do valor `'*/*'`, cobertura 67%, que
passava nos três critérios) sem mudar o resultado. E o critério é definido sobre um corpus que
num `run` real está incompleto: `original_responses/` só tem os steps já processados, então o
denominador no step 10 é 10. Tem que ser a janela causal, sem memoização entre steps —
medido, dá o mesmo resultado final (6,6 s contra 5,7 s, 63 origens contra 64).

## M9 — Comparação de filtros de admissão [eu]

Sobre o cenário de M8 (923 origens, 19 extratores, 18 falsos positivos):

| filtro | pré-porta | extratores | FP |
|---|---:|---:|---:|
| (sem filtro) | 923 | 19 | 18 |
| piso 4 / 8 / 16 | 537 / 418 / 328 | 18 / 3 / 3 | 17 / 2 / 2 |
| piso 24 / 32 | 248 / 153 | 1 / 1 | 0 / 0 |
| ubiquidade < 50% / < 10% / < 2% | 655 / 427 / 212 | 3 / 3 / 1 | 2 / 2 / 0 |
| cobertura ≥ 50% / ≥ 80% | 221 / 13 | 3 / 1 | 2 / 0 |
| **cobertura ≥ 50% + não-host** | **200** | **1** | **0** |
| **cobertura ≥ 50% + ubiq < 50% + não-host** | **200** | **1** | **0** |

⚠️ **CORRIGIDO** — o script original (`exp11_filters.py`) implementava a regra de host
**bidirecional** (`frag in host or host in frag`), que é a direção que o desenho declara
errada, e não continha as quatro linhas de combinação que a tabela apresenta. Reproduzi as
combinações com a regra unidirecional: os números se sustentam, a procedência do script
original não. `medições/descoberta.py` implementa a regra unidirecional.

⚠️ **Vários filtros zeram a coluna de FP nesta gravação.** Com 18 falsos positivos num fluxo
só, esta tabela **não distingue** entre eles — e M11 mostra que nenhum deles sobrevive à
segunda gravação. Serve como piso de exigência, não como escolha.

## M10 — O que o piso custaria [eu + rev]

[eu] O piso vale só para o passe de fragmento: valor curto que casa **inteiro** continua
virando extrator. O que ele perde é valor curto cuja origem só aparece parcialmente —
`'csrf=a1b2c3d4'` (cobertura 62%) e `'sid=9f3a'` (50%) seriam rejeitados por piso 32. Nenhum
ocorre nas duas gravações; é raciocínio sobre a classe.

[rev] Medido na gravação anterior, os casamentos **inteiros legítimos** têm comprimento 18–21
(`ETag`, 63 valores) e 29 (`Last-Modified`, 21 valores). Logo **piso ≥ 18 destrói a classe de
requisição condicional**; teto duro é 17. Piso 4 é grátis nas duas gravações e mata 1 dos 3
falsos positivos da anterior.

⚠️ Nenhum critério cobre "token curto dentro de valor longo"
(`http://host/api/items/12345?x=1`, cobertura 16%). É limitação da granularidade do
candidato, que o `BaselineDiff` entrega como URL inteira.

## M11 — A segunda gravação derruba a conclusão [rev]

Desenho corrigido (fragmento + cobertura 50% + piso 4 + vocabulário + porta), medido nas duas:

| | gravação atual | gravação anterior |
|---|---|---|
| hoje | 17 extratores, 254 linhas, 8 âncoras | 117 extratores, 865 linhas, 69 âncoras |
| desenho corrigido | **1 extrator** (`Authorization`←153) | **3 extratores, 3 falsos positivos** |
| `Authorization` recuperado | sim | **não** (0/9) |

Os 3 da gravação anterior: `url`←14 (inteiro, 85 chars), `header::path`←14 (inteiro, 60) e
`header:priority`←76 (inteiro, 3 chars, `'u=0'`). **Precisão 0 de 3, recall 0.** Dois motivos
distintos: os falsos positivos vêm de M12, e o `Authorization` é inalcançável porque o login
daquela gravação (step 154) tem corpo de 0 bytes.

## M12 — `real_responses/` guarda corpo comprimido como mojibake [eu]

A causa dos falsos positivos de M11:

```
gravação anterior — respostas legíveis numa época e ilegíveis na outra: 4
  step  13 enc=br    HAR  80821 ch (0% FFFD) | EXEC  23259 ch (43% FFFD)
  step  14 enc=gzip  HAR   1272 ch (0% FFFD) | EXEC    430 ch (39% FFFD)
  step  76 enc=br    HAR 102025 ch (0% FFFD) | EXEC  17750 ch (44% FFFD)
  step 159 enc=br    HAR 208522 ch (0% FFFD) | EXEC  67879 ch (44% FFFD)

gravação atual — 0 inversões (26 de 311 são ilegíveis nas DUAS épocas: binário legítimo)
```

Steps 13, 14, 76 e 159 são exatamente as origens dos falsos positivos. [rev] Prova cruzada: o
mesmo recurso e o mesmo valor dão "estático" na gravação atual (corpo decodifica) e "mudou" na
anterior (não decodifica).

⚠️ **CORRIGIDO** — a primeira revisão atribuiu isso a bundles de CDN encolhendo entre as
épocas. Não encolhem: o corpo da execução foi persistido ainda comprimido. É defeito de
persistência do projeto (item 10 do backlog) e pré-requisito da porta.

## M13 — Extrator literal congelado não deveria virar âncora [eu]

O achado de maior efeito, e independente de todo o resto. `medições/../medir_ancoras.py` (na
pasta da etapa em andamento):

| workspace | linhas de dependência | → recalculáveis | âncoras | curls com âncora | `smart` médio |
|---|---:|---:|---|---|---|
| `ws_20260817_main` | 254 | **11** (96% congelados) | 8 → 5 | 219/320 → 7/320 | 2,38 → **1,03** |
| outra execução do mesmo HAR | 254 | **8** (97%) | 8 → 4 | 219/320 → 4/320 | 2,38 → **1,02** |
| gravação anterior | 865 | **93** (89%) | 69 → 65 | 232/235 → 68/235 | 6,48 → **1,32** |

⚠️ **CORRIGIDO** — a versão original atribuía a redução de âncoras à porta de admissão. **89%
a 96% dela vem daqui**, a custo de zero capacidade. Virou o item 9 do backlog.

## M14 — Requisição condicional [eu + rev]

[eu] `MEDIDO NAS DUAS`: a gravação atual tem **0** `If-None-Match` e 0 `If-Modified-Since`; a
anterior tem **126 e 126**, com 124 respostas 304.

⚠️ **CORRIGIDO** — a versão original concluía que "a classe de risco está vazia". Está vazia
**nesta** gravação; é 53,6% da anterior.

[rev] Com a porta, 84 tokens (63 `If-None-Match` + 21 `If-Modified-Since`) viram literal
congelado, afetando 126 curls. Custo funcional medido contra o servidor:

```
com o ETag congelado do HAR (o que a porta produz): {304: 126}  divergências: 0
com o ETag adulterado (simula deploy)             : {200: 126}
```

Hoje o custo é zero; no primeiro deploy, 126 curls divergem. Admissão por dois lados
(`mudou entre as épocas` **ou** `origem estruturada`) recupera 100% da classe por **+0,30
requisição por replay**.

## M15 — Contraexemplo do CORS aberto [rev]

Patchando a época da execução para `Access-Control-Allow-Origin: *`, desenho corrigido
inalterado:

```
gravação atual, normal      : 1 extrator,  13 linhas, 1 âncora
gravação atual, com ACAO: * : 5 extratores, 255 linhas, 2 âncoras
        204x header:Origin  <-75 inteiro   len=21     30x header:Referer <-75 fragmento
```

`Origin: *` em 204 lugares e `Referer: */dashboard/`. Piso não pega (21 chars), origem
estruturada aceita (valor exato de header), razão de corpo aceita (0 bytes), `TokenLocation`
aceita. O único filtro que segura é o veto de endereço aplicado ao **texto casado**, não só a
fragmento. [eu] O risco é real no código de hoje: o token do `Origin` é referenciado **576
vezes** nos 320 curls.

## M16 — Granularidade temporal do JWT [eu]

```
A) três logins imediatos (mesmo segundo)     -> 2 tokens distintos de 3
   exp=1802816915 sig=y7FmHpnl3FjOFo  (×2, byte a byte idêntico)
   exp=1802816916 sig=vfwBPazJyrEFQZ
B) três logins separados por mais de 1 s     -> 3 tokens distintos de 3
```

⚠️ **CORRIGIDO** — a spec de 17/08 afirmava "três logins seguidos devolvem três tokens
diferentes". O JWT é função de `(payload, exp)` com `exp` em segundos: dois logins no mesmo
segundo devolvem o token idêntico.

Não ameaça a porta (as épocas estão separadas por dias), mas corrige o que se pode afirmar:
**"dinâmico" não é propriedade do valor, é a relação entre a taxa de mudança dele e o
intervalo entre as duas observações.** No outro extremo estão `ETag` (idêntico em 285/285) e
`Last-Modified` (292/296), que mudam no deploy.

## M17 — Contexto para o alinhamento de duas gravações [eu]

Se algum dia o `--mode dry` for alimentado por um segundo HAR: alinhar não é lookup por
chave. Da gravação atual, 324 entries para **110 chaves `(método, url)` distintas**, 75
repetidas, cobrindo **289 entries (89%)**. `GET /src/app.js` aparece 4 vezes. É alinhamento de
sequência.

## M18 — Impacto nos cenários golden [eu]

Para a etapa do item 9: o fixture `synthetic_flow.har` produz **uma** linha de dependência
congelada (`req_0006.curl.sh`, token literal com origem no step 5), e os três cenários de
smart têm alvo 9, 4 e 9 — nenhum passa pelo step 6. Os 27 cenários passam byte-idênticos, e
**nenhum exercita o defeito**. A cobertura nova é o coração daquela etapa.

[rev] Para a etapa do item 11: tornar o valor `4242` estático mata o propósito de 6 cenários
(`replay_smart_*`, `replay_list_out_of_order`, `replay_ref_fallback`, 2 do `optimize`),
incluindo a única cobertura de `_fallback_to_captured`. E `run_dry_default` já cobre os cinco
agentes, sem ser tocado pela porta — a premissa de que a rede de caracterização morre é falsa.
