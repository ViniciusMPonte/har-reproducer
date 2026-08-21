# Spec — Porta de Admissão por Mudança entre Épocas

## 0. Sumário

O header `Authorization: Bearer <JWT>` nunca é modelado como token dinâmico: fica congelado
como literal em 13 dos 320 `.curl.sh` deste fluxo, porque a busca de origem exige que o
valor inteiro apareça numa resposta anterior, e o request manda `Bearer <jwt>` enquanto a
resposta do login traz só `{"token":"<jwt>"}`. Esta etapa ensina o projeto a aceitar como
origem o maior pedaço contíguo comum entre o valor e a resposta (o "fragmento"), e a
admitir esse fragmento — ou um casamento inteiro — como extrator **só quando há evidência
de que o valor muda** entre a resposta gravada no `.har` e a resposta obtida agora. Sem
essa segunda condição, o mecanismo de fragmento sozinho criaria extrator para qualquer
pedaço de URL, header de cache ou trecho de HTML que coincidisse por acaso — e mediu-se
que isso realmente aconteceria.

Esta é a terceira e última etapa de uma investigação que começou em 20/08/2026
(`docs/20260820 Investigação da Porta de Admissão/`). As duas primeiras já foram
implementadas e mergeadas: extrator literal não vira mais âncora do `replay --mode smart`
(89–97% do ganho que esta investigação media, sem precisar de nada do que vem abaixo), e o
corpo de resposta comprimido não é mais persistido como mojibake (pré-requisito de qualquer
comparação entre duas respostas). As duas mudaram os números que a investigação original
media, e todo número deste documento foi **remedido depois das duas**, sobre workspaces
regravados com o código atual.

### Glossário

| termo | significado nesta spec |
|---|---|
| **época do HAR / época da execução** | A resposta gravada no `.har` original (`original_responses/`) versus a resposta obtida ao reproduzir o fluxo agora (`real_responses/`). |
| **candidato** | Par `(path, valor)` que o `BaselineDiff` marca como possivelmente dinâmico. |
| **origem** | Step anterior cuja resposta contém o texto de um candidato. |
| **casamento inteiro** | Origem encontrada porque a resposta contém o valor do candidato por completo — o único mecanismo que existe hoje. |
| **fragmento** | Maior pedaço contíguo do valor que uma resposta contém, quando ela não contém o valor inteiro. |
| **cobertura** | `len(fragmento) / len(valor)`. Também é o limite de poda da busca do fragmento — não é um terceiro critério independente (medido, §3.2). |
| **texto casado** | O texto que efetivamente casou — o valor inteiro, ou o fragmento. É sobre ele, não sobre o valor do candidato, que a porta e os demais critérios operam. |
| **porta de admissão** | Regra final: só vira extrator o texto casado que **difere** entre as duas épocas no mesmo blob do step de origem. Requisição condicional (que normalmente não difere) é uma decisão de escopo separada, aberta em §3.8. |
| **container** | Onde dentro da resposta o texto casado foi localizado: um header nomeado, um cookie nomeado, a `redirect_url`, ou o corpo sem localização mais fina. |
| **vocabulário do fluxo** | Conjunto de hosts e origins (`host`, `host:porta`, `esquema://host:porta`) observados nos requests do próprio HAR, condicionado à ordem de aparição (§3.6). |
| **âncora** | Step de origem citado numa linha de dependência **recalculável** de um `.curl.sh` (`CurlTokenComment.parse_anchors`, já em produção desde a etapa anterior). Puxada para o schedule do `replay --mode smart`. |

Todos os números têm procedência declarada em `medições.md`, nesta mesma pasta.

---

## 1. Objetivo

### 1.1 O problema, medido agora

Workspace `arquivos-har/ws_atual_pos_correcoes` — HAR de 324 entries, regravado com o
código atual (pós itens 9 e 10), em 21/08/2026:

```
curls com Authorization literal (Bearer eyJ...) ......... 13
curls com Authorization dinâmico ({{extractor:...}}) .....  0
linhas de dependência que citam o step 153 (o login) .....  0
extratores no workspace .................................. 17
linhas de dependência totais ............................. 254
```

`OriginFinder.find` exige o valor **inteiro**: o request manda `Bearer <jwt>` (180
caracteres); a resposta do login (step 153) traz `{"token":"<jwt>"}` — só o JWT, 173
caracteres. `find('Bearer eyJ…', 0, 224)` devolve `None`; `find('eyJ…', 0, 224)` (só o JWT)
devolve `step_index=153`. O JWT não expira em breve (`exp` medido agora: 13/02/2027), então
o sintoma não é "o fluxo está quebrado hoje" — é "o fluxo quebra no dia em que expirar, sem
aviso, porque a ferramenta nunca aprendeu a renovar esse valor".

### 1.2 O que aconteceria sem a porta, medido

Aceitar fragmento sem nenhuma condição adicional cria extrator para qualquer coincidência.
Simulação sobre o mesmo workspace, sem porta: 47 origens distintas de fragmento, das quais
só uma é o JWT — as outras 46 são pedaços de URL de asset estático (`/src/assets/...`,
60–72% de cobertura), fragmento de header de negociação de conteúdo, etc. Sem uma segunda
condição, **46 extratores desnecessários** seriam criados, cada um virando âncora.

### 1.3 O que esta etapa cobre

1. **Casamento por fragmento** com poda de busca por cobertura mínima (§3.1, §3.2).
2. **Piso mínimo de tamanho, aplicado ao texto casado (inteiro e fragmento)** — não só ao
   fragmento (§3.3).
3. **Vocabulário do fluxo aplicado ao texto casado**, com veto condicionado à ordem de
   aparição, para não recusar subdomínio dinâmico por engano (§3.4).
4. **Porta de admissão** — três veredictos (mudou/estático/indeterminado), sobre o mesmo
   blob de sempre (§3.5).
5. **Descoberta sempre na época do HAR**, execução na época corrente — a única separação de
   corpora que faz sentido, com dois corpora passados ao resolvedor (§3.7).
6. **Consequências obrigatórias da separação de épocas**: parar de semear o token com o
   valor da época do HAR (§3.9), e cair para `captured_value` quando a extração falha na
   execução (§3.10).
7. **Registro do que a porta dispensou**, numa categoria que nunca ancora (§3.11).
8. **Fixtures que divergem entre as épocas**, para o pipeline de descoberta continuar
   coberto (§3.12).

**Decisão tomada (§3.8):** requisição condicional rebaixa a literal, como qualquer outro
valor estático — sem tratamento especial. É uma regressão medida e aceita (custo em §3.8),
coberta pela redescoberta reativa quando ela existir.

### 1.4 O que foi medido e **não** precisa entrar

- **Uma política de cache nova para o fragmento.** A hipótese original da investigação era
  que aceitar fragmento exigiria mudar como `CandidateResolver._find_origin` cacheia
  origens — um fragmento de baixa cobertura poderia "roubar" um casamento inteiro melhor
  que só aparece depois no fluxo. Medido de novo, sobre os dois workspaces regravados,
  comparando três políticas de cache (`descoberta.py --cache {definitivo,misses,provisorio}`
  em `docs/20260820 .../medições/`): o cache que já existe hoje (uma entrada por valor,
  guardada na primeira vez que se acha qualquer origem) dá **exatamente o mesmo resultado**
  que a política mais elaborada considerada, nos dois workspaces. O caso que motivava a
  mudança (`header:Origin`, fragmento `'http://'` de 7 caracteres, cobertura 33%) nunca
  chega a ser cacheado, porque a cobertura mínima de §3.2 o rejeita **antes** — e as 204
  ocorrências desse header continuam casando o valor inteiro, verificado. `_find_origin` e
  `_origin_cache` (`candidate_resolver.py:67-79`) **não mudam.**
- **Redescoberta reativa.** Fora de escopo desde a investigação original — é a etapa que
  cobre o valor genuinamente dinâmico que por acaso veio igual nas duas observações,
  **incluindo requisição condicional** (§3.8): é o caso concreto e medido desta classe, não
  hipotético — 84 extratores do HAR anterior regridem a literal por esta decisão.
- **Segundo HAR para dar duas épocas ao `--mode dry`.** Alinhar duas gravações é
  alinhamento de sequência, não lookup por chave — 110 chaves `(método, url)` distintas
  para 324 entries no HAR atual, 75 repetidas. Fica fora; `--mode dry` continua sem porta.
- **Compor vários extratores parciais para o mesmo valor.** Nos 122 valores distintos do
  fluxo atual, nenhuma peça restante (prefixo/sufixo fora do fragmento) muda entre as
  épocas — a capacidade dispararia zero vezes aqui.
- **`BaselineDiff` comparar contra a primeira entry do HAR**, em vez de contra o step
  anterior ou uma janela — é a causa raiz de excesso de candidato, mas é assunto de outra
  spec.
- **Token curto dentro de valor longo** (`.../items/12345?x=1`, só `12345` dinâmico) —
  nenhum critério desta spec alcança esse caso; é limitação da granularidade do candidato.
- **Gate de LLM** para decidir admissão — a admissão fica determinística.

---

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `OriginFinder` — `har_reproducer/tracking/origin_finder.py` (65 linhas, arquivo inteiro)

```python
def find(self, value: str, from_step_index: int, before_step_index: int) -> Optional[OriginMatch]:
    eligible: List[int] = [
        index for index in self.corpus.eligible_indexes(before_step_index)
        if index >= from_step_index
    ]
    if not eligible:
        return None
    for variant in ValueVariants.of(value):
        match: Optional[OriginMatch] = self._find_variant(eligible, variant, variant == value)
        if match is not None:
            return match
    return None
```

`_find_variant` (`:27-33`) devolve o **primeiro** step elegível cujo texto contém a
variante inteira. `_build_match`/`_origin_key` (`:35-58`) só tentam achar a chave de origem
quando a variante casada é o valor cru (`is_raw`), comparando por **igualdade exata**
contra cookies e depois headers:

```python
def _origin_key(self, step_index: int, variant: str) -> Optional[Tuple[str, OriginContainer]]:
    response: Optional[Dict[str, Any]] = self.corpus.response(step_index)
    if response is None:
        return None
    cookie_key: Optional[str] = self._exact_key(response.get("cookies"), variant)
    if cookie_key is not None:
        return cookie_key, OriginContainer.COOKIE
    header_key: Optional[str] = self._exact_key(response.get("headers"), variant)
    if header_key is not None:
        return header_key, OriginContainer.HEADER
    return None

@staticmethod
def _exact_key(container: Optional[Dict[str, str]], variant: str) -> Optional[str]:
    for name, value in (container or {}).items():
        if value == variant:
            return name
    return None
```

⚠️ **`_exact_key` compara por `==`, não por `in`, e continua assim (3.3, 3.5).** Um
candidato cujo texto casado é uma **substring** de um header ou cookie — não o valor
inteiro dele — tem `origin_container=None`, tratado como corpo não-localizado. Medido: é o
caso de `'u=0'`, achado dentro do header `priority: u=0,i=?0` da resposta do step 76
(workspace `ws_anterior_pos_correcoes`). **Generalizar essa comparação para contenção foi
considerado e descartado** (3.5) — reabre a mesma classe de coincidência que a cobertura
fecha do lado do fragmento, e o piso mínimo (3.3) já mata esse caso específico sem precisar
disso.

### `ResponseCorpus` — `har_reproducer/tracking/response_corpus.py` (89 linhas, arquivo inteiro)

`searchable_text` (`:33-45`) serializa headers, cookies, `redirect_url` e corpo numa string
só, memoizada por step. `response(step_index)` (`:22-30`) devolve o dicionário estruturado
(`{"headers": ..., "cookies": ..., "redirect_url": ..., "body": ...}`), também memoizado.
Não muda — é a mesma classe, sobre dois corpora diferentes (§3.7), e §3.5 usa
`response(step_index)` (o dict estruturado), não `searchable_text` (o blob), para localizar
o container.

### `CandidateResolver` — `har_reproducer/tracking/candidate_resolver.py` (200 linhas)

```python
def _process_candidate(self, candidate: DynamicToken, step_index: int) -> DynamicToken:
    origin: Optional[OriginMatch] = self._find_origin(candidate.current_value, step_index)
    if origin is None:
        candidate.status = "NotFound"
        return candidate
    candidate.origin_step = origin.step_index
    candidate.origin_key = origin.origin_key
    candidate.origin_container = origin.origin_container
    base_token_id: str = self._derive_token_id(candidate.path, candidate.origin_step)
    slot_id, initial_error = self._find_slot(base_token_id, candidate)
    candidate.token_id = slot_id
    if self.session_store.state.registry.get(slot_id) is not None:
        candidate.status = "Resolved"
        return candidate
    return self._generate_new_extractor(candidate, initial_error)
```

```python
def _find_origin(self, value: str, step_index: int) -> Optional[OriginMatch]:
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

⚠️ **Não muda (1.4).** O cache positivo é definitivo por valor, o cache de negativos tem
janela — e, medido, isso já é suficiente sob os critérios de §3.2/§3.3/§3.4.

`_check_persisted_slot` (`:112-122`) roda o extrator persistido contra
`self.response_corpus.responses_dir` e compara com `candidate.current_value`;
`_accept_persisted_slot` (`:124-130`) semeia o token; `_register_extractor` (`:157-170`)
grava `captured_value = candidate.current_value`; `_build_literal_extractor` (`:191-200`)
emite `return {candidate.current_value!r}`. Todos passam a operar sobre
`extracted_value` (§3.10), e `_accept_persisted_slot` deixa de semear (§3.9).

### `TokenResolver` — `har_reproducer/tracking/token_resolver.py` (36 linhas, arquivo inteiro)

```python
def resolve_all(self, force: bool = False) -> None:
    for token_id, extractor in self.session_store.state.registry.items():
        if not force and token_id in self.session_store.state.tokens:
            continue
        if self._should_refresh_token(extractor):
            self._refresh_token(token_id, extractor)

def _refresh_token(self, token_id: str, extractor: Extractor) -> None:
    if not (self.responses_dir / f"res_{extractor.origin_step:04d}.json").exists():
        return
    try:
        value: Optional[str] = self.extractor_runner.run(extractor, self.responses_dir)
    except Exception as e:
        print(f"Failed to refresh token '{token_id}': {e}")
        return
    if value:
        self.session_store.set_token(token_id, value)
```

⚠️ **Token já semeado nunca é atualizado** (`resolve_all`, `:17-18`) — torna §3.9
obrigatória. ⚠️ **Falha deixa o placeholder cru** — `_refresh_token` retorna sem gravar em
dois casos (arquivo ausente, `:26-27`; valor falsy, `:35-36`) e num terceiro relança depois
de logar (exceção, `:31-33`); nos três, se nada semear o token,
`SessionStore._resolve_token_placeholder` devolve o `{{extractor:…}}` cru. Torna §3.10
obrigatória.

### `PlaceholderApplier` — `har_reproducer/tracking/placeholder_applier.py` (80 linhas)

`_apply_token` (`:20-32`) usa `token.current_value` para decidir se substitui e para casar
a substring; `_ordered_by_value_length` (`:16-18`) ordena por `len(token.current_value)`.
Os dois passam a usar `extracted_value` (§3.10). A mecânica de substituição por substring
já suporta "fragmento dinâmico + afixo literal" sem mudança — é o mesmo mecanismo que hoje
produz `-H 'Referer: {{extractor:...}}/'` quando o token vale só a origin e a barra final
fica literal.

### `TokenLocationDetector.find` — `har_reproducer/tracking/token_location_detector.py:12-30`

Decide a `TokenLocation` procurando o valor em cookies → headers → `redirect_url` → body.
Não muda de comportamento; passa a receber `extracted_value` no lugar de `current_value`
(§3.10) — é o que faz o JWT ser corretamente localizado como `BODY_JSON` (o fragmento é
exatamente a folha `data['token']`).

### `AgentFactory.create` — `har_reproducer/agents/construction/agent_factory.py:42-64`

```python
return agent_cls(
    token_id=candidate.token_id,
    response_sample=response_sample,
    expected_value=candidate.current_value,
    ...
    origin_key=self._origin_key_for(candidate),
    ...
)
```

`expected_value=candidate.current_value` (`:48`) passa a ser `candidate.extracted_value`
(§3.10) — é contra esse valor que `BaseAgent.run_tdd_loop` (`base_agent.py:135-202`) mede
sucesso (`actual_value == self.expected_value`, `:199`). `_origin_key_for` (`:58-64`) já
funciona sem mudança: ele só usa `origin_key`/`origin_container` quando
`CONTAINER_LOCATIONS` bate com `origin_location`, e §3.5 preenche os dois com a mesma
semântica de hoje (nome do container), só que também para casamento por contenção.

### `CurlTokenComment` — `har_reproducer/replay/curl_token_comment.py` (121 linhas, arquivo inteiro)

Já ganhou `parse_anchors` na etapa anterior (item 9): devolve só as dependências cuja linha
**não** carrega `OriginStatusPhrase` — usado por `ReplayRunner._expand_pending` para montar
o schedule do `smart`. `parse` continua devolvendo todas as dependências (usado pelo
`ReplayTokenResolver`, que precisa do step de origem de todo token, inclusive dos
literais). `_split_clause_and_status`/`_categorize` (`:84-99`) já sabem separar cláusula de
sufixo e classificar frases — é o que §3.11 reaproveita para a categoria nova.

### `CurlGenerator._token_comments` — `har_reproducer/reproduction/curl_generator.py:61-71`

```python
def _token_comments(self, tokens: List[DynamicToken]) -> List[str]:
    lines: List[str] = [
        self.curl_token_comment.format_dependency_line(
            token.token_id, token.origin_step, self._origin_status(token)
        )
        for token in tokens if token.origin_step is not None
    ]
    unresolved: List[str] = [token.path for token in tokens if token.origin_step is None]
    ...
```

⚠️ Filtra por `origin_step is not None`. Um candidato que a porta desta etapa dispensa
**tem** `origin_step` preenchido (a porta roda depois de achar origem) — sem mudança aqui,
ele continuaria emitindo linha de dependência. É o que §3.11 corrige, filtrando por
`status` em vez de por `origin_step`.

### `models/session.py` — `DynamicToken.status`

```python
status: Literal["UnderReview", "NotFound", "Unresolved", "Resolved"]
```

Ganha um quinto valor, `"Static"` (§3.11). Nenhum código de produção lê `status` hoje além
de escrevê-lo — só testes — então o novo valor não quebra nenhum consumidor por si só; o
que passa a lê-lo é o `CurlGenerator` corrigido.

### `EngineFactory.create` / `_build_tracker` — `har_reproducer/engines/construction/engine_factory.py:59-110`

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

Um diretório só serve descoberta e execução — é o que §3.7 desfaz.

### `Engine._process_entry` — `har_reproducer/engines/engine.py:69-96`

```python
self._persist_request_step(index, step.request)
self._persist_original_response_step(index, step.response)
if skip_reason is not None:
    return self._skip_entry(index, skip_reason)
step.analysis = self.tracker.analyze_step(step, first_entry)
self.token_resolver.resolve_all()
response: StepResponse = self.execute_step(step)
self._persist_response_step(index, response)
```

⚠️ Em `--mode main`, quando o step `N` é analisado, `real_responses/` já contém as
respostas dos steps `< N` desta execução — é o que torna a porta calculável no lugar
certo. Em `--mode dry`, `_persist_response_step` é no-op e `real_responses/` fica vazio.

### `ReplayTokenResolver._fallback_to_captured` — `har_reproducer/replay/replay_token_resolver.py:69-82`

Já existe no `replay` o comportamento que §3.10 traz para o `run`: ao falhar, usa
`extractor.captured_value` com aviso no stdout.

---

## 3. Decisões de arquitetura

### 3.1 — `FragmentMatcher`: maior substring comum, podada pela cobertura

**Componente novo**, `har_reproducer/tracking/fragment_matcher.py`, sem estado.

**Estado esperado:** um método `longest_common(value: str, text: str) -> Optional[Tuple[str, int]]`
(fragmento e deslocamento no valor):

1. `k_min = ceil(MIN_COVERAGE * len(value))`, limitado a `len(value) - 1` (fragmento igual
   ao valor inteiro é caso do passe anterior).
2. Se nenhum pedaço de tamanho `k_min` do valor está no texto, devolve `None` — é a poda:
   descarta o caso comum antes de qualquer busca cara.
3. Senão, busca binária em `[k_min, len(value) - 1]` pelo maior `k` que ainda tem algum
   pedaço presente.
4. Desempate, nesta ordem: maior fragmento → menor deslocamento dentro do valor → (entre
   textos, em `OriginFinder`) step mais antigo.

⚠️ **Sem `ValueVariants`.** O passe roda só sobre o valor cru — o fragmento precisa ser
substring do valor **como ele aparece no request**, senão `PlaceholderApplier` não consegue
substituí-lo.

Medido (`docs/20260820 .../medições/lcs.py`, `descoberta.py`), sobre o workspace atual
regravado: com a poda, a descoberta completa do fluxo (324 steps) custa **2,6 s**, contra
**1,6 s** do passe de valor inteiro sozinho — a diferença é o passe de fragmento inteiro,
incluindo os critérios de §3.2–§3.4.

### 3.2 — Critérios de admissão do fragmento: cobertura e piso, não três

**Estado esperado:** um fragmento só é considerado se passar em dois critérios — não três.

| critério | regra |
|---|---|
| cobertura mínima | `MIN_COVERAGE = 0.5` — já é o limite de poda de §3.1, não um filtro a mais |
| piso absoluto | `len(fragmento) >= MIN_LENGTH` — ver §3.3, aplicado junto com o inteiro |

**A ubiquidade do lado do fragmento foi medida e não faz nada.** Testado com limiar 0,20
sobre os dois workspaces regravados: **0 fragmentos rejeitados** nos dois. Os fragmentos de
baixa entropia que ela existia para pegar (`'*/'`, `'control'`) já morrem na cobertura —
valores curtos o bastante para serem vocabulário comum também são curtos demais para ter
50% de si mesmos casados por um pedaço genérico. Fica fora do lado do fragmento; volta do
lado estruturado em §3.6/§3.8, onde ela faz trabalho real.

### 3.3 — Piso mínimo aplicado ao texto casado, inteiro **e** fragmento

**Estado atual:** nenhum piso — qualquer casamento inteiro vira candidato a extrator,
independente do tamanho.

**Estado esperado:** `MIN_LENGTH = 4`, comparado contra o texto casado (o valor inteiro
quando o casamento é inteiro; o fragmento quando é por fragmento).

**Por que também no casamento inteiro.** Medido no workspace anterior regravado, o único
falso positivo que sobrevive à porta de §3.5 depois do item 10 é `header:priority = 'u=0'`
— 3 caracteres, casamento **inteiro** (o valor inteiro do candidato é curto, então "inteiro"
e "de baixa entropia" coincidem aqui). Nenhum piso do lado do fragmento o alcançaria.

**O teto.** Medido: os casamentos inteiros **legítimos** do workspace anterior têm
comprimento 18–21 (`ETag`, 63 valores distintos) e 29 (`Last-Modified`, 21 valores). Um piso
≥ 18 começaria a destruir a classe de requisição condicional inteira. `MIN_LENGTH = 4` mata
o falso positivo conhecido e está a uma distância segura desse teto.

### 3.4 — `OriginFinder`: passe de fragmento na mesma chamada do passe de valor inteiro

**Estado esperado:** `find` ganha um segundo passe, executado só quando o passe de valor
inteiro (todas as variantes) não achou nada — na **mesma chamada**, não numa tentativa
posterior.

⚠️ **Tem que ser na mesma chamada.** `_find_origin` (§2, `CandidateResolver`) só cacheia
negativo com janela: um valor que não achou origem no step `N` só volta a ser procurado a
partir de `N`. Como segunda tentativa numa chamada futura, a janela negativa já teria
excluído os steps anteriores — é a mesma armadilha que a política de cache de 1.4 evitava
por outro caminho, e aqui a solução é estrutural (uma chamada, dois passes), não uma
política de cache nova.

Regras do passe: percorre os steps elegíveis (mesma janela do passe inteiro) aplicando
`FragmentMatcher.longest_common`; se um fragmento passa em §3.2 (cobertura) e §3.3 (piso) e
não é vetado por §3.6 (vocabulário), devolve `OriginMatch` com o fragmento preenchido;
`origin_key`/`origin_container` calculados sobre o **texto casado** (o fragmento), via a
generalização de §3.5.

### 3.5 — Porta de admissão: comparação de blob, mantida simples — três veredictos

**Estado atual:** todo candidato com origem encontrada vira extrator.

**Estado esperado:** depois de achar a origem e **antes** de `_find_slot`, comparar o
**texto casado** contra o corpo pesquisável (`searchable_text`, o mesmo blob de sempre) da
resposta de execução no mesmo step de origem:

| situação | veredito |
|---|---|
| texto casado **não** aparece no blob da execução | **mudou** |
| resposta de execução ausente ou vazia | **indeterminado** |
| texto casado aparece igual no blob da execução | **estático** |
| `--mode dry` (sem corpus de execução) | porta não se aplica |

Mecanismo idêntico ao que a investigação original media — **não** generaliza `_exact_key`
para contenção. Essa generalização foi desenhada, medida e descartada:

**Por que foi descartada.** A ideia era resolver o falso positivo de
`header:priority='u=0'` comparando especificamente o container (header/cookie) em vez do
blob inteiro — "aquele header existe na execução?" em vez de "o texto aparece em algum
lugar?". Medido: o piso mínimo de §3.3, aplicado também ao casamento inteiro, **já mata
esse falso positivo sozinho** (`'u=0'` tem 3 caracteres, abaixo do piso de 4) — a
generalização não era necessária para o único caso conhecido. E, medida separadamente, ela
**reabre uma classe de coincidência**: comparar por contenção dentro de um header/cookie é
ainda uma busca de substring, só num texto menor que o blob inteiro — testada, ela admite
lixo novo (`header:Sec-Fetch-Site` casando por contenção dentro de um header de resposta
alheio; no HAR anterior, mais quatro categorias). A comparação de blob simples, com o piso
já cobrindo o caso medido, é a opção sem esse custo.

⚠️ **`--mode dry` fica sem porta, deliberadamente.** `real_responses/` tem 0 arquivos em
dry; sem segunda observação não há como provar estático, e a porta significa "provado
estático, pula". A alternativa (fail-closed) zeraria os extratores em dry, inclusive o
`Authorization`.

### 3.6 — Veto de endereço do fluxo, condicionado à ordem de aparição

**Componente novo**, `har_reproducer/tracking/flow_vocabulary.py`.

**Estado esperado:** acumula, a cada step **analisado** (antes de resolver os candidatos
daquele step), o `hostname`, `netloc` e `esquema://netloc` da URL do request, junto com o
**índice do step** em que cada endereço apareceu por primeira vez. Expõe
`rejects(matched_text: str, origin_step: int) -> bool`: verdadeiro quando `matched_text`
**é igual** a um endereço observado **cuja primeira aparição foi num step anterior a
`origin_step`**.

Aplicado ao texto casado, inteiro e fragmento, dentro de `OriginFinder`/`OriginMatch`.

**Por que igualdade, não contenção.** Medido nos dois workspaces: toda rejeição de
vocabulário observada é `texto_casado == endereço` exato; a contenção (`texto ⊆ endereço`)
testada contra a igualdade dá exatamente a mesma saída nos dois — e carrega uma classe de
falso negativo que a igualdade não tem: `'api'`/`'fonts'` seriam vetáveis por serem
substring de algum hostname, sem nunca terem sido, eles mesmos, um endereço observado.

**Por que condicionar à ordem de aparição.** Sem a condição, um host de tenant ou sessão
(`sess-abc123.example.com`) observado no **próprio** step de origem do candidato vetaria
esse candidato por definição — o endereço só existe porque aquela resposta o revelou, e
seria rejeitado por coincidir com ele mesmo. Medido sobre o workspace anterior regravado: a
versão incondicional rejeita 14 ocorrências de fragmento; a condicional rejeita 11 — a
diferença são as **3 ocorrências de um único fragmento distinto**, `'http://localhost:8090'`
com origem no step 34, admitidas pela condicional e vetadas pela incondicional. A origem é
um bundle JavaScript que **informa** a URL da API antes de qualquer request a usar — é
exatamente o caso de subdomínio dinâmico legítimo que a formulação incondicional
destruiria. As outras 11 rejeições (`'http://127.0.0.1:8080'`, origem no step 75) são
idênticas nas duas versões.

### 3.7 — Descoberta sempre na época do HAR; execução na época corrente

**Estado esperado:**

```python
discovery_responses_dir: Path = self.workspace.original_responses
execution_responses_dir: Optional[Path] = (
    self.workspace.real_responses if engine_cls.USES_NETWORK else None
)
```

`CandidateResolver` passa a receber **dois** corpora: o de descoberta (`OriginFinder`,
`TokenLocationDetector`, verificação do agente, identidade de slot) e o de execução,
`Optional[ResponseCorpus]` — usado **só** pela porta de §3.5, e `None` desliga a porta em
`--mode dry` (é o sinal explícito, não "o diretório está vazio", que evita a ambiguidade
que existiria se o mesmo diretório servisse os dois papéis). `TokenResolver` continua
recebendo o diretório de execução como hoje.

**Por que é a única pareação com significado.** O valor procurado vem do request gravado
no HAR; não existe "valor de agora" de um campo antes da requisição ser montada. Medido: os
dois JWT (HAR e execução) têm 173 caracteres cada e compartilham **123** de prefixo,
divergindo a partir dos dígitos do `exp` — 123/180 = **68%** de cobertura, que passaria por
qualquer limiar de §3.2. Descobrir na época da execução montaria prefixo fresco com
assinatura velha, que nenhum servidor aceita; só a escolha certa da época protege desse
erro, a cobertura não.

⚠️ Renomear `response_corpus` → `discovery_corpus` no `CandidateResolver` — o nome atual
não distingue os dois papéis.

### 3.8 — Requisição condicional: a porta rebaixa a literal, decisão tomada

**O custo é uma regressão medida, não um "continua faltando".** Hoje, **sem porta
nenhuma**, um candidato de `If-None-Match`/`If-Modified-Since` com origem encontrada
(`ETag`/`Last-Modified` da resposta anterior, por igualdade exata) já recebe um extrator
real via `HeaderAgent` — é assim que os 84 extratores condicionais do HAR anterior existem
**hoje**, sem nada desta etapa. A porta de §3.5, sem tratamento especial, rebaixa essa
classe inteira a literal, porque `ETag`/`Last-Modified` são **idênticos** entre duas
observações próximas no tempo (medido: 210/210 e 215/218 no HAR anterior; 285/285 e
292/296 no atual).

**Decisão: nenhum tratamento especial nesta etapa.** Requisição condicional é tratada
exatamente como qualquer outro valor que não mudou entre as épocas — vira literal, e o
candidato é registrado por §3.11 como qualquer outro estático.

**Por quê.** Dois discriminadores foram medidos para admitir essa classe sem reabrir
coincidência (ubiquidade do valor no blob, e reuso do valor entre candidatos) e nenhum
ficou limpo: o primeiro admite 1–2 slots de lixo que **viram âncora de verdade** (diferente
do literal do item 9, um `HeaderAgent` genuíno com origem sempre ancora); o segundo zera o
lixo mas perde 9 dos 84 extratores genuínos. Nenhuma das duas trocas foi considerada boa o
bastante para o ganho que ela compra, e complexidade nova sem uma solução limpa não se
justifica. O custo aceito, medido: zero hoje, **+0,30 requisição por replay** no primeiro
deploy (medido depois de somar ao item 9, que já reduz o custo de 6,48 para 1,32
requisições no HAR anterior), e 126 dos 235 curls daquele HAR divergindo quando o `ETag`
mudar de verdade. É o caso que a **redescoberta reativa** (fora de escopo, §1.4) existe
para cobrir: detectar que um step que passava parou de passar e refazer a descoberta com
as respostas frescas em mão — ela terá mais contexto (o status divergiu de verdade, não só
uma comparação de duas amostras) do que esta porta tem isoladamente.

### 3.9 — `_accept_persisted_slot` deixa de semear o token

**Estado atual:** ao reaproveitar slot persistido, grava o valor no `SessionStore`
(`candidate_resolver.py:129`).

**Estado esperado:** a linha `self.session_store.set_token(slot_id, result)` sai. Registro
em `state.registry` e cache `_validated_values` continuam (identidade de slot, época do
HAR); quem semeia valor é `TokenResolver.resolve_all()`, que roda em seguida
(`engine.py:87`) lendo a época da execução.

Sem isso, o token da época do HAR entraria no `SessionStore` e nunca seria atualizado
(`resolve_all` pula token já presente — §2, `TokenResolver`) — o `Authorization` congelado
de novo, por outro caminho.

### 3.10 — `extracted_value`; consequências no fallback

```python
class OriginMatch(BaseModel):
    step_index: int
    origin_key: Optional[str] = None
    origin_container: Optional[OriginContainer] = None
    fragment: Optional[str] = None

class DynamicToken(BaseModel):
    ...
    origin_fragment: Optional[str] = None

    @property
    def extracted_value(self) -> str:
        return self.origin_fragment or self.current_value
```

`current_value` continua sendo o que o request carrega; `extracted_value` é o que o
extrator tem que produzir. Consumidores que passam a usar a propriedade (tabela consolidada
em §4).

⚠️ A atribuição de `origin_fragment` acontece logo depois de achar a origem, **antes** da
porta e de `_find_slot` — inclusive no caminho de cache positivo.

⚠️ **`TokenResolver` ganha fallback para `captured_value`, só quando o token ainda não tem
valor** (`token_id not in state.tokens`) — nunca sobrescrevendo um valor bom durante
`Engine.handle_recovery`'s `resolve_all(force=True)` (recuperação de 401/403). Das três
desistências de `_refresh_token` (§2): arquivo ausente **não** dispara fallback (é "ainda
não se aplica" — o step de origem nem rodou); valor falsy dispara.

### 3.11 — Registrar o que a porta dispensou, sem ancorar

**Estado esperado:** quinto valor em `DynamicToken.status`: `"Static"` — atribuído quando a
porta devolve estático ou indeterminado. `CurlGenerator._token_comments` passa a filtrar a
linha de dependência por `token.status == "Resolved"` (verificado: equivalente a "existe
extrator registrado", byte-idêntico ao golden atual), em vez de por `origin_step is not
None`. Uma categoria nova, que **não** casa com `DEPENDENCY_PATTERN` nem com
`UNRESOLVED_PATTERN`:

```
# [Static N] path←step
```

para candidatos com `status == "Static"`, preservando o step de origem para diagnóstico
futuro sem virar âncora — `parse_anchors` (item 9) já ignora qualquer linha que não seja
`# [Token ...]`, então nenhuma mudança é necessária ali.

### 3.12 — Fixtures precisam divergir entre as épocas

**Estado atual:** o servidor canned de teste devolve exatamente o que o `.har` sintético
gravou — com a porta, o cenário `run_main` passaria a produzir 0 extratores, e a cobertura
de todo o pipeline de descoberta no caminho de rede apagaria.

**Estado esperado:**

- Valores que devem continuar dinâmicos passam a divergir entre o HAR e o canned
  (`SESSIONID`, `tok_CSS_1`, `scr_NONCE_2`, `PLAINVAL777`, `PREFS`).
- O valor `4242` (usado em path de URL, `GET /item/4242`) também diverge — precisa de
  roteamento por prefixo no `CannedHttpHandler` (`/item/<qualquer>` → `{"id": 9999}`), para
  não quebrar o lookup exato de `(método, path)`. Preservar esse valor divergente é o que
  mantém 6 cenários de `replay`/`optimize` exercitando propósito real (expansão transitiva
  do smart, piso `--from`, fallback do replay) — medido, sem ele eles ainda passam, mas sem
  testar nada.
- Fixture novo `tests/fixtures/auth_flow.har`: login devolvendo `{"token": "<TOKEN_HAR>"}`,
  recurso protegido que só aceita `Bearer <TOKEN_VIVO>` (≠ `TOKEN_HAR`, ambos ≥ 32 chars).
  É o teste que falha hoje (literal do HAR → 403) e passa depois.
- `Content-Type: application/json` do request do step 9 **fica estático** — divergir
  exigiria o canned devolver algo como `text/json`, semanticamente errado; a cobertura do
  `HeaderAgent` continua garantida por outro par header-de-request/header-de-resposta
  criado no fixture, não pela divergência deste em particular.

---

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `tracking/fragment_matcher.py` → `FragmentMatcher` | **novo**: `longest_common`, busca binária podada por cobertura (3.1) |
| `tracking/flow_vocabulary.py` → `FlowVocabulary` | **novo**: veto por igualdade, condicionado à ordem de aparição (3.6) |
| `tracking/origin_finder.py` → `OriginFinder` | passe de fragmento na mesma chamada; `origin_key`/`origin_container` também para fragmento, via `_exact_key` **sem mudança** (igualdade, não contenção) (3.4) |
| `models/analysis.py` → `OriginMatch` | campo `fragment` (3.10) |
| `models/session.py` → `DynamicToken` | campo `origin_fragment`, propriedade `extracted_value`, quinto valor `"Static"` em `status` (3.10, 3.11) |
| `tracking/candidate_resolver.py` → `CandidateResolver` | recebe `discovery_corpus` e `execution_corpus: Optional[...]`; porta de admissão (3.5); usa `extracted_value`; `_accept_persisted_slot` deixa de semear (3.7, 3.9, 3.10). **`_find_origin`/`_origin_cache` não mudam (1.4). Requisição condicional depende da decisão de §3.8/§6.** |
| `tracking/placeholder_applier.py`, `agents/construction/agent_factory.py`, `tracking/token_location_detector.py` (via chamador) | usam `extracted_value` (3.10) |
| `tracking/token_resolver.py` → `TokenResolver` | fallback para `captured_value` só quando token ainda não tem valor (3.10) |
| `engines/construction/engine_factory.py` → `EngineFactory` | separa `discovery_responses_dir`/`execution_responses_dir`; passa `execution_corpus: Optional[ResponseCorpus]` (3.7) |
| `reproduction/curl_generator.py` → `CurlGenerator` | filtra linha de dependência por `status == "Resolved"`; emite `[Static N]` (3.11) |
| `tests/support/canned_http_handler.py`, `tests/fixtures/synthetic_flow.har`, `tests/fixtures/auth_flow.har` (novo) | valores divergentes, roteamento por prefixo, fixture de autenticação (3.12) |
| golden de `run_main`, `run_dry_*`; `tests/unit/test_engine_factory.py`, `test_candidate_resolver.py`, `test_origin_finder.py`, `test_token_resolver.py`, `test_placeholder_applier.py`, `test_curl_generator.py`, `test_agent_factory.py`, `test_token_location_detector.py` | regeneração e acompanhamento de assinatura |

`CurlTokenComment`, `ReplayTokenResolver`, `ReplayRunner`, `ReplayOptimizer` — **não
mudam.** `parse_anchors` (item 9) já ignora `[Static N]` por construção.

---

## 5. Casos de borda e comportamento de erro

**5.1 Fragmento com `TokenLocation` indeterminada.** Vira `LiteralAgent` com o fragmento
como literal — mesmo comportamento que o valor inteiro já tem hoje.

**5.2 Fragmento maximal que "vaza" além do token.** Pode incluir caractere vizinho
compartilhado por acaso; o agente não extrai exatamente aquele texto, o laço TDD esgota,
cai em `LITERAL_FALLBACK`. Não observado nos dois workspaces.

**5.3 Fragmento de um token aparece dentro do valor de outro.** `PlaceholderApplier`
substitui todas as ocorrências — comportamento que já existe hoje com valor inteiro
(`-H 'Referer: {{extractor:...}}/'`), o fragmento herda a borda sem alargá-la.

**5.4 Extração falha na época da execução.** Cai para `captured_value` com aviso (3.10); o
request sai com o literal, nunca com `{{extractor:...}}` cru.

**5.5 Steps pulados como origem.** `original_responses/` guarda a resposta do HAR também
para steps pulados por `skip_rules`; `real_responses/` guarda `status_code=0` sem corpo —
tratado como indeterminado por 3.5, sem extrator.

**5.6 `--mode dry`.** Sem porta (`execution_corpus=None`). `Authorization` ganha aresta e
extrator resolvendo para o valor do próprio HAR — correto, dry não tem outra época.

**5.7 Um valor genuinamente dinâmico que veio igual nas duas observações.** É a classe da
decisão de §3.8: requisição condicional é o caso medido e aceito (84 extratores do HAR
anterior), mas qualquer outro token que por coincidência de tempo não tenha mudado entre a
gravação e a execução (ex.: token rotativo que não rotacionou) cai na mesma classe. Fica
literal e quebra no dia em que mudar — é o custo declarado desta porta, e é o que a
redescoberta reativa (fora de escopo) existiria para cobrir. O registro de 3.11 é o que
torna esse caso diagnosticável por `grep` em vez de virar mistério.

**5.8 Workspaces gerados antes desta etapa.** Continuam com as arestas antigas; `replay`/
`optimize` sobre eles seguem como hoje. Sem migração — é preciso rodar `run` de novo.

**5.9 Custo.** 1,6 s → 2,6 s de descoberta no fluxo de 324 steps, contra um `run` de
2m24s — irrelevante.

---

## 6. Suposições e pontos a confirmar

- **`MIN_COVERAGE = 0.5`, `MIN_LENGTH = 4`** — medidos e confirmados sobre os dois
  workspaces disponíveis; nenhum dos dois é `config.json`, ambos `ClassVar`.
- **Nomes** (`FragmentMatcher`, `FlowVocabulary`, `extracted_value`, `discovery_corpus`) —
  ajustáveis.
- **Formato de `[Static N]`** — ajustável; não é ajustável a garantia de não colisão com
  `DEPENDENCY_PATTERN`/`UNRESOLVED_PATTERN`.
- **Renomear `response_corpus` → `discovery_corpus`** custa churn de teste — confirmar se
  entra aqui ou fica para depois.

---

## 7. Referência

Toda alteração de código desta spec segue [[guia-de-estilo]]. As decisões respeitam o
princípio de genericidade de [[arquitetura-e-fundamentos]]: `Bearer` não é conhecido pelo
código em lugar nenhum; o vocabulário do fluxo é derivado da própria gravação; e o critério
de "dinâmico" continua sendo evidência observada — o valor mudou, ou a evidência é
posicionalmente idêntica à do request — nunca aparência de formato ou nome de header.
