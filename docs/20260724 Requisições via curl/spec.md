# SPEC — Tokens dinâmicos, curl templates e transporte via mitmproxy

## 0. Contexto e princípios norteadores

- O curl salvo em disco deve ser um **template reprocessável**: valores de token trocados por `{{extractor:token_id}}`, nunca o valor literal.
- Não deve existir duas lógicas paralelas de resolução de token (uma "live", outra "standalone") — uma única implementação, num arquivo próprio, reaproveitada nos dois contextos.
- A execução real de cada step deve rodar o `curl` de fato (não `httpx`), via proxy mitmproxy, porque o objetivo final do projeto é permitir reexecutar o fluxo inteiro a partir dos arquivos `.curl.sh` salvos — um step específico ou todos.
- Nenhuma lib de terceiros nova para geração/escaping de curl — `shlex.quote` (stdlib) resolve.
- Sem código morto ao final: toda implementação substituída é removida, não deixada ao lado.

---

## 1. Escopo

Models (`TokenLocation`, `TokenTrace`, `ProjectConfig`, `WorkspaceDir`) · `SessionStore.render()` · `PlaceholderApplier` · `CurlGenerator` (reescrita) · `TokenTracker.analyze_step` · `TokenResolver` (novo, extraído de `Engine`) · `ExtractorRunner` (pequeno acréscimo) · `RequestBuilder` · Transporte novo baseado em curl+mitmproxy (substitui `HttpTransport`) · Addon do mitmproxy (novo) · `MitmProxyOrchestrator` (novo) · `Workspace` · `Engine` / `DryEngine` · `CliHandlers`.

## 2. Fora de escopo

- `CandidateResolver` e o loop TDD com LLM — tratados como corretos, não tocados.
- Implementação de fato de uma ferramenta CLI de "replay standalone a partir de curls salvos" — este spec deixa a base pronta (extractors autocontidos em disco, `TokenResolver` reaproveitável) mas não entrega essa ferramenta.
- `success_criteria` / `Validator` — não afetados pela troca de transporte.

---

## 3. Mudanças de modelo

### 3.1 `TokenLocation` (enum, `session.py`)
Adicionar `URL_PARAM = "UrlParam"` — cobre token detectado/aplicado na query string da URL.

### 3.2 `TokenTrace` — **remover a classe inteira**
Uso confirmado como exclusivo do `CurlGenerator` atual, que deixa de precisar dela.

### 3.3 `DynamicToken`, `StepAnalysis` — sem mudança estrutural
`StepAnalysis` deixa de ser retorno descartado e passa a ser efetivamente consumido por `Engine._process_entry`.

### 3.4 `ProjectConfig` (`config.py`)
Adicionar `proxy_port: Optional[int] = None`. Ausente → porta livre escolhida automaticamente em runtime (não é erro).

### 3.5 `WorkspaceDir` (enum)
Adicionar um novo membro para o arquivo de captura fixo do addon (ex.: `MITM_CAPTURE = "mitm_capture"`), e correspondente helper em `Workspace` (ex.: `Workspace.mitm_capture_file()`, caminho fixo dentro desse diretório, sempre sobrescrito).

Adicionar também `Workspace.curl_file(index) -> Path`, análogo a `request_file`/`response_file`, formalizando o padrão `req_{index:04d}.curl.sh` que hoje está hardcoded dentro de `RequestBuilder.write_curl` (método que será removido — ver §12).

---

## 4. `SessionStore.render()`

- Novo padrão de regex: `\{\{extractor:([a-f0-9]+)\}\}`.
- Substitui cada ocorrência pelo valor em `self.state.tokens[token_id]`.
- **Remove por completo** o suporte ao formato antigo `{{token_id}}` — sem fallback.
- Token ausente em `state.tokens` → placeholder permanece literal (sem exceção).
- `render_dict` inalterado (depende só de `render`).

---

## 5. `PlaceholderApplier`

- `_placeholder_for`: gera `{{extractor:{token_id}}}`.
- `apply()`: ordena `tokens` por `len(token.current_value)` decrescente antes de iterar — evita que a substituição de um token cujo valor é substring de outro corrompa o placeholder do segundo.
- Novo método `_replace_in_url(request, value, placeholder)`, mesmo padrão dos já existentes (`_replace_in_headers/cookies/body`) — substring match, chamado dentro de `_apply_token` junto aos demais.
- Quando a substituição ocorre na URL, o campo de localização do `DynamicToken` correspondente deve refletir `TokenLocation.URL_PARAM`.

---

## 6. `CurlGenerator` — reescrita completa

**Nova assinatura:** `generate(request: StepRequest, tokens: List[DynamicToken]) -> str` — sem `session_store`, sem `step_index`.

**Responsabilidade:** puramente formatação. Não detecta tokens — assume que `request` já foi processado por quem o chamou (com ou sem placeholders, dependendo do uso — ver §6.3).

### 6.1 Regras de formatação
- Headers e cookies iterados **separadamente**, nunca via `{**headers, **cookies}` (resolve bug de colisão de chave com nome igual entre header e cookie).
- Cookies combinados numa única flag: `--cookie 'chave1=valor1; chave2=valor2'`.
- Todo valor inserido na string final passa por `shlex.quote()` (header completo, cookie combinado, body, URL).
- Body mantém `--data-binary`.

### 6.2 Comentários de origem
Um comentário por item de `tokens`, agregados **no topo do bloco gerado** (antes de `curl -X ...`):
```
# Token {token_id} comes from response of step {origin_step}
```
Se `tokens` for uma lista vazia, nenhum comentário é emitido.

### 6.3 Reaproveitamento para dois casos de uso distintos
`CurlGenerator` é chamado em dois contextos diferentes, sem duplicar lógica:
- **Template (persistido em disco):** chamado com o `request` já mutado pelo `PlaceholderApplier` (contém `{{extractor:...}}`) e a lista real de `tokens` da análise — gera o curl com placeholders + comentários.
- **Literal (usado para executar de fato):** chamado com o `final_request` já resolvido (sem placeholders) e `tokens=[]` — gera um curl 100% literal, sem comentários, usado internamente pelo transporte novo para montar o comando a ser executado via `subprocess`.

### 6.4 Remoções dentro de `CurlGenerator`
`_find_token_traces`, `_header_and_cookie_traces`, `_body_traces`, `_get_trace_for_value`, `_find_token_id_by_value`, `_trace_comment` (versão antiga baseada em `TokenTrace`) — todos removidos.

---

## 7. `TokenTracker.analyze_step`

- Chama `CurlGenerator().generate(step.request, tokens)` (uso "template", §6.3) para preencher `StepAnalysis.curl_template`.
- Remove `_generate_curl_template` (staticmethod) — versão pobre, sem cookies/body/comentários, substituída pela chamada acima.
- Retorno (`StepAnalysis`) passa a ser efetivamente consumido por `Engine` (ver §11).

---

## 8. `TokenResolver` (novo arquivo, ex.: `har_reproducer/tracking/token_resolver.py`)

Extração de `Engine.update_session_tokens` + `Engine._should_refresh_token` + `Engine._refresh_token`, sem mudança de lógica interna — só de localização/dono.

- Construtor recebe `session_store: SessionStore` (constrói seu próprio `ExtractorRunner` internamente, encapsulando essa dependência).
- Método público (ex.: `resolve_all()`) substitui `Engine.update_session_tokens`; mesma lógica: para cada `Extractor` verificado e com `origin_step`, se `Workspace.response_file(origin_step)` existir, reexecuta via `ExtractorRunner` e atualiza `session_store.state.tokens`.
- `Engine` passa a ter `self.token_resolver: TokenResolver`, chamado no lugar do método antigo (removido de `Engine`).

**Nota sobre reuso standalone:** o corte é limpo porque `ExtractorRunner` não depende de estado do `Engine` (confirmado em §9) — mas o "resolver standalone" completo (script separado que roda depois do processo terminar) não é entregue neste spec; o que este item garante é que a peça de resolução viva num único lugar, pronta para ser chamada por essa futura ferramenta sem reescrever nada. Inclusão formal desta extração no escopo deste spec: confirmada.

---

## 9. `ExtractorRunner` — acréscimo pequeno

Cada `extract_{token_id}.py` já é autocontido (código + `step_index` embutidos no texto do arquivo, resolvendo o path da response via `Path(__file__).resolve().parent.parent`) — não precisa do model `Extractor` em memória para rodar, só do path do arquivo.

Adicionar um método que executa um extractor **já existente em disco**, dado só o `token_id` (sem precisar do model `Extractor`):
- Resolve `Workspace.extractor_file(token_id)`.
- Se o arquivo existir, delega para a mesma lógica interna hoje presa em `_execute_extractor_script` (que já não depende do model).
- Se não existir, retorna `None`.

Isso é o que viabiliza, no futuro, resolver um curl salvo sem precisar reconstruir o registry inteiro em memória — o arquivo `.py` na pasta `extractors/` já é a fonte da verdade.

---

## 10. `RequestBuilder`

- `build_final_request` — mantido sem mudanças (segue resolvendo `step.request`, que já contém placeholders após `analyze_step`, para valores literais via `session_store.render_dict`/`render`).
- `write_curl` — **removido por completo**. O `curl_template` já é computado em `analyze_step` (§7) e fica disponível em `StepAnalysis` antes mesmo do request ser executado; não há motivo para `RequestBuilder` chamar `CurlGenerator` de novo. A persistência do arquivo `.curl.sh` passa a ser responsabilidade de `Engine` (§11), condicionada ao resultado da execução.
- Import de `CurlGenerator` removido deste arquivo.

---

## 11. Transporte novo — substitui `HttpTransport`

Novo arquivo (ex.: `har_reproducer/reproduction/curl_http_transport.py`), mesma interface pública de hoje: `send_request(final_request: StepRequest, step_index: int) -> StepResponse`.

### 11.1 Sequência de execução
1. Monta o curl **literal** (sem placeholders) a partir de `final_request`, via `CurlGenerator().generate(final_request, tokens=[])` (§6.3).
2. Executa via `subprocess.run`, com:
   - `--proxy http://127.0.0.1:{porta}` (porta vinda de `ProjectConfig.proxy_port` ou escolhida livre em runtime — ver §13).
   - `--cacert {caminho do CA do mitmproxy}` — **nunca** `-k`/`--insecure`. Caminho fixo: raiz do projeto (ex.: `mitmproxy-ca-cert.pem` na raiz) — o `mitmdump` deve ser iniciado apontando seu `confdir` para lá, para que o CA seja gerado/lido sempre no mesmo lugar, independente de onde o usuário rode o comando.
   - **Sem** `-L`/`--location` (não segue redirect — mantém paridade com `follow_redirects=False` do `HttpTransport` atual e evita múltiplos flows numa única chamada, o que quebraria a premissa de "um arquivo de captura por request").
   - Timeout fixo de 30s.
   - Flags para descartar o corpo da resposta no stdout do próprio `curl` (o corpo real vem da captura HAR, não da saída do processo) — só o exit code e o tempo de execução importam aqui.
3. Se o `curl` falhar (exit code ≠ 0, timeout, exceção) → constrói `StepResponse` de erro no mesmo formato do `HttpTransport._build_error_response` atual, com `cookies={}` (sem equivalente a `client.cookies` nesse modelo).
4. Se o `curl` retornar com sucesso → lê o arquivo de captura fixo (`Workspace.mitm_capture_file()`, escrito pelo addon — ver §12), sincronamente, logo após o `subprocess.run` retornar (sem polling assumido como necessário, mas com uma pequena rede de segurança de poucas tentativas/curto backoff antes de falhar, dado que o comportamento exato de timing do addon ainda não foi validado empiricamente).
5. Extrai a única entry do HAR capturado (`HARParser.get_entries(...)[0]`) e reaproveita `HARParser.parse_entry(entry, step_index).response` para construir o `StepResponse` final — mesma lógica de parsing já usada para o `.har` original, sem duplicação.

### 11.2 Remoção
`http_transport.py` (implementação baseada em `httpx.Client`) é removida por completo.

---

## 12. Addon do mitmproxy (novo — não existe rascunho ainda)

Arquivo novo (ex.: `har_reproducer/reproduction/mitm_addon.py`), rodando dentro do processo `mitmdump`.

**Contrato de saída (necessário para compatibilidade com `HARParser`):**
- A cada resposta capturada (hook `response`), monta um envelope **HAR oficial completo** com uma única entry: `{"log": {"entries": [entry]}}` — usando o schema padrão (headers como lista `{name, value}`, cookies como lista `{name, value}`, `postData.text`, `content.text`/`encoding`, `status`, `redirectUrl`).
- Escreve esse envelope **sempre no mesmo caminho fixo** (`Workspace.mitm_capture_file()`), sobrescrevendo a cada request — sem indexação própria, sem inspecionar headers do request para descobrir a que step pertence (essa correlação é feita do lado do transporte, que já sabe o `step_index` via parâmetro — §11.1).
- Escrita **síncrona**, dentro do próprio hook — nenhuma fila, nenhuma escrita assíncrona.

**Risco residual, não coberto por este spec:** o comportamento exato de timing do mitmproxy (se o hook `response` garante que a escrita em disco termina antes do `curl` do lado do cliente considerar a resposta completa) não foi validado — depende de teste de ponta a ponta durante a implementação. O retry curto mencionado em §11.1 existe como mitigação, não como certeza.

---

## 13. `MitmProxyOrchestrator` (novo — ex.: `har_reproducer/reproduction/mitm_proxy_orchestrator.py`)

- Sobe `mitmdump` com o addon (§12) como subprocess, numa porta livre se `ProjectConfig.proxy_port` não estiver definido, ou na porta configurada caso esteja.
- Aguarda o processo ficar pronto (health check síncrono — tentativa de conexão na porta, com timeout curto, antes de prosseguir).
- Envolve a chamada a `engine.run()` (não o `Engine.__init__`/lógica interna) — ver §16, ponto de entrada exato.
- Em `finally` (sucesso ou exceção durante `run()`), derruba o processo do `mitmdump`.

---

## 14. `Engine` / `DryEngine`

### 14.1 Indicador de uso de rede
Adicionar `USES_NETWORK: ClassVar[bool] = True` em `Engine`. `DryEngine` sobrescreve para `False` — ele nunca chama transporte nenhum (`execute_step` já é totalmente sobrescrito e devolve `step.response` original do `.har`, sem tocar rede).

### 14.2 Mudanças de fluxo em `_process_entry`/`execute_step`/`_attempt_step`
Nova ordem, descrita por etapas (sem código):

1. `analyze_step(step, first_entry)` roda **uma vez** por entry, antes do loop de tentativas — retorna `analysis: StepAnalysis` (contém `curl_template` já pronto e `dynamic_tokens`).
2. `token_resolver.resolve_all()` roda (substitui `update_session_tokens()`).
3. Dentro do loop de tentativas (`execute_step`, mantendo `MAX_STEP_ATTEMPTS`):
   - `build_final_request(step)` resolve os placeholders para valores literais atuais.
   - Transporte novo executa a request literal.
   - Se resposta recuperável (`RECOVERABLE_STATUS_CODES`) e não é a última tentativa → `handle_recovery` (chama `token_resolver.resolve_all()` de novo) e repete.
4. **Depois** do loop de tentativas terminar (sucesso ou esgotamento), `_persist_step` grava request/response como hoje, e — **só se a resposta obtida não for a de erro de transporte (`status_code != 0`)** — grava `analysis.curl_template` em `Workspace.curl_file(index)`. Numa falha total de transporte, nenhum arquivo de curl é escrito para aquele index (evita persistir um template junto de uma tentativa que nunca chegou a bater na rede de verdade). Critério confirmado.

### 14.3 Remoções em `Engine`
`update_session_tokens`, `_should_refresh_token`, `_refresh_token` — movidos para `TokenResolver` (§8), removidos daqui.

---

## 15. `CliHandlers.handle_run`

- Antes de instanciar/rodar o engine: consulta `engine_cls.USES_NETWORK` (a classe resolvida por `EngineFactory` a partir do `EngineMode`) — se `True`, envolve a chamada com `MitmProxyOrchestrator`; se `False` (caso `DryEngine`), roda `engine.run()` direto, sem subir proxy nenhum.

---

## 16. Lista consolidada de remoções (checklist "sem código morto")

| Item | Arquivo |
|---|---|
| `TokenTracker._generate_curl_template` | token_tracker.py |
| `TokenTrace` (classe inteira) | models/session.py |
| `CurlGenerator._find_token_traces` | curl_generator.py |
| `CurlGenerator._header_and_cookie_traces` | curl_generator.py |
| `CurlGenerator._body_traces` | curl_generator.py |
| `CurlGenerator._get_trace_for_value` | curl_generator.py |
| `CurlGenerator._find_token_id_by_value` | curl_generator.py |
| `CurlGenerator._trace_comment` (versão antiga) | curl_generator.py |
| Suporte a `{{token_id}}` (formato antigo) | session_store.py `render()` |
| Parâmetro `session_store`/`step_index` em `CurlGenerator.generate` | curl_generator.py |
| `RequestBuilder.write_curl` | request_builder.py |
| `HttpTransport` (classe inteira, baseada em `httpx`) | http_transport.py |
| `Engine.update_session_tokens`, `_should_refresh_token`, `_refresh_token` | engine.py (movidos para `TokenResolver`) |

## 17. Lista de arquivos novos

- `har_reproducer/tracking/token_resolver.py` — `TokenResolver`
- `har_reproducer/reproduction/curl_http_transport.py` — substitui `HttpTransport`
- `har_reproducer/reproduction/mitm_addon.py` — addon do mitmproxy
- `har_reproducer/reproduction/mitm_proxy_orchestrator.py` — `MitmProxyOrchestrator`

---

## 18. Pontos revisados e confirmados

1. **Critério de "sucesso" para persistir o curl template** (§14.2) — `status_code != 0`. Confirmado.
2. **Timing do addon** (§12) — abordagem de retry curto como mitigação aceita; validação definitiva só com teste real durante a implementação, permanece como risco técnico conhecido (não bloqueia o spec).
3. **`TokenResolver` como entrega formal deste spec** — confirmado, faz parte.
4. **Localização do CA do mitmproxy** — raiz do projeto (não o padrão `~/.mitmproxy`). Ajustado em §11.1: `mitmdump` deve ser iniciado com `confdir` apontando para a raiz do projeto.
