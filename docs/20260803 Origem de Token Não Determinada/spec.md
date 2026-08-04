# Spec — Origem de Token Não Determinada

## 1. Objetivo

Hoje, quando um candidato a token dinâmico tem sua origem "encontrada" pelo
`ResponseGrep`, mas o `TokenLocationDetector` não consegue confirmar em qual parte
daquela response o valor realmente está (headers, cookies ou body), o método
`TokenLocationDetector.find` **chuta** `TokenLocation.BODY_JSON` em vez de admitir
que não sabe. Isso força o `CandidateResolver` a instanciar um `JSONPathAgent` e
gastar até `BaseAgent.MAX_LLM_ATTEMPTS` (5) chamadas ao LLM tentando extrair um
valor de um JSON onde ele nunca esteve — uma tentativa estruturalmente fadada ao
fracasso.

Isso foi reproduzido e confirmado rodando o pipeline (`uv run python -m
har_reproducer.main run --mode dry`) contra `progressofit.har` até o step 12
(`GET /src/app.js`). O candidato problemático é o header `Accept: */*`
(`req_0012.json:5`). O log mostrou:

```
[AVISO] Não foi possível determinar a origem do token '*/*...' com confiança; assumindo BODY_JSON.
Attempt 1 failed for 0b7b9cc9965d8224310afbf1bc7a3917. Retrying...
Attempt 2 failed for 0b7b9cc9965d8224310afbf1bc7a3917. Retrying...
[AVISO] Falha na chamada ao LLM ...: 429 RESOURCE_EXHAUSTED ...
Attempt 3 failed ... Attempt 4 failed ...
Step 12 completed with status 200
```

A causa raiz tem duas camadas:

1. **`ResponseGrep._grep_single_pattern`** (`har_reproducer/tracking/response_grep.py:60`)
   passa o valor do candidato direto para o `grep` **como regex, sem escapar**.
   `*/*` como regex é quase degenerado: um `*` sem átomo anterior é tratado como
   literal, e o `*` final quantifica o `/` anterior como "zero ou mais" — na prática
   esse padrão casa com qualquer arquivo que tenha um `*` em qualquer lugar. Isso
   produz um `origin_step` **falso-positivo**: o pipeline "acha" que `*/*` vem de
   uma response anterior, quando na verdade o grep só casou por acidente de regex.
2. **`TokenLocationDetector.find`** (`har_reproducer/tracking/token_location_detector.py:24-27`)
   corretamente não encontra `*/*` de verdade em headers/cookies/body daquela
   response (porque o match do grep era ilusório) — mas em vez de sinalizar essa
   incerteza, assume `BODY_JSON` mesmo sabendo (pelo próprio retorno de
   `_find_in_body` duas linhas antes) que o valor **não está** no body. É uma
   contradição lógica: o método prova que o valor não está lá, e no fallback
   responde que está.

**O que essa mudança cobre:**
- `ResponseGrep` passa a buscar por substring literal, não regex — elimina a
  classe de falso-positivo/falso-negativo para qualquer valor com metacaractere de
  regex (não só `*/*`).
- `TokenLocationDetector.find` passa a checar também `redirect_url` (campo que o
  `ResponseGrep` já pesquisa mas o detector nunca olhou), e a testar as mesmas
  variantes de encoding (url/base64) que o `ResponseGrep` já usa para decidir se
  há origem — fechando o gap entre "o que prova que há origem" e "o que o
  detector sabe reconhecer" — antes de desistir e retornar explicitamente "não
  determinado" (`None`) em vez de chutar uma location que ele mesmo já
  descartou.
- Quando a origem fica genuinamente "não determinada", o `CandidateResolver` para
  de tentar (e falhar) gerar um extractor real via LLM, e gera diretamente um
  extractor trivial que apenas retorna o valor literal capturado — sem custo de
  LLM, sem retries, sem risco de rate limit.
- O extractor literal fica marcado com um `AgentType` próprio e o curl gerado
  ganha um comentário extra sinalizando que a origem não foi determinada — para
  que isso seja auditável, não silenciosamente idêntico a uma resolução com
  confiança real.

**Fora de escopo (não implementar agora):**
- **Causa raiz anterior** — `BaselineDiff._diff_headers` (`baseline_diff.py:24-29`)
  trata qualquer header que difira de um baseline único e fixo (o step 0) como
  candidato dinâmico, mesmo quando a diferença é só variação normal por tipo de
  request (ex.: `Accept: */*` em um `fetch` de script vs. `Accept:
  text/html,...` na navegação inicial). É essa heurística que faz `Accept` virar
  candidato antes de chegar em qualquer código tocado por esta spec. Corrigir isso
  eliminaria o cenário na origem, mas é uma mudança de escopo maior (decidir
  quais headers ignorar, revisar `extract_static_values`) e fica para uma spec
  separada.
- **"Estático após replay"** (`ReplayTokenResolver.STATIC_CONFIRMATION_THRESHOLD`,
  `replay_runner.STATIC_WARNING_SUFFIX`) — mecanismo diferente e já existente, que
  decide que um extractor **já verificado e funcionando** é estático depois de
  observar 5 execuções de replay sem o valor mudar. Isso não é tocado aqui: o
  problema desta spec acontece **antes** de qualquer extractor existir. Os dois
  mecanismos coexistem sem conflito (ver seção 5).
- Ensinar `_locate_in_html` a diferenciar `BODY_HTML` de `SCRIPT` quando o valor só
  aparece de forma codificada dentro do HTML/script — o suporte a variantes de
  encoding desta spec (decisão 3.3) cobre a **detecção da origem** (headers,
  cookies, redirect_url, presença no body), não essa subclassificação interna;
  nesse caso específico o comportamento já existente de `_locate_in_html`
  (default `BODY_HTML`) continua valendo, documentado como limitação conhecida
  (seção 5).

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `TokenLocationDetector.find` — `har_reproducer/tracking/token_location_detector.py:10-27`
```python
@classmethod
def find(cls, value: str, response_sample: Dict[str, Any]) -> TokenLocation:
    location: Optional[TokenLocation] = cls._find_in_headers(value, response_sample)
    if location is not None:
        return location
    location = cls._find_in_cookies(value, response_sample)
    if location is not None:
        return location
    location = cls._find_in_body(value, response_sample)
    if location is not None:
        return location
    print(f"[AVISO] ...; assumindo BODY_JSON.")
    return TokenLocation.BODY_JSON
```
Checa headers, cookies e body, nessa ordem. As decisões 3.2 e 3.3 estendem
`_find_in_headers`/`_find_in_cookies`/`_find_in_body` e adicionam
`_find_in_redirect_url`; a decisão 3.4 muda o fallback final (as duas últimas
linhas).

### `ResponseGrep.find`/`_grep_single_pattern`/`_build_pattern_variants` — `har_reproducer/tracking/response_grep.py:12-78`
```python
@classmethod
def find(cls, responses_dir: Path, pattern: str) -> Optional[Tuple[int, str]]:
    for variant in cls._build_pattern_variants(pattern):
        match: Optional[Tuple[int, str]] = cls._grep_single_pattern(responses_dir, variant)
        if match is not None:
            return match
    return None

@classmethod
def _build_pattern_variants(cls, pattern: str) -> List[str]:
    candidates: List[str] = [
        pattern,
        cls.try_decode(pattern),
        urllib.parse.quote(pattern, safe=""),
        base64.b64encode(pattern.encode("utf-8")).decode("ascii"),
    ]
    return cls._deduplicate(candidates)
```
`_build_pattern_variants` gera as 4 formas do valor que o `ResponseGrep` aceita
como evidência de origem (literal, decodificada, url-encoded, base64); cada
variante é usada como regex do `grep` porque não há flag de string fixa (decisão
3.1 corrige isso). Esse é o único ponto de chamada ao `grep` no projeto. A
decisão 3.3 reaproveita essa mesma lista de variantes dentro do
`TokenLocationDetector` — por isso `_build_pattern_variants` precisa deixar de
ser "privado por convenção" e virar `ResponseGrep.value_variants` (público, sem
mudar corpo/lógica), para ser chamado de outra classe sem violar o guia de
estilo (nenhuma classe deveria depender de método `_`-prefixado de outra).

### `CandidateResolver._process_candidate`/`_generate_new_extractor`/`_generate_extractor` — `har_reproducer/tracking/candidate_resolver.py:40-144`
```python
def _process_candidate(self, candidate: DynamicToken) -> DynamicToken:
    origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, candidate.current_value)
    if not origin:
        candidate.status = "NotFound"
        return candidate
    candidate.origin_step = origin[0]
    ...
    return self._generate_new_extractor(candidate, initial_error)

def _generate_new_extractor(self, candidate, initial_error):
    candidate.status = "UnderReview"
    response_sample = self._load_response(candidate.origin_step)
    if response_sample is None:
        return candidate
    candidate.origin_location = TokenLocationDetector.find(candidate.current_value, response_sample)
    self._register_extractor(candidate, response_sample, initial_error)
    return candidate

def _generate_extractor(self, candidate, response_sample, initial_error=None):
    agent_cls: Type[BaseAgent] = self.LOCATION_AGENTS.get(candidate.origin_location, RegexAgent)
    agent: BaseAgent = agent_cls(token_id=..., response_sample=..., expected_value=..., path=...,
                                  location=candidate.origin_location.value if candidate.origin_location else None,
                                  llm=self.llm)
    return agent.run_tdd_loop(origin_step=candidate.origin_step, initial_error=initial_error)
```
`TokenLocationDetector.find` só é chamado depois que `ResponseGrep.find` **já**
confirmou (ou pensou ter confirmado) uma origem — por isso `candidate.origin_step`
sempre existe nesse ponto. `LOCATION_AGENTS` (linhas 17-23) mapeia
`TokenLocation → Type[BaseAgent]`; o único membro do enum fora do dict é
`URL_PARAM`, que já cai no default `RegexAgent`.

### `BaseAgent` — `har_reproducer/agents/base_agent.py:20-38`
```python
MAX_LLM_ATTEMPTS: int = 5
...
def _build_strategies(self) -> List[Strategy]:
    deterministic: List[Strategy] = self.deterministic_strategies()
    llm_attempts: List[Strategy] = [self._llm_strategy] * self.MAX_LLM_ATTEMPTS
    return deterministic + llm_attempts
```
Cada tentativa de gerar um extractor real passa por estratégias determinísticas
(quando existem) e depois até 5 chamadas ao LLM — é esse custo que o extractor
literal evita por completo.

### `RegexAgent` — `har_reproducer/agents/regex_agent.py`
Estratégias determinísticas (`_key_pattern`/`_context_pattern`) só olham
`response_sample.get("body")`. A estratégia via LLM (`_llm_strategy` →
`ExtractorPrompt.build`, `har_reproducer/prompts/extractor_prompt.py:8-29`) recebe
o `response_sample` **inteiro** no prompt (`Response sample: {response_sample!r}`),
incluindo `redirect_url` — ou seja, o LLM tem visibilidade para escrever código que
leia `redirect_url` mesmo que as estratégias determinísticas só cubram `body`. Isso
importa para a decisão 3.2: rotear um valor achado em `redirect_url` para
`RegexAgent` (via `URL_PARAM`) não é um beco sem saída, o LLM consegue de fato
extrair de lá.

### `PlaceholderApplier._apply_token` — `har_reproducer/tracking/placeholder_applier.py:20-26`
```python
def _apply_token(self, request: StepRequest, token: DynamicToken) -> None:
    if not token.current_value:
        return
    extractor: Optional[Extractor] = self._verified_extractor(token.token_id)
    if extractor is None:
        return
    ...
```
Sem extractor verificado, nada é substituído — o curl final mantém o valor
literal do HAR. É por isso que o candidato `Accept: */*` de hoje, mesmo terminando
`Unresolved`, **não gera um curl quebrado** — o dano de hoje é só o custo/tempo
gasto tentando (e falhando) gerar o extractor, não uma reprodução incorreta.

### `CurlGenerator._token_comments` — `har_reproducer/reproduction/curl_generator.py:57-63`
```python
@staticmethod
def _token_comments(tokens: List[DynamicToken]) -> List[str]:
    return [
        f"# Token {token.token_id} comes from response of step {token.origin_step}"
        for token in tokens
        if token.origin_step is not None
    ]
```
Gera esse comentário para **qualquer** token com `origin_step`, resolvido ou não
— hoje o candidato `Unresolved` do step 12 já deixa esse comentário no curl, sem
qualquer indicação de que a extração falhou.

### `CurlDependencyParser.DEPENDENCY_PATTERN` — `har_reproducer/replay/curl_dependency_parser.py:8-11`
```python
DEPENDENCY_PATTERN: ClassVar[Pattern[str]] = re.compile(
    r"^# Token (?P<token_id>[a-z0-9]+) comes from response of step (?P<origin_step>\d+)$",
    re.MULTILINE,
)
```
Regex **ancorada** (`^...$`) na linha exata gerada por `CurlGenerator`. É usada
por `ReplayTokenResolver.resolve` (`har_reproducer/replay/replay_token_resolver.py:32-38`)
só para os `token_id` que aparecem como placeholder `{{extractor:token_id}}` no
texto do curl — como `PlaceholderApplier` nunca cria esse placeholder sem
extractor verificado, um candidato `Unresolved`/`NotFound` nunca é procurado por
`ReplayTokenResolver`, mesmo tendo o comentário de dependência escrito. Importa
para a decisão 3.7: **não posso** anexar texto na mesma linha desse comentário,
porque quebraria esse regex ancorado para candidatos resolvidos normalmente que
também usem essa mesma linha de comentário.

### `ExtractorRunner._write_extractor_script` — `har_reproducer/reproduction/extractor_runner.py:27-30`
```python
def _write_extractor_script(self, extractor: Extractor) -> Path:
    if extractor.origin_step is None:
        raise ValueError(f"Extractor '{extractor.token_id}' has no origin_step to load a response from.")
```
Exige `origin_step` não nulo. Como o extractor literal só é gerado quando
`ResponseGrep` já achou uma origem (`candidate.origin_step` setado antes de
`TokenLocationDetector.find` ser chamado), essa exigência já é satisfeita sem
mudança adicional.

### `Extractor`/`DynamicToken`/`AgentType` — `har_reproducer/models/session.py:7-43`
```python
class AgentType(str, Enum):
    COOKIE = "CookieAgent"
    HEADER = "HeaderAgent"
    JSONPATH = "JSONPathAgent"
    CSS = "CSSAgent"
    REGEX = "RegexAgent"

class Extractor(BaseModel):
    token_id: str
    code: str
    verified: bool = False
    agent_type: AgentType
    origin_step: Optional[int] = None
    temp_file_path: Optional[str] = None
    valid_count: int = 0
    last_value: Optional[str] = None
    ever_changed: bool = False

class DynamicToken(BaseModel):
    token_id: str
    path: str
    current_value: str
    destination_location: TokenLocation
    origin_location: Optional[TokenLocation] = None
    origin_step: Optional[int] = None
    status: Literal["UnderReview", "NotFound", "Unresolved", "Resolved"]
```
`origin_location` já é `Optional` — só o retorno do `find()` é que hoje nunca
entrega `None` a esse campo.

### `ExtractorTemplate.render_script` — `har_reproducer/templates/extractor_template.py:26-48`
Envolve `extractor.code` numa função que carrega a response do disco e chama
`extract_{safe_token_id}(response)`. Qualquer código de extractor, literal ou
não, só precisa seguir esse contrato de assinatura — não precisa realmente usar o
argumento `response`.

### `BaseAgent._sanitize_identifier` — `har_reproducer/agents/base_agent.py:41-45`
```python
@staticmethod
def _sanitize_identifier(raw: str) -> str:
    sanitized: str = re.sub(r"\W", "_", str(raw))
    if sanitized and sanitized[0].isdigit():
        sanitized = f"t_{sanitized}"
    return sanitized or "token"
```
Função pura, sem estado de instância — reaproveitada pela decisão 3.5 fora de um
`BaseAgent`, para nomear a função do extractor literal. Pelo mesmo motivo do
`ResponseGrep.value_variants`, precisa virar `BaseAgent.sanitize_identifier`
(público, mesmo corpo) para ser chamada do `CandidateResolver` sem reaproveitar
um método `_`-prefixado de outra classe.

## 3. Decisões de arquitetura

### 3.1 — `ResponseGrep` deve buscar substring literal, não regex

**Estado atual** (`response_grep.py:60`):
```python
cmd: List[str] = ["grep", "-rl", "--include=res_*.json", pattern, str(responses_dir)]
```
`pattern` (e suas variantes) é interpretado como ERE. Qualquer valor com
metacaractere de regex (`. * + ? [ ] ( ) { } ^ $ | \`) pode gerar falso-positivo
(caso `*/*`) ou falso-negativo.

**Estado esperado:**
```python
cmd: List[str] = ["grep", "-rlF", "--include=res_*.json", pattern, str(responses_dir)]
```
Adicionar a flag `-F` (fixed-string) faz o `grep` tratar `pattern` como string
literal. Nenhuma outra lógica de `_build_pattern_variants`/`try_decode`/
`_extract_step_index` muda.

### 3.2 — `TokenLocationDetector.find` deve checar `redirect_url` antes de desistir

**Estado atual**: só `_find_in_headers`, `_find_in_cookies`, `_find_in_body` — três
dos campos de `StepResponse` (`har_reproducer/models/http.py:16-23`, que também
tem `status_code` e `redirect_url`). O `ResponseGrep` (que decide se há origem)
pesquisa o arquivo bruto inteiro, incluindo `redirect_url`; o `find()` não.

**Estado esperado:** novo método, na mesma linha dos existentes:
```python
@staticmethod
def _find_in_redirect_url(value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
    redirect_url: Optional[str] = response_sample.get("redirect_url")
    if redirect_url and value in redirect_url:
        return TokenLocation.URL_PARAM
    return None
```
Chamado em `find()` depois de `_find_in_cookies` e antes de `_find_in_body` (ordem
não é crítica, mas mantém a leitura "headers → cookies → redirect → body").
Reaproveita `TokenLocation.URL_PARAM` (já existe, já é o valor semanticamente
correto para "o valor viaja numa URL", já usado por
`BaselineDiff._determine_location` para candidatos de query string) — não cria
membro novo no enum. Um `URL_PARAM` vindo daqui cai no mesmo default
`RegexAgent` que `URL_PARAM` já usa hoje (`LOCATION_AGENTS.get(...,
RegexAgent)`), e a estratégia via LLM do `RegexAgent` recebe o `response_sample`
completo (inclui `redirect_url`) — tem visibilidade real pra extrair de lá (ver
seção 2).

### 3.3 — `TokenLocationDetector` deve checar as mesmas variantes de encoding que o `ResponseGrep` já usa

**Estado atual**: `_find_in_headers`, `_find_in_cookies`, `_find_in_redirect_url`
(3.2) e a checagem de presença em `_find_in_body` usam `value in texto` —
comparação pela forma literal exata. O `ResponseGrep` já decidiu que há origem
testando 4 variantes do valor (`ResponseGrep.value_variants`, ver seção 2); o
`find()` não tenta nenhuma delas além da literal. Isso deixa um
gap real: um token pode genuinamente vir de um header/cookie, só que codificado
ali (ex.: base64), e `find()` falha em confirmar isso mesmo quando é verdade.

Esse gap importa mais do que "só mais um caso de borda": `HeaderAgent`/
`CookieAgent` (ver seção 2) resolvem por **nome da chave**, não por valor — se
`find()` disser `HEADER` para um token codificado, o `HeaderAgent` ainda
funciona (pega o header pelo nome; se o valor bruto não bater com
`expected_value`, o `run_tdd_loop` já teria essa tentativa marcada como falha e
seguiria pra tentativa via LLM, que recebe o `response_sample` inteiro e tem
chance real de decodificar). Sem esse gap fechado, esse token cairia
incorretamente no extractor literal (decisão 3.5) — congelando como "estático"
um valor que na verdade é dinâmico, só que codificado.

**Estado esperado:** um helper compartilhado, usado pelos quatro pontos de
checagem:
```python
@classmethod
def _value_present(cls, value: str, text: str) -> bool:
    return any(variant in text for variant in ResponseGrep.value_variants(value))
```
`_find_in_headers`, `_find_in_cookies`, `_find_in_redirect_url` passam a chamar
`cls._value_present(value, header_value)` (etc.) no lugar de `value in
header_value`. Em `_find_in_body`, a guarda inicial (`token_location_detector.py:46`)
```python
if not body or value not in body:
    return None
```
vira:
```python
if not body or not cls._value_present(value, body):
    return None
```

⚠️ **Limite proposital**: dentro de `_locate_in_html` (subclassificação
`BODY_HTML` vs. `SCRIPT` quando o valor já foi confirmado em algum lugar do
body), as checagens `value in html_without_scripts` e `value in
match.group(1)` **continuam literais** — não viram `_value_present`. Ensinar
essa parte a raciocinar sobre variantes exigiria saber qual variante casou lá
dentro para procurar a variante certa nos dois pedaços (HTML vs. script), o que
é uma mudança maior; o comportamento já existente (default `BODY_HTML` quando
não dá pra decidir) continua cobrindo esse caso. Ver seção 5.

### 3.4 — Fallback deve retornar "não determinado" em vez de chutar `BODY_JSON`

**Estado atual** (`token_location_detector.py:11,24-27`):
```python
@classmethod
def find(cls, value: str, response_sample: Dict[str, Any]) -> TokenLocation:
    ...
    location = cls._find_in_body(value, response_sample)
    if location is not None:
        return location
    print(f"[AVISO] Não foi possível determinar a origem do token '{value[:30]}...' com confiança; assumindo BODY_JSON.")
    return TokenLocation.BODY_JSON
```

**Estado esperado:**
```python
@classmethod
def find(cls, value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
    ...
    location = cls._find_in_body(value, response_sample)
    if location is not None:
        return location
    print(f"[AVISO] Não foi possível determinar a origem do token '{value[:30]}...'.")
    return None
```
Assinatura muda de `TokenLocation` para `Optional[TokenLocation]`. Mensagem de
aviso ajustada (remove "assumindo BODY_JSON", que deixa de ser verdade).

⚠️ Único caller é `candidate_resolver.py:89`
(`candidate.origin_location = TokenLocationDetector.find(...)`) — já aceita
`None` sem quebrar (o campo `DynamicToken.origin_location` já é `Optional`), mas
o comportamento de `_generate_extractor` a partir daqui precisa saber tratar esse
`None` (decisão 3.5) em vez de deixá-lo cair no default `RegexAgent` do
`LOCATION_AGENTS.get(candidate.origin_location, RegexAgent)`.

### 3.5 — `CandidateResolver` gera um extractor literal quando a origem não é determinada

**Estado atual** (`candidate_resolver.py:128-144`):
```python
def _generate_extractor(self, candidate, response_sample, initial_error=None):
    agent_cls: Type[BaseAgent] = self.LOCATION_AGENTS.get(candidate.origin_location, RegexAgent)
    agent: BaseAgent = agent_cls(...)
    return agent.run_tdd_loop(origin_step=candidate.origin_step, initial_error=initial_error)
```
Com a mudança 3.4, `candidate.origin_location is None` passa a significar
"genuinamente não determinado" (não mais "seja BODY_JSON, sem confiança"). Hoje,
um `None` cairia no default `RegexAgent` e repetiria o mesmo problema
(tentativa via LLM fadada a falhar, sem nenhuma pista de onde procurar).

**Estado esperado:**
```python
def _generate_extractor(self, candidate, response_sample, initial_error=None):
    if candidate.origin_location is None:
        return self._build_literal_extractor(candidate)
    agent_cls: Type[BaseAgent] = self.LOCATION_AGENTS.get(candidate.origin_location, RegexAgent)
    agent: BaseAgent = agent_cls(...)
    return agent.run_tdd_loop(origin_step=candidate.origin_step, initial_error=initial_error)

def _build_literal_extractor(self, candidate: DynamicToken) -> Extractor:
    safe_token_id: str = BaseAgent.sanitize_identifier(candidate.token_id)
    return Extractor(
        token_id=candidate.token_id,
        code=f"def extract_{safe_token_id}(response):\n    return {candidate.current_value!r}\n",
        verified=True,
        agent_type=AgentType.LITERAL,
        origin_step=candidate.origin_step,
    )
```
Nenhuma instância de `BaseAgent`/subclasses, nenhuma chamada ao LLM, nenhum
`run_tdd_loop` — o código é `return <valor literal>`, correto por construção, não
precisa de validação. `verified=True` de imediato.

O reaproveitamento entre execuções ("não pesquisar de novo") já vem de graça:
`_register_extractor` (linha 103-115, inalterado) salva esse `Extractor` no
`session_store.state.registry` e via `ExtractorMetadataStore.save` exatamente
como qualquer outro; `_reuse_persisted_from_disk` (linhas 69-80, inalterado) já
reexecuta e reaproveita por `token_id` em runs futuras, sem distinguir se o
extractor é literal ou não.

⚠️ Não alterar o default `RegexAgent` para `TokenLocation.URL_PARAM` — esse
comportamento já existe hoje e não faz parte deste fix (decisão 3.2 só adiciona
uma FORMA NOVA de chegar em `URL_PARAM`, a partir de `redirect_url`).

### 3.6 — Novo membro no enum `AgentType`

**Estado atual** (`models/session.py:7-12`): 5 membros, todos ligados a uma
estratégia real de extração.

**Estado esperado:**
```python
class AgentType(str, Enum):
    COOKIE = "CookieAgent"
    HEADER = "HeaderAgent"
    JSONPATH = "JSONPathAgent"
    CSS = "CSSAgent"
    REGEX = "RegexAgent"
    LITERAL = "LiteralAgent"
```
Permite distinguir, em `extract_*.meta.json` e em qualquer auditoria futura, um
extractor gerado por um Agent real de um valor fixo porque a origem não foi
determinada.

### 3.7 — Comentário adicional no curl quando a origem não foi determinada

**Estado atual** (`curl_generator.py:57-63`): uma única linha de comentário por
token com `origin_step`, sem indicar confiança/resolução.

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
    return lines
```
⚠️ A anotação vai numa **linha separada**, não anexada à linha existente. A
`CurlDependencyParser.DEPENDENCY_PATTERN` (`curl_dependency_parser.py:8-11`) é
ancorada (`^...$`) exatamente na linha `# Token {id} comes from response of step
{origin_step}` — anexar texto ali quebraria esse regex para candidatos
resolvidos normalmente que compartilham esse formato de linha. Manter a linha
original intacta preserva o parsing de dependências tal como é hoje.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `ResponseGrep._grep_single_pattern` | `grep -rl` → `grep -rlF` (substring literal, não regex) |
| `ResponseGrep._build_pattern_variants` | vira público, `ResponseGrep.value_variants` (mesmo corpo) |
| `TokenLocationDetector.find` | novo `_find_in_redirect_url`; checagens de header/cookie/redirect_url/body passam a usar `_value_present` (variantes de encoding via `ResponseGrep.value_variants`); assinatura `Optional[TokenLocation]`; fallback retorna `None` em vez de `BODY_JSON` |
| `BaseAgent._sanitize_identifier` | vira público, `BaseAgent.sanitize_identifier` (mesmo corpo) |
| `CandidateResolver._generate_extractor` | novo branch para `origin_location is None` → `_build_literal_extractor` (sem Agent/LLM) |
| `AgentType` (enum) | novo membro `LITERAL = "LiteralAgent"` |
| `CurlGenerator._token_comments` | linha extra de comentário quando `token.origin_location is None` |

## 5. Casos de borda e comportamento de erro

- **Valor com outros metacaracteres de regex** (`.`, `+`, `[`, etc., não só
  `*`) — corrigido igualmente pela mudança 3.1, sem tratamento especial por
  caractere.
- **Valor está em `headers`/`cookies`/`body`/`redirect_url` só de forma
  codificada** — coberto pela decisão 3.3 (`_value_present` testando as mesmas
  variantes do `ResponseGrep`): `find()` classifica a location corretamente, e
  o Agent correspondente (`HeaderAgent`/`CookieAgent` por nome de chave, ou
  `RegexAgent`/LLM por conteúdo) tem uma chance real de decodificar — não fica
  mais preso ao extractor literal.
- **Valor está no body só de forma codificada, e a subclassificação
  `BODY_HTML` vs. `SCRIPT` depende dessa forma codificada** — limitação aceita,
  fora de escopo (ver seção 1): `_locate_in_html` continua comparando de forma
  literal e cai no default `BODY_HTML` quando não consegue decidir. Não é uma
  regressão: hoje esse caso específico nem chegaria a ser reconhecido como
  presente no body.
- **Mesmo candidato "não determinado" aparece em vários steps do mesmo HAR,
  com `origin_step` diferente em cada ocorrência** (porque o `ResponseGrep`
  pode achar um arquivo diferente conforme mais responses se acumulam) — cada
  ocorrência gera seu próprio `token_id`/extractor literal. Aceito: é o mesmo
  comportamento de cache por `token_id` que já existe hoje para extractors
  reais, não uma regressão introduzida por esta mudança.
- **Extractor literal, uma vez usado em replay** — converge com o mecanismo
  já existente `ReplayTokenResolver.STATIC_CONFIRMATION_THRESHOLD`: como sempre
  retorna o mesmo valor por construção, depois de 5 observações de replay
  também é marcado "- probably static" (`replay_runner.STATIC_WARNING_SUFFIX`).
  Comportamento esperado, não é conflito com esta spec.
- **`find()` mudando de retorno garantido `TokenLocation` para
  `Optional[TokenLocation]`** — único caller (`candidate_resolver.py:89`)
  precisa passar a tratar `None` explicitamente na escolha de agente (decisão
  3.5); hoje não trata porque nunca recebia `None`.
- **`ResponseGrep.find` retorna `None` (nenhuma variante bate em nenhum
  response)** — candidato já vira `status = "NotFound"` antes de qualquer
  código desta spec ser executado (`candidate_resolver.py:44-46`, inalterado).
  Fora do alcance desta mudança; comportamento já existente e já adequado
  (`PlaceholderApplier` também não substitui nada nesse caso).

## 6. Suposições e pontos a confirmar

- Reaproveitar `TokenLocation.URL_PARAM` para o achado em `redirect_url` (em vez
  de criar um valor novo no enum) — assumido como correto por ser semanticamente
  "o valor viaja numa URL", mesmo padrão já usado por `BaselineDiff`.
- Nome do novo membro do enum: `AgentType.LITERAL = "LiteralAgent"` — sujeito a
  ajuste de nomenclatura.
- Texto exato do comentário extra no curl (seção 3.6) — sujeito a ajuste de
  wording.
- Confirmado nesta conversa: a causa raiz em `BaselineDiff` (headers de
  negociação de conteúdo virando candidatos por diferirem de um baseline único)
  fica de fato fora de escopo desta spec, tratada como melhoria futura separada.

## Referência

Toda alteração de código desta spec segue o padrão descrito em
[[guia-de-estilo]] (`.claude/skills/guia-de-estilo`).
