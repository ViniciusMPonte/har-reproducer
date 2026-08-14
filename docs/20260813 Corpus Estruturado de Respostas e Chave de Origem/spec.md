# Spec — Corpus Estruturado de Respostas e Chave de Origem

> **Revisão 2** (13/08/2026). A revisão 1 foi submetida a duas revisões adversariais
> independentes e teve erros de medição e três defeitos de projeto confirmados. Todos
> os números desta revisão foram remedidos com simulação fiel do pipeline (busca por
> **ocorrência**, não por candidato distinto — ver seção 1.3) e as correções estão
> incorporadas. O registro do que mudou está na seção 7.

## 1. Objetivo

O relatório `docs/20260811-3 Teste do Otimizador contra Servidor Real/relatorio.md`
(seção 3.1) registrou que o header `Authorization: Bearer <JWT>` nunca é modelado
como token dinâmico, e apontou como causa o fato de `ResponseGrep` não reconhecer o
prefixo `"Bearer "`. Investigando o pipeline para corrigir isso, apareceram **duas
falhas anteriores e independentes** desse diagnóstico, ambas na etapa de *descoberta
de origem* — a etapa que decide se um valor vira extrator ou vira literal congelado.

### 1.1 Falha A — o corpus de busca é o texto serializado do arquivo, não a resposta

`ResponseGrep._grep_single_pattern` (`response_grep.py:62-82`) roda
`grep -lF <valor> res_NNNN.json`. Esses arquivos são a serialização Pydantic de
`StepResponse` (`Engine._persist_response_step`, `engine.py:99-100`), onde o body é
uma **string JSON** — aspas, barras e quebras de linha aparecem escapados
(`\"`, `\\`, `\n`). Qualquer valor de candidato que contenha um desses caracteres
**nunca casa consigo mesmo**, mesmo estando literalmente na resposta.

Medido sobre o workspace real (`arquivos-har/output`, 238 steps, 3 deles pulados por
scheme `ws://`, 1.912 ocorrências `(step, path)`, **257** candidatos `(path, value)`
distintos):

| corpus de busca | candidatos que casam pelo valor inteiro |
|---|---|
| texto cru do `res_NNNN.json` (hoje) | **54** |
| serialização estruturada da resposta | **117** |
| perdidos ao trocar de corpus | **0** |

Os 63 ganhos são **todos** `header:If-None-Match` — ETags no formato
`W/"9b1-19a1d941a25"`, cujo `"` é escapado no arquivo. São 63 dependências reais, já
presentes no dado, que o pipeline hoje descarta por um detalhe de serialização.

### 1.2 Falha B — o agente procura o valor pela chave de destino, não pela de origem

Quando a origem é encontrada, `AgentFactory.create` (`agent_factory.py:38-51`) passa
`path=candidate.path` — o caminho no **request** (`header:If-None-Match`) — e
`BaseAgent.key` (`base_agent.py:45-51`) deriva dali a chave que
`HeaderAgent._by_name` vai procurar **na resposta de origem**. Mas o valor mora, na
resposta, sob outra chave: `ETag`.

Medido — candidatos cujo valor está **byte-idêntico** sob uma chave de header/cookie
da resposta de origem, com a chave de origem **diferente** da de destino:

| destino | chave na origem | candidatos | acha origem hoje? |
|---|---|---|---|
| `header:If-None-Match` | `ETag` | 63 | não (Falha A) |
| `header:If-Modified-Since` | `Last-Modified` | 21 | **sim** |
| `header:Cache-Control` / `header:Pragma` | `Pragma` | 2 | **sim** |
| **total** | | **86** | 23 hoje |

Em 63 de 63 casos de `If-None-Match` a resposta de origem **não tem** nenhum header
chamado `If-None-Match` — e o mesmo vale para `If-Modified-Since` (uma resposta não
replica headers de requisição). Ou seja, `_by_name` falha, `_context_pattern` também
(depende de `_header_value()`, que usa a mesma chave errada), e cada candidato queima
as 5 tentativas de LLM de `BaseAgent.MAX_LLM_ATTEMPTS`, com `RETRY_DELAY_SECONDS = 5`
de espera entre elas, terminando em `LiteralFallbackAgent`.

Custo, medido em `token_id` distintos (`_derive_token_id = md5(path:origin_step)` — os
86 produzem 86 slots distintos, então o cache da spec de 04/08 não os colapsa):

| cenário | chamadas de LLM | sleep obrigatório |
|---|---|---|
| **hoje** (23 candidatos com origem, chave errada) | 115 | ~9,6 min |
| **corrigindo só a Falha A** (86 candidatos) | 430 | ~36 min |
| **corrigindo A e B** | **0** | ~0 |

⚠️ Esses números valem **com LLM configurado**. `ProjectConfig.llm` tem default
`None`; com `llm=None`, `_llm_strategy` devolve `None`, `generate_code` esgota a lista
e `run_tdd_loop` sai pelo `break` — 0 chamadas e ~5 min de sleep (uma tentativa
determinística falha por candidato). O `config.json` da raiz do projeto configura
`google/gemini-3.1-flash-lite`, então o custo alto é o do uso corrente.

⚠️ Note o efeito perverso: **corrigir só a Falha A quadruplica o desperdício de LLM.**
As duas falhas precisam ser corrigidas na mesma etapa.

### 1.3 Nota de metodologia (o que a revisão 1 errou)

A revisão 1 mediu "um candidato distinto = uma busca de origem" e chegou a
269 / 52 / 115. O pipeline não faz isso: `CandidateResolver.resolve` roda **por step**
e `_find_origin` (`candidate_resolver.py:63-70`) **só cacheia positivos** —

```python
origin = ResponseGrep.find(self.responses_dir, value, step_index)
if origin is not None:
    self._origin_cache[value] = origin
```

— então um candidato sem origem no step 12 é rebuscado do zero no step 200, agora com
janela elegível maior, e pode ser encontrado. Somando isso ao fato de que os steps
78, 90 e 166 (`ws://`) são pulados por `StepSkipEvaluator.ALLOWED_SCHEMES` e nunca
chegam a `analyze_step`, os números corretos são **257 / 54 / 117**. O **delta
(+63, 0 perdidos, todos `If-None-Match`) reproduz exatamente** — é a parte sólida.

Essa mesma ausência de cache de negativos é o que torna o corpus caro (decisão 3.6).

### 1.4 O que esta mudança cobre

- Trocar o corpus de descoberta de "texto do arquivo" para uma **serialização
  estruturada da resposta**, eliminando a classe inteira de falso-negativo por escape
  — e removendo a dependência de `subprocess`/`grep` do caminho de descoberta.
- Descobrir e propagar a **chave de origem** (`origin_key`), com o **container**
  (header/cookie) em que ela foi achada, para que o agente procure pela chave certa.
- **Cachear negativos com janela** em `CandidateResolver`, sem o que a troca de corpus
  seria uma regressão de performance de ~3× (decisão 3.6).
- Dar paridade a `RegexAgent._context_pattern` com a âncora de fim que
  `HeaderAgent._context_pattern` ganhou na spec de 04/08.
- Registrar no `.curl.sh` **o que** ficou congelado como literal por não ter origem
  descoberta — trilha de auditoria grep-ável.
- Reportar entries do HAR sem corpo de resposta gravado, que é a pré-condição do
  projeto que o `progressofit.har` viola no step do login.

### 1.5 Fora de escopo (decidido explicitamente)

- **Casamento parcial / decomposição de valor** (o `Bearer ` do relatório
  propriamente dito). É a **spec seguinte**, e depende do corpus estruturado desta
  como base. O que já foi medido e decidido sobre ela está na seção 6.
- **`origin_key` por substring** — é o cenário `Sec-Fetch-Site` ×
  `Cross-Origin-Opener-Policy` da spec de 04/08. Ver 3.4 para o que a regra de
  igualdade exata protege e o que **não** protege.
- **Trocar o corpus de `real_responses` para `original_responses` em `--mode main`.**
  Medido: +2 candidatos, 0 perdidos. Ortogonal; fica para a spec seguinte.
- **Aviso agregado de "valores sem origem" em `replay`/`optimize`.** Estava na
  revisão 1 e foi **removido**: medido que 1.035 ocorrências sem origem se espalham
  por **235 dos 238 steps**, sempre os mesmos 22 paths, então o aviso seria um número
  praticamente constante em toda execução — ruído que se aprende a ignorar. E não há
  discriminador barato: `header:Authorization` tem **1 valor distinto em 9 steps**,
  indistinguível em forma de `header:Accept`. A linha no `.curl.sh` (3.9) fica; o
  aviso agregado, não. A causa raiz é `BaselineDiff` comparar contra a primeira entry
  do HAR, declarada fora de escopo desde a spec de 04/08.
- **`TokenResolver`** continua recebendo `responses_dir: Path` cru — resolve tokens já
  registrados, não descobre origem.
- **`BaselineDiff` tratar header contextual como candidato dinâmico** — continua fora,
  pelos mesmos motivos da spec de 04/08.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `ResponseGrep` — `har_reproducer/tracking/response_grep.py` (arquivo inteiro)

```python
class ResponseGrep:

    @classmethod
    def find(cls, responses_dir: Path, pattern: str, before_step_index: int) -> Optional[Tuple[int, str]]:
        candidate_files: List[Path] = cls._eligible_response_files(responses_dir, before_step_index)
        if not candidate_files:
            return None

        for variant in cls.value_variants(pattern):
            match: Optional[Tuple[int, str]] = cls._grep_single_pattern(candidate_files, variant)
            if match is not None:
                return match
        return None

    @staticmethod
    def try_decode(value: str) -> str: ...

    @classmethod
    def value_variants(cls, value: str) -> List[str]:
        candidates: List[str] = [
            value,
            cls.try_decode(value),
            urllib.parse.quote(value, safe=""),
            base64.b64encode(value.encode("utf-8")).decode("ascii"),
        ]
        return cls._deduplicate(candidates)

    @classmethod
    def _grep_single_pattern(cls, candidate_files: List[Path], pattern: str) -> Optional[Tuple[int, str]]:
        cmd: List[str] = ["grep", "-lF", pattern, *(str(path) for path in candidate_files)]
        result: CompletedProcess[str] = subprocess.run(cmd, capture_output=True, text=True, check=True)
        ...
        first_match_file: str = sorted(result.stdout.splitlines())[0]
        ...
        return step_index, filename

    @classmethod
    def _eligible_response_files(cls, responses_dir: Path, before_step_index: int) -> List[Path]:
        eligible: List[Path] = []
        for path in sorted(responses_dir.glob("res_*.json")):
            step_index: Optional[int] = cls._extract_step_index(path.name)
            if step_index is not None and step_index < before_step_index:
                eligible.append(path)
        return eligible
```

Três responsabilidades misturadas: **variantes de encoding**
(`value_variants`/`try_decode`/`_deduplicate`), **elegibilidade temporal**
(`_eligible_response_files`/`_extract_step_index`, o que garante que uma origem nunca
é uma resposta futura), e **busca** (`_grep_single_pattern`, via `subprocess`). O
retorno `Tuple[int, str]` carrega `(step_index, filename)`; o `filename` **não é lido
por ninguém**.

`value_variants` é chamado de fora por `TokenLocationDetector._value_present`
(`token_location_detector.py:113-115`):

```python
@classmethod
def _value_present(cls, value: str, text: str) -> bool:
    return any(variant in text for variant in ResponseGrep.value_variants(value))
```

⚠️ Duas propriedades do comportamento atual que serão referenciadas em 3.3:

1. **`grep -F` com padrão multi-linha casa por OR de linha.** Verificado no shell: o
   padrão `"QQQ\nZZZ"` casa num arquivo que contém só `ZZZ`. Ou seja, hoje um
   candidato cujo valor tenha `\n` acha origem se **qualquer uma** de suas linhas
   estiver na resposta.
2. **`sorted(result.stdout.splitlines())[0]` é ordenação lexicográfica de caminhos**,
   que coincide com "menor índice" apenas porque `Workspace.STEP_INDEX_WIDTH = 4` é
   fixo e o padding é uniforme — não por construção.

### `CandidateResolver` — `har_reproducer/tracking/candidate_resolver.py:24-70,126-132,163-172`

```python
    def __init__(
            self,
            responses_dir: Path,
            session_store: SessionStore,
            extractor_runner: ExtractorRunner,
            metadata_store: ExtractorMetadataStore,
            agent_factory: AgentFactory,
    ) -> None:
        self.responses_dir: Path = responses_dir
        ...
        self._origin_cache: Dict[str, Tuple[int, str]] = {}

    def _process_candidate(self, candidate: DynamicToken, step_index: int) -> DynamicToken:
        origin: Optional[Tuple[int, str]] = self._find_origin(candidate.current_value, step_index)
        if not origin:
            candidate.status = "NotFound"
            return candidate

        candidate.origin_step = origin[0]
        base_token_id: str = self._derive_token_id(candidate.path, candidate.origin_step)
        ...

    def _find_origin(self, value: str, step_index: int) -> Optional[Tuple[int, str]]:
        cached_origin: Optional[Tuple[int, str]] = self._origin_cache.get(value)
        if cached_origin is not None:
            return cached_origin
        origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, value, step_index)
        if origin is not None:
            self._origin_cache[value] = origin
        return origin

    def _generate_new_extractor(self, candidate: DynamicToken, initial_error: Optional[str]) -> DynamicToken:
        candidate.status = "UnderReview"
        response_sample: Optional[Dict[str, Any]] = self._load_response(candidate.origin_step)
        if response_sample is None:
            return candidate
        candidate.origin_location = TokenLocationDetector.find(candidate.current_value, response_sample)
        self._register_extractor(candidate, response_sample, initial_error)
        return candidate

    def _load_response(self, step_index: int) -> Optional[Dict[str, Any]]:
        res_file: Path = self.responses_dir / f"res_{step_index:04d}.json"
        if not res_file.exists():
            return None
        try:
            data: Dict[str, Any] = json.loads(res_file.read_text(encoding="utf-8"))
            return data
        except Exception as e:
            print(f"[AVISO] Falha ao carregar response do step {step_index}: {e}")
            return None
```

Único consumidor de `ResponseGrep.find`. Usa só `origin[0]`. `_load_response` faz uma
**segunda** leitura do mesmo arquivo, como `Dict`, para servir de `response_sample` ao
`TokenLocationDetector` e ao `Agent` — é esse dicionário que
`ExtractorTemplate.render_temp_script` embute no script de verificação.

⚠️ **`_origin_cache` só guarda positivos.** É a causa da medição da seção 1.3 e do
custo da decisão 3.6: medido, o candidato `header:Sec-Fetch-Site = "same-origin"`
aparece em mais de 200 steps e, sem origem, dispara uma varredura completa em cada um.

### `TokenLocationDetector.find` — `har_reproducer/tracking/token_location_detector.py:11-30`

```python
    @classmethod
    def find(cls, value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        location: Optional[TokenLocation] = cls._find_in_cookies(value, response_sample)
        if location is not None:
            return location
        location = cls._find_in_headers(value, response_sample)
        ...
```

⚠️ **Procura cookies ANTES de headers.** Qualquer nova descoberta de chave de origem
tem que usar a mesma precedência, sob pena de o agente escolhido (derivado de
`origin_location`) discordar do container da chave (ver 3.4/3.7).

### `BaseAgent.key` / `__init__` — `har_reproducer/agents/base_agent.py:20-51`

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

`key` é a chave **de destino**, derivada de `candidate.path`. É usada por
`HeaderAgent._by_name`/`_header_value`, `CookieAgent._by_name`/`_context_pattern` e
`RegexAgent._key_pattern` — todos aplicando essa chave **sobre a resposta de origem**,
que é onde a suposição quebra.

⚠️ `RegexAgent._key_pattern` tem o guard `if not key or key == "body"`. Se `key`
passar a vir de outra fonte, esse guard deixa de proteger.

### `HeaderAgent._context_pattern` — `har_reproducer/agents/header_agent.py:45-55`

```python
    def _context_pattern(self) -> Optional[str]:
        header_value: Optional[str] = self._header_value()
        if not header_value:
            return None
        pos: int = header_value.find(self.expected_value)
        if pos == -1:
            return None
        prefix: str = header_value[:pos]
        suffix: str = header_value[pos + len(self.expected_value):]
        boundary: str = rf"(?={re.escape(suffix[0])})" if suffix else "$"
        return rf"{re.escape(prefix)}({self.lazy_value_char_class()}){boundary}"
```

Recebeu na spec de 04/08 (decisão 3.2, bloco ⚠️ "achado durante a implementação") a
combinação **classe preguiçosa + lookahead do caractere real que segue o valor**.

### `RegexAgent` — `har_reproducer/agents/regex_agent.py:20-36`

```python
    def _key_pattern(self) -> Optional[str]:
        key: Optional[str] = self.key
        if not key or key == "body":
            return None
        return rf"{re.escape(key)}['\"]?\s*[:=]\s*['\"]?({self.value_char_class()})"

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

**Não** recebeu o tratamento acima: grupo guloso, sem âncora de fim.

### `CurlTokenComment` — `har_reproducer/replay/curl_token_comment.py` (arquivo inteiro)

```python
class DependencyPhrase(str, Enum):
    COMES_FROM_STEP = "comes from response of step"

class OriginStatusPhrase(str, Enum):
    UNDETERMINED = "origin location undetermined — using literal captured value"
    EXTRACTION_EXHAUSTED = "origin location determined but extraction exhausted — using literal captured value"

class ReplayStatusPhrase(str, Enum):
    PROBABLY_STATIC = "probably static"
    COULD_NOT_EXTRACT = "could not extract value from response, using captured value"

class CurlTokenComment:
    CATEGORY_SEPARATOR: ClassVar[str] = "; "
    CLAUSE_CLOSING_MARKER: ClassVar[str] = "]"
    DEPENDENCY_PATTERN: ClassVar[Pattern[str]] = re.compile(
        r"^# \[Token (?P<token_id>[a-z0-9]+) "
        rf"{re.escape(DependencyPhrase.COMES_FROM_STEP.value)} "
        r"(?P<origin_step>\d+)\]",
        re.MULTILINE,
    )
    def format_dependency_line(self, token_id, origin_step, origin_status=None) -> str: ...
    def with_replay_status(self, line, phrase) -> str: ...
    def parse(self, curl_text: str) -> Dict[str, int]: ...
```

Formato consolidado na etapa de 12/08: a **cláusula** vive entre colchetes e o
`DEPENDENCY_PATTERN` ancora só nela; status extra vai **depois** do `]`, separado por
`"; "`. Contrato que **não pode ser afrouxado**.

### `CurlGenerator._token_comments` — `har_reproducer/reproduction/curl_generator.py:61-77`

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

Token sem `origin_step` (todo candidato `NotFound`) é silenciosamente ignorado.

### `EngineFactory.create`/`_build_tracker` — `engine_factory.py:51-96`

```python
        tracking_responses_dir: Path = (
            self.workspace.real_responses if engine_cls.USES_NETWORK else self.workspace.original_responses
        )
        ...
        candidate_resolver: CandidateResolver = CandidateResolver(
            tracking_responses_dir, session_store, extractor_runner, metadata_store, agent_factory
        )
```

Raiz de composição do ramo `run` — único lugar que pode instanciar os colaboradores
novos. ⚠️ Qualquer mudança na assinatura de `CandidateResolver.__init__` **tem que
mudar este arquivo no mesmo commit**, ou o repositório não executa.

### `Engine._reproduce`/`_process_entry` — `har_reproducer/engines/engine.py:44-82`

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

    def _process_entry(self, index, entry, first_entry) -> StepResponse:
        step: Step = HARParser.parse_entry(entry, index)
        ...
```

⚠️ `_reproduce` **não tem o `Step` em mãos** — `HARParser.parse_entry` roda dentro de
`_process_entry`, que devolve só o `StepResponse` da execução (não a resposta gravada
no HAR). Qualquer contagem sobre a resposta *do HAR* precisa resolver isso (3.10).

### `HARParser.parse_entry` — `har_reproducer/fs_io/har_parser.py:64-82`

```python
        res_content: Dict[str, Any] = res_data.get("content", {})
        text: Optional[str] = res_content.get("text")
        encoding: Optional[str] = res_content.get("encoding")
        body: str = HARParser.decode_body(text or "", encoding)
```

`content` sem `text` (ou com `text` vazio) vira `body=""` **sem aviso**. Medido no
`progressofit.har`: **140 de 238** entries nessa situação, distribuídas assim:

| status | entries sem corpo |
|---|---|
| 304 | 124 |
| 200 | 5 |
| 404 | 5 |
| 101 | 3 |
| 403 | 2 |
| -1 | 1 |

⚠️ **89% são `304 Not Modified`**, que por definição não têm corpo. O sinal acionável
é **12**, não 140 — e a entry `154` (`POST /auth/login`, status 200, corpo vazio),
origem do JWT do relatório, está entre eles.

## 3. Decisões de arquitetura

### 3.1 — `ValueVariants`: extrair as variantes de encoding para uma classe própria

**Estado atual:** `ResponseGrep.value_variants`/`try_decode`/`_deduplicate` são
métodos de `ResponseGrep`, consumidos de fora por `TokenLocationDetector`.

**Estado esperado:** arquivo novo `har_reproducer/tracking/value_variants.py`:

```python
class ValueVariants:

    @staticmethod
    def try_decode(value: str) -> str:
        # corpo idêntico ao ResponseGrep.try_decode atual

    @classmethod
    def of(cls, value: str) -> List[str]:
        candidates: List[str] = [
            value,
            cls.try_decode(value),
            urllib.parse.quote(value, safe=""),
            base64.b64encode(value.encode("utf-8")).decode("ascii"),
        ]
        return cls._deduplicate(candidates)

    @staticmethod
    def _deduplicate(values: List[str]) -> List[str]:
        # corpo idêntico ao ResponseGrep._deduplicate atual
```

`TokenLocationDetector._value_present` passa a chamar `ValueVariants.of(value)`.
Motivo: `ResponseGrep` deixa de ser classe de utilidade sem estado (3.3) e passa a
receber colaborador por construtor; manter dentro dele um utilitário que outra classe
consome estaticamente misturaria os dois papéis.

⚠️ Comportamento **idêntico**: a ordem das variantes (`cru`, `decodificado`,
`URL-encode`, `base64-encode`) é significativa — a primeira que casar vence.

### 3.2 — `ResponseCorpus`: corpus estruturado de respostas, com memoização por step

**Estado atual:** não existe. A leitura está partida entre
`ResponseGrep._eligible_response_files` e `CandidateResolver._load_response`.

**Estado esperado:** arquivo novo `har_reproducer/tracking/response_corpus.py`:

```python
class ResponseCorpus:

    def __init__(self, responses_dir: Path, step_index_width: int) -> None:
        self.responses_dir: Path = responses_dir
        self.step_index_width: int = step_index_width
        self._responses: Dict[int, Dict[str, Any]] = {}
        self._searchable: Dict[int, str] = {}

    def eligible_indexes(self, before_step_index: int) -> List[int]:
        indexes: List[int] = []
        for path in sorted(self.responses_dir.glob("res_*.json")):
            step_index: Optional[int] = self._extract_step_index(path.name)
            if step_index is not None and step_index < before_step_index:
                indexes.append(step_index)
        return indexes

    def response(self, step_index: int) -> Optional[Dict[str, Any]]:
        # memoiza em self._responses; mesmo tratamento de erro de _load_response

    def searchable_text(self, step_index: int) -> Optional[str]:
        # memoiza em self._searchable a partir de response()

    @classmethod
    def _serialize(cls, response: Dict[str, Any]) -> str:
        parts: List[str] = []
        for name, value in (response.get("headers") or {}).items():
            parts.append(f"{name}: {value}")
        for name, value in (response.get("cookies") or {}).items():
            parts.append(f"{name}={value}")
        redirect_url: Optional[str] = response.get("redirect_url")
        if redirect_url:
            parts.append(str(redirect_url))
        body: Optional[Union[str, bytes]] = response.get("body")
        if body:
            parts.append(cls._decode_body(body))
        return "\n".join(parts)
```

Notas de projeto:

- O `searchable_text` é o **conteúdo real** da resposta: nada escapado. É isso que
  fecha a Falha A.
- **A memoização é por índice de step e é obrigatória.** Medido: sem ela, uma execução
  completa faz **121.318** desserializações a 0,091 ms cada = **~11 s** — contra
  ~5 s do `grep -lF` de hoje, ou seja, uma regressão de ~2×. Com memoização são 238
  desserializações (~0,02 s). ⚠️ A revisão 1 desta spec **proibia** cache aqui,
  baseada numa medição de 269 buscas em vez das ~121 mil reais; a proibição está
  removida.
- ⚠️ `eligible_indexes` **nunca** é memoizado: em `--mode main` o diretório cresce
  enquanto o pipeline roda. Memoizar `response`/`searchable_text` é seguro porque
  `Engine._persist_response_step` escreve cada arquivo uma única vez.
- `response()` devolve o `Dict` cru do JSON, **não** `StepResponse`: é esse dicionário
  que vira `response_sample` para `TokenLocationDetector` e para o `Agent`.
- A ordem da serialização (`headers`, `cookies`, `redirect_url`, `body`) faz parte do
  contrato.
- ⚠️ O corpus novo **descarta** campos que o texto do arquivo continha:
  `status_code`, `body_mime`, `skipped`, `skip_reason` e os próprios nomes de campo
  JSON. Medido neste workspace: 0 candidatos perdidos. Mas a classe "valor que só
  existia em `body_mime`" some — é um aperto intencional (um `Content-Type` de
  requisição não "vem" do `body_mime` de uma resposta).

### 3.3 — `OriginFinder` (era `ResponseGrep`): busca sobre o corpus, sem `subprocess`

**Estado atual:** ver seção 2 — `@classmethod` recebendo `responses_dir: Path`,
`subprocess.run(["grep", "-lF", ...])`, retorno `Tuple[int, str]`.

**Estado esperado:** a classe é renomeada para `OriginFinder`
(`har_reproducer/tracking/origin_finder.py`) — não sobra nenhum `grep` no nome nem no
corpo — e vira classe de instância:

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

    def _find_variant(self, eligible: List[int], variant: str, is_raw: bool) -> Optional[OriginMatch]:
        for step_index in eligible:
            text: Optional[str] = self.corpus.searchable_text(step_index)
            if text is None or variant not in text:
                continue
            return self._build_match(step_index, variant, is_raw)
        return None
```

⚠️ Comportamento **preservado**:

- **Ordem das variantes manda sobre a ordem dos steps**: esgota todos os steps com a
  variante 1 antes de tentar a variante 2, como `find` faz hoje.
- **Desempate pelo menor índice.** ⚠️ Hoje isso é ordenação **lexicográfica de nomes
  de arquivo** (`sorted(result.stdout.splitlines())[0]`), que coincide com ordem
  numérica só porque `STEP_INDEX_WIDTH = 4` é fixo. A nova implementação ordena
  inteiros, o que é a intenção original — a equivalência vale para todo workspace com
  padding uniforme, que é o único que o `Workspace` produz.
- **Causalidade temporal** (`step_index < before_step_index`) mora agora em
  `ResponseCorpus.eligible_indexes`.

⚠️ Mudanças **deliberadas** de comportamento, que precisam de teste próprio:

1. **Valores multi-linha passam a exigir casamento integral.** Hoje `grep -F` trata um
   padrão com `\n` como vários padrões alternativos, então um candidato multi-linha
   casa se **qualquer** de suas linhas estiver na resposta — falso-positivo grosseiro.
   `variant not in text` é estrito. Medido: **0 candidatos com `\n` no valor neste
   workspace**, logo 0 impacto aqui, mas é aperto real e intencional.
2. Sai `subprocess` e o `except subprocess.CalledProcessError`.
3. O `filename` do retorno some (ninguém lia).
4. Novo parâmetro `from_step_index`, exigido pelo cache de negativos (3.6). É
   **obrigatório**, sem default — o guia de estilo desaconselha default que esconde
   decisão.

### 3.4 — `OriginMatch`, `OriginContainer` e a regra do `origin_key`

**Estado atual:** a origem é um `Tuple[int, str]`.

**Estado esperado:** novos tipos em `har_reproducer/models/analysis.py`:

```python
class OriginContainer(str, Enum):
    HEADER = "Header"
    COOKIE = "Cookie"


class OriginMatch(BaseModel):
    step_index: int
    origin_key: Optional[str] = None
    origin_container: Optional[OriginContainer] = None
```

**Regra do `origin_key`** — só é preenchido quando as **duas** condições valem:

1. o casamento ocorreu com a **variante crua** (o próprio `current_value`);
2. existe um cookie **ou** header da resposta de origem cujo valor é **exatamente
   igual** ao valor procurado.

⚠️ **Precedência: cookies antes de headers**, idêntica à de
`TokenLocationDetector.find`. Ordem invertida (headers primeiro, como na revisão 1
desta spec) produz regressão limpa: valor presente nos dois containers →
`origin_location = Cookie` → `CookieAgent` recebendo **nome de header** como chave →
`cookies.get("ETag")` → falha, **e** desliga a chave derivada de `path`, que era a
única com chance. `origin_container` existe para tornar esse acoplamento explícito
(ver 3.7).

Razão de cada condição:

- **(1) variante crua** — o `Agent` é verificado contra `expected_value =
  candidate.current_value`. Se o casamento foi por variante transformada, um extrator
  que devolva o valor daquele header devolveria algo diferente do esperado.
- **(2) igualdade exata** — casamento por substring é o cenário `Sec-Fetch-Site` ×
  `Cross-Origin-Opener-Policy` da spec de 04/08, onde `"same-origin"` é substring
  genuína de `"same-origin-allow-popups"`. Hoje esse caso falha de forma inofensiva;
  com `origin_key` por substring, `HeaderAgent._context_pattern` passaria a **ter
  sucesso** sobre um header sem relação causal.

⚠️ **Risco residual aceito, medido e declarado:** igualdade exata elimina a classe
*substring*, **não** a classe *coincidência de valor de baixa entropia*. Contraexemplo
real deste workspace: `header:Cache-Control = "no-cache"` recebe
`origin_key = "Pragma"`, porque a resposta de origem tem `Pragma: no-cache` — mesmo
valor, nenhuma relação causal. O extrator gerado é verificado e conceitualmente
errado. Isso **não é regressão**: hoje esse candidato já vira extrator (via
`_context_pattern` sobre o próprio `Cache-Control`), e o valor extraído é o mesmo.
Aceito para esta etapa; a evidência que discriminaria (o valor rotaciona? aparece em
uma única resposta?) é assunto da spec seguinte.

### 3.5 — `DynamicToken.origin_key` e `origin_container`

**Estado atual** (`models/session.py:46-54`): sem esses campos.

**Estado esperado:**

```python
class DynamicToken(BaseModel):
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

⚠️ **Não** adicionar campos espelho em `Extractor`: só têm consumidor no cache-miss
(onde o agente é construído); num cache-hit nenhum agente é criado. Persistir sem
consumidor seria campo morto em todo `.meta.json`.

### 3.6 — `CandidateResolver`: corpus por construtor, `origin_key`, e cache de negativos

**Estado atual:** recebe `responses_dir: Path`, chama `ResponseGrep.find`
estaticamente, relê o arquivo em `_load_response`, e **só cacheia origens positivas**.

**Estado esperado:**

```python
    def __init__(
            self,
            response_corpus: ResponseCorpus,
            origin_finder: OriginFinder,
            session_store: SessionStore,
            extractor_runner: ExtractorRunner,
            metadata_store: ExtractorMetadataStore,
            agent_factory: AgentFactory,
    ) -> None:
        self.response_corpus: ResponseCorpus = response_corpus
        self.origin_finder: OriginFinder = origin_finder
        ...
        self._origin_cache: Dict[str, OriginMatch] = {}
        self._origin_misses: Dict[str, int] = {}

    def _process_candidate(self, candidate: DynamicToken, step_index: int) -> DynamicToken:
        origin: Optional[OriginMatch] = self._find_origin(candidate.current_value, step_index)
        if origin is None:
            candidate.status = "NotFound"
            return candidate

        candidate.origin_step = origin.step_index
        candidate.origin_key = origin.origin_key
        candidate.origin_container = origin.origin_container
        base_token_id: str = self._derive_token_id(candidate.path, candidate.origin_step)
        ...

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

**O cache de negativos é a decisão, não a otimização.** `_origin_misses[value] = N`
significa "já varri todos os steps `< N` e não achei". Numa consulta futura em
`M > N`, só `[N, M)` precisa ser varrido. É **monotônico e correto**: uma resposta já
gravada não muda, e `Workspace` escreve cada `res_NNNN.json` uma única vez. Medido: é
o que evita que a troca de corpus vire regressão de performance (ver 3.2).

`_load_response` é **removido**; `_generate_new_extractor` chama
`self.response_corpus.response(candidate.origin_step)`.

⚠️ `self.responses_dir` some, mas `_check_persisted_slot`
(`candidate_resolver.py:108`) continua precisando de um `Path` para
`ExtractorRunner.run_existing` — passa a vir de `self.response_corpus.responses_dir`.
É acoplamento a um atributo de outro objeto (Demeter); **aceito como dívida
declarada**, porque a alternativa (mudar a assinatura de `ExtractorRunner`) tem raio
de alcance maior e nenhum defeito observado a justificar.

⚠️ `_origin_cache` continua chaveado **só pelo valor**, sem o `path`
(`docs/20260805 Regressão de Cache de Origem no CandidateResolver`). Com `origin_key`
e `origin_container` no cache, dois candidatos de `path` diferente e mesmo valor
passam a compartilhar também esses campos. Isso é **correto por construção**:
`origin_key`/`origin_container` são função de `(valor, resposta de origem)`, não do
path de destino. Medido: `header:origin` e `header:Origin` são exatamente esse caso.

⚠️ `_derive_token_id` continua `md5(f"{path}:{origin_step}")` — `origin_key` **não**
entra no hash, sob pena de mudar a identidade de todo slot já persistido.

⚠️ O ramo de cache-hit (`registry.get(slot_id) is not None`) continua **não**
preenchendo `origin_location` (bug §3.2 do relatório de 11/08). Fora do escopo.

### 3.7 — `BaseAgent`/`AgentFactory`: chave de origem, só quando o container concorda

**Estado atual:** `key` deriva sempre de `path` (destino).

**Estado esperado:**

```python
    def __init__(self, token_id, response_sample, expected_value, workspace, script_executor, sleeper,
                 path=None, location=None, origin_key=None, llm=None) -> None:
        ...
        self.origin_key: Optional[str] = origin_key

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

E `AgentFactory.create` passa `origin_key` **apenas quando o container concorda com a
location de origem**:

```python
    CONTAINER_LOCATIONS: ClassVar[Dict[OriginContainer, TokenLocation]] = {
        OriginContainer.HEADER: TokenLocation.HEADER,
        OriginContainer.COOKIE: TokenLocation.COOKIE,
    }

    @classmethod
    def _origin_key_for(cls, candidate: DynamicToken) -> Optional[str]:
        if candidate.origin_container is None:
            return None
        if cls.CONTAINER_LOCATIONS.get(candidate.origin_container) != candidate.origin_location:
            return None
        return candidate.origin_key
```

⚠️ Esse guard é o que impede três regressões:

1. `CookieAgent` recebendo nome de header (e vice-versa) quando o valor está nos dois
   containers;
2. `RegexAgent._key_pattern` passar a procurar **no body** por um nome de header —
   com `origin_location` em `SCRIPT`/`BODY_*` o container nunca concorda, então
   `origin_key` não chega lá e o comportamento é o de hoje;
3. o guard `if not key or key == "body"` de `_key_pattern` continuar significando o
   que significa.

⚠️ A revisão 1 desta spec afirmava que o efeito em `RegexAgent._key_pattern` era
"colateral e desejável". **Estava errado** — procurar `ETag['\"]?\s*[:=]` dentro de um
bundle JS é uma tentativa a mais fadada a falhar. Corrigido pelo guard acima.

⚠️ Os três agentes consumidores (`HeaderAgent`, `CookieAgent`, `RegexAgent`) **não
mudam nenhuma linha** — verificado que todos os call sites usam argumentos nomeados.

### 3.8 — `RegexAgent._context_pattern`: âncora de fim e classe preguiçosa

**Estado atual:** grupo guloso, sem fronteira de fim.

**Estado esperado:**

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

Mesma forma de `HeaderAgent`/`CookieAgent` (spec de 04/08, decisão 3.2).

Defeito que isso corrige: quando `expected_value` contém caractere fora de
`[\w\-.]` (qualquer `/`, típico de caminho e URL), `value_char_class()` devolve `.+?`
que, **sem âncora de fim, casa exatamente um caractere**. ⚠️ A revisão 1 dizia "falha
sempre" — falso na borda: para `expected_value` de **um** caractere, acerta.

⚠️ `_key_pattern` **não muda**.

⚠️ Churn medido nos 57 extratores persistidos em `arquivos-har/output/extractors/`:
7 são `RegexAgent`, dos quais 5 foram escritos por LLM (não passam por
`_context_pattern`) e **2 são determinísticos**. Nos dois, o caractere seguinte ao
valor está fora de `[\w\-.]`, então guloso e preguiçoso-com-lookahead capturam o mesmo
grupo: **muda o texto do regex, não o valor extraído**. Nenhum extrator que hoje
verifica passa a falhar.

### 3.9 — `CurlTokenComment`/`CurlGenerator`: linha de auditoria para valores sem origem

**Estado atual:** candidato `NotFound` não deixa rastro nenhum no `.curl.sh`, e é
essa ausência que faz `optimize` reportar `SUCCESSFUL` sobre um schedule cheio de
literais congelados sem aviso (relatório de 11/08, seções 3.1/3.4).

**Estado esperado:** nova cláusula em `CurlTokenComment`:

```python
class CurlTokenComment:
    ...
    UNRESOLVED_PATTERN: ClassVar[Pattern[str]] = re.compile(
        r"^# \[Unresolved (?P<count>\d+)\] (?P<paths>.+)$",
        re.MULTILINE,
    )

    def format_unresolved_line(self, paths: List[str]) -> str:
        clause: str = f"# [Unresolved {len(paths)}]"
        return f"{clause} {self.CATEGORY_SEPARATOR.join(paths)}"

    def parse_unresolved(self, curl_text: str) -> List[str]:
        match: Optional[Match[str]] = self.UNRESOLVED_PATTERN.search(curl_text)
        if match is None:
            return []
        return match.group("paths").split(self.CATEGORY_SEPARATOR)
```

E `CurlGenerator._token_comments` emite **uma** linha consolidada, depois das linhas
de dependência:

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

Decisões de forma, todas medidas:

- **Uma linha consolidada por step.** Medido: 1.035 ocorrências sem origem em **235
  dos 238 steps** (distribuição: 133 steps com 4 paths, 74 com 5, 11 com 6, e uma
  cauda até 10). Uma linha por candidato encheria todo `.curl.sh` e o golden.
- Maior linha gerada no workspace real: **208 caracteres**. Nenhum dos 22 paths
  contém `"; "` nem `\n`, então o `split(CATEGORY_SEPARATOR)` de `parse_unresolved` é
  seguro.
- Lista **paths**, nunca valores — identifica o que ficou congelado sem escrever
  credencial no arquivo.
- A ordem dos paths segue a ordem dos tokens recebidos (ordem de
  `BaselineDiff.detect_candidates`) — determinismo é requisito do golden.
- `UNRESOLVED_PATTERN` e `DEPENDENCY_PATTERN` **não** se casam cruzado (a palavra após
  `[` difere), e nenhuma anotação de replay é anexada a essa linha.

⚠️ **Limitação declarada:** a linha aparece em praticamente todo `.curl.sh` deste
workspace, e 20 dos 22 paths são header de contexto de navegador
(`Accept`, `Sec-Fetch-*`, `user-agent`) que são inofensivos como literal. O valor da
linha é ser **grep-ável** (`grep -l 'Unresolved.*Authorization' curls/*.sh`), não ser
um alarme. A causa da diluição é `BaselineDiff` comparar contra a primeira entry do
HAR — fora de escopo desde a spec de 04/08. **Foi por isso que o aviso agregado em
`replay`/`optimize` (decisão 3.10 da revisão 1) foi removido**: seria um número
praticamente constante, e não existe discriminador barato — medido,
`header:Authorization` tem 1 valor distinto em 9 steps, indistinguível em forma de
`header:Accept`.

### 3.10 — Aviso de entries do HAR sem corpo de resposta gravado

**Estado atual:** `HARParser.parse_entry` transforma `content` sem `text` em
`body=""` silenciosamente; `Engine._reproduce` não tem o `Step` em mãos para contar.

**Estado esperado:** a contagem vive no `HARParser`, que é a classe que já conhece o
formato do HAR, e `Engine._reproduce` só reporta — sem estado novo em `Engine`:

```python
class HARParser:
    BODYLESS_STATUS_CODES: ClassVar[Set[int]] = {101, 204, 304}

    @classmethod
    def entries_missing_response_body(cls, entries: List[Dict[str, Any]]) -> int:
        return sum(1 for entry in entries if cls._missing_response_body(entry))

    @classmethod
    def _missing_response_body(cls, entry: Dict[str, Any]) -> bool:
        response: Dict[str, Any] = entry["response"]
        if response.get("status") in cls.BODYLESS_STATUS_CODES:
            return False
        return not (response.get("content", {}).get("text") or "")
```

`Engine._reproduce` chama isso com as `entries` que já tem em mãos e imprime uma vez,
quando maior que zero:

```
WARNING: 12 de 238 entries do HAR não têm corpo de resposta gravado (excluídos os
status 101/204/304, que normalmente não carregam corpo). Origens de token que
estejam nesses corpos são indescobríveis — regrave o HAR preservando o conteúdo das
respostas ("Preserve log" + export completo).
```

⚠️ **`BODYLESS_STATUS_CODES` é conhecimento de protocolo hardcoded, e é uma exceção
consciente ao princípio de genericidade de [[arquitetura-e-fundamentos]].** A razão:
sem o recorte, o aviso mais alarmante do produto diria "140 de 238" num HAR gravado
corretamente, sendo 124 deles `304 Not Modified` — 89% de ruído, e o usuário
regravaria um HAR que já estava certo. O recorte é sobre **quais status carregam
corpo**, um fato de HTTP e não uma suposição sobre o site; nenhum header, formato de
token ou convenção de aplicação é assumido. Alternativa considerada e descartada:
imprimir a distribuição por status sem filtrar — mais genérico, porém obriga o
usuário a fazer o recorte de cabeça toda vez.

⚠️ **Não** transformar em erro nem alterar o retorno de `run()`; imprimir antes do
`Final Validation Result`. `DryEngine` herda `_reproduce` sem alteração própria.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `tracking/value_variants.py` (**novo**) | `ValueVariants` — `of`/`try_decode`/`_deduplicate` movidos de `ResponseGrep` |
| `tracking/response_corpus.py` (**novo**) | `ResponseCorpus` — `eligible_indexes`/`response`/`searchable_text`, com memoização por step |
| `tracking/origin_finder.py` (**novo**, era `response_grep.py`) | `OriginFinder` — instância sobre `ResponseCorpus`, sem `subprocess`, `find(value, from_step_index, before_step_index)`, aplica a regra do `origin_key` |
| `tracking/response_grep.py` | **removido** |
| `models/analysis.py` | Novos `OriginContainer` (enum) e `OriginMatch` |
| `models/session.py` | `DynamicToken` ganha `origin_key` e `origin_container` |
| `models/__init__.py` | Exporta `OriginContainer` e `OriginMatch` |
| `tracking/__init__.py` | Exporta `ValueVariants`, `ResponseCorpus`, `OriginFinder`; remove `ResponseGrep` |
| `tracking/token_location_detector.py` | `_value_present` passa a usar `ValueVariants.of` |
| `tracking/candidate_resolver.py` | Recebe `ResponseCorpus` + `OriginFinder`; `_load_response` removido; grava `origin_key`/`origin_container`; **cache de negativos com janela** |
| `engines/construction/engine_factory.py` | Monta `ResponseCorpus` e `OriginFinder` e injeta no `CandidateResolver` |
| `agents/base_agent.py` | Novo `origin_key`; `key` passa a preferi-lo |
| `agents/construction/agent_factory.py` | `CONTAINER_LOCATIONS` + `_origin_key_for`: só propaga `origin_key` quando o container concorda com `origin_location` |
| `agents/regex_agent.py` | `_context_pattern` ganha classe preguiçosa + lookahead de fim |
| `replay/curl_token_comment.py` | `UNRESOLVED_PATTERN`, `format_unresolved_line`, `parse_unresolved` |
| `reproduction/curl_generator.py` | `_token_comments` emite a linha consolidada de valores sem origem |
| `fs_io/har_parser.py` | `BODYLESS_STATUS_CODES` + `entries_missing_response_body` |
| `engines/engine.py` | `_reproduce` imprime o aviso de HAR sem corpo |

## 5. Casos de borda e comportamento de erro

- **Resposta ilegível ou ausente** — `ResponseCorpus.response` mantém o
  `except Exception` + `print` de aviso + retorno `None` que `_load_response` tinha
  (borda de I/O, guia de estilo). `searchable_text` devolve `None` e `_find_variant`
  pula o step. ⚠️ A memoização **não** deve cachear a falha: um arquivo ainda não
  escrito em `--mode main` passa a existir depois.
- **Resposta sem nenhum campo** — `searchable_text` devolve `""`; `variant not in ""`
  é falso para variante não-vazia, e `ValueVariants._deduplicate` já descarta vazio.
- **Valor que casa em mais de uma resposta elegível** — vence o **menor índice**, como
  hoje.
- **Valor exatamente igual em duas chaves da mesma resposta** — vence o cookie (3.4);
  dentro do mesmo container, a primeira na ordem de iteração. Ambas extraem o mesmo
  valor.
- **Valor presente num cookie e num header** — `origin_container = COOKIE`,
  `origin_location = Cookie` (mesma precedência), `CookieAgent` recebe a chave do
  cookie. Sem o alinhamento de precedência de 3.4 este caso seria regressão.
- **`origin_key` de container que discorda de `origin_location`** — `AgentFactory`
  não o propaga; o agente usa a chave derivada de `path`, comportamento de hoje.
- **`origin_key` aponta para header que some numa execução futura** — o extrator falha
  no replay e cai no `captured_value` via `ReplayTokenResolver._fallback_to_captured`.
- **Casamento no `body` ou no `redirect_url`** — `origin_key` e `origin_container`
  ficam `None`; comportamento idêntico ao de hoje.
- **Candidato que casa por variante base64/URL** — `origin_key` fica `None` (3.4).
- **Valor multi-linha** — deixa de casar por linha isolada (3.3, aperto intencional).
  0 casos neste workspace.
- **Cache de negativos e resposta que aparece depois** — `_origin_misses[value] = N`
  só afirma algo sobre steps `< N`; steps `>= N` são sempre varridos.
- **Workspace com `.curl.sh` de rodada anterior** — `Workspace` nunca limpa nada; um
  curl antigo sem a linha `[Unresolved]` simplesmente não a tem.
- **`RegexAgent` cujo `expected_value` termina no fim do body** — `boundary = "$"`,
  caminho já exercitado por `HeaderAgent`.
- **`--mode dry`** — todo o desenho vale igual, com o corpus em `original_responses`.
  Neste HAR o ganho de 63 ETags **também acontece** em dry (ETags estão nos headers,
  que o HAR grava); o `Authorization` continua indescobrível por falta de corpo
  gravado, e passa a ser reportado pelo aviso de 3.10.

## 6. Suposições e pontos a confirmar

- Nomes (`ValueVariants`, `ResponseCorpus`, `OriginFinder`, `OriginMatch`,
  `OriginContainer`, `DynamicToken.origin_key`/`origin_container`) — sujeitos a
  ajuste.
- Texto do aviso de 3.10 e formato da linha `[Unresolved N]` — sujeitos a ajuste de
  wording. **Não** é ajustável a garantia de que `UNRESOLVED_PATTERN` e
  `DEPENDENCY_PATTERN` não se casem cruzado.
- Renomear `ResponseGrep` → `OriginFinder` é churn de diff em troca de um nome que
  não mente (não há mais `grep`). Confirmar se vale nesta etapa ou se fica para
  depois.
- **Decidido nesta conversa, registrado para a spec seguinte** (não implementar
  aqui): casamento por fragmento com âncora expandida; classificação da aresta em
  proveniência × necessidade comparando as duas épocas (`original_responses` ×
  `real_responses`), com proveniência **nunca** virando âncora de
  `compute_smart_schedule`; desempate de ambiguidade por maior fragmento e, no empate,
  pelo step mais recente; promoção proveniência → necessidade quando o replay observa
  divergência do `captured_value`; write-back de demoção a partir da fase 2 do
  `optimize`. **Descartados** com motivo: minimizar o número de extratores
  reconstruindo o valor por muitos fragmentos (a evidência de cada fragmento cai
  exponencialmente com o tamanho, e a reconstrução costura o literal obsoleto);
  invalidar extrator porque o literal "ainda funciona" (lógica invertida); gate de LLM
  antes de criar extrator (LLM é opcional e a ordem "determinístico antes de LLM" é
  princípio do projeto).

## 7. O que mudou da revisão 1 para a revisão 2

| # | Revisão 1 | Revisão 2 | Origem |
|---|---|---|---|
| 1 | 269 candidatos, 52 → 115 | **257, 54 → 117** (delta +63 e 0 perdidos confirmados) | medição por ocorrência, steps `ws://` pulados |
| 2 | "63 candidatos viram determinísticos" | **86** (63 `ETag` + 21 `Last-Modified` + 2 `Pragma`); 23 deles já queimam LLM hoje | medição |
| 3 | "custo <1 s, sem cache no corpus" | **~11 s sem cache**; memoização por step passa a ser obrigatória, mais cache de negativos com janela em `_origin_cache` | medição: 121.318 desserializações |
| 4 | "mesmo resultado da busca atual" | declara o **aperto multi-linha** do `grep -F` | verificado no shell |
| 5 | `origin_key` header → cookie | **cookie → header**, alinhado a `TokenLocationDetector`; `OriginMatch` ganha `origin_container` e `AgentFactory` só propaga quando concorda | regressão apontada por duas revisões independentes |
| 6 | "igualdade exata evita falso-positivo" | evita a classe **substring**; **não** evita coincidência de baixa entropia (`Cache-Control` → `Pragma`, medido). Risco declarado e aceito | medição |
| 7 | efeito em `RegexAgent._key_pattern` "desejável" | **errado**; bloqueado pelo guard de container | revisão |
| 8 | `.+?` sem âncora "falha sempre" | falha exceto para valor de 1 caractere; churn medido: 2 dos 7 `RegexAgent` mudam o texto do regex, 0 mudam o valor | medição |
| 9 | aviso agregado em `replay`/`optimize` (3.10) | **removido** — constante em 235/238 steps, sem discriminador barato | medição |
| 10 | "140 de 238 sem corpo", sem filtrar por status | **12 de 238**, excluindo 101/204/304; exceção ao princípio de genericidade declarada | medição: 124 são `304` |
| 11 | `Engine._reproduce` conta o `body` do `Step` | contagem no `HARParser`; `_reproduce` só reporta | `_reproduce` não tem o `Step` |
| 12 | `ResponseGrep` mantém o nome | renomeado para `OriginFinder` | não há mais `grep` |
| 13 | §4 omitia `models/__init__.py` e `tracking/__init__.py` | incluídos | revisão |

## Referência

Toda alteração de código desta spec segue o padrão descrito em [[guia-de-estilo]]
(`.claude/skills/guia-de-estilo`). As decisões respeitam o princípio de genericidade
de [[arquitetura-e-fundamentos]] — `ETag` não é conhecido pelo código, é **descoberto**
como a chave onde o valor procurado mora — com **uma exceção consciente e declarada**:
`HARParser.BODYLESS_STATUS_CODES` (decisão 3.10).
