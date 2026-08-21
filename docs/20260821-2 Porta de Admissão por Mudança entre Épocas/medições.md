# Medições desta etapa

Todo número de `spec.md` está aqui, com o comando que o produz. Datas: 21/08/2026, depois
do merge dos itens 9 e 10. Os números da investigação original (`docs/20260820
Investigação da Porta de Admissão/medições.md`) que **não** dependiam de época de execução
(contagens sobre o `.har` puro: cobertura do JWT na época do HAR, chaves `(método,url)`
distintas, `If-None-Match`/`If-Modified-Since`) foram herdados sem remedir — eles não
mudam com os itens 9/10, que só tocam o pipeline de descoberta e a captura de execução.
Todo número que envolve `real_responses/` ou a porta foi **remedido** sobre workspaces
regravados com o código atual.

## Procedência dos workspaces

| workspace | HAR | entries | comando |
|---|---|---|---|
| `arquivos-har/ws_atual_pos_correcoes` | `arquivos-har/progressofit.har` | 324 | `uv run python -m har_reproducer.main run --har ../arquivos-har/progressofit.har --output ../arquivos-har/ws_atual_pos_correcoes --mode main --config config.json` |
| `arquivos-har/ws_anterior_pos_correcoes` | `../progressofit(antigo).har` | 238 | idem, com o HAR anterior |

Regravados em 21/08/2026 contra o servidor real da aplicação (`localhost:8090`,
`127.0.0.1:8080`), com o código de `master` **depois** do merge dos itens 9 e 10. Não estão
no repositório — são dados derivados, ~10–16 MB cada, e regeráveis com os comandos acima.
⚠️ O `run` não é determinístico entre execuções (laço TDD dos agentes usa LLM quando
`config.json` configura) — números que dependem de quantos extratores viram `LiteralAgent`
vs um agente real podem variar alguns pontos percentuais entre regeração.

## Scripts usados

Todos em `docs/20260820 Investigação da Porta de Admissão/medições/` (já commitados,
recebem caminhos por argumento): `descoberta.py` (descoberta + porta, parametrizável por
`--cache`, `--cobertura`, `--piso`, `--ubiquidade`, `--sem-vocabulario`, `--porta`),
`epocas.py` (legibilidade de corpo, estabilidade de header, requisição condicional),
`lcs.py` (módulo de apoio). E `docs/20260820 Extrator Literal Não Vira Âncora/medir_ancoras.py`.

## §1.1 — O problema, medido agora

```
$ WS=arquivos-har/ws_atual_pos_correcoes
$ grep -l "Authorization: Bearer eyJ" $WS/curls/*.curl.sh | wc -l        # 13
$ grep -l "Authorization: {{extractor" $WS/curls/*.curl.sh | wc -l       # 0
$ grep -h "comes from response of step 0153" $WS/curls/*.curl.sh | wc -l # 0
$ ls $WS/curls/*.curl.sh | wc -l                                         # 320
$ ls $WS/extractors/*.py | wc -l                                         # 17
$ grep -h "comes from response" $WS/curls/*.curl.sh | wc -l              # 254
```

`exp` do JWT do login, medido via `real_responses/res_0153.json`: `1802868074` →
13/02/2027, calculado com `base64.urlsafe_b64decode` do segundo segmento do JWT.

## §1.2 — Sem porta, 47 origens de fragmento, 1 é o JWT

```
$ uv run python descoberta.py --har arquivos-har/progressofit.har \
      --workspace arquivos-har/ws_atual_pos_correcoes --estrategia lcs
  (sem --porta: todos os fragmentos ficam "admitidos", nenhum filtrado por época)
  origens distintas: 15 inteiras + 47 fragmentos
```

## §1.4 — A política de cache não precisa mudar

```
$ for c in definitivo misses provisorio; do
    uv run python descoberta.py --har arquivos-har/progressofit.har \
        --workspace arquivos-har/ws_atual_pos_correcoes --cache $c --porta
  done
  definitivo:  1 extrator, 13 ocorrências
  misses:      1 extrator,  1 ocorrência    <- reproduz o bug da spec original
  provisorio:  1 extrator, 13 ocorrências

$ (idem sobre arquivos-har/ws_anterior_pos_correcoes)
  as três políticas dão 1 extrator / 1 ocorrência (o falso positivo de header:priority)
```

Confirmação de que `header:Origin` continua casando inteiro sob a política mais simples:

```python
rows = [(i,p,v,m) for i,p,v,m in h.rows if p == "header:Origin"]
Counter(m.kind for _,_,_,m in rows)   # {'inteiro': 204}
```

## §2 — A lacuna de `_exact_key`

```
$ uv run python - <<'EOF'
from har_reproducer.tracking.response_corpus import ResponseCorpus
d = ResponseCorpus("arquivos-har/ws_anterior_pos_correcoes/original_responses", 4)
e = ResponseCorpus("arquivos-har/ws_anterior_pos_correcoes/real_responses", 4)
print(d.response(76)["headers"]["priority"])   # 'u=0,i=?0'
print(e.response(76)["headers"].get("priority"))  # None
EOF
```

Request da época da execução (`real_requests/req_0076.json`) confirma que o header
`priority: u=0` **foi enviado** — é a resposta da CDN (`cdnjs.cloudflare.com`) que varia,
não o replay do request.

## §3.1 — Custo do passe de fragmento

```
$ uv run python descoberta.py --har arquivos-har/progressofit.har \
      --workspace arquivos-har/ws_atual_pos_correcoes --estrategia inteiro   # tempo=1,6s
$ uv run python descoberta.py --har arquivos-har/progressofit.har \
      --workspace arquivos-har/ws_atual_pos_correcoes --estrategia lcs --porta  # tempo=2,6s
```

## §3.2 — Ubiquidade do lado do fragmento não rejeita nada

```
$ uv run python descoberta.py ... --ubiquidade 0.2 --porta   # (padrão)
   0 rejeitado: ubiquidade     -- sobre ws_atual_pos_correcoes
$ (idem sobre ws_anterior_pos_correcoes: 0 rejeitado: ubiquidade)
```

## §3.3 — Piso mínimo, teto duro

```
$ uv run python epocas.py --workspace arquivos-har/ws_anterior_pos_correcoes
  etag            idêntico entre as épocas em 210/210
  last-modified   idêntico entre as épocas em 215/218
```

Comprimento dos valores de `ETag`/`Last-Modified` do HAR anterior, medido diretamente dos
headers (18–21 caracteres para `ETag`, 29 para `Last-Modified` — formato RFC 1123).

## §3.4/§3.5 — Descoberta completa, workspace anterior, pós item 10

```
$ uv run python descoberta.py --har "progressofit(antigo).har" \
      --workspace arquivos-har/ws_anterior_pos_correcoes --porta
  entries=238 steps pulados=[78, 90, 166] tempo=1,7s
   1887  ocorrências de candidato
    653  sem fragmento
    114  casou inteiro
    102  rejeitado: piso
     46  fragmento admitido
     34  rejeitado: vocabulário do fluxo
      5  rejeitado: ubiquidade
  origens distintas: 114 inteiras + 46 fragmentos
  veredito da porta: {'inteiro/estatico': 867, 'fragmento/estatico': 225, 'inteiro/mudou': 1}
  EXTRATORES: 1 — header:priority <- step 76
```

## §3.6 — Vocabulário condicional, verificado com script próprio

Reimplementei as duas versões (incondicional e condicional) sobre `ws_anterior_pos_correcoes`,
acumulando `first_seen[endereço] = índice do step`:

```
rejeições incondicional: 14
   ('http://localhost:8090', 34, 'url')  x3
   ('http://127.0.0.1:8080', 75, ...)    x11
rejeições condicional: 11
   ('http://127.0.0.1:8080', 75, ...)    x11
admitidos pela condicional que a incondicional vetava: 1 fragmento distinto (3 ocorrências)
   ('http://localhost:8090', 34, 'url')
```

3 ocorrências de `'http://localhost:8090'` (origem step 34, um bundle JS que informa a URL
da API antes de qualquer request usá-la) deixam de ser rejeitadas **antes** da porta
decidir — o que importa para diagnóstico via `[Static N]` (§3.11), não para o resultado
final, já que a porta as rejeitaria de qualquer forma por serem estáticas entre as épocas.

## §3.7 — Cobertura do JWT nas duas épocas

```python
har_jwt = "eyJ..." # 173 chars, res_0153.json/original_responses
exec_jwt = "eyJ..." # 173 chars, res_0153.json/real_responses
common_prefix_length = 123  # divergem a partir dos dígitos do exp
123 / 180  # 0.683... => 68%
```

## §3.8 — Requisição condicional, custo funcional contra o servidor real

```
$ uv run python epocas.py --workspace arquivos-har/ws_anterior_pos_correcoes \
      --har "progressofit(antigo).har"
  if-none-match        126
  if-modified-since    126
  respostas 304        124
```

Teste funcional contra o servidor: reenviei as 126 requisições condicionais com (a) o
`ETag` congelado do HAR — 126/126 devolveram 304; (b) o `ETag` com um caractere alterado —
126/126 devolveram 200.

Ubiquidade, `sum(1 for s in steps if valor in texts[s]) / len(steps)`, sobre
`ws_atual_pos_correcoes` (311 respostas com texto):

```
'keep-alive'                                 97,2%
'no-cache'                                     5,6%
ETag real ('W/"1663-19ed2a41011"')             0,31%
Last-Modified real ('Tue, 16 Jun 2026 ...')    4,67%
```

⚠️ Não medi o custo de um limiar mais agressivo que 0,5 (ex.: ≤0,05) neste workspace — o
`Last-Modified` de exemplo já está em 4,67%, perto do que um limiar assim cortaria, então a
afirmação de uma rodada de revisão anterior ("9 de 21 valores destruídos") não é reafirmada
aqui sem recontagem. Não é necessária: a spec adota 0,5, que passa longe dos dois.

## §5.9 — Custo total

2,6 s de descoberta contra 2m24s de `run` completo (medido no log da regeração de
`ws_atual_pos_correcoes`) — 1,8% do tempo total, e a maior parte dele é rede/subprocesso,
não a descoberta.

---

## §3.5/§3.8 — Revisão em cima da hora: R2 não era necessária, e a admissão por dois lados não tem limiar limpo

Estas duas medições foram feitas **depois** de escrever a primeira versão desta spec, e
derrubam duas das suas decisões. Registradas aqui antes de corrigir o documento.

### R2 (generalização de `_exact_key` para contenção) é desnecessária

O piso mínimo (§3.3), aplicado **também ao casamento inteiro**, já mata o único falso
positivo conhecido (`header:priority='u=0'`, 3 caracteres) sem precisar de nenhuma
generalização de container:

```
$ (script ad-hoc, mesma lógica de descoberta.py, com piso aplicado à passagem "inteiro")
piso_no_inteiro=True:  0 extratores
piso_no_inteiro=False: 1 extrator (header:priority <- 76)
```

E a generalização por **contenção** (em vez de igualdade) reabre exatamente a classe de
coincidência que a cobertura+piso fecharam do lado do fragmento — testada, ela admite
lixo novo do lado do header/cookie: no HAR atual, `header:Sec-Fetch-Site` (candidato de
**request**) casando por contenção dentro de um header de resposta do step 14; no HAR
anterior, mais 4 categorias de lixo (`header::authority`, `referer`, `sec-fetch-mode`,
`origin`) além do lixo já esperado.

**Decisão: §3.5 não generaliza `_exact_key`.** A porta volta a ser a comparação simples
"o texto casado aparece no corpo bruto da execução?" (blob completo, como hoje), com dois
vereditos — mudou / estático — mais indeterminado quando a resposta de execução está
vazia. `_exact_key` continua por igualdade, exatamente como hoje.

### Admissão por dois lados: testada com o `origin_container` que já existe (igualdade)

Sem a generalização por contenção, usando o `origin_container`/`origin_key` que
`OriginFinder` **já popula hoje** (via `_exact_key`, igualdade exata):

```
ws_atual, ubiquidade < 0.5:     2 extratores não-condicionais admitidos como lixo
   header:Origin <- 75            (reuso do valor: 266 ocorrências)
   header:Cache-Control <- 75     (reuso do valor: 2 ocorrências)
ws_anterior, ubiquidade < 0.5:  85 extratores = 84 condicionais + 1 lixo (header:origin <- 75)
```

Troquei ubiquidade por **reuso do valor entre candidatos** (quantas vezes o mesmo valor
aparece como candidato em todo o fluxo — é a medida mais direta de "isto é uma constante
compartilhada", diferente de ubiquidade, que mede presença no blob e por isso não separa
bem `Cache-Control` de `Last-Modified` quando os dois têm ubiquidade parecida):

```
reuso do valor 'http://127.0.0.1:8080' (Origin): 266    <- corretamente alto
reuso do valor do Cache-Control específico:        2    <- baixo, mas ainda é lixo
```

```
ws_atual, reuso <= 2:      2 extratores não-condicionais (Cache-Control, Connection)
ws_anterior, reuso <= 2:   75 extratores, TODOS condicionais/Authorization
                           (perde 9 dos 84 condicionais — provavelmente ETag/Last-Modified
                           compartilhado por assets idênticos servidos em rotas diferentes)
```

**Nem ubiquidade nem reuso, isolados, separam de forma limpa "constante de protocolo
compartilhada" de "validador genuíno de recurso" nesta escala de amostra (238–324
entries).** Qualquer limiar testado deixa passar 1–2 slots de lixo, ou corta alguns
validadores genuínos. Isso não é uma falha de calibração — é uma medição real do limite do
método com os dados disponíveis.

**Consequência para a decisão de escopo.** O regime pós item 9 muda o custo da omissão:
hoje, **sem porta nenhuma**, um candidato de conditional-header com origem encontrada já
recebe um extrator real (`HeaderAgent`, por igualdade exata) — é assim que os 84
extratores do HAR anterior existem hoje. Se esta etapa entrega a porta **sem** nenhuma
condição de dois lados, ela **regride** essa classe de "funciona hoje" para "literal
congelado" — não é "continua quebrado", é "quebra algo que já funcionava". O custo dessa
regressão, medido antes (`docs/20260820 .../revisões-adversariais.md` §5.2): zero hoje,
+0,30 requisição por replay no primeiro deploy, e divergência de status em 126 dos 235
curls daquele HAR quando o `ETag` mudar de verdade.
