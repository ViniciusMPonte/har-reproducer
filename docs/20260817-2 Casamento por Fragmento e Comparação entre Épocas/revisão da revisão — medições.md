# Revisão da revisão — o que se sustenta, medido sobre a gravação atual

> Tudo aqui foi medido em 19/08/2026 sobre `arquivos-har/progressofit.har` (330 entries,
> 4.384.702 bytes, gravado 19/08 18:56) e sobre `arquivos-har/output` (o workspace atual,
> 326 curls, 118 extratores). Nada foi herdado da spec: o HAR dela (324 entries, 17
> extratores) não existe mais.
>
> As simulações usam as classes reais do projeto (`BaselineDiff`, `ResponseCorpus`,
> `ValueVariants`, semântica de cache do `CandidateResolver`). O baseline reproduz o
> workspace em disco: 118 slots contra 118 arquivos `.meta.json`, 1276 arestas contra
> 1252 linhas de dependência (a diferença são os 4 steps `ws://` pulados, que a simulação
> não pula).

## Sumário

1. A porta de admissão (só vira extrator o que muda entre épocas) é a única parte que
   entrega o objetivo declarado: **7 steps → 1 step** no schedule do alvo autenticado.
2. O casamento por fragmento, em qualquer variante, é **irrelevante para esse número** e
   não resolve o `Authorization` nesta gravação — porque o HAR **não gravou o corpo da
   resposta do login**.
3. O `FragmentMatcher` da spec (§3.1) está **errado**: a prova da âncora única é falsa.
   Ele acha 1 fragmento onde o algoritmo correto acha 50.
4. A regra do usuário ("o resto tem que ser buscado como literal") é a parte mais forte
   da proposta: sozinha, ela corta os casamentos por fragmento de **170 para 33 (–81%)** e
   é ela, não o piso, que separa sinal de ruído. Ela também **protege** contra o único caso
   realmente perigoso (V4), onde a spec falha.
   Duas ressalvas medidas: com o piso 32 da spec ela vira restritiva demais (rejeita 59 de
   63), e sem piso nenhum a busca custa 44 s contra 2,5 s. Piso **8** é o ponto ótimo.
5. Transformar o afixo em extrator parcial **aumenta** o número de steps do schedule —
   o oposto do objetivo.

---

## 1. O fato que muda o diagnóstico: o HAR atual não gravou o corpo do login

```
entry 154  POST 200 application/json  http://localhost:8090/auth/login   content.text = None
```

`original_responses/res_0154.json` tem `body: ""`. O JWT fresco só existe em
`real_responses/res_0154.json`, capturado pelo proxy durante o `run main`.

10 das 330 entries estão sem corpo (login, dois `apifree.min.js`, dois woff2 do
gstatic, dois 404 do backend, um 301, dois woff2 do cdnjs).

**Consequência direta:** com a decisão §3.3 da spec (descoberta sempre em
`original_responses`), o `Authorization` é **indescobrível** nesta gravação — por valor
inteiro, por fragmento da spec, por fragmento corrigido ou por LCS. Medido:

| corpus de descoberta | valor inteiro | fragmento (spec) | LCS (usuário) |
|---|---|---|---|
| `original_responses` | None | None | `'Bearer '` (7 ch) → afixo (o JWT) sem origem → descartado |
| `real_responses` | None | **step 154, 123 ch** | step 154, 123 ch → afixo `g1OTV9.BzJI…` sem origem → **descartado** |

A linha de baixo é a armadilha V4 da própria spec, e ela mostra o único ponto em que a
ideia do usuário ganha da spec — ver §4.

## 2. A porta de admissão: entrega o objetivo, e o custo é maior do que a spec mediu

Simulação sobre os 2676 candidatos (240 valores distintos) do fluxo:

| | arestas | extratores | steps de origem | schedule do alvo 224 |
|---|---|---|---|---|
| hoje | 1276 | 118 | 70 | **7 steps** |
| com a porta | **5** | **2** | 1 | **1 step** |

A porta barra 1271 arestas. **380 delas** (30%) são requisição condicional
(`If-None-Match` 190 + `If-Modified-Since` 190). A spec declarou esse custo, mas o mediu
num HAR que tinha **zero** `If-None-Match`; nesta gravação é o terceiro maior grupo.

Confirmado o motivo: `ETag` é idêntico entre as épocas em **283/283** steps e
`Last-Modified` em **290/294**.

⚠️ **As 2 arestas que sobrevivem à porta são falso-positivo.** Ambas apontam para o step
14 (`fonts.googleapis.com/css2?family=Fredoka`). O corpo difere entre as épocas
(1272 bytes no HAR, 430 na execução) porque o Google Fonts faz *content negotiation* por
`User-Agent` — o curl recebe uma variante sem `woff2`. Não há token dinâmico ali; o
extrator vai falhar no replay e cair no `captured_value`.

**Ou seja: aplicada sozinha sobre esta gravação, a spec inteira produz 0 extratores
corretos e 2 espúrios.** O problema não é a regra — é que a evidência que ela precisa
(o corpo do login) não está no HAR.

## 3. O `FragmentMatcher` da spec está errado

A spec §3.1 usa **uma** âncora, `valor[16:32]`, e justifica assim:

> "O bloco `valor[ANCHOR:2*ANCHOR]` está contido em qualquer fragmento que comece em
> `a <= ANCHOR` e termine em `b >= 2*ANCHOR` — e todo fragmento de tamanho mínimo
> satisfaz a segunda condição."

Satisfaz a segunda, sim. A primeira (`a <= ANCHOR`) **não é implicada por nada** e a prova
a assume em silêncio. Um fragmento que comece depois do caractere 16 é invisível.

Contraexemplo mínimo:

```
valor = "PREFIXO-QUE-SO-EXISTE-NO-REQUEST-SUFIXO-COMPARTILHADO-DE-40-CHARS-XXXXXX"
texto = "lixo lixo SUFIXO-COMPARTILHADO-DE-40-CHARS-XXXXXX mais lixo"
fragmento comum real: 39 caracteres
âncora valor[16:32] = 'XISTE-NO-REQUEST' → ausente do texto → FragmentMatcher devolve None
```

E isso não é teórico — é a classe **dominante** neste fluxo, porque URL começa com
`http://127.0.0.1:8080` (21 caracteres):

| algoritmo | fragmentos achados | tempo |
|---|---|---|
| âncora única (spec §3.1) | **1** | 0,08 s |
| âncoras em todos os blocos alinhados de 16 | **50** | 0,27 s |
| LCS exata por autômato de sufixos, piso 32 | **50** | 35,40 s |

49 falsos negativos, todos com o fragmento começando no índice 21, 25 ou 30:

```
valor[66] 'http://127.0.0.1:8080/src/assets/images/carrossel/carrossel-1.jpeg'
          fragmento len=45 @step 0: '/src/assets/images/carrossel/carrossel-1.jpeg' (índice 21)
valor[96] 'http://127.0.0.1:8080/src/view/component/goal-training-creation/…'
          fragmento len=66 @step 27: '/component/goal-training-creation/GoalTraining…' (índice 30)
```

**Correção:** sementes em todos os blocos alinhados `valor[k*16:(k+1)*16]`. Aí a prova
fecha de verdade — qualquer janela de tamanho ≥ 2·ANCHOR contém um bloco alinhado inteiro.
É a proposta que a "revisão adversarial" da spec (item 5 da §7) descartou por engano.

**E ela é exatamente equivalente à LCS do usuário:** 0 divergências em 133 valores,
**131× mais rápida**. Esse é o resultado de engenharia mais útil daqui — a semântica que
o usuário quer ("a maior substring comum") não precisa de autômato de sufixos, desde que
exista um piso de tamanho. O piso é o que compra a velocidade.

## 4. A estratégia de extratores parciais do usuário

Cinco variantes, mesmo fluxo, descoberta em `original_responses`, porta de época aplicada
peça a peça:

| variante | fragmentos | arestas | extratores | steps de origem | schedule 224 / 230 | tempo |
|---|---|---|---|---|---|---|
| **A** hoje (valor inteiro) | — | 1276 | 118 | 70 | 7 / 7 | 2,2 s |
| **B** spec como escrita | 1 | 1280 | 119 | 70 | 7 / 7 | 0,6 s |
| **B+** spec corrigida (multi-âncora) | 63 | 1515 | 175 | 75 | 7 / 12 | 0,8 s |
| **C** usuário literal (LCS sem piso, afixo vira extrator) | 45 | **3390** | 184 | 75 | não medido | **70 s** |
| **D** usuário com piso 32 (afixo vira extrator) | 5 | 1298 | 126 | 75 | 7 / 10 | 1,2 s |
| **E** híbrido: piso 32, afixo só valida e fica literal | 5 | 1287 | 123 | 74 | 7 / 10 | 1,2 s |

Com a porta de época ligada:

| variante | arestas | extratores | steps de origem | schedule 224 / 230 |
|---|---|---|---|---|
| A | 5 | 2 | 1 | 1 / 1 |
| B | 5 | 2 | 1 | 1 / 1 |
| B+ | 16 | 7 | 5 | 1 / 2 |
| C | 57 | 8 | 3 | — |
| D | 13 | 6 | 5 | 1 / 2 |
| E | 9 | 5 | 4 | 1 / 2 |

### 4.1 Sem piso: a regra do afixo é que faz o filtro, não o piso

⚠️ **Correção de uma afirmação anterior deste documento.** A primeira redação dizia
"o piso não é opcional". Medido por valor distinto, isso está errado: quem filtra é a
**regra do afixo**, e ela filtra bem.

Sobre os 171 valores distintos que não têm origem por valor inteiro:

| | fragmentos achados | admitidos pela regra do afixo | tempo |
|---|---|---|---|
| LCS exata, **sem piso** (a proposta) | 170 | **33** | 44,3 s |
| multi-semente, piso 4 | 155 | 24 | 11,3 s |
| multi-semente, piso 6 | 150 | 24 | 4,0 s |
| **multi-semente, piso 8** | 142 | **23** | **2,5 s** |
| multi-semente, piso 16 | 132 | 23 | 1,3 s |
| multi-semente, piso 32 (a spec) | 63 | 4 | 0,4 s |

A LCS sozinha admitiria 170 — ruído. A regra do afixo derruba para **33 (–81%)**, e é
isso que torna o "sem piso" viável. O piso 32 da spec é que é o número errado: mata 29
dos 33.

**Os 33 admitidos, por qualidade:**

- **23 são decomposições legítimas de URL** em host + caminho, ambos com origem real:
  ```
  'http://localhost:8090/api/user'          = 'http://localhost:8090'@34 + '/api/user'@18
  'http://127.0.0.1:8080/dashboard/'        = 'http://127.0.0.1:8080'@75 + '/dashboard/'@32
  'http://127.0.0.1:8080/src/assets/images/logotipo.svg'
                    = 'http://127.0.0.1:8080' + '/src/assets/images/logotipo.svg'@53
  ```
  O piso 32 da spec destrói todas as 23 — as peças têm 7 a 31 caracteres.

- **10 são estilhaço de valor de baixa entropia**, com peça de 1 a 3 caracteres:
  ```
  header::method        'GET'       = 'G'@0  + 'ET'@0
  header:Sec-Fetch-Mode 'cors'      = 'c'@0  + 'ors'@1
  header:sec-fetch-mode 'no-cors'   = 'no'@0 + '-co'@1 + 'rs'@0
  header:Connection     'Upgrade'   = 'Up'@11 + 'grad'@1 + 'e'@0
  header:Upgrade        'websocket' = 'web'@1 + 'socket'@0
  header:priority       'u=1'       = 'u'@0  + '=1'@0
  header:Accept         '*/*'       = '*'@1  + '/*'@1
  ```

**Um piso baixo separa exatamente esses dois grupos, e é 17× mais rápido.** Com piso 8:
23 admitidos, e os 10 perdidos são precisamente os 10 estilhaços — nenhuma perda útil,
0 extras. O piso deixa de ser critério de qualidade (esse papel é da regra do afixo) e
passa a ser o que permite semear com `str.find` em vez de streamar cada resposta por um
autômato de sufixos: **2,5 s contra 44,3 s**.

Alternativa ao piso, para quem não quiser número nenhum: os 6 piores estilhaços
(`'G'|'ET'`, `'c'|'ors'`, `'no'|'-co'|'rs'`, `'Up'|'grad'|'e'`, `'web'|'socket'`) são
exatamente os que **cortam no meio de uma palavra** — a regra de fronteira da §4.4 os
rejeita e mantém os 23. Mas ela não compra a velocidade; o piso baixo compra as duas
coisas.

### 4.2 A regra do afixo protege — no caso certo, e só nele

Este é o ponto em que a proposta ganha da spec, e ganha de forma limpa. Cenário V4
(descoberta em `real_responses`, que é o que o `run main` faz **hoje**):

```
valor  = 'Bearer eyJ…NTk5' + 'g1OTV9.BzJIc3nSiFTtZOrD8xYh3SzEpsMvNJrJAC_hb4pnO8Y'
                              └── exp + assinatura do JWT VELHO
fragmento = 123 caracteres do prefixo comum, @step 154 (resposta fresca do login)

spec  → ADMITE. Monta 'Bearer ' + prefixo_fresco + exp_velho + assinatura_velha
         = JWT corrompido que nenhum servidor aceita.
usuário → o afixo 'g1OTV9.BzJI…' não é encontrado literalmente em resposta nenhuma
         → DESCARTA o token. Correto.
```

A spec escapa dessa armadilha por outro caminho (§3.3 troca o corpus de descoberta), mas
**a regra do usuário é a que protege por construção** — vale para qualquer corpus, e é a
única defesa se a etapa 3 (redescoberta reativa) passar a alimentar a descoberta com
respostas frescas, que é justamente o plano.

### 4.3 Com o piso 32 da spec, porém, a mesma regra vira restritiva demais

O quadro da §4.1 é com a proposta do usuário inteira (sem piso, ou com piso baixo). Se a
regra do afixo for acoplada ao **piso 32 da spec**, ela inverte de sinal — porque o piso
força o fragmento a ser o caminho longo e joga o host constante para o afixo. Dos 63
fragmentos que o algoritmo corrigido acha com piso 32:

| motivo da rejeição | quantos |
|---|---|
| afixo `http://127.0.0.1:8080/src/view` — nunca aparece em resposta nenhuma | 23 |
| afixo `http://127.0.0.1:8080/src/view/com` — idem | 13 |
| afixo `http://127.0.0.1:8080` — só aparece no step 75, depois da janela do candidato | 9 |
| afixo `http://127.0.0.1:8080/src` — idem | 7 |
| afixo `2.png`, `3.png`, … (o dígito do avatar) | 6 |
| afixo `2025-10-27&endDate=2025-12-01` | 1 |
| **total rejeitado** | **59** |
| **total aceito** | **4** |

Quase toda a rejeição é o mesmo fenômeno: **o afixo é o prefixo constante da URL**
(esquema + host + diretório), que por definição não aparece no corpo de nenhuma resposta,
porque as respostas trazem caminhos relativos. A regra pede que uma constante do request
tenha origem numa resposta — e constante não tem origem.

Taxa de falso-negativo **nessa combinação**: 94% (59/63). O culpado é o piso 32, não a
regra: com piso 8 a mesma regra admite 23 decomposições de URL e rejeita só estilhaço
(§4.1).

### 4.4 O teste de fronteira dá a mesma proteção sem falso-negativo

Regra alternativa, do mesmo tamanho de código: **o corte tem que cair num delimitador** —
de cada lado, ou o caractere vizinho no valor não é alfanumérico, ou o caractere da ponta
do fragmento não é alfanumérico.

| caso | afixo encontrável (usuário) | corte em delimitador |
|---|---|---|
| 63 fragmentos legítimos do fluxo | 4 aceitos, **59 rejeitados** | **63 aceitos, 0 rejeitados** |
| V4 (`…NTk5` \| `g1OTV9.BzJI…`, corte no meio do base64) | rejeita ✓ | **rejeita ✓** |
| caso ideal (`Bearer ` \| `eyJ…`, corte no espaço) | aceita ✓ | **aceita ✓** |

Separação perfeita nos dois casos que importam, e nenhuma perda. O que a intuição do
usuário está captando de verdade é "**o corte não pode partir um token opaco ao meio**" —
e fronteira de delimitador mede isso diretamente, enquanto "o resto existe em alguma
resposta" mede por tabela e erra 94% das vezes.

### 4.5 Extrator parcial para o afixo trabalha contra o objetivo declarado

Cenário controlado, com o corpo do login reconstituído em `original_responses` (é o
cenário da spec original, que esta gravação não tem):

```
SPEC     : 1 extrator  — JWT[173] @step 154 ; 'Bearer ' fica literal
           steps no schedule: {154}

USUÁRIO  : 2 extratores — JWT[173] @step 154
                        + 'Bearer '[7] @step 23  ← extrai a string literal "Bearer "
                                                    de dentro de um blob de JS
           steps no schedule: {23, 154}
```

O afixo `'Bearer '` **não muda entre as épocas** (medido: `muda_entre_epocas=False`). Com a
porta aplicada peça a peça ele seria barrado e o resultado convergiria para o da spec; com
a porta aplicada ao token inteiro (que é como a proposta está escrita — "validar se o
token possui alguma alteração, se tiver aí criamos os extratores parciais") ele sobrevive
e **arrasta o step 23 para o schedule de todos os 21 steps autenticados**.

Sem a porta, o efeito no fluxo inteiro: a variante D leva o schedule do step 230 de
**7 para 10 steps**; a variante B+ (spec corrigida), de 7 para 12. Nenhuma variante de
fragmento reduz o schedule de step nenhum. **Quem reduz é a porta, e só ela** (7 → 1).

### 4.6 Custo

| passe | tempo no fluxo (330 steps, 240 valores distintos) |
|---|---|
| valor inteiro (hoje) | 2,2 s |
| + fragmento por âncora única (spec) | +0,08 s |
| + fragmento multi-âncora (correto) | +0,27 s |
| + LCS exata com piso 32 | +35,4 s |
| + LCS exata sem piso (proposta literal) | **+68 s** (30× o pipeline inteiro) |

---

## 5. As outras três specs propostas

### Spec 1 — porta de admissão + separar parse do run + alinhar dois HARs

- **A porta**: correta, é o núcleo, e o número acima confirma (7 → 1 step). A ressalva é o
  custo: 380 arestas de requisição condicional caem junto. Elas **precisam** da etapa
  reativa, senão o replay pós-deploy acusa `200` onde esperava `304` sem aresta que
  explique.
- **Separar o parse do `run`**: faz sentido e é barato. Hoje `Engine._reproduce`
  (`engines/engine.py:41-53`) lê o `.har` e persiste `real_requests/` +
  `original_responses/` no mesmo laço da análise. Um comando `parse` que só produz esses
  dois diretórios, e um `run` que exige que eles existam, deixa o `run` ser reexecutado
  contra respostas de outra procedência — que é exatamente o que a spec 3 precisa.
- **Alinhar duas gravações do mesmo fluxo para dar segunda época ao `dry`**: é a peça
  frágil da proposta, por duas medições:
  1. **Não resolveria o caso motivador.** O corpo do login não está no HAR. Uma segunda
     gravação do mesmo navegador também não teria. O JWT fresco só existe porque o
     `run main` capturou via proxy.
  2. **O alinhamento é ambíguo em 88% do fluxo.** 330 entries para apenas **115** pares
     `(método, URL)` distintos; **290 entries** compartilham chave com outra
     (`GET /src/app.js` aparece 4 vezes, e assim por diante). Alinhar por chave exige
     casar ordem + contagem, e qualquer variação de comportamento entre as duas gravações
     (um clique a mais, um lazy-load que não disparou) desloca tudo dali para frente.

  Alternativa mais barata com o mesmo efeito: rodar o `run main` **duas vezes** no mesmo
  workspace e comparar `real_responses` da execução N com a N-1. Duas épocas reais, mesma
  ordem de entries por construção, zero código de alinhamento. E se a intenção é dar porta
  ao `dry`, o caminho é o mesmo — dois `real_responses` de origens declaradas, que é
  precisamente o parâmetro que a spec 3 já vai precisar.

### Spec 2 — extratores parciais

Sustenta-se, com um ajuste. O que se sustenta: a **regra do afixo** (é o filtro de
qualidade da proposta — 170 → 33) e a **busca pela maior substring**, que não precisa de
autômato de sufixos: multi-semente com piso baixo dá resultado idêntico em 1/17 do tempo.
O ajuste é o piso — **8, não 32 e não zero**: 32 mata as 23 decomposições de URL úteis,
zero custa 44 s e admite 10 estilhaços de 1 a 3 caracteres.

O que não se sustenta é o **extrator parcial para o afixo**: ele adiciona âncora, aumenta
o schedule e, quando a porta é aplicada peça a peça, é sempre barrado — 47 das 49 peças
não mudam entre as épocas. A decomposição serve para **encontrar** a origem; a peça
estática deve sair literal no curl.

### Spec 3 — redescoberta reativa

Correta, e a observação de que "a solução depende que todos esses passos sejam executados"
é o ponto mais importante da revisão inteira. Com a porta ligada e sem esta etapa, o
projeto **perde** 380 arestas de requisição condicional e não ganha nenhuma em troca nesta
gravação. A porta sozinha é uma regressão; porta + redescoberta é a feature.

Sobre o mecanismo: apontar o `run main` para o diretório de respostas de um replay
divergente funciona e é o encaixe natural do "separar o parse do run" da spec 1 —
`run` passa a receber *qual* é o corpus de descoberta e *qual* é o de comparação, em vez
de derivá-los do modo.

### Spec 4 — agente autônomo

Sem objeção. Vale registrar que a spec já mediu (§1.7) que o modelo do `config.json` erra
3/18 quando decide sem as duas épocas em mãos, e sempre no mesmo caso — então a ferramenta
que o agente recebe tem que **entregar as duas épocas**, não perguntar "esse valor parece
dinâmico?".

## 6. As duas queixas de leitura

Estão certas, e não são só estilo — o texto realmente não fecha sozinho.

- **Item 4** (`optimize`: proveniência × necessidade). Traduzido: hoje o `optimize` nunca
  tenta remover as âncoras, só os steps entre elas — e âncora é qualquer step que apareça
  numa linha `comes from response of step`. Como o `ReplayTokenResolver` lê a resposta
  congelada em disco quando a origem está fora do schedule, quase toda âncora é removível
  sem quebrar nada (medido no relatório: 6 dos 7 steps do alvo principal). "Proveniência"
  = a aresta existe só porque o valor apareceu ali; "necessidade" = o step precisa rodar
  de verdade. A frase da spec diz que a porta resolve isso por construção, porque só cria
  aresta quando o valor muda. **Só que isso é verdade em cima de duas observações**, e a
  §1.5 admite que duas observações não provam nada permanente — então o "por construção"
  é mais forte do que a evidência permite.
- **Item 2** (`origin_location` no cache hit). Traduzido: quando o candidato reusa um slot
  já registrado, `CandidateResolver._process_candidate` (`:61-63`) volta cedo sem preencher
  `origin_location`; o `CurlGenerator` então escreve `origin location undetermined — using
  literal captured value` mesmo para token que tem extrator determinístico funcionando.
  No relatório eram 540 de 757 linhas mentindo. É cosmético para a execução e enganoso para
  qualquer investigação.

A sugestão de abrir a spec com **glossário + sumário** procede. Os termos que precisam de
entrada: *época*, *porta de admissão*, *aresta*, *âncora*, *proveniência × necessidade*,
*fragmento*, *afixo*, *slot*.

---

## Recomendação

1. **Fase 1 — parse separado do run** (spec 1, sem o alinhador de HAR). Baixo risco,
   destrava as fases 2 e 3.
2. **Fase 2 — casamento por fragmento**, com: multi-semente (não âncora única), **piso 8**
   (não 32), **regra do afixo** como porta de admissão do corte, e afixo **literal** no
   curl — nunca extrator próprio. Sem porta de época ainda.
3. **Fase 3 — porta de admissão + redescoberta reativa juntas.** Entregar a porta sozinha
   é regressão medida (−380 arestas de requisição condicional, +2 extratores espúrios,
   0 corretos).
4. **Antes de qualquer coisa: regravar o HAR com o corpo do login.** Nenhuma das três
   fases resolve o `Authorization` nesta gravação — o dado não está lá. Alternativa que
   dispensa a regravação: fazer a descoberta poder ler `real_responses` de uma execução
   **anterior** (não da corrente), que é a fase 3 já resolvendo o problema da fase 2.
