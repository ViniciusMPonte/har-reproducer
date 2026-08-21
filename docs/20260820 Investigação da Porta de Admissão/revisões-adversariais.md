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
