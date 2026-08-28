# Plano de Implementação — Jar de Cookies Determinístico entre Steps

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de
> uma task posterior). Cada task é autocontida — não deveria ser necessário
> reabrir a spec pra executar uma task isolada.

## [T01] — `CookieAttributes`/`StepResponse`: modelo aditivo pra domínio/path/expiração de cookie

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/http.py` (`StepResponse`), `har_reproducer/models/__init__.py` (export).

**Contexto:** Hoje `StepResponse.cookies: Dict[str, str]` guarda só nome→valor
de cada `Set-Cookie` — sem domínio, path ou expiração. O jar de cookies (T05)
precisa dessa informação pra decidir o escopo de cada cookie e removê-lo
quando expira. Esta task só cria o modelo; quem o popula de fato são T02
(captura ao vivo) e T03 (parse do envelope).

**Estado atual** (`models/http.py:16-24`):
```python
class StepResponse(BaseModel):
    status_code: int
    headers: Dict[str, str] = Field(default_factory=dict)
    cookies: Dict[str, str] = Field(default_factory=dict)
    body: Optional[Union[str, bytes]] = None
    body_mime: Optional[str] = None
    redirect_url: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None
```

**Estado esperado depois:**
- Novo modelo `CookieAttributes(BaseModel)` com `domain: Optional[str] = None`,
  `path: str = "/"`, `expired: bool = False`.
- `StepResponse` ganha `cookie_attributes: Dict[str, CookieAttributes] =
  Field(default_factory=dict)` — campo aditivo, logo após `cookies`.
- `CookieAttributes` exportado em `har_reproducer/models/__init__.py`
  (`__all__` e import), no mesmo padrão dos demais modelos de `http.py`.
- ⚠️ `cookies: Dict[str, str]` **não muda de shape** — zero impacto em
  `CookieAgent`/qualquer extractor já gerado que lê `response['cookies']`
  como string simples (spec seção 3.1).

**Critérios de aceite:**
- [x] `CookieAttributes()` (sem argumentos) produz `domain=None, path="/",
  expired=False`.
- [x] `StepResponse(status_code=200).cookie_attributes == {}` (default
  vazio, não quebra nenhuma construção existente de `StepResponse` que não
  passa esse campo).
- [x] `StepResponse(status_code=200, cookies={"a": "1"}).model_dump_json()`
  inclui tanto `"cookies"` quanto `"cookie_attributes"` no JSON serializado
  (round-trip via `model_validate_json` preserva os dois campos).
- [x] Não-regressão: toda a suíte de testes que constrói `StepResponse`
  diretamente (`grep -rn "StepResponse(" tests/` — usado em
  `test_engine.py`, `test_replay_runner.py`, `test_replay_optimizer.py`,
  `test_curl_http_transport.py`, `test_har_parser.py`, `test_cookie_agent.py`
  e outros) continua passando sem alteração, já que o campo novo tem default.

---

## [T02] — `MitmAddon`: preservar atributos de `Set-Cookie` na captura ao vivo

**Depende de:** T01 (usa o shape `{"name", "value", "domain", "path",
"expired"}` que T03 vai consumir).
**Arquivos envolvidos:** `har_reproducer/reproduction/mitm_addon.py`
(`_response_cookies_list`).

**Contexto:** `response.cookies.items(multi=True)` do mitmproxy já devolve
`attrs` (dict com `domain`/`path`/`expires`/`max-age` já parseados) — hoje
esse método os recebe e descarta. Essa é a única fonte de dado que
efetivamente alimenta o jar (T05/T07-T09), já que o jar nunca é alimentado a
partir do HAR original (spec seção 3.1).

**Estado atual** (`mitm_addon.py:74-79`):
```python
@staticmethod
def _response_cookies_list(response: Response) -> List[Dict[str, str]]:
    cookies_list: List[Dict[str, str]] = []
    for name, (value, _attrs) in response.cookies.items(multi=True):
        cookies_list.append({"name": name, "value": value})
    return cookies_list
```

**Estado esperado depois:**
```python
from mitmproxy.net.http import cookies as mitm_cookies

@staticmethod
def _response_cookies_list(response: Response) -> List[Dict[str, Any]]:
    cookies_list: List[Dict[str, Any]] = []
    for name, (value, attrs) in response.cookies.items(multi=True):
        cookies_list.append({
            "name": name,
            "value": value,
            "domain": attrs.get("domain"),
            "path": attrs.get("path", "/"),
            "expired": mitm_cookies.is_expired(attrs),
        })
    return cookies_list
```
- ⚠️ Import de `mitmproxy.net.http.cookies` — módulo já disponível como
  dependência instalada (`pyproject.toml`, `mitmproxy>=11.1.3`); não
  reimplementar `is_expired` (spec seção 2).
- Assinatura de retorno muda de `List[Dict[str, str]]` para `List[Dict[str,
  Any]]` (o valor de `"expired"` é `bool`, não `str`) — ajustar o tipo de
  retorno declarado.

**Critérios de aceite:**
- [x] Uma resposta simulada com `Set-Cookie: a=1; Domain=.exemplo.com;
  Path=/api` produz `{"name": "a", "value": "1", "domain": ".exemplo.com",
  "path": "/api", "expired": False}`.
- [x] Uma resposta simulada com `Set-Cookie: a=1; Max-Age=0` produz
  `"expired": True`.
- [x] Uma resposta simulada com `Set-Cookie: a=1` (sem `Domain`/`Path`)
  produz `"domain": None, "path": "/"`.
- [x] Múltiplos `Set-Cookie` na mesma resposta produzem uma entrada por
  cookie (não-regressão do comportamento de multiplicidade já existente).
- [x] Não-regressão: `test_mitm_addon.py` (suíte já existente) continua
  passando; qualquer teste que hoje só verifica `{"name", "value"}` precisa
  ser ajustado pra também aceitar as chaves novas (não que elas estejam
  ausentes).

---

## [T03] — `HARParser.parse_entry`: construir `cookie_attributes` a partir do envelope

**Depende de:** T01, T02 (consome o shape que T02 produz).
**Arquivos envolvidos:** `har_reproducer/fs_io/har_parser.py`
(`parse_entry`).

**Contexto:** `HARParser.parse_entry` é usado tanto pra parsear o HAR
original (baseline/`BaselineDiff`) quanto pra ler de volta o envelope que o
`MitmAddon` escreve (via `CurlHttpTransport._try_read_capture`,
`curl_http_transport.py:72-80`) — é este segundo uso que alimenta o jar.

**Estado atual** (`har_parser.py:76-92`):
```python
res_headers: Dict[str, str] = {v["name"]: v["value"] for v in res_data.get("headers", [])}
res_cookies: Dict[str, str] = {c["name"]: c["value"] for c in res_data.get("cookies", [])}

res_content: Dict[str, Any] = res_data.get("content", {})
text: Optional[str] = res_content.get("text")
encoding: Optional[str] = res_content.get("encoding")

body: str = HARParser.decode_body(text or "", encoding)

response: StepResponse = StepResponse(
    status_code=res_data["status"],
    headers=res_headers,
    cookies=res_cookies,
    body=body,
    body_mime=res_content.get("mimeType"),
    redirect_url=res_data.get("redirectUrl")
)
```

**Estado esperado depois:**
```python
res_cookie_attributes: Dict[str, CookieAttributes] = {
    c["name"]: CookieAttributes(
        domain=c.get("domain"), path=c.get("path", "/"), expired=c.get("expired", False)
    )
    for c in res_data.get("cookies", [])
}
...
response: StepResponse = StepResponse(
    status_code=res_data["status"],
    headers=res_headers,
    cookies=res_cookies,
    cookie_attributes=res_cookie_attributes,
    body=body,
    body_mime=res_content.get("mimeType"),
    redirect_url=res_data.get("redirectUrl")
)
```
- ⚠️ Um HAR original exportado por navegador não tem a chave `expired` (tem
  `expires`, uma data) — `c.get("expired", False)` cai no default `False`
  nesse caso. Isso é aceito (spec seção 3.1): o jar nunca é alimentado a
  partir do HAR original, só da captura ao vivo (via T02), então esse
  contexto nunca chega a importar pro comportamento do jar. Não implementar
  parsing de `expires` (string ISO) nesta task — fora de escopo.
- Requests (`req_cookies`, linha 61) não ganham `cookie_attributes` — cookies
  de request não têm atributos de `Set-Cookie` pra preservar.

**Critérios de aceite:**
- [x] Parseando um envelope de captura (formato produzido por T02) com
  `{"name": "sess", "value": "x", "domain": ".exemplo.com", "path": "/",
  "expired": False}`, `step.response.cookie_attributes["sess"]` bate exatamente
  (`domain=".exemplo.com"`, `path="/"`, `expired=False`).
- [x] Parseando uma entry de HAR genuíno (cookies sem chave `expired`),
  `step.response.cookie_attributes[nome].expired == False` (default, sem
  levantar `KeyError`).
- [x] Uma entry sem nenhum cookie na resposta produz
  `cookie_attributes == {}`.
- [x] Não-regressão: `test_har_parser.py` (suíte existente) continua
  passando; `res_cookies`/`req_cookies` continuam com o mesmo shape
  `Dict[str, str]` de antes.

---

## [T04] — `RequestUrlScope`: utilitário `url → (host, port, path)`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/reproduction/request_url_scope.py`
(novo), `har_reproducer/reproduction/__init__.py` (export).

**Contexto:** `Engine`, `ReplayRunner` e `ReplayOptimizer` (T07-T09)
precisam, cada um, derivar `(host, port, path)` de uma URL — pra consultar o
jar e pra alimentá-lo. Extraído como componente único em vez de
reimplementado três vezes (guia de estilo: "duplicação de lógica vira
constante/coleção").

**Estado atual:** Não existe (`grep -rn "_url_parts\|RequestUrlScope"
har_reproducer/` não retorna nada).

**Estado esperado depois:**
```python
from typing import ClassVar, Dict, Tuple
from urllib.parse import urlparse, ParseResult

from har_reproducer.fs_io import Workspace
from har_reproducer.models import StepRequest


class RequestUrlScope:
    DEFAULT_PORT_BY_SCHEME: ClassVar[Dict[str, int]] = {"http": 80, "https": 443}

    @staticmethod
    def parts(url: str) -> Tuple[str, int, str]:
        parsed: ParseResult = urlparse(url)
        host: str = parsed.hostname or ""
        port: int = parsed.port or RequestUrlScope.DEFAULT_PORT_BY_SCHEME.get(parsed.scheme, 443)
        path: str = parsed.path or "/"
        return host, port, path

    @staticmethod
    def parts_for_step(workspace: Workspace, index: int) -> Tuple[str, int, str]:
        request: StepRequest = StepRequest.model_validate_json(
            workspace.request_file(index).read_text(encoding="utf-8")
        )
        return RequestUrlScope.parts(request.url)
```
- Exportado em `reproduction/__init__.py` (`__all__` + import), mesmo padrão
  dos demais componentes desse pacote.
- ⚠️ Suposição: `StepRequest.url`/o texto persistido em
  `workspace.request_file(index)` é sempre uma URL absoluta (garantido pelo
  schema HAR e por `HARParser.parse_entry`, que nunca relativiza a URL). Se
  `urlparse` devolver `hostname=None` (URL malformada, hipótese não
  observada em nenhum HAR real), `parts` devolve `host=""`, que nunca casa
  com nenhum escopo do jar — degrada pro comportamento de "cookie nunca
  definido" (T05), não lança exceção.

**Critérios de aceite:**
- [x] `RequestUrlScope.parts("https://exemplo.com/login")` →
  `("exemplo.com", 443, "/login")`.
- [x] `RequestUrlScope.parts("http://exemplo.com/login")` →
  `("exemplo.com", 80, "/login")`.
- [x] `RequestUrlScope.parts("https://exemplo.com:8443/api")` →
  `("exemplo.com", 8443, "/api")` (porta explícita tem prioridade sobre o
  default do scheme).
- [x] `RequestUrlScope.parts("https://exemplo.com")` (sem path) →
  `path == "/"`.
- [x] `RequestUrlScope.parts("https://[::1]:9000/x")` (IPv6 com colchetes) →
  host reconhecido corretamente (`urlparse` já resolve isso nativamente).
- [x] `RequestUrlScope.parts_for_step(workspace, index)` lê
  `workspace.request_file(index)`, faz o parse de `StepRequest` e devolve o
  mesmo resultado que `parts(request.url)` chamado diretamente.

---

## [T05] — `CookieJar`: estrutura em memória por escopo de domínio/porta/path

**Depende de:** T01 (usa `CookieAttributes`).
**Arquivos envolvidos:** `har_reproducer/session/cookie_jar.py` (novo),
`har_reproducer/session/__init__.py` (export).

**Contexto:** Núcleo da feature — alimentado por qualquer `StepResponse` já
lida (fresca ou cacheada) em `run`/`replay`/`optimize`, consultado antes de
montar o `--cookie` de cada request subsequente cujo escopo case. Sem
dependência de mitmproxy como processo — puro estado Python (spec seção 3.2).

**Estado atual:** Não existe.

**Estado esperado depois:**
```python
from http import cookiejar
from typing import Dict, NamedTuple

from har_reproducer.models import CookieAttributes


class CookieScope(NamedTuple):
    domain: str
    port: int
    path: str


class CookieJar:
    def __init__(self) -> None:
        self._cookies_by_scope: Dict[CookieScope, Dict[str, str]] = {}

    def reset(self) -> None:
        self._cookies_by_scope.clear()

    def feed(
            self, response_host: str, response_port: int,
            cookies: Dict[str, str], attributes: Dict[str, CookieAttributes],
    ) -> None:
        for name, value in cookies.items():
            attrs: CookieAttributes = attributes.get(name, CookieAttributes())
            scope: CookieScope = CookieScope(
                domain=attrs.domain or response_host, port=response_port, path=attrs.path,
            )
            if attrs.expired:
                self._cookies_by_scope.get(scope, {}).pop(name, None)
            else:
                self._cookies_by_scope.setdefault(scope, {})[name] = value

    def current(self, request_host: str, request_port: int, request_path: str) -> Dict[str, str]:
        merged: Dict[str, str] = {}
        for scope, cookies in self._cookies_by_scope.items():
            if self._matches(scope, request_host, request_port, request_path):
                merged.update(cookies)
        return merged

    @staticmethod
    def _matches(scope: CookieScope, request_host: str, request_port: int, request_path: str) -> bool:
        return (
            scope.port == request_port
            and CookieJar._domain_match(request_host, scope.domain)
            and request_path.startswith(scope.path)
        )

    @staticmethod
    def _domain_match(host: str, cookie_domain: str) -> bool:
        if cookiejar.domain_match(host, cookie_domain):
            return True
        return cookiejar.domain_match(host, cookie_domain.strip("."))
```
- Exportado em `session/__init__.py`.
- ⚠️ `_domain_match` é **portado** de `stickycookie.py:27-32` (não é
  `cookiejar.domain_match` cru — confirmado que `cookiejar.domain_match(
  "exemplo.com", ".exemplo.com")` sozinho devolve `False`; o wrapper tenta
  também `cookie_domain.strip(".")`). Não simplificar removendo o segundo
  `if`.
- ⚠️ `_matches` casa path por `startswith` — mesma imprecisão "crua" do
  `stickycookie` original (não implementa o algoritmo exato de path-match do
  RFC 6265). Limitação aceita, não uma omissão a corrigir nesta task (spec
  seções 1 e 5).
- ⚠️ Precedência entre dois escopos que colidem no mesmo nome de cookie: sem
  regra determinística — `current()` mescla por ordem de iteração do dict
  (ordem de primeira inserção da chave de escopo, não recência de feed).
  Limitação aceita (spec seção 1).

**Critérios de aceite:**
- [x] `feed("exemplo.com", 443, {"a": "1"}, {})` seguido de
  `current("exemplo.com", 443, "/")` → `{"a": "1"}`.
- [x] `feed` com `attributes={"a": CookieAttributes(domain=".exemplo.com")}`
  seguido de `current("sub.exemplo.com", 443, "/")` → inclui `"a"`
  (subdomínio casa) **e** `current("exemplo.com", 443, "/")` → também inclui
  `"a"` (domínio-base também casa, via o wrapper portado).
  `current("outro.com", 443, "/")` → não inclui `"a"`.
  `current("exemplo.com", 8443, "/")` → não inclui `"a"` (porta diferente).
- [x] `feed` de um cookie com `attrs.expired=True` remove esse nome do
  escopo correspondente — uma chamada `current` subsequente pro mesmo escopo
  não o inclui mais.
- [x] `current` de um escopo nunca alimentado devolve `{}` (não lança
  exceção).
- [x] `reset()` limpa todo o estado — `current` depois de `reset()` devolve
  `{}` mesmo pra escopos alimentados antes do reset.
- [x] `current("exemplo.com", 443, "/admin")` inclui um cookie alimentado
  com `path="/"` (path-match por prefixo — comportamento documentado, não
  RFC-exato).

---

## [T06] — `CookieJarCurlOverride`: sobrescrever `--cookie` de um curl já resolvido

**Depende de:** T05.
**Arquivos envolvidos:**
`har_reproducer/reproduction/cookie_jar_curl_override.py` (novo),
`har_reproducer/reproduction/__init__.py` (export).

**Contexto:** Recebe o texto de um `.curl.sh` já resolvido (placeholders de
extractor já substituídos por `SessionStore.render`) e sobrescreve o
`--cookie` com o estado atual do jar pro escopo daquela request — "o `.curl.
sh` é o piso, o jar sobrescreve quando sabe mais" (spec seção 3.4).

**Estado atual:** Não existe.

**Estado esperado depois:**
```python
import shlex
from typing import ClassVar, Dict, List

from har_reproducer.session import CookieJar


class CookieJarCurlOverride:
    COOKIE_FLAG: ClassVar[str] = "--cookie"
    LINE_CONTINUATION_ARTIFACT: ClassVar[str] = "\n"

    def __init__(self, cookie_jar: CookieJar) -> None:
        self.cookie_jar: CookieJar = cookie_jar

    def apply(self, curl_resolved: str, host: str, port: int, path: str) -> str:
        jar_cookies: Dict[str, str] = self.cookie_jar.current(host, port, path)
        if not jar_cookies:
            return curl_resolved

        tokens: List[str] = self._tokenize(curl_resolved)
        existing: Dict[str, str] = self._parse_cookie_tokens(tokens)
        merged: Dict[str, str] = {**existing, **jar_cookies}
        rebuilt: List[str] = self._replace_or_append_cookie_tokens(tokens, merged)
        return shlex.join(rebuilt)

    def _tokenize(self, curl_resolved: str) -> List[str]:
        return [token for token in shlex.split(curl_resolved) if token != self.LINE_CONTINUATION_ARTIFACT]

    def _parse_cookie_tokens(self, tokens: List[str]) -> Dict[str, str]:
        index: int = self._cookie_flag_index(tokens)
        if index is None:
            return {}
        return self._parse_cookie_string(tokens[index + 1])

    def _cookie_flag_index(self, tokens: List[str]) -> Optional[int]:
        return tokens.index(self.COOKIE_FLAG) if self.COOKIE_FLAG in tokens else None

    @staticmethod
    def _parse_cookie_string(cookie_string: str) -> Dict[str, str]:
        pairs: Dict[str, str] = {}
        for part in cookie_string.split(";"):
            if "=" not in part:
                continue
            key, value = part.strip().split("=", 1)
            pairs[key] = value
        return pairs

    @staticmethod
    def _format_cookie_string(cookies: Dict[str, str]) -> str:
        return "; ".join(f"{key}={value}" for key, value in cookies.items())

    def _replace_or_append_cookie_tokens(self, tokens: List[str], merged: Dict[str, str]) -> List[str]:
        formatted: str = self._format_cookie_string(merged)
        index: Optional[int] = self._cookie_flag_index(tokens)
        if index is None:
            return tokens + [self.COOKIE_FLAG, formatted]
        return tokens[:index + 1] + [formatted] + tokens[index + 2:]
```
- Exportado em `reproduction/__init__.py`.
- ⚠️ **`shlex.split` não implementa a semântica real de continuação de
  linha do bash**: `CurlGenerator.generate` junta partes com `" \\\n
  "` (`curl_generator.py:17`), e `shlex.split` sobre esse padrão produz um
  token literal `"\n"` isolado entre cada par de partes — confirmado
  rodando `shlex.split('a \\\n   b')` → `['a', '\n', 'b']`. `_tokenize`
  **tem** que filtrar esses artefatos antes de qualquer parsing/
  reconstrução, senão o comando reconstruído carrega argumentos espúrios e
  quebra a execução real do curl.
- ⚠️ Tokenizar via `shlex.split` (que respeita quoting) é o que evita que a
  substring `--cookie` dentro do payload de `--data-binary` seja confundida
  com a flag real — ela permanece presa dentro do token único e citado do
  body. Não usar regex de texto livre sobre a string crua.
- ⚠️ `shlex.join` reconstrói o comando como **uma única linha**, sem as
  continuações `\` de formatação do `.curl.sh` original — isso é cosmético
  (o `bash -c` que `CurlHttpTransport` usa executa uma linha só igual a um
  comando multi-linha com continuação). O arquivo `.curl.sh` em disco nunca
  é reescrito por este componente, só a string em memória repassada a
  `http_transport.send_request`.
- Se o jar não tiver nada pro escopo (`jar_cookies` vazio), devolve o texto
  original **sem tokenizar** (early return antes do `shlex.split`) —
  preserva a formatação original de qualquer request que o jar não afeta.

**Critérios de aceite:**
- [x] Curl sem `--cookie` nenhum, jar com `{"sess": "x"}` pro escopo → o
  resultado tem um `--cookie 'sess=x'` novo inserido.
- [x] Curl com `--cookie 'a=1; b=2'`, jar com `{"a": "9"}` pro escopo → o
  resultado tem `--cookie` com `a=9` (jar vence) e `b=2` preservado (chave
  que o jar não tem, mantém o valor original).
- [x] Curl com `--data-binary '{"cmd": "--cookie fake"}'`, jar com algo pro
  escopo → o `--data-binary` do resultado continua com o payload original
  intacto (a substring `--cookie` dentro do JSON não é confundida com a
  flag real, nem duplicada, nem removida).
- [x] Curl gerado no formato multi-linha real de `CurlGenerator.generate`
  (com as continuações `\`), passado por `apply` com jar não-vazio → o
  resultado, quando executado via `bash -c` de verdade num teste de
  integração local, recebe exatamente os argumentos esperados (sem tokens
  `\n` espúrios) — validar com um script auxiliar que imprime `argv`
  recebido, não só inspecionar a string.
- [x] Jar vazio pro escopo da request → `apply` devolve a string de entrada
  **idêntica**, byte a byte (early return, sem tokenizar).

---

## [T07] — `Engine`/`EngineFactory`: aplicar e alimentar o jar no modo `run`

**Depende de:** T02, T04, T05, T06.
**Arquivos envolvidos:** `har_reproducer/engines/engine.py` (`Engine`),
`har_reproducer/engines/construction/engine_factory.py` (`EngineFactory.create`).

**Contexto:** `Engine._reproduce` é um laço único e sequencial do primeiro ao
último step do HAR — sem conceito de "tentativa", então o jar só cresce (ou
perde cookie expirado) na ordem certa, como um navegador real.

**Estado atual** (`engine.py:18-42, 143-152`):
```python
def __init__(
        self, har_path, workspace, session_store, tracker, token_resolver,
        skip_evaluator, retry_policy, validator, comparator, success_criteria, http_transport,
) -> None:
    ...
    self.http_transport: Optional[HttpTransport] = http_transport

def execute_step(self, step: Step) -> StepResponse:
    return self.retry_policy.execute(
        step.index, lambda: self._attempt_step(step), lambda response: self.handle_recovery(step.index, response)
    )

def _attempt_step(self, step: Step) -> StepResponse:
    assert self.http_transport is not None
    curl_literal: str = self.session_store.render(step.analysis.curl_template)
    response: StepResponse = self.http_transport.send_request(curl_literal, step.index)
    return response
```

**Estado esperado depois:**
- `Engine.__init__` ganha dois parâmetros novos: `cookie_jar: CookieJar`,
  `cookie_jar_curl_override: CookieJarCurlOverride` (guardados como atributos
  tipados, como todo o resto do construtor).
- `_attempt_step` aplica o override e alimenta o jar **dentro da própria
  função** (não depois que `execute_step`/`retry_policy.execute` retorna —
  `StepRetryPolicy.execute`, `step_retry_policy.py:9-21`, pode chamar
  `_attempt_step` até 2 vezes e só devolve a última resposta ao chamador):
  ```python
  def _attempt_step(self, step: Step) -> StepResponse:
      assert self.http_transport is not None
      curl_literal: str = self.session_store.render(step.analysis.curl_template)
      host, port, path = RequestUrlScope.parts(step.request.url)
      curl_with_jar: str = self.cookie_jar_curl_override.apply(curl_literal, host, port, path)
      response: StepResponse = self.http_transport.send_request(curl_with_jar, step.index)
      self.cookie_jar.feed(host, port, response.cookies, response.cookie_attributes)
      return response
  ```
- `EngineFactory.create` (`engine_factory.py:61-99`) constrói `CookieJar()` e
  `CookieJarCurlOverride(cookie_jar)` (uma vez por chamada de `create`, junto
  com os demais colaboradores) e os repassa a `engine_cls(...)` — para
  **ambos** `Engine` e `DryEngine` (que ignora esses atributos, já que
  `DryEngine.execute_step` sobrescreve o método inteiro e nunca chama
  `_attempt_step`, mas herda o mesmo `__init__` de `Engine`).
- Nenhum reset é necessário — execução única e sequencial.

**Critérios de aceite:**
- [x] Dois steps consecutivos: o primeiro devolve uma resposta com
  `Set-Cookie: sess=abc`; o segundo tem `--cookie 'sess=old'` fixo no
  `curl_template` gerado — depois da mudança, a request enviada de fato pro
  segundo step carrega `sess=abc`, não `sess=old` (teste de integração com
  um `HttpTransport` fake que grava o texto do curl recebido).
- [x] Um step cujo `curl_template` não tem `--cookie` nenhum, mas o jar já
  tem cookie pro escopo daquele host: a request enviada ganha um `--cookie`
  novo.
- [x] Retry (`StepRetryPolicy`): se a primeira tentativa de um step (que
  dispara recuperação) já vier com `Set-Cookie`, a segunda tentativa do
  mesmo step já usa esse valor no jar.
- [x] Não-regressão: `test_engine.py` (suíte existente) continua passando —
  ajustar a construção de `Engine` no teste pra passar os dois novos
  parâmetros (`grep -c "Engine(" tests/unit/test_engine.py` → 1 site).
  `test_engine_factory.py` idem, ajustado pra verificar que `create()`
  repassa `cookie_jar`/`cookie_jar_curl_override` ao `engine_cls`.
- [x] Um HAR sem nenhum `Set-Cookie` em nenhuma resposta: comportamento do
  `run` idêntico ao de antes da mudança (jar sempre vazio, `apply` sempre
  early-return).

---

## [T08] — `ReplayRunner`: aplicar e alimentar o jar no modo `replay`

**Depende de:** T02, T04, T05, T06.
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py`
(`ReplayRunner`).

**Contexto:** `_run_step`/`attempt()` é o ponto de render+envio de cada step
em qualquer um dos 4 modos de replay (`all`/`slice`/`smart`/`list`) — todos
convergem em `execute_schedule` → `_run_step`.

**Estado atual** (`replay_runner.py:19-43, 96-110`):
```python
def __init__(
        self, workspace, curl_token_comment, session_store, http_transport, replay_token_resolver,
        retry_policy, comparator, run_id, replay_run_dir, res_refer_dir, original_responses_dir,
) -> None:
    ...

def _run_step(self, index: int, schedule: Set[int], annotate: bool = True) -> StepResponse:
    curl_text: str = self.workspace.curl_file(index).read_text(encoding="utf-8")

    def attempt() -> StepResponse:
        static_token_ids, fallback_token_ids = self.replay_token_resolver.resolve(
            curl_text, schedule, self.replay_run_dir, self.res_refer_dir, self.original_responses_dir
        )
        if annotate and static_token_ids:
            self._annotate_static_tokens(index, static_token_ids)
        if annotate and fallback_token_ids:
            self._annotate_fallback_tokens(index, fallback_token_ids)
        curl_resolved: str = self.session_store.render(curl_text)
        return self.http_transport.send_request(curl_resolved, index)
    ...
```

**Estado esperado depois:**
- `ReplayRunner.__init__` ganha `cookie_jar: CookieJar`,
  `cookie_jar_curl_override: CookieJarCurlOverride` como novos parâmetros
  (atributos tipados, mesmo padrão do resto do construtor).
- `attempt()` aplica o override e alimenta o jar (mesmo motivo do T07 — pode
  ser chamada mais de uma vez por `StepRetryPolicy`):
  ```python
  def attempt() -> StepResponse:
      static_token_ids, fallback_token_ids = self.replay_token_resolver.resolve(
          curl_text, schedule, self.replay_run_dir, self.res_refer_dir, self.original_responses_dir
      )
      if annotate and static_token_ids:
          self._annotate_static_tokens(index, static_token_ids)
      if annotate and fallback_token_ids:
          self._annotate_fallback_tokens(index, fallback_token_ids)
      curl_resolved: str = self.session_store.render(curl_text)
      host, port, path = RequestUrlScope.parts_for_step(self.workspace, index)
      curl_with_jar: str = self.cookie_jar_curl_override.apply(curl_resolved, host, port, path)
      response: StepResponse = self.http_transport.send_request(curl_with_jar, index)
      self.cookie_jar.feed(host, port, response.cookies, response.cookie_attributes)
      return response
  ```
- Nenhum reset é necessário aqui: `run_all`/`run_slice`/`run_smart`/
  `run_list` fazem, cada um, uma única chamada a `execute_schedule` por
  invocação de CLI — mesmo pulando steps, o jar refletir exatamente os
  cookies que um navegador teria se pulasse os mesmos steps é o
  comportamento correto (spec seção 3.6).

**Critérios de aceite:**
- [x] `run_smart`/`run_slice` pulando um step intermediário que originalmente
  setava um cookie usado por um step posterior no schedule: se o step que
  seta o cookie **está** no schedule computado, o cookie propaga
  corretamente pro step posterior.
- [x] Mesma verificação de retry do T07, agora em `ReplayRunner`.
- [x] Não-regressão: `test_replay_runner.py` (suíte existente) continua
  passando — ajustar o único site de construção de `ReplayRunner`
  (`grep -c "ReplayRunner(" tests/unit/test_replay_runner.py` → 1) pra
  passar os dois novos parâmetros.
- [x] Um `.curl.sh` cujo `--cookie` já está correto (nenhum cookie no jar
  pro escopo): comportamento idêntico ao de antes da mudança.

---

## [T09] — `ReplayOptimizer`: jar isolado por tentativa, alimentado do backbone antes do tráfego

**Depende de:** T04, T05, T06, T08 (compartilha o `CookieJar` do
`ReplayRunner`).
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py`
(`ReplayOptimizer`).

**Contexto:** Único modo que precisa de tratamento especial: o mesmo
`schedule_executor` (`ReplayRunner`) atravessa **todas as tentativas** de uma
busca de `optimize`, e respostas servidas por `_backbone_response_cache` não
passam por `_run_step` (não alimentam o jar por conta própria). ⚠️ A ordem
importa: o jar tem que estar populado com os cookies do backbone **antes**
de `_execute_raw` mandar qualquer tráfego novo desta tentativa — alimentar
só depois deixaria toda tentativa de fase 2 rodar com o jar vazio (spec
seção 3.7, correção sobre uma versão anterior desta spec que tinha essa
ordem invertida).

**Estado atual** (`replay_optimizer.py:20-31, 97-108`):
```python
def __init__(
        self, schedule_executor: ScheduleExecutor, metadata_store: SilentExtractorMetadataStore,
        max_requests: int = 500,
) -> None:
    self.schedule_executor: ScheduleExecutor = schedule_executor
    self.metadata_store: SilentExtractorMetadataStore = metadata_store
    self.max_requests: int = max_requests
    self.requests_made: int = 0
    self.backbone: List[int] = []
    self._backbone_response_cache: Dict[int, StepResponse] = {}

def _execute(self, ordered_indexes: List[int], schedule: Set[int]) -> List[Tuple[int, StepResponse]]:
    refreshes: int = 0
    results: List[Tuple[int, StepResponse]] = self._execute_raw(ordered_indexes, schedule)
    while self._needs_reactive_refresh(results) and refreshes < self.MAX_REACTIVE_REFRESHES:
        refreshes += 1
        ...
        self._execute_raw(self.backbone, set(self.backbone), force_refresh=True)
        results = self._execute_raw(ordered_indexes, schedule)
    return results
```

**Estado esperado depois:**
- `ReplayOptimizer.__init__` ganha dois parâmetros novos: `workspace:
  Workspace`, `cookie_jar: CookieJar` (o **mesmo** `CookieJar` injetado no
  `ReplayRunner` que é passado como `schedule_executor` — garantido pela raiz
  de composição, T10). ⚠️ `optimize()` continua recebendo `workspace` como
  parâmetro do método (`replay_optimizer.py:35`, usado em
  `workspace.optimized_steps_file`) — **não remover** esse parâmetro nem
  tentar unificar com `self.workspace`; são o mesmo objeto na prática (só a
  raiz de composição garante isso), manter os dois é a mudança de menor
  raio de impacto (evita alterar a assinatura pública de `optimize()`, que
  tem 9 call sites de teste).
- `_execute` reseta o jar e o realimenta a partir do backbone cacheado
  **antes** de `_execute_raw`:
  ```python
  def _execute(self, ordered_indexes: List[int], schedule: Set[int]) -> List[Tuple[int, StepResponse]]:
      self.cookie_jar.reset()
      self._feed_cookie_jar_from_backbone_cache()
      refreshes: int = 0
      results: List[Tuple[int, StepResponse]] = self._execute_raw(ordered_indexes, schedule)
      while self._needs_reactive_refresh(results) and refreshes < self.MAX_REACTIVE_REFRESHES:
          refreshes += 1
          ...
          self._execute_raw(self.backbone, set(self.backbone), force_refresh=True)
          self.cookie_jar.reset()
          self._feed_cookie_jar_from_backbone_cache()
          results = self._execute_raw(ordered_indexes, schedule)
      return results

  def _feed_cookie_jar_from_backbone_cache(self) -> None:
      for index in sorted(self.backbone):
          response: Optional[StepResponse] = self._backbone_response_cache.get(index)
          if response is None:
              continue
          host, port, _ = RequestUrlScope.parts_for_step(self.workspace, index)
          self.cookie_jar.feed(host, port, response.cookies, response.cookie_attributes)
  ```
- Nenhuma alimentação adicional depois de `_execute_raw`: `ReplayRunner.
  attempt()` (T08) já alimenta o jar internamente a cada resposta obtida ao
  vivo — os steps de `ordered_indexes` que passam por `execute_schedule`
  nesta tentativa se alimentam sozinhos, em ordem, à medida que são
  enviados. A pré-alimentação cobre exatamente o que `_run_step` não
  alcança: índices do backbone que são cache hit.
- `_run_phase1` (`self._execute(self.backbone, set(self.backbone))`) cai no
  mesmo fluxo sem mudança adicional — primeira chamada, cache vazio, nada é
  pré-alimentado, todo o backbone roda ao vivo via `execute_schedule`,
  alimentando o jar em ordem ascendente.

**Critérios de aceite:**
- [x] Uma tentativa de fase 2 que remove um candidato do schedule (função
  `trial` em `_reduce_anchors`) e cujo êxito depende de um cookie que **só**
  o candidato removido estabelecia: a tentativa reduzida falha de verdade
  (o jar, resetado, não carrega mais aquele cookie) — não passa por
  contaminação de uma tentativa anterior.
- [x] Uma tentativa cujo êxito depende de um cookie estabelecido por um step
  do **backbone** (não por `ordered_indexes`): o curl da primeira request de
  `ordered_indexes` nesta tentativa já sai com esse cookie aplicado (jar
  pré-alimentado antes de `_execute_raw`, não depois).
- [x] Refresh reativo (`_needs_reactive_refresh`): depois do backbone ser
  reexecutado com `force_refresh=True`, a tentativa seguinte de
  `ordered_indexes` usa os cookies do backbone **recém-reexecutado**, não os
  da versão anterior.
- [x] Não-regressão: `test_replay_optimizer.py` (suíte existente, 39
  chamadas ao helper `_optimizer(...)` — grep confirma esse é o único ponto
  de construção no arquivo de teste) — ajustar `_optimizer` pra construir e
  passar `workspace`/`cookie_jar` (usar `tmp_path` já disponível como
  fixture do pytest onde a assinatura do teste ainda não o recebe); os 9
  call sites de `.optimize(workspace, ...)` **não mudam** (assinatura do
  método intacta).
- [x] Um `optimize` sem nenhum `Set-Cookie` em nenhuma resposta do fluxo:
  resultado do schedule reduzido idêntico ao de antes da mudança.

---

## [T10] — `cli_handlers`: raiz de composição — instanciar e compartilhar `CookieJar` entre `ReplayRunner` e `ReplayOptimizer`

**Depende de:** T08, T09.
**Arquivos envolvidos:** `har_reproducer/cli/cli_handlers.py`
(`_build_replay_runner`, `handle_replay`, `handle_optimize`).

**Contexto:** Fio de injeção que garante que `ReplayRunner` e
`ReplayOptimizer` enxerguem exatamente a **mesma instância** de `CookieJar`
— sem isso, é fácil instanciar dois jars diferentes por engano e a feature
inteira vira no-op silencioso (T09 depende disto). `handle_run` não precisa
de mudança aqui — a construção do jar pro modo `run` já foi resolvida
inteiramente dentro de `EngineFactory.create` (T07).

**Estado atual** (`cli_handlers.py:217-249, 135-168`):
```python
@staticmethod
def _build_replay_runner(
        workspace, orchestrator, run_id, res_refer_dir, script_executor, sleeper,
        metadata_store_factory: Type[ExtractorMetadataStore] = ExtractorMetadataStore,
) -> ReplayRunner:
    session_store: SessionStore = SessionStore()
    ...
    return ReplayRunner(
        workspace=workspace, curl_token_comment=curl_token_comment, session_store=session_store,
        http_transport=http_transport, replay_token_resolver=replay_token_resolver,
        retry_policy=retry_policy, comparator=comparator, run_id=run_id,
        replay_run_dir=workspace.replay_run_dir(run_id), res_refer_dir=res_refer_dir,
        original_responses_dir=workspace.original_responses,
    )

def handle_optimize(self, args: Namespace) -> bool:
    ...
    runner: ReplayRunner = self._build_replay_runner(
        workspace, orchestrator, run_id, res_refer_dir, script_executor, sleeper,
        metadata_store_factory=SilentExtractorMetadataStore,
    )
    ...
    optimizer: ReplayOptimizer = ReplayOptimizer(
        schedule_executor=runner, metadata_store=SilentExtractorMetadataStore(workspace),
        max_requests=args.max_requests,
    )
```

**Estado esperado depois:**
- `_build_replay_runner` ganha `cookie_jar: CookieJar`,
  `cookie_jar_curl_override: CookieJarCurlOverride` como novos parâmetros,
  repassados direto ao `ReplayRunner(...)`.
- `handle_replay` constrói `CookieJar()`/`CookieJarCurlOverride(cookie_jar)`
  **antes** de chamar `_build_replay_runner` e os passa como argumento (não
  precisa reusar em mais nada nesse comando, mas evita instanciar por
  construtor com default).
- `handle_optimize` faz o mesmo, e **passa a mesma instância** de
  `cookie_jar` também pro `ReplayOptimizer(...)`:
  ```python
  cookie_jar: CookieJar = CookieJar()
  cookie_jar_curl_override: CookieJarCurlOverride = CookieJarCurlOverride(cookie_jar)
  runner: ReplayRunner = self._build_replay_runner(
      workspace, orchestrator, run_id, res_refer_dir, script_executor, sleeper,
      cookie_jar, cookie_jar_curl_override,
      metadata_store_factory=SilentExtractorMetadataStore,
  )
  ...
  optimizer: ReplayOptimizer = ReplayOptimizer(
      schedule_executor=runner, metadata_store=SilentExtractorMetadataStore(workspace),
      max_requests=args.max_requests, workspace=workspace, cookie_jar=cookie_jar,
  )
  ```

**Critérios de aceite:**
- [x] `handle_optimize`: o objeto `cookie_jar` passado pro
  `ReplayOptimizer(...)` é literalmente (`is`) o mesmo objeto que
  `runner.cookie_jar` (o `ReplayRunner` construído por
  `_build_replay_runner`) — teste de integração com `id()`/`is` explícito,
  não só igualdade de valor.
- [x] `handle_replay` (sem `optimize`): `run_all`/`run_slice`/`run_smart`/
  `run_list` continuam funcionando (teste e2e via `tests/golden/replay_*`
  já existente) com o jar sempre presente, mesmo que vazio na maioria dos
  casos (nenhuma regressão de comportamento pra HARs sem cookie dinâmico).
- [x] Não-regressão: nenhuma das golden trees de `tests/golden/replay_*`/
  `tests/golden/run_*` muda de conteúdo pra um HAR de fixture sem
  `Set-Cookie` nenhum (jar sempre vazio nesse caso — comportamento
  observável idêntico ao de antes da feature).
- [x] `py_compile`/import de `cli_handlers.py` sem erro depois da mudança
  (checagem de compilação, já que é um arquivo grande com várias raízes de
  composição — garantir que nenhuma outra raiz foi afetada por engano).
