# Revisões adversariais — achados consolidados

Duas revisões independentes, ambas com contexto limpo (sem ter visto a discussão que gerou o
desenho), acesso ao código e aos dois workspaces, e instrução de verificar rodando código em
vez de confiar no documento. Lentes diferentes de propósito:

- **Revisão de implementabilidade** — o engenheiro que teria que virar a spec em tasks sem
  poder perguntar nada: fidelidade das citações de código, decisões que obrigariam a
  inventar, efeito colateral nos consumidores, cobertura de teste.
- **Revisão de evidência** — cético por padrão: a medição sustenta a conclusão? reproduz? o
  desenho sobrevive a uma segunda gravação? viola a genericidade do projeto?

Cada uma rodou duas rodadas. Os achados abaixo estão agrupados por consequência, não por
revisor. **Verifiquei por conta própria** todos os marcados com ✅ — os outros são reportados
como vieram, com a fonte indicada.

---

## 1. Achados que derrubaram decisões

### 1.1 ✅ A política de cache entregaria o extrator a 1 de 13 curls

A spec descartada dizia, em §3.5, que ao aceitar um fragmento o valor volta ao cache de
negativos "de modo que as ocorrências seguintes reprocessem a busca". Mas
`CandidateResolver._find_origin` grava `_origin_misses[value] = step_index`, e
`OriginFinder.find` filtra `index >= from_step_index` — então gravar `misses[jwt] = 224`
**exclui o step 153 da janela** de todas as ocorrências seguintes.

Medido, contando **ocorrências** (não origens distintas):

```
política                                        Authorization com extrator
grava _origin_misses no acerto de fragmento     1/13
não grava (janela larga, refaz o LCS)          13/13   — 29,4 s
cache provisório + repasse do passe barato     13/13   —  5,6 s
```

⚠️ **O instrumento de medição original escondeu o defeito**: todos os scripts contavam
origens distintas e sobreviventes da porta, nunca ocorrências que receberam placeholder. O
número "1 extrator" estava certo e era irrelevante.

**Resolução, medida depois:** as duas revisões pareciam se contradizer (uma disse que o cache
provisório é o que transforma 1 em 13; a outra, que ele não muda nada). São três variáveis
e o desenho amarrava as três:

```
NOVO  cache PROVISÓRIO (com repasse) : 3,5s  1 extrator, 13 linhas
NOVO  cache DEFINITIVO (como hoje)   : 2,8s  1 extrator, 13 linhas
```

O que quebra os 13 curls é **gravar `_origin_misses` no acerto de fragmento** — uma linha.
Cachear o fragmento para reuso já é o comportamento de hoje e está correto. A maquinaria de
promoção é peso morto: +23% de tempo, e a única promoção em 3.143 ocorrências é lixo
(`'origin'` promovido de `'same-origin'`).

### 1.2 ✅ A causa dos falsos positivos é um defeito de persistência, não mudança de CDN

A primeira revisão atribuiu os falsos positivos da gravação anterior a bundles de CDN de
terceiros que encolhem entre as épocas. A segunda descobriu que eles **não encolhem**: o
corpo da época da execução foi persistido ainda comprimido, como texto com 39% a 44% de
U+FFFD. Verifiquei:

```
ws_anterior — respostas legíveis numa época e ilegíveis na outra: 4
  step  13 enc=br    HAR  80821 ch (0% FFFD) | EXEC  23259 ch (43% FFFD)
  step  14 enc=gzip  HAR   1272 ch (0% FFFD) | EXEC    430 ch (39% FFFD)
  step  76 enc=br    HAR 102025 ch (0% FFFD) | EXEC  17750 ch (44% FFFD)
  step 159 enc=br    HAR 208522 ch (0% FFFD) | EXEC  67879 ch (44% FFFD)

ws_atual — respostas legíveis numa época e ilegíveis na outra: 0
                    (26 de 311 são ilegíveis nas DUAS épocas — conteúdo binário legítimo)
```

Os steps 13, 14, 76 e 159 são exatamente as origens dos falsos positivos. Prova cruzada da
revisão: o **mesmo recurso e o mesmo valor** dão "estático" no workspace atual (corpo
decodifica) e "mudou" no anterior (não decodifica). Virou o item 10 do backlog, e é
pré-requisito da porta.

### 1.3 O casamento de valor inteiro não tem defesa nenhuma

Os critérios de admissão do desenho valiam só para fragmento. Um valor de 3 caracteres
(`header:priority = 'u=0'`) casado **inteiro** dentro de um CSS de 100 KB que mudou entre as
épocas vira extrator e âncora, e nada o impede. Na gravação anterior, 3 dos 9 sobreviventes
eram casamentos inteiros (comprimentos 3, 60 e 85).

A revisão de evidência mediu as quatro defesas propostas e nenhuma resolve isolada:

```
base (desenho da spec)      extr=3   piso 4 no inteiro     extr=2 (mata só 'u=0')
piso 16 / 24 / 32           extr=2   origem estruturada    extr=0
corpo estável (razão ≤2×)   extr=0   TokenLocation != None extr=1
```

Piso alto tem preço duro: os casamentos inteiros legítimos da gravação anterior têm
comprimento 18–21 (`ETag`, 63 valores) e 29 (`Last-Modified`, 21 valores) — **piso ≥ 18
começa a destruir a classe de requisição condicional inteira**. Teto duro: 17.

Exigir origem estruturada (valor exato de header/cookie ou folha completa de JSON) resolve
nesta amostra mas cria falso negativo demonstrável nos próprios fixtures do projeto:
`tok_CSS_1` está dentro de uma `<div>` e `scr_NONCE_2` dentro de um `<script>` — origem por
substring de corpo. Rejeitá-las apaga a cobertura de `CSSAgent` e `RegexAgent`, que existem
justamente para essa classe. O JWT sobrevive (é folha JSON), o CSRF-em-HTML não.

### 1.4 O contraexemplo do `Access-Control-Allow-Origin: *`

Construído pela revisão de evidência, patchando a época da execução:

```
NOVO  normal      : extr=1  dep= 13  anc=1
NOVO  com ACAO: * : extr=5  dep=255  anc=2
        204x header:Origin  <-75 inteiro   len=21
         30x header:Referer <-75 fragmento len=21
```

`Origin: *` em 204 lugares e `Referer: */dashboard/` — o desastre que a própria spec
descartada previa em §1.2 e deixava sem defesa. Piso não pega (21 caracteres), origem
estruturada **aceita** (é o valor exato de um header), razão de corpo aceita (0 bytes nas
duas épocas), `TokenLocation` aceita (`Header`). O único filtro que segura é o veto de
endereço do fluxo aplicado ao **texto casado**, e não só a fragmento.

### 1.5 ✅ O ganho grande não era da porta

Das 254 linhas de dependência do workspace atual, 246 vêm de extratores **literais**; na
gravação anterior, 772 de 865. Um extrator literal devolve o que um literal devolveria e
ainda assim emite linha de dependência, que é a única fonte de âncora.

```
                        linhas dep   âncoras   curls com âncora   smart médio
atual, hoje                 254         8         219/320           2,38 req
atual, sem âncora literal    11         5           7/320           1,03 req
anterior, hoje              865        69         232/235           6,48 req
anterior, sem âncora lit.    93        65          68/235           1,32 req
```

**89% a 96% de todo o ganho que a spec atribuía à porta**, a custo de zero capacidade
perdida. Virou o item 9 e é a etapa em andamento.

---

## 2. Achados que corrigiram números

### 2.1 ✅ O step 224 devolve 200, não 403

A spec descartada afirmava, em §1.1, que `replay --mode list [23, 75, 153, 224]` dá
`Step 224 → 403`. Medido contra o servidor no ar, dá **200**, e `GET /auth/check` com o JWT
congelado do `.curl.sh` também dá 200 (`exp` 2027-02-13). A frase foi herdada da spec de
17/08 sem reverificação — exatamente o erro que a regra de procedência acrescentada à skill
`spec-e-plano` existe para impedir.

Consequência prática: o critério de aceite da etapa da porta **não** pode ser "224 passa a
dar 200", porque já dá. Tem que ser: os 13 curls deixam de conter o literal e passam a conter
`{{extractor:…}}` com aresta para o step 153, verificável com JWT adulterado.

### 2.2 ✅ A classe de risco não está vazia — é a maioria da outra gravação

A medição original registrou "0 `If-None-Match` neste HAR" e concluiu que a classe de
requisição condicional estava vazia. A gravação anterior do mesmo site tem:

```
HAR anterior: 238 entries | If-None-Match=126 | If-Modified-Since=126 | respostas 304=124
```

Com a porta, 84 tokens (63 `If-None-Match` + 21 `If-Modified-Since`) viram literal
congelado, afetando 126 curls — **53,6% da gravação**. E a revisão mediu o custo funcional
contra o servidor:

```
com o ETag congelado do HAR (o que a porta produz): {304: 126}  divergências: 0
com o ETag adulterado (simula deploy)             : {200: 126}
```

Hoje o custo é zero; no primeiro deploy, 126 curls divergem. Proposta medida da revisão:
admissão por dois lados — `mudou entre as épocas` **ou** `origem estruturada` — recupera 100%
da classe por **+0,30 requisição por replay**.

### 2.3 ✅ O fragmento na época da execução cobre 68%, não 64%

A revisão de evidência reportou 116 de 180 (64%). Medido: os dois JWT têm 173 caracteres e
compartilham **123** de prefixo, divergindo a partir dos dígitos do `exp` — então
**123/180 = 68%**. O número da spec original (123 caracteres) estava certo.

Isso **reforça** o ponto da revisão em vez de enfraquecê-lo: 68% passa por qualquer limiar de
cobertura plausível, então o critério de cobertura não protege do erro de descobrir na época
da execução. Só a escolha da época protege.

### 2.4 ✅ Os corpos ausentes do HAR anterior: 140 brutos, 13 pela régua do projeto

A revisão reportou "140 de 238 entries sem corpo (59%)". Correto como contagem bruta, mas
`HARParser.entries_missing_response_body` — a régua que o próprio `run` imprime — exclui os
status que normalmente não carregam corpo (101/204/304) e reporta **13**. O login daquela
gravação é uma dessas 13: status 200, corpo vazio.

Consequência que se mantém: com a descoberta fixada na época do HAR, o `Authorization` não
tem origem naquela gravação, e a etapa da porta não entregaria nada lá. A gravação anterior
serve para amostrar falsos positivos, **não** para validar o objetivo.

### 2.5 ✅ O custo foi precificado numa implementação diferente da especificada

A spec descartada citava 8,1 s de descoberta em §3.1, §3.4, §3.5 e §5.10. Esse número saiu
de uma implementação com blob concatenado e memoizado por janela — não da implementação que
§3.1 descrevia (busca por step). A revisão mediu a implementação especificada: **4,0 s**.
E a comparação de §3.1 ("15,5 s contra 8,1 s") confrontava o total de uma configuração com
o componente de outra.

### 2.6 A ubiquidade não rejeitava nada, e era inimplementável como definida

Dois argumentos independentes, um de cada revisão:

- **Não faz trabalho:** com limiar 0,5 rejeita **zero** fragmentos nas duas gravações; o
  conjunto de extratores é idêntico com e sem ela. O caso que a spec dizia que ela protegia
  (`'cache-control'` casando `'control'`, cobertura 54%, ubiquidade 99%) é construído, não
  observado. Os falsos positivos curtos que de fato aparecem têm ubiquidade **baixa**:
  `'*/'` 21,5%, `'cor'`/`'ors'`/`'u='` idem.
- **Não é implementável como definida:** a spec a definia sobre "o corpus de descoberta", e
  as medições usaram um `original_responses/` completo. Num `run` real esse diretório é
  preenchido progressivamente, então no step 10 o denominador é 10. E memoizar por fragmento
  congela um valor calculado sobre uma amostra minúscula — a mesma patologia de "resposta
  provisória tratada como definitiva" que §3.5 existia para corrigir.

Medido depois: com limiar **0,20** ela passa a rejeitar 57 fragmentos (a classe `'*/'` do
valor `'*/*'`, cobertura 67%, que passava nos três critérios) sem mudar o resultado final. E
a revisão de evidência mostrou que ela faz trabalho real do lado do **casamento inteiro**
(`'keep-alive'` está em 97% das respostas). Conclusão: o critério não estava errado, estava
calibrado e posicionado errado.

---

## 3. Achados de implementação que a etapa da porta vai reencontrar

Reportados pela revisão de implementabilidade e não reverificados por mim, exceto onde
marcado. Ficam registrados para não serem redescobertos:

- **O candidato dispensado pela porta continua virando âncora.** `CurlGenerator._token_comments`
  filtra por `token.origin_step is not None`, e um candidato reprovado tem `origin_step`
  preenchido. Sem tratamento, a redução de linhas de dependência não acontece. Precisa de um
  valor novo em `DynamicToken.status` (`"Static"`) e de o gerador filtrar por "tem extrator
  registrado". ✅ Verifiquei o mecanismo: `DEPENDENCY_PATTERN` é a única fonte de âncora.
- **Nenhum código de produção lê `DynamicToken.status`** — só testes. Então `status` não
  serve de discriminador sem trabalho novo. A alternativa medida (`status == "Resolved"`)
  produz o golden `run_main` byte-idêntico e evita injetar `SessionStore` no `CurlGenerator`,
  o que quebraria 11 testes só por assinatura.
- **`--mode dry` precisa de sinal explícito.** Com o código de §3.6 da spec descartada, o
  corpus de execução em dry é o mesmo da descoberta, então a porta reprova tudo e o dry perde
  todos os extratores. A decisão: `execution_corpus: Optional[ResponseCorpus]`, com a
  `EngineFactory` entregando `None` quando `not engine_cls.USES_NETWORK`.
- **`origin_key` muda de capitalização entre as épocas** (`'pragma'` × `'Pragma'`,
  `'connection'` × `'Connection'`, `'access-control-allow-origin'` × capitalizado).
  `HeaderAgent._by_name` tem fallback lowercase e sobrevive; **`CookieAgent._by_name` não
  tem** — é `cookies.get(key)` puro. Extrator de cookie descoberto numa época e executado na
  outra falha em silêncio.
- **O fallback para `captured_value` sobrescreveria valor bom.** `Engine.handle_recovery`
  chama `resolve_all(force=True)` em 401/403; sem guarda, o fallback instala o literal da
  época do HAR sobre um token que já tinha valor fresco. Decisão: só quando
  `token_id not in state.tokens`. E dos três pontos de desistência de `_refresh_token`, o de
  "arquivo de resposta ausente" não deve disparar fallback.
- **Fragmento com espaço em branco na borda é inverificável.** `BaseAgent._execute_script` e
  `ExtractorRunner._execute_extractor_script` fazem `.strip()` na saída, então um fragmento
  maximal que começa ou termina em espaço nunca é aceito pelo laço TDD.
- **`PlaceholderApplier` substitui globalmente.** Um token cujo texto extraído é `'no-c'`
  (admitido por piso 4, do valor `'no-cors'`) reescreveria `Cache-Control: no-cache` como
  `Cache-Control: {{extractor:X}}ache`. Medido: 0 co-ocorrências nas duas gravações, então
  não se materializa — mas a única defesa é a porta.
- **A cobertura mínima nunca rejeita nada**, porque é o limite de poda da busca: todo
  fragmento devolvido já a satisfaz. Os critérios efetivos eram dois, não três.
- **A afirmação "`replay` e `optimize` não mudam" é falsa.** `ReplayOptimizer._compute_backbone`
  usa `anchors[-2]` e `_ranges_target_to_from` particiona entre âncoras consecutivas; mudar o
  número de âncoras muda a **forma** da busca, não só o conteúdo.
- **A premissa de que a rede de caracterização morre é falsa.** `run_dry_default` já cobre os
  cinco agentes e a porta não se aplica em dry — os goldens de dry passam byte-idênticos. O
  que a porta destrói é a cobertura do caminho de rede e do schedule do replay.
- **Tornar o valor `4242` estático mata o propósito de 6 cenários** (`replay_smart_noflag`,
  `replay_smart_to_4`, `replay_smart_from_3`, `replay_list_out_of_order`,
  `replay_ref_fallback`, e os 2 do `optimize`), incluindo a única cobertura de
  `_fallback_to_captured`. Custa ~5 linhas de roteamento por prefixo no `CannedHttpHandler`
  deixar ele divergir — muito mais barato do que perder os cenários.

---

## 4. O que as revisões verificaram e **sustentou**

Registrado porque tem valor igual ao que caiu:

- **A separação das duas épocas é a decisão mais sólida do desenho.** Descoberta na época do
  HAR dá fragmento de 173/180 (96%) — o JWT correto; na época da execução dá 123/180 (68%) —
  prefixo fresco com assinatura velha. `TokenLocationDetector.find` devolve `BODY_JSON` com a
  resposta da época do HAR e `None` com a da execução. Cair para a época da execução quando a
  do HAR não tem origem seria **ativamente pior** que o literal congelado.
- **O casamento por fragmento entrega o que promete**: é o único mecanismo que acha o
  `Authorization`, o agente que o resolve é o `JSONPathAgent` existente com `data['token']`,
  e o custo do passe é uma fração do total.
- **Todo o §2 da spec descartada** (mapa dos componentes) foi conferido linha a linha: os
  trechos citados existem literalmente, as assinaturas batem, e os comportamentos descritos
  como "estado atual" conferem. É a parte reaproveitável.
- **`searchable_text` é um blob e o casamento inteiro de hoje já é substring**: confirmado que
  `'?1'` casou dentro de bytes binários, `'same-origin'` dentro de
  `cross-origin-opener-policy: same-origin-allow-popups`, `'u=0'` dentro de
  `priority: u=0,i=?0`. A simetria que justifica aplicar a porta aos dois casos está certa —
  o que não segue é que a porta seja suficiente.
- **As categorias informativas novas não colidem com parser nenhum**: testado com as regex
  reais, `# [Static N] …` e `# [Frozen N] …` não casam com `DEPENDENCY_PATTERN` nem com
  `UNRESOLVED_PATTERN`, e `ReplayRunner._apply_replay_status` nunca as toca.
- **`_accept_persisted_slot` deixar de semear o token é seguro**: nada dentro de
  `analyze_step` consome `state.tokens`; `PlaceholderApplier` olha o `registry` e a
  renderização só acontece em `Engine._attempt_step`.
- **A honestidade metodológica do anexo original** — o aviso de que uma gravação não
  generaliza, a correção de um número herdado, o registro de que a tabela de filtros não
  distingue entre alternativas — foi apontada pela revisão como acima da média e deve ser
  preservada. É o que permitiu que os erros fossem achados.

---

## 5. Segunda rodada — as três lacunas da §1.3/1.4, resolvidas com número

A primeira rodada (§1–4) derrubou o desenho original mas deixou três lacunas abertas:
casamento inteiro sem defesa, requisição condicional sem admissão, e `FlowVocabulary` sem
formulação que não vetasse subdomínio dinâmico. Uma segunda rodada, com os dois revisores
recebendo o desenho corrigido (fragmento + cobertura 50% + piso 4 + vocabulário + porta +
cache provisório) e os mesmos dois workspaces, resolveu as três com medição. Reportado aqui
porque só existia na conversa, nunca commitado.

⚠️ Depois desta rodada, o item 9 (extrator literal não vira âncora) foi implementado e
mergeado. A regra abaixo rotulada **R4** é exatamente esse item, já em produção — citada
aqui porque ela é 89–97% do ganho que a segunda rodada mede, e porque as outras três regras
só fazem sentido combinadas com ela.

### 5.1 — Casamento inteiro: quatro regras, nenhuma isolada

| regra | o que faz | efeito medido |
|---|---|---|
| **R1** | piso absoluto de tamanho aplicado ao **texto casado**, inteiro e fragmento | mata `'u=0'` (3 chars); 0 casamentos legítimos destruídos em qualquer piso ≤ 17 nas duas gravações; piso ≥ 18 começa a destruir a classe de `ETag` (comprimento 18–21); teto duro 17 |
| **R2** | a porta exige **evidência posicional**: mesma chave de header/cookie, mesma folha de JSON, ou corpo legível — não "o texto não aparece no blob" | mata os 2 falsos positivos com origem no step 14 (o `google-fonts.css`) |
| **R3** | o veto de `FlowVocabulary` aplicado ao **texto casado**, inteiro e fragmento (hoje só se aplicava a fragmento) | é o único filtro que segura o contraexemplo `Access-Control-Allow-Origin: *` (5.4) |
| **R4** | nenhuma linha de dependência quando o extrator resultante é literal (`origin_location=None` ou `LITERAL_FALLBACK`) | **é o item 9, já implementado.** 89–97% do ganho medido em toda esta investigação |

Com as quatro juntas, medido nas duas gravações: `atual` 1 extrator/13 linhas/1 âncora,
inclusive sob `Access-Control-Allow-Origin: *`; `anterior` 0 extratores/0 linhas/0 âncoras,
inclusive sob o mesmo ataque.

⚠️ **Descoberta feita nesta rodada, importante para reler M11/M12 com o item 10 já
corrigido:** os falsos positivos do workspace anterior tinham origem nos steps **14 e 76**
— e os dois são exatamente dois dos quatro casos de corpo comprimido persistido como
mojibake que motivaram o item 10 (M12). Ou seja, **parte dos falsos positivos da primeira
rodada podem ter sido efeito do defeito do item 10**, não só de o casamento inteiro não ter
defesa. Precisa remedir com o workspace regenerado depois da correção do item 10 antes de
decidir se R1/R2/R3 ainda são necessárias, ou se ficam menos urgentes.

### 5.2 — Requisição condicional: admissão por dois lados, não porta única

Números com o desenho corrigido, gravação anterior: 126 ocorrências de `If-None-Match` (63
valores) + 126 de `If-Modified-Since` (21 valores) = 84 extratores, 252 ocorrências, 126
curls (53,6% da gravação), 65 âncoras distintas — a porta rebaixa **todos** a literal.

Contra o servidor: `ETag` congelado do HAR devolve **304 em 126/126** requisições (zero
divergência hoje); `ETag` adulterado (simulando deploy) devolve **200 em 126/126**. Ou
seja, o custo de admitir esses extratores como literal é **zero hoje**, e só aparece no
primeiro deploy.

Decomposição do custo: das 865 linhas do workspace anterior, 772 (89,2%) já são de
extrator literal — **isso é só o item 9 (R4)**, que sozinho leva 865→93 linhas e 6,48→1,32
requisições por replay. Ou seja, o "custo" de 6,48 requisições que a spec original atribuía
à ausência de porta já não existe depois do item 9; o que resta depois de R4 é **+0,30
requisição por replay**, não 5+.

**Proposta, medida:** admissão por dois lados — `mudou entre as épocas` **OU**
`origem estruturada` (o texto casado é o valor exato de um header, de um cookie, ou uma
folha completa de JSON), sob R1+R3+R4. Resultado: gravação anterior recupera **100%** dos
84 extratores condicionais (`extr=84 dep=252 anc=64`); gravação atual ganha só 3 slots de
lixo estrutural (`Cache-Control`/`Pragma`/`Connection`, valores `'no-cache'`/`'keep-alive'`)
além do JWT (`extr=4 dep=16 anc=3`).

O lixo é separável por **ubiquidade aplicada ao lado estruturado**: `'keep-alive'` está em
97% das respostas, `'no-cache'` em 5,6%, `ETag`/`Last-Modified` em 1,3% cada — um limiar
abaixo de 50% mata o `keep-alive` sem tocar no resto; um limiar mais agressivo (≤5%) mata
também o `no-cache`, ao custo de 9 dos 21 valores de `Last-Modified` (as faixas de
ubiquidade se sobrepõem: 5,1%–16,9%). Ou seja, a ubiquidade que foi cortada do lado do
fragmento (§2.6) volta a fazer trabalho real do lado estruturado — é outro eixo, não o
mesmo critério reaproveitado sem pensar.

**Resposta à pergunta "entregar a porta sem redescoberta reativa deixa a ferramenta melhor
ou pior?"**: com R4 (item 9) já valendo, a resposta deixou de ser um trade-off — ela é
melhor hoje **e** só marginalmente mais cara depois de um deploy (+0,30 req/replay), desde
que a admissão seja de dois lados. Sem o lado estruturado, ela seria melhor hoje e ativamente
pior no deploy (126/235 curls divergindo). A escolha entre os dois é a decisão real desta
lacuna, não "ter porta ou não ter".

### 5.3 — `FlowVocabulary`: veto condicionado à ordem de aparição, não posição absoluta

Todas as rejeições nas duas gravações são `fragmento == endereço` **exato**, nunca
contenção frouxa — quatro formulações testadas (`in`, `==`, "endereço do próprio request",
"esquema+autoridade") dão exatamente a mesma saída. A direção frouxa `fragmento ⊆ endereço`
que a spec original adotava não compra nada e carrega toda a classe de falso negativo da
objeção (`'api'`, `'fonts'`, `'example'` ficam vetáveis conforme o vocabulário cresce).

E pelo mesmo critério que tirou a ubiquidade do lado do fragmento ("não rejeita nada em
nenhuma das duas gravações" não é bem o caso aqui — ela rejeita, mas a saída final não
muda com ou sem ela, porque a porta já rejeitaria os mesmos fragmentos por outro motivo) —
só que ela é **indispensável do outro lado**: é o único filtro que segura o
`Access-Control-Allow-Origin: *` (5.4/5.1, R3).

**Formulação recomendada:** veto sobre o **texto casado** (inteiro e fragmento), por
**igualdade** com um endereço observado, **condicionado a esse endereço já ter aparecido
num request anterior ao step de origem**. Medido: saída idêntica ao veto absoluto nos casos
que already funcionavam, e **admite 3 fragmentos que o veto absoluto vetava por engano**
(`'http://localhost:8090'`, origem no step 34/36 — um bundle JS que informa a URL da API
**antes** de qualquer request usá-la). É exatamente o caso legítimo que a objeção original
descrevia (subdomínio de tenant/sessão cujo próprio descobrimento é a evidência), resolvido
sem custo.

### 5.4 — O contraexemplo que motivou R3, por extenso

Servidor configurado com `Access-Control-Allow-Origin: *`, patchando só a época da
execução, desenho corrigido sem R1/R2/R3 (só cobertura + piso de fragmento + porta + cache
provisório):

```
gravação atual, normal      : 1 extrator,  13 linhas, 1 âncora
gravação atual, com ACAO: * : 5 extratores, 255 linhas, 2 âncoras
        204x header:Origin  <-75 inteiro   len=21
         30x header:Referer <-75 fragmento len=21
```

`Origin: *` em 204 lugares, `Referer: */dashboard/`. Nenhuma das defesas que só valem para
fragmento (cobertura, piso do fragmento) o alcança, porque o casamento aqui é **inteiro**.
Com R1+R2+R3+R4: `1 extrator/13 linhas/1 âncora`, mesmo sob o ataque.

---

## 6. Terceira rodada — medição fresca depois dos itens 9 e 10 aplicados

Feita em 21/08/2026, depois do merge dos itens 9 e 10. Os dois workspaces da investigação
foram **regravados** com o código atual (`run --mode main` contra o servidor real,
preservados como `arquivos-har/ws_atual_pos_correcoes` e `arquivos-har/ws_anterior_pos_correcoes`,
fora do repositório por serem dados derivados — mesma política dos originais).

### 6.1 — O item 10 eliminou a classe de inversão de legibilidade, mas sobrou 1 falso positivo

M12 refeito sobre `ws_anterior_pos_correcoes`:

```
ilegíveis (>5% U+FFFD): época do HAR 11/98 | época da execução 15/102
legíveis numa época e ILEGÍVEIS na outra: 0        (era 4, antes do item 10)
```

A descoberta completa + porta sobre esse workspace, com os critérios já corrigidos
(cobertura 50% + piso 4 + vocabulário + ubiquidade 0,20):

```
1256 -> 46 fragmentos admitidos, todos "estático" (rejeitados corretamente)
1 extrator sobrevive: header:priority <- step 76, valor 'u=0'
```

Investigado: a resposta do step 76 (`cdnjs.cloudflare.com`) tem `102025` caracteres nas
duas épocas (tamanho idêntico, sem mojibake), mas o header `priority: u=0,i=?0` está
presente na época do HAR e **ausente** na época da execução — variação do lado da CDN
(Cloudflare), não do projeto. Confirmado que o request enviou `priority: u=0` nas duas
épocas (é replay fiel do header de request); é a resposta que varia.

**Isso é o "terceiro caso" que a spec original já previa** (header extraído que não existe
na época da execução, §3.4 da spec descartada) — só que agora com exemplo real, atual, e
isolado do defeito do item 10 (que foi corrigido e não é mais a explicação).

### 6.2 — A política de cache complexa é desnecessária sob os critérios corrigidos

Comparação fresca das três políticas (`descoberta.py --cache {definitivo,misses,provisorio}`)
nos dois workspaces regravados:

| política | HAR atual: extratores / ocorrências | HAR antigo: extratores / ocorrências |
|---|---|---|
| cache simples (igual a `CandidateResolver._find_origin` hoje, sem mudança) | 1 / **13** | 1 / 1 |
| nunca cachear fragmento (variante "segura" da §3.5 antiga) | 1 / **1** ← reproduz o bug original | 1 / 1 |
| cache provisório + repasse do passe barato (a recomendação da investigação) | 1 / **13** | 1 / 1 |

**Cache simples e cache provisório empatam.** Verificado que `header:Origin` (266
ocorrências no HAR atual) continua casando o valor **inteiro** em 204 ocorrências mesmo com
o cache mais simples: o fragmento `'http://'` (7 chars, cobertura 33% de
`'http://127.0.0.1:8080'`) é rejeitado pela cobertura mínima **antes** de qualquer
oportunidade de cache — o caso que motivava a maquinaria complexa não sobrevive à cobertura
de 50%, então a maquinaria nunca é exercitada.

**Conclusão: `CandidateResolver._find_origin`/`_origin_cache` não precisam de nenhuma
mudança.** A política de cache que a spec descartada (e a primeira rodada de revisão)
tratavam como decisão central da etapa (§3.5) sai do escopo — zero código novo ali. O que
muda é só o que `OriginFinder.find` devolve (agora podendo ser um fragmento), e o cache
existente já lida com isso corretamente por construção.

### 6.3 — R2 (evidência posicional) precisa generalizar `_origin_key`, não reimplementar

O caso do §6.1 mostrou que a evidência às vezes é uma **substring** de um header
(`'u=0'` dentro de `'u=0,i=?0'`), não o valor exato — e `OriginFinder._exact_key`
(`origin_finder.py:60-64`) só compara por **igualdade exata**, então nunca populava
`origin_key`/`origin_container` para esse caso (ele ficava `None`, tratado como
substring-de-corpo).

A formulação de R2 é a generalização natural: localizar em qual container (header, cookie,
corpo, `redirect_url`) o texto casado apareceu na época do HAR **por contenção** (não por
igualdade), e comparar especificamente esse container contra a época da execução —
container ausente lá → indeterminado; presente e diferente → mudou; presente e igual →
estático. É extensão de `_exact_key`, generalizando `==` para `in`, não um mecanismo novo.
