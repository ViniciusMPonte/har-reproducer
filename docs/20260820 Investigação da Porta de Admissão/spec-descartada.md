# Spec DESCARTADA — Casamento por Fragmento e Comparação entre Épocas

> ⚠️ **Este documento não vale como spec. Não implemente nada a partir dele.**
>
> Foi escrito em 20/08/2026, aprovado por ninguém, e descartado no mesmo dia depois de duas
> revisões adversariais de contexto limpo. Está preservado aqui porque três partes dele
> continuam úteis e foram reaproveitadas: o mapa dos componentes existentes (§2), a análise
> das duas épocas (§1.2, §1.3, §3.6) e a lista do que foi avaliado e descartado com motivo.
>
> **O que foi derrubado**, em resumo (o detalhe está em `revisões-adversariais.md`):
>
> - §3.5 (política de cache), como escrita, entregaria o extrator do `Authorization` a **1
>   dos 13 curls** — gravar `_origin_misses` no acerto de fragmento exclui o step do login
>   da janela seguinte.
> - §3.6 e §3.7 se contradizem em `--mode dry`: com o código de §3.6, o corpus de execução
>   em dry é o mesmo da descoberta, então a porta reprova tudo e o dry perde todos os
>   extratores.
> - §3.12: o candidato dispensado pela porta continua com `origin_step` preenchido, então
>   continuaria emitindo linha de dependência e virando âncora — a redução de 254 para 13
>   linhas não aconteceria.
> - §1.1 afirma que o step 224 devolve `403`. Medido contra o servidor: devolve **200**. A
>   frase foi herdada da spec de 17/08 sem reverificação.
> - §3.3: a ubiquidade, com limiar 0,5, rejeita **zero** fragmentos nas duas gravações; e,
>   como definida (sobre o corpus completo), é inimplementável num `run` real, porque
>   `original_responses/` só tem os steps já processados.
> - A afirmação central ("os três critérios + a porta zeram os falsos positivos") não
>   sobrevive à segunda gravação: 9 extratores, 8 falsos positivos, e o `Authorization`
>   não está entre eles.
> - E o mais consequente: **89% a 96% das linhas de dependência que a spec atribui à porta
>   vêm de extrator literal congelado**, que não deveria virar âncora — assunto que virou
>   etapa própria e não precisa de nada desta spec.
>
> O que substituiu esta spec está registrado como itens 9, 10 e 11 do adendo de 20/08 em
> `docs/20260817 Reteste do Otimizador contra Servidor Real/correcoes.md`.

---

## 0. Sumário

Hoje o projeto cria extrator para valor que **nunca muda** e não cria extrator para o
único valor que **muda de verdade** neste fluxo. Esta etapa corrige os dois com o mesmo
critério: um candidato só vira extrator quando existe evidência observada de que o valor
mudou entre a resposta gravada no HAR e a resposta obtida na execução; e a busca de
origem passa a aceitar como origem o maior pedaço contíguo do valor que a resposta
contém, não só o valor inteiro. No workspace medido, isso troca **17 extratores e 254
linhas de dependência** por **1 extrator e 13 linhas** — e o extrator que sobra é o
`Authorization: Bearer <JWT>`, que hoje fica congelado como literal e quebra no dia em
que o token expirar.

### Glossário

Termos que esta etapa inventa ou ressignifica. Sem eles o resto do documento não se lê.

| termo | significado nesta spec |
|---|---|
| **época** | Momento de captura de uma resposta. Há duas: a **época do HAR** (`original_responses/`, o que o servidor respondeu quando o fluxo foi gravado) e a **época da execução** (`real_responses/`, o que o servidor respondeu no `run` corrente). |
| **candidato** | Par `(path, valor)` que o `BaselineDiff` marcou como possivelmente dinâmico, comparando o request do step contra o request da primeira entry do HAR. `path` é `url`, `header:Nome`, `cookie:Nome` ou `body[:N]`. |
| **origem** | Step anterior cuja resposta contém o texto do candidato. É o que transforma um literal em aresta `step X depende de step Y`. |
| **casamento inteiro** | Origem encontrada porque a resposta contém o valor do candidato **por completo**. É o único modo que existe hoje. |
| **fragmento** | Maior pedaço contíguo do valor do candidato que a resposta contém, quando ela não contém o valor inteiro. |
| **cobertura** | `len(fragmento) / len(valor)`. Mede o quanto da evidência a resposta explica. Substitui um piso absoluto de tamanho. |
| **ubiquidade** | Fração das respostas do corpus de descoberta que contêm o fragmento. Mede se o texto é evidência de origem ou vocabulário que qualquer resposta tem. |
| **vocabulário do fluxo** | Conjunto de hosts e origins (`host`, `host:porta`, `esquema://host:porta`) observados nos requests do próprio HAR. Usado para reconhecer que um fragmento é o endereço do próprio site, não um token. |
| **porta de admissão** | Regra final: o texto casado tem que **diferir** entre as duas épocas no mesmo step de origem. Se for idêntico, o valor fica literal e nenhum extrator é criado. |
| **âncora** | Step de origem citado numa linha de dependência de um `.curl.sh`. O `replay --mode smart` puxa toda âncora para o schedule, então cada aresta encarece todo replay que use aquele curl. |
| **peça restante** | Prefixo e/ou sufixo do valor que sobram fora do fragmento (ex.: `'Bearer '` em `'Bearer <jwt>'`). |

Todos os números deste documento estão em `medições.md`, nesta mesma pasta, com a
procedência e os scripts que os produzem.

---

## 1. Objetivo

### 1.1 Problema A — valor dinâmico que nunca vira extrator

O header `Authorization: Bearer <JWT>` fica congelado como literal em 13 `.curl.sh`; o
step do login nunca vira origem de ninguém; e o trecho autenticado do fluxo só funciona
enquanto aquele JWT específico não expirar. Medido no workspace
`arquivos-har/ws_20260817_main` (HAR de 17/08/2026, 324 entries):

```
$ grep -l "Authorization: Bearer eyJ" curls/*.curl.sh | wc -l      # 13 — literal congelado
$ grep -l "Authorization: {{extractor" curls/*.curl.sh | wc -l     # 0  — token dinâmico
$ grep -h "comes from response of step 0153" curls/*.curl.sh | wc -l   # 0  — login como origem
```

A causa é precisa: o request manda `Bearer <jwt>` e a resposta do login (step 153) traz
`{"token":"<jwt>"}`. `OriginFinder` exige o valor **inteiro** no texto da resposta, então
a origem nunca é encontrada. Medido com as classes reais, corpus da época do HAR:

```
find('Bearer eyJ…xPxM', 0, 224) ......... None
find('eyJ…xPxM', 0, 224)   (só o JWT) ... step_index=153
```

Incluir o login à mão no replay não resolve — ele roda, devolve um token novo, e nenhum
`.curl.sh` consome esse token: `--mode list [23, 75, 153, 224]` dá `Step 153 → 200`
seguido de `Step 224 → 403`.

### 1.2 Problema B — valor estático que vira extrator

O mesmo workspace tem 17 extratores. Os 15 valores distintos que os originaram são
idênticos entre as duas épocas — são URL de CDN, `application/json`, `no-cache`,
`keep-alive`, `document`, `same-origin`, `?1`, `http://127.0.0.1:8080`. Nenhum é
recalculável nem precisa ser: um extrator cujo valor não muda devolve exatamente o que um
literal devolveria.

O custo não é cosmético. Cada aresta vira âncora, e âncora entra no schedule do
`replay --mode smart`. Hoje são **254 linhas de dependência**, **8 âncoras** (steps 0, 1,
4, 14, 23, 37, 75, 154) e **219 dos 320 curls** arrastando pelo menos uma delas. E há um
risco latente: o token de `Origin` (`http://127.0.0.1:8080`, origem no header
`access-control-allow-origin` do step 75) é referenciado 576 vezes; num servidor
configurado com `Access-Control-Allow-Origin: *`, o replay montaria `Origin: *` e
`Referer: */dashboard/` em todos esses lugares.

Os dois problemas têm a mesma solução porque têm o mesmo critério: **evidência observada
de mudança**, e não aparência (formato, tamanho, nome de header) nem força do casamento.

### 1.3 O que esta etapa cobre

1. **Casamento por fragmento** — aceitar como origem o maior pedaço contíguo do valor que
   uma resposta contém (§3.1, §3.4).
2. **Três critérios de admissão do fragmento** — cobertura, ubiquidade e vocabulário do
   fluxo, todos derivados em runtime, nenhum com constante de protocolo (§3.2, §3.3).
3. **Cache positivo só para casamento inteiro** — fragmento é resposta provisória e não
   pode congelar a decisão para o resto do fluxo (§3.5).
4. **Separação das duas épocas** — descoberta e verificação sempre na época do HAR;
   execução sempre na época corrente (§3.6).
5. **Porta de admissão por mudança entre épocas**, com registro do que foi dispensado
   (§3.7, §3.12).
6. **Consequências obrigatórias da separação de épocas** — parar de semear o token com o
   valor da época do HAR (§3.10) e cair para o `captured_value` quando a extração falha na
   época da execução (§3.11).
7. **Fixtures que divergem entre as épocas** — sem isso a porta zera a cobertura de teste
   de todo o pipeline de descoberta (§3.13).

### 1.4 Fora de escopo

- **Redescoberta reativa.** Um valor genuinamente dinâmico que veio igual nas duas
  observações fica literal e quebra no dia em que mudar. A solução é detectar que um step
  que antes passava parou de passar e, nesse ponto, refazer a descoberta com as respostas
  frescas em mão. É a etapa seguinte. Fica registrado que ela é viável sem passar o `.har`
  para o `replay`: `real_requests/req_0224.json` guarda o request literal, com o JWT cru e
  sem placeholder, porque é gravado antes da análise, e as duas épocas estão em disco.
- **Segundo HAR do mesmo fluxo para dar duas épocas ao `--mode dry`.** Alinhar duas
  gravações não é lookup por chave: das 324 entries deste HAR há 110 chaves
  `(método, url)` distintas, 75 repetidas, cobrindo 89% das entries. É alinhamento de
  sequência, com peso próprio. O `--mode dry` fica sem porta nesta etapa (§3.7).
- **Compor vários extratores parciais para um mesmo valor.** A peça restante que sobra
  fora do fragmento fica literal e, quando ela própria muda entre as épocas, é reportada
  (§3.8). Criar um segundo extrator para ela é decisão adiada — medido, nos 122 valores
  distintos deste fluxo nenhuma peça restante muda entre as épocas, então a capacidade
  dispararia zero vezes aqui.
- **`BaselineDiff` comparar contra a primeira entry do HAR.** É a causa raiz do excesso de
  candidatos, e é pior do que parece: a entry 0 deste HAR tem 6 headers (`Accept`,
  `Upgrade-Insecure-Requests`, `User-Agent`, `sec-ch-ua`, `sec-ch-ua-mobile`,
  `sec-ch-ua-platform`), então todo `Sec-Fetch-*`, `Host`, `Origin`, `Referer`,
  `Cache-Control`, `Pragma` e `Content-Type` de qualquer step posterior é candidato para
  sempre. A porta corta o efeito, não a causa. Vale spec própria.
- **Token curto dentro de valor longo** (`http://host/api/items/12345?x=1`, onde só
  `12345` é dinâmico). Nenhum critério desta spec o alcança — cobertura seria 16%. É
  limitação da granularidade do candidato, que chega como URL inteira.
- **Gate de LLM para decidir admissão.** A admissão fica determinística: o dado responde a
  pergunta, e a LLM é opcional no projeto (`ProjectConfig.llm` tem default `None` e nenhum
  cenário golden a configura).

---

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `OriginFinder` — `har_reproducer/tracking/origin_finder.py` (65 linhas, arquivo inteiro)

Ponto único de descoberta de origem. `find` (`:13-25`) filtra os steps elegíveis pela
janela `[from_step_index, before_step_index)`, percorre as variantes de encoding
(`ValueVariants.of`) e delega a `_find_variant` (`:27-33`), que devolve o **primeiro**
step cuja resposta contém a variante inteira:

```python
def _find_variant(self, eligible: List[int], variant: str, is_raw: bool) -> Optional[OriginMatch]:
    for step_index in eligible:
        text: Optional[str] = self.corpus.searchable_text(step_index)
        if text is None or variant not in text:
            continue
        return self._build_match(step_index, variant, is_raw)
    return None
```

`_build_match`/`_origin_key` (`:35-58`) só tentam descobrir a chave de origem quando a
variante casada é o valor cru, comparando por igualdade exata contra cookies e depois
headers. É onde entra o passe de fragmento (§3.4).

### `ResponseCorpus` — `har_reproducer/tracking/response_corpus.py` (89 linhas, arquivo inteiro)

Corpus sobre um diretório de respostas, memoizado por step. `searchable_text` (`:33-45`)
serializa headers (`Nome: valor`), cookies (`nome=valor`), `redirect_url` e o corpo cru
numa string só, via `_serialize` (`:57-72`).

⚠️ **`searchable_text` não é "a resposta"; é um blob.** Isso importa para o desenho: o
casamento de valor inteiro de hoje **já é busca por substring**, e não evidência
estrutural. Medido, onde os casamentos atuais realmente aconteceram: `'?1'` dentro de
bytes binários de um corpo, `'same-origin'` dentro de
`cross-origin-opener-policy: same-origin-allow-popups`, `'application/json'` dentro de
código JS, `'document'` dentro de `document.getElementsByTagName(...)`. Não existe
fronteira "inteiro é confiável / pedaço é suspeito" — por isso a porta de §3.7 vale para
os dois casos, e não só para fragmentos.

A classe não muda. As duas épocas de §3.6 são duas instâncias dela.

### `CandidateResolver` — `har_reproducer/tracking/candidate_resolver.py` (200 linhas)

Acha origem, deriva o `token_id` do slot, reusa o extrator persistido se ele reproduzir o
valor do candidato, senão gera um novo.

```python
def _process_candidate(self, candidate: DynamicToken, step_index: int) -> DynamicToken:   # :45
    origin: Optional[OriginMatch] = self._find_origin(candidate.current_value, step_index)
    if origin is None:
        candidate.status = "NotFound"
        return candidate

    candidate.origin_step = origin.step_index
    candidate.origin_key = origin.origin_key
    candidate.origin_container = origin.origin_container
    base_token_id: str = self._derive_token_id(candidate.path, candidate.origin_step)
    ...
```

```python
def _find_origin(self, value: str, step_index: int) -> Optional[OriginMatch]:              # :67
    cached_origin: Optional[OriginMatch] = self._origin_cache.get(value)
    if cached_origin is not None:
        return cached_origin

    from_step_index: int = self._origin_misses.get(value, 0)
    origin: Optional[OriginMatch] = self.origin_finder.find(value, from_step_index, step_index)
    if origin is None:
        self._origin_misses[value] = step_index
        return None

    self._origin_cache[value] = origin
    return origin
```

⚠️ Duas propriedades deste método são load-bearing para esta etapa:

- **O cache de negativos tem janela**: um valor que não achou origem no step `N` só volta a
  ser procurado a partir de `N`. Consequência: o passe de fragmento e a porta têm que
  rodar **na mesma chamada** do passe de valor inteiro — como segunda tentativa posterior,
  a janela negativa já teria excluído o step 153 para todos os steps depois do 224.
- **O cache positivo é definitivo**: uma vez gravado, o valor nunca mais é procurado. É o
  que torna §3.5 necessária.

`_check_persisted_slot` (`:112-122`) roda o extrator persistido contra
`self.response_corpus.responses_dir` e compara com `candidate.current_value`;
`_accept_persisted_slot` (`:124-130`) grava o valor no `SessionStore`;
`_register_extractor` (`:157-170`) grava `captured_value = candidate.current_value`;
`_build_literal_extractor` (`:192-200`) emite `return {candidate.current_value!r}`. Todos
passam a operar sobre o texto que o extrator tem que produzir, não sobre o valor do
request (§3.9).

### `TokenResolver` — `har_reproducer/tracking/token_resolver.py` (36 linhas, arquivo inteiro)

Resolve, contra o diretório de respostas da **execução**, todo token registrado que ainda
não tem valor:

```python
def resolve_all(self, force: bool = False) -> None:      # :15
    for token_id, extractor in self.session_store.state.registry.items():
        if not force and token_id in self.session_store.state.tokens:
            continue
        if self._should_refresh_token(extractor):
            self._refresh_token(token_id, extractor)
```

⚠️ **Token já semeado nunca é atualizado** (`:17-18`) — é o que torna §3.10 obrigatória.
⚠️ **Falha na resolução deixa o placeholder cru**: `_refresh_token` (`:25-36`) retorna sem
gravar quando o extrator não devolve valor, e `SessionStore._resolve_token_placeholder`
devolve o texto original do match — o request sairia com `{{extractor:…}}` literal dentro
do header. É o que torna §3.11 obrigatória.

### `PlaceholderApplier` — `har_reproducer/tracking/placeholder_applier.py` (80 linhas)

Substitui **cada ocorrência do valor do token** pelo placeholder, em ordem decrescente de
tamanho do valor (`_ordered_by_value_length`, `:16-18`), em url, headers, cookies e body.

⚠️ A substituição já é por substring, e o efeito "fragmento dinâmico + afixo literal" já
existe no workspace atual sem feature nova: `-H 'Referer: {{extractor:5809b41a…}}/'` em
`req_0224.curl.sh`, onde o token vale `http://127.0.0.1:8080` e a barra ficou literal. **A
mecânica de saída que o fragmento precisa já está pronta.**

### `EngineFactory.create` / `_build_tracker` — `engines/construction/engine_factory.py:59-112`

Raiz de composição do ramo `run`. Hoje um único diretório alimenta duas coisas de
naturezas diferentes — o corpus da descoberta e o `TokenResolver` da execução:

```python
tracking_responses_dir: Path = (
    self.workspace.real_responses if engine_cls.USES_NETWORK else self.workspace.original_responses
)
...
response_corpus: ResponseCorpus = ResponseCorpus(tracking_responses_dir, Workspace.STEP_INDEX_WIDTH)
...
    self._build_tracker(response_corpus, session_store, extractor_runner, metadata_store),
    TokenResolver(tracking_responses_dir, session_store, extractor_runner),
```

É esse casamento que §3.6 desfaz.

### `Engine._process_entry` — `har_reproducer/engines/engine.py:69-96`

```python
self._persist_request_step(index, step.request)
self._persist_original_response_step(index, step.response)   # época do HAR, antes da análise
if skip_reason is not None:
    return self._skip_entry(index, skip_reason)
step.analysis = self.tracker.analyze_step(step, first_entry) # descoberta
self.token_resolver.resolve_all()                            # execução
response: StepResponse = self.execute_step(step)
self._persist_response_step(index, response)                 # época da execução
```

⚠️ Em `--mode main`, quando o step `N` é analisado, `real_responses/` já contém as
respostas dos steps `< N` **desta execução** — é o que torna a porta de §3.7 calculável no
lugar certo. Em `--mode dry`, `_persist_response_step` é no-op (`DryEngine`) e
`real_responses/` fica vazio, o que define o comportamento da porta nesse modo.

### `TokenTracker.analyze_step` — `har_reproducer/tracking/token_tracker.py:24-40`

Orquestra a análise de um step: diff contra o baseline, resolução dos candidatos,
aplicação de placeholders, geração do curl. É quem tem o `step.request` em mãos — por isso
é o lugar natural para alimentar o vocabulário do fluxo (§3.2).

### `CurlGenerator._token_comments` / `CurlTokenComment` — `reproduction/curl_generator.py:61-71`, `replay/curl_token_comment.py`

Emitem uma linha de dependência por token com origem e uma linha `[Unresolved N]` com os
paths sem origem. `CurlTokenComment.DEPENDENCY_PATTERN` (`:26-31`) é o que
`ReplayRunner.compute_smart_schedule` usa para achar âncoras — a categoria nova de §3.12
**não** pode casar com esse padrão.

### `ReplayTokenResolver` — `har_reproducer/replay/replay_token_resolver.py:47-82, 95-106`

```python
if origin_step in schedule:
    override_dir: Path = replay_run_dir
else:
    override_dir = self._reference_dir_for_step(origin_step, res_refer_dir, original_responses_dir)
```

⚠️ É a razão de §3.7 ser porta e não etiqueta: **fora do schedule, o extrator lê a resposta
congelada** e devolve o mesmo valor que um literal devolveria. Ou a aresta ancora (e paga
um custo que não se justifica), ou o extrator não faz diferença nenhuma.

`_fallback_to_captured` (`:69-82`) é o comportamento que §3.11 traz para o `run`.
`_record_observation` (`:95-106`) já acumula observações por token e o `ReplayRunner` já
anota `probably static` no `.curl.sh` depois de 5 observações iguais — **e nada consome
essa anotação**. É o mesmo sinal da porta com mais amostras, e o precedente que justifica
a porta agir em vez de só rotular.

### `AgentFactory.create` / `BaseAgent.run_tdd_loop` — `agents/construction/agent_factory.py:42-63`, `agents/base_agent.py`

`create` monta o agente pela `origin_location` e passa `expected_value=candidate.current_value`
(`:48`). `run_tdd_loop` gera código, executa contra a resposta de amostra e só aceita
quando a saída bate exatamente com `expected_value`. O par (valor esperado, resposta de
verificação) tem que ser da mesma época — daí §3.6 e §3.9.

### `TokenLocationDetector.find` — `tracking/token_location_detector.py:12-30`

Decide a `TokenLocation` procurando o valor em cookies → headers → `redirect_url` → body, e
é quem escolhe o agente. Medido para o JWT: `BODY_JSON` com a resposta da época do HAR;
`None` com a da execução — outra razão de a descoberta ficar na época do HAR.

---

## 3. Decisões de arquitetura

### 3.1 — `FragmentMatcher`: maior substring comum, podada pela cobertura

**Componente novo**, `har_reproducer/tracking/fragment_matcher.py`, sem estado: dado o
valor do candidato e um texto pesquisável, devolve o maior pedaço contíguo que os dois
compartilham, ou `None`.

**Estado atual:** não existe; só há o teste de contenção do valor inteiro.

**Estado esperado:** um método `longest_common(value, text) -> Optional[Tuple[str, int]]`
(fragmento e deslocamento dentro do valor), com esta mecânica:

1. `k_min = ceil(MIN_COVERAGE * len(value))`, limitado a `len(value) - 1` (fragmento igual
   ao valor inteiro é caso do passe anterior).
2. Se nenhum pedaço de tamanho `k_min` do valor está no texto, devolve `None`
   imediatamente. Este teste é a poda: descarta o caso comum antes de qualquer busca.
3. Senão, busca binária em `[k_min, len(value) - 1]` pelo maior `k` que ainda tem um
   pedaço presente, testando os `len(value) - k + 1` pedaços de cada tamanho com
   contenção de string.
4. Devolve o maior pedaço encontrado e seu deslocamento.

⚠️ **A poda por cobertura não é uma otimização opcional — é o que torna o critério de
§3.3 exequível.** Sem `k_min`, a busca binária começa em 1 e o passe fica caro sem
necessidade: medido, 15,5 s contra 8,1 s no fluxo completo, para o mesmo resultado.

⚠️ **Sem `ValueVariants` no passe de fragmento.** Ele roda só sobre o valor cru, por motivo
estrutural: o fragmento precisa ser substring do valor **como ele aparece no request**,
senão `PlaceholderApplier` não consegue substituí-lo.

**Alternativa descartada: âncora fixa de tamanho.** A versão anterior deste desenho usava
uma âncora `valor[16:32]` com expansão maximal e piso absoluto de 32 caracteres. É mais
rápida (2,2 s), mas o piso absoluto rejeita toda classe de token curto cuja origem só
aparece parcialmente — `'csrf=a1b2c3d4'` com a resposta trazendo `'a1b2c3d4'` (cobertura
62%) seria descartado. Cobertura entrega o mesmo efeito de forma proporcional, e a poda
recupera boa parte do custo.

### 3.2 — `FlowVocabulary`: hosts e origins observados no próprio fluxo

**Componente novo**, `har_reproducer/tracking/flow_vocabulary.py`, com estado acumulado.

**Estado atual:** não existe. Nada no código sabe quais são os endereços do site.

**Estado esperado:** uma coleção que observa a URL de cada request analisado e acumula, de
cada uma, `hostname`, `netloc` e `esquema://netloc`. Expõe `contains(fragment) -> bool`,
verdadeiro quando o fragmento está **contido** em algum desses valores.

- Alimentado por `TokenTracker.analyze_step`, com a URL do step corrente, **antes** de
  resolver os candidatos daquele step.
- Acumulação causal: só entram endereços de steps já processados. Medido, o resultado é
  idêntico ao de derivar o conjunto do HAR inteiro de antemão (mesmas 58 rejeições, mesmo
  extrator final), e evita um segundo parse do `.har` de 5 MB.

⚠️ **A direção da contenção importa.** A regra rejeita quando `fragmento ⊆ endereço`,
nunca quando `endereço ⊆ fragmento`. Um token legítimo pode conter o endereço do site
(`https://site/callback?token=XYZ`); rejeitá-lo por isso seria um falso negativo.

Isso é o oposto de hardcode: nenhum host é conhecido pelo código: o conjunto sai da
gravação, como toda a evidência deste projeto.

### 3.3 — Três critérios de admissão do fragmento

**Estado atual:** não se aplica — não há fragmento.

**Estado esperado:** um fragmento só é aceito como origem se passar nos três:

| critério | regra | por quê |
|---|---|---|
| **cobertura** | `len(fragmento) / len(valor) >= MIN_COVERAGE` (0.5) | a resposta tem que explicar a maior parte do valor; o que sobra é afixo, não a metade desconhecida |
| **ubiquidade** | fração das respostas do corpus de descoberta que contêm o fragmento `< MAX_UBIQUITY` (0.5) | texto presente em metade das respostas não é evidência de origem, é vocabulário |
| **vocabulário do fluxo** | `not FlowVocabulary.contains(fragmento)` | fragmento que é o endereço do próprio site não é token |

Os três são constantes de classe (`ClassVar`), não configuração de `config.json`.

**Por que três, e não um piso de tamanho.** Medido no cenário sem filtro nenhum (923
origens de fragmento), a porta de época sozinha deixa passar 19 extratores, dos quais 18
são falsos positivos — e **16 deles são vocabulário de HTTP**: `'control'` (presente em
318 das 321 respostas, com 15 steps de origem distintos), `'da'` (320/321), além de
`'/'`, `'*/'`, `'ht'`, `'.js'`, `'age'` antes da porta. A porta é cega para essa classe:
`'control'` vem do nome do header `cache-control`, e "mudou entre as épocas" só porque em
alguns steps esse header existe numa época e não na outra.

**Efeito medido de cada critério neste fluxo** (322 valores-ocorrência que chegam ao passe
de fragmento):

```
739  descartados pela cobertura (poda do FragmentMatcher)
 58  rejeitados pelo vocabulário do fluxo
  0  rejeitados pela ubiquidade
205  admitidos  -> 200 origens distintas -> 1 sobrevive à porta de época
```

⚠️ **A ubiquidade não dispara neste fluxo** — a cobertura já mata todo fragmento de baixa
entropia daqui (`'control'` tem cobertura 12%). Ela fica porque cobre uma classe que a
cobertura não alcança: valor curto que é ele próprio vocabulário, como
`'cache-control'` casando `'control'` (cobertura 54%, ubiquidade 99%). É defesa
declarada, não critério medido — está registrado em §6 como o candidato a corte se o
plano precisar encolher.

⚠️ **Com 18 falsos positivos num fluxo só, a medição não distingue entre filtros.** Vários
zeram a coluna: piso 24, piso 32, ubiquidade < 2%, cobertura ≥ 80%. A escolha aqui é por
justificativa semântica — cobertura e ubiquidade dizem algo sobre a evidência, um piso
absoluto diz só "coube nesta gravação". O que a medição estabelece é o mínimo: qualquer
critério adotado tem que zerar essa coluna.

### 3.4 — `OriginFinder`: passe de fragmento depois do passe de valor inteiro

**Estado atual:** `find` devolve o primeiro step elegível cujo texto contém o valor
inteiro (testando as variantes de encoding), ou `None`.

**Estado esperado:** idem; se `None`, e **na mesma chamada**, percorre todos os steps
elegíveis aplicando `FragmentMatcher` ao valor cru e devolve um `OriginMatch` com o
fragmento preenchido, ou `None`.

Regras:

1. **Desempate: maior fragmento; em empate, o step mais antigo.** Diferente do passe de
   valor inteiro, onde todos os steps que casam trazem a mesma evidência, aqui a evidência
   **é** o tamanho do pedaço; entre pedaços de mesmo tamanho, o step mais antigo mantém a
   reutilização do extrator estável entre execuções.
2. Os três critérios de §3.3 são aplicados ao candidato a fragmento; se algum reprovar, o
   resultado é `None` (equivale a não ter achado origem).
3. **`origin_key` calculado sobre o texto casado**, não sobre o valor inteiro. Neste fluxo
   o fragmento do JWT mora no body e o resultado é `origin_key=None`, medido.
4. **Custo:** medido no fluxo completo (324 steps, corpus de 4,16M chars), a descoberta
   passa de **1,84 s para 8,1 s** — 6,4 s no `FragmentMatcher` e 0,1 s nos critérios —
   contra um `run --mode main` de 2m24s. É +4% do tempo de parede do comando.

### 3.5 — Cache positivo só para casamento de valor inteiro

**Estado atual:** `_find_origin` grava todo `OriginMatch` em `self._origin_cache[value]`, e
o valor nunca mais é procurado.

**Estado esperado:** só o casamento de **valor inteiro** entra no cache positivo. Um
casamento por fragmento é devolvido e usado para aquele step, mas o valor continua no
cache de negativos com janela (`_origin_misses[value] = step_index`), de modo que as
ocorrências seguintes reprocessem a busca.

**Por quê.** A busca de origem é causal — só olha respostas de steps anteriores ao step que
usa o valor. Um fragmento é, portanto, a melhor resposta *naquele ponto do fluxo*, não a
melhor resposta possível. Rastro medido de `header:Origin = 'http://127.0.0.1:8080'` (266
ocorrências):

```
1ª ocorrência ............ step 6, janela de busca = steps [0, 6), 6 respostas
valor inteiro na janela? . NÃO
maior substring ......... 'http://' (7 chars), step 1
valor inteiro existe a partir do step 75 (header access-control-allow-origin)
```

Com o cache atual, `'http://'` seria gravado no step 6 e o casamento inteiro do step 75
**nunca aconteceria** — medido: 14 origens inteiras em vez de 15. Com a mudança, as 204
ocorrências a partir do step 75 casam o valor inteiro corretamente.

⚠️ **Esta mudança e os critérios de §3.3 são complementares, não alternativas.** Medido:
parar de cachear fragmento **sem** os critérios explode de 92 para 923 origens de
fragmento e de 1 para 19 extratores; aplicar os critérios **sem** parar de cachear mantém
o erro do `Origin`. As duas juntas: 8,1 s, 15 origens inteiras, 200 fragmentos, 1 extrator.

⚠️ Como o mesmo valor pode receber um fragmento nos steps iniciais e o valor inteiro depois
que a origem verdadeira aparece, dois extratores distintos podem existir para o mesmo
valor em pontos diferentes do fluxo. Isso é correto: cada step recebe a melhor origem
disponível no seu próprio ponto, e é o mesmo comportamento que já existe hoje entre um
step que deu miss (literal) e um step posterior que casou (extrator).

### 3.6 — Descoberta e verificação na época do HAR; execução na época corrente

**Estado atual** (`engine_factory.py:70-83`): um diretório só, escolhido pelo modo, serve
descoberta e execução.

**Estado esperado:** dois papéis explícitos.

```python
discovery_responses_dir: Path = self.workspace.original_responses          # sempre a época do HAR
execution_responses_dir: Path = (
    self.workspace.real_responses if engine_cls.USES_NETWORK else self.workspace.original_responses
)
```

O `CandidateResolver` recebe **os dois** corpora: o de descoberta (usado por
`OriginFinder`, `TokenLocationDetector`, pela verificação do agente e pela identidade de
slot) e o de execução (usado **só** pela porta de §3.7). O `TokenResolver` continua
recebendo o diretório de execução.

**Por que essa é a única pareação com significado.** O valor procurado vem do request
gravado no HAR; não existe "o valor de agora" de um campo de request antes de a requisição
ser montada. A comparação atual em `--mode main` é (valor do HAR, resposta de agora), que
só funciona para valor estável entre épocas — exatamente o que a porta agora rejeita de
propósito. Para o JWT, os dois valores diferem nos dígitos do `exp` e compartilham 123
caracteres de prefixo; sem a troca de época, o fragmento encontrado seria esse prefixo
comum, e a reconstrução montaria prefixo fresco + assinatura velha, que nenhum servidor
aceita.

Consequência medida: a troca é **neutra para a descoberta** — mesmos 15 pares com origem,
mesmos steps de origem, sobre os dois corpora.

⚠️ Renomear `CandidateResolver.response_corpus` para `discovery_corpus` faz parte da
mudança: o nome atual não distingue os dois papéis, e é o mal-entendido que produziu o
defeito. `tests/unit/test_engine_factory.py` afirma o casamento antigo e muda junto.

### 3.7 — Porta de admissão: só vira extrator o que mudou entre as épocas

**Estado atual:** todo candidato com origem encontrada vira extrator (ou literal, quando a
`TokenLocation` não é determinada).

**Estado esperado:** depois de achar a origem e **antes** de procurar o slot, o
`CandidateResolver` consulta o corpus de execução no mesmo step de origem:

| situação | veredito |
|---|---|
| o texto casado **não** aparece na resposta da execução | **mudou** → segue para o slot e gera extrator |
| o texto casado aparece igual nas duas | **estático** → não cria extrator; valor fica literal, e o candidato é registrado (§3.12) |
| a resposta da execução não existe ou está vazia | **indeterminado** → não cria extrator; registrado igual |
| `--mode dry` (não há corpus de execução) | **porta não se aplica** → comportamento de hoje |

Números desta decisão, medidos: 15 casamentos inteiros e 200 fragmentos entram, **1
extrator sai** — `header:Authorization`, origem no step 153. O workspace vai de 17
extratores e 254 linhas de dependência para 1 extrator e 13 linhas, e de 8 âncoras para 1.

⚠️ **`--mode dry` fica sem porta, e isso é deliberado.** Em dry, `real_responses/` tem 0
arquivos. Sem segunda observação não há como provar que algo é estático, e a porta
significa "provado estático, pula". A alternativa (fail-closed) zeraria os extratores em
dry, inclusive o `Authorization`, que é o objetivo desta etapa.

⚠️ **A porta é uma amostra de duas observações.** Um valor genuinamente dinâmico que veio
igual nas duas fica literal e quebra no dia em que mudar. O caso conhecido é requisição
condicional: `ETag` idêntico entre as épocas em 285/285 casos e `Last-Modified` em
292/296 neste workspace — eles mudam no deploy, não entre duas execuções separadas por
minutos. É o custo declarado desta decisão, e é o que a redescoberta reativa (fora de
escopo, §1.4) existe para resolver. O registro de §3.12 é o que torna esse caso
diagnosticável por `grep` em vez de virar mistério.

⚠️ **Terceiro caso, real:** um valor extraído de um header de resposta que **não existe**
na época da execução. Pela regra de texto, "não aparece" = "mudou", então a porta o admite
e o extrator falha em todo replay. O fallback de §3.11 degrada isso para o literal, com
aviso — é uma das razões de §3.11 não ser opcional.

### 3.8 — Peça restante: enriquece o diagnóstico, nunca veta o token

**Estado atual:** não se aplica.

**Estado esperado:** admitido um fragmento, o prefixo e o sufixo que sobram são procurados
**literalmente** (contenção do texto inteiro, sem fragmento) no corpus de descoberta, na
mesma janela.

- Peça encontrada e **idêntica** entre as épocas → fica literal no `.curl.sh`. Nada a
  fazer; é o caso normal de afixo.
- Peça **não** encontrada → fica literal no `.curl.sh`. **Não descarta o token.**
- Peça encontrada e **diferente** entre as épocas → fica literal, e o `.curl.sh` recebe um
  aviso identificando a peça e o step de origem: está sendo congelado algo que se provou
  dinâmico.

⚠️ **Por que a peça restante não pode ser veto.** A versão anterior deste desenho
descartava o token quando alguma peça não tinha origem literal. Medido, o afixo `'Bearer '`
só tem origem porque o JavaScript do cliente é servido como resposta e contém
`` headers['Authorization'] = `Bearer ${token}` `` (steps 23, 100 e 174). Contrafactual no
mesmo corpus: com `'bearer '`, `'JWT '`, `'Bearer: '` ou `'AUTH '` no lugar, nenhuma peça
teria origem e **o JWT seria descartado** — o token que motiva esta etapa dependeria de uma
coincidência de bundle. Como filtro, a regra também não entrega nada: medido, ela e a porta
de época produzem o mesmo extrator único, e a porta sozinha já rejeita tudo que a regra
rejeitaria.

⚠️ O afixo nunca entra no código do extrator: ele fica literal no `.curl.sh`. A alternativa
(extrator devolvendo `'Bearer ' + valor`) foi descartada — assa no extrator um pedaço que é
do request, não da resposta, e desalinha o `captured_value`.

### 3.9 — `OriginMatch.fragment`, `DynamicToken.origin_fragment` e `extracted_value`

```python
class OriginMatch(BaseModel):            # models/analysis.py:8-11
    step_index: int
    origin_key: Optional[str] = None
    origin_container: Optional[OriginContainer] = None
    fragment: Optional[str] = None       # None = casou o valor inteiro

class DynamicToken(BaseModel):           # models/session.py:51-61
    ...
    origin_fragment: Optional[str] = None

    @property
    def extracted_value(self) -> str:
        return self.origin_fragment or self.current_value
```

`current_value` continua sendo **o que o request carrega naquele path**; `extracted_value`
é **o que o extrator tem que produzir**. Consumidores que passam a usar a propriedade:

| lugar | hoje | depois |
|---|---|---|
| `CandidateResolver._check_cached_slot` (`:108`) | `cached_value == candidate.current_value` | `== candidate.extracted_value` |
| `CandidateResolver._check_persisted_slot` (`:118`) | `result != candidate.current_value` | `!= candidate.extracted_value` |
| `CandidateResolver._generate_new_extractor` (`:139`) | `TokenLocationDetector.find(candidate.current_value, …)` | `…find(candidate.extracted_value, …)` |
| `CandidateResolver._register_extractor` (`:165`) | `captured_value = candidate.current_value` | `= candidate.extracted_value` |
| `CandidateResolver._build_literal_extractor` (`:196`) | `return {candidate.current_value!r}` | `{candidate.extracted_value!r}` |
| `AgentFactory.create` (`:48`) | `expected_value=candidate.current_value` | `=candidate.extracted_value` |
| `PlaceholderApplier._apply_token` / `_ordered_by_value_length` (`:16-32`) | substitui e ordena por `current_value` | por `extracted_value` |
| a porta de §3.7 | — | compara `candidate.extracted_value` contra a resposta da execução |

⚠️ A atribuição de `origin_fragment` acontece em `_process_candidate`, logo depois de
`_find_origin` e **antes** da porta e de `_find_slot` — inclusive quando a origem veio do
cache positivo, senão os steps seguintes substituiriam pelo valor errado.

### 3.10 — `_accept_persisted_slot` deixa de semear o token

**Estado atual:** ao reaproveitar um slot persistido, grava o valor extraído no
`SessionStore` (`candidate_resolver.py:129`). Como o corpus era o da execução, o valor
semeado era o fresco — certo por acidente.

**Estado esperado:** a linha `self.session_store.set_token(slot_id, result)` sai. O registro
em `state.registry` e o cache `_validated_values` continuam (identidade de slot, época do
HAR); quem semeia valor é `TokenResolver.resolve_all()`, que roda em seguida
(`engine.py:87`) lendo a época da execução.

Sem isso, o token da época do HAR entraria no `SessionStore` e nunca seria atualizado
(`resolve_all` pula token já presente em `state.tokens`) — o `Authorization` congelado de
novo, por outro caminho.

⚠️ Nada dentro de `analyze_step` consome `state.tokens`: `PlaceholderApplier` olha o
`registry`, e a renderização só acontece em `Engine._attempt_step`.

### 3.11 — `TokenResolver`: fallback para `captured_value` quando a extração falha

**Estado atual:** `_refresh_token` desiste em silêncio e o token fica sem valor — o request
sai com `{{extractor:…}}` literal dentro do header.

**Estado esperado:** ao desistir, usar `extractor.captured_value` com aviso no stdout — o
mesmo que `ReplayTokenResolver._fallback_to_captured` já faz no `replay`. Sem
`captured_value`, mantém o comportamento atual.

É rede de segurança para as duas classes que esta etapa passa a permitir criar: extrator
verificado numa época e executado em outra (§3.6) e o terceiro caso da porta (§3.7).

### 3.12 — Registrar no `.curl.sh` o que a porta dispensou

Sem registro, a informação "havia origem, mas o valor não muda" morre — e ela é o insumo
da redescoberta reativa e da investigação humana.

**Estado atual:** `CurlGenerator._token_comments` emite uma linha de dependência por token
com origem e uma linha `[Unresolved N]` com os paths sem origem.

**Estado esperado:** duas categorias novas, ambas informativas:

- candidatos dispensados pela porta, com o step de origem preservado — algo como
  `# [Static 2] header:Content-Type←0023; header:Origin←0075`;
- peças restantes congeladas apesar de mudarem entre as épocas (§3.8) — algo como
  `# [Frozen 1] header:Authorization prefix 'Bearer '←0023`.

⚠️ Nenhuma das duas pode casar com `CurlTokenComment.DEPENDENCY_PATTERN`: esse padrão é o
que `compute_smart_schedule` usa para achar âncoras, e categoria informativa **não** pode
virar âncora. O teste tem que afirmar isso explicitamente.

### 3.13 — Os fixtures precisam divergir entre as épocas

Consequência mais pesada da porta, e a maior parte do trabalho desta etapa: hoje o servidor
canned devolve exatamente os mesmos valores que o HAR sintético gravou
(`tests/support/canned_http_handler.py:11-39`, um dicionário `(método, path) → CannedResponse`
fixo, e `tests/fixtures/synthetic_flow.har`, 10 entries). Com a porta, **o cenário
`run_main` passa a produzir 0 extratores**, e a rede de caracterização de todo o pipeline
de descoberta (agentes, extratores, placeholders, comentários de dependência) apaga junto.

**Estado esperado:**

- Os valores que devem continuar dinâmicos passam a **divergir de forma determinística**
  entre o HAR e o servidor canned. Os valores canned de hoje são `SESSIONID=abc123sess`,
  `tok_CSS_1`, `scr_NONCE_2`, `4242`, `PLAINVAL777`, `PREFS=xyz789` — a divergência é do
  tipo "o HAR gravou `abc123sess`, o servidor devolve `abc123live`". Isso é mais fiel ao
  mundo real (token de sessão muda a cada execução) e mantém a cobertura de
  `CookieAgent`/`CSSAgent`/`JSONPathAgent`/`RegexAgent`/`HeaderAgent`.
- **Fixture novo** (`tests/fixtures/auth_flow.har`) para a classe desta etapa: um `POST` de
  login cuja resposta é `{"token": "<TOKEN_DO_HAR>"}`, um `GET` seguinte com
  `Authorization: Bearer <TOKEN_DO_HAR>`, e endpoints canned que devolvem sempre
  `{"token": "<TOKEN_VIVO>"}` (≠ `<TOKEN_DO_HAR>`, ambos longos o bastante para a cobertura
  mínima) e respondem `200` no recurso protegido **só** com `Bearer <TOKEN_VIVO>`, `403`
  caso contrário. É o teste que falha hoje (literal do HAR → `403`) e passa depois.
- **Fixture novo de fragmento espúrio**: um valor curto e ubíquo que muda entre as épocas
  (a classe `'control'` de §3.3), para garantir que os critérios o rejeitam. Sem ele, os
  três critérios ficam sem teste que os justifique.

⚠️ São 27 cenários golden. Os de `--mode dry` não mudam por causa da porta (ela não se
aplica lá), mas mudam por causa dos valores novos do fixture; os de rede (`run_main`,
`replay_*`) são regerados. Isso é regeneração esperada, não regressão — mas o plano tem que
declarar, cenário por cenário, o que mudou e por quê.

### 3.14 — O que explicitamente **não** muda

- **`replay` e `optimize`.** `ReplayTokenResolver` já resolve pela resposta do replay quando
  a origem está no schedule, e `compute_smart_schedule` já lê as linhas de dependência. A
  aresta nova entra sozinha nos dois; as arestas removidas saem sozinhas. Nenhum ajuste de
  `--max-requests` faz parte desta etapa.
- **`ValueVariants`, `ResponseCorpus`, `BaselineDiff`, os agentes.** Nenhum muda. O agente
  que resolve o JWT é o `JSONPathAgent` existente, com `data['token']`.
- **`config.json`.** `MIN_COVERAGE`, `MAX_UBIQUITY` e o vocabulário do fluxo são internos.

---

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `tracking/fragment_matcher.py` → `FragmentMatcher` | **novo**: maior substring comum entre valor e texto, podada por `MIN_COVERAGE` (§3.1) |
| `tracking/flow_vocabulary.py` → `FlowVocabulary` | **novo**: acumula hosts/origins dos requests já analisados; `contains(fragment)` (§3.2) |
| `tracking/origin_finder.py` → `OriginFinder` | passe de fragmento após o de valor inteiro, na mesma chamada; três critérios de admissão; desempate por maior fragmento e step mais antigo; `_origin_key` sobre o texto casado (§3.3, §3.4) |
| `models/analysis.py` → `OriginMatch` | campo `fragment` (§3.9) |
| `models/session.py` → `DynamicToken` | campo `origin_fragment` + propriedade `extracted_value` (§3.9) |
| `tracking/candidate_resolver.py` → `CandidateResolver` | recebe corpus de descoberta **e** de execução; cache positivo só para valor inteiro; **porta de admissão**; propaga o fragmento; usa `extracted_value`; busca das peças restantes; `_accept_persisted_slot` deixa de semear (§3.5–§3.10) |
| `tracking/token_tracker.py` → `TokenTracker` | alimenta o `FlowVocabulary` com a URL do step antes de resolver os candidatos (§3.2) |
| `tracking/placeholder_applier.py` → `PlaceholderApplier` | substitui e ordena por `extracted_value` (§3.9) |
| `agents/construction/agent_factory.py` → `AgentFactory` | `expected_value=candidate.extracted_value` (§3.9) |
| `tracking/token_resolver.py` → `TokenResolver` | fallback para `captured_value` com aviso (§3.11) |
| `engines/construction/engine_factory.py` → `EngineFactory` | separa `discovery_responses_dir` de `execution_responses_dir`; passa os dois corpora ao resolver (§3.6) |
| `replay/curl_token_comment.py` → `CurlTokenComment` + `CurlGenerator` | duas categorias informativas novas, nenhuma casando com `DEPENDENCY_PATTERN` (§3.12) |
| `tests/support/canned_http_handler.py`, `tests/fixtures/synthetic_flow.har`, `tests/fixtures/auth_flow.har` | valores dinâmicos divergem entre HAR e servidor canned; fixture de autenticação; fixture de fragmento espúrio (§3.13) |
| golden de `run_main` e `replay_*`; `tests/unit/test_engine_factory.py`, `test_candidate_resolver.py`, `test_origin_finder.py`, `test_token_resolver.py`, `test_placeholder_applier.py`, `test_curl_generator.py`, `test_curl_token_comment.py`, `tests/support/recording_origin_finder.py` | regeneração e acompanhamento de assinatura |

---

## 5. Casos de borda e comportamento de erro

**5.1 Fragmento admitido com `TokenLocation` indeterminada.** Vira `LiteralAgent` com o
**fragmento** como literal — mesmo comportamento que o valor inteiro já tem hoje. Sob a
porta, esse caminho só é alcançado por valor que muda entre observações.

**5.2 Fragmento maximal que "vaza" além do token.** A expansão é maximal e pode incluir um
caractere vizinho compartilhado por acaso; o agente não consegue extrair exatamente aquele
texto, o laço TDD esgota e cai em `LITERAL_FALLBACK` com o fragmento. Não observado neste
fluxo.

**5.3 O fragmento de um token aparece dentro do valor de outro candidato.**
`PlaceholderApplier` substitui todas as ocorrências, então o placeholder de um token pode
aparecer dentro do header de outro — é o `-H 'Referer: {{extractor:…}}/'` que já existe
hoje. O fragmento herda a borda sem alargá-la. Fora de escopo.

**5.4 Extração falha na época da execução.** Cai para `captured_value` com aviso (§3.11); o
request sai com o literal, nunca com `{{extractor:…}}` cru.

**5.5 Origem existe só na época da execução.** Deixa de ser encontrada, porque o corpus de
descoberta muda de época. Medido: 0 pares nessa situação neste fluxo.

**5.6 Steps pulados como origem.** `original_responses/` guarda a resposta gravada no HAR
também para os steps pulados, enquanto `real_responses/` guarda `status_code=0` sem corpo.
A porta trata isso como **indeterminado** e não cria extrator — o que elimina de lambuja a
classe "extrator cuja origem o replay nunca executa". Neste HAR são 4 steps pulados (81,
155, 240, 251, todos `ws://`).

**5.7 `--mode dry`.** Sem porta. O `Authorization` passa a ter aresta e extrator resolvendo
para o valor do próprio HAR — correto: o dry não tem outra época para consultar.

**5.8 Valor menor que o mínimo de cobertura.** `k_min = ceil(0.5 * len(valor))` é sempre ≥ 1
e limitado a `len(valor) - 1`. Para um valor de 1 caractere não há fragmento possível e o
matcher devolve `None` sem entrar na busca.

**5.9 Workspaces gerados antes desta etapa.** Continuam com as arestas antigas; `replay` e
`optimize` sobre eles seguem como hoje. Não há migração — é preciso rodar `run` de novo.

**5.10 Custo.** Descoberta de 1,84 s para 8,1 s no fluxo de 324 steps, contra um `run` de
2m24s. A memória não muda de classe, mas **dois** `ResponseCorpus` ficam memoizados por
execução em vez de um. A ubiquidade é memoizada por fragmento.

**5.11 Um valor genuinamente dinâmico que veio igual nas duas observações.** A porta o deixa
literal e ele quebra no dia em que mudar (§3.7). É o custo declarado desta etapa, e §3.12 é
o que o torna diagnosticável em vez de virar mistério.

O que decide se um valor cai nessa armadilha é a **granularidade temporal** dele comparada
ao intervalo entre as duas observações. Medido contra o servidor de autenticação em
20/08/2026: o JWT é função de `(payload, exp)`, e `exp` tem granularidade de segundo — dois
logins dentro do **mesmo segundo** devolvem o token byte a byte idêntico (3 logins imediatos
→ 2 tokens distintos); separados por mais de um segundo, sempre distintos (3 logins → 3
tokens). As duas épocas desta etapa estão separadas por dias, então a porta vê o JWT como
"mudou" com folga. No outro extremo estão `ETag` e `Last-Modified`, que mudam no deploy e
não entre duas execuções separadas por minutos: medidos idênticos entre as épocas em 285/285
e 292/296 casos neste workspace.

⚠️ A conclusão de projeto é que "dinâmico" não é propriedade do valor, e sim da relação
entre a taxa de mudança dele e o intervalo entre as observações. A porta mede exatamente
isso, e não mais do que isso.

---

## 6. Suposições e pontos a confirmar

- **`MIN_COVERAGE = 0.5` e `MAX_UBIQUITY = 0.5`.** Confirmados por medição neste fluxo, que
  não distingue entre eles e várias alternativas (§3.3). São `ClassVar`, não configuração.
- **A ubiquidade é o critério cortável.** Ela rejeita 0 fragmentos neste fluxo; cobertura e
  vocabulário do fluxo já zeram os falsos positivos sozinhos. Fica porque cobre uma classe
  que a cobertura não alcança, mas é o primeiro item a sair se o plano precisar encolher.
- **Nomes** (`FragmentMatcher`, `FlowVocabulary`, `MIN_COVERAGE`, `MAX_UBIQUITY`,
  `OriginMatch.fragment`, `DynamicToken.origin_fragment`, `extracted_value`,
  `discovery_corpus`) — ajustáveis.
- **Texto e formato das linhas de §3.12** (`[Static N]`, `[Frozen N]`, a seta `path←step`) —
  ajustáveis. **Não** é ajustável a garantia de que elas não casem com `DEPENDENCY_PATTERN`.
- **Renomear `response_corpus` → `discovery_corpus`** custa churn em teste; confirmar se
  entra aqui.
- **Formato dos fixtures de §3.13** (quais valores divergem, quantas entries no
  `auth_flow.har`) — proposta na decisão; a exigência dura é divergência determinística e
  recurso protegido que só aceita o token vivo.
- **Peça restante virar um segundo extrator** está fora (§1.4, §3.8). Se a preferência for
  incluir agora, `CandidateResolver.resolve` passa a poder devolver mais tokens do que
  recebeu candidatos, e `PlaceholderApplier`/`CurlGenerator` já suportam isso por
  iterarem sobre a lista — mas o plano cresce sem caso medido que o justifique.

---

## 7. Referência

Toda alteração de código desta spec segue o padrão descrito em [[guia-de-estilo]]
(`.claude/skills/guia-de-estilo`). As decisões respeitam o princípio de genericidade de
[[arquitetura-e-fundamentos]]: `Bearer ` não é conhecido pelo código em lugar nenhum,
nenhum host é hardcoded (o vocabulário do fluxo sai da própria gravação), e o critério de
"dinâmico" deixa de ser aparência — formato, tamanho, nome de header — e passa a ser
**evidência observada**: o valor mudou de uma execução para outra.
