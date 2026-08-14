# Plano de Implementação — Corpus Estruturado de Respostas e Chave de Origem

> Baseado em `spec.md` **revisão 2**. Ordem das tasks é topológica (nenhuma task
> depende de uma task posterior). Cada task é autocontida — não deveria ser necessário
> reabrir a spec pra executar uma task isolada.
>
> **Contrato de estado verde/vermelho.** Toda task deixa o repositório **importável e
> com `pytest tests/unit` verde**. As tasks T04, T09 e T10 deixam o **golden**
> vermelho de propósito, e cada uma declara qual classe de divergência introduz; a
> T11 fecha. Nenhuma outra task pode deixar suíte vermelha — se deixar, o plano está
> errado e é para parar.

---

## [T01] — `ValueVariants`: extrair as variantes de encoding de `ResponseGrep`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/value_variants.py` (novo, `ValueVariants`), `har_reproducer/tracking/response_grep.py`, `har_reproducer/tracking/token_location_detector.py`, `har_reproducer/tracking/__init__.py`, `tests/unit/test_response_grep_helpers.py`

**Contexto:**
`ResponseGrep` acumula três papéis: gerar variantes de encoding, listar respostas elegíveis por causalidade temporal, e buscar. Na T04 ele deixa de ser classe de utilidade sem estado e passa a receber colaborador por construtor. Manter dentro dele um utilitário que **outra** classe consome estaticamente (`TokenLocationDetector._value_present` chama `ResponseGrep.value_variants`) misturaria os papéis. Task puramente estrutural — nenhum comportamento muda (spec 3.1).

**Estado atual:**
- `ResponseGrep.try_decode(value)`, `ResponseGrep.value_variants(value)`, `ResponseGrep._deduplicate(values)`.
- `TokenLocationDetector._value_present` chama `ResponseGrep.value_variants(value)`.
- `tests/unit/test_response_grep_helpers.py` exercita `try_decode`, `value_variants` e `_extract_step_index`.

**Estado esperado depois:**
- Arquivo novo `tracking/value_variants.py` com `ValueVariants`: `try_decode` (`@staticmethod`), `of` (`@classmethod`, era `value_variants`), `_deduplicate` (`@staticmethod`) — **corpos idênticos**, só movidos.
- `ResponseGrep` perde os três e chama `ValueVariants.of(pattern)`. `_extract_step_index` e `_eligible_response_files` **continuam** nele (saem na T04).
- `TokenLocationDetector._value_present` chama `ValueVariants.of(value)`.
- `tracking/__init__.py` exporta `ValueVariants` (mantendo `ResponseGrep`), `__all__` em ordem alfabética.
- `tests/unit/test_response_grep_helpers.py`: os quatro testes de variantes apontam para `ValueVariants`. ⚠️ Os dois testes de `_extract_step_index` **continuam apontando para `ResponseGrep` nesta task** — a T04 é que os move, junto com o método.
- ⚠️ A **ordem** das variantes (`cru`, `decodificado`, `URL-encode`, `base64-encode`) é significativa (a primeira que casar vence) e não pode ser alterada.
- ⚠️ `value_variants` → `of` é renomeação deliberada; não deixar alias.

**Critérios de aceite:**
- [x] `ValueVariants.try_decode("valor%20com%20espaco")` retorna `"valor com espaco"`.
- [x] `ValueVariants.try_decode(base64.b64encode(b"segredo").decode("ascii"))` retorna `"segredo"`.
- [x] `ValueVariants.of("abc")` não tem duplicatas nem string vazia, e `ValueVariants.of("abc")[0] == "abc"`.
- [x] `grep -rn "ResponseGrep.value_variants\|ResponseGrep.try_decode" har_reproducer/ tests/` não retorna nada.
- [x] Não-regressão: `uv run pytest` passa **inteiro**, golden incluído — a task não altera comportamento observável.

---

## [T02] — `models`: `OriginContainer`, `OriginMatch` e os dois campos de `DynamicToken`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/analysis.py`, `har_reproducer/models/session.py`, `har_reproducer/models/__init__.py`, `tests/unit/test_origin_match.py` (novo)

**Contexto:**
`ResponseGrep.find` devolve `Tuple[int, str]` com um `filename` que ninguém lê. A T04 troca por um model que carrega, além do step de origem, a **chave** da resposta de origem onde o valor mora (`ETag`) e o **container** dessa chave (header/cookie). O container não é decoração: sem ele, `AgentFactory` não tem como saber se a chave descoberta serve ao agente escolhido, e valor presente em cookie **e** header vira regressão (spec 3.4/3.7).

**Estado atual:**
- `models/analysis.py` tem só `StepAnalysis`, e importa apenas `Dict, List` de `typing`.
- `DynamicToken` tem `token_id`, `path`, `current_value`, `destination_location`, `origin_location`, `origin_step`, `status`, `extraction_exhausted`.

**Estado esperado depois:**
- `models/analysis.py` ganha (⚠️ acrescentar `Optional` ao import de `typing` e `Enum` ao de `enum`):
  ```python
  class OriginContainer(str, Enum):
      HEADER = "Header"
      COOKIE = "Cookie"

  class OriginMatch(BaseModel):
      step_index: int
      origin_key: Optional[str] = None
      origin_container: Optional[OriginContainer] = None
  ```
- `DynamicToken` ganha `origin_key: Optional[str] = None` e `origin_container: Optional[OriginContainer] = None`, declarados **depois** de `origin_step` e **antes** de `status`.
- `models/__init__.py` exporta `OriginContainer` e `OriginMatch` (import e `__all__`, ordem alfabética).
- Arquivo de teste novo `tests/unit/test_origin_match.py` — os critérios abaixo precisam de casa.
- ⚠️ **Não** adicionar campos espelho em `Extractor`: só têm consumidor no cache-miss; persistir seria campo morto em todo `.meta.json` (spec 3.5).
- ⚠️ `origin_step` continua `Optional[int]`.

**Critérios de aceite:**
- [x] `OriginMatch(step_index=7)` é válido, com `origin_key is None` e `origin_container is None`.
- [x] `OriginMatch(step_index=7, origin_key="ETag", origin_container=OriginContainer.HEADER)` preserva os três campos.
- [x] `OriginContainer("Cookie") is OriginContainer.COOKIE`.
- [x] `DynamicToken(...)` construído como todos os call sites atuais fazem continua válido, com os dois campos novos em `None`.
- [x] `from har_reproducer.models import OriginContainer, OriginMatch` funciona.
- [x] Não-regressão: `uv run pytest` passa inteiro; nenhum `.meta.json` do golden muda.

---

## [T03] — `ResponseCorpus`: corpus estruturado com memoização por step

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/response_corpus.py` (novo), `har_reproducer/tracking/__init__.py`, `tests/unit/test_response_corpus.py` (novo)

**Contexto:**
A busca de origem roda `grep -lF <valor> res_NNNN.json` sobre o **texto do arquivo** — a serialização Pydantic de `StepResponse`, onde o body é uma string JSON com aspas e barras escapadas. Valor contendo `"` nunca casa consigo mesmo: medido, 63 candidatos (todos ETags `W/"9b1-19a1d941a25"` em `header:If-None-Match`) são descartados por isso. Esta task cria o corpus que expõe o **conteúdo real** (spec 3.2).

**Estado atual:**
- Não existe. A leitura está partida entre `ResponseGrep._eligible_response_files` e `CandidateResolver._load_response`.

**Estado esperado depois:**
- `ResponseCorpus`, recebendo `responses_dir: Path` e `step_index_width: int` por construtor (o width monta `res_{index:0{width}d}.json` em `response()`), com dois dicionários de memoização como atributos.
- `eligible_indexes(before_step_index) -> List[int]` — glob de `res_*.json`, índice extraído do nome, mantém `< before_step_index`, devolve **ordenado crescente**. É aqui que mora a causalidade temporal.
- `response(step_index) -> Optional[Dict[str, Any]]` — lê e desserializa, **memoizando por índice**. Tratamento de erro idêntico ao de `_load_response`: `except Exception` + `print(f"[AVISO] Falha ao carregar response do step {step_index}: {e}")` + `return None`; arquivo inexistente devolve `None` sem print.
- `searchable_text(step_index) -> Optional[str]` — `None` se `response()` for `None`; senão a serialização, memoizada, nesta ordem fixa, unida por `"\n"`: headers como `f"{name}: {value}"`; cookies como `f"{name}={value}"`; `redirect_url` se não vazio; `body` decodificado (`bytes` → `decode("utf-8", errors="replace")`) se não vazio.
- `_extract_step_index(filename)` — corpo idêntico ao de `ResponseGrep` (que ainda mantém o seu até a T04).
- ⚠️ **A memoização é obrigatória, não otimização.** Medido: sem ela, uma execução completa faz 121.318 desserializações a 0,091 ms = ~11 s, contra ~5 s do `grep` atual — a troca de corpus viraria regressão de performance.
- ⚠️ **`eligible_indexes` nunca é memoizado**: em `--mode main` o diretório cresce durante a execução.
- ⚠️ **Falha não é memoizada**: um `res_NNNN.json` ainda não escrito passa a existir depois; cachear `None` congelaria a ausência.
- ⚠️ `response()` devolve o `Dict` cru, **não** `StepResponse`: é ele que vira `response_sample` para `TokenLocationDetector`/`Agent` e que `ExtractorTemplate.render_temp_script` embute.
- ⚠️ O corpus descarta `status_code`, `body_mime`, `skipped`, `skip_reason` e nomes de campo JSON, que o texto do arquivo continha. Aperto intencional (spec 3.2).

**Critérios de aceite:**
- [x] `eligible_indexes(3)` sobre diretório com `res_0000.json`…`res_0005.json` retorna `[0, 1, 2]`; `eligible_indexes(0)` retorna `[]`.
- [x] Arquivo com nome fora do padrão é ignorado sem quebrar.
- [x] Resposta com `headers={"ETag": 'W/"9b1-19a1d941a25"'}` → `searchable_text` **contém** `W/"9b1-19a1d941a25"` com aspas cruas (o caso que o `grep` sobre arquivo não acha).
- [x] Resposta com body `'{"token":"abc"}'` → `searchable_text` contém `{"token":"abc"}` sem barras de escape.
- [x] Resposta totalmente vazia → `searchable_text` retorna `""`, não `None`.
- [x] `response(7)` de arquivo inexistente retorna `None` sem lançar; de JSON corrompido retorna `None` e imprime aviso.
- [x] **Memoização**: duas chamadas a `searchable_text(1)` leem o arquivo uma vez (verificar apagando o arquivo entre as chamadas e conferindo que a segunda ainda devolve o texto).
- [x] **Não memoiza falha**: `response(9)` com arquivo ausente devolve `None`; criado o arquivo, a chamada seguinte devolve o conteúdo.
- [x] **Não memoiza `eligible_indexes`**: `eligible_indexes(9)` devolve `[0]`; criado `res_0001.json`, a chamada seguinte devolve `[0, 1]`.
- [x] Não-regressão: `uv run pytest` passa inteiro (a classe ainda não tem consumidor).

---

## [T04] — `OriginFinder` (era `ResponseGrep`): buscar no corpus e devolver `OriginMatch`

**Depende de:** T01 (`ValueVariants`), T02 (`OriginMatch`), T03 (`ResponseCorpus`).
**Arquivos envolvidos:** `har_reproducer/tracking/origin_finder.py` (novo), `har_reproducer/tracking/response_grep.py` (removido), `har_reproducer/tracking/__init__.py`, `har_reproducer/tracking/candidate_resolver.py` (só o import e a chamada, mínimo para o repo importar), `tests/unit/test_response_grep_helpers.py` (renomear para `tests/unit/test_origin_finder.py`), `tests/unit/test_response_corpus.py`

**Contexto:**
A classe deixa de rodar `subprocess`/`grep` sobre arquivos e passa a buscar no `searchable_text` do corpus. Além de fechar a falha de escape, o corpus dá acesso à resposta desserializada, o que permite descobrir **sob qual chave e em qual container** o valor mora na origem — informação que hoje se perde (spec 3.3/3.4). O nome muda porque não sobra nenhum `grep`.

**Estado atual:**
```python
class ResponseGrep:
    @classmethod
    def find(cls, responses_dir: Path, pattern: str, before_step_index: int) -> Optional[Tuple[int, str]]:
        candidate_files = cls._eligible_response_files(responses_dir, before_step_index)
        if not candidate_files:
            return None
        for variant in ValueVariants.of(pattern):          # após T01
            match = cls._grep_single_pattern(candidate_files, variant)
            if match is not None:
                return match
        return None

    @classmethod
    def _grep_single_pattern(cls, candidate_files, pattern):
        cmd = ["grep", "-lF", pattern, *(str(p) for p in candidate_files)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        ...
        first_match_file = sorted(result.stdout.splitlines())[0]
        ...
```

**Estado esperado depois:**
- `OriginFinder` em `tracking/origin_finder.py`, classe de instância: `__init__(self, corpus: ResponseCorpus)`.
- `find(self, value: str, from_step_index: int, before_step_index: int) -> Optional[OriginMatch]` — filtra `corpus.eligible_indexes(before_step_index)` por `>= from_step_index`; para cada variante de `ValueVariants.of(value)`, **na ordem**, varre os índices **crescentes** e devolve no primeiro `searchable_text` que contenha a variante.
- `_origin_key`/`_origin_container` implementam a regra da spec 3.4: só quando a variante é a **crua** (`variant == value`) e existe **cookie** (primeiro) ou **header** (depois) cujo valor é **exatamente igual** à variante; devolve o nome da chave e o container. `None` nos demais casos.
- `tracking/__init__.py`: exporta `OriginFinder` e `ResponseCorpus`, remove `ResponseGrep`. `response_grep.py` é apagado.
- `candidate_resolver.py` recebe **apenas** o ajuste mínimo de import/chamada para o repositório continuar importável — a mudança de assinatura do construtor é a T05.
- `tests/unit/test_response_grep_helpers.py` vira `tests/unit/test_origin_finder.py`; ⚠️ os **dois testes de `_extract_step_index` migram para `tests/unit/test_response_corpus.py`**, porque o método foi para lá na T03 (é a contradição que a revisão 1 deste plano tinha entre T01 e T04).
- ⚠️ **Comportamento preservado, é observável:** a ordem das variantes manda sobre a ordem dos steps (esgota todos os steps com a variante 1 antes da variante 2); desempate pelo **menor índice**.
- ⚠️ **Nota sobre o desempate:** hoje ele é ordenação **lexicográfica de nomes de arquivo**, equivalente a "menor índice" só porque `STEP_INDEX_WIDTH = 4` é fixo. Ordenar inteiros é a intenção original e vale para todo workspace que o `Workspace` produz.
- ⚠️ **Mudança deliberada de comportamento:** valores multi-linha passam a exigir casamento integral. `grep -F` com padrão contendo `\n` trata cada linha como padrão alternativo (OR) — hoje um candidato multi-linha acha origem se **qualquer** linha sua estiver na resposta. `variant not in text` é estrito. Medido: 0 candidatos com `\n` no workspace real, mas precisa de teste próprio.
- ⚠️ `from_step_index` é **obrigatório**, sem default — é o que a T05 usa para o cache de negativos, e um default esconderia a decisão.
- ⚠️ `origin_key` **nunca** por substring (é o caso `Sec-Fetch-Site` × `Cross-Origin-Opener-Policy` da spec de 04/08) nem por variante transformada (o agente é verificado contra o valor cru).
- ⚠️ **Precedência cookie → header**, idêntica a `TokenLocationDetector.find`. Invertida, produz regressão: valor nos dois containers → `CookieAgent` com nome de header como chave.

**Critérios de aceite:**
- [x] Corpus com `res_0001.json` de header `{"ETag": 'W/"9b1-abc"'}`: `find('W/"9b1-abc"', 0, 5)` retorna `OriginMatch(step_index=1, origin_key="ETag", origin_container=HEADER)`.
- [x] Mesmo corpus, `find('W/"9b1-abc"', 0, 1)` retorna `None` (causalidade temporal).
- [x] `find(valor, 3, 10)` ignora respostas de índice `< 3` (janela inferior).
- [x] Valor presente cru em `res_0002` e `res_0004` → `step_index == 2` (menor índice).
- [x] Valor cru em `res_0004` e base64 em `res_0002` → `step_index == 4` (variante crua vence a ordem dos steps).
- [x] Valor presente **num cookie e num header** da mesma resposta → `origin_container is COOKIE` e `origin_key` é o nome do cookie.
- [x] Valor que casa só no body → `origin_key is None` e `origin_container is None`.
- [x] Valor que é **substring** do valor de um header (`same-origin` em `same-origin-allow-popups`) → casa, mas `origin_key is None`.
- [x] Valor que casa por variante base64 num header → `origin_key is None`.
- [x] **Multi-linha**: valor `"AAA\nBBB"` com resposta contendo só `BBB` → `None` (hoje o `grep` casaria).
- [x] `grep -rn "subprocess" har_reproducer/tracking/` não retorna nada; `har_reproducer/tracking/response_grep.py` não existe.
- [x] Não-regressão: `uv run pytest tests/unit` passa inteiro. **Golden diverge nesta task** (classe (a): 63 ETags passam a ter origem) — esperado, fechado na T11.

---

## [T05] — `CandidateResolver` + `EngineFactory`: corpus por construtor, `origin_key` e cache de negativos

**Depende de:** T04.
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py`, `har_reproducer/engines/construction/engine_factory.py`, `tests/unit/test_candidate_resolver.py`, `tests/unit/test_engine_factory.py`

**Contexto:**
`CandidateResolver` é o único consumidor de `OriginFinder.find`, e `EngineFactory` é a única raiz de composição que o constrói. As duas mudanças **têm que estar no mesmo commit**: separadas, o commit intermediário deixa `EngineFactory` passando 5 posicionais para um `__init__` de 6 e o repositório não executa. Além da troca de colaborador, esta task fecha o buraco de performance: `_find_origin` hoje **só cacheia positivos**, então um candidato sem origem é rebuscado do zero a cada uma de suas ocorrências (spec 1.3 e 3.6).

**Estado atual:**
```python
    def __init__(self, responses_dir: Path, session_store, extractor_runner, metadata_store, agent_factory) -> None:
        self.responses_dir: Path = responses_dir
        ...
        self._origin_cache: Dict[str, Tuple[int, str]] = {}

    def _find_origin(self, value, step_index):
        cached_origin = self._origin_cache.get(value)
        if cached_origin is not None:
            return cached_origin
        origin = ResponseGrep.find(self.responses_dir, value, step_index)
        if origin is not None:
            self._origin_cache[value] = origin
        return origin
```
e, em `engine_factory.py:90-92`:
```python
        candidate_resolver: CandidateResolver = CandidateResolver(
            tracking_responses_dir, session_store, extractor_runner, metadata_store, agent_factory
        )
```
e, em `tests/unit/test_engine_factory.py:40`:
```python
    assert engine.tracker.candidate_resolver.responses_dir == workspace.original_responses
```

**Estado esperado depois:**
- Construtor: `response_corpus: ResponseCorpus` e `origin_finder: OriginFinder` entram como **primeiros** parâmetros, no lugar de `responses_dir`; os demais na mesma ordem.
- `self.responses_dir` some; `_check_persisted_slot` passa a usar `self.response_corpus.responses_dir` na chamada a `extractor_runner.run_existing`. ⚠️ **Não** mudar a assinatura de `ExtractorRunner.run_existing`. Isso é acoplamento a atributo de outro objeto (Demeter), **aceito como dívida declarada** (spec 3.6).
- `_origin_cache: Dict[str, OriginMatch]` e novo `_origin_misses: Dict[str, int]`.
- `_find_origin(value, step_index)`: positivo no cache → devolve; senão chama `self.origin_finder.find(value, self._origin_misses.get(value, 0), step_index)`; se `None`, grava `self._origin_misses[value] = step_index` e devolve `None`; se achou, grava em `_origin_cache`.
- `_process_candidate` grava `origin_step`, `origin_key` **e** `origin_container` antes de derivar o `token_id`.
- `_load_response` removido; `_generate_new_extractor` chama `self.response_corpus.response(candidate.origin_step)`.
- `EngineFactory.create` monta `ResponseCorpus(tracking_responses_dir, Workspace.STEP_INDEX_WIDTH)` e repassa o **corpus** a `_build_tracker`, que monta `OriginFinder(response_corpus)` e injeta os dois.
- `tests/unit/test_engine_factory.py:40` passa a asserir `...candidate_resolver.response_corpus.responses_dir`.
- `tests/unit/test_candidate_resolver.py:32` passa a construir com corpus + finder.
- ⚠️ `TokenResolver` **continua** recebendo `tracking_responses_dir: Path` — não descobre origem, não sofre nenhuma das falhas.
- ⚠️ A escolha `real_responses` × `original_responses` por modo **não muda**.
- ⚠️ O cache de negativos é **monotônico e correto**: `_origin_misses[value] = N` afirma só "não achei entre os steps `< N`"; consulta em `M > N` varre `[N, M)`. Uma resposta já gravada não muda.
- ⚠️ `_origin_cache` continua chaveado só pelo valor (`docs/20260805 Regressão de Cache de Origem no CandidateResolver`). Compartilhar `origin_key`/`origin_container` entre paths distintos de mesmo valor é **correto por construção** — são função de `(valor, resposta)`, não do path.
- ⚠️ `_derive_token_id` continua `md5(f"{path}:{origin_step}")`; `origin_key` **não** entra no hash.
- ⚠️ O ramo de cache-hit continua **não** preenchendo `origin_location` (bug §3.2 do relatório de 11/08). Fora de escopo; não mexer de passagem.

**Critérios de aceite:**
- [x] Candidato cujo valor está no header `ETag` de resposta anterior termina com `origin_step` correto, `origin_key == "ETag"` e `origin_container is OriginContainer.HEADER`.
- [x] Candidato sem origem termina `status == "NotFound"` com os três campos em `None`.
- [x] Candidato cujo valor casa no body termina com `origin_key is None` e `origin_step` correto.
- [x] **Cache de negativos**: valor sem origem consultado no step 5 e depois no step 9 faz `origin_finder.find` ser chamado com `from_step_index=0` na primeira e `from_step_index=5` na segunda (dublê que registra as chamadas).
- [x] **Cache de negativos não esconde origem nova**: valor sem origem no step 5; gravada uma resposta no step 6; consulta no step 9 encontra a origem.
- [x] **Cache de positivos preservado**: duas consultas do mesmo valor com origem fazem uma única chamada a `find`.
- [x] `grep -rn "_load_response" har_reproducer/` não retorna nada.
- [x] `EngineFactory.create(EngineMode.DRY, ...)` produz `CandidateResolver` cujo corpus aponta para `workspace.original_responses`; `EngineMode.MAIN`, para `workspace.real_responses`.
- [x] `TokenResolver` recebido pelo engine continua com o mesmo `responses_dir` em ambos os modos.
- [x] Não-regressão: `uv run pytest tests/unit` passa **inteiro** (é o ponto onde a revisão 1 deste plano errava). Golden continua divergindo pela classe (a) da T04.

---

## [T06] — `BaseAgent`/`AgentFactory`: chave de origem, só quando o container concorda

**Depende de:** T02 (campos no model), T05 (campos preenchidos).
**Arquivos envolvidos:** `har_reproducer/agents/base_agent.py`, `har_reproducer/agents/construction/agent_factory.py`, `tests/unit/test_base_agent.py`, `tests/unit/test_agent_factory.py`, `tests/unit/test_agents_strategies.py`

**Contexto:**
`BaseAgent.key` deriva sempre de `candidate.path`, o caminho no **request** (`header:If-None-Match`), mas todas as estratégias determinísticas aplicam essa chave **sobre a resposta de origem**, onde o valor mora sob outra chave (`ETag`). Medido: 86 candidatos nessa situação (63 `ETag`, 21 `Last-Modified`, 2 `Pragma`), e em nenhum a resposta de origem tem a chave de destino. Cada um queima 5 tentativas de LLM com 5 s de sleep entre elas: 430 chamadas e ~36 min depois da T04, dos quais 115 chamadas e ~9,6 min **já são desperdiçados hoje** pelos 23 que já acham origem (spec 3.7).

**Estado atual:**
```python
    def __init__(self, token_id, response_sample, expected_value, workspace, script_executor, sleeper,
                 path=None, location=None, llm=None) -> None: ...

    @property
    def key(self) -> Optional[str]:
        if self.path is None:
            return None
        if ":" in self.path:
            return self.path.split(":", 1)[1]
        return self.path
```
e `AgentFactory.create` passando `path=candidate.path, location=..., llm=self.llm`.

**Estado esperado depois:**
- `BaseAgent.__init__` ganha `origin_key: Optional[str] = None`, **entre** `location` e `llm`, guardado em `self.origin_key`.
- `key` prefere `self.origin_key` quando não for `None`; senão o comportamento de hoje.
- `AgentFactory` ganha `CONTAINER_LOCATIONS: ClassVar[Dict[OriginContainer, TokenLocation]]` (`HEADER→HEADER`, `COOKIE→COOKIE`) e `_origin_key_for(candidate)`, que devolve `candidate.origin_key` **apenas** se `CONTAINER_LOCATIONS.get(candidate.origin_container) == candidate.origin_location`; `None` caso contrário. `create` passa `origin_key=self._origin_key_for(candidate)`.
- ⚠️ O guard de container impede **três** regressões: (1) `CookieAgent` recebendo nome de header e vice-versa; (2) `RegexAgent._key_pattern` procurando um nome de header dentro de um bundle JS — com `origin_location` em `SCRIPT`/`BODY_*` o container nunca concorda; (3) o guard `if not key or key == "body"` de `_key_pattern` continuar significando o que significa.
- ⚠️ `HeaderAgent`, `CookieAgent` e `RegexAgent` **não mudam nenhuma linha** — todos os call sites usam argumentos nomeados, verificado.

**Critérios de aceite:**
- [x] `BaseAgent(..., path="header:If-None-Match", origin_key="ETag").key == "ETag"`.
- [x] `BaseAgent(..., path="header:If-None-Match", origin_key=None).key == "If-None-Match"` (comportamento de hoje).
- [x] `BaseAgent(..., path=None, origin_key=None).key is None`.
- [x] `HeaderAgent` com `origin_key="ETag"`, `expected_value='W/"9b1-abc"'` e `response_sample` cujo header `ETag` vale `W/"9b1-abc"`: a **primeira** estratégia determinística (`_by_name`) verifica com sucesso — zero tentativas de LLM.
- [x] `AgentFactory.create` com `origin_container=HEADER` e `origin_location=HEADER` propaga o `origin_key`.
- [x] `AgentFactory.create` com `origin_container=HEADER` e `origin_location=COOKIE` **não** propaga (agente recebe `origin_key=None`).
- [x] `AgentFactory.create` com `origin_location=SCRIPT` **não** propaga, qualquer que seja o container.
- [x] Não-regressão: `uv run pytest tests/unit` passa; agente sem `origin_key` gera exatamente o mesmo código de antes.

---

## [T07] — `RegexAgent._context_pattern`: âncora de fim e classe preguiçosa

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/agents/regex_agent.py`, `tests/unit/test_agents_strategies.py`

**Contexto:**
A spec de 04/08 (decisão 3.2, bloco ⚠️ "achado durante a implementação") corrigiu `HeaderAgent`/`CookieAgent` para usar classe **preguiçosa** + lookahead do caractere que segue o valor, porque um quantificador guloso sem âncora consome o delimitador quando ele pertence à classe do valor. `RegexAgent._context_pattern` ficou de fora. Consequência: quando `expected_value` contém caractere fora de `[\w\-.]` (qualquer `/`), `value_char_class()` devolve `.+?` que, sem âncora de fim, casa exatamente **um** caractere (spec 3.8).

**Estado atual:**
```python
        prefix: str = body[max(0, pos - 20):pos]
        if not prefix.strip():
            return None
        return rf"{re.escape(prefix)}({self.value_char_class()})"
```

**Estado esperado depois:**
```python
        prefix: str = body[max(0, pos - 20):pos]
        if not prefix.strip():
            return None
        end: int = pos + len(self.expected_value)
        boundary: str = rf"(?={re.escape(body[end])})" if end < len(body) else "$"
        return rf"{re.escape(prefix)}({self.lazy_value_char_class()}){boundary}"
```
- ⚠️ `_key_pattern` **não muda**: lá o grupo já é delimitado pelo contexto `chave: valor` à esquerda, e não há defeito observado.
- ⚠️ "Falha sempre" seria exagero: para `expected_value` de **um** caractere, o `.+?` sem âncora acerta. O defeito é para valores de 2+ caracteres.
- ⚠️ Churn medido: dos 57 extratores persistidos, 7 são `RegexAgent`; 5 vieram de LLM (não passam por `_context_pattern`) e **2 são determinísticos**. Nos dois, o caractere seguinte está fora de `[\w\-.]`, então guloso e preguiçoso-com-lookahead capturam o mesmo grupo: **muda o texto do regex, não o valor extraído**.

**Critérios de aceite:**
- [x] Body `abc: token123-suffix`, `expected_value="token123"`: o grupo 1 é exatamente `"token123"` (hoje o guloso leva `-suffix`).
- [x] Body `import x from '/src/a/B.js'`, `expected_value="/src/a/B.js"`: o grupo 1 é exatamente `/src/a/B.js` (hoje `.+?` sem âncora casa só `/`).
- [x] `expected_value` terminando no fim do body gera padrão com `$` no lugar do lookahead.
- [x] `expected_value` de um caractere continua funcionando (não-regressão da borda).
- [x] `expected_value` ausente do body continua devolvendo `None`; prefixo só com espaço continua devolvendo `None`.
- [x] Não-regressão: `uv run pytest tests/unit/test_agents_strategies.py` passa; nenhum caso que hoje verifica passa a falhar.

---

## [T08] — `CurlTokenComment`: cláusula de auditoria para valores sem origem

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/replay/curl_token_comment.py`, `tests/unit/test_curl_token_comment.py`

**Contexto:**
Candidato que termina `NotFound` não deixa **nenhum** rastro no `.curl.sh` (`CurlGenerator._token_comments` pula todo token com `origin_step is None`). É essa ausência que faz `optimize` reportar `SUCCESSFUL` sobre um schedule cheio de literais congelados do HAR (relatório de 11/08, seções 3.1/3.4). Esta task cria o formato; a T09 o emite (spec 3.9).

**Estado atual:**
- `DependencyPhrase`, `OriginStatusPhrase`, `ReplayStatusPhrase`, e `CurlTokenComment` com `CATEGORY_SEPARATOR`, `CLAUSE_CLOSING_MARKER`, `DEPENDENCY_PATTERN`, `format_dependency_line`, `with_replay_status`, `parse`.

**Estado esperado depois:**
- `UNRESOLVED_PATTERN: ClassVar[Pattern[str]] = re.compile(r"^# \[Unresolved (?P<count>\d+)\] (?P<paths>.+)$", re.MULTILINE)`.
- `format_unresolved_line(self, paths: List[str]) -> str` — `f"# [Unresolved {len(paths)}] " + CATEGORY_SEPARATOR.join(paths)`.
- `parse_unresolved(self, curl_text: str) -> List[str]` — paths da primeira ocorrência, ou `[]`.
- ⚠️ O contrato de colchetes da etapa de 12/08 **não pode ser afrouxado**: cláusula entre `[` e `]`, e nenhuma anotação de replay é anexada à linha `[Unresolved ...]`.
- ⚠️ `UNRESOLVED_PATTERN` e `DEPENDENCY_PATTERN` não podem se casar cruzado (a palavra após `[` difere). Precisa de teste explícito nos dois sentidos.
- ⚠️ Medido no workspace real: maior linha gerada tem **208 caracteres** e nenhum dos 22 paths contém `"; "` ou `\n`, então o `split(CATEGORY_SEPARATOR)` é seguro.

**Critérios de aceite:**
- [x] `format_unresolved_line(["header:Accept", "url"])` retorna `# [Unresolved 2] header:Accept; url`.
- [x] `parse_unresolved(format_unresolved_line(["a", "b"]))` retorna `["a", "b"]` (round-trip).
- [x] `parse_unresolved("")` e `parse_unresolved("#!/bin/bash\ncurl -X GET x")` retornam `[]`.
- [x] `DEPENDENCY_PATTERN.findall(format_unresolved_line(["a"]))` é vazio.
- [x] `parse_unresolved(format_dependency_line("abc123", 7))` é `[]`.
- [x] `parse` continua achando a dependência num texto que contenha **as duas** linhas.
- [x] Não-regressão: `uv run pytest` passa **inteiro** — a task só acrescenta API, ninguém a chama ainda.

---

## [T09] — `CurlGenerator`: emitir a linha consolidada de valores sem origem

**Depende de:** T08.
**Arquivos envolvidos:** `har_reproducer/reproduction/curl_generator.py`, `tests/unit/test_curl_generator.py`

**Contexto:**
Com o formato da T08 pronto, o gerador registra no `.curl.sh` **o que** ficou congelado como literal por não ter origem descoberta (spec 3.9).

**Estado atual:**
```python
    def _token_comments(self, tokens: List[DynamicToken]) -> List[str]:
        lines: List[str] = []
        for token in tokens:
            if token.origin_step is None:
                continue
            lines.append(self.curl_token_comment.format_dependency_line(
                token.token_id, token.origin_step, self._origin_status(token)
            ))
        return lines
```

**Estado esperado depois:**
```python
    def _token_comments(self, tokens: List[DynamicToken]) -> List[str]:
        lines: List[str] = [
            self.curl_token_comment.format_dependency_line(
                token.token_id, token.origin_step, self._origin_status(token)
            )
            for token in tokens if token.origin_step is not None
        ]
        unresolved: List[str] = [token.path for token in tokens if token.origin_step is None]
        if unresolved:
            lines.append(self.curl_token_comment.format_unresolved_line(unresolved))
        return lines
```
- ⚠️ **Uma** linha consolidada por step, nunca uma por candidato: medido, 1.035 ocorrências sem origem espalhadas por **235 dos 238 steps** (133 steps com 4 paths, 74 com 5, 11 com 6, cauda até 10).
- ⚠️ A linha lista **paths**, nunca valores — não escreve credencial no arquivo.
- ⚠️ A linha vem **depois** de todas as linhas de dependência, e a ordem dos paths segue a ordem dos tokens recebidos (ordem de `BaselineDiff.detect_candidates`) — determinismo é requisito do golden.
- ⚠️ `_origin_status` **não muda**.
- ⚠️ **Golden diverge nesta task** (classe (c): praticamente todo `.curl.sh` ganha a linha) — esperado, fechado na T11.

**Critérios de aceite:**
- [x] Um token resolvido (`origin_step=3`) e dois sem origem → 2 linhas: a de dependência e `# [Unresolved 2] <path1>; <path2>`, nessa ordem.
- [x] Nenhum token sem origem → exatamente as linhas de dependência de antes.
- [x] Só tokens sem origem → exatamente uma linha, e o curl continua com o bloco de comando abaixo dela.
- [x] Lista vazia → curl sem comentário nenhum.
- [x] Não-regressão: `uv run pytest tests/unit` passa; a montagem do bloco `curl` não muda. Golden diverge (classe (c)).

---

## [T10] — `HARParser`/`Engine`: avisar quando o HAR não gravou corpo de resposta

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/fs_io/har_parser.py`, `har_reproducer/engines/engine.py`, `tests/unit/test_har_parser.py`, `tests/unit/test_engine.py`

**Contexto:**
`HARParser.parse_entry` transforma `content` sem `text` (ou com `text` vazio) em `body=""` silenciosamente. Medido no `progressofit.har`: 140 de 238 entries nessa situação — mas **124 delas são `304 Not Modified`**, que por definição não têm corpo. O sinal acionável é **12**, e a entry `154` (`POST /auth/login`, status 200, corpo vazio), origem do JWT do relatório de 11/08, está entre eles. O README declara HAR completo como pré-condição; hoje a violação é invisível (spec 3.10).

**Estado atual:**
```python
    def _reproduce(self) -> bool:
        entries: List[Dict[str, Any]] = HARParser.get_entries(self.har_path)
        first_entry: Step = HARParser.parse_entry(entries[0], 0)
        last_response: Optional[StepResponse] = None
        for index, entry in enumerate(entries):
            response: StepResponse = self._process_entry(index, entry, first_entry)
            if not response.skipped:
                last_response = response
        return self._validate_final(last_response)
```
⚠️ `_reproduce` **não tem o `Step`** — `HARParser.parse_entry` roda dentro de `_process_entry`, que devolve o `StepResponse` da **execução**, não a resposta gravada no HAR.

**Estado esperado depois:**
- `HARParser` ganha `BODYLESS_STATUS_CODES: ClassVar[Set[int]] = {101, 204, 304}` e `entries_missing_response_body(entries: List[Dict[str, Any]]) -> int`, que conta entries cujo status **não** está nesse conjunto e cujo `content.text` é vazio/ausente.
- `Engine._reproduce` chama isso com as `entries` que já tem e delega a um método privado que imprime uma vez, só quando maior que zero, **antes** do `Final Validation Result`:
  ```
  WARNING: 12 de 238 entries do HAR não têm corpo de resposta gravado (excluídos os
  status 101/204/304, que normalmente não carregam corpo). Origens de token que
  estejam nesses corpos são indescobríveis — regrave o HAR preservando o conteúdo das
  respostas ("Preserve log" + export completo).
  ```
- ⚠️ A contagem mora no `HARParser` porque é ele que já conhece o formato do HAR — e assim **nenhum estado novo** entra em `Engine` (um contador em atributo tornaria `run()` não idempotente).
- ⚠️ `BODYLESS_STATUS_CODES` é conhecimento de protocolo hardcoded e é **exceção consciente** ao princípio de genericidade, declarada na spec 3.10: sem o recorte, o aviso diria "140 de 238" num HAR correto, 89% disso `304`.
- ⚠️ **Não** transformar em erro nem alterar o retorno de `run()`. `DryEngine` herda `_reproduce` sem alteração própria.
- ⚠️ **Golden diverge nesta task** (classe (d): `stdout.txt`) — medido, `tests/fixtures/synthetic_flow.har` tem 2 de 10 entries com `content.text` vazio, então o WARNING dispara em **todo** golden de `run` e nos de `replay` cujo `stdout.txt` vem do `run`.

**Critérios de aceite:**
- [x] `entries_missing_response_body` sobre 3 entries, 2 sem corpo e status 200, retorna `2`.
- [x] Entry com status `304` e sem corpo **não** é contada; com status `204` e `101` também não.
- [x] Entry com `content` sem a chave `text` e entry com `text: ""` são contadas igualmente.
- [x] HAR com todas as entries com corpo → `0`, e nenhum aviso impresso.
- [x] `run` sobre HAR com entries sem corpo imprime o aviso **uma única vez**, antes do `Final Validation Result`.
- [x] O retorno de `run()` é o mesmo de antes da task para o mesmo HAR (comparar com o baseline).
- [x] `DryEngine` imprime o mesmo aviso (herda `_reproduce`).
- [x] Não-regressão: `uv run pytest tests/unit` passa. Golden diverge (classe (d)).

---

## [T11] — Golden: regenerar as fixtures de caracterização

**Depende de:** T01–T10.
**Arquivos envolvidos:** `tests/golden/**` (27 diretórios de referência)

**Contexto:**
A rede golden compara a árvore inteira do workspace produzido por cada comando contra uma referência versionada — **incluindo `stdout.txt`**, presente nos 27 diretórios (`tests/test_cli_run.py:30` e `tests/test_cli_replay.py:103` gravam a saída no workspace antes da comparação). Esta etapa muda, de propósito, quatro coisas dessa árvore.

**Estado atual:**
- 27 diretórios em `tests/golden/`, comparados por `GoldenWorkspace.assert_matches`; regeneração por `HAR_REPRODUCER_UPDATE_GOLDEN=1`.

**Estado esperado depois:**
- Fixtures regeneradas com `HAR_REPRODUCER_UPDATE_GOLDEN=1 uv run pytest`, e a suíte inteira passando **sem** a variável depois disso.
- As **quatro** classes de mudança esperadas, e nenhuma outra:
  - **(a)** candidatos que antes ficavam `NotFound` agora acham origem pelo corpus estruturado — novos `.curl.sh` com placeholder, novos arquivos em `extractors/` (T04);
  - **(b)** `RegexAgent` gera regex com âncora de fim — muda o texto do `.py` persistido, não o valor extraído (T07);
  - **(c)** `.curl.sh` com candidato sem origem ganha a linha `# [Unresolved N] ...` (T09);
  - **(d)** `stdout.txt` ganha o WARNING de HAR sem corpo (T10).
- ⚠️ Divergência fora dessas quatro classes: **parar e investigar**, não regravar.
- ⚠️ Commit separado, `test:`, com o resumo das classes no corpo.

**Critérios de aceite:**
- [x] `uv run pytest` passa inteiro sem `HAR_REPRODUCER_UPDATE_GOLDEN`.
- [x] Script de conferência: para cada `.curl.sh`, o conjunto de `token_id` casados por `DEPENDENCY_PATTERN` **antes ⊆ depois** — nenhuma dependência foi perdida.
- [x] Script de conferência: para cada `extractors/*.meta.json`, `captured_value` inalterado — nenhum extrator passou a devolver valor diferente.
- [x] Todo arquivo alterado no diff cai em (a), (b), (c) ou (d); a lista de arquivos por classe fica no corpo do commit.
- [x] Os `.curl.sh` que ganharam `# [Unresolved N]` continuam com o bloco `curl` byte-idêntico.
- [x] Não-regressão: `tests/test_cli_run.py`, `test_cli_replay.py`, `test_cli_optimize.py`, `test_cli_parse.py`, `test_cli_config.py` e `test_cli_errors.py` passam.

---

## Anexo — cobertura spec × plano

| Decisão da spec | Task |
|---|---|
| 3.1 `ValueVariants` | T01 |
| 3.2 `ResponseCorpus` (com memoização) | T03 |
| 3.3 `OriginFinder` sobre o corpus | T04 |
| 3.4 `OriginMatch`/`OriginContainer` + regra do `origin_key` | T02 (tipos) + T04 (regra) |
| 3.5 `DynamicToken.origin_key`/`origin_container` | T02 |
| 3.6 `CandidateResolver` + cache de negativos + `EngineFactory` | T05 |
| 3.7 `BaseAgent.origin_key` + guard de container | T06 |
| 3.8 `RegexAgent._context_pattern` | T07 |
| 3.9 linha `[Unresolved N]` | T08 (formato) + T09 (emissão) |
| 3.10 aviso de HAR sem corpo | T10 |
| — regeneração do golden | T11 |

**Tipos de commit:** T01 `refactor:`; T02, T03, T04, T05, T06, T08, T09, T10 `feat:`; T07 `feat:` (é conserto de defeito, mas a skill reserva `fix:` para bug descoberto **durante** a implementação, fora do plano, e sem `T0N` — como T07 é previsto e tem ID, vai como `feat:`); T11 `test:`.
