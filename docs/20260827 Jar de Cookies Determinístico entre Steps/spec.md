# Spec — Jar de Cookies Determinístico entre Steps

## 0. Sumário e glossário

Hoje, um cookie só é rastreado como valor dinâmico se o `BaselineDiff`
detectar que ele **mudou de valor** em relação ao primeiro step do HAR
(baseline). Isso deixa de fora o caso mais comum de cookie de sessão: um
cookie já estabelecido antes ou no primeiro request da gravação, que
permanece com o mesmo valor durante toda a captura — porque a gravação foi
feita a partir de uma sessão já autenticada, e nada nela invalida ou renova
esse cookie. Como esse cookie nunca "muda" dentro da amostra, ele nunca vira
candidato a token dinâmico, e o sistema o trata como literal do HAR para
sempre. Isso é uma falha silenciosa: contra um servidor real, o valor de
sessão que ele emite na prática quase certamente difere do que foi gravado, e
qualquer step que dependa desse cookie tende a falhar sem que o pipeline de
descoberta de tokens veja motivo pra suspeitar de nada.

Esta etapa introduz um **jar de cookies** — componente novo, em Python puro,
sem depender de observação passiva de tráfego pelo mitmproxy — que replica o
comportamento padrão de propagação de cookies de um navegador: toda resposta
já lida (fresca ou reaproveitada de cache) alimenta o jar com os cookies que
ela declarou via `Set-Cookie` **e seus atributos** (`Domain`, `Path`,
expiração), e toda request subsequente cujo host/porta/path casem com o
escopo de um cookie conhecido tem esse cookie aplicado por cima do que o HAR
gravou. Isso vale para os três modos que fazem requisição de rede real:
`run`, `replay` e `optimize`. Em `optimize`, o jar precisa ser reconstruído do
zero a cada tentativa de schedule que a busca binária de âncoras testa, **e
realimentado a partir do backbone antes de qualquer tráfego novo ser
enviado** — do contrário, cookies obtidos numa tentativa vazariam para a
tentativa seguinte (ou, pior, o jar ficaria vazio bem na hora em que a
tentativa mais precisa dele) e produziriam resultado incorreto sobre quais
steps são de fato necessários, o que vai contra o próprio objetivo do
`optimize` (achar a menor sequência que ainda funciona de verdade).

Glossário:

- **Jar de cookies**: estrutura em memória que guarda, por escopo
  (domínio + porta + path), o valor mais recente conhecido de cada cookie —
  alimentada por toda resposta HTTP lida (fresca ou cacheada) e consultada
  antes de cada request subsequente cujo destino case com aquele escopo.
- **Escopo de um cookie**: a tripla (domínio, porta, path) sob a qual um
  cookie se aplica — derivada dos atributos `Domain`/`Path` do `Set-Cookie`
  quando presentes, com o host/path da própria resposta como padrão quando
  ausentes (mesma regra que um navegador aplica).
- **Alimentar (feed)**: atualizar o jar com os cookies e atributos
  (`Set-Cookie`) de uma resposta específica — remove do jar o que veio
  marcado como expirado.
- **Aplicar (override)**: sobrescrever o `--cookie` de uma request já
  resolvida (placeholders de extractor já substituídos) com o estado atual do
  jar para o escopo daquela request.
- **Tentativa (attempt)**: uma chamada do `ReplayOptimizer` que testa se um
  subconjunto específico de steps (schedule) ainda alcança o critério de
  sucesso. Cada tentativa precisa de um jar isolado das demais, e realimentado
  a partir do backbone **antes** de qualquer request da própria tentativa ser
  enviada.
- **Backbone**: conjunto de steps entre `from_index` e a penúltima âncora,
  cujas respostas o `ReplayOptimizer` já cacheia (introduzido em
  `docs/20260825 Cache de Respostas do Backbone na Otimização de Replay`) para
  evitar reexecução repetida entre tentativas.

## 1. Objetivo

**Problema atual:** `BaselineDiff._diff_cookies` (seção 2) só marca um cookie
como candidato a token dinâmico se o valor no step atual for diferente do
valor da mesma chave no primeiro step do HAR. Um cookie de sessão
estabelecido antes da gravação começar, e que nunca muda dentro dela, não
passa por esse filtro — nunca vira candidato, nunca tem origem rastreada, e o
`CurlGenerator` o embute como literal fixo em todo `.curl.sh` que o usa.
Contra um servidor real, esse literal quase certamente está errado (o
servidor real emite um valor de sessão próprio), e não há fallback melhor
hoje — o valor gravado é tudo o que existe.

**Custo de não resolver:** qualquer execução de `run`/`replay`/`optimize`
contra o servidor real tende a falhar de forma pouco óbvia sempre que depende
de um desses cookies "aparentemente estáticos". Para o `optimize`
especificamente, isso é mais grave: um schedule reduzido pode "passar" na
validação só porque, por coincidência, o valor literal do HAR ainda satisfaz o
servidor durante aquela execução específica — tornando a conclusão de "menor
sequência que funciona" não confiável.

**O que esta mudança cobre:** um jar de cookies determinístico, alimentado
pelas respostas que os três modos (`run`, `replay`, `optimize`) já leem hoje —
sem heurística de diff, sem busca por valor literal, sem LLM — que passa a ser
a fonte de verdade para o cookie enviado em cada request subsequente cujo
escopo (domínio/porta/path) case com o do cookie. O escopo é respeitado de
verdade (não simplificado por host exato), e cookies marcados como expirados
(`Max-Age=0`/`Expires` no passado) são removidos do jar — ver seção 3.1 sobre
por que isso não exige heurística nova, só parar de descartar informação que
o mitmproxy e o próprio HAR já fornecem.

**Fora de escopo nesta etapa:**

- **Precedência determinística entre dois escopos que casam simultaneamente e
  têm cookie do mesmo nome** (ex.: um cookie `session` válido em `/` e outro
  `session` válido em `/admin`, ambos vigentes ao mesmo tempo, ambos casando
  com uma request pra `/admin`). O jar aplica os dois sem uma regra de
  precedência por recência ou especificidade de path — qual valor "vence" na
  colisão depende da ordem de iteração interna do jar, não de qual foi
  alimentado por último nem de qual path é mais específico. Isso é uma
  simplificação aceita: o próprio addon `stickycookie` do mitmproxy, usado
  como referência nesta spec, tem exatamente essa limitação — concatena os
  dois pares no header em vez de resolver a precedência (`stickycookie.py:91`,
  com o comentário `# FIXME: we need to formalise this...` no próprio código
  deles). Revisar se um HAR real expuser esse cenário (seção 6).
- **Casamento de path por prefixo simples, não pelo algoritmo exato do RFC
  6265.** `CookieJar._matches` usa `request_path.startswith(scope.path)` —
  mesma checagem "crua" que `stickycookie.py:87` usa. Isso significa que um
  cookie com `Path=/foo` vaza também para `/foobar`/`/foobiz`, o que um
  navegador real (que exige que o path termine em `/` ou que o próximo
  caractere do request-path seja `/`) nunca faria. Herdado deliberadamente
  junto com o resto da lógica portada de `stickycookie.py` (seção 3.2) — não
  é um esquecimento, é a mesma simplificação que a ferramenta de referência
  desta spec também adota.
- **Remover `CookieAgent`/o rastreamento de cookie via `TokenTracker`/
  `BaselineDiff`.** Fica como está nesta etapa. O jar passa a sobrescrever o
  `--cookie` resolvido sempre que tiver algo mais recente para aquele escopo,
  tornando o rastreamento de cookie redundante na prática para a maioria dos
  casos — mas decidir removê-lo é assunto de uma spec futura, depois de
  validar o jar em produção.
- **Usar o addon nativo `stickycookie` do mitmproxy diretamente.**
  Considerado e descartado — ver seção 3.8. A lógica de casamento de domínio
  dele é **portada** (não importada) para dentro do `CookieJar` — ver seção
  3.2.

## 2. Componentes existentes reaproveitados

### `BaselineDiff._diff_cookies` — `har_reproducer/tracking/baseline_diff.py:32-38`

```python
@staticmethod
def _diff_cookies(step: Step, baseline: Step) -> Dict[str, str]:
    return {
        f"cookie:{key}": value
        for key, value in step.request.cookies.items()
        if baseline.request.cookies.get(key) != value
    }
```

Confirma o problema descrito na seção 1: comparação por mesma chave contra o
primeiro step do HAR (`baseline`, passado por `Engine._reproduce`,
`engines/engine.py:49`). Se o valor bate com o do baseline, o cookie nunca
entra no dict `diffs` e nunca vira `DynamicToken`.

### `MitmAddon._response_cookies_list` — `har_reproducer/reproduction/mitm_addon.py:74-79`

```python
@staticmethod
def _response_cookies_list(response: Response) -> List[Dict[str, str]]:
    cookies_list: List[Dict[str, str]] = []
    for name, (value, _attrs) in response.cookies.items(multi=True):
        cookies_list.append({"name": name, "value": value})
    return cookies_list
```

`response.cookies.items(multi=True)` do mitmproxy **já devolve** `attrs`
(dict com `domain`, `path`, `expires`/`max-age` já parseados pelo próprio
mitmproxy) — este método os recebe e descarta (`_attrs`, prefixo de
"não uso"). É o ponto exato onde a informação de escopo/expiração se perde
hoje na captura ao vivo — a única fonte que o jar de fato consome (ver nota
sobre `HARParser` logo abaixo).

### `HARParser.parse_entry` — `har_reproducer/fs_io/har_parser.py:55-94`

```python
req_cookies: Dict[str, str] = {c["name"]: c["value"] for c in req_data.get("cookies", [])}
...
res_cookies: Dict[str, str] = {c["name"]: c["value"] for c in res_data.get("cookies", [])}
```

Mesmo descarte, mas usado em dois contextos diferentes: (a) parsear o HAR
**original** (exportado por um navegador real, cujo schema HAR 1.2 traz cada
cookie com `expires` — uma string de data, **não** um booleano) para
construir o `baseline`/comparações de `BaselineDiff`; e (b) parsear o
**envelope que o `MitmAddon` escreve** durante a captura ao vivo (mesmo
formato de log, consumido de volta por
`CurlHttpTransport._try_read_capture`, `curl_http_transport.py:72-80`, que
reaproveita esta mesma função). ⚠️ O jar desta spec só é alimentado pela via
(b) — nenhum dos três modos (`run`/`replay`/`optimize`) alimenta o jar
diretamente a partir do HAR original (seção 3.1 detalha por quê isso é
seguro apesar dos dois contextos compartilharem a mesma função de parse).

### `mitmproxy.net.http.cookies.is_expired` — `.venv/lib/python3.12/site-packages/mitmproxy/net/http/cookies.py:348-362`

```python
def is_expired(cookie_attrs):
    exp_ts = get_expiration_ts(cookie_attrs)
    now_ts = time.time()
    if exp_ts is None:
        return False
    else:
        return exp_ts <= now_ts
```

Já lida com `Max-Age` e `Expires` (via `get_expiration_ts`, mesma biblioteca)
e já é dependência instalada do projeto (`pyproject.toml`, `mitmproxy>=11.1.3`)
— reaproveitado tal como está, sem reescrever lógica de expiração.

### Casamento de domínio de `stickycookie.py` — `.venv/lib/python3.12/site-packages/mitmproxy/addons/stickycookie.py:27-32`

```python
def domain_match(a: str, b: str) -> bool:
    if cookiejar.domain_match(a, b):
        return True
    elif cookiejar.domain_match(a, b.strip(".")):
        return True
    return False
```

⚠️ **Não é o `http.cookiejar.domain_match` puro da biblioteca padrão** — é um
wrapper que também tenta o domínio sem o `.` inicial. Isso importa:
`cookiejar.domain_match("exemplo.com", ".exemplo.com")` sozinho devolve
`False` (confirmado rodando o interpretador) — ou seja, um cookie declarado
com `Domain=.exemplo.com` por uma resposta do próprio `exemplo.com` (sem
subdomínio) não bateria numa request subsequente para esse mesmo
`exemplo.com` usando só a função crua da stdlib. O wrapper do mitmproxy é que
resolve isso, tentando também `b.strip(".")`. Esta spec **porta esse
wrapper** (não a função crua) para dentro do `CookieJar` — seção 3.2.

### `StepRetryPolicy.execute` — `har_reproducer/reproduction/step_retry_policy.py:9-21`

```python
def execute(
        self, step_index: int,
        attempt_fn: Callable[[], StepResponse], recovery_fn: Callable[[StepResponse], bool],
) -> StepResponse:
    for attempt in range(self.MAX_STEP_ATTEMPTS):
        response: StepResponse = attempt_fn()
        is_last_attempt: bool = attempt == self.MAX_STEP_ATTEMPTS - 1
        if not is_last_attempt and recovery_fn(response):
            print(f"Recovery successful for step {step_index}. Retrying request...")
            continue
        return response
```

Chama `attempt_fn()` até `MAX_STEP_ATTEMPTS` (2) vezes, mas só devolve ao
chamador a resposta da **última** chamada — as respostas de tentativas
anteriores (inclusive uma que tenha definido um cookie relevante antes de
falhar) nunca chegam a quem invocou `execute`. Isso importa para onde o jar é
alimentado (seções 3.5/3.6): tem que ser dentro de `attempt_fn`, não depois
que `execute` retorna, senão uma resposta intermediária com `Set-Cookie`
nunca alimenta o jar.

### `PlaceholderApplier._replace_in_cookies` — `har_reproducer/tracking/placeholder_applier.py:54-58`

```python
@staticmethod
def _replace_in_cookies(request: StepRequest, value: str, placeholder: str) -> None:
    for key, cookie_value in list(request.cookies.items()):
        if value in cookie_value:
            request.cookies[key] = cookie_value.replace(value, placeholder)
```

Único outro lugar do código que manipula `StepRequest.cookies` além de
`CurlGenerator`/`BaselineDiff`. Só substitui o **valor** por um placeholder de
extractor — a chave do cookie nunca muda. Compatível sem nenhuma mudança: o
merge do `CookieJarCurlOverride` (seção 3.4) mescla por chave depois que
`SessionStore.render` já substituiu o placeholder de volta por um valor
literal — o fato de o valor ter passado por um placeholder no meio do
caminho é invisível pro jar.

### `CurlGenerator._cookie_part` — `har_reproducer/reproduction/curl_generator.py:46-53`

Monta o `--cookie` uma única vez, em tempo de `run`, embutindo-o como texto
fixo no `.curl.sh` — com placeholders `{{extractor:<id>}}` nos valores
dinâmicos já rastreados. Essa string nunca muda depois; é gravada em disco
(`Workspace.curl_file`) e só tem os placeholders substituídos depois, por
`SessionStore.render`.

### `Engine._attempt_step` / `ReplayRunner._run_step` / `ReplayOptimizer._execute`/`_execute_raw`

Pontos de render+envio de cada modo (`engine.py:148-152`,
`replay_runner.py:96-126`, `replay_optimizer.py:97-133`) — descritos em
detalhe nas seções 3.5 a 3.7. `_execute`/`_execute_raw` do `ReplayOptimizer`
chama `execute_schedule` (que por sua vez chama `_run_step`) **até 5 vezes**
por tentativa no pior caso: 1 chamada inicial + até `MAX_REACTIVE_REFRESHES`
(2) iterações do laço de `_needs_reactive_refresh`, cada iteração fazendo uma
chamada de refresh do backbone (`force_refresh=True`) mais uma nova tentativa
— sempre através do **mesmo** `schedule_executor` (injetado como
`ReplayRunner` em `cli_handlers.py:149-152`) e do **mesmo** processo
`mitmdump` (`orchestrator.run(...)` envolve `optimizer.optimize(...)` inteiro,
`cli_handlers.py:162-166`). Índices que já estão em
`_backbone_response_cache` **não** passam por `execute_schedule`/`_run_step`
nesta chamada — a resposta cacheada é reaproveitada sem gerar tráfego novo.
Isso é o que exige tratamento especial no jar (seção 3.7).

### `Workspace.request_file` — `har_reproducer/fs_io/workspace.py:46-47`

`Engine._persist_request_step` (`engine.py:107-108`) grava a `StepRequest`
completa (inclusive `.url`) nesse arquivo durante o `run`. `ReplayRunner` e
`ReplayOptimizer` podem ler esse arquivo pra obter a URL de cada step sem
precisar reparsear o texto do `.curl.sh`.

## 3. Decisões de arquitetura

### 3.1 Preservar atributos de `Set-Cookie` na captura ao vivo (widening aditivo)

**Estado atual:** `StepResponse.cookies: Dict[str, str]`
(`models/http.py:19`) guarda só nome→valor — usado hoje por `CookieAgent`
(`agents/cookie_agent.py:17-28`, `cookies.get(key)`) e por qualquer extractor
já gerado, que espera exatamente essa forma. `MitmAddon` descarta
`domain`/`path`/expiração antes desse dict existir (seção 2).

**Estado esperado:** um novo modelo aditivo, sem tocar `cookies:
Dict[str,str]` (zero impacto em `CookieAgent`/extractors existentes):

```python
class CookieAttributes(BaseModel):
    domain: Optional[str] = None
    path: str = "/"
    expired: bool = False
```

`StepResponse` ganha `cookie_attributes: Dict[str, CookieAttributes] =
Field(default_factory=dict)`.

`MitmAddon._response_cookies_list` passa a usar os `attrs` que já recebe:

```python
@staticmethod
def _response_cookies_list(response: Response) -> List[Dict[str, Any]]:
    cookies_list: List[Dict[str, Any]] = []
    for name, (value, attrs) in response.cookies.items(multi=True):
        cookies_list.append({
            "name": name,
            "value": value,
            "domain": attrs.get("domain"),
            "path": attrs.get("path", "/"),
            "expired": cookies.is_expired(attrs),
        })
    return cookies_list
```

`HARParser.parse_entry` passa a construir `res_cookie_attributes` ao lado de
`res_cookies`, lendo `c.get("domain")`, `c.get("path", "/")`, `c.get("expired",
False)` de cada item de `res_data["cookies"]`.

⚠️ **Isso serve apenas ao caminho da captura ao vivo (b), não ao HAR
original (a).** Um HAR genuíno exportado por navegador não tem a chave
`expired` (tem `expires`, uma data) — ao parsear o HAR original, `c.get(
"expired", False)` sempre cai no default `False`, mesmo que o `expires`
gravado já tenha passado. Isso é inofensivo porque **o jar nunca é
alimentado a partir do HAR original** (ele só recebe `StepResponse` de
respostas ao vivo — seções 3.5 a 3.7) — mas fica registrado aqui pra quem for
mexer em `HARParser` depois não assumir que os dois contextos produzem dado
equivalente.

⚠️ Isso não muda o **shape** de `cookies: Dict[str,str]` em lugar nenhum — é
puramente um campo novo, populado a partir de dado que já está disponível e
hoje é descartado. Nenhum extractor/teste que depende de
`response['cookies']` como string simples precisa mudar.

### 3.2 Novo componente `CookieJar`

`har_reproducer/session/cookie_jar.py` — chave por escopo
`(domain, port, path)`, mesmo formato de `TOrigin` do `stickycookie.py`
(seção 2), com o casamento de domínio **portado** (não importado) do wrapper
de `stickycookie.py:27-32`, não da função crua da stdlib:

```python
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

Sem dependência de mitmproxy como processo — puro estado em memória. `feed` é
chamado com `StepResponse.cookies`/`StepResponse.cookie_attributes` de
qualquer resposta lida (fresca ou cacheada); `current` é consultado antes de
montar o `--cookie` de cada request subsequente. `reset` só é usado pelo
`optimize` (seção 3.7).

⚠️ **Precedência entre escopos que colidem** (seção 1): `current()` mescla
por ordem de iteração do dict `_cookies_by_scope` (ordem de primeira
inserção de cada chave de escopo) — isso **não** equivale a "o último
alimentado vence"; é só a ordem em que os escopos foram descobertos pela
primeira vez. Documentado como limitação aceita, não uma garantia de
recência.

Razão de ser um componente à parte (e não um método dentro de
`SessionStore`): `SessionStore` resolve placeholders de extractor — um
mecanismo de identidade única por token (`token_id` → valor). O jar resolve
por escopo de URL — uma chave de domínio completamente diferente, sem relação
com `token_id`/`Extractor`. Misturar as duas dentro da mesma classe forçaria
`SessionStore` a saber sobre hosts/portas/paths, o que não é responsabilidade
dela hoje.

### 3.3 Novo componente `RequestUrlScope`

`har_reproducer/reproduction/request_url_scope.py` — utilitário único de
`url → (host, port, path)`, compartilhado por `Engine`, `ReplayRunner` e
`ReplayOptimizer` (seção 3.5-3.7). Extraído como componente próprio em vez de
reimplementado em cada uma das três classes (o que violaria "duplicação de
lógica vira constante/coleção" do guia de estilo). Também expõe
`parts_for_step`, que lê a URL persistida em `Workspace.request_file(index)`
(seção 2) — usado por `ReplayRunner` e `ReplayOptimizer`, que não têm a URL
em mãos diretamente (diferente do `Engine`, que já tem `step.request.url`):

```python
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

⚠️ Suposição implícita: `StepRequest.url` é sempre uma URL absoluta (com
scheme e host) — garantido pelo schema HAR (`req_data["url"]` é sempre
absoluta no formato HAR 1.2) e por `HARParser.parse_entry`, que nunca
relativiza a URL. Se `parsed.hostname` vier vazio (URL malformada, hipótese
não observada em nenhum HAR real até hoje), `parts` devolve host `""`, que
simplesmente nunca casa com nenhum escopo do jar — degrada para o
comportamento de "cookie nunca definido" (seção 5), não quebra.

### 3.4 Novo componente `CookieJarCurlOverride`

`har_reproducer/reproduction/cookie_jar_curl_override.py` — recebe o
`CookieJar` **por construtor** (não por parâmetro de método, consistente com
o padrão de dependência do guia de estilo já usado por `Engine`/
`ReplayRunner`):

```python
class CookieJarCurlOverride:
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
```

Recebe o texto do curl **já resolvido** (depois de `SessionStore.render`) e:

1. Tokeniza via `shlex.split` — respeita quoting, então uma substring
   `--cookie` dentro do payload de `--data-binary` (texto arbitrário do body
   original do HAR) nunca aparece como um token isolado, permanece presa
   dentro do token único do body. ⚠️ **`shlex.split` não implementa a
   semântica real de continuação de linha do bash**: o texto que
   `CurlGenerator.generate` produz usa `" \\\n     "` para separar partes
   (`curl_generator.py:17`), e `shlex.split` sobre esse padrão devolve um
   token literal `"\n"` isolado entre cada par de partes (confirmado
   rodando: `shlex.split('a \\\n   b')` → `['a', '\n', 'b']`) — um artefato
   da tokenização, não conteúdo real do comando. `_tokenize` filtra
   explicitamente esses tokens antes de qualquer outro processamento.
2. Localiza o token exato `"--cookie"` na lista já tokenizada/filtrada e lê o
   token seguinte como o valor atual (parseado em `chave=valor; chave=valor`)
   — ou um dict vazio, se a request original não tinha `--cookie` nenhum.
3. Mescla com `jar.current(host, port, path)` — **o jar sempre vence** em
   caso de mesma chave, porque ele reflete o que o servidor realmente
   respondeu nesta execução, e o texto gravado no `.curl.sh` reflete o que o
   HAR gravou (ou o que um extractor conseguiu inferir de uma amostra única).
4. Se o jar tiver cookies pra esse escopo e a request original **não** tinha
   `--cookie` nenhum, insere um par de tokens `["--cookie", "chave=valor;
   ..."]` novo — replicando fielmente o comportamento de um navegador, que
   sempre anexa os cookies que conhece pra um escopo, independente de a
   request "esperar" por eles ou não.
5. Reconstrói o comando a partir dos tokens finais via `shlex.join` (Python
   ≥ 3.8, já disponível — projeto roda em 3.12) — que re-quota corretamente
   cada token. ⚠️ **O resultado é uma única linha, sem as continuações `\`
   de formatação do `.curl.sh` original** — isso é puramente cosmético: o
   `bash -c` que `CurlHttpTransport` usa pra executar (`curl_http_transport.
   py:26-27`) roda uma linha só exatamente igual a um comando multi-linha com
   continuação. O arquivo `.curl.sh` em disco nunca é reescrito por este
   componente — só a string em memória que vai para
   `http_transport.send_request`.
6. Se o jar não tiver nada pra esse escopo, devolve o texto original **sem
   tokenizar/reconstruir** (early return antes do passo 1) — preserva
   exatamente a formatação original para qualquer request que o jar não
   afeta (a maioria, no caso comum de nenhum cookie relevante ainda visto).

⚠️ Isso muda o comportamento observável de "só usa o que está no `.curl.sh`"
para "usa o `.curl.sh` como piso, sobrescrito pelo jar quando o jar sabe
mais" — é a mudança central desta spec, não um efeito colateral.

### 3.5 Integração no modo `run` (`Engine`)

**Estado atual** (`engine.py:143-152`):

```python
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

**Estado esperado:** `Engine` recebe um `CookieJar` e um
`CookieJarCurlOverride` por construtor. `_attempt_step` aplica o override
depois do `render` e **alimenta o jar dentro da própria função** — não depois
que `execute_step`/`retry_policy.execute` retorna, porque
`StepRetryPolicy.execute` (seção 2) pode chamar `_attempt_step` mais de uma
vez e só devolve a última resposta ao chamador:

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

`self.cookie_jar_curl_override` já foi construído com `self.cookie_jar` (seção
3.4 — `CookieJarCurlOverride` recebe o jar por construtor, não por parâmetro
de `apply`); os dois são injetados como a mesma dupla de instâncias na raiz
de composição do `run` (`cli_handlers.handle_run`, seção 4).

Nenhum reset é necessário aqui: `_reproduce` (`engine.py:47-58`) é um único
laço sequencial, do primeiro ao último step do HAR, sem conceito de
"tentativa" — o jar só cresce (ou perde cookie expirado), na ordem certa,
exatamente como um navegador real acumularia cookies ao longo de uma única
sessão de navegação. Cada tentativa de reenvio de `StepRetryPolicy` também
aplica o jar corrente antes de enviar e o alimenta com o que recebeu de
volta, inclusive quando essa tentativa falha.

### 3.6 Integração no modo `replay` (`ReplayRunner`)

**Estado atual** (`replay_runner.py:96-110`): `_run_step` lê o `.curl.sh`,
resolve tokens, aplica `session_store.render`, envia.

**Estado esperado:** `ReplayRunner` recebe `CookieJar` e
`CookieJarCurlOverride` por construtor (mesmo padrão do `Engine`). Dentro de
`attempt()` (função interna de `_run_step`, linha 99-110) — pelo mesmo motivo
da seção 3.5 (`StepRetryPolicy` pode chamar `attempt()` mais de uma vez):

```python
def attempt() -> StepResponse:
    ...
    curl_resolved: str = self.session_store.render(curl_text)
    host, port, path = RequestUrlScope.parts_for_step(self.workspace, index)
    curl_with_jar: str = self.cookie_jar_curl_override.apply(curl_resolved, host, port, path)
    response: StepResponse = self.http_transport.send_request(curl_with_jar, index)
    self.cookie_jar.feed(host, port, response.cookies, response.cookie_attributes)
    return response
```

`RequestUrlScope.parts_for_step` (seção 3.3) lê `StepRequest.url` de
`workspace.request_file(index)` (seção 2) — não precisa reparsear o
`.curl.sh`. `self.workspace` já é atributo existente de `ReplayRunner`
(`replay_runner.py:33`), nenhuma dependência nova precisa ser adicionada
aqui.

Nenhum reset é necessário para o comando `replay` isolado: `run_all`/
`run_slice`/`run_smart`/`run_list` fazem, cada um, **uma única chamada** a
`execute_schedule` por invocação de CLI (`replay_runner.py:45-59`) — mesmo
quando o schedule pula steps (`smart`/`slice`/`list`), o jar refletir
exatamente os cookies que um navegador teria se ele também pulasse esses
mesmos steps é o comportamento **correto** para validar se aquele schedule
reduzido funciona — não é uma limitação, é a semântica desejada.

### 3.7 Integração no modo `optimize` (`ReplayOptimizer`)

Este é o único modo que precisa de tratamento especial, pelos dois motivos já
citados na seção 2: (a) o mesmo `schedule_executor`/jar atravessa **todas as
tentativas** de uma busca; (b) respostas servidas por
`_backbone_response_cache` não passam por `_run_step`, então não alimentam o
jar por conta própria.

**Estado atual** (`replay_optimizer.py:97-133`, reproduzido na seção 2): cada
tentativa (`_attempt`/`_confirm`/`_reduce_anchors`) chama `_execute`, que por
sua vez chama `_execute_raw` uma ou mais vezes (mais chamadas em caso de
`_needs_reactive_refresh`, até 5 no total).

**Estado esperado:**

1. `ReplayOptimizer` recebe, por construtor, um `workspace: Workspace` (novo
   parâmetro — hoje `ReplayOptimizer.__init__`, `replay_optimizer.py:20-28`,
   não guarda nenhum; `workspace` só chega como parâmetro do método
   `optimize()`, linha 35) e uma referência ao **mesmo** `CookieJar` usado
   pelo `ReplayRunner` que ele orquestra como `schedule_executor`.

   ⚠️ **Isso exige mudar a raiz de composição, não só declarar a intenção em
   prosa.** Hoje `cli_handlers._build_replay_runner`
   (`cli_handlers.py:217-249`, `@staticmethod`) constrói **todos** os
   colaboradores do `ReplayRunner` internamente e devolve só a instância
   pronta — não há canal para `handle_optimize` (linhas 135-168) obter de
   volta o `CookieJar` que ficaria dentro desse `ReplayRunner`, pra também
   passar pro `ReplayOptimizer` na linha 155. A mudança concreta:
   `handle_optimize` passa a construir `CookieJar()` e
   `CookieJarCurlOverride(cookie_jar)` **antes** de chamar
   `_build_replay_runner`; `_build_replay_runner` ganha os dois como novos
   parâmetros e os repassa ao `ReplayRunner(...)`; e o mesmo `cookie_jar` (a
   mesma instância Python, não uma cópia) é passado também pro
   `ReplayOptimizer(...)` — garantindo que os dois enxerguem exatamente o
   mesmo estado. Sem essa mudança explícita no fio de injeção, é fácil
   instanciar dois jars diferentes por engano, e a feature inteira desta
   seção vira no-op silencioso (nenhum erro, só o jar do `ReplayOptimizer`
   nunca refletindo o que o `ReplayRunner` de fato viu).
2. `_execute` reseta o jar **e o realimenta a partir do backbone cacheado
   ANTES de qualquer tráfego novo desta tentativa ser enviado** — não depois
   (⚠️ ordem invertida em relação a uma primeira versão desta spec: alimentar
   só depois de `_execute_raw` retornar deixaria o jar vazio durante o
   próprio envio das requests desta tentativa, que é exatamente quando ele
   precisa estar populado):

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

3. Nenhuma alimentação adicional é necessária depois disso: como
   `ReplayRunner._run_step`/`attempt()` (seção 3.6) já alimenta o jar
   internamente a cada resposta obtida ao vivo, os steps de `ordered_indexes`
   que passam por `execute_schedule` nesta tentativa alimentam o jar por
   conta própria, em ordem, à medida que são enviados. A pré-alimentação do
   passo 2 cobre exatamente o que `_run_step` não alcança: os índices do
   backbone que são cache hit (servidos por `_backbone_response_cache`,
   nunca chamam `_run_step` nesta tentativa).
4. `_run_phase1` (que hoje chama `self._execute(self.backbone,
   set(self.backbone))` uma única vez pra estabelecer o backbone) já cai
   nesse mesmo fluxo sem mudança adicional: na primeira chamada, o cache
   está vazio, `_feed_cookie_jar_from_backbone_cache` não alimenta nada, e
   todo o backbone é executado ao vivo por `execute_schedule` — cada step
   alimentando o jar via `_run_step`, em ordem ascendente (`_compute_backbone`
   já devolve os índices ordenados), exatamente como o `run` faria.

**Por que resetar em toda tentativa, e não só na atualização reativa
(`force_refresh`):** o vazamento que motiva o reset não é de sessão
invalidada (isso já é coberto por `_needs_reactive_refresh`) — é de
**contaminação entre tentativas distintas** durante a fase 2
(`_resolve_range`, linhas 156-179): ao testar remover um candidato do
schedule (`trial`, linha 176), se o jar ainda "lembrar" de um cookie que
**só** o candidato removido tinha estabelecido numa tentativa anterior, a
tentativa sem esse candidato pode passar por engano — dando resultado
incorreto sobre se o candidato é removível, quando na prática o servidor real
(sem aquele cookie) teria recusado a request. Resetar a cada tentativa
garante que cada uma seja avaliada apenas com os cookies que ela mesma, de
fato, estabeleceria.

### 3.8 Por que não usar o addon `stickycookie` do mitmproxy inteiro

O mitmproxy já traz um cookie jar pronto e correto
(`mitmproxy/addons/stickycookie.py`, disponível no `.venv` do projeto,
`mitmproxy>=11.1.3`) — cogitado como primeira opção por não precisar de
código novo algum. Descartado como **addon** (mas não como fonte de lógica —
seções 3.1/3.2 já reaproveitam `is_expired`/o wrapper de `domain_match`)
porque ele só aprende cookies **observando tráfego ao vivo** que passa pelo
proxy (hook `response()`) e só os aplica em requests que também passam ao
vivo pelo proxy (hook `request()`). Isso é incompatível com o cache de
respostas do backbone (`_backbone_response_cache`, seção 2): numa tentativa
que reaproveita uma resposta cacheada, **nenhum tráfego novo passa pelo
proxy** — o addon nunca teria a chance de reforçar aquele cookie no jar
dele, e um cache hit "esqueceria" cookies que só foram vistos ao vivo em
tentativas anteriores. Rodar tudo sempre ao vivo (sem cache) resolveria
isso, mas reverteria o ganho de performance da etapa anterior
(`docs/20260825 Cache de Respostas do Backbone na Otimização de Replay`).

A solução desta spec (`CookieJar` em Python puro, alimentado explicitamente
pelas respostas que `Engine`/`ReplayRunner`/`ReplayOptimizer` **já leem**,
seja a resposta fresca ou cacheada) não depende de tráfego ao vivo para
aprender um cookie — funciona identicamente nos dois casos, porque quem
alimenta o jar é o código Python que já tem o `StepResponse` em mãos, não um
observador passivo de rede.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `CookieAttributes` (novo, `models/http.py`) | Modelo aditivo: `domain`, `path`, `expired`. Não altera `StepResponse.cookies`. |
| `StepResponse` | Ganha campo `cookie_attributes: Dict[str, CookieAttributes]`, aditivo. |
| `MitmAddon._response_cookies_list` | Passa a incluir `domain`/`path`/`expired` (já parseados pelo mitmproxy, só paravam de ser descartados). |
| `HARParser.parse_entry` | Passa a construir `res_cookie_attributes` ao lado de `res_cookies`; só é preenchido de forma útil quando a origem é o envelope do `MitmAddon` (HAR original não tem `expired`, fica no default — seção 3.1). |
| `RequestUrlScope` (novo, `reproduction/request_url_scope.py`) | Utilitário único `url → (host, port, path)`, compartilhado por `Engine`/`ReplayRunner`/`ReplayOptimizer`. |
| `CookieJar` (novo, `session/cookie_jar.py`) | Estrutura em memória por escopo `(domain, port, path)`: `feed(host, port, cookies, attributes)`, `current(host, port, path)`, `reset()`. Casamento de domínio portado de `stickycookie.py:27-32`. |
| `CookieJarCurlOverride` (novo, `reproduction/cookie_jar_curl_override.py`) | Recebe `CookieJar` **por construtor**. Sobrescreve o `--cookie` de um curl já resolvido com o estado atual do jar, via tokenização de shell (`shlex.split`/`shlex.join`, filtrando os tokens `"\n"` que a continuação de linha do `.curl.sh` introduz) — nunca regex de texto livre nem reconstrução ingênua por rejoin direto. |
| `Engine` | Recebe `CookieJar`/`CookieJarCurlOverride` por construtor; `_attempt_step` aplica o override e alimenta o jar **dentro da mesma função**, cobrindo também tentativas de retry. Sem reset (execução única e sequencial). |
| `ReplayRunner` | Recebe `CookieJar`/`CookieJarCurlOverride` por construtor; `attempt()` (dentro de `_run_step`) aplica o override e alimenta o jar, cobrindo retry. Sem reset (uma chamada de `execute_schedule` por invocação de CLI). |
| `ReplayOptimizer` | Ganha `workspace: Workspace` como novo parâmetro de construtor (hoje não guarda nenhum) e recebe referência ao **mesmo** `CookieJar` que a raiz de composição injetou no `ReplayRunner`; `_execute` reseta o jar e o realimenta a partir do backbone cacheado **antes** de qualquer tráfego novo da tentativa, em toda tentativa (inicial e em cada refresh reativo). |
| `cli_handlers._build_replay_runner`/`handle_optimize` (raiz de composição) | `_build_replay_runner` ganha `cookie_jar`/`cookie_jar_curl_override` como novos parâmetros (construídos por quem a chama, repassados ao `ReplayRunner`). `handle_optimize` constrói essa dupla **antes** de chamar `_build_replay_runner`, repassa a mesma instância de `CookieJar` também ao `ReplayOptimizer(...)` — garantindo identidade compartilhada, não duas instâncias por engano (seção 3.7, item 1). `handle_run` faz o mesmo, mais simples, direto para `Engine`. |
| `BaselineDiff`/`CookieAgent`/`TokenTracker`/`PlaceholderApplier` | Sem mudança nesta etapa (seção 1 — fora de escopo; `PlaceholderApplier` já é compatível por natureza — seção 2). |
| `MitmProxyOrchestrator` | Sem mudança — o jar não depende de observação de tráfego (seção 3.8). |

## 5. Casos de borda e comportamento de erro

- **Cookie nunca definido por `Set-Cookie` dentro desta execução** (existia
  antes da gravação começar, ex.: cookie de terceiro fixado no navegador antes
  do HAR ser capturado). `CookieJar.current(...)` não tem entrada de escopo
  que case — `CookieJarCurlOverride.apply` devolve o texto original sem
  alterar. Comportamento idêntico ao atual (literal do HAR / valor de
  extractor existente). Esta é a única situação em que o jar genuinamente não
  tem como ajudar — nem um navegador real "descobriria" esse valor do nada.
- **Cookie expirado durante a execução** (`Max-Age=0` ou `Expires` no
  passado num `Set-Cookie` recebido ao vivo): `CookieJar.feed` remove essa
  entrada do escopo correspondente (via `attrs.expired`, seção 3.1/3.2) — uma
  request subsequente ao mesmo escopo deixa de receber esse cookie do jar
  (volta a valer o literal do HAR/extractor, se existir, ou nenhum, se o
  cookie também não estava no `.curl.sh` original).
- **Cookie com `Domain=.exemplo.com` valendo pra múltiplos subdomínios, e
  também pro domínio-base sem subdomínio**: com o casamento de domínio
  portado do `stickycookie` (seção 3.2, não a função crua da stdlib), uma
  resposta de `sub1.exemplo.com` (ou do próprio `exemplo.com`) que define
  esse cookie passa a valer também pra requests a `sub2.exemplo.com` **e** a
  `exemplo.com`.
- **Reactive refresh do backbone** (`_needs_reactive_refresh`,
  `replay_optimizer.py:140-141`): coberto pelo reset-e-realimentação-antes-do-
  envio da seção 3.7 — cada iteração do laço reseta e realimenta o jar a
  partir do backbone recém-reexecutado **antes** de tentar `ordered_indexes`
  de novo.
- **Retry de step (`StepRetryPolicy`, `engine.py:132-146`,
  `replay_runner.py:112-121`)**: cada tentativa de envio do mesmo step
  (inclusive as que disparam recuperação) aplica o jar corrente antes de
  enviar e o alimenta com a resposta obtida — o feed acontece dentro da
  própria função de tentativa (seções 3.5/3.6), não depois que
  `StepRetryPolicy.execute` devolve só a última resposta.
- **Dois escopos colidindo no mesmo nome de cookie** (seção 1): sem regra de
  precedência determinística — limitação aceita, replicando a mesma lacuna
  não resolvida do `stickycookie` original.
- **Cookie com `Path=/foo` vazando para `/foobar`** (seção 1): `CookieJar.
  _matches` casa path por `startswith`, não pelo algoritmo exato do RFC
  6265 — limitação aceita, replicando o mesmo comportamento "cru" de
  `stickycookie.py:87`.
- **Tokens `"\n"` artefato de `shlex.split` sobre a continuação de linha do
  `.curl.sh`** (seção 3.4): filtrados explicitamente por
  `CookieJarCurlOverride._tokenize` antes de qualquer parsing/reconstrução —
  sem esse filtro, o comando reconstruído levaria argumentos espúrios pro
  curl e quebraria a request.
- **Múltiplos `Set-Cookie` de nomes diferentes na mesma resposta**: já
  cobertos por `StepResponse.cookies` (um dict, uma entrada por nome) —
  `CookieJar.feed` os aplica todos de uma vez.
- **Escopo nunca visto antes** (primeira request pra aquele domínio/porta/path
  dentro da execução): `CookieJar.current(...)` devolve `{}` — comportamento
  igual ao caso "cookie nunca definido" acima.
- **`skip_reason` (`StepSkipEvaluator`, `engine.py:80-87,101-105`)**: steps
  pulados nunca chegam a `_attempt_step`/`execute_step` — não geram tráfego,
  não alimentam nem consultam o jar. Comportamento inalterado.
- **`--data-binary` com texto contendo a substring `--cookie`**: coberto pelo
  parsing por tokens de shell (seção 3.4) — não confundido com a flag real.

## 6. Suposições e pontos a confirmar

- Assumimos que nenhum HAR real deste projeto depende de dois cookies de
  mesmo nome, escopados por paths que se sobrepõem no mesmo host, vigentes ao
  mesmo tempo (o caso de precedência não resolvido citado na seção 1). Se um
  HAR real expuser isso, precisa de uma regra de precedência por
  especificidade de path — não implementada nesta etapa.
- Assumimos que remover `CookieAgent`/o rastreamento de cookie via
  `TokenTracker` é uma decisão a parte, a ser tomada depois de validar o jar
  em uso real — não incluída nesta etapa.

## 7. Referência

Toda implementação desta spec segue `guia-de-estilo` (tipagem explícita,
dependências por construtor, métodos privados pequenos, zero comentários no
código, `Enum(str, Enum)` para conjuntos fechados, etc.) — ver
[[guia-de-estilo]].
