# Plano de Implementação — Extração por Substring e Fallback de Exaustão

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## T01 — `BaseAgent`: expor `value_char_class` publicamente (promovido de `RegexAgent`)

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/agents/base_agent.py` (`BaseAgent`), `har_reproducer/agents/regex_agent.py` (`RegexAgent._key_pattern`, `RegexAgent._context_pattern`, `RegexAgent._value_char_class`)

**Contexto:**
`RegexAgent._value_char_class` decide a classe de caracteres do grupo de captura
de um regex de extração, a partir de `self.expected_value`. As tasks T04/T05
(`HeaderAgent`/`CookieAgent`) precisam da mesma lógica pra montar seus próprios
regexes de substring. Hoje esse método é `_`-prefixado, privado por convenção —
pelo guia de estilo, nenhuma classe deveria depender de método `_`-prefixado de
outra, então precisa virar público antes de ser reaproveitado.

**Estado atual:**
```python
# regex_agent.py
def _key_pattern(self) -> Optional[str]:
    key: Optional[str] = self.key
    if not key or key == "body":
        return None
    return rf"{re.escape(key)}['\"]?\s*[:=]\s*['\"]?({self._value_char_class()})"

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

**Estado esperado depois:**
```python
# base_agent.py — novo método (mesmo corpo, sem underscore inicial)
def value_char_class(self) -> str:
    if re.fullmatch(r"[\w\-.]+", self.expected_value):
        return r"[\w\-.]+"
    return r".+?"
```
```python
# regex_agent.py — _value_char_class removido; call sites atualizados
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
⚠️ `base_agent.py` já importa `re` no topo do arquivo — não precisa de novo
import. Nenhuma outra lógica de `RegexAgent` muda.

**Critérios de aceite:**
- [x] `BaseAgent(token_id="x", response_sample={}, expected_value="abc-123").value_char_class()` retorna `r"[\w\-.]+"`.
- [x] `BaseAgent(token_id="x", response_sample={}, expected_value="a b?c").value_char_class()` retorna `r".+?"` (contém caractere fora de `\w\-.`).
- [x] `RegexAgent(...)._key_pattern()`/`_context_pattern()` continuam produzindo exatamente o mesmo regex de antes pra um mesmo `key`/`body`/`expected_value` fixo — não regressão.
- [x] Nenhum ponto do código chama `RegexAgent._value_char_class` (nome antigo) — só existe `BaseAgent.value_char_class`.

## T02 — `AgentType`: novo membro `LITERAL_FALLBACK`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/session.py` (`AgentType`)

**Contexto:**
O extractor literal que a task T06 vai gerar no caminho de "origem determinada,
mas extração esgotada" precisa de um `agent_type` que o distinga do
`AgentType.LITERAL` já existente (que significa "origem nunca determinada") —
são causas diferentes e precisam ficar auditáveis separadamente em
`extract_*.meta.json`.

**Estado atual:**
```python
class AgentType(str, Enum):
    COOKIE = "CookieAgent"
    HEADER = "HeaderAgent"
    JSONPATH = "JSONPathAgent"
    CSS = "CSSAgent"
    REGEX = "RegexAgent"
    LITERAL = "LiteralAgent"
```

**Estado esperado depois:**
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

**Critérios de aceite:**
- [x] `AgentType.LITERAL_FALLBACK.value == "LiteralFallbackAgent"`.
- [x] `Extractor(token_id="x", code="...", agent_type=AgentType.LITERAL_FALLBACK, origin_step=1)` valida normalmente com Pydantic.
- [x] Os 6 membros existentes (`COOKIE`, `HEADER`, `JSONPATH`, `CSS`, `REGEX`, `LITERAL`) continuam com os mesmos valores — não regressão.

## T03 — `DynamicToken`: novo campo `extraction_exhausted`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/session.py` (`DynamicToken`)

**Contexto:**
O `CurlGenerator` (task T07) precisa saber, a partir do próprio `DynamicToken`,
se um token virou extractor literal por "origem nunca determinada" ou por
"origem determinada mas extração esgotada" — sem precisar consultar o registry
de extractors (que ele não recebe hoje). Esse campo é o sinal que a task T06 seta.

**Estado atual:**
```python
class DynamicToken(BaseModel):
    token_id: str
    path: str
    current_value: str
    destination_location: TokenLocation
    origin_location: Optional[TokenLocation] = None
    origin_step: Optional[int] = None
    status: Literal["UnderReview", "NotFound", "Unresolved", "Resolved"]
```

**Estado esperado depois:**
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

**Critérios de aceite:**
- [ ] `DynamicToken(token_id="x", path="p", current_value="v", destination_location=TokenLocation.HEADER, status="UnderReview").extraction_exhausted` é `False` por padrão.
- [ ] Passar `extraction_exhausted=True` explicitamente no construtor reflete em `.extraction_exhausted`.
- [ ] `BaselineDiff._build_candidate` (`baseline_diff.py:55-66`, não tocado por esta task) continua construindo `DynamicToken` sem passar esse campo, e o resultado continua validando — não regressão.

## T04 — `HeaderAgent`: estratégia determinística de substring na própria chave

**Depende de:** T01 (precisa de `BaseAgent.value_char_class` público).
**Arquivos envolvidos:** `har_reproducer/agents/header_agent.py` (`HeaderAgent`, arquivo inteiro)

**Contexto:**
Hoje `HeaderAgent` só tem `_by_name`, que exige que `expected_value` seja igual
ao valor **inteiro** do header. Quando o token é uma substring legítima de um
header real (ex.: um ID embutido num header composto), isso força uma tentativa
via LLM sem nenhuma estratégia determinística de apoio. A nova estratégia busca
o valor **dentro do mesmo header de destino** (`self.key`) — nunca em outro
header da response — pra não abrir margem de casar com um campo não
relacionado (ver `spec.md` seção 1, caso `Sec-Fetch-Site`/
`Cross-Origin-Opener-Policy`).

**Estado atual:**
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

**Estado esperado depois:**
```python
import re
from typing import Dict, List, Optional

from har_reproducer.agents.base_agent import BaseAgent
from har_reproducer.contracts import Strategy


class HeaderAgent(BaseAgent):

    def deterministic_strategies(self) -> List[Strategy]:
        strategies: List[Strategy] = [self._by_name]
        context_pattern: Optional[str] = self._context_pattern()
        if context_pattern is not None:
            strategies.append(self._make_context_strategy(context_pattern))
        return strategies

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
⚠️ `_context_pattern` só olha o header **com a mesma chave de destino**
(`self.key`) — nunca itera por todos os headers da response. Se a chave não
existir na response de origem, `_header_value()` devolve `None` e nenhuma
estratégia nova é adicionada (comportamento correto, não um bug a "corrigir").

⚠️ O lookup case-insensitive dentro de `_build_context_code` é uma repetição
proposital do mesmo trecho em `_by_name` — o código gerado roda isolado, num
subprocesso, sem acesso a métodos do `HeaderAgent`. Não fatorar isso num helper
compartilhado dentro do texto do template.

**Critérios de aceite:**
- [ ] Response de origem `{"headers": {"X-Trace": "prefix-abc123-suffix"}}`,
  `expected_value="abc123"`, `path="header:X-Trace"`: `_by_name` falha (valor
  inteiro não bate), a nova estratégia de contexto gera código que, executado,
  retorna exatamente `"abc123"` — `run_tdd_loop` termina com `Extractor`
  `verified=True`.
- [ ] Response de origem sem a chave `Sec-Fetch-Site` em `headers` (caso real da
  spec): `_header_value()` retorna `None`, `_context_pattern()` retorna `None`,
  `deterministic_strategies()` tem só 1 estratégia (`_by_name`) — sem exceção,
  sem estratégia espúria.
- [ ] Caso já existente (`_by_name` bate com o valor inteiro do header) continua
  resolvendo pela primeira estratégia, sem precisar da nova — não regressão.
- [ ] Fallback case-insensitive: `headers = {"x-trace": "prefix-abc123-suffix"}`,
  `path="header:X-Trace"` (case diferente) — `_header_value()` ainda encontra o
  valor via o mesmo fallback já usado por `_by_name`, e a extração por substring
  funciona igual.

## T05 — `CookieAgent`: estratégia determinística de substring na própria chave

**Depende de:** T01 (precisa de `BaseAgent.value_char_class` público).
**Arquivos envolvidos:** `har_reproducer/agents/cookie_agent.py` (`CookieAgent`, arquivo inteiro)

**Contexto:**
Espelha a task T04, mas pra cookies — sem o fallback case-insensitive, porque
`_by_name` de `CookieAgent` também não tem essa ambiguidade hoje.

**Estado atual:**
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

**Estado esperado depois:**
```python
import re
from typing import List, Optional

from har_reproducer.agents.base_agent import BaseAgent
from har_reproducer.contracts import Strategy


class CookieAgent(BaseAgent):

    def deterministic_strategies(self) -> List[Strategy]:
        strategies: List[Strategy] = [self._by_name]
        context_pattern: Optional[str] = self._context_pattern()
        if context_pattern is not None:
            strategies.append(self._make_context_strategy(context_pattern))
        return strategies

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
⚠️ Mesma restrição da T04: `_context_pattern` só olha o cookie com a mesma
chave de destino — nunca todos os cookies da response.

**Critérios de aceite:**
- [ ] Response de origem `{"cookies": {"session": "sid=abc123;path=/"}}`,
  `expected_value="abc123"`, `path="cookie:session"`: `_by_name` falha, a nova
  estratégia gera código que retorna exatamente `"abc123"` — `run_tdd_loop`
  termina com `Extractor` `verified=True`.
- [ ] Response de origem sem a chave de destino em `cookies`:
  `_context_pattern()` retorna `None`, `deterministic_strategies()` tem só 1
  estratégia — sem exceção.
- [ ] Caso já existente (`_by_name` bate com o valor inteiro do cookie) continua
  resolvendo pela primeira estratégia — não regressão.

## T06 — `CandidateResolver`: fallback para extrator literal quando o Agent esgota tentativas

**Depende de:** T02 (`AgentType.LITERAL_FALLBACK`), T03 (`DynamicToken.extraction_exhausted`).
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (`CandidateResolver._generate_extractor`, `CandidateResolver._build_literal_extractor`)

**Contexto:**
Quando `origin_location` é determinado, mas `agent.run_tdd_loop(...)` esgota
todas as estratégias (determinísticas + LLM) e retorna `None`,
`_register_extractor` marca `Unresolved` sem persistir nada — o mesmo
`token_id` (determinístico por `path`+`origin_step`, ver `spec.md` seção 2)
reaparece em steps seguintes e repete o mesmo custo de LLM do zero, toda vez
(caso real: `Sec-Fetch-Site`, 6 tentativas repetidas em cada um dos steps 15 a
19 do `progressofit.har`). A partir desta task, esse esgotamento também vira um
extractor literal, cacheado normalmente.

**Estado atual:**
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
```

**Estado esperado depois:**
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
⚠️ `_build_literal_extractor` passa a exigir `agent_type` explícito — os dois
call sites (`origin_location is None`, e o novo fallback pós-exaustão) já estão
atualizados acima. Nenhum outro ponto do código chama esse método.

⚠️ `_register_extractor` (chamador, inalterado) não precisa de nenhuma mudança:
com essa task, `_generate_extractor` nunca mais devolve `None` quando
`response_sample` existe, então o ramo `else: candidate.status = "Unresolved"`
de `_register_extractor` só continua alcançável pelo caminho já existente e
não tocado (`_generate_new_extractor` retornando cedo quando `_load_response`
falha).

**Critérios de aceite:**
- [ ] Candidato com `origin_location = TokenLocation.HEADER`, `origin_step = 5`,
  `current_value = "same-origin"`, e um `Agent` cujo `run_tdd_loop` (mockado)
  retorna `None`: `_generate_extractor` devolve um `Extractor` com
  `agent_type == AgentType.LITERAL_FALLBACK`, `verified == True`, `code`
  contendo `return 'same-origin'`; `candidate.extraction_exhausted` vira `True`.
- [ ] Candidato com `origin_location = None` continua devolvendo
  `AgentType.LITERAL` (não `LITERAL_FALLBACK`), e `candidate.extraction_exhausted`
  permanece `False` — não regressão do caminho da spec anterior.
- [ ] Candidato com `origin_location = TokenLocation.HEADER` e `Agent` cujo
  `run_tdd_loop` (mockado) devolve um `Extractor` de verdade: esse `Extractor`
  é devolvido sem alteração, `candidate.extraction_exhausted` permanece `False`
  — não regressão do caminho de sucesso normal.
- [ ] Rodando `_register_extractor` de ponta a ponta pro cenário de exaustão:
  `candidate.status` termina `"Resolved"` (não mais `"Unresolved"`), e o
  extractor literal de fallback é salvo em `session_store.state.registry` e via
  `metadata_store.save` — verificável relendo o `.meta.json` gerado.
- [ ] **Regressão end-to-end**: rodar novamente `uv run python -m
  har_reproducer.main run --har progressofit.har --config config.json --mode
  dry` — o candidato do header `Sec-Fetch-Site` (token que hoje repete
  `Attempt N failed` em cada step 15 a 19) deve falhar (tentar e esgotar) **só
  na primeira ocorrência**; nas ocorrências seguintes do mesmo `token_id`, o
  extractor cacheado (`agent_type: "LiteralFallbackAgent"` no `.meta.json`) é
  reaproveitado via `_reuse_persisted_from_disk` (inalterado), sem nenhum novo
  `Attempt N failed` pra esse token.

## T07 — `CurlGenerator`: comentário distinto quando a extração foi esgotada

**Depende de:** T03 (`DynamicToken.extraction_exhausted`).
**Arquivos envolvidos:** `har_reproducer/reproduction/curl_generator.py` (`CurlGenerator._token_comments`)

**Contexto:**
Depois da T06, um token pode virar extractor literal por dois motivos
diferentes: origem nunca determinada (já sinalizado desde a spec anterior) ou
origem determinada mas extração esgotada (novo). O curl gerado precisa
distinguir os dois na auditoria, sem quebrar o parsing de dependências do
replay.

**Estado atual:**
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

**Estado esperado depois:**
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
⚠️ Mesma regra da spec anterior: linha extra **separada**, nunca anexada à
primeira — `CurlDependencyParser.DEPENDENCY_PATTERN`
(`har_reproducer/replay/curl_dependency_parser.py:8-11`) continua ancorado
(`^...$`) só na primeira linha; não tocar essa classe.

**Critérios de aceite:**
- [ ] Token com `origin_step = 5`, `origin_location = TokenLocation.HEADER`,
  `extraction_exhausted = False`: gera só a linha base — não regressão.
- [ ] Token com `origin_step = 5`, `origin_location = TokenLocation.HEADER`,
  `extraction_exhausted = True`: gera a linha base seguida de
  `# Token {id} origin location determined but extraction exhausted — using
  literal captured value`.
- [ ] Token com `origin_step = 5`, `origin_location = None` (independente de
  `extraction_exhausted`, que fica `False` por default nesse caminho): gera a
  linha base seguida de `# Token {id} origin location undetermined — using
  literal captured value` — não regressão do comportamento da spec anterior
  (o ramo `elif` nunca executa quando `origin_location is None`, porque o `if`
  já capturou o caso).
- [ ] Token com `origin_step = None`: nenhuma linha de comentário — não
  regressão.
- [ ] `CurlDependencyParser().parse(curl_text)` continua extraindo
  `{token_id: origin_step}` corretamente mesmo com a terceira linha extra
  presente — não regressão do parsing de dependências usado no replay.
