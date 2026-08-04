# Spec — Extração por Substring e Fallback de Exaustão

## 1. Objetivo

A spec anterior (`docs/20260803 Origem de Token Não Determinada`) resolveu o caso em
que o `ResponseGrep` acha uma origem, mas o `TokenLocationDetector` não consegue
determinar em qual parte da response o valor está — nesse caso, `origin_location`
vira `None` e o `CandidateResolver` gera direto um extractor literal, sem acionar
nenhum `Agent`/LLM.

Rodando o pipeline (`uv run python -m har_reproducer.main run --har
progressofit.har`) depois dessa correção, apareceu um caso adjacente, ainda não
coberto: o candidato ao header de requisição `Sec-Fetch-Site` (valor `same-origin`)
teve origem **erroneamente confirmada** no header de response
`Cross-Origin-Opener-Policy: same-origin-allow-popups` de uma response de fonte do
Google — porque `"same-origin"` é, de fato, uma substring literal de
`"same-origin-allow-popups"`. Isso não é falso-positivo de regex (já corrigido pela
spec anterior); é uma colisão de substring genuína entre dois campos HTTP
semanticamente não relacionados.

Como `TokenLocationDetector.find` encontra essa substring dentro de um header,
`origin_location` fica `HEADER` (não `None`) — então o candidato **não** cai no
atalho do extractor literal. Ele vai para o `HeaderAgent` de verdade, que:
1. Tenta a estratégia determinística `_by_name` — falha, porque a response de
   origem não tem nenhum header chamado literalmente `Sec-Fetch-Site` (é um header
   de **requisição**, a response não o replica).
2. Esgota as 5 tentativas via LLM — falha todas, porque o valor genuinamente não
   está extraível daquela response da forma que o `HeaderAgent`/LLM sabem procurar.

O log observado:
```
Attempt 1 failed for 9dd730ba1423e0af5846044dffbddf8e. Retrying...
...
Attempt 6 failed for 9dd730ba1423e0af5846044dffbddf8e. Retrying...
Step 15 completed with status 200
Attempt 1 failed for 9dd730ba1423e0af5846044dffbddf8e. Retrying...
...
```
O candidato termina `Unresolved`. Como `_register_extractor` só cacheia quando o
`Agent` retorna um `Extractor` (`candidate_resolver.py:103-115`), **nada é
persistido** — e como esse mesmo `token_id` reaparece a cada step subsequente que
usa o mesmo header (steps 15 a 19 no log), o pipeline refaz a mesma tentativa
fadada ao fracasso, do zero, em cada ocorrência.

**O que essa mudança cobre:**
- Dar ao `HeaderAgent`/`CookieAgent` uma estratégia determinística de extração por
  substring **na própria chave de destino** (`self.key`) — para o cenário legítimo
  em que o token realmente é uma substring de um header/cookie real (ex.: um ID de
  sessão embutido num cookie composto), sem depender só do LLM acertar por sorte, e
  sem abrir margem para casar com uma chave **diferente e não relacionada** (que é
  o que causou o problema do `Sec-Fetch-Site`).
- Quando, mesmo assim, nenhuma estratégia (determinística ou via LLM) consegue
  produzir um extractor que verifique (`run_tdd_loop` retorna `None`), o
  `CandidateResolver` para de tentar do zero a cada nova ocorrência do mesmo
  candidato: gera um extractor literal (mesmo mecanismo da spec anterior),
  cacheado normalmente via `ExtractorMetadataStore`, com um `AgentType` e um
  comentário no curl **distintos** do caso "origem não determinada" — porque a
  causa é diferente (aqui a origem foi confirmada, só não deu pra extrair de
  verdade) e isso precisa continuar auditável.

**Fora de escopo (não implementar agora — discutido e decidido explicitamente):**
- **`BaselineDiff._diff_headers`** (`baseline_diff.py:23-29`) tratar qualquer header
  que difira do baseline fixo (step 0) como candidato dinâmico, mesmo quando a
  diferença é variação normal por contexto de requisição (`Accept`, `Sec-Fetch-*`,
  etc.) — é a causa mais profunda por trás tanto do `Accept: */*` da spec anterior
  quanto do `Sec-Fetch-Site` desta. Decidido deixar de fora porque **não existe
  solução fechada e universalmente correta** para esse problema: distinguir "header
  varia por contexto de navegador" de "header é um token real" depende de
  semântica que não está no dado (nenhuma allowlist de headers cobre customizações
  de aplicação, e nenhum site é obrigado a seguir convenção nenhuma). Os itens desta
  spec (3.1–3.7) garantem que, mesmo sem essa correção, o pior caso continua sendo
  seguro e de custo limitado — então essa causa raiz fica como melhoria futura,
  não bloqueante.
- **Detecção mais rigorosa em `ResponseGrep`/`TokenLocationDetector`** (ex.: exigir
  fronteira de palavra em vez de substring crua) — descartada porque o mesmo
  helper (`_value_present`) é compartilhado com a checagem de `body`, onde
  substring sem fronteira é um caso legítimo e já em produção (o
  `RegexAgent._context_pattern` existe exatamente para isso). Apertar a checagem
  quebraria esse caso legítimo para ganhar proteção parcial contra um caso mais raro.
- **Remover/substituir extractors marcados "probably static"** no replay
  (`ReplayRunner.STATIC_WARNING_SUFFIX`) — hoje esse mecanismo só anota (sufixo de
  comentário + contadores em `.meta.json`), nunca desativa ou troca o extractor de
  verdade por um literal. Confirmado que não há plano de implementação para isso
  ainda; fica para um segundo momento, separado desta spec.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `HeaderAgent` — `har_reproducer/agents/header_agent.py` (arquivo inteiro)
```python
class HeaderAgent(BaseAgent):

    def deterministic_strategies(self) -> List[Strategy]:
        return [self._by_name]

    def _by_name(self, last_error: Optional[str] = None) -> Optional[str]:
        key: Optional[str] = self.key
        if not key:
            return None
        return f"""
def extract_{self.safe_token_id}(response: dict) -> str:
    headers = response.get('headers', {{}})
    target = {key!r}
    value = headers.get(target)
    if value is None:
        lowered = {{str(k).lower(): v for k, v in headers.items()}}
        value = lowered.get(target.lower())
    if not value:
        raise Exception("Token not found in headers")
    return value
"""
```
Única estratégia determinística: busca o header pela chave exata (`self.key`, vindo
de `candidate.path` tipo `"header:Sec-Fetch-Site"`), com fallback case-insensitive.
Devolve o valor **inteiro** do header. Se `expected_value` for só uma parte desse
valor, essa estratégia falha e cai direto pra tentativa via LLM — sem nenhuma
tentativa determinística de "essa chave contém o valor como substring".

### `CookieAgent` — `har_reproducer/agents/cookie_agent.py` (arquivo inteiro)
```python
class CookieAgent(BaseAgent):

    def deterministic_strategies(self) -> List[Strategy]:
        return [self._by_name]

    def _by_name(self, last_error: Optional[str] = None) -> Optional[str]:
        key: Optional[str] = self.key
        if not key:
            return None
        return f"""
def extract_{self.safe_token_id}(response: dict) -> str:
    cookies = response.get('cookies', {{}})
    value = cookies.get({key!r})
    if not value:
        raise Exception("Token not found in cookies")
    return value
"""
```
Mesmo formato do `HeaderAgent`, sem o fallback case-insensitive (cookies não têm
essa ambiguidade). Mesma limitação: só valor inteiro, sem estratégia de substring.

### `RegexAgent._context_pattern`/`_value_char_class` — `har_reproducer/agents/regex_agent.py`
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
    return rf"{re.escape(prefix)}({self._value_char_class()})"

def _value_char_class(self) -> str:
    if re.fullmatch(r"[\w\-.]+", self.expected_value):
        return r"[\w\-.]+"
    return r".+?"
```
Este é o precedente direto da decisão 3.1/3.2: localiza onde `expected_value`
aparece dentro de um texto maior (`body`), usa o texto **antes** da ocorrência como
âncora, e monta um regex que extrai o grupo correspondente — sem embutir o valor
literal no regex, então continua funcionando se o valor mudar entre replays,
contanto que a âncora (contexto) se mantenha. `_value_char_class` decide a classe
de caracteres do grupo de captura (`\w\-.` para valores "normais", `.+?` não-guloso
para valores com caracteres incomuns). Ambos são usados só dentro de
`RegexAgent` hoje — a decisão 3.1 promove `_value_char_class` pra
`BaseAgent`, no mesmo padrão que `T01`/`T02` da spec anterior já fizeram com
`ResponseGrep._build_pattern_variants`/`BaseAgent._sanitize_identifier`.

### `BaseAgent` — `har_reproducer/agents/base_agent.py:19-63`
```python
class BaseAgent:
    MAX_LLM_ATTEMPTS: int = 5

    def __init__(self, token_id, response_sample, expected_value, path=None, location=None, llm=None) -> None:
        self.token_id: str = token_id
        self.safe_token_id: str = self.sanitize_identifier(token_id)
        self.response_sample: Dict[str, Any] = response_sample
        self.expected_value: str = expected_value
        self.path: Optional[str] = path
        ...

    @staticmethod
    def sanitize_identifier(raw: str) -> str: ...

    @property
    def key(self) -> Optional[str]:
        if self.path is None:
            return None
        if ":" in self.path:
            return self.path.split(":", 1)[1]
        return self.path

    def deterministic_strategies(self) -> List[Strategy]:
        return []

    def _build_strategies(self) -> List[Strategy]:
        deterministic: List[Strategy] = self.deterministic_strategies()
        llm_attempts: List[Strategy] = [self._llm_strategy] * self.MAX_LLM_ATTEMPTS
        return deterministic + llm_attempts

    def run_tdd_loop(self, max_attempts=None, origin_step=None, initial_error=None) -> Optional[Extractor]:
        strategies: List[Strategy] = self._get_strategies()
        ...
        for attempt in range(total):
            code: Optional[str] = self.generate_code(last_error=last_error)
            if code is None:
                break
            success, error = self._verify_code(code)
            if success:
                return Extractor(..., verified=True, agent_type=AgentType(self.__class__.__name__), ...)
            last_error = error
            print(f"Attempt {attempt + 1} failed for {self.token_id}. Retrying...")
        self._cleanup_script(...)
        return None
```
`run_tdd_loop` roda todas as `deterministic_strategies()` da subclasse seguidas de
até `MAX_LLM_ATTEMPTS` (5) tentativas via LLM, na ordem em que aparecem na lista
combinada. Se **nenhuma** produzir código que verifique, devolve `None` — é esse
`None` que hoje vira `status = "Unresolved"` sem cache nenhum (ver
`CandidateResolver` abaixo). `self.key` é a chave de destino derivada de
`candidate.path` (formato `"header:NomeDoHeader"`/`"cookie:NomeDoCookie"`,
produzido por `BaselineDiff._build_candidate`) — é essa mesma chave que a decisão
3.1/3.2 usa para escopar a nova estratégia de substring **só ao campo correto**,
em vez de qualquer campo da response.

### `CandidateResolver` — `har_reproducer/tracking/candidate_resolver.py` (estado pós spec anterior)
```python
def _generate_extractor(
        self,
        candidate: DynamicToken,
        response_sample: Dict[str, Any],
        initial_error: Optional[str] = None,
) -> Optional[Extractor]:
    if candidate.origin_location is None:
        return self._build_literal_extractor(candidate)

    agent_cls: Type[BaseAgent] = self.LOCATION_AGENTS.get(candidate.origin_location, RegexAgent)
    agent: BaseAgent = agent_cls(
        token_id=candidate.token_id,
        response_sample=response_sample,
        expected_value=candidate.current_value,
        path=candidate.path,
        location=candidate.origin_location.value if candidate.origin_location else None,
        llm=self.llm,
    )
    return agent.run_tdd_loop(origin_step=candidate.origin_step, initial_error=initial_error)

@staticmethod
def _build_literal_extractor(candidate: DynamicToken) -> Extractor:
    safe_token_id: str = BaseAgent.sanitize_identifier(candidate.token_id)
    return Extractor(
        token_id=candidate.token_id,
        code=f"def extract_{safe_token_id}(response):\n    return {candidate.current_value!r}\n",
        verified=True,
        agent_type=AgentType.LITERAL,
        origin_step=candidate.origin_step,
    )

def _register_extractor(self, candidate, response_sample, initial_error=None) -> None:
    new_extractor: Optional[Extractor] = self._generate_extractor(candidate, response_sample, initial_error)
    if new_extractor is not None:
        self.session_store.state.registry[candidate.token_id] = new_extractor
        self.metadata_store.save(new_extractor)
        candidate.status = "Resolved"
    else:
        candidate.status = "Unresolved"
```
Hoje só o caminho `origin_location is None` (spec anterior) evita o `Agent`. Quando
`origin_location` **é** determinado mas `agent.run_tdd_loop(...)` retorna `None`
(esgotou tudo), `_generate_extractor` devolve `None`, `_register_extractor` marca
`Unresolved` **sem chamar `metadata_store.save`** — nada fica persistido. É esse
buraco que a decisão 3.4 fecha.

### `_process_candidate`/`_derive_token_id` — `candidate_resolver.py:40-49,93-95`
```python
def _process_candidate(self, candidate: DynamicToken) -> DynamicToken:
    origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, candidate.current_value)
    if not origin:
        candidate.status = "NotFound"
        return candidate
    candidate.origin_step = origin[0]
    candidate.token_id = self._derive_token_id(candidate.path, candidate.origin_step)
    ...

@staticmethod
def _derive_token_id(path: str, origin_step: int) -> str:
    return hashlib.md5(f"{path}:{origin_step}".encode("utf-8")).hexdigest()
```
`token_id` é determinístico: mesmo `path` (chave de destino) + mesmo `origin_step`
(achado por `ResponseGrep.find`, que busca literalmente por `current_value`) sempre
geram o mesmo hash. É por isso que o `Sec-Fetch-Site: same-origin` reaparece com o
**mesmo** `token_id` em cada step subsequente que carrega o mesmo valor: mesmo
path, mesma busca, mesmo resultado de `ResponseGrep`. Isso garante que o cache que
a decisão 3.4 passa a produzir (via `_register_extractor`/`metadata_store.save`,
inalterados) vai ser efetivamente reaproveitado por `_reuse_persisted_from_disk`
(`candidate_resolver.py:69-80`, inalterado) na próxima ocorrência — sem precisar
de nenhuma mudança nesse mecanismo de cache, ele já reaproveita por `token_id`
independentemente do `agent_type` do extractor salvo.

### `ExtractorMetadataStore`/`ExtractorRunner` — `har_reproducer/reproduction/extractor_metadata_store.py`, `extractor_runner.py`
`ExtractorMetadataStore.save`/`.load` serializam/desserializam qualquer `Extractor`
via Pydantic, sem checar `agent_type`. `ExtractorRunner.run`/`run_existing` executam
o `code` do extractor via subprocess, também sem distinção por `agent_type`. Nenhum
dos dois precisa de alteração — o extractor literal gerado pela decisão 3.4 é
salvo/executado exatamente como qualquer outro.

### `AgentType`/`DynamicToken`/`Extractor` — `har_reproducer/models/session.py` (estado pós spec anterior)
```python
class AgentType(str, Enum):
    COOKIE = "CookieAgent"
    HEADER = "HeaderAgent"
    JSONPATH = "JSONPathAgent"
    CSS = "CSSAgent"
    REGEX = "RegexAgent"
    LITERAL = "LiteralAgent"

class DynamicToken(BaseModel):
    token_id: str
    path: str
    current_value: str
    destination_location: TokenLocation
    origin_location: Optional[TokenLocation] = None
    origin_step: Optional[int] = None
    status: Literal["UnderReview", "NotFound", "Unresolved", "Resolved"]
```
`AgentType.LITERAL` hoje cobre só o caso "origem não determinada". A decisão 3.5
adiciona um membro irmão para "origem determinada, mas extração esgotada". A
decisão 3.6 adiciona um campo booleano a `DynamicToken` para o `CurlGenerator`
saber gerar o comentário certo sem precisar consultar o `Extractor`/registry (que
ele não tem acesso hoje).

### `CurlGenerator._token_comments` — `har_reproducer/reproduction/curl_generator.py:57-65` (estado pós spec anterior)
```python
@staticmethod
def _token_comments(tokens: List[DynamicToken]) -> List[str]:
    lines: List[str] = []
    for token in tokens:
        if token.origin_step is None:
            continue
        lines.append(f"# Token {token.token_id} comes from response of step {token.origin_step}")
        if token.origin_location is None:
            lines.append(f"# Token {token.token_id} origin location undetermined — using literal captured value")
    return lines
```
Só distingue hoje "origem não determinada". A decisão 3.7 adiciona um terceiro
ramo para "origem determinada, extração esgotada" — mantendo a mesma regra da
spec anterior de nunca anexar texto à primeira linha (`CurlDependencyParser.
DEPENDENCY_PATTERN` continua ancorado exatamente nela, ver spec anterior seção
3.7, inalterado aqui).

## 3. Decisões de arquitetura

### 3.1 — Promover `RegexAgent._value_char_class` para `BaseAgent.value_char_class` (compartilhado)

**Estado atual** (`regex_agent.py`): método privado, usado só internamente por
`_key_pattern`/`_context_pattern` da própria classe.

**Estado esperado:** mesmo corpo, sem underscore inicial, movido para
`BaseAgent`:
```python
def value_char_class(self) -> str:
    if re.fullmatch(r"[\w\-.]+", self.expected_value):
        return r"[\w\-.]+"
    return r".+?"
```
`RegexAgent` passa a chamar `self.value_char_class()` (era `self._value_char_class()`).
Necessário porque as decisões 3.2/3.3 (`HeaderAgent`/`CookieAgent`) reaproveitam
esse método — e, pelo guia de estilo, nenhuma classe deveria depender de método
`_`-prefixado de outra (mesmo padrão de `ResponseGrep.value_variants`/
`BaseAgent.sanitize_identifier` na spec anterior).

### 3.2 — `HeaderAgent`: estratégia determinística de substring na própria chave

**Estado atual:** só `_by_name` (ver seção 2), que exige igualdade exata com o
valor inteiro do header.

**Estado esperado:** nova estratégia determinística, adicionada **depois** de
`_by_name` na lista (`_by_name` continua tendo prioridade — é mais barata e mais
específica quando aplicável):
```python
def deterministic_strategies(self) -> List[Strategy]:
    strategies: List[Strategy] = [self._by_name]
    context_pattern: Optional[str] = self._context_pattern()
    if context_pattern is not None:
        strategies.append(self._make_context_strategy(context_pattern))
    return strategies

def _header_value(self) -> Optional[str]:
    key: Optional[str] = self.key
    if not key:
        return None
    headers: Dict[str, str] = self.response_sample.get("headers", {})
    value: Optional[str] = headers.get(key)
    if value is None:
        lowered: Dict[str, str] = {str(k).lower(): v for k, v in headers.items()}
        value = lowered.get(key.lower())
    return value

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

def _make_context_strategy(self, pattern: str) -> Strategy:
    def strategy(last_error: Optional[str] = None) -> Optional[str]:
        return self._build_context_code(pattern)
    return strategy

def _build_context_code(self, pattern: str) -> str:
    key: Optional[str] = self.key
    return f"""
import re

def extract_{self.safe_token_id}(response: dict) -> str:
    headers = response.get('headers', {{}})
    target = {key!r}
    value = headers.get(target)
    if value is None:
        lowered = {{str(k).lower(): v for k, v in headers.items()}}
        value = lowered.get(target.lower())
    if not value:
        raise Exception("Token not found in headers")
    match = re.search({pattern!r}, value)
    if not match:
        raise Exception("Token not found via substring match in header")
    return match.group(1)
"""
```
`_context_pattern` só busca dentro do valor do header **com a mesma chave de
destino** (`self.key`) — nunca em qualquer outro header da response. É essa
restrição que evita reproduzir o problema do `Sec-Fetch-Site`/
`Cross-Origin-Opener-Policy`: se a chave de destino não existir na response de
origem (como no caso real), `_header_value()` devolve `None`, `_context_pattern`
devolve `None`, nenhuma estratégia nova é adicionada — cai direto pra LLM/exaustão
(decisão 3.4 cobre o que acontece depois disso), sem chance de "achar por acaso"
num campo errado.

⚠️ O código gerado (`_build_context_code`) repete o mesmo lookup case-insensitive
de `_by_name` **dentro do texto do template** — não é duplicação de lógica do
agente, é necessidade: o código gerado roda depois, isolado, num subprocesso
(via `ExtractorTemplate`/`ExtractorRunner`), sem acesso a métodos do `HeaderAgent`.
Não tentar "consertar" isso extraindo uma função compartilhada dentro do código
gerado.

⚠️ **Achado durante a implementação:** um quantificador guloso sem âncora de
fim (a versão originalmente desenhada nesta seção) falha sempre que o
delimitador que segue o valor no header também pertence à classe de
caracteres de `value_char_class()` (ex.: `"prefix-abc123-suffix"` com
`expected_value="abc123"` — a classe `[\w\-.]+` inclui hífen, então o `+`
guloso consome também o `-suffix`). Corrigido adicionando
`BaseAgent.lazy_value_char_class()` (mesma classe de `value_char_class()`,
quantificador preguiçoso) e ancorando o fim da captura com um lookahead
`(?=...)` para o caractere real observado logo após o valor na response de
origem (ou `$` quando o valor vai até o fim do header). Não embute o valor em
si no regex — só a fronteira estrutural que o segue —, então continua
funcionando se o valor mudar entre replays, contanto que essa fronteira se
mantenha. Não altera `RegexAgent`/`value_char_class` (decisão 3.1,
inalterada).

### 3.3 — `CookieAgent`: mesma estratégia, escopada a cookies

**Estado atual:** só `_by_name` (ver seção 2).

**Estado esperado:** espelha 3.2, trocando `headers`/`self.response_sample.get("headers")`
por `cookies`/`self.response_sample.get("cookies")`, sem o fallback
case-insensitive (cookies não têm essa ambiguidade, igual `_by_name` já não tem):
```python
def deterministic_strategies(self) -> List[Strategy]:
    strategies: List[Strategy] = [self._by_name]
    context_pattern: Optional[str] = self._context_pattern()
    if context_pattern is not None:
        strategies.append(self._make_context_strategy(context_pattern))
    return strategies

def _context_pattern(self) -> Optional[str]:
    key: Optional[str] = self.key
    if not key:
        return None
    cookie_value: Optional[str] = self.response_sample.get("cookies", {}).get(key)
    if not cookie_value:
        return None
    pos: int = cookie_value.find(self.expected_value)
    if pos == -1:
        return None
    prefix: str = cookie_value[:pos]
    return rf"{re.escape(prefix)}({self.value_char_class()})"

def _make_context_strategy(self, pattern: str) -> Strategy:
    def strategy(last_error: Optional[str] = None) -> Optional[str]:
        return self._build_context_code(pattern)
    return strategy

def _build_context_code(self, pattern: str) -> str:
    key: Optional[str] = self.key
    return f"""
import re

def extract_{self.safe_token_id}(response: dict) -> str:
    cookies = response.get('cookies', {{}})
    value = cookies.get({key!r})
    if not value:
        raise Exception("Token not found in cookies")
    match = re.search({pattern!r}, value)
    if not match:
        raise Exception("Token not found via substring match in cookie")
    return match.group(1)
"""
```

### 3.4 — `CandidateResolver._generate_extractor`: fallback literal quando o Agent esgota tentativas

**Estado atual** (ver seção 2): `run_tdd_loop` retornando `None` propaga `None` até
`_register_extractor`, que marca `Unresolved` sem persistir nada — repete o mesmo
custo em toda ocorrência futura do mesmo `token_id`.

**Estado esperado:**
```python
def _generate_extractor(
        self,
        candidate: DynamicToken,
        response_sample: Dict[str, Any],
        initial_error: Optional[str] = None,
) -> Optional[Extractor]:
    if candidate.origin_location is None:
        return self._build_literal_extractor(candidate, AgentType.LITERAL)

    agent_cls: Type[BaseAgent] = self.LOCATION_AGENTS.get(candidate.origin_location, RegexAgent)
    agent: BaseAgent = agent_cls(
        token_id=candidate.token_id,
        response_sample=response_sample,
        expected_value=candidate.current_value,
        path=candidate.path,
        location=candidate.origin_location.value if candidate.origin_location else None,
        llm=self.llm,
    )
    extractor: Optional[Extractor] = agent.run_tdd_loop(
        origin_step=candidate.origin_step, initial_error=initial_error
    )
    if extractor is not None:
        return extractor

    candidate.extraction_exhausted = True
    return self._build_literal_extractor(candidate, AgentType.LITERAL_FALLBACK)

@staticmethod
def _build_literal_extractor(candidate: DynamicToken, agent_type: AgentType) -> Extractor:
    safe_token_id: str = BaseAgent.sanitize_identifier(candidate.token_id)
    return Extractor(
        token_id=candidate.token_id,
        code=f"def extract_{safe_token_id}(response):\n    return {candidate.current_value!r}\n",
        verified=True,
        agent_type=agent_type,
        origin_step=candidate.origin_step,
    )
```
`_build_literal_extractor` passa a exigir `agent_type` explícito (não hardcoda
mais `AgentType.LITERAL`) — os dois call sites (`origin_location is None` e o novo
fallback pós-exaustão) passam o `AgentType` correspondente. Com isso,
`_generate_extractor` **nunca mais devolve `None`** quando `response_sample`
existe — `_register_extractor` (inalterado) sempre cai no ramo `Resolved` +
`metadata_store.save`, fechando o buraco de cache.

⚠️ Isso não muda o valor que termina no curl da requisição corrente: sem extractor
verificado, `PlaceholderApplier` já mantinha o valor literal do HAR (ver spec
anterior, seção 2) — o extractor literal devolve exatamente esse mesmo valor. A
mudança é só sobre **não repetir o trabalho fadado ao fracasso** nas próximas
ocorrências do mesmo `token_id`.

### 3.5 — Novo membro no enum `AgentType`

**Estado atual** (`models/session.py`): 6 membros (5 originais + `LITERAL` da spec
anterior).

**Estado esperado:**
```python
class AgentType(str, Enum):
    COOKIE = "CookieAgent"
    HEADER = "HeaderAgent"
    JSONPATH = "JSONPathAgent"
    CSS = "CSSAgent"
    REGEX = "RegexAgent"
    LITERAL = "LiteralAgent"
    LITERAL_FALLBACK = "LiteralFallbackAgent"
```
Permite diferenciar em `.meta.json`/auditoria "origem nunca determinada"
(`LiteralAgent`) de "origem determinada, mas nenhuma estratégia conseguiu
extrair" (`LiteralFallbackAgent`) — o segundo caso é mais sério (pode indicar uma
origem incorreta, como no caso `Sec-Fetch-Site`) e merece ficar rastreável
separadamente.

### 3.6 — Novo campo `DynamicToken.extraction_exhausted`

**Estado atual** (`models/session.py`): sem esse campo.

**Estado esperado:**
```python
class DynamicToken(BaseModel):
    token_id: str
    path: str
    current_value: str
    destination_location: TokenLocation
    origin_location: Optional[TokenLocation] = None
    origin_step: Optional[int] = None
    status: Literal["UnderReview", "NotFound", "Unresolved", "Resolved"]
    extraction_exhausted: bool = False
```
Setado como `True` só pela decisão 3.4, no ramo de fallback pós-exaustão. Default
`False` cobre todos os outros casos (inclusive `origin_location is None`, que não
passa por esse branch). Único consumidor: `CurlGenerator` (decisão 3.7).

### 3.7 — `CurlGenerator._token_comments`: comentário distinto para exaustão

**Estado atual** (ver seção 2): só dois ramos (linha base; "origem não
determinada").

**Estado esperado:**
```python
@staticmethod
def _token_comments(tokens: List[DynamicToken]) -> List[str]:
    lines: List[str] = []
    for token in tokens:
        if token.origin_step is None:
            continue
        lines.append(f"# Token {token.token_id} comes from response of step {token.origin_step}")
        if token.origin_location is None:
            lines.append(f"# Token {token.token_id} origin location undetermined — using literal captured value")
        elif token.extraction_exhausted:
            lines.append(
                f"# Token {token.token_id} origin location determined but extraction exhausted — "
                f"using literal captured value"
            )
    return lines
```
Mesma regra da spec anterior: linha extra **separada**, nunca anexada à primeira
(`CurlDependencyParser.DEPENDENCY_PATTERN` continua ancorado só nela — inalterado,
não faz parte desta spec).

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `BaseAgent` | `_value_char_class` (de `RegexAgent`) vira público, `BaseAgent.value_char_class` |
| `RegexAgent` | Chama `self.value_char_class()` em vez do método próprio removido |
| `HeaderAgent` | Nova estratégia determinística `_context_pattern`/`_make_context_strategy`/`_build_context_code` — substring na própria chave |
| `CookieAgent` | Idem, escopado a `cookies` |
| `CandidateResolver._generate_extractor` | Fallback para `_build_literal_extractor(candidate, AgentType.LITERAL_FALLBACK)` quando `run_tdd_loop` retorna `None` |
| `CandidateResolver._build_literal_extractor` | Passa a exigir `agent_type` explícito (dois call sites) |
| `AgentType` (enum) | Novo membro `LITERAL_FALLBACK = "LiteralFallbackAgent"` |
| `DynamicToken` (model) | Novo campo `extraction_exhausted: bool = False` |
| `CurlGenerator._token_comments` | Novo ramo de comentário quando `extraction_exhausted` |

## 5. Casos de borda e comportamento de erro

- **Chave de destino não existe na response de origem** (caso real:
  `Sec-Fetch-Site` numa response que só tem headers de servidor) — `_header_value`/
  `cookies.get(key)` devolvem `None`, nenhuma estratégia de substring é adicionada,
  segue pro LLM e depois pro fallback da decisão 3.4. Comportamento esperado, é
  exatamente o caso que motivou esta spec.
- **Substring coincide na própria chave, mas ainda por acaso** (ex.: um header
  cujo valor **naquela response específica** contém o valor atual como substring
  sem relação causal real) — risco residual aceito, não coberto por esta spec:
  é ordens de magnitude mais raro que o caso corrigido (precisa colidir chave **e**
  conteúdo), e mesmo se acontecer, na pior hipótese gera um extractor que passa a
  falhar quando o valor real mudar — nesse ponto o mecanismo de replay já existente
  (`ReplayTokenResolver`) trataria como token mudou (`ever_changed = True`), não
  como estático.
- **`run_tdd_loop` esgota e cai no fallback, mas o valor real deveria variar por
  requisição** (ex.: um header que legitimamente muda por contexto, não só por
  coincidência) — o extractor literal fixa o valor capturado **daquela ocorrência
  específica** (`candidate.current_value` no momento da falha). Se um step
  seguinte tiver um `current_value` diferente para o mesmo destino, `ResponseGrep.
  find` busca por esse **novo** valor, tipicamente resultando em `origin_step`
  diferente e, portanto, `token_id` diferente (`_derive_token_id`, inalterado) —
  não há colisão entre extractors de valores diferentes do mesmo `path`.
- **`_build_literal_extractor` chamado sem `agent_type`** — não é mais possível
  depois da decisão 3.4 (parâmetro passa a ser obrigatório); qualquer novo call
  site futuro precisa decidir explicitamente qual `AgentType` usar.
- **Interação com o cache existente** (`_reuse_verified_in_memory`/
  `_reuse_persisted_from_disk`, ambos inalterados) — o extractor literal de
  fallback é salvo com `verified=True` exatamente como qualquer outro, então passa
  a ser reaproveitado normalmente nas próximas ocorrências do mesmo `token_id`,
  sem precisar de nenhuma lógica especial de cache para esse `agent_type`.

## 6. Suposições e pontos a confirmar

- Nome do novo membro do enum: `AgentType.LITERAL_FALLBACK = "LiteralFallbackAgent"`
  — sujeito a ajuste de nomenclatura.
- Nome do novo campo: `DynamicToken.extraction_exhausted` — sujeito a ajuste.
- Texto exato do comentário extra no curl (decisão 3.7) — sujeito a ajuste de
  wording, seguindo o mesmo tom do comentário já existente da spec anterior.
- Confirmado nesta conversa: `BaselineDiff` (causa raiz de headers contextuais
  virando candidato), detecção mais rigorosa em `ResponseGrep`/
  `TokenLocationDetector`, e remoção de extractors "probably static" ficam
  explicitamente fora de escopo desta spec.

## Referência

Toda alteração de código desta spec segue o padrão descrito em
[[guia-de-estilo]] (`.claude/skills/guia-de-estilo`).
