# Plano de Implementação — Corpus Estruturado de Respostas e Chave de Origem

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

---

## [T01] — `ValueVariants`: extrair as variantes de encoding de `ResponseGrep` para uma classe própria

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/value_variants.py` (novo, `ValueVariants`), `har_reproducer/tracking/response_grep.py` (`ResponseGrep.try_decode`/`value_variants`/`_deduplicate` removidos), `har_reproducer/tracking/token_location_detector.py` (`TokenLocationDetector._value_present`), `har_reproducer/tracking/__init__.py`, `tests/unit/test_response_grep_helpers.py`

**Contexto:**
`ResponseGrep` hoje acumula três papéis: gerar variantes de encoding de um valor, listar respostas elegíveis por causalidade temporal, e buscar. Nas tasks seguintes ele deixa de ser classe de utilidade sem estado e passa a receber colaborador por construtor (T04). Manter dentro dele um utilitário que **outra** classe consome estaticamente (`TokenLocationDetector._value_present` chama `ResponseGrep.value_variants`) misturaria os dois papéis. Esta task é puramente estrutural — nenhum comportamento muda (spec seção 3.1).

**Estado atual:**
- `ResponseGrep.try_decode(value)` — tenta URL-decode e depois base64-decode, devolvendo o valor transformado ou o original.
- `ResponseGrep.value_variants(value)` — devolve `[value, try_decode(value), quote(value, safe=""), b64encode(value)]` deduplicado.
- `ResponseGrep._deduplicate(values)` — remove vazios e repetidos preservando a ordem.
- `TokenLocationDetector._value_present` chama `ResponseGrep.value_variants(value)`.
- `tests/unit/test_response_grep_helpers.py` exercita `ResponseGrep.try_decode`, `ResponseGrep.value_variants` e `ResponseGrep._extract_step_index`.

**Estado esperado depois:**
- Arquivo novo `tracking/value_variants.py` com a classe `ValueVariants`, contendo `try_decode` (`@staticmethod`), `of` (`@classmethod`, era `value_variants`) e `_deduplicate` (`@staticmethod`) — **corpos idênticos aos atuais**, só movidos.
- `ResponseGrep` perde os três métodos e passa a chamar `ValueVariants.of(pattern)` no lugar de `cls.value_variants(pattern)`. `_extract_step_index` e `_eligible_response_files` **continuam onde estão** (saem só na T03/T04).
- `TokenLocationDetector._value_present` passa a chamar `ValueVariants.of(value)`.
- `tracking/__init__.py` exporta `ValueVariants` (mantendo `ResponseGrep`), em ordem alfabética no `__all__`.
- `tests/unit/test_response_grep_helpers.py` passa a chamar `ValueVariants.try_decode`/`ValueVariants.of` nos quatro testes correspondentes; os dois testes de `_extract_step_index` continuam apontando para `ResponseGrep`.
- ⚠️ A **ordem** das variantes (`cru`, `decodificado`, `URL-encode`, `base64-encode`) é significativa — a primeira que casar vence a busca. Não reordenar nem "melhorar" a lista.
- ⚠️ Renomear `value_variants` → `of` é deliberado (`ValueVariants.of(x)` lê melhor que `ValueVariants.value_variants(x)`). Não deixar alias para o nome antigo.

**Critérios de aceite:**
- [ ] `ValueVariants.try_decode("valor%20com%20espaco")` retorna `"valor com espaco"`.
- [ ] `ValueVariants.try_decode(base64.b64encode(b"segredo").decode("ascii"))` retorna `"segredo"`.
- [ ] `ValueVariants.of("abc")` não tem duplicatas nem string vazia, e `ValueVariants.of("abc")[0] == "abc"` (variante crua sempre primeiro).
- [ ] `grep -rn "ResponseGrep.value_variants\|ResponseGrep.try_decode" har_reproducer/` não retorna nada.
- [ ] Não-regressão: a suíte inteira (`pytest`) passa sem nenhuma mudança em fixtures golden — a task não altera comportamento observável.

---

## [T02] — `models`: novo `OriginMatch` e campo `DynamicToken.origin_key`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/analysis.py` (`OriginMatch`), `har_reproducer/models/session.py` (`DynamicToken`), `har_reproducer/models/__init__.py`

**Contexto:**
`ResponseGrep.find` devolve hoje `Tuple[int, str]` com `(step_index, filename)`, e o `filename` não é lido por ninguém. A T04 troca esse retorno por um model que carrega, além do step de origem, a **chave** da resposta de origem onde o valor mora (`ETag`, por exemplo) — informação que o agente precisa e que hoje se perde. O `DynamicToken` precisa transportar essa chave do `CandidateResolver` até o `AgentFactory` (spec seções 3.4 e 3.5).

**Estado atual:**
- `models/analysis.py` tem só `StepAnalysis`.
- `DynamicToken` tem `token_id`, `path`, `current_value`, `destination_location`, `origin_location`, `origin_step`, `status`, `extraction_exhausted`.

**Estado esperado depois:**
- `models/analysis.py` ganha:
  ```python
  class OriginMatch(BaseModel):
      step_index: int
      origin_key: Optional[str] = None
  ```
- `DynamicToken` ganha `origin_key: Optional[str] = None`, declarado **depois** de `origin_step` e **antes** de `status`.
- `models/__init__.py` exporta `OriginMatch` (import e `__all__`, em ordem alfabética).
- ⚠️ **Não** adicionar campo espelho em `Extractor`: `origin_key` só tem consumidor no cache-miss (onde o agente é construído); persistir sem consumidor deixaria campo morto em todo `.meta.json` (spec 3.5).
- ⚠️ `origin_step` continua `Optional[int]` — não aproveitar esta task para apertar tipo.

**Critérios de aceite:**
- [ ] `OriginMatch(step_index=7)` é válido e `origin_key` fica `None`.
- [ ] `OriginMatch(step_index=7, origin_key="ETag").origin_key == "ETag"`.
- [ ] `DynamicToken(...)` construído sem `origin_key` (como todos os call sites atuais fazem) continua válido, com `origin_key is None`.
- [ ] `from har_reproducer.models import OriginMatch` funciona.
- [ ] Não-regressão: `pytest` passa inteiro; nenhum `.meta.json` do golden muda (o campo novo está em `DynamicToken`, que não é persistido).

---

## [T03] — `ResponseCorpus`: corpus estruturado de respostas

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/response_corpus.py` (novo, `ResponseCorpus`), `har_reproducer/tracking/__init__.py`

**Contexto:**
A busca de origem roda hoje `grep -lF <valor> res_NNNN.json` sobre o **texto do arquivo** — que é a serialização Pydantic de `StepResponse`, onde o body é uma string JSON com aspas e barras escapadas. Qualquer valor contendo `"` nunca casa consigo mesmo. Medido no workspace real: 63 candidatos (todos `header:If-None-Match`, ETags no formato `W/"9b1-19a1d941a25"`) são descartados por esse detalhe. Esta task cria o corpus que expõe o **conteúdo real** da resposta (spec seção 3.2).

**Estado atual:**
- Não existe. A leitura de respostas está partida entre `ResponseGrep._eligible_response_files` (glob de arquivos) e `CandidateResolver._load_response` (lê o mesmo arquivo de novo como `Dict`).

**Estado esperado depois:**
- Classe nova `ResponseCorpus`, recebendo `responses_dir: Path` e `step_index_width: int` por construtor (o width é necessário para montar `res_{index:0{width}d}.json` em `response()`).
- `eligible_indexes(before_step_index: int) -> List[int]` — varre `responses_dir.glob("res_*.json")`, extrai o índice do nome, mantém só os `< before_step_index`, devolve **ordenado crescente**. É aqui que passa a morar a restrição de causalidade temporal (uma origem nunca é uma resposta futura).
- `response(step_index: int) -> Optional[Dict[str, Any]]` — lê e desserializa o JSON. Mesmo tratamento de erro de `CandidateResolver._load_response`: `except Exception` + `print(f"[AVISO] Falha ao carregar response do step {step_index}: {e}")` + `return None`; arquivo inexistente devolve `None` sem print.
- `searchable_text(step_index: int) -> Optional[str]` — devolve `None` se `response()` devolveu `None`; senão, a serialização estruturada, nesta ordem fixa, uma entrada por linha, unidas por `"\n"`:
  1. cada header como `f"{name}: {value}"`;
  2. cada cookie como `f"{name}={value}"`;
  3. `redirect_url`, se não vazio;
  4. `body` decodificado (se `bytes`, `decode("utf-8", errors="replace")`), se não vazio.
- `_extract_step_index(filename)` — corpo idêntico ao de `ResponseGrep` (que ainda mantém o seu até a T04 removê-lo).
- ⚠️ `response()` devolve o `Dict` cru do JSON, **não** `StepResponse`: é esse dicionário que vira `response_sample` para `TokenLocationDetector` e para o `Agent`, e é ele que `ExtractorTemplate.render_temp_script` embute no script de verificação. Trocar o tipo propagaria por todos os agentes.
- ⚠️ **Sem cache** em atributo de instância. Medido: leitura direta custa <1 s para os 269 candidatos do workspace real; `CandidateResolver` já tem os caches dele.
- ⚠️ A ordem da serialização faz parte do contrato (a T04 não depende dela para decidir *onde* casou, mas o golden e os testes dependem de estabilidade).

**Critérios de aceite:**
- [ ] `eligible_indexes(3)` sobre um diretório com `res_0000.json`…`res_0005.json` retorna `[0, 1, 2]`.
- [ ] `eligible_indexes(0)` retorna `[]`.
- [ ] Arquivo com nome fora do padrão (`nomeinvalido.json`) é ignorado sem quebrar.
- [ ] Para uma resposta com `headers={"ETag": 'W/"9b1-19a1d941a25"'}`, `searchable_text` **contém** a substring `W/"9b1-19a1d941a25"` (com aspas cruas) — é o caso que o `grep` sobre o arquivo não acha.
- [ ] Para uma resposta com body `'{"token":"abc"}'`, `searchable_text` contém `{"token":"abc"}` sem barras de escape.
- [ ] `response(7)` de arquivo inexistente retorna `None` sem lançar; de JSON corrompido retorna `None` e imprime aviso.
- [ ] `searchable_text` de resposta totalmente vazia (sem headers/cookies/redirect/body) retorna `""`, não `None`.
- [ ] Não-regressão: `pytest` passa inteiro (a classe ainda não é usada por ninguém nesta task).

---

## [T04] — `ResponseGrep`: buscar sobre o corpus estruturado e devolver `OriginMatch` com `origin_key`

**Depende de:** T01 (`ValueVariants`), T02 (`OriginMatch`), T03 (`ResponseCorpus`).
**Arquivos envolvidos:** `har_reproducer/tracking/response_grep.py` (`ResponseGrep` inteiro), `tests/unit/test_response_grep_helpers.py`

**Contexto:**
`ResponseGrep` deixa de rodar `subprocess`/`grep` sobre arquivos e passa a buscar no `searchable_text` do corpus. Além de fechar a falha de escape, o corpus dá acesso à resposta desserializada — o que permite descobrir **sob qual chave** o valor mora na origem (`ETag`), informação que o agente precisa e que hoje se perde (spec seções 3.3 e 3.4).

**Estado atual:**
```python
class ResponseGrep:

    @classmethod
    def find(cls, responses_dir: Path, pattern: str, before_step_index: int) -> Optional[Tuple[int, str]]:
        candidate_files: List[Path] = cls._eligible_response_files(responses_dir, before_step_index)
        if not candidate_files:
            return None
        for variant in cls.value_variants(pattern):          # após T01: ValueVariants.of(pattern)
            match: Optional[Tuple[int, str]] = cls._grep_single_pattern(candidate_files, variant)
            if match is not None:
                return match
        return None

    @classmethod
    def _grep_single_pattern(cls, candidate_files, pattern):
        cmd = ["grep", "-lF", pattern, *(str(path) for path in candidate_files)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        ...
        first_match_file = sorted(result.stdout.splitlines())[0]
        ...
        return step_index, filename
```

**Estado esperado depois:**
- `ResponseGrep` vira classe de instância: `__init__(self, corpus: ResponseCorpus)`, guardando `self.corpus: ResponseCorpus`.
- `find(self, value: str, before_step_index: int) -> Optional[OriginMatch]`:
  - obtém `self.corpus.eligible_indexes(before_step_index)`; lista vazia → `None`;
  - para cada variante de `ValueVariants.of(value)`, **na ordem**, varre os índices elegíveis **em ordem crescente** e devolve no primeiro `searchable_text` que contenha a variante.
- `_origin_key(step_index, variant, is_raw) -> Optional[str]` implementa a regra da spec 3.4: devolve `None` quando `is_raw` é falso; senão procura, na resposta desserializada, um **header** e depois um **cookie** cujo valor seja **exatamente igual** à variante, devolvendo o nome da primeira chave encontrada; `None` se nenhuma casar.
- `is_raw` é `variant == value` (a variante crua é sempre a primeira de `ValueVariants.of`).
- Saem: `subprocess`, `_grep_single_pattern`, `_eligible_response_files`, `_extract_step_index`, `try_decode`/`value_variants`/`_deduplicate` (já saíram na T01), e o `import base64`/`urllib` que ficarem órfãos.
- ⚠️ **Ordem preservada, é comportamento observável:** a varredura esgota **todos** os steps com a variante 1 antes de tentar a variante 2 (é o que `find` faz hoje), e o desempate entre steps é sempre o **menor índice** (hoje: `sorted(result.stdout.splitlines())[0]`).
- ⚠️ O `filename` do retorno antigo **não** tem substituto: ninguém o lia.
- ⚠️ `origin_key` **não** pode ser preenchido por substring (valor que é apenas parte do valor do header). É o caso `Sec-Fetch-Site` × `Cross-Origin-Opener-Policy` da spec de 04/08: hoje ele falha de forma inofensiva; com `origin_key` por substring, `HeaderAgent._context_pattern` passaria a ter **sucesso** sobre um header sem relação causal, produzindo extrator verificado e errado.
- ⚠️ `origin_key` **não** pode ser preenchido para variante transformada (URL/base64): o agente é verificado contra `expected_value = current_value`, e um extrator que devolva a variante devolveria valor diferente do esperado.

**Critérios de aceite:**
- [ ] Corpus com `res_0001.json` cujo header é `{"ETag": 'W/"9b1-abc"'}`: `find('W/"9b1-abc"', 5)` retorna `OriginMatch(step_index=1, origin_key="ETag")` — o caso que o `grep` sobre arquivo não achava.
- [ ] Mesmo corpus, `find('W/"9b1-abc"', 1)` retorna `None` (causalidade temporal: o step 1 não é anterior ao step 1).
- [ ] Valor presente em `res_0002.json` e `res_0004.json` com a variante crua → retorna `step_index=2` (menor índice).
- [ ] Valor presente cru em `res_0004.json` e presente como base64 em `res_0002.json` → retorna `step_index=4` (a variante crua vence a ordem dos steps).
- [ ] Valor que casa só dentro do body (`{"token":"abc"}` com valor `abc`) retorna `origin_key is None`.
- [ ] Valor que é **substring** do valor de um header (`same-origin` dentro de `same-origin-allow-popups`) retorna match com `origin_key is None`.
- [ ] Valor que casa por variante base64 num header retorna `origin_key is None`.
- [ ] Valor presente num cookie e em nenhum header retorna o nome do cookie como `origin_key`.
- [ ] `grep -rn "subprocess" har_reproducer/tracking/` não retorna nada.
- [ ] Não-regressão: `tests/unit/test_response_grep_helpers.py` atualizado passa; a suíte de integração ainda **não** passa nesta task isolada, porque `CandidateResolver` ainda chama a API antiga — a T05 fecha isso. Se a task for commitada isolada, rodar ao menos `pytest tests/unit/test_response_grep_helpers.py`.

---

## [T05] — `CandidateResolver`: receber corpus e grep por construtor, gravar `origin_key`, remover `_load_response`

**Depende de:** T04.
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (`CandidateResolver.__init__`, `_process_candidate`, `_find_origin`, `_generate_new_extractor`, `_load_response`, `_check_persisted_slot`), `tests/unit/test_candidate_resolver.py`

**Contexto:**
`CandidateResolver` é o único consumidor de `ResponseGrep.find`. Hoje ele recebe `responses_dir: Path`, chama o grep estaticamente e **relê o mesmo arquivo** em `_load_response` para obter o `response_sample`. Com o corpus da T03 as duas leituras viram uma só, e o `origin_key` descoberto pela T04 passa a ser gravado no candidato (spec seção 3.6).

**Estado atual:**
```python
    def __init__(self, responses_dir: Path, session_store, extractor_runner, metadata_store, agent_factory) -> None:
        self.responses_dir: Path = responses_dir
        ...
        self._origin_cache: Dict[str, Tuple[int, str]] = {}

    def _process_candidate(self, candidate, step_index):
        origin: Optional[Tuple[int, str]] = self._find_origin(candidate.current_value, step_index)
        if not origin:
            candidate.status = "NotFound"
            return candidate
        candidate.origin_step = origin[0]
        ...

    def _find_origin(self, value, step_index):
        cached_origin = self._origin_cache.get(value)
        if cached_origin is not None:
            return cached_origin
        origin = ResponseGrep.find(self.responses_dir, value, step_index)
        ...

    def _check_persisted_slot(self, slot_id, candidate):
        ...
        result = self.extractor_runner.run_existing(slot_id, self.responses_dir)

    def _generate_new_extractor(self, candidate, initial_error):
        response_sample = self._load_response(candidate.origin_step)
        ...

    def _load_response(self, step_index): ...
```

**Estado esperado depois:**
- Construtor: `response_corpus: ResponseCorpus` e `response_grep: ResponseGrep` entram como **primeiros** parâmetros, no lugar de `responses_dir`; os demais (`session_store`, `extractor_runner`, `metadata_store`, `agent_factory`) ficam na mesma ordem.
- `self.responses_dir` deixa de existir; `_check_persisted_slot` passa a usar `self.response_corpus.responses_dir` na chamada a `extractor_runner.run_existing`. ⚠️ **Não** mudar a assinatura de `ExtractorRunner.run_existing` (continua recebendo `Path`).
- `_origin_cache: Dict[str, OriginMatch]`.
- `_find_origin(value, step_index) -> Optional[OriginMatch]` delega a `self.response_grep.find(value, step_index)`.
- `_process_candidate` grava `candidate.origin_step = origin.step_index` **e** `candidate.origin_key = origin.origin_key`, antes de derivar o `token_id`.
- `_load_response` é removido; `_generate_new_extractor` chama `self.response_corpus.response(candidate.origin_step)`.
- `tests/unit/test_candidate_resolver.py:32` passa a construir `CandidateResolver(ResponseCorpus(tmp_path, Workspace.STEP_INDEX_WIDTH), ResponseGrep(corpus), SessionStore(), ...)`.
- ⚠️ O cache `_origin_cache` continua chaveado **só pelo valor**, sem o `step_index` — é comportamento atual e conhecido (`docs/20260805 Regressão de Cache de Origem no CandidateResolver`). Não "consertar" aqui.
- ⚠️ `_derive_token_id` continua sendo `md5(f"{path}:{origin_step}")` — `origin_key` **não** entra no hash. Entrar mudaria a identidade de todo slot já persistido em `extractors/`.
- ⚠️ O ramo de cache-hit (`registry.get(slot_id) is not None`) continua **não** preenchendo `origin_location` (bug §3.2 do relatório de 11/08). Está fora do escopo desta spec; não aproveitar a passagem para mexer.

**Critérios de aceite:**
- [ ] Candidato cujo valor está no header `ETag` de uma resposta anterior termina com `origin_step` correto **e** `origin_key == "ETag"`.
- [ ] Candidato sem origem em nenhuma resposta elegível termina com `status == "NotFound"`, `origin_step is None` e `origin_key is None`.
- [ ] Candidato cujo valor casa dentro do body termina com `origin_key is None` e `origin_step` correto.
- [ ] `grep -n "_load_response" har_reproducer/` não retorna nada.
- [ ] Duas chamadas a `_find_origin` com o mesmo valor fazem uma única busca (cache preservado).
- [ ] Não-regressão: `pytest tests/unit` passa inteiro; os testes de integração/golden podem divergir aqui por causa dos 63 ETags recém-descobertos — divergência **esperada**, resolvida na T14. Anotar no commit quais golden divergem.

---

## [T06] — `EngineFactory`: montar `ResponseCorpus` e `ResponseGrep` na raiz de composição

**Depende de:** T05.
**Arquivos envolvidos:** `har_reproducer/engines/construction/engine_factory.py` (`EngineFactory.create`, `_build_tracker`), `tests/unit/test_engine_factory.py`

**Contexto:**
`EngineFactory` é a raiz de composição do ramo `run` — o único lugar que pode instanciar os colaboradores novos. Hoje ela decide `tracking_responses_dir` (real ou original, conforme o modo) e passa esse `Path` cru para `CandidateResolver` e `TokenResolver` (spec seção 3.6).

**Estado atual:**
```python
        tracking_responses_dir: Path = (
            self.workspace.real_responses if engine_cls.USES_NETWORK else self.workspace.original_responses
        )
        ...
        return engine_cls(
            har_path, self.workspace, session_store,
            self._build_tracker(tracking_responses_dir, session_store, extractor_runner, metadata_store),
            TokenResolver(tracking_responses_dir, session_store, extractor_runner),
            ...
        )

    def _build_tracker(self, tracking_responses_dir, session_store, extractor_runner, metadata_store) -> TokenTracker:
        agent_factory = AgentFactory(self.workspace, self.script_executor, self.sleeper, self.llm)
        candidate_resolver = CandidateResolver(
            tracking_responses_dir, session_store, extractor_runner, metadata_store, agent_factory
        )
        ...
```

**Estado esperado depois:**
- `create` monta `ResponseCorpus(tracking_responses_dir, Workspace.STEP_INDEX_WIDTH)` e repassa o **corpus** (não o `Path`) para `_build_tracker`.
- `_build_tracker` monta `ResponseGrep(response_corpus)` e injeta os dois no `CandidateResolver`.
- ⚠️ `TokenResolver` **continua** recebendo `tracking_responses_dir: Path` — ele resolve tokens já registrados, não descobre origem, e não sofre nenhuma das duas falhas desta spec (declarado fora de escopo na seção 1).
- ⚠️ A escolha `real_responses` × `original_responses` por modo **não muda** nesta spec.

**Critérios de aceite:**
- [ ] `EngineFactory.create(EngineMode.DRY, ...)` produz um `Engine` cujo `CandidateResolver` busca em `workspace.original_responses`.
- [ ] `EngineFactory.create(EngineMode.MAIN, ..., http_transport=...)` produz um cujo `CandidateResolver` busca em `workspace.real_responses`.
- [ ] `TokenResolver` recebido pelo engine continua com o mesmo `responses_dir` de antes em ambos os modos.
- [ ] Não-regressão: `pytest tests/unit/test_engine_factory.py` passa; `pytest tests/unit` passa inteiro.

---

## [T07] — `BaseAgent`/`AgentFactory`: procurar pela chave de origem em vez da chave de destino

**Depende de:** T02 (campo no model), T05 (campo preenchido).
**Arquivos envolvidos:** `har_reproducer/agents/base_agent.py` (`BaseAgent.__init__`, property `key`), `har_reproducer/agents/construction/agent_factory.py` (`AgentFactory.create`), `tests/unit/test_base_agent.py`, `tests/unit/test_agent_factory.py`, `tests/unit/test_agents_strategies.py`

**Contexto:**
`BaseAgent.key` deriva sempre de `candidate.path`, que é o caminho no **request** (`header:If-None-Match`). Mas todas as estratégias determinísticas aplicam essa chave **sobre a resposta de origem**, onde o valor mora sob outra chave (`ETag`). Medido: em 63 de 63 casos deste workspace a resposta de origem não tem nenhum header com o nome de destino, então `HeaderAgent._by_name` falha, `_context_pattern` falha (depende de `_header_value()`, que usa a mesma chave errada), e cada candidato queima as 5 tentativas de LLM com 5 s de sleep entre elas — 315 chamadas e ~26 min de espera para terminar em `LiteralFallbackAgent` (spec seção 3.7).

**Estado atual:**
```python
    def __init__(self, token_id, response_sample, expected_value, workspace, script_executor, sleeper,
                 path=None, location=None, llm=None) -> None:
        ...

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
- `BaseAgent.__init__` ganha `origin_key: Optional[str] = None`, posicionado **entre** `location` e `llm`, guardado em `self.origin_key: Optional[str]`.
- `key` passa a preferir a chave de origem:
  ```python
  @property
  def key(self) -> Optional[str]:
      if self.origin_key is not None:
          return self.origin_key
      if self.path is None:
          return None
      if ":" in self.path:
          return self.path.split(":", 1)[1]
      return self.path
  ```
- `AgentFactory.create` passa `origin_key=candidate.origin_key`.
- ⚠️ Isso muda o comportamento de **três** consumidores de uma vez, sem alterar uma linha deles: `HeaderAgent._by_name`/`_header_value`, `CookieAgent._by_name`/`_context_pattern` e `RegexAgent._key_pattern`. Para os dois primeiros é o objetivo; para `_key_pattern` o efeito é colateral e desejável (passa a procurar no body pela chave da origem).
- ⚠️ Todos os call sites usam argumentos nomeados; a posição do parâmetro não quebra nada, mas manter `llm` por último é a convenção do arquivo.

**Critérios de aceite:**
- [ ] `BaseAgent(..., path="header:If-None-Match", origin_key="ETag").key == "ETag"`.
- [ ] `BaseAgent(..., path="header:If-None-Match", origin_key=None).key == "If-None-Match"` (comportamento de hoje preservado).
- [ ] `BaseAgent(..., path=None, origin_key=None).key is None`.
- [ ] `HeaderAgent` com `origin_key="ETag"`, `expected_value='W/"9b1-abc"'` e `response_sample` cujo header `ETag` vale `W/"9b1-abc"`: a **primeira** estratégia determinística (`_by_name`) gera código que verifica com sucesso — **zero** tentativas de LLM.
- [ ] `AgentFactory.create` propaga `candidate.origin_key` para o agente construído.
- [ ] Não-regressão: `pytest tests/unit/test_base_agent.py tests/unit/test_agent_factory.py tests/unit/test_agents_strategies.py` passa; agente sem `origin_key` gera exatamente o mesmo código de antes.

---

## [T08] — `RegexAgent._context_pattern`: âncora de fim e classe preguiçosa (paridade com `HeaderAgent`)

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/agents/regex_agent.py` (`RegexAgent._context_pattern`), `tests/unit/test_agents_strategies.py`

**Contexto:**
A spec `docs/20260804 Extração por Substring e Fallback de Exaustão` (decisão 3.2, bloco ⚠️ "achado durante a implementação") corrigiu `HeaderAgent._context_pattern`/`CookieAgent._context_pattern` para usar classe **preguiçosa** + lookahead do caractere real que segue o valor, porque um quantificador guloso sem âncora de fim consome o delimitador quando ele pertence à classe de caracteres do valor. `RegexAgent._context_pattern` ficou de fora e continua guloso e sem fronteira. Consequência: para todo valor que contenha caractere fora de `[\w\-.]` (qualquer `/`, típico de caminho e URL), `value_char_class()` devolve `.+?`, que **sem âncora de fim casa exatamente um caractere** e falha sempre (spec seção 3.8).

**Estado atual:**
```python
    def _context_pattern(self) -> Optional[str]:
        body: Optional[str] = self.response_sample.get("body")
        if not isinstance(body, str):
            return None
        pos: int = body.find(self.expected_value)
        if pos == -1:
            return None
        prefix: str = body[max(0, pos - 20):pos]
        if not prefix.strip():
            return None
        return rf"{re.escape(prefix)}({self.value_char_class()})"
```

**Estado esperado depois:**
```python
    def _context_pattern(self) -> Optional[str]:
        body: Optional[str] = self.response_sample.get("body")
        if not isinstance(body, str):
            return None
        pos: int = body.find(self.expected_value)
        if pos == -1:
            return None
        prefix: str = body[max(0, pos - 20):pos]
        if not prefix.strip():
            return None
        end: int = pos + len(self.expected_value)
        boundary: str = rf"(?={re.escape(body[end])})" if end < len(body) else "$"
        return rf"{re.escape(prefix)}({self.lazy_value_char_class()}){boundary}"
```
- ⚠️ `_key_pattern` **não muda**: lá o grupo já é delimitado pelo contexto `chave: valor` à esquerda, e não há defeito observado que justifique mexer.
- ⚠️ Esta task altera o **texto do regex** de extratores gerados por `RegexAgent`. O valor extraído não muda (o `run_tdd_loop` só aceita código que devolve exatamente `expected_value`); o que muda é qual estratégia verifica primeiro e o `.py` persistido. Golden vai divergir — resolvido na T14.

**Critérios de aceite:**
- [ ] Body `abc: token123-suffix`, `expected_value="token123"`: o padrão gerado casa e o grupo 1 é exatamente `"token123"` (hoje o guloso levaria `-suffix` junto).
- [ ] Body `import x from '/src/a/B.js'`, `expected_value="/src/a/B.js"`: o padrão gerado casa e o grupo 1 é exatamente `/src/a/B.js` (hoje `.+?` sem âncora casaria só `/`).
- [ ] `expected_value` terminando exatamente no fim do body gera padrão com `$` no lugar do lookahead.
- [ ] `expected_value` ausente do body continua devolvendo `None`.
- [ ] Prefixo só com espaço em branco continua devolvendo `None`.
- [ ] Não-regressão: `pytest tests/unit/test_agents_strategies.py` passa; nenhum caso que hoje verifica com sucesso passa a falhar.

---

## [T09] — `CurlTokenComment`: cláusula de auditoria para valores sem origem

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/replay/curl_token_comment.py` (`UnresolvedOriginPhrase`, `CurlTokenComment`), `tests/unit/test_curl_token_comment.py`

**Contexto:**
Candidato que termina `NotFound` não deixa **nenhum** rastro no `.curl.sh` (`CurlGenerator._token_comments` pula todo token com `origin_step is None`). É essa ausência que faz `optimize` reportar `SUCCESSFUL` sobre um schedule cheio de literais congelados do HAR, sem aviso (relatório de 11/08, seções 3.1/3.4 e conclusão, itens 2 e 4). Esta task cria o formato da linha; a T10 a emite e a T11/T12 a agregam (spec seção 3.9).

**Estado atual:**
- `DependencyPhrase`, `OriginStatusPhrase`, `ReplayStatusPhrase`, e `CurlTokenComment` com `CATEGORY_SEPARATOR = "; "`, `CLAUSE_CLOSING_MARKER = "]"`, `DEPENDENCY_PATTERN`, `format_dependency_line`, `with_replay_status`, `parse`.

**Estado esperado depois:**
- Novo enum `UnresolvedOriginPhrase(str, Enum)` com `NO_RECORDED_ORIGIN = "no recorded origin — value kept literal from HAR"` (usado pelo texto do relatório da T11/T12, não pela linha do curl).
- Novo `UNRESOLVED_PATTERN: ClassVar[Pattern[str]] = re.compile(r"^# \[Unresolved (?P<count>\d+)\] (?P<paths>.+)$", re.MULTILINE)`.
- `format_unresolved_line(self, paths: List[str]) -> str` — devolve `f"# [Unresolved {len(paths)}] " + CATEGORY_SEPARATOR.join(paths)`.
- `parse_unresolved(self, curl_text: str) -> List[str]` — devolve os paths da primeira ocorrência, ou `[]` se não houver.
- ⚠️ O contrato de colchetes consolidado em `docs/20260812 Correção da Anotação de Token Estático que Quebra o Parser de Dependências` **não pode ser afrouxado**: a cláusula vive entre `[` e `]`, e nenhuma anotação de replay é anexada à linha `[Unresolved ...]`.
- ⚠️ `UNRESOLVED_PATTERN` e `DEPENDENCY_PATTERN` não podem se casar cruzado — a palavra após `[` difere (`Unresolved` × `Token`). Isso precisa de teste explícito.

**Critérios de aceite:**
- [ ] `format_unresolved_line(["header:Accept", "url"])` retorna `# [Unresolved 2] header:Accept; url`.
- [ ] `parse_unresolved(format_unresolved_line(["a", "b"]))` retorna `["a", "b"]` (round-trip).
- [ ] `parse_unresolved("")` e `parse_unresolved("#!/bin/bash\ncurl -X GET x")` retornam `[]`.
- [ ] `CurlTokenComment.DEPENDENCY_PATTERN.findall(format_unresolved_line(["a"]))` é vazio.
- [ ] `parse_unresolved(format_dependency_line("abc123", 7))` é `[]`.
- [ ] `parse` continua achando a dependência num texto que contenha **as duas** linhas.
- [ ] Não-regressão: `pytest tests/unit/test_curl_token_comment.py` passa inteiro, inclusive os testes da etapa de 12/08.

---

## [T10] — `CurlGenerator`: emitir a linha consolidada de valores sem origem

**Depende de:** T09.
**Arquivos envolvidos:** `har_reproducer/reproduction/curl_generator.py` (`CurlGenerator._token_comments`), `tests/unit/test_curl_generator.py`

**Contexto:**
Com o formato da T09 pronto, o gerador passa a registrar no `.curl.sh` **o que** ficou congelado como literal por não ter origem descoberta (spec seção 3.9).

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
- ⚠️ **Uma** linha consolidada por step, nunca uma por candidato: 215 dos 269 candidatos distintos do workspace real são `NotFound` (a maioria header de contexto de navegador — `Accept`, `Sec-Fetch-*`, `priority`), e uma linha por candidato encheria todo `.curl.sh` e o golden de ruído.
- ⚠️ A linha lista **paths**, nunca valores — identifica o que ficou congelado sem escrever credencial dentro do arquivo.
- ⚠️ A linha de `[Unresolved]` vem **depois** de todas as linhas de dependência, e a ordem dos paths segue a ordem dos tokens recebidos (que é a ordem de `BaselineDiff.detect_candidates`) — determinismo é requisito do golden.
- ⚠️ `_origin_status` **não muda**.

**Critérios de aceite:**
- [ ] Lista com um token resolvido (`origin_step=3`) e dois sem origem produz 2 linhas: a de dependência e `# [Unresolved 2] <path1>; <path2>`, nessa ordem.
- [ ] Lista sem nenhum token sem origem produz exatamente as linhas de dependência de antes (nenhuma linha nova).
- [ ] Lista **só** com tokens sem origem produz exatamente uma linha, e o curl continua com o bloco de comando abaixo dela.
- [ ] Lista vazia continua produzindo o curl sem nenhum comentário.
- [ ] Não-regressão: `pytest tests/unit/test_curl_generator.py` passa; nenhuma mudança na montagem do bloco `curl` propriamente dito.

---

## [T11] — `ScheduleExecutor`/`ReplayRunner`: expor e reportar os valores sem origem do schedule

**Depende de:** T09.
**Arquivos envolvidos:** `har_reproducer/contracts/schedule_executor.py` (`ScheduleExecutor`), `har_reproducer/replay/replay_runner.py` (`ReplayRunner.unresolved_origins`, `_run_schedule`), `tests/unit/test_replay_runner.py`, `tests/unit/test_schedule_executor_contract.py`, `tests/support/fake_schedule_executor.py`

**Contexto:**
`ReplayOptimizer` não tem acesso ao `Workspace` para ler `.curl.sh` — tudo que ele sabe do workspace passa pelo Protocol `ScheduleExecutor`. Para que tanto `replay` quanto `optimize` possam avisar quantos literais congelados o schedule carrega, a informação precisa entrar nesse contrato (spec seção 3.10).

**Estado atual:**
- `ScheduleExecutor` declara `execute_schedule`, `compute_smart_schedule`, `existing_step_indexes`.
- `ReplayRunner._run_schedule` imprime o relatório por step (`_print_step_report`) e o veredito.

**Estado esperado depois:**
- `ScheduleExecutor` ganha `def unresolved_origins(self, indexes: List[int]) -> Dict[int, List[str]]: ...`.
- `ReplayRunner.unresolved_origins` lê o `.curl.sh` de cada índice e aplica `CurlTokenComment.parse_unresolved`, devolvendo só os índices com pelo menos um path.
- `ReplayRunner` ganha um método privado que formata e imprime o aviso, chamado por `_run_schedule` **antes** do veredito:
  ```
  WARNING: o schedule carrega 47 valor(es) sem origem gravada em 12 step(s)
    (steps 0, 1, 14, 23, ...) — literais congelados do HAR. O resultado pode deixar de
    funcionar quando esses valores expirarem, sem que este comando avise.
  ```
- `tests/support/fake_schedule_executor.py` implementa o método novo (devolvendo `{}` por padrão, com possibilidade de injetar um mapa).
- ⚠️ É **aviso**, não falha: nem `_run_schedule` nem o veredito `✓ SUCCESS`/`✗ FAILURE` mudam de comportamento. Recusar o schedule foi considerado e descartado (quebraria o uso atual, onde o próprio `Authorization` cai nessa classe).
- ⚠️ `.curl.sh` gerado antes desta spec não tem a linha: `parse_unresolved` devolve `[]`, `unresolved_origins` devolve `{}`, nenhum aviso é impresso. Workspace antigo continua funcionando.
- ⚠️ Ler o curl aqui **não** pode explodir se o arquivo não existir — os índices vêm sempre de `existing_step_indexes`, mas o método é público e o Protocol não garante isso; usar leitura defensiva com aviso, no padrão de borda de I/O do guia de estilo.

**Critérios de aceite:**
- [ ] `unresolved_origins([0, 1])` sobre um workspace onde só o `req_0001.curl.sh` tem a linha retorna `{1: [...]}`.
- [ ] `unresolved_origins([])` retorna `{}`.
- [ ] Índice cujo curl não existe é ignorado com aviso, sem lançar.
- [ ] `replay --mode all` sobre workspace com valores sem origem imprime o WARNING **e** continua até o veredito normal.
- [ ] `replay` sobre workspace sem nenhuma linha `[Unresolved]` não imprime WARNING nenhum.
- [ ] `FakeScheduleExecutor` satisfaz o Protocol atualizado (`test_schedule_executor_contract.py` passa).
- [ ] Não-regressão: `pytest tests/unit/test_replay_runner.py` passa; o veredito de sucesso/fracasso de todos os modos continua idêntico.

---

## [T12] — `ReplayOptimizer`: reportar os valores sem origem da sequência final

**Depende de:** T11.
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py` (`ReplayOptimizer.optimize`), `tests/unit/test_replay_optimizer.py`

**Contexto:**
O risco documentado no relatório de 11/08 é o `optimize` reportar `Optimization SUCCESSFUL` sobre um schedule que só funciona enquanto os literais congelados do HAR continuarem válidos. Com a T11, a informação já está disponível pelo `ScheduleExecutor` (spec seção 3.10).

**Estado atual:**
```python
        final_list: List[int] = sorted({from_index, *anchors, *kept})
        if not self._confirm(final_list, to_index, success_criteria):
            print("ReplayOptimizer: aborted — final confirmation failed after all ranges passed individually.")
            return None

        destination: Path = output_path if output_path is not None else workspace.optimized_steps_file(run_id)
        destination.write_text("\n".join(str(index) for index in final_list) + "\n", encoding="utf-8")
        return final_list
```

**Estado esperado depois:**
- Entre a confirmação e a escrita do arquivo, `optimize` consulta `self.schedule_executor.unresolved_origins(final_list)` e imprime o **mesmo formato de aviso** da T11 quando o resultado não é vazio.
- O texto do aviso vive num único lugar (extrair para onde fizer sentido pelo guia de estilo — não duplicar a string entre `ReplayRunner` e `ReplayOptimizer`).
- ⚠️ Aviso, não abort: `optimize` continua escrevendo o `.txt` e devolvendo `final_list`.
- ⚠️ O aviso é sobre a **`final_list`**, não sobre as âncoras da fase 1 — é a lista que o usuário vai reusar em `replay --mode list`.

**Critérios de aceite:**
- [ ] `optimize` cujo `final_list` toca steps com valores sem origem imprime o WARNING e **ainda assim** escreve o arquivo e retorna a lista.
- [ ] `optimize` sobre workspace sem nenhuma linha `[Unresolved]` não imprime WARNING.
- [ ] O aviso cita os steps da `final_list`, não os da backbone.
- [ ] A string do aviso não aparece duplicada no código (`grep -c` na frase retorna 1).
- [ ] Não-regressão: `pytest tests/unit/test_replay_optimizer.py` e `tests/test_cli_optimize.py` passam; abort por `--max-requests` e por confirmação final continuam sem escrever arquivo.

---

## [T13] — `Engine`: avisar quando o HAR não gravou corpo de resposta

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/engines/engine.py` (`Engine._reproduce`), `tests/unit/test_engine.py`

**Contexto:**
`HARParser.parse_entry` transforma `content` sem a chave `text` em `body=""` silenciosamente. Medido no `progressofit.har`: 140 de 238 entries nessa situação — incluindo a entry `154` (`POST /auth/login`), origem do JWT discutido no relatório de 11/08. O README declara HAR completo (com body de toda requisição) como pré-condição do projeto; hoje a violação é invisível, e o efeito prático é que a origem de um token fica indescobrível **por falta de dado**, não por deficiência de algoritmo (spec seção 3.11).

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

**Estado esperado depois:**
- `_process_entry` (que já parseia o `Step` e tem `step.response` em mãos) contabiliza as entries cujo `step.response.body` está vazio; ao final de `_reproduce`, um método privado imprime uma vez:
  ```
  WARNING: 140 de 238 entries do HAR não têm corpo de resposta gravado. Origens de
  token que estejam nesses corpos são indescobríveis — regrave o HAR preservando o
  conteúdo das respostas ("Preserve log" + export completo).
  ```
- O aviso só é impresso quando a contagem é maior que zero.
- ⚠️ A contagem é sobre o `StepResponse` **já parseado**, não sobre o JSON cru do HAR.
- ⚠️ **Não** filtrar por código de status: um `204`/`304` legitimamente sem corpo entra na contagem. Filtrar seria embutir conhecimento de protocolo — o aviso é informativo e o número serve para o usuário julgar.
- ⚠️ **Não** transformar em erro nem alterar o retorno de `run()`; a ordem de impressão é antes do `Final Validation Result`.
- ⚠️ `DryEngine` herda o comportamento sem precisar de alteração própria — conferir.

**Critérios de aceite:**
- [ ] HAR com 3 entries, 2 sem corpo de resposta: o aviso é impresso uma única vez citando `2 de 3`.
- [ ] HAR com todas as entries com corpo: nenhum aviso.
- [ ] Entry pulada por `skip_rules` continua entrando na contagem (o corpo gravado no HAR independe de o step ter sido executado).
- [ ] O retorno de `run()` é idêntico com e sem o aviso.
- [ ] `DryEngine` imprime o mesmo aviso.
- [ ] Não-regressão: `pytest tests/unit/test_engine.py` e `tests/test_cli_run.py` passam.

---

## [T14] — Golden: regenerar as fixtures de caracterização

**Depende de:** T01–T13.
**Arquivos envolvidos:** `tests/golden/**` (27 diretórios de referência)

**Contexto:**
A rede golden compara a árvore inteira do workspace produzido por cada comando contra uma referência versionada. Esta etapa muda, de propósito, três coisas que aparecem nessa árvore: (a) candidatos que antes ficavam `NotFound` agora acham origem pelo corpus estruturado (novos `.curl.sh` com placeholder, novos arquivos em `extractors/`), (b) `RegexAgent` passa a gerar regex com âncora de fim (T08), (c) todo `.curl.sh` com candidato sem origem ganha a linha `# [Unresolved N] ...` (T10).

**Estado atual:**
- 27 diretórios em `tests/golden/`, comparados por `GoldenWorkspace.assert_matches`.
- Regeneração via `HAR_REPRODUCER_UPDATE_GOLDEN=1`.

**Estado esperado depois:**
- Fixtures regeneradas com `HAR_REPRODUCER_UPDATE_GOLDEN=1 uv run pytest`, e **a suíte inteira passando sem a variável** depois disso.
- ⚠️ Antes de aceitar a regeneração, **inspecionar o diff** e conferir, em cada classe de mudança, que ela é a esperada: nenhum `.curl.sh` pode ter perdido uma dependência que tinha antes, e nenhum extrator persistido pode ter passado a devolver valor diferente. Um extrator "verificado e errado" entraria aqui carimbado como esperado — é o único ponto do plano onde isso é possível.
- ⚠️ Se algum golden divergir por motivo **não** previsto em (a)/(b)/(c), parar e investigar antes de regravar.
- ⚠️ Commit separado, `test:`, com o resumo das classes de mudança no corpo.

**Critérios de aceite:**
- [ ] `uv run pytest` passa inteiro sem `HAR_REPRODUCER_UPDATE_GOLDEN`.
- [ ] O diff das fixtures foi lido e cada arquivo alterado se encaixa em (a), (b) ou (c).
- [ ] Nenhum `.curl.sh` do golden perdeu uma linha `# [Token ... comes from response of step N]` que tinha antes.
- [ ] Os `.curl.sh` do golden que ganharam `# [Unresolved N]` continuam com o bloco `curl` inalterado.
- [ ] Não-regressão: `tests/test_cli_run.py`, `test_cli_replay.py`, `test_cli_optimize.py`, `test_cli_parse.py`, `test_cli_config.py` e `test_cli_errors.py` passam.
