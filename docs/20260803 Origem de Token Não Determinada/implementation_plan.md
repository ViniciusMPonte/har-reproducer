# Plano de Implementação — Origem de Token Não Determinada

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## T01 — `ResponseGrep`: grep de string fixa e variantes de valor expostas publicamente

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/response_grep.py` (`ResponseGrep._grep_single_pattern`, `ResponseGrep._build_pattern_variants`)

**Contexto:**
`ResponseGrep` decide se um candidato a token dinâmico "tem origem" em alguma
response já persistida, procurando o valor (e variantes dele) via `grep` nos
arquivos `res_*.json`. Essa busca hoje trata o valor como regex sem escapar, o
que gera falso-positivo pra qualquer valor com metacaractere de regex (o caso
real observado: header `Accept: */*` — `*/*` como regex ERE casa com
praticamente qualquer arquivo que tenha um `*`, porque o `*` solto é tratado
como literal e o `*` final quantifica o `/` anterior como "zero ou mais").
Além disso, a lista de variantes que essa classe testa (`_build_pattern_variants`)
precisa ser reaproveitada pelo `TokenLocationDetector` (task T04) — hoje é um
método `_`-prefixado, privado por convenção, e não deve ser chamado de outra
classe nesse estado.

**Estado atual:**
```python
@classmethod
def _grep_single_pattern(cls, responses_dir: Path, pattern: str) -> Optional[Tuple[int, str]]:
    try:
        cmd: List[str] = ["grep", "-rl", "--include=res_*.json", pattern, str(responses_dir)]
        result: CompletedProcess[str] = subprocess.run(cmd, capture_output=True, text=True, check=True)
        ...

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
`find()` chama `cls._build_pattern_variants(pattern)` internamente.

**Estado esperado depois:**
- `_grep_single_pattern` monta o comando com a flag `-F` (fixed-string):
  ```python
  cmd: List[str] = ["grep", "-rlF", "--include=res_*.json", pattern, str(responses_dir)]
  ```
- `_build_pattern_variants` é renomeado para `value_variants`, sem underscore
  inicial, mesmo corpo, virando `@classmethod` público:
  ```python
  @classmethod
  def value_variants(cls, value: str) -> List[str]:
      candidates: List[str] = [
          value,
          cls.try_decode(value),
          urllib.parse.quote(value, safe=""),
          base64.b64encode(value.encode("utf-8")).decode("ascii"),
      ]
      return cls._deduplicate(candidates)
  ```
- `find()` (`ResponseGrep.find`) atualiza a chamada interna para
  `cls.value_variants(pattern)`.
- ⚠️ Nenhuma outra lógica muda: `try_decode`, `_deduplicate`,
  `_extract_step_index` ficam exatamente como estão.

**Critérios de aceite:**
- [x] `ResponseGrep._grep_single_pattern(dir, "*/*")` não casa mais por acidente
  de regex com um arquivo que só contenha um `*` solto sem a substring `*/*`
  literal (verificar criando um `res_0000.json` de teste com um `*` isolado e
  confirmando que não aparece no resultado).
- [x] `ResponseGrep.value_variants("abc")` retorna uma lista contendo `"abc"` e
  `"YWJj"` (base64 de `"abc"`), sem duplicatas — mesmo comportamento de hoje,
  só com nome/visibilidade novos.
- [x] `ResponseGrep.find(dir, pattern)` continua retornando `(step_index,
  filename)` para os mesmos casos que já funcionavam antes desta task (não
  regressão): rodar contra um `responses_dir` com um valor presente
  literalmente em algum `res_000N.json` e confirmar que o step certo ainda é
  encontrado.
- [x] Nenhum outro ponto do código chama `ResponseGrep._build_pattern_variants`
  (nome antigo) — só existe a versão pública `value_variants`.

## T02 — `BaseAgent`: expor `sanitize_identifier` publicamente

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/agents/base_agent.py` (`BaseAgent.__init__`, `BaseAgent._sanitize_identifier`)

**Contexto:**
`CandidateResolver` (task T05) precisa nomear a função Python do extractor
literal do mesmo jeito que qualquer outro extractor gerado por um `BaseAgent` —
reaproveitando a sanitização de identificador que já existe, em vez de
duplicá-la. Hoje esse método é `_`-prefixado, privado por convenção.

**Estado atual:**
```python
def __init__(self, token_id, response_sample, expected_value, path=None, location=None, llm=None) -> None:
    self.token_id: str = token_id
    self.safe_token_id: str = self._sanitize_identifier(token_id)
    ...

@staticmethod
def _sanitize_identifier(raw: str) -> str:
    sanitized: str = re.sub(r"\W", "_", str(raw))
    if sanitized and sanitized[0].isdigit():
        sanitized = f"t_{sanitized}"
    return sanitized or "token"
```

**Estado esperado depois:**
```python
def __init__(self, token_id, response_sample, expected_value, path=None, location=None, llm=None) -> None:
    self.token_id: str = token_id
    self.safe_token_id: str = self.sanitize_identifier(token_id)
    ...

@staticmethod
def sanitize_identifier(raw: str) -> str:
    sanitized: str = re.sub(r"\W", "_", str(raw))
    if sanitized and sanitized[0].isdigit():
        sanitized = f"t_{sanitized}"
    return sanitized or "token"
```
Só renomeação (remove o underscore inicial) e atualização do único call site
interno (`__init__`, linha 33). Corpo do método idêntico.

**Critérios de aceite:**
- [x] `BaseAgent.sanitize_identifier("0b7b9cc9...")` retorna
  `"t_0b7b9cc9..."` (prefixo `t_` porque começa com dígito) — mesmo
  comportamento de hoje.
- [x] `BaseAgent.sanitize_identifier("abc-123")` retorna `"abc_123"` — mesmo
  comportamento de hoje.
- [x] `HeaderAgent(...).safe_token_id`, `CookieAgent(...).safe_token_id`, etc.
  continuam sendo populados corretamente (nenhuma regressão nas subclasses,
  que herdam `__init__` sem override).
- [x] Nenhum ponto do código chama `BaseAgent._sanitize_identifier` (nome
  antigo) — só existe a versão pública `sanitize_identifier`.

## T03 — `AgentType`: novo membro `LITERAL`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/session.py` (`AgentType`)

**Contexto:**
O extractor literal que a task T05 vai gerar precisa de um `agent_type` que o
distinga de um extractor gerado por um Agent real — para que
`extract_*.meta.json` e qualquer auditoria futura consigam diferenciar "valor
fixo porque a origem não foi determinada" de uma extração de verdade.

**Estado atual:**
```python
class AgentType(str, Enum):
    COOKIE = "CookieAgent"
    HEADER = "HeaderAgent"
    JSONPATH = "JSONPathAgent"
    CSS = "CSSAgent"
    REGEX = "RegexAgent"
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
```

**Critérios de aceite:**
- [x] `AgentType.LITERAL.value == "LiteralAgent"`.
- [x] `Extractor(token_id="x", code="...", agent_type=AgentType.LITERAL,
  origin_step=1)` continua validando normalmente com Pydantic (não regressão
  no modelo `Extractor`).
- [x] Os 5 membros existentes (`COOKIE`, `HEADER`, `JSONPATH`, `CSS`, `REGEX`)
  continuam com os mesmos valores.

## T04 — `TokenLocationDetector`: checar `redirect_url` e variantes de encoding; retornar `Optional[TokenLocation]` em vez de chutar `BODY_JSON`

**Depende de:** T01 (precisa de `ResponseGrep.value_variants` público).
**Arquivos envolvidos:** `har_reproducer/tracking/token_location_detector.py` (`TokenLocationDetector`, classe inteira)

**Contexto:**
`TokenLocationDetector.find` só é chamado depois que `ResponseGrep.find` já
"confirmou" uma origem — mas a busca do `ResponseGrep` é mais ampla (pesquisa o
arquivo bruto inteiro, incluindo `redirect_url`, e testa 4 variantes de
encoding do valor) do que o que `find()` sabe reconhecer (só headers/cookies/
body, só a forma literal). Essa lacuna faz `find()` falhar em confirmar
origens genuínas, e o fallback atual "resolve" isso chutando `BODY_JSON` —
mesmo sabendo, pelo retorno do próprio `_find_in_body` duas linhas antes, que
o valor não está no body. É uma contradição lógica que gera extractors
condenados a falhar (caso real: header `Accept: */*` no step 12 de
`progressofit.har`, ver `spec.md` seção 1).

**Estado atual:**
```python
class TokenLocationDetector:

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

        print(
            f"[AVISO] Não foi possível determinar a origem do token '{value[:30]}...' com confiança; assumindo BODY_JSON."
        )
        return TokenLocation.BODY_JSON

    @staticmethod
    def _find_in_headers(value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        for header_value in response_sample.get("headers", {}).values():
            if value in header_value:
                return TokenLocation.HEADER
        return None

    @staticmethod
    def _find_in_cookies(value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        for cookie_value in response_sample.get("cookies", {}).values():
            if value in cookie_value:
                return TokenLocation.COOKIE
        return None

    @classmethod
    def _find_in_body(cls, value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        body: Optional[str] = response_sample.get("body")
        if not body or value not in body:
            return None
        ...
```

**Estado esperado depois:**
```python
from har_reproducer.tracking.response_grep import ResponseGrep

class TokenLocationDetector:

    @classmethod
    def find(cls, value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        location: Optional[TokenLocation] = cls._find_in_headers(value, response_sample)
        if location is not None:
            return location

        location = cls._find_in_cookies(value, response_sample)
        if location is not None:
            return location

        location = cls._find_in_redirect_url(value, response_sample)
        if location is not None:
            return location

        location = cls._find_in_body(value, response_sample)
        if location is not None:
            return location

        print(f"[AVISO] Não foi possível determinar a origem do token '{value[:30]}...'.")
        return None

    @classmethod
    def _find_in_headers(cls, value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        for header_value in response_sample.get("headers", {}).values():
            if cls._value_present(value, header_value):
                return TokenLocation.HEADER
        return None

    @classmethod
    def _find_in_cookies(cls, value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        for cookie_value in response_sample.get("cookies", {}).values():
            if cls._value_present(value, cookie_value):
                return TokenLocation.COOKIE
        return None

    @classmethod
    def _find_in_redirect_url(cls, value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        redirect_url: Optional[str] = response_sample.get("redirect_url")
        if redirect_url and cls._value_present(value, redirect_url):
            return TokenLocation.URL_PARAM
        return None

    @classmethod
    def _find_in_body(cls, value: str, response_sample: Dict[str, Any]) -> Optional[TokenLocation]:
        body: Optional[str] = response_sample.get("body")
        if not body or not cls._value_present(value, body):
            return None
        ...  # resto do método (_is_script_mime/_is_json_mime/_is_html_mime/_locate_in_html) inalterado

    @classmethod
    def _value_present(cls, value: str, text: str) -> bool:
        return any(variant in text for variant in ResponseGrep.value_variants(value))
```
⚠️ Dentro de `_locate_in_html` (subclassificação `BODY_HTML` vs. `SCRIPT`), as
comparações `value in html_without_scripts` e `value in match.group(1)`
**não** mudam para `_value_present` — ficam literais, com o comportamento
padrão (`BODY_HTML`) já existente quando não conseguem decidir. Isso é
intencional (spec.md seção 3.3 e seção 5), não um esquecimento.

**Critérios de aceite:**
- [ ] `TokenLocationDetector.find("*/*", {"headers": {}, "cookies": {}, "body": None, "redirect_url": None})` retorna `None` (não `TokenLocation.BODY_JSON`).
- [ ] `TokenLocationDetector.find("abc123", {"headers": {"Location": "https://x/abc123"}, "cookies": {}, "body": None, "redirect_url": None})` retorna `TokenLocation.HEADER` (comportamento já existente, não regressão).
- [ ] `TokenLocationDetector.find("abc", {"headers": {}, "cookies": {}, "body": None, "redirect_url": "https://x.com/callback?token=abc"})` retorna `TokenLocation.URL_PARAM` (novo, via `_find_in_redirect_url`).
- [ ] `TokenLocationDetector.find("abc", {"headers": {"X-Data": "YWJj"}, "cookies": {}, "body": None, "redirect_url": None})` retorna `TokenLocation.HEADER` (novo: `"YWJj"` é o base64 de `"abc"`, reconhecido via `_value_present`/`ResponseGrep.value_variants`; hoje retornaria `BODY_JSON` incorretamente).
- [ ] `TokenLocationDetector.find("qualquercoisa", {"headers": {}, "cookies": {}, "body": '{"outra_chave": "outro_valor"}', "body_mime": "application/json", "redirect_url": None})` retorna `None` (valor genuinamente ausente, nem literal nem em nenhuma variante).
- [ ] Casos já cobertos hoje continuam idênticos: valor em `body` JSON válido retorna `BODY_JSON`; valor em bloco `<script>` retorna `SCRIPT`; valor em HTML fora de `<script>` retorna `BODY_HTML`.

## T05 — `CandidateResolver`: gerar extractor literal quando a origem não é determinada

**Depende de:** T02 (`BaseAgent.sanitize_identifier` público), T03 (`AgentType.LITERAL`), T04 (`origin_location is None` passa a significar "genuinamente não determinado").
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (`CandidateResolver._generate_extractor`)

**Contexto:**
Depois da T04, `candidate.origin_location is None` (setado em
`_generate_new_extractor`, linha 89, inalterada) significa "não determinado
com confiança" de verdade. Sem tratamento explícito, isso cairia no default
`LOCATION_AGENTS.get(None, RegexAgent)` → `RegexAgent`, reproduzindo o mesmo
problema que motivou esta spec (até 5 chamadas ao LLM tentando extrair um
valor de um lugar que não foi identificado). Em vez disso, o candidato deve
virar um extractor trivial que retorna o valor literal capturado, sem custo de
LLM.

**Estado atual:**
```python
def _generate_extractor(
        self,
        candidate: DynamicToken,
        response_sample: Dict[str, Any],
        initial_error: Optional[str] = None,
) -> Optional[Extractor]:
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
Import novo necessário no topo do arquivo: `AgentType` (de
`har_reproducer.models`, já importado `DynamicToken, Extractor, TokenLocation`
— só adicionar `AgentType` na mesma linha).

⚠️ `_register_extractor` (chamador de `_generate_extractor`, inalterado) já
salva o resultado via `ExtractorMetadataStore.save` e registra em
`session_store.state.registry` independentemente do `agent_type` — não precisa
de nenhuma mudança para o extractor literal ser cacheado/reaproveitado em
execuções futuras via `_reuse_persisted_from_disk` (também inalterado).

⚠️ Não alterar o default `RegexAgent` em
`LOCATION_AGENTS.get(candidate.origin_location, RegexAgent)` — esse branch só
executa quando `origin_location` é `TokenLocation.URL_PARAM` (único valor do
enum fora do dict), comportamento já existente e fora do escopo desta task.

**Critérios de aceite:**
- [ ] Candidato com `origin_location = None` e `current_value = "*/*"` e
  `origin_step = 5` gera um `Extractor` com `agent_type == AgentType.LITERAL`,
  `verified == True`, `origin_step == 5`, e `code` contendo `return '*/*'`.
- [ ] Executar esse `code` (via `ExtractorRunner.run` ou chamando a função
  gerada diretamente com qualquer `response` dict, inclusive `{}`) retorna
  exatamente `"*/*"`, sem lançar exceção — não depende do conteúdo de
  `response`.
- [ ] Nenhuma chamada a `agent_cls(...)`/`run_tdd_loop`/LLM acontece para esse
  caminho (verificável por não haver instância de `BaseAgent` envolvida).
- [ ] Candidato com `origin_location = TokenLocation.HEADER` continua indo
  para `HeaderAgent.run_tdd_loop` normalmente — não regressão do caminho
  existente.
- [ ] **Regressão end-to-end**: rodar novamente `uv run python -m
  har_reproducer.main run --har progressofit.har --config config.json --mode
  dry` (mesmo `output_dir` já existente, sem `--reset`) até o step 12 não deve
  imprimir nenhum `Attempt N failed` nem erro `429 RESOURCE_EXHAUSTED` para o
  candidato do header `Accept` — o step 12 deve completar direto, e o
  `extract_*.meta.json` correspondente deve existir com
  `"agent_type": "LiteralAgent"`.

## T06 — `CurlGenerator`: comentário extra quando a origem não foi determinada

**Depende de:** T04 (`origin_location is None` só passa a significar "não determinado" depois dessa task).
**Arquivos envolvidos:** `har_reproducer/reproduction/curl_generator.py` (`CurlGenerator._token_comments`)

**Contexto:**
Hoje o curl gerado tem uma linha `# Token {id} comes from response of step
{origin_step}` para qualquer token com `origin_step`, resolvido ou não — sem
indicar quando a extração não teve confiança. Depois desta spec, um token
resolvido via extractor literal (T05) merece ficar visível como tal, para
auditoria futura, sem quebrar o parsing de dependências que já existe.

**Estado atual:**
```python
@staticmethod
def _token_comments(tokens: List[DynamicToken]) -> List[str]:
    return [
        f"# Token {token.token_id} comes from response of step {token.origin_step}"
        for token in tokens
        if token.origin_step is not None
    ]
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
    return lines
```
⚠️ A segunda linha é **um comentário novo e separado**, nunca anexado à
primeira linha na mesma string — `CurlDependencyParser.DEPENDENCY_PATTERN`
(`har_reproducer/replay/curl_dependency_parser.py:8-11`) é ancorada (`^...$`)
exatamente no formato `# Token {id} comes from response of step {origin_step}`;
anexar texto ali quebraria esse regex para todo token que usa essa linha,
inclusive os resolvidos normalmente.

**Critérios de aceite:**
- [ ] Token com `origin_step = 5`, `origin_location = TokenLocation.HEADER`
  gera só a linha `# Token {id} comes from response of step 5` — não
  regressão do formato existente.
- [ ] Token com `origin_step = 5`, `origin_location = None` gera duas linhas:
  `# Token {id} comes from response of step 5` seguida de `# Token {id} origin
  location undetermined — using literal captured value`.
- [ ] Token com `origin_step = None` continua sem gerar nenhuma linha de
  comentário — não regressão.
- [ ] `CurlDependencyParser().parse(curl_text)` continua extraindo
  `{token_id: origin_step}` corretamente a partir do curl gerado, mesmo
  quando a segunda linha extra está presente logo abaixo (a regex ancorada
  `^...$` com `re.MULTILINE` casa a primeira linha independente da segunda) —
  não regressão do parsing de dependências usado no replay.
