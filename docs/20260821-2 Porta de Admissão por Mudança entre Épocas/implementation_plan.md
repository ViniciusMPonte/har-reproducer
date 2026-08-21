# Plano de Implementação — Porta de Admissão por Mudança entre Épocas

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## Decisões dos pontos abertos da spec (§6)

Fechadas aqui para que as tasks sejam executáveis:

1. **Nomes:** `FragmentMatcher`, `FlowVocabulary`, `extracted_value` — como usados na spec.
2. **Renomear `response_corpus` → `discovery_corpus`** em `CandidateResolver`: **entra**
   nesta etapa (T05). É baixo custo (um atributo, poucos testes) e é o nome que evita
   reintroduzir o mal-entendido que motivou a investigação original.
3. **Formato de `[Static N]`:** `# [Static N] path←step; path←step` — mesmo separador
   (`CATEGORY_SEPARATOR`) e mesma seta que a spec propôs, sem espaço ao redor de `←`.
4. **`§3.8` (requisição condicional) não gera task.** Já é o comportamento resultante das
   demais tasks — nenhum código dedicado.

## Nota de execução

TDD em cada task. Tasks T10–T12 tocam fixtures e goldens de rede — rodar
`pytest --runslow` só a partir delas; as tasks T01–T09 só precisam de
`pytest tests/unit -q`.

---

## [T01] — Modelos: `OriginMatch.fragment`, `DynamicToken.origin_fragment`/`extracted_value`/`"Static"`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/analysis.py` (`OriginMatch`), `har_reproducer/models/session.py` (`DynamicToken`), `tests/unit/test_origin_match.py`

**Contexto:**
Toda a etapa depende de dois campos novos e uma propriedade que não existem hoje: o
`OriginMatch` não sabe representar "casei por fragmento", e o `DynamicToken` não distingue
"o que o request carrega" (`current_value`) de "o que o extrator tem que produzir"
(`extracted_value`, que passa a ser o fragmento quando houver um). Um quinto valor de
`status` marca o candidato que a porta (T05) dispensa.

**Estado atual:**
```python
class OriginMatch(BaseModel):          # models/analysis.py
    step_index: int
    origin_key: Optional[str] = None
    origin_container: Optional[OriginContainer] = None

class DynamicToken(BaseModel):         # models/session.py:51-61
    token_id: str
    path: str
    current_value: str
    destination_location: TokenLocation
    origin_location: Optional[TokenLocation] = None
    origin_step: Optional[int] = None
    origin_key: Optional[str] = None
    origin_container: Optional[OriginContainer] = None
    status: Literal["UnderReview", "NotFound", "Unresolved", "Resolved"]
    extraction_exhausted: bool = False
```

**Estado esperado depois:**
```python
class OriginMatch(BaseModel):
    step_index: int
    origin_key: Optional[str] = None
    origin_container: Optional[OriginContainer] = None
    fragment: Optional[str] = None      # None = casou o valor inteiro

class DynamicToken(BaseModel):
    ...
    status: Literal["UnderReview", "NotFound", "Unresolved", "Resolved", "Static"]
    extraction_exhausted: bool = False
    origin_fragment: Optional[str] = None

    @property
    def extracted_value(self) -> str:
        return self.origin_fragment or self.current_value
```

⚠️ `extracted_value` é `@property`, não campo persistido — não aparece em
`model_dump_json()`, e isso é intencional: só `origin_fragment` precisa ser serializado.

**Critérios de aceite:**
- [ ] `OriginMatch(step_index=1).fragment is None` (default).
- [ ] `OriginMatch(step_index=1, fragment="abc").fragment == "abc"`.
- [ ] `DynamicToken(..., status="Static")` é aceito pelo validador do Pydantic (hoje
      rejeitaria com `ValidationError`).
- [ ] Um `DynamicToken` sem `origin_fragment` tem `extracted_value == current_value`.
- [ ] Um `DynamicToken` com `origin_fragment="frag"` tem `extracted_value == "frag"`,
      mesmo que `current_value` seja diferente.
- [ ] Não-regressão: todo `DynamicToken(...)` construído sem os campos novos nos testes
      existentes (`grep -rl "DynamicToken(" tests/`) continua válido — os campos novos têm
      default.

---

## [T02] — `FragmentMatcher`: maior substring comum, podada pela cobertura

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/fragment_matcher.py` (novo), `tests/unit/test_fragment_matcher.py` (novo)

**Contexto:**
Componente novo, sem estado, usado por `OriginFinder` (T04). Dado o valor de um candidato e
o texto pesquisável de uma resposta, devolve o maior pedaço contíguo que os dois
compartilham — ou `None`, se nem o pedaço de tamanho mínimo (`MIN_COVERAGE * len(valor)`)
aparecer no texto.

**Estado atual:** não existe.

**Estado esperado depois:**
```python
class FragmentMatcher:
    MIN_COVERAGE: ClassVar[float] = 0.5

    @classmethod
    def longest_common(cls, value: str, text: str) -> Optional[Tuple[str, int]]:
        ...  # devolve (fragmento, deslocamento no valor), ou None
```

Algoritmo: `k_min = ceil(MIN_COVERAGE * len(value))`, limitado a `len(value) - 1`; se nenhum
pedaço de tamanho `k_min` está em `text`, devolve `None` (a poda); senão, busca binária em
`[k_min, len(value) - 1]` pelo maior `k` com algum pedaço presente. Desempate entre pedaços
do mesmo tamanho `k`: **menor deslocamento dentro do valor**.

⚠️ Não usar `ValueVariants` aqui — é decisão de `OriginFinder` (T04), este componente só
compara texto cru.
⚠️ Nunca devolver o valor inteiro como "fragmento" — `k_max = len(value) - 1` já garante
isso, mas vale um teste explícito.

**Critérios de aceite:**
- [ ] `longest_common("Bearer abc123def", "xxx abc123def yyy")` devolve `("abc123def", 7)`
      (fragmento é o próprio candidato sem o prefixo `"Bearer "`).
- [ ] `longest_common("http://127.0.0.1:8080", "http:// nada aqui")` devolve `None` — o
      maior pedaço comum (`"http://"`, 7 de 21 chars, 33%) não atinge a cobertura mínima.
- [ ] `longest_common("abcdefgh", "xyzabcdxyz")` (cobertura exata no limite, 4 de 8 = 50%)
      devolve um fragmento de 4 caracteres, não `None`.
- [ ] `longest_common(value, text)` nunca devolve `(value, 0)` — o valor inteiro não é um
      resultado válido deste método.
- [ ] Valor de 1 caractere devolve `None` (nada abaixo do mínimo de granularidade).
- [ ] Dois pedaços de mesmo tamanho máximo, em deslocamentos diferentes do valor: devolve o
      de menor deslocamento.

---

## [T03] — `FlowVocabulary`: endereços do fluxo, veto condicionado à ordem de aparição

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/flow_vocabulary.py` (novo), `tests/unit/test_flow_vocabulary.py` (novo)

**Contexto:**
Componente novo, com estado acumulado ao longo do `run`. Observa a URL de cada step
analisado e guarda `hostname`, `netloc` e `esquema://netloc`, com o índice do **primeiro**
step em que cada um apareceu. `rejects` diz se um texto casado deveria ser vetado como
"é o endereço do próprio site, não um token" — só quando esse endereço já era conhecido
**antes** do step de origem do candidato.

**Estado atual:** não existe.

**Estado esperado depois:**
```python
class FlowVocabulary:
    def __init__(self) -> None:
        self._first_seen: Dict[str, int] = {}

    def observe(self, url: str, step_index: int) -> None:
        parsed = urlparse(url)
        if not parsed.hostname:
            return
        for address in (parsed.hostname, parsed.netloc, f"{parsed.scheme}://{parsed.netloc}"):
            self._first_seen.setdefault(address, step_index)

    def rejects(self, matched_text: str, origin_step: int) -> bool:
        first_seen: Optional[int] = self._first_seen.get(matched_text)
        return first_seen is not None and first_seen < origin_step
```

⚠️ `setdefault` — só a **primeira** aparição de um endereço conta; observações repetidas
não sobrescrevem o índice.
⚠️ Igualdade exata (`matched_text == address`), não contenção — decisão medida (spec §3.6):
contenção não muda a saída nos dois workspaces e carrega falso negativo
(`'api'`/`'fonts'` vetáveis por serem substring de hostname).

**Critérios de aceite:**
- [ ] Depois de `observe("http://127.0.0.1:8080/x", 5)`, `rejects("http://127.0.0.1:8080", 10)`
      é `True` e `rejects("http://127.0.0.1:8080", 3)` é `False` (endereço só apareceu
      **depois** do step de origem do candidato).
- [ ] `rejects` de um texto que nunca foi observado como endereço é `False`.
- [ ] `rejects("api", ...)` é `False` mesmo depois de observar `"https://api.example.com"`
      — sem contenção, só igualdade exata.
- [ ] Duas observações do mesmo endereço, em steps diferentes: `_first_seen` guarda o
      **menor** dos dois índices.

---

## [T04] — `OriginFinder` + `TokenTracker`: passe de fragmento, piso, veto de vocabulário

**Depende de:** T01 (`OriginMatch.fragment`), T02 (`FragmentMatcher`), T03 (`FlowVocabulary`).
**Arquivos envolvidos:** `har_reproducer/tracking/origin_finder.py` (`OriginFinder`), `har_reproducer/tracking/token_tracker.py` (`TokenTracker`), `tests/unit/test_origin_finder.py`, `tests/unit/test_token_tracker.py`, `tests/support/recording_origin_finder.py`

**Contexto:**
`OriginFinder.find` hoje só sabe achar o valor inteiro. Ganha um piso mínimo aplicado a
**qualquer** casamento (inteiro ou fragmento), um veto de vocabulário aplicado ao texto
casado, e um segundo passe — fragmento — quando o valor inteiro não é achado, na **mesma
chamada**. `TokenTracker` passa a alimentar o vocabulário com a URL de cada step, antes de
resolver os candidatos daquele step.

**Estado atual:**
```python
class OriginFinder:
    def __init__(self, corpus: ResponseCorpus) -> None:
        self.corpus: ResponseCorpus = corpus

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
```python
class TokenTracker:
    def __init__(self, baseline_diff, candidate_resolver, placeholder_applier, curl_generator) -> None: ...
    def analyze_step(self, step: Step, baseline_step: Step) -> StepAnalysis:
        diffs = self.baseline_diff.compare(step, baseline_step)
        candidates = self.baseline_diff.detect_candidates(diffs)
        tokens = self.candidate_resolver.resolve(candidates, step.index)
        ...
```

**Estado esperado depois:**
- `OriginFinder.__init__` ganha `flow_vocabulary: FlowVocabulary`.
- `MIN_LENGTH: ClassVar[int] = 4` em `OriginFinder`.
- `find` aplica o piso ao casamento inteiro: se `len(value) < MIN_LENGTH`, devolve `None`
  sem tentar nada (piso é sobre o **valor do candidato** quando o casamento é inteiro,
  porque nesse caso texto casado == valor).
- Se o passe de valor inteiro não achou nada, um segundo passe: para cada step elegível,
  `FragmentMatcher.longest_common(value, texto_do_step)` sobre o texto **cru** (sem
  `ValueVariants`); entre os fragmentos achados, desempate **maior fragmento → menor
  deslocamento (`FragmentMatcher` já resolve) → step mais antigo**; o fragmento vencedor só
  é aceito se `len(fragmento) >= MIN_LENGTH` **e** `not flow_vocabulary.rejects(fragmento,
  step_do_fragmento)`. Aceito, devolve `OriginMatch(step_index=..., fragment=fragmento)`,
  com `origin_key`/`origin_container` calculados sobre o **fragmento** via `_origin_key`
  (mecanismo existente, sem mudança — igualdade exata, quase sempre `None` para fragmento).
- O veto de vocabulário também se aplica ao casamento **inteiro**: depois de achar via
  `_find_variant`, se `flow_vocabulary.rejects(variant_crua, step_achado)`, o passe de
  valor inteiro segue para o próximo step elegível em vez de aceitar (⚠️ só quando
  `is_raw`; variantes decodificadas/base64 não são endereço literal do fluxo).
- `TokenTracker.__init__` ganha `flow_vocabulary: FlowVocabulary`; `analyze_step` chama
  `self.flow_vocabulary.observe(step.request.url, step.index)` como primeira linha, antes
  de `self.baseline_diff.compare(...)`.

⚠️ **Tudo isso roda na mesma chamada de `find`, não como segunda tentativa** — `_find_origin`
em `CandidateResolver` só cacheia negativo com janela; uma tentativa futura já teria a
janela negativa avançada, perdendo steps anteriores.
⚠️ **`_exact_key` não muda** — continua igualdade exata, nunca contenção (spec §3.5,
decisão medida e descartada a generalização).

**Critérios de aceite:**
- [ ] `find("Bearer eyJ...", 0, 224)` sobre um corpus onde só `eyJ...` (sem `"Bearer "`)
      aparece na resposta do step 153: devolve `OriginMatch(step_index=153, fragment="eyJ...")`.
- [ ] `find("u=0", 0, 76)` sobre um corpus onde `"u=0"` aparece inteiro no step 76: devolve
      `None` — 3 caracteres, abaixo do piso, mesmo sendo casamento inteiro.
- [ ] `find("http://127.0.0.1:8080", ...)` sobre um corpus onde só `"http://"` (7 de 21
      chars, 33%) aparece antes do step de origem verdadeiro: devolve `None` (fragmento sem
      cobertura), permitindo que uma chamada posterior, com o step de origem verdadeiro na
      janela, ache o valor **inteiro**.
- [ ] Um fragmento cujo texto é igual a um endereço observado num step **anterior** ao de
      origem do fragmento: rejeitado, `find` devolve `None`.
- [ ] O mesmo fragmento, mas o endereço só foi observado num step **posterior** ao de
      origem do fragmento: aceito.
- [ ] `TokenTracker.analyze_step` chama `flow_vocabulary.observe` com a URL e o índice do
      `step` recebido, antes de chamar `candidate_resolver.resolve`.
- [ ] Não-regressão: os 15 testes de `tests/unit/test_origin_finder.py` (verificados
      individualmente — nenhum usa valor abaixo de `MIN_LENGTH=4` num contexto onde o
      fragmento se aplicaria) passam sem alteração de asserção, só atualizando `_finder(...)`
      para passar um `FlowVocabulary()` vazio.
- [ ] Não-regressão: os 5 testes de `tests/unit/test_token_tracker.py` que constroem
      `TokenTracker(...)` passam um `FlowVocabulary()` real (não fake — é componente puro,
      sem I/O) como quinto argumento.
- [ ] `RecordingOriginFinder.__init__` (`tests/support/recording_origin_finder.py`) aceita e
      repassa `flow_vocabulary` ao `super().__init__`.

---

## [T05] — `CandidateResolver`: dois corpora, `extracted_value`, porta de admissão

**Depende de:** T01, T04 (via `OriginMatch.fragment` e o `OriginFinder` já fragment-aware).
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py`, `tests/unit/test_candidate_resolver.py`

**Contexto:**
O coração da etapa. `_process_candidate` ganha a porta de admissão entre achar a origem e
alocar um slot; todo lugar que hoje lê `current_value` para decidir o que o extrator produz
passa a ler `extracted_value`; e `_accept_persisted_slot` para de semear o `SessionStore`.

**Estado atual:**
```python
def __init__(self, response_corpus, origin_finder, session_store, extractor_runner, metadata_store, agent_factory) -> None:
    self.response_corpus: ResponseCorpus = response_corpus
    ...

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
`_check_cached_slot`, `_check_persisted_slot`, `_generate_new_extractor`,
`_register_extractor`, `_build_literal_extractor` usam `candidate.current_value`.
`_accept_persisted_slot` chama `self.session_store.set_token(slot_id, result)`.

**Estado esperado depois:**
- Renomear `response_corpus` → `discovery_corpus` (parâmetro e atributo).
- Novo parâmetro `execution_corpus: Optional[ResponseCorpus]`.
- `_process_candidate`:
  1. Acha origem via `_find_origin(candidate.current_value, step_index)` — **sem mudança**
     na assinatura nem no cache (`_find_origin`/`_origin_cache`/`_origin_misses` intocados).
  2. Preenche `origin_step`, `origin_key`, `origin_container`, **e `origin_fragment =
     origin.fragment`** — sempre, mesmo quando o veredito da porta (próximo passo) vai
     rejeitar. Isso é o que mantém os testes que só verificam esses campos passando sem
     depender da porta.
  3. **Porta de admissão** (só quando `execution_corpus is not None`): busca
     `execution_corpus.searchable_text(origin.step_index)`. Vazio/ausente → indeterminado;
     `candidate.extracted_value not in texto` → mudou; senão → estático. Se **não** for
     "mudou" (ou a porta não se aplica, ou é dry), segue normalmente para o passo 4; se
     **for** estático/indeterminado, `candidate.status = "Static"` e retorna
     imediatamente — **sem** `_find_slot`, sem gerar extrator.
  4. `_find_slot`/geração de extrator, como hoje, mas usando `extracted_value` em todo
     lugar que hoje usa `current_value` (`_check_cached_slot`, `_check_persisted_slot`,
     `_generate_new_extractor`'s chamada a `TokenLocationDetector.find`,
     `_register_extractor`'s `captured_value`, `_build_literal_extractor`'s `return`).
- `_accept_persisted_slot`: remover a linha `self.session_store.set_token(slot_id, result)`.
  Registro em `state.registry` e `_validated_values` continuam.

⚠️ **`execution_corpus is None` desliga a porta inteiramente** (não é "resposta vazia" —
esse é o veredito "indeterminado" quando o corpus existe mas a resposta específica não).
`None` é o sinal de "estamos em `--mode dry`", vindo de T06.

**Critérios de aceite:**
- [ ] Candidato cuja origem casa por fragmento, com `execution_corpus` cuja resposta no
      step de origem **não** contém o fragmento: `status == "Resolved"`, e o extrator
      gerado usa `extracted_value` (fragmento), não `current_value`.
- [ ] Mesmo cenário, mas a resposta de execução **contém** o fragmento idêntico:
      `status == "Static"`, `token_id`/registry não populados, nenhuma chamada ao
      `agent_factory`/`extractor_runner`.
- [ ] Resposta de execução ausente no step de origem: `status == "Static"` (indeterminado,
      mesmo tratamento que estático — não gera extrator).
- [ ] `execution_corpus=None`: candidato segue direto para geração de extrator, **sem**
      checar época de execução nenhuma — comportamento idêntico ao de hoje.
- [ ] `_accept_persisted_slot`: `session_store.state.tokens` **não** é populado depois de
      aceitar um slot persistido (novo teste — hoje nenhum teste verifica isso, mas o
      comportamento muda).
- [ ] Não-regressão: os testes de `_check_cached_slot`/`_check_persisted_slot`/`_find_slot`
      que chamam esses métodos **diretamente** (não via `resolve()`) continuam passando sem
      alteração — não passam pela porta.
- [ ] Não-regressão: `test_process_candidate_records_origin_key_and_container_from_header`,
      `test_process_candidate_without_origin_leaves_the_three_fields_none`,
      `test_process_candidate_matching_in_body_has_no_origin_key`,
      `test_negative_cache_narrows_the_search_window_on_the_next_lookup`,
      `test_negative_cache_does_not_hide_an_origin_written_later`,
      `test_positive_cache_keeps_a_single_find_call` — todos usam `_resolver(...)`, que
      passa `execution_corpus=None`; continuam passando sem alteração de asserção.
- [ ] Não-regressão: `test_accept_persisted_slot_backfills_captured_value_when_none` e
      `test_accept_persisted_slot_keeps_existing_captured_value` continuam passando sem
      alteração — nenhum dos dois verifica `session_store.state.tokens`.
- [ ] Não-regressão: `test_generate_new_extractor_reads_the_response_from_the_corpus`
      continua passando sem alteração — `execution_corpus=None` nos testes existentes
      significa que a porta nunca intercepta esse fluxo.
- [ ] `_resolver`/`_resolver_verifying`/`_resolver_with_executor` (helpers de teste) passam
      `execution_corpus=None` explicitamente ao construtor, documentando que os testes
      existentes exercitam o equivalente a `--mode dry`.

---

## [T06] — `EngineFactory`: dois corpora, `FlowVocabulary` e `TokenTracker` conectados

**Depende de:** T03, T04, T05 (constrói os três com as assinaturas novas).
**Arquivos envolvidos:** `har_reproducer/engines/construction/engine_factory.py`, `tests/unit/test_engine_factory.py`

**Contexto:**
Ponto único onde hoje um diretório serve descoberta e execução. Passa a separar os dois
papéis e a montar `FlowVocabulary` uma vez por `run`, compartilhada entre `OriginFinder` e
`TokenTracker`.

**Estado atual:**
```python
tracking_responses_dir: Path = (
    self.workspace.real_responses if engine_cls.USES_NETWORK else self.workspace.original_responses
)
...
response_corpus: ResponseCorpus = ResponseCorpus(tracking_responses_dir, Workspace.STEP_INDEX_WIDTH)
return engine_cls(
    har_path, self.workspace, session_store,
    self._build_tracker(response_corpus, session_store, extractor_runner, metadata_store),
    TokenResolver(tracking_responses_dir, session_store, extractor_runner),
    ...
)
```

**Estado esperado depois:**
```python
discovery_responses_dir: Path = self.workspace.original_responses
execution_responses_dir: Optional[Path] = (
    self.workspace.real_responses if engine_cls.USES_NETWORK else None
)
discovery_corpus: ResponseCorpus = ResponseCorpus(discovery_responses_dir, Workspace.STEP_INDEX_WIDTH)
execution_corpus: Optional[ResponseCorpus] = (
    ResponseCorpus(execution_responses_dir, Workspace.STEP_INDEX_WIDTH)
    if execution_responses_dir is not None else None
)
flow_vocabulary: FlowVocabulary = FlowVocabulary()
...
return engine_cls(
    har_path, self.workspace, session_store,
    self._build_tracker(discovery_corpus, execution_corpus, flow_vocabulary, session_store, extractor_runner, metadata_store),
    TokenResolver(
        self.workspace.real_responses if engine_cls.USES_NETWORK else self.workspace.original_responses,
        session_store, extractor_runner,
    ),
    ...
)
```

⚠️ `TokenResolver` continua recebendo o diretório de **execução** — em dry, é
`original_responses` (comportamento de hoje, sem mudar); a diferença é que
`execution_corpus` (para a porta) é **`None`** em dry, não um `ResponseCorpus` apontando
para `original_responses`. São coisas diferentes: `TokenResolver` sempre lê alguma coisa;
`execution_corpus` só existe quando há uma segunda época de verdade.

`_build_tracker` passa `flow_vocabulary` para `OriginFinder(discovery_corpus, flow_vocabulary)`
e para `TokenTracker(..., flow_vocabulary)`, e `execution_corpus` para
`CandidateResolver(discovery_corpus, ..., execution_corpus=execution_corpus)`.

**Critérios de aceite:**
- [ ] `create(EngineMode.MAIN, ...)`: `engine.tracker.candidate_resolver.discovery_corpus.responses_dir
      == workspace.original_responses` (**mudou** — hoje é `real_responses`).
- [ ] `create(EngineMode.MAIN, ...)`: `engine.tracker.candidate_resolver.execution_corpus.responses_dir
      == workspace.real_responses`.
- [ ] `create(EngineMode.DRY, ...)`: `engine.tracker.candidate_resolver.discovery_corpus.responses_dir
      == workspace.original_responses` (sem mudança de valor, só de nome do atributo).
- [ ] `create(EngineMode.DRY, ...)`: `engine.tracker.candidate_resolver.execution_corpus is None`.
- [ ] `engine.token_resolver.responses_dir` continua `real_responses` em `MAIN` e
      `original_responses` em `DRY` — **sem mudança**, é o que
      `test_create_dry_uses_original_responses_directory` e
      `test_create_main_passes_through_transport_and_uses_real_responses_directory` já
      verificam (essas duas asserções sobre `token_resolver` não mudam; só a de
      `candidate_resolver.response_corpus` → `discovery_corpus` muda de nome e, no caso de
      `MAIN`, de valor esperado).
- [ ] Não-regressão: `test_resolve_class_maps_modes_to_engine_classes`,
      `test_create_dry_ignores_http_transport`,
      `test_llm_is_none_when_project_config_has_no_llm_settings` passam sem alteração.

---

## [T07] — `TokenResolver`: fallback para `captured_value`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/token_resolver.py`, `tests/unit/test_token_resolver.py`

**Contexto:**
Hoje, se a extração falhar, o token fica sem valor e o `{{extractor:...}}` sai cru no
request. Consequência da separação de épocas: um extrator verificado na época do HAR pode
falhar na época da execução (ex.: header ausente). Precisa de rede de segurança —
`ReplayTokenResolver._fallback_to_captured` já faz isso no `replay`.

**Estado atual:**
```python
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

**Estado esperado depois:**
```python
def _refresh_token(self, token_id: str, extractor: Extractor) -> None:
    if not (self.responses_dir / f"res_{extractor.origin_step:04d}.json").exists():
        return
    try:
        value: Optional[str] = self.extractor_runner.run(extractor, self.responses_dir)
    except Exception as e:
        print(f"Failed to refresh token '{token_id}': {e}")
        value = None
    if value:
        self.session_store.set_token(token_id, value)
    elif extractor.captured_value is not None:
        print(f"Token '{token_id}' could not be extracted; using captured value instead.")
        self.session_store.set_token(token_id, extractor.captured_value)
```

⚠️ O caso "arquivo de resposta ausente" (`:26-27`) **não** passa por aqui — ele retorna
antes, sem fallback, porque o step de origem ainda nem rodou (não é falha de extração, é
"ainda não se aplica").
⚠️ `resolve_all` já pula token que está em `state.tokens` (`:17-18`) — o fallback só roda
quando o token **ainda não tem valor**, então nunca sobrescreve um valor bom, inclusive na
recuperação de 401/403 (`resolve_all(force=True)`, que relê a mesma resposta imutável e
mantém o token que já resolveu).

**Critérios de aceite:**
- [ ] Extrator cujo script devolve string vazia, com `captured_value` setado: token acaba
      com o valor de `captured_value`.
- [ ] Mesmo cenário, sem `captured_value` (`None`): token continua sem valor (comportamento
      de hoje).
- [ ] Extrator cujo script lança exceção, com `captured_value` setado: cai no fallback,
      mesmo resultado do caso acima.
- [ ] Arquivo de resposta do step de origem ausente: **não** tenta fallback (retorna antes
      de qualquer coisa, como hoje) — token continua sem valor mesmo com `captured_value`
      setado.
- [ ] Não-regressão: `resolve_all` continua pulando token já presente em `state.tokens`.

---

## [T08] — `CurlTokenComment`: formato da linha `[Static N]`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/replay/curl_token_comment.py`, `tests/unit/test_curl_token_comment.py`

**Contexto:**
Candidato dispensado pela porta (T05) não tem `token_id` de slot — a porta roda antes de
`_find_slot`. A linha nova identifica por `path`/`origin_step`, não por token, e **não**
pode colidir com `DEPENDENCY_PATTERN` nem `UNRESOLVED_PATTERN` — é o que garante que
`parse`/`parse_anchors` (já em produção, item 9) nunca a tratem como dependência.

**Estado atual:** `CurlTokenComment` (121 linhas) não tem nenhuma linha para "candidato com
origem, mas a porta dispensou".

**Estado esperado depois:**
```python
def format_static_line(self, entries: List[Tuple[str, int]]) -> str:
    clause: str = f"# [Static {len(entries)}]"
    rendered: List[str] = [f"{path}←{step:0{self.step_index_width}d}" for path, step in entries]
    return f"{clause} {self.CATEGORY_SEPARATOR.join(rendered)}"
```

**Critérios de aceite:**
- [ ] `format_static_line([("header:Content-Type", 23)])` devolve
      `"# [Static 1] header:Content-Type←0023"`.
- [ ] `format_static_line([("header:X", 1), ("header:Y", 2)])` devolve uma linha com as
      duas entradas separadas por `"; "`.
- [ ] `CurlTokenComment.DEPENDENCY_PATTERN.match(...)` não casa com nenhuma linha produzida
      por `format_static_line` (teste explícito — é a garantia de não-colisão).
- [ ] `CurlTokenComment.UNRESOLVED_PATTERN.search(...)` idem, não casa.
- [ ] `parse_anchors` de um texto que só tem linhas `[Static N]` devolve `{}`.

---

## [T09] — `CurlGenerator`: filtra por `status`, emite `[Static N]`

**Depende de:** T01 (`status == "Static"`), T08 (`format_static_line`).
**Arquivos envolvidos:** `har_reproducer/reproduction/curl_generator.py`, `tests/unit/test_curl_generator.py`

**Contexto:**
Hoje toda linha de dependência é emitida por `origin_step is not None`, sem olhar se o
candidato tem extrator de verdade. Um candidato dispensado pela porta **tem** `origin_step`
(a porta roda depois de achar origem), então sem esta mudança ele continuaria emitindo
`# [Token ...]` — a redução de linhas de dependência não aconteceria.

**Estado atual:**
```python
def _token_comments(self, tokens: List[DynamicToken]) -> List[str]:
    lines: List[str] = [
        self.curl_token_comment.format_dependency_line(token.token_id, token.origin_step, self._origin_status(token))
        for token in tokens if token.origin_step is not None
    ]
    unresolved: List[str] = [token.path for token in tokens if token.origin_step is None]
    if unresolved:
        lines.append(self.curl_token_comment.format_unresolved_line(unresolved))
    return lines
```

**Estado esperado depois:**
```python
def _token_comments(self, tokens: List[DynamicToken]) -> List[str]:
    lines: List[str] = [
        self.curl_token_comment.format_dependency_line(token.token_id, token.origin_step, self._origin_status(token))
        for token in tokens if token.status == "Resolved"
    ]
    static: List[Tuple[str, int]] = [
        (token.path, token.origin_step) for token in tokens
        if token.status == "Static" and token.origin_step is not None
    ]
    if static:
        lines.append(self.curl_token_comment.format_static_line(static))
    unresolved: List[str] = [token.path for token in tokens if token.origin_step is None]
    if unresolved:
        lines.append(self.curl_token_comment.format_unresolved_line(unresolved))
    return lines
```

⚠️ **Verificado que `status == "Resolved"` é equivalente a "tem extrator registrado"** —
todo caminho que chega a `_register_extractor`/reaproveita slot persistido marca
`status = "Resolved"`, e nenhum outro caminho marca esse valor. Preferir esse filtro em vez
de injetar `SessionStore` no `CurlGenerator` (que exigiria mudar a assinatura de
`generate`/`__init__` e quebraria os testes existentes só por isso).
⚠️ `origin_step is not None` na linha de `static` é defensivo — hoje todo candidato com
`status == "Static"` tem `origin_step` setado (T05 só marca "Static" depois de achar
origem), mas o guard evita `None` vazando para `format_static_line`.

**Critérios de aceite:**
- [ ] Token com `status == "Resolved"` e `origin_step` setado: gera linha `[Token ...]`,
      como hoje.
- [ ] Token com `status == "Static"`: **não** gera linha `[Token ...]`; gera entrada em
      `[Static N]`.
- [ ] Dois tokens `"Static"` e um `"Resolved"` no mesmo curl: uma linha `[Token ...]`, uma
      linha `[Static 2]`.
- [ ] Token com `origin_step is None` (`"NotFound"`/`"Unresolved"`): continua em
      `[Unresolved N]`, sem mudança.
- [ ] Não-regressão: nenhum teste existente de `test_curl_generator.py` constrói um
      `DynamicToken` com `status == "Static"` hoje, então todos continuam gerando só linhas
      `[Token ...]`/`[Unresolved]`, sem alteração de saída esperada.

---

## [T10] — Fixtures: `CannedHttpHandler` roteia `/item/<qualquer>`; valores divergem

**Depende de:** Nenhuma (fixture de teste, não depende do código de produção mudado).
**Arquivos envolvidos:** `tests/support/canned_http_handler.py`, `tests/support/canned_response.py` (se precisar), `tests/fixtures/synthetic_flow.har`

**Contexto:**
Hoje o servidor canned devolve exatamente o que o `.har` sintético gravou — com a porta
(T05) ativa, `run_main` passaria a produzir 0 extratores, apagando a cobertura de todo o
pipeline de descoberta no caminho de rede. Os valores que devem continuar dinâmicos
precisam divergir entre o `.har` e o canned.

**Estado atual:** `CannedHttpHandler.CANNED_RESPONSES` é um dicionário fixo
`(método, path) → CannedResponse`; `4242` (usado em `GET /item/4242`) é servido por lookup
exato.

**Estado esperado depois:**
- `_serve` (ou onde o lookup acontece) passa a rotear `/item/<qualquer coisa>` para a
  mesma resposta, ignorando o sufixo do path — preservando o lookup exato para as demais
  rotas.
- O corpo servido para `/item/*` diverge do que `synthetic_flow.har` gravou (ex.:
  `{"id": 9999}` em vez de `{"id": 4242}`).
- `SESSIONID`, `tok_CSS_1`, `scr_NONCE_2`, `PLAINVAL777`, `PREFS` — os valores que
  `CANNED_RESPONSES` devolve para os cookies/corpo/header correspondentes passam a
  divergir dos valores gravados em `synthetic_flow.har` (ex.: `abc123sess` no `.har`,
  `abc123live` no canned).

⚠️ **`application/json` do `Content-Type` do request do step 9 fica estático** — não
diverge. Divergir exigiria o canned devolver algo como `text/json` no header de origem, o
que é semanticamente errado. A cobertura do `HeaderAgent` fica garantida por um par
header-de-request/header-de-resposta **novo**, não pela divergência deste.

**Critérios de aceite:**
- [ ] `GET /item/4242` e `GET /item/9999` contra o `CannedHttpHandler` devolvem a mesma
      resposta (roteamento por prefixo).
- [ ] As demais rotas de `CANNED_RESPONSES` continuam servidas por lookup exato, sem
      regressão (`GET /login`, `POST /api/do`, etc.).
- [ ] Os 5 valores dinâmicos citados divergem entre `synthetic_flow.har` e o que o canned
      devolve, verificável comparando os dois diretamente.
- [ ] Um novo par header-de-request/header-de-resposta cobre o `HeaderAgent` sem depender
      de `Content-Type`/`application/json`.

---

## [T11] — Fixture novo: `tests/fixtures/auth_flow.har`

**Depende de:** T10 (mesma infraestrutura de servidor canned).
**Arquivos envolvidos:** `tests/fixtures/auth_flow.har` (novo), `tests/support/canned_http_handler.py`

**Contexto:**
É o teste de aceitação da classe que motiva a etapa inteira: um login cuja resposta traz um
token, um recurso protegido que só aceita o token **vivo** (da execução), não o do `.har`.
Falha hoje (literal congelado → 403 depois de qualquer expiração/rotação simulada) e passa
depois de T01–T09.

**Estado atual:** não existe.

**Estado esperado depois:**
- `auth_flow.har`: `POST /login` → `{"token": "<TOKEN_HAR>"}`; `GET /protected` com
  `Authorization: Bearer <TOKEN_HAR>`.
- Canned: `POST /login` sempre devolve `{"token": "<TOKEN_VIVO>"}` (≠ `TOKEN_HAR`, os dois
  com ≥ 32 caracteres); `GET /protected` devolve `200` só com `Bearer <TOKEN_VIVO>`, `403`
  com qualquer outro valor (inclusive `TOKEN_HAR`).

**Critérios de aceite:**
- [ ] Servidor canned, chamado com o `TOKEN_HAR`: `GET /protected` devolve `403`.
- [ ] Servidor canned, chamado com o `TOKEN_VIVO`: `GET /protected` devolve `200`.
- [ ] `run --mode main` sobre `auth_flow.har` produz um `.curl.sh` para `/protected` com
      `Authorization: {{extractor:...}}`, não o literal.
- [ ] O `replay` desse workspace sobre o `/protected` devolve `200` (valida a ponta a
      ponta: descoberta → extração → substituição → request de verdade).

---

## [T12] — Regeneração dos goldens `run_main`/`run_dry_*` afetados

**Depende de:** T01–T11 (todo o código e todas as fixtures).
**Arquivos envolvidos:** `tests/golden/run_main/`, `tests/golden/run_dry_default/`, `tests/golden/run_dry_reset_removes_litter/`, `tests/golden/run_dry_skip_rules_methods/`

**Contexto:**
Regeneração de golden — a comparação de árvore é a verificação (TDD não se aplica aqui,
por exceção já registrada na skill `spec-e-plano`). O que importa é declarar, cenário por
cenário, **o que mudou e por quê**, para a regeneração não se confundir com regressão.

**Estado esperado depois, declarado por cenário:**
- `run_main`: número de extratores muda (perde os que a porta dispensa para os valores que
  já eram estáticos hoje — `4242` renomeado, se aplicável — mantém os que continuam
  dinâmicos); ganha linhas `[Static N]` nos curls correspondentes.
- `run_dry_*`: a porta **não** se aplica em dry (`execution_corpus=None`) — mudam só pelos
  valores novos dos fixtures (T10/T11), não pela porta. Declarar explicitamente quais
  extratores mudam de valor capturado, sem mudar de tipo de agente.

**Critérios de aceite:**
- [ ] `HAR_REPRODUCER_UPDATE_GOLDEN=1 pytest --runslow -q -k "run_main or run_dry"` grava
      as árvores novas.
- [ ] Cada árvore regravada é revisada à mão antes do commit — nenhum `.curl.sh` deveria
      conter `{{extractor:...}}` cru (falha de extração sem fallback) nem literal onde a
      spec esperava dinâmico.
- [ ] `auth_flow.har` (T11) tem cenário golden próprio, não é só regeneração — é o teste
      vermelho→verde da etapa.
- [ ] `pytest --runslow -q` inteiro verde depois da regeneração.
