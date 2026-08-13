# Spec — Corpus Estruturado de Respostas e Chave de Origem

## 1. Objetivo

O relatório `docs/20260811-3 Teste do Otimizador contra Servidor Real/relatorio.md`
(seção 3.1) registrou que o header `Authorization: Bearer <JWT>` nunca é modelado
como token dinâmico, e apontou como causa o fato de `ResponseGrep` não reconhecer o
prefixo `"Bearer "`. Investigando o pipeline para corrigir isso, apareceram **duas
falhas anteriores e independentes** desse diagnóstico, ambas na etapa de *descoberta
de origem* — a etapa que decide se um valor vira extrator ou vira literal congelado:

**Falha A — o corpus de busca é o texto serializado do arquivo, não a resposta.**
`ResponseGrep._grep_single_pattern` (`response_grep.py:62-82`) roda
`grep -lF <valor> res_NNNN.json`. Esses arquivos são a serialização Pydantic de
`StepResponse` (`Engine._persist_response_step`, `engine.py:99-100`), onde o body é
uma **string JSON** — aspas, barras e quebras de linha aparecem escapados
(`\"`, `\\`, `\n`). Qualquer valor de candidato que contenha um desses caracteres
**nunca casa consigo mesmo**, mesmo estando literalmente na resposta.

Medido sobre o workspace real (`arquivos-har/output`, 235 steps, 238 respostas,
269 candidatos `(path, value)` distintos):

| corpus de busca | candidatos que casam pelo valor inteiro |
|---|---|
| texto cru do `res_NNNN.json` (hoje) | **52** |
| serialização estruturada da resposta | **115** |
| perdidos ao trocar de corpus | **0** |

Os 63 ganhos são **todos** `header:If-None-Match` — ETags no formato
`W/"9b1-19a1d941a25"`, cujo `"` é escapado no arquivo. São 63 dependências reais,
já presentes no dado, que o pipeline hoje descarta por um detalhe de serialização.

**Falha B — o agente procura o valor pela chave de destino, não pela chave de
origem.** Quando a origem é encontrada, `AgentFactory.create`
(`agent_factory.py:38-51`) passa `path=candidate.path` — o caminho no **request**
(`header:If-None-Match`) — e `BaseAgent.key` (`base_agent.py:45-51`) deriva dali a
chave que `HeaderAgent._by_name` vai procurar **na resposta de origem**. Mas o valor
mora, na resposta, sob outra chave: `ETag`.

Medido: nos 63 casos acima, o valor está byte-idêntico no header `ETag` da resposta
de origem, e em **63 de 63** a resposta de origem **não tem** nenhum header chamado
`If-None-Match`. Ou seja, `_by_name` falharia em todos, `_context_pattern` também
(depende de `_header_value()`, que usa a mesma chave errada), e cada candidato
queimaria as 5 tentativas de LLM de `BaseAgent.MAX_LLM_ATTEMPTS` com
`RETRY_DELAY_SECONDS = 5` de espera entre elas — **315 chamadas de LLM e ~26 min de
sleep**, terminando em `LiteralFallbackAgent` (o caminho que a spec
`docs/20260804 Extração por Substring e Fallback de Exaustão` criou justamente para
não repetir trabalho fadado ao fracasso).

**O que esta mudança cobre:**

- Trocar o corpus de descoberta de "texto do arquivo" para uma **serialização
  estruturada da resposta** (headers, cookies, `redirect_url` e body decodificado),
  eliminando a classe inteira de falso-negativo por escape — e, de quebra, removendo
  a dependência de `subprocess`/`grep` do caminho de descoberta.
- Descobrir e propagar a **chave de origem** (`origin_key`): o nome do header ou
  cookie da resposta de origem cujo valor é exatamente o valor procurado. O agente
  passa a procurar por essa chave em vez da chave de destino — o que transforma 63
  candidatos hoje irrecuperáveis em extratores determinísticos, com **zero** chamadas
  de LLM.
- Dar paridade a `RegexAgent._context_pattern` com a âncora de fim que
  `HeaderAgent._context_pattern` ganhou na spec de 04/08 e que o `RegexAgent` não
  recebeu — hoje ele monta um grupo guloso sem fronteira, o que faz todo fragmento
  contendo `/` falhar sempre.
- Tornar **visível** o valor que não tem origem descoberta: hoje ele vira literal em
  silêncio, e `replay --mode smart`/`optimize` reportam sucesso sobre um schedule que
  só funciona enquanto aquele literal congelado do HAR continuar válido. Passa a
  existir uma linha de auditoria no `.curl.sh` e um relatório agregado nos comandos
  que executam schedule.

**Fora de escopo (decidido explicitamente):**

- **Casamento parcial / decomposição de valor** (o `Bearer ` do relatório
  propriamente dito, com localização por fragmento, unidade de origem, alinhamento de
  span e classificação da aresta em proveniência × necessidade). É a **spec seguinte**,
  e depende do corpus estruturado desta como base. Registrado na seção 6 o que já foi
  medido e decidido sobre ela, para não se perder.
- **`origin_key` por substring** (o valor ser apenas *parte* do valor de um header da
  origem). Descartado nesta etapa: é exatamente o cenário `Sec-Fetch-Site` ×
  `Cross-Origin-Opener-Policy` documentado na spec de 04/08 (seção 1), onde
  `"same-origin"` é substring genuína de `"same-origin-allow-popups"` sem nenhuma
  relação causal. Hoje esse caso falha de forma inofensiva (`_by_name` não acha a
  chave de destino → LLM → literal); com `origin_key` por substring, a estratégia de
  substring da spec de 04/08 passaria a **ter sucesso** e produziria um extrator
  *confiantemente errado*. A regra desta spec (3.4) só aceita casamento exato.
- **Trocar o corpus de descoberta de `real_responses` para `original_responses` em
  `--mode main`** (comparar valor-do-HAR com resposta-da-mesma-época). Medido:
  +2 candidatos, 0 perdidos neste workspace — conceitualmente relevante, praticamente
  pequeno, e ortogonal a esta etapa. Fica para a spec seguinte, onde a comparação
  entre as duas épocas passa a ter uso central.
- **`TokenResolver`** (`tracking/token_resolver.py`) continua recebendo
  `responses_dir: Path` cru e checando existência de arquivo — ele resolve tokens já
  registrados, não descobre origem, e não sofre nenhuma das duas falhas.
- **`BaselineDiff` tratar header contextual como candidato dinâmico** — causa raiz de
  fundo de vários falso-positivos, já declarada fora de escopo na spec de 04/08 pelos
  mesmos motivos (não existe solução fechada e universalmente correta). Continua fora.

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

Classe de utilidade sem estado (`@classmethod`/`@staticmethod`), citada como tal em
[[arquitetura-e-fundamentos]]. Três responsabilidades hoje misturadas: **variantes de
encoding** de um valor (`value_variants`/`try_decode`/`_deduplicate`), **elegibilidade
temporal** de respostas (`_eligible_response_files`/`_extract_step_index`, o que
garante que uma origem nunca é uma resposta futura), e **busca** (`_grep_single_pattern`,
via `subprocess`). O retorno `Tuple[int, str]` carrega `(step_index, filename)` — o
`filename` **não é lido por ninguém** (ver `CandidateResolver._find_origin` abaixo).

`value_variants` é chamado de fora da classe por
`TokenLocationDetector._value_present` (`token_location_detector.py:113-115`):

```python
@classmethod
def _value_present(cls, value: str, text: str) -> bool:
    return any(variant in text for variant in ResponseGrep.value_variants(value))
```

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

Único consumidor de `ResponseGrep.find`. Usa só `origin[0]`; o `filename` é
descartado. `_load_response` faz uma **segunda** leitura do mesmo arquivo, agora como
`Dict`, para servir de `response_sample` ao `TokenLocationDetector` e ao `Agent`. O
`response_sample` é o dicionário cru do JSON — é ele que `ExtractorTemplate.
render_temp_script` embute no script de verificação, então o formato precisa ser
exatamente esse.

### `BaseAgent.key` / `__init__` — `har_reproducer/agents/base_agent.py:20-51`

```python
    def __init__(
            self,
            token_id: str,
            response_sample: Dict[str, Any],
            expected_value: str,
            workspace: Workspace,
            script_executor: ScriptExecutor,
            sleeper: Sleeper,
            path: Optional[str] = None,
            location: Optional[str] = None,
            llm: Optional[BaseChatModel] = None,
    ) -> None:
        ...

    @property
    def key(self) -> Optional[str]:
        if self.path is None:
            return None
        if ":" in self.path:
            return self.path.split(":", 1)[1]
        return self.path
```

`key` é a chave **de destino**, derivada de `candidate.path` (formato
`"header:If-None-Match"`, produzido por `BaselineDiff._build_candidate`). É usada por
`HeaderAgent._by_name`/`_header_value`, `CookieAgent._by_name`/`_context_pattern` e
`RegexAgent._key_pattern` — todos aplicando essa chave **sobre a resposta de origem**,
que é onde a suposição quebra.

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
combinação **classe preguiçosa + lookahead do caractere real que segue o valor** —
justamente porque um quantificador guloso sem âncora de fim consome o delimitador
quando ele pertence à classe de caracteres do valor.

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

**Não** recebeu o tratamento acima: usa `value_char_class()` (gulosa) e não ancora o
fim. Consequência: para todo valor cujo caractere seguinte no body pertence à classe
(`[\w\-.]`), o grupo consome além do valor e a verificação falha; e para todo valor
que contenha caractere fora de `[\w\-.]` (qualquer `/`, típico de caminho e URL),
`value_char_class()` devolve `.+?` — que, **sem âncora de fim**, casa exatamente
**um** caractere e falha sempre.

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

    def __init__(self, step_index_width: int) -> None: ...
    def format_dependency_line(self, token_id, origin_step, origin_status=None) -> str: ...
    def with_replay_status(self, line, phrase) -> str: ...
    def parse(self, curl_text: str) -> Dict[str, int]: ...
```

Formato consolidado na etapa de 12/08 (`docs/20260812 Correção da Anotação de Token
Estático que Quebra o Parser de Dependências`): a **cláusula** vive entre colchetes e
o `DEPENDENCY_PATTERN` ancora só nela; qualquer status extra vai **depois** do `]`,
separado por `"; "`. É esse contrato que impede uma anotação de replay de quebrar o
parser de dependências, e ele **não pode ser afrouxado** por esta spec.

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

Token sem `origin_step` (todo candidato `NotFound`) é **silenciosamente ignorado** —
não deixa rastro nenhum no `.curl.sh`. É essa ausência de rastro que faz `optimize`
reportar `SUCCESSFUL` sobre um schedule cheio de literais congelados sem nenhum aviso
(relatório, seções 3.1, 3.4 e conclusão itens 2 e 4).

### `ScheduleExecutor` — `har_reproducer/contracts/schedule_executor.py` (arquivo inteiro)

```python
class ScheduleExecutor(Protocol):
    def execute_schedule(self, ordered_indexes, schedule, annotate=True) -> List[Tuple[int, StepResponse]]: ...
    def compute_smart_schedule(self, from_index, to_index) -> Tuple[List[int], Set[int]]: ...
    def existing_step_indexes(self) -> List[int]: ...
```

Contrato entre `ReplayOptimizer` e `ReplayRunner`. `ReplayOptimizer` não tem acesso ao
`Workspace` para ler `.curl.sh` — tudo que ele sabe do workspace passa por aqui
(exceto o `workspace` recebido em `optimize()`, usado só para o caminho de saída).

### `EngineFactory.create`/`_build_tracker` — `har_reproducer/engines/construction/engine_factory.py:51-96`

```python
        tracking_responses_dir: Path = (
            self.workspace.real_responses if engine_cls.USES_NETWORK else self.workspace.original_responses
        )
        ...
        candidate_resolver: CandidateResolver = CandidateResolver(
            tracking_responses_dir, session_store, extractor_runner, metadata_store, agent_factory
        )
```

Raiz de composição do ramo `run` (a outra é `CliHandlers._build_replay_runner`, do
ramo `replay`/`optimize`). É o único lugar que pode instanciar os colaboradores novos.

### `HARParser.parse_entry` — `har_reproducer/fs_io/har_parser.py:64-82`

```python
        res_content: Dict[str, Any] = res_data.get("content", {})
        text: Optional[str] = res_content.get("text")
        encoding: Optional[str] = res_content.get("encoding")

        body: str = HARParser.decode_body(text or "", encoding)
```

Quando o HAR não gravou o corpo da resposta (`content` sem a chave `text`, típico de
export do DevTools com `size: -1`), `body` vira `""` **sem nenhum aviso**. Medido no
`progressofit.har`: **140 de 238** entries nessa situação — incluindo a entry `154`
(`POST /auth/login`), que é exatamente a origem do JWT discutido no relatório. O
README declara HAR completo (com body de toda requisição) como pré-condição do
projeto; hoje a violação dessa pré-condição é invisível.

## 3. Decisões de arquitetura

### 3.1 — `ValueVariants`: extrair as variantes de encoding para uma classe própria

**Estado atual:** `ResponseGrep.value_variants`/`try_decode`/`_deduplicate` são
métodos de `ResponseGrep`, e `TokenLocationDetector` depende deles a partir de fora
(`ResponseGrep.value_variants(value)`).

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
Motivo: `ResponseGrep` deixa de ser classe de utilidade sem estado nesta spec
(decisão 3.3) e passa a receber colaborador por construtor; manter dentro dela um
utilitário que outra classe consome estaticamente misturaria os dois papéis. É o
mesmo movimento que a spec de 04/08 fez ao promover `_value_char_class` para
`BaseAgent.value_char_class` — nenhuma classe deveria depender de método
`_`-prefixado (nem de utilitário embutido) de outra.

⚠️ Comportamento **idêntico**: a ordem das variantes (`cru`, `decodificado`,
`URL-encode`, `base64-encode`) é significativa (a primeira que casar vence) e não
pode ser alterada.

### 3.2 — `ResponseCorpus`: corpus estruturado de respostas

**Estado atual:** não existe. A leitura de respostas está espalhada em
`ResponseGrep._eligible_response_files` (lista arquivos por glob) e
`CandidateResolver._load_response` (lê o mesmo arquivo de novo como `Dict`).

**Estado esperado:** arquivo novo `har_reproducer/tracking/response_corpus.py`:

```python
class ResponseCorpus:

    def __init__(self, responses_dir: Path, step_index_width: int) -> None:
        self.responses_dir: Path = responses_dir
        self.step_index_width: int = step_index_width

    def eligible_indexes(self, before_step_index: int) -> List[int]:
        indexes: List[int] = []
        for path in sorted(self.responses_dir.glob("res_*.json")):
            step_index: Optional[int] = self._extract_step_index(path.name)
            if step_index is not None and step_index < before_step_index:
                indexes.append(step_index)
        return indexes

    def response(self, step_index: int) -> Optional[Dict[str, Any]]:
        # o que CandidateResolver._load_response faz hoje, com o mesmo tratamento de erro

    def searchable_text(self, step_index: int) -> Optional[str]:
        response: Optional[Dict[str, Any]] = self.response(step_index)
        if response is None:
            return None
        return self._serialize(response)

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

    @staticmethod
    def _decode_body(body: Union[str, bytes]) -> str:
        return body if isinstance(body, str) else body.decode("utf-8", errors="replace")

    @staticmethod
    def _extract_step_index(filename: str) -> Optional[int]:
        # corpo idêntico ao ResponseGrep._extract_step_index atual
```

Notas de projeto:

- O `searchable_text` é o **conteúdo real** da resposta: nada escapado. É isso que
  fecha a Falha A.
- A ordem (`headers`, `cookies`, `redirect_url`, `body`) é fixa e faz parte do
  contrato — a decisão 3.3 depende de o body vir por último para poder decidir *onde*
  o valor casou sem reparsear.
- `response()` devolve o `Dict` cru do JSON (não `StepResponse`), porque é esse
  dicionário que vira `response_sample` para `TokenLocationDetector` e para o `Agent`,
  e é ele que `ExtractorTemplate.render_temp_script` embute no script de verificação.
  Trocar por `StepResponse` mudaria o formato do `response_sample` e propagaria por
  todos os agentes — fora de escopo.
- ⚠️ **Não** manter cache em atributo de instância nesta etapa. `CandidateResolver`
  já tem o seu (`_origin_cache`, `_validated_values`) e a medição de custo com leitura
  direta é de menos de 1 s para os 269 candidatos deste workspace. Cache aqui só
  adicionaria estado sem ganho medido.

### 3.3 — `ResponseGrep`: busca sobre o corpus, sem `subprocess`, devolvendo `OriginMatch`

**Estado atual:** ver seção 2 — `@classmethod` recebendo `responses_dir: Path`,
`subprocess.run(["grep", "-lF", ...])`, retorno `Tuple[int, str]` com um `filename`
que ninguém usa.

**Estado esperado:**

```python
class ResponseGrep:

    def __init__(self, corpus: ResponseCorpus) -> None:
        self.corpus: ResponseCorpus = corpus

    def find(self, value: str, before_step_index: int) -> Optional[OriginMatch]:
        eligible: List[int] = self.corpus.eligible_indexes(before_step_index)
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
            return OriginMatch(step_index=step_index, origin_key=self._origin_key(step_index, variant, is_raw))
        return None

    def _origin_key(self, step_index: int, variant: str, is_raw: bool) -> Optional[str]:
        if not is_raw:
            return None
        response: Optional[Dict[str, Any]] = self.corpus.response(step_index)
        if response is None:
            return None
        return self._exact_key(response.get("headers"), variant) or self._exact_key(response.get("cookies"), variant)

    @staticmethod
    def _exact_key(container: Optional[Dict[str, str]], variant: str) -> Optional[str]:
        for name, value in (container or {}).items():
            if value == variant:
                return name
        return None
```

⚠️ Pontos que **preservam o comportamento observável atual** e não podem mudar:

- **Ordem de varredura por índice crescente.** Hoje o desempate é
  `sorted(result.stdout.splitlines())[0]` — o menor nome de arquivo entre os que
  casaram, que corresponde ao menor índice. `eligible_indexes` já devolve ordenado;
  o `for` para no primeiro. Mesmo resultado, sem `sorted` sobre saída de subprocess.
- **Ordem das variantes** manda sobre a ordem dos steps: hoje `find` esgota todos os
  arquivos com a variante 1 antes de tentar a variante 2, e `_find_variant` mantém
  exatamente isso.
- **Restrição de causalidade temporal** (`step_index < before_step_index`) — é o que
  garante que uma origem nunca seja uma resposta futura, e mora agora em
  `ResponseCorpus.eligible_indexes`.

Mudanças deliberadas:

- Sai `subprocess`/`grep`. Não é ganho de performance (medido: <1 s), é remoção de uma
  borda de I/O externa e do `except subprocess.CalledProcessError` associado.
- O `filename` do retorno some (ninguém lia).

### 3.4 — `OriginMatch` e a regra do `origin_key`

**Estado atual:** não existe; a origem é um `Tuple[int, str]`.

**Estado esperado:** novo model em `har_reproducer/models/analysis.py`:

```python
class OriginMatch(BaseModel):
    step_index: int
    origin_key: Optional[str] = None
```

**Regra do `origin_key` (é a decisão, não o tipo):** só é preenchido quando as **duas**
condições valem:

1. o casamento ocorreu com a **variante crua** (o próprio `current_value`, não uma
   variante URL/base64), e
2. existe um header **ou** cookie da resposta de origem cujo valor é **exatamente
   igual** ao valor procurado.

Precedência: headers antes de cookies; dentro de cada um, a primeira chave na ordem de
iteração do dicionário. Nos demais casos (casamento no body, no `redirect_url`, por
variante transformada, ou só como substring de um header) `origin_key` fica `None` e
tudo se comporta exatamente como hoje.

Razão de cada condição:

- **(1) variante crua** — o `Agent` é verificado contra `expected_value =
  candidate.current_value`. Se o casamento foi por uma variante transformada, o valor
  do header é a variante, e um extrator que devolva o valor daquele header devolveria
  algo diferente do esperado. Prometer uma chave que não reproduz o valor esperado só
  gastaria tentativa.
- **(2) igualdade exata** — casamento por substring é o cenário `Sec-Fetch-Site` ×
  `Cross-Origin-Opener-Policy` da spec de 04/08. Hoje ele falha de forma inofensiva;
  com `origin_key` por substring, `HeaderAgent._context_pattern` passaria a **ter
  sucesso** sobre um header sem relação causal, produzindo extrator verificado e
  errado. Casamento parcial com evidência é assunto da spec seguinte, não desta.

### 3.5 — `DynamicToken.origin_key`

**Estado atual** (`models/session.py:46-54`): sem esse campo.

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
    status: Literal["UnderReview", "NotFound", "Unresolved", "Resolved"]
    extraction_exhausted: bool = False
```

⚠️ **Não** adicionar o campo espelho em `Extractor`. `origin_key` só é consumido no
instante em que o `Agent` é construído (cache-miss); num cache-hit nenhum agente é
criado. Persistir sem consumidor seria campo morto em 114 arquivos de `extractors/`.
A spec seguinte, que precisa repopular campos no caminho de cache-hit
(bug §3.2 do relatório), decide isso com um consumidor real na mão.

### 3.6 — `CandidateResolver`: passa a receber o corpus e o `ResponseGrep` já montado

**Estado atual:** ver seção 2 — recebe `responses_dir: Path`, chama
`ResponseGrep.find` estaticamente e relê o arquivo em `_load_response`.

**Estado esperado:**

```python
    def __init__(
            self,
            response_corpus: ResponseCorpus,
            response_grep: ResponseGrep,
            session_store: SessionStore,
            extractor_runner: ExtractorRunner,
            metadata_store: ExtractorMetadataStore,
            agent_factory: AgentFactory,
    ) -> None:
        self.response_corpus: ResponseCorpus = response_corpus
        self.response_grep: ResponseGrep = response_grep
        ...
        self._origin_cache: Dict[str, OriginMatch] = {}

    def _process_candidate(self, candidate: DynamicToken, step_index: int) -> DynamicToken:
        origin: Optional[OriginMatch] = self._find_origin(candidate.current_value, step_index)
        if origin is None:
            candidate.status = "NotFound"
            return candidate

        candidate.origin_step = origin.step_index
        candidate.origin_key = origin.origin_key
        base_token_id: str = self._derive_token_id(candidate.path, candidate.origin_step)
        ...

    def _find_origin(self, value: str, step_index: int) -> Optional[OriginMatch]:
        cached_origin: Optional[OriginMatch] = self._origin_cache.get(value)
        if cached_origin is not None:
            return cached_origin
        origin: Optional[OriginMatch] = self.response_grep.find(value, step_index)
        if origin is not None:
            self._origin_cache[value] = origin
        return origin
```

`_load_response` é **removido**; `_generate_new_extractor` passa a chamar
`self.response_corpus.response(candidate.origin_step)`.

⚠️ `self.responses_dir` some do `CandidateResolver`, mas `ExtractorRunner.run_existing`
continua recebendo um `Path` em `_check_persisted_slot`
(`candidate_resolver.py:108`) — esse `Path` passa a vir de
`self.response_corpus.responses_dir`. Não trocar a assinatura de `ExtractorRunner`.

⚠️ O cache `_origin_cache` é chaveado só pelo valor, **sem** o `step_index` — é
comportamento atual e conhecido (`docs/20260805 Regressão de Cache de Origem no
CandidateResolver`). Não alterar aqui.

### 3.7 — `BaseAgent.origin_key` e a precedência em `key`

**Estado atual:** ver seção 2 — `key` deriva sempre de `path` (destino).

**Estado esperado:**

```python
    def __init__(
            self,
            token_id: str,
            response_sample: Dict[str, Any],
            expected_value: str,
            workspace: Workspace,
            script_executor: ScriptExecutor,
            sleeper: Sleeper,
            path: Optional[str] = None,
            location: Optional[str] = None,
            origin_key: Optional[str] = None,
            llm: Optional[BaseChatModel] = None,
    ) -> None:
        ...
        self.origin_key: Optional[str] = origin_key
        ...

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

E `AgentFactory.create` passa `origin_key=candidate.origin_key`.

⚠️ `origin_key` entra **antes** de `llm` na lista de parâmetros, para manter `llm`
como último (é assim que os call sites atuais o passam nomeado, mas a convenção do
arquivo é essa). Todos os call sites usam argumentos nomeados —
`AgentFactory.create` e os testes — então a posição não quebra nada, mas manter a
convenção evita ruído no diff.

⚠️ Isso muda o comportamento de **três** agentes de uma vez (`HeaderAgent`,
`CookieAgent`, `RegexAgent._key_pattern`) para todo candidato que tenha `origin_key`.
Para `HeaderAgent`/`CookieAgent` é o objetivo. Para `RegexAgent._key_pattern` o efeito
é colateral e desejável: passa a procurar no body pela chave **da origem**
(`ETag['\"]?\s*[:=]...`) em vez de pela chave de destino — mais correto pelo mesmo
argumento. Nenhum dos três muda uma linha de código próprio.

### 3.8 — `RegexAgent._context_pattern`: âncora de fim e classe preguiçosa

**Estado atual:** ver seção 2 — grupo guloso, sem fronteira de fim.

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

Mesma forma exata de `HeaderAgent._context_pattern`/`CookieAgent._context_pattern`
(spec de 04/08, decisão 3.2): classe preguiçosa + lookahead do caractere real que
segue o valor na resposta de origem, ou `$` quando o valor vai até o fim. Não embute o
valor no regex — só a fronteira estrutural que o segue —, então continua funcionando
se o valor mudar entre replays.

⚠️ `_key_pattern` **não muda** (continua com `value_char_class()` guloso e sem
âncora): lá o grupo já é delimitado pelo contexto `chave: valor` à esquerda, e mexer
nele é mudança de comportamento sem defeito observado que a justifique.

⚠️ Esta decisão **pode alterar o código de extratores já persistidos** quando o
`RegexAgent` for reexecutado, e portanto altera o golden. O valor extraído não muda
(o `run_tdd_loop` só aceita código que devolve exatamente `expected_value`); o que
muda é qual estratégia consegue verificar primeiro e o texto do regex gerado.

### 3.9 — `CurlTokenComment`/`CurlGenerator`: linha de auditoria para valores sem origem

**Estado atual:** candidato `NotFound` não deixa rastro nenhum no `.curl.sh`.

**Estado esperado:** nova frase e novo formato de cláusula em `CurlTokenComment`:

```python
class UnresolvedOriginPhrase(str, Enum):
    NO_RECORDED_ORIGIN = "no recorded origin — value kept literal from HAR"


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

E `CurlGenerator._token_comments` passa a emitir **uma** linha consolidada, depois das
linhas de dependência, quando houver candidato sem origem:

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

Decisões de forma:

- **Uma linha consolidada por step**, não uma por candidato. Medido: 215 dos 269
  candidatos distintos deste workspace são `NotFound`, a maioria header de contexto de
  navegador (`Accept`, `Sec-Fetch-*`, `priority`). Uma linha por candidato encheria
  todo `.curl.sh` e o golden de ruído.
- O texto lista os **paths** (`header:Accept`, `url`, ...), não os valores — é o que
  identifica *o que* ficou congelado sem vazar credencial para dentro do arquivo.
- A cláusula usa a mesma convenção de colchetes da etapa de 12/08, e
  `UNRESOLVED_PATTERN` **não** casa `DEPENDENCY_PATTERN` nem vice-versa (a palavra
  após `[` difere: `Unresolved` × `Token`). Nenhuma anotação de replay é anexada a
  essa linha.
- `UnresolvedOriginPhrase` fica declarada para uso do relatório da decisão 3.10 —
  não entra na linha do curl (que já é autoexplicativa pelo path).

### 3.10 — Relatório agregado de valores sem origem em `replay` e `optimize`

**Estado atual:** `ReplayRunner._run_schedule` imprime o relatório por step e o
veredito; `ReplayOptimizer.optimize` imprime só a estimativa e o resultado. Nenhum dos
dois sabe quantos literais congelados o schedule carrega.

**Estado esperado:**

1. `ScheduleExecutor` (Protocol) ganha:

```python
    def unresolved_origins(self, indexes: List[int]) -> Dict[int, List[str]]: ...
```

2. `ReplayRunner` implementa lendo os `.curl.sh` dos índices e aplicando
   `CurlTokenComment.parse_unresolved`:

```python
    def unresolved_origins(self, indexes: List[int]) -> Dict[int, List[str]]:
        found: Dict[int, List[str]] = {}
        for index in indexes:
            paths: List[str] = self.curl_token_comment.parse_unresolved(
                self.workspace.curl_file(index).read_text(encoding="utf-8")
            )
            if paths:
                found[index] = paths
        return found
```

3. `ReplayRunner._run_schedule` imprime o aviso antes do veredito, e
   `ReplayOptimizer.optimize` imprime sobre a `final_list` antes de escrever o
   arquivo. Formato único, num método próprio para não duplicar:

```
WARNING: o schedule carrega 47 valor(es) sem origem gravada em 12 step(s)
  (steps 0, 1, 14, 23, ...) — literais congelados do HAR. O resultado pode deixar de
  funcionar quando esses valores expirarem, sem que este comando avise.
```

⚠️ É **aviso**, não falha: o comando continua e o veredito de sucesso/fracasso não
muda. Recusar o schedule foi considerado e descartado — quebraria o uso atual deste
workspace, onde o próprio `Authorization` cai nessa classe.

⚠️ `.curl.sh` gerado por um `run` anterior a esta spec não tem a linha —
`parse_unresolved` devolve `[]` e o aviso não aparece. Workspace antigo continua
funcionando, só não ganha o relatório até o próximo `run`.

### 3.11 — Aviso de entries do HAR sem corpo de resposta gravado

**Estado atual:** `HARParser.parse_entry` transforma `content` sem `text` em
`body=""` silenciosamente.

**Estado esperado:** `Engine._reproduce` (e, por herança, `DryEngine`) conta as
entries cujo `step.response.body` ficou vazio **e** cujo `status_code` normalmente
carregaria corpo, e imprime uma vez, ao final:

```
WARNING: 140 de 238 entries do HAR não têm corpo de resposta gravado. Origens de
token que estejam nesses corpos são indescobríveis — regrave o HAR preservando o
conteúdo das respostas ("Preserve log" + export completo).
```

⚠️ A contagem é sobre o `StepResponse` já parseado (não sobre o JSON cru do HAR), e
não filtra por código de status: um `204`/`304` legitimamente sem corpo entra na
contagem. Filtrar por status seria embutir conhecimento de protocolo — o aviso é
informativo e o número serve para o usuário julgar. ⚠️ **Não** transformar em erro
nem alterar o retorno de `run()`.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `tracking/value_variants.py` (**novo**) | `ValueVariants` — `of`/`try_decode`/`_deduplicate` movidos de `ResponseGrep`, comportamento idêntico |
| `tracking/response_corpus.py` (**novo**) | `ResponseCorpus` — `eligible_indexes`/`response`/`searchable_text`; serialização estruturada da resposta |
| `models/analysis.py` | Novo model `OriginMatch(step_index, origin_key)` |
| `models/session.py` | `DynamicToken` ganha `origin_key: Optional[str] = None` |
| `tracking/response_grep.py` | `ResponseGrep` vira classe de instância sobre `ResponseCorpus`; sem `subprocess`; devolve `OriginMatch`; aplica a regra do `origin_key` |
| `tracking/token_location_detector.py` | `_value_present` passa a usar `ValueVariants.of` |
| `tracking/candidate_resolver.py` | Recebe `ResponseCorpus` + `ResponseGrep` por construtor; `_load_response` removido; grava `candidate.origin_key`; `_origin_cache` passa a `Dict[str, OriginMatch]` |
| `engines/construction/engine_factory.py` | Raiz de composição monta `ResponseCorpus` e `ResponseGrep` e injeta no `CandidateResolver` |
| `agents/base_agent.py` | Novo parâmetro/atributo `origin_key`; `key` passa a preferi-lo ao derivado de `path` |
| `agents/construction/agent_factory.py` | Passa `origin_key=candidate.origin_key` |
| `agents/regex_agent.py` | `_context_pattern` ganha classe preguiçosa + lookahead de fim (paridade com `HeaderAgent`) |
| `replay/curl_token_comment.py` | `UnresolvedOriginPhrase`, `UNRESOLVED_PATTERN`, `format_unresolved_line`, `parse_unresolved` |
| `reproduction/curl_generator.py` | `_token_comments` emite a linha consolidada de valores sem origem |
| `contracts/schedule_executor.py` | Novo método `unresolved_origins` no Protocol |
| `replay/replay_runner.py` | Implementa `unresolved_origins`; `_run_schedule` imprime o aviso agregado |
| `optimization/replay_optimizer.py` | Imprime o aviso agregado sobre a `final_list` antes de escrever o arquivo |
| `engines/engine.py` | Aviso de entries do HAR sem corpo de resposta gravado |

## 5. Casos de borda e comportamento de erro

- **Resposta ilegível ou ausente** (`res_NNNN.json` corrompido) —
  `ResponseCorpus.response` mantém o `except Exception` + `print` de aviso + retorno
  `None` que `CandidateResolver._load_response` já tinha (borda de I/O, guia de
  estilo). `searchable_text` devolve `None` e `_find_variant` pula o step.
- **Resposta sem nenhum campo** (headers vazios, body vazio) — `searchable_text`
  devolve `""`; `variant not in ""` é falso para variante não-vazia e o step é pulado.
  ⚠️ `ValueVariants._deduplicate` já descarta valor vazio, então `variant` nunca é `""`.
- **Valor que casa em mais de uma resposta elegível** — vence o **menor índice**, como
  hoje. Não muda nesta spec. (Casamento por fragmento, onde a ambiguidade fica
  frequente, é da spec seguinte, e lá a regra decidida é "maior evidência, desempate
  pelo step mais recente".)
- **Valor que casa em duas chaves da mesma resposta com o mesmo valor exato** —
  `origin_key` recebe a primeira na ordem de iteração (headers antes de cookies).
  Ambas extraem o mesmo valor, então a escolha não altera o resultado.
- **`origin_key` aponta para header que some numa execução futura** — o extrator
  gerado falha no replay e cai no `captured_value` via
  `ReplayTokenResolver._fallback_to_captured`, mecanismo inalterado.
- **Casamento no `body` com `origin_key = None`** — comportamento idêntico ao de hoje
  em todos os agentes (a chave continua vindo de `path`). Nenhum dos 63 ganhos
  medidos depende disso.
- **Candidato cujo valor casa por variante base64/URL** — `origin_key` fica `None` por
  construção (decisão 3.4, condição 1). O agente segue o caminho atual.
- **Workspace com `.curl.sh` de rodada anterior** — `Workspace` nunca limpa nada entre
  execuções ([[arquitetura-e-fundamentos]]); um curl antigo sem a linha `[Unresolved]`
  simplesmente não contribui para o aviso. Não é erro.
- **`RegexAgent` cujo `expected_value` termina exatamente no fim do body** —
  `end == len(body)`, `boundary = "$"`, igual ao caminho já exercitado por
  `HeaderAgent`.
- **`--mode dry`** — todo o desenho vale igual, com o corpus apontando para
  `original_responses`. Neste HAR o ganho de 63 ETags **também acontece** em dry (os
  ETags estão nos headers, que o HAR grava); o `Authorization` continua indescobrível
  por falta de corpo gravado, e passa a ser reportado pelo aviso da decisão 3.11.

## 6. Suposições e pontos a confirmar

- Nome das classes novas (`ValueVariants`, `ResponseCorpus`, `OriginMatch`) e do campo
  `DynamicToken.origin_key` — sujeitos a ajuste de nomenclatura.
- Texto exato dos dois avisos (3.10 e 3.11) e do formato da linha `[Unresolved N]` —
  sujeitos a ajuste de wording. O que **não** é ajustável é a garantia de que
  `UNRESOLVED_PATTERN` e `DEPENDENCY_PATTERN` não se casem cruzado.
- `ResponseCorpus.__init__` recebe `step_index_width` — confirmado durante o
  planejamento que o parâmetro é necessário: `response(step_index)` monta o nome do
  arquivo (`res_{step_index:0{width}d}.json`), do mesmo modo que
  `Workspace.response_file`. A raiz de composição passa `Workspace.STEP_INDEX_WIDTH`.
- **Decidido nesta conversa, registrado para a spec seguinte** (não implementar aqui):
  casamento por fragmento com âncora expandida; classificação da aresta em
  proveniência × necessidade comparando as duas épocas (`original_responses` ×
  `real_responses`), com proveniência **nunca** virando âncora de
  `compute_smart_schedule`; desempate de ambiguidade por maior fragmento e, em caso de
  empate, pelo step mais recente; promoção proveniência → necessidade quando o replay
  observa divergência do `captured_value`; write-back de demoção a partir da fase 2 do
  `optimize`. Ficaram **descartados** com motivo: minimizar o número de extratores
  reconstruindo o valor por muitos fragmentos (a evidência de cada fragmento cai
  exponencialmente com o tamanho, e a reconstrução costura o literal obsoleto);
  invalidar extrator porque o literal "ainda funciona" (lógica invertida — descartaria
  a dependência verdadeira); gate de LLM antes de criar extrator (LLM é opcional no
  pipeline e a ordem "determinístico antes de LLM" é princípio do projeto).

## Referência

Toda alteração de código desta spec segue o padrão descrito em [[guia-de-estilo]]
(`.claude/skills/guia-de-estilo`), e as decisões respeitam o princípio de genericidade
descrito em [[arquitetura-e-fundamentos]] (`.claude/skills/arquitetura-e-fundamentos`):
nenhum header, formato de token ou convenção de protocolo é hardcoded — `ETag` não é
conhecido pelo código, é **descoberto** como a chave onde o valor procurado mora.
