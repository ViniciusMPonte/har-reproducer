# Plano de Implementação — Tokens dinâmicos, curl templates e transporte via mitmproxy

> Derivado de `spec.md`. Cada task abaixo é autocontida: quem for executá-la não precisa ler o spec inteiro nem o histórico da conversa — só a task. As referências `§N` ao spec são só para quem quiser aprofundar, não são pré-requisito de leitura.

**Convenção de status:** cada task tem uma lista de dependências (`Depende de`). Tasks sem dependência entre si podem ser feitas em paralelo, por pessoas ou sessões diferentes.

---

## T01 — Adicionar `TokenLocation.URL_PARAM`

**Depende de:** nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/session.py`

**Contexto:** o enum `TokenLocation` marca onde um token foi encontrado/aplicado (`HEADER`, `COOKIE`, `BODY_JSON`, `BODY_HTML`, `SCRIPT`). Não existe hoje uma opção para "token na query string da URL", e isso vai ser necessário porque o `PlaceholderApplier` passará a substituir tokens também na URL (ver T06).

**Estado atual:** `TokenLocation` não tem valor para URL.

**Estado esperado depois:** `TokenLocation` tem um novo membro `URL_PARAM = "UrlParam"`.

**Critérios de aceite:**
- [X] Novo membro `URL_PARAM` existe no enum, com valor de string `"UrlParam"`.
- [X] Nenhum outro membro do enum foi alterado ou removido.
- [X] O projeto ainda importa/compila normalmente (nenhum outro arquivo depende do número/ordem dos membros do enum).

---

## T02 — Remover a classe `TokenTrace`

**Depende de:** nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/session.py`

**Contexto:** `TokenTrace` é um model hoje usado exclusivamente pela implementação atual do `CurlGenerator`, que será reescrita (T07) para não depender mais dele — a nova versão recebe uma lista de `DynamicToken` em vez de detectar traces sozinha.

**Estado atual:** classe `TokenTrace` existe em `session.py`, com campos `token_id`, `value`, `origin_step`, `location`, `key`.

**Estado esperado depois:** a classe não existe mais no arquivo.

**Critérios de aceite:**
- [X] Classe `TokenTrace` removida por completo do arquivo.
- [X] Nenhum import de `TokenTrace` sobra em nenhum outro arquivo do projeto (buscar por `TokenTrace` no repositório inteiro antes de fechar a task — a remoção do uso em `CurlGenerator` acontece em T07, então rode essa busca só depois de T07 estar concluída, ou trate T02 e T07 como um par a fechar junto).

---

## T03 — Adicionar `proxy_port` em `ProjectConfig`

**Depende de:** nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/config.py` (classe `ProjectConfig`)

**Contexto:** a porta do `mitmdump` (usado pelo novo transporte, T12) precisa ser configurável via o mesmo `config.json` que já é usado hoje para configurar o LLM (`ProjectConfig.llm`) e os critérios de sucesso (`ProjectConfig.success_criteria`).

**Estado atual:** `ProjectConfig` tem só `llm: Optional[LLMSettings]` e `success_criteria: List[SuccessCriterion]`.

**Estado esperado depois:** `ProjectConfig` ganha `proxy_port: Optional[int] = None`.

**Critérios de aceite:**
- [X] Campo `proxy_port: Optional[int] = None` adicionado a `ProjectConfig`.
- [X] Um `config.json` sem esse campo continua sendo parseado sem erro (campo é opcional).
- [X] Um `config.json` com `"proxy_port": 8080` (por exemplo) popula `ProjectConfig.proxy_port` corretamente com esse valor.
- [X] Nenhum comportamento de leitura do restante do `ProjectConfig` (llm, success_criteria) foi alterado.

---

## T04 — Novo `WorkspaceDir` para captura do mitmproxy + helpers em `Workspace`

**Depende de:** nenhuma.
**Arquivos envolvidos:** `har_reproducer/fs_io/workspace_dir.py`, `har_reproducer/fs_io/workspace.py`

**Contexto:** o addon do mitmproxy (T13) precisa de um diretório fixo dentro do workspace do projeto para gravar o arquivo de captura de cada request (sempre sobrescrito, um por vez). Além disso, hoje o caminho do arquivo `.curl.sh` está hardcoded dentro de `RequestBuilder.write_curl` (`self.curls_dir / f"req_{step.index:04d}.curl.sh"`) — esse método será removido (T11), e o padrão de nomeação precisa de um lar formal em `Workspace`, no mesmo padrão de `request_file`/`response_file`.

**Estado atual:**
- `WorkspaceDir` tem: `CURLS`, `REAL_RESPONSES`, `REAL_REQUESTS`, `EXTRACTORS`, `TEMP_EXTRACTORS`.
- `Workspace` tem os métodos `temp_extractor_file`, `extractor_file`, `request_file`, `response_file` — todos seguindo o padrão `cls._ensure_initialized()` + retorno de `Path`.
- Não existe diretório nem helper para a captura do mitmproxy.
- Não existe helper `curl_file`.

**Estado esperado depois:**
- Novo membro em `WorkspaceDir`, ex.: `MITM_CAPTURE = "mitm_capture"`.
- Novo método `Workspace.mitm_capture_file() -> Path`: retorna sempre o **mesmo caminho fixo** (ex.: `cls.mitm_capture / "capture.har"`) — não indexado por step, já que é sobrescrito a cada request.
- Novo método `Workspace.curl_file(index: int) -> Path`: retorna `cls.curls / f"req_{index:04d}.curl.sh"` — mesmo padrão de nomeação que existia hardcoded em `RequestBuilder.write_curl`.

**Critérios de aceite:**
- [X] `WorkspaceDir.MITM_CAPTURE` existe e, ao chamar `Workspace.init(output_dir)`, o diretório correspondente é criado no disco (mesmo comportamento automático que os outros membros do enum já têm, via o loop em `Workspace.init`).
- [X] `Workspace.mitm_capture_file()` levanta `RuntimeError` se chamado antes de `Workspace.init()` (mesmo padrão de `_ensure_initialized()` dos outros métodos).
- [X] `Workspace.mitm_capture_file()` retorna sempre o mesmo `Path`, independente de quantas vezes for chamado.
- [X] `Workspace.curl_file(index)` retorna `Path` no formato `.../curls/req_{index:04d}.curl.sh`, com zero-padding de 4 dígitos igual aos outros métodos (`request_file`, `response_file`).

---

## T05 — `SessionStore.render()`: novo formato de placeholder

**Depende de:** nenhuma.
**Arquivos envolvidos:** `har_reproducer/session/session_store.py` (classe `SessionStore`)

**Contexto:** hoje `render(template: str)` substitui ocorrências de `{{token_id}}` pelo valor em `self.state.tokens[token_id]`, via `str.replace` simples num loop. O novo formato de placeholder passa a ser `{{extractor:token_id}}` (decisão de produto: deixa explícito que é um token resolvido via extractor). Não haverá suporte ao formato antigo — sem fallback, sem detecção dupla.

**Estado atual:**
```python
def render(self, template: str) -> str:
    result: str = template
    for token_id, value in self.state.tokens.items():
        result = result.replace(f"{{{{{token_id}}}}}", value)
    return result
```

**Estado esperado depois:** `render` reconhece o padrão `{{extractor:token_id}}` via regex (ex.: `\{\{extractor:([a-f0-9]+)\}\}`), substituindo cada ocorrência pelo valor correspondente em `self.state.tokens`. Se o `token_id` capturado não existir em `self.state.tokens`, o placeholder correspondente permanece **literal** no texto (sem levantar exceção). `render_dict` não precisa de nenhuma mudança de código — ele já delega para `render` em cada string encontrada recursivamente.

**Critérios de aceite:**
- [X] `render("Bearer {{extractor:abc123}}")`, com `state.tokens = {"abc123": "real-value"}`, retorna `"Bearer real-value"`.
- [X] `render("{{abc123}}")` (formato antigo, sem prefixo `extractor:`) **não é resolvido** — string retorna inalterada, literal.
- [X] `render("{{extractor:naoexiste}}")`, com `"naoexiste"` ausente de `state.tokens`, retorna a string com o placeholder intacto, sem lançar exceção.
- [X] Múltiplos placeholders diferentes na mesma string são todos resolvidos numa única chamada de `render`.
- [X] `render_dict` (chamado sobre um dict/list aninhado contendo o novo formato) resolve corretamente em qualquer profundidade — sem alteração de código nele, só validação de que o comportamento em cascata continua funcionando com o novo regex.

---

## T06 — `PlaceholderApplier`: novo formato, ordenação e suporte a URL

**Depende de:** T01 (precisa de `TokenLocation.URL_PARAM`).
**Arquivos envolvidos:** `har_reproducer/tracking/placeholder_applier.py` (classe `PlaceholderApplier`)

**Contexto:** essa classe muta um `StepRequest` in-place, trocando o valor literal de um token pelo placeholder, para cada `DynamicToken` recebido, quando o extractor correspondente está `verified`. Hoje ela cobre headers, cookies e body — falta cobrir a URL, falta a ordenação por tamanho (evitar que token A, substring de token B, corrompa a substituição de B), e o formato do placeholder precisa mudar.

**Estado atual:**
- `_placeholder_for(token_id)` retorna `f"{{{{{token_id}}}}}"` (formato antigo, sem prefixo).
- `apply(request, tokens)` itera `tokens` na ordem recebida, sem ordenação.
- Existem `_replace_in_headers`, `_replace_in_cookies`, `_replace_in_body` — não existe `_replace_in_url`.
- `request.url` nunca é tocado.

**Estado esperado depois:**
- `_placeholder_for(token_id)` retorna `f"{{{{extractor:{token_id}}}}}"`.
- `apply(request, tokens)`: antes de iterar, ordena `tokens` por `len(token.current_value)` **decrescente**.
- Novo método `_replace_in_url(request, value, placeholder)`: mesmo padrão dos métodos existentes — se `value in request.url`, substitui por `placeholder` (`request.url = request.url.replace(value, placeholder)`).
- `_apply_token` passa a chamar `_replace_in_url` junto com os outros três métodos existentes.
- Quando uma substituição ocorre na URL, isso deveria refletir em algum campo do `DynamicToken` relacionado a localização (`destination_location` ou equivalente já existente no model) como `TokenLocation.URL_PARAM` — **checar o model `DynamicToken` (já existe, não faz parte desta task alterá-lo) para confirmar qual campo é o correto antes de implementar esse detalhe.**

**Critérios de aceite:**
- [X] `_placeholder_for("abc123")` retorna `"{{extractor:abc123}}"`.
- [X] Um `DynamicToken` com `current_value` igual a uma substring dentro de `Authorization: Bearer <valor>` (num header) resulta em só o trecho `<valor>` substituído — `Bearer ` permanece intacto.
- [X] Dois tokens onde o valor de um é substring do valor do outro (ex.: `"abc"` e `"abc123"`) são aplicados na ordem certa (mais longo primeiro) sem corromper o placeholder do outro — testar explicitamente esse cenário.
- [X] Um `DynamicToken` cujo `current_value` aparece na query string de `request.url` é substituído corretamente pelo placeholder, sem afetar o resto da URL.
- [X] Token com `current_value` vazio continua sendo ignorado (comportamento já existente, não deve regredir).
- [X] Token sem extractor `verified` continua sendo ignorado (comportamento já existente, não deve regredir).

---

## T07 — Reescrita completa de `CurlGenerator`

**Depende de:** T02 (remoção de `TokenTrace`, que este arquivo deixa de importar).
**Arquivos envolvidos:** `har_reproducer/reproduction/curl_generator.py` (classe `CurlGenerator`)

**Contexto:** hoje `CurlGenerator.generate(step_index, request, session_store)` faz sua própria detecção de tokens (comparando valores de header/cookie/body contra `session_store.state.tokens`) e monta comentários posicionais. Isso deixa de fazer sentido: a detecção de token já é feita por `PlaceholderApplier` (T06) antes de chegar aqui. `CurlGenerator` passa a ser **puramente um formatador**: recebe um `StepRequest` (já com ou sem placeholders, dependendo de quem chama) e uma lista de `DynamicToken`, e devolve a string do curl.

**Estado atual — assinatura e comportamento:**
```python
def generate(self, step_index, request, session_store=None) -> str
```
- Faz merge de `{**request.headers, **request.cookies}` para detectar traces (bug: colide chaves duplicadas entre header e cookie).
- Gera uma flag `--cookie` por cookie (múltiplas flags).
- Não usa `shlex.quote` em lugar nenhum — valores com aspas simples quebram o curl gerado.
- Métodos internos de detecção de trace: `_find_token_traces`, `_header_and_cookie_traces`, `_body_traces`, `_get_trace_for_value`, `_find_token_id_by_value`, `_trace_comment`.

**Estado esperado depois — nova assinatura e comportamento:**
```python
def generate(self, request: StepRequest, tokens: List[DynamicToken]) -> str
```
- Headers e cookies iterados **separadamente** — nunca via merge de dict.
- Cookies combinados numa única flag: `--cookie 'chave1=valor1; chave2=valor2'`.
- Todo valor inserido na string final passa por `shlex.quote()` — o header inteiro (`"chave: valor"`), a string de cookies combinada, o body, e a URL.
- Body mantém `--data-binary`.
- Comentários: um por item de `tokens`, agregados no **topo do bloco gerado** (antes de `curl -X ...`), no formato exato:
  ```
  # Token {token_id} comes from response of step {origin_step}
  ```
  Se `tokens` for lista vazia, nenhum comentário é emitido.
- Métodos de detecção de trace listados acima: **todos removidos**.
- Import de `TokenTrace`, `SessionStore`: removidos (a classe não depende mais deles).

**Critérios de aceite:**
- [X] Header ou cookie com valor contendo aspas simples (`'`) gera um curl sintaticamente válido (testar com `shlex.split` no resultado, por exemplo, pra confirmar que não quebra).
- [X] Um header e um cookie com o **mesmo nome de chave** aparecem ambos corretamente no curl gerado, sem um sobrescrever o outro.
- [X] Múltiplos cookies resultam em uma única flag `--cookie`, valores separados por `; `.
- [X] Chamando `generate(request, tokens=[])` sobre um `request` sem nenhum placeholder produz um curl 100% literal, sem nenhum comentário `# Token ...`.
- [X] Chamando `generate(request, tokens=[dt1, dt2])` produz exatamente 2 linhas de comentário, uma para cada `DynamicToken`, agregadas antes do `curl -X`, no formato especificado acima.
- [X] Um `request` que já contém `{{extractor:token_id}}` em algum header/cookie/body (aplicado previamente por `PlaceholderApplier`) aparece **literalmente** no curl gerado — `CurlGenerator` não tenta resolver nem tocar nesse texto.
- [X] Nenhum dos métodos antigos de detecção de trace (`_find_token_traces`, `_header_and_cookie_traces`, `_body_traces`, `_get_trace_for_value`, `_find_token_id_by_value`, `_trace_comment`) existe mais na classe.
- [X] Busca por `TokenTrace` no arquivo inteiro não retorna nenhuma ocorrência.

---

## T08 — Atualizar `TokenTracker.analyze_step`

**Depende de:** T06, T07.
**Arquivos envolvidos:** `har_reproducer/tracking/token_tracker.py` (classe `TokenTracker`)

**Contexto:** `analyze_step` já orquestra `BaselineDiff` → `CandidateResolver` → `PlaceholderApplier` → geração de curl → `StepAnalysis`. A única mudança aqui é trocar a geração de curl "pobre" (`_generate_curl_template`, staticmethod que só monta método+URL+headers, sem cookies/body/comentários) pela chamada ao `CurlGenerator` já reescrito em T07.

**Estado atual:**
```python
@staticmethod
def _generate_curl_template(request: StepRequest) -> str:
    headers_str = " ".join(f'-H "{key}: {value}"' for key, value in request.headers.items())
    return f"curl -X {request.method} '{request.url}' {headers_str}"
```
chamado dentro de `analyze_step` como `template = self._generate_curl_template(step.request)`.

**Estado esperado depois:**
- `_generate_curl_template` removido.
- `analyze_step` chama `CurlGenerator().generate(step.request, tokens)` no lugar (usando o `step.request` já mutado por `self.placeholder_applier.apply(step.request, tokens)`, que roda logo antes na mesma função, e a lista `tokens` já disponível no escopo do método).
- O restante de `analyze_step` (chamadas a `baseline_diff`, `candidate_resolver`, montagem de `StepAnalysis`) não muda.

**Critérios de aceite:**
- [X] `_generate_curl_template` não existe mais na classe.
- [X] `analyze_step` retorna um `StepAnalysis.curl_template` gerado via `CurlGenerator` — validar manualmente (ou via teste) que o resultado inclui cookies e body quando o step tiver, coisa que a versão antiga nunca fazia.
- [X] `StepAnalysis.dynamic_tokens` continua sendo preenchido normalmente (comportamento herdado, não deve regredir).
- [X] Nenhuma outra mudança de comportamento em `analyze_step` além da troca da geração do curl.

---

## T09 — Extrair `TokenResolver` de dentro de `Engine`

**Depende de:** nenhuma (extração isolada — não depende de mudanças em outros arquivos, mas será consumida por T15).
**Arquivos envolvidos:** novo arquivo `har_reproducer/tracking/token_resolver.py`; `har_reproducer/engines/engine.py` (remoção)

**Contexto:** hoje a lógica de "reexecutar extractors verificados contra a response salva em disco, e atualizar `session_store.state.tokens`" vive dentro de `Engine` (`update_session_tokens`, `_should_refresh_token`, `_refresh_token`). O objetivo é ter **uma única lógica de resolução de token**, num arquivo próprio, para ser reaproveitada tanto pelo fluxo live do `Engine` quanto por uma futura ferramenta de replay standalone (essa ferramenta standalone não é entregue nesta task, só a extração que a viabiliza).

**Estado atual — em `engine.py`:**
```python
def update_session_tokens(self) -> None:
    for token_id, extractor in self.session_store.state.registry.items():
        if self._should_refresh_token(extractor):
            self._refresh_token(token_id, extractor)

def _should_refresh_token(self, extractor: Extractor) -> bool:
    return extractor.verified and extractor.origin_step is not None

def _refresh_token(self, token_id: str, extractor: Extractor) -> None:
    if not Workspace.response_file(extractor.origin_step).exists():
        return
    try:
        value = self.extractor_runner.run(extractor)
    except Exception as e:
        print(f"Failed to refresh token '{token_id}': {e}")
        return
    if value:
        self.session_store.set_token(token_id, value)
```
`self.extractor_runner: ExtractorRunner` é criado no `__init__` do `Engine` e usado só aqui.

**Estado esperado depois:**
- Novo arquivo `token_resolver.py`, classe `TokenResolver`:
  - Construtor recebe `session_store: SessionStore`.
  - Constrói internamente sua própria instância de `ExtractorRunner` (encapsula essa dependência — `Engine` não precisa mais criar/possuir um `ExtractorRunner` separado).
  - Método público `resolve_all() -> None`: mesma lógica de `update_session_tokens`/`_should_refresh_token`/`_refresh_token`, movida sem alteração de comportamento.
- Em `Engine`:
  - `update_session_tokens`, `_should_refresh_token`, `_refresh_token` removidos.
  - `self.extractor_runner` removido do `__init__` (a menos que seja usado em outro lugar do `Engine` — checar antes de remover; pelos arquivos vistos até aqui, não é).
  - `self.token_resolver: TokenResolver = TokenResolver(self.session_store)` adicionado ao `__init__`.
  - Toda chamada a `self.update_session_tokens()` dentro de `Engine` (em `_process_entry` e `handle_recovery`) passa a ser `self.token_resolver.resolve_all()`.

**Critérios de aceite:**
- [X] `TokenResolver.resolve_all()` produz exatamente o mesmo efeito colateral (atualização de `session_store.state.tokens`) que `Engine.update_session_tokens()` produzia antes, para o mesmo cenário de entrada (mesmo registry, mesmas responses em disco).
- [X] `Engine` não tem mais `update_session_tokens`, `_should_refresh_token`, `_refresh_token`, nem `self.extractor_runner`.
- [X] `Engine._process_entry` e `Engine.handle_recovery` chamam `self.token_resolver.resolve_all()` no lugar de `self.update_session_tokens()`.
- [X] `TokenResolver` não importa nada de `har_reproducer.engines` (evita dependência circular — ele deve poder ser importado e instanciado sem precisar de um `Engine`).

---

## T10 — `ExtractorRunner`: rodar um extractor já existente em disco só pelo `token_id`

**Depende de:** nenhuma.
**Arquivos envolvidos:** `har_reproducer/reproduction/extractor_runner.py` (classe `ExtractorRunner`)

**Contexto:** cada `extract_{token_id}.py` já é autocontido — o código e o `step_index` ficam embutidos no texto do arquivo no momento em que é escrito (`_write_extractor_script`), e o script resolve o caminho da response via `Path(__file__).resolve().parent.parent`. Isso significa que rodar um extractor que já existe em disco **não precisa do model `Extractor` em memória** — só precisa do `token_id`, pra localizar o arquivo. Hoje `ExtractorRunner.run(extractor)` sempre reescreve o script a partir do model antes de rodar; falta um caminho que executa o que já existe, sem reescrever.

**Estado atual:**
```python
def run(self, extractor: Extractor) -> Optional[str]:
    extractor_file = self._write_extractor_script(extractor)
    self._cleanup_temp_file(extractor)
    return self._execute_extractor_script(extractor_file)
```
`_execute_extractor_script(extractor_file: Path)` já não depende do model — só do `Path`.

**Estado esperado depois:** novo método público, ex.:
```python
def run_existing(self, token_id: str) -> Optional[str]:
    extractor_file = Workspace.extractor_file(token_id)
    if not extractor_file.exists():
        return None
    return self._execute_extractor_script(extractor_file)
```
`run(extractor)` existente não muda — esse método novo é aditivo, não substitui nada.

**Critérios de aceite:**
- [X] `run_existing(token_id)` com um `token_id` cujo arquivo `extract_{token_id}.py` existe em disco executa esse script e retorna o `stdout` (mesma semântica de retorno de `run`).
- [X] `run_existing(token_id)` com um `token_id` cujo arquivo **não existe** retorna `None`, sem lançar exceção.
- [X] `run(extractor)` (método já existente) continua funcionando exatamente como antes — nenhuma regressão.

---

## T11 — Limpeza em `RequestBuilder`

**Depende de:** T04 (precisa de `Workspace.curl_file`), T07 (o método removido usava a assinatura antiga de `CurlGenerator`).
**Arquivos envolvidos:** `har_reproducer/reproduction/request_builder.py` (classe `RequestBuilder`)

**Contexto:** `write_curl` hoje gera um curl **literal** (a partir do `final_request` já resolvido) chamando `CurlGenerator().generate(step.index, final_request, session_store=...)` — assinatura que não existe mais depois de T07. Além disso, o `curl_template` (com placeholders) já é computado em `TokenTracker.analyze_step` (T08), então não há mais necessidade de `RequestBuilder` gerar curl nenhum — a persistência do arquivo passa a ser responsabilidade de `Engine` (T15), usando o valor já calculado.

**Estado atual:**
```python
def write_curl(self, step: Step, final_request: StepRequest) -> None:
    curl_cmd = CurlGenerator().generate(step.index, final_request, session_store=self.session_store)
    curl_file = self.curls_dir / f"req_{step.index:04d}.curl.sh"
    curl_file.write_text(f"#!/bin/bash\n{curl_cmd}\n", encoding="utf-8")
```

**Estado esperado depois:**
- `write_curl` removido por completo.
- Import de `CurlGenerator` removido deste arquivo.
- `build_final_request` (o outro método da classe) **não muda** — continua resolvendo placeholders via `session_store.render_dict`/`render`.
- Atributo `self.curls_dir` no `__init__`: avaliar se ainda é usado por algo além de `write_curl` — se não for, pode ser removido também (checar antes; pelos arquivos vistos, só era usado ali).

**Critérios de aceite:**
- [X] `write_curl` não existe mais na classe.
- [X] Nenhum import de `CurlGenerator` sobra neste arquivo.
- [X] `build_final_request` continua funcionando sem nenhuma mudança de comportamento.
- [X] Nenhum outro arquivo do projeto ainda chama `RequestBuilder.write_curl` (buscar no repositório inteiro — isso só pode ser confirmado depois de T15, que é quem tira a chamada de dentro do `Engine`; se T15 ainda não foi feita, deixe uma nota explícita de que essa checagem final fica pendente).

---

## T12 — Novo transporte: `CurlHttpTransport` (substitui `HttpTransport`)

**Depende de:** T04 (`Workspace.mitm_capture_file`), T07 (`CurlGenerator` no modo literal, `tokens=[]`), T03 (`ProjectConfig.proxy_port`, indiretamente — a porta chega como parâmetro do construtor, não é essa classe que lê o `config.json` diretamente).
**Arquivos envolvidos:** novo arquivo `har_reproducer/reproduction/curl_http_transport.py`; remoção de `har_reproducer/reproduction/http_transport.py`

**Contexto:** a execução real de cada request passa a ser feita via `curl` de verdade (subprocess), apontando para um proxy `mitmproxy` já em execução (subido por T14), em vez de `httpx.Client` direto. Isso é necessário porque o objetivo final do projeto é permitir reexecutar o fluxo inteiro a partir dos arquivos `.curl.sh` salvos.

**Estado atual (`HttpTransport`, a ser substituído):**
```python
class HttpTransport:
    def send_request(self, final_request: StepRequest, step_index: int) -> StepResponse:
        with httpx.Client(follow_redirects=False) as client:
            ...
```
Constrói `StepResponse` diretamente do `httpx.Response`. Em erro, monta `StepResponse` com `status_code=0`, `cookies=dict(client.cookies)`, `body=str(exc)`.

**Estado esperado depois — `CurlHttpTransport`, mesma interface pública (`send_request(final_request: StepRequest, step_index: int) -> StepResponse`):**

1. Construtor recebe a porta do proxy (ex.: `port: int`) e o caminho do CA do mitmproxy (raiz do projeto — ver T14 pra saber exatamente onde esse CA é gerado).
2. `send_request`:
   a. Monta o curl literal via `CurlGenerator().generate(final_request, tokens=[])`.
   b. Executa via `subprocess.run`, com: `--proxy http://127.0.0.1:{port}`, `--cacert {caminho do CA}`, **sem** `-L`/`--location`, timeout de 30s, descartando o corpo da resposta na saída do próprio `curl` (só o exit code e o fato de ter havido resposta importam aqui — o corpo real vem da captura HAR, no passo seguinte).
   c. Se falhar (exit code ≠ 0, timeout, exceção): retorna `StepResponse(status_code=0, headers={}, cookies={}, body=<mensagem de erro>, body_mime=None, redirect_url=None)` — mesmo formato do `HttpTransport._build_error_response` atual, exceto `cookies` que fica sempre `{}` (não há client/cookie-jar equivalente disponível aqui).
   d. Se tiver sucesso: lê `Workspace.mitm_capture_file()` (arquivo fixo escrito pelo addon — depende de T13 estar funcionando pra testar de ponta a ponta, mas o **código** desta task pode ser escrito e testado com um arquivo de captura mockado/fixture, sem depender do addon real estar pronto). Antes de desistir, tenta ler o arquivo algumas vezes com um pequeno intervalo entre tentativas (rede de segurança contra timing do addon — ver T13).
   e. Extrai a única entry via `HARParser.get_entries(caminho)[0]`, reaproveita `HARParser.parse_entry(entry, step_index).response` pra construir o `StepResponse` final.
3. Remover `http_transport.py` (`HttpTransport`) — mas só depois de confirmar, em T15, que nada mais importa essa classe.

**Critérios de aceite:**
- [ ] Dado um `final_request` válido e um mock/fixture do arquivo `mitm_capture_file()` no formato HAR esperado, `send_request` retorna um `StepResponse` correto (status, headers, cookies, body) — testável sem mitmproxy real rodando, usando um arquivo de captura fixo como fixture de teste.
- [ ] Simulando uma falha do `curl` (ex.: mockando `subprocess.run` pra retornar exit code ≠ 0), `send_request` retorna `StepResponse(status_code=0, cookies={}, ...)` no formato especificado.
- [ ] O comando de curl montado internamente inclui `--proxy`, `--cacert`, timeout, e **não** inclui `-L`/`--location`.
- [ ] `HttpTransport` (arquivo antigo) removido — só fechar esse critério depois de T15 confirmar que não há mais nenhuma referência a ele no projeto.

---

## T13 — Addon do mitmproxy

**Depende de:** T04 (`Workspace.mitm_capture_file`).
**Arquivos envolvidos:** novo arquivo `har_reproducer/reproduction/mitm_addon.py`

**Contexto:** script que roda **dentro do processo do `mitmdump`** (não é chamado diretamente pelo resto do projeto — é carregado pelo `mitmdump` via `-s`). A cada resposta que passa pelo proxy, ele precisa gravar um HAR de uma única entry, sempre no mesmo arquivo fixo, sobrescrevendo a captura anterior. Não existe nenhum rascunho disso hoje — é código novo, não refatoração.

**Estado atual:** não existe.

**Estado esperado depois:** um addon (`mitmproxy` script com função `response(flow)`, seguindo a API de addons do mitmproxy) que, a cada resposta capturada:
1. Monta um envelope HAR oficial completo com uma única entry: `{"log": {"entries": [entry]}}`, usando o schema padrão — headers como lista `[{"name": ..., "value": ...}]`, cookies como lista `[{"name": ..., "value": ...}]`, `request.postData.text` para o body do request, `response.content.text`/`content.encoding` para o body da resposta, `response.status`, `response.redirectUrl` se houver.
2. Escreve esse envelope em `Workspace.mitm_capture_file()` — **caminho fixo, precisa ser passado pro addon de alguma forma** (ex.: variável de ambiente lida no addon, já que o `mitmdump` roda como processo separado e não recebe argumentos Python diretos do resto do projeto — decidir o mecanismo exato de passagem do caminho como parte desta task).
3. Escrita **síncrona**, dentro do próprio hook `response` — sem fila, sem thread, sem escrita assíncrona.

**Critérios de aceite:**
- [X] Rodando `mitmdump -s mitm_addon.py` manualmente e fazendo uma requisição HTTP de teste através dele (ex.: `curl --proxy http://127.0.0.1:8080 http://example.com`), o arquivo de captura é criado/atualizado com um HAR válido daquela requisição.
- [X] O JSON gerado, quando passado para `HARParser.get_entries()` seguido de `HARParser.parse_entry(entries[0], 0)`, produz um `Step` válido sem lançar exceção — **este é o critério de aceite mais importante da task**: validar de ponta a ponta contra o parser real, não só visualmente.
- [X] Uma segunda requisição sobrescreve o arquivo (não acumula, não vira lista de duas entries).
- [X] Testar especificamente com uma URL HTTPS (não só HTTP) — exercita a parte de interceptação TLS do mitmproxy, que é o caso de uso real do projeto.

---

## T14 — `MitmProxyOrchestrator`

**Depende de:** T13 (addon), T03 (`ProjectConfig.proxy_port`).
**Arquivos envolvidos:** novo arquivo `har_reproducer/reproduction/mitm_proxy_orchestrator.py`

**Contexto:** classe responsável pelo ciclo de vida do processo `mitmdump` — subir antes da execução do `Engine`, esperar ficar pronto, e derrubar no final (sucesso ou erro). Só é usada para o modo `main` do `Engine` (ver T17) — o modo `dry` nunca precisa dela.

**Estado atual:** não existe.

**Estado esperado depois:** classe com, no mínimo:
- Construtor recebe a porta desejada (`Optional[int]`, vindo de `ProjectConfig.proxy_port`) — se `None`, escolhe uma porta livre em runtime (ex.: abrindo e fechando um socket na porta 0 pra descobrir uma porta livre, padrão comum em Python).
- Sobe `mitmdump -s {caminho do addon}` como subprocess, com `--set confdir={raiz do projeto}` (pra o CA ficar sempre no mesmo lugar — raiz do projeto, não `~/.mitmproxy`), na porta resolvida.
- Health check síncrono: tenta conectar na porta escolhida, em loop curto com timeout total razoável (ex.: alguns segundos), antes de considerar o proxy "pronto".
- Método que executa uma função/callback passada (tipicamente `engine.run()`) **depois** do proxy estar pronto, e que, em `finally`, derruba o processo do `mitmdump` — independente de a função ter levantado exceção ou não.
- Expõe a porta resolvida e o caminho do CA (`{raiz do projeto}/mitmproxy-ca-cert.pem`, caminho padrão que o mitmproxy usa quando `confdir` aponta pra lá) para quem for construir o `CurlHttpTransport` (T12/T15).

**Critérios de aceite:**
- [ ] Instanciando o orquestrador sem porta configurada, ele sobe numa porta livre (testável verificando que a porta escolhida está de fato aceitando conexões depois do health check passar).
- [ ] Instanciando com uma porta específica, ele sobe exatamente naquela porta.
- [ ] Depois que a função passada termina (com sucesso ou lançando exceção), o processo `mitmdump` não está mais rodando (checar via PID/processo, não só "não deu erro").
- [ ] O arquivo de CA (`mitmproxy-ca-cert.pem`) aparece na raiz do projeto depois da primeira subida do proxy.

---

## T15 — Mudanças em `Engine`

**Depende de:** T08 (`StepAnalysis`/`analyze_step` prontos), T09 (`TokenResolver`), T11 (`RequestBuilder` limpo), T12 (`CurlHttpTransport`), T04 (`Workspace.curl_file`).
**Arquivos envolvidos:** `har_reproducer/engines/engine.py` (classe `Engine`)

**Contexto:** esta é a task que amarra tudo — reordena o fluxo de execução por step pra: analisar uma vez, resolver tokens, tentar executar (com retry existente), e só persistir o curl template se a execução obteve alguma resposta real (não erro de transporte).

**Estado atual (resumo do fluxo relevante):**
```python
def _process_entry(self, index, entry, first_entry):
    step = HARParser.parse_entry(entry, index)
    self.tracker.analyze_step(step, first_entry)      # retorno descartado hoje
    self.update_session_tokens()
    final_request, response = self.execute_step(step)
    self._persist_step(index, final_request, response)
    ...

def _attempt_step(self, step):
    final_request = self.request_builder.build_final_request(step)
    self.request_builder.write_curl(step, final_request)   # removido em T11
    response = self.http_transport.send_request(final_request, step.index)
    return final_request, response
```
`self.http_transport: HttpTransport` criado no `__init__`.

**Estado esperado depois:**
1. `self.http_transport` passa a ser uma instância de `CurlHttpTransport` (T12), recebendo porta e caminho do CA — esses dois valores chegam via parâmetros do `__init__` de `Engine` (propagados de fora, de quem cria o `Engine` — ver T17, que é quem sabe a porta/CA vindos do orquestrador).
2. Adicionar `USES_NETWORK: ClassVar[bool] = True` na classe.
3. `_process_entry`:
   - `analysis: StepAnalysis = self.tracker.analyze_step(step, first_entry)` — retorno agora é capturado, não descartado.
   - `self.token_resolver.resolve_all()` no lugar de `self.update_session_tokens()`.
   - `final_request, response = self.execute_step(step)` — sem mudança de assinatura aqui.
   - `self._persist_step(index, final_request, response)` — sem mudança.
   - **Novo:** se `response.status_code != 0`, escrever `analysis.curl_template` em `Workspace.curl_file(index)` (formato: `f"#!/bin/bash\n{analysis.curl_template}\n"`, mesmo padrão que `write_curl` tinha antes de ser removido).
4. `_attempt_step`: remove a chamada a `self.request_builder.write_curl(...)` (método não existe mais); resto igual (`build_final_request` + `send_request`).
5. `handle_recovery`: troca `self.update_session_tokens()` por `self.token_resolver.resolve_all()`.
6. Remover `update_session_tokens`, `_should_refresh_token`, `_refresh_token`, `self.extractor_runner` (já cobertos em T09 — só confirmar que ficaram removidos aqui).

**Critérios de aceite:**
- [ ] `Engine.USES_NETWORK` existe e vale `True`.
- [ ] Rodando um fluxo de teste (mesmo que com mocks de `CurlHttpTransport`), o arquivo `.curl.sh` só é escrito quando `response.status_code != 0`; num cenário forçado de falha total de transporte (`status_code == 0`), nenhum arquivo de curl é escrito para aquele index.
- [ ] O `curl_template` escrito em disco é exatamente `analysis.curl_template` retornado por `analyze_step` — sem nenhuma segunda chamada a `CurlGenerator` dentro do `Engine`.
- [ ] `self.http_transport` é uma instância de `CurlHttpTransport`, não mais `HttpTransport`.
- [ ] Nenhuma referência a `HttpTransport` (import ou uso) sobra em `engine.py` — feito isso, fechar o critério pendente de T12 (remoção do arquivo `http_transport.py`) e o critério pendente de T11 (nenhum outro lugar chama `write_curl`).
- [ ] `update_session_tokens`, `_should_refresh_token`, `_refresh_token`, `self.extractor_runner` não existem mais em `Engine`.

---

## T16 — `DryEngine.USES_NETWORK = False`

**Depende de:** T15 (precisa que `Engine.USES_NETWORK` já exista).
**Arquivos envolvidos:** `har_reproducer/engines/dry_engine.py` (classe `DryEngine`)

**Contexto:** `DryEngine` sobrescreve `execute_step` por completo e nunca chama transporte nenhum — ele monta o `final_request` (resolvendo placeholders) e devolve `step.response`, a resposta original do `.har`, sem tocar rede. Isso precisa ficar explícito via o indicador criado em T15, pra `CliHandlers` (T17) saber que não precisa subir o proxy nesse modo.

**Estado atual:** `DryEngine(Engine)` não declara `USES_NETWORK`.

**Estado esperado depois:** `DryEngine` declara `USES_NETWORK: ClassVar[bool] = False`, sobrescrevendo o valor herdado de `Engine`.

**Critérios de aceite:**
- [ ] `DryEngine.USES_NETWORK` vale `False`.
- [ ] `Engine.USES_NETWORK` (classe base) continua valendo `True` — a sobrescrita não afeta a classe base nem qualquer outra subclasse futura que não a declare explicitamente.
- [ ] `DryEngine.execute_step` não foi alterado nesta task (comportamento existente preservado).

---

## T17 — `CliHandlers.handle_run`: orquestrar o proxy condicionalmente

**Depende de:** T14 (`MitmProxyOrchestrator`), T15 (`Engine.USES_NETWORK`, `Engine` aceitando porta/CA no construtor), T16 (`DryEngine.USES_NETWORK`).
**Arquivos envolvidos:** `har_reproducer/cli/cli_handlers.py` (classe `CliHandlers`, método `handle_run`)

**Contexto:** ponto de entrada real de uma execução (`main.py` → `CliHandlers.handle_run`). Precisa decidir, antes de rodar o engine, se sobe o `MitmProxyOrchestrator` — só faz sentido para engines com `USES_NETWORK = True` (hoje, só o modo `main`; `dry` não precisa).

**Estado atual:**
```python
def handle_run(self, args: Namespace) -> None:
    har_path = Path(args.har)
    output_dir = self._resolve_output_dir(args, har_path)
    self._reset_output_dir(output_dir)
    config_path = Path(args.config) if args.config else None

    mode = EngineMode(args.mode)
    engine = self._engine_factory.create(mode, har_path, output_dir, config_path)
    result = engine.run()
    if result:
        print("\nReproduction SUCCESSFUL: Target state reached.")
    else:
        print("\nReproduction FAILED: Target state not reached.")
```

**Estado esperado depois:**
- Resolver a classe do engine (`EngineFactory._STRATEGIES[mode]`, ou expor um jeito de consultar isso sem instanciar ainda — checar `EngineFactory` pra ver a forma menos invasiva de fazer essa consulta) para checar `USES_NETWORK` **antes** de decidir se sobe o orquestrador.
- Se `USES_NETWORK` for `True`: instanciar `MitmProxyOrchestrator` (usando `proxy_port` do `ProjectConfig`, carregado a partir de `config_path` — checar como isso é lido hoje, já que `Engine._load_project_config` já faz esse parsing internamente; pode ser necessário expor esse parsing separadamente, ou deixar o `Engine` receber o orquestrador já pronto — decidir a forma mais simples sem duplicar o parsing de config), rodar `engine.run()` dentro dele (passando porta/CA pro `Engine` construir seu `CurlHttpTransport`).
- Se `USES_NETWORK` for `False`: `engine.run()` direto, sem subir nada.
- Resto do método (mensagens de sucesso/falha) não muda.

**Critérios de aceite:**
- [ ] Rodando com `--mode dry`, nenhum processo `mitmdump` é criado (checável via lista de processos durante um teste automatizado, ou logging explícito).
- [ ] Rodando com `--mode main` (default), o `mitmdump` sobe antes da execução e é derrubado ao final, mesmo se `engine.run()` lançar exceção.
- [ ] O comportamento de mensagens de sucesso/falha impresso ao final continua idêntico ao atual.

---

## T18 — Checklist final de código morto

**Depende de:** todas as tasks anteriores (T01–T17).
**Arquivos envolvidos:** todo o repositório (busca textual, não edição).

**Contexto:** conferência final de que nada do que foi substituído ao longo do plano ficou esquecido para trás — item explicitamente pedido: nenhum código morto na entrega final.

**Estado esperado depois de rodar esta checagem — busca no repositório inteiro, sem nenhuma ocorrência de:**
- [ ] `TokenTrace`
- [ ] `TokenTracker._generate_curl_template`
- [ ] `CurlGenerator._find_token_traces`, `_header_and_cookie_traces`, `_body_traces`, `_get_trace_for_value`, `_find_token_id_by_value`, `_trace_comment`
- [ ] Suporte ao formato antigo de placeholder (`{{token_id}}` sem prefixo) em `session_store.py`
- [ ] `RequestBuilder.write_curl`
- [ ] `HttpTransport` / `http_transport.py`
- [ ] `Engine.update_session_tokens`, `_should_refresh_token`, `_refresh_token`
- [ ] Qualquer import não utilizado deixado para trás em arquivos tocados por este plano (`curl_generator.py`, `request_builder.py`, `engine.py`, `session_store.py`, `session.py`)

**Critério de aceite final:** todos os itens acima confirmados ausentes do repositório.
