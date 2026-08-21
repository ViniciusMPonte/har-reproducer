# Plano de Implementação — Descompressão do Corpo Capturado pelo Mitmproxy

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## Decisão do ponto aberto da spec (§6)

- **Cobertura de ponta a ponta (estender `CannedHttpHandler` para servir rota comprimida):
  fica fora.** O teste de unidade da T02 já reproduz o defeito e a correção com fidelidade
  aos codecs reais (`mitmproxy.net.encoding`, os mesmos que o `mitmdump` de produção usa).
  Ensinar o servidor de teste a negociar compressão HTTP de verdade é infraestrutura nova,
  maior que o defeito corrigido, sem ganho de confiança proporcional.
- **O defeito irmão do request** (`_build_post_data`) está documentado em
  `problemas-encontrados.md`, nesta mesma pasta, e não vira task. Sem `Content-Encoding` de
  request observado em nenhuma das duas gravações da investigação, não há caso medido que
  justifique corrigir agora.

---

## [T01] — `tests/unit/test_mitm_addon.py`: teste vermelho que reproduz o mojibake

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/unit/test_mitm_addon.py` (novo)

**Contexto:**
`MitmAddon` não tem nenhum teste de unidade hoje — o único caminho que a exercitaria é a
suíte de rede (`@pytest.mark.slow`), e ela nunca serve resposta comprimida
(`CannedResponse.body` é `str` puro, sem noção de `Content-Encoding`). Esta task escreve o
teste que prova o defeito **antes** de tocar em `mitm_addon.py` — ele tem que falhar pelo
motivo certo contra o código atual.

**Estado atual:**
- `MitmAddon._build_content` (`har_reproducer/reproduction/mitm_addon.py:90-101`) usa
  `response.raw_content`, que para uma resposta com `Content-Encoding: gzip` contém os
  bytes **comprimidos**, não o texto original.
- Não existe `tests/unit/test_mitm_addon.py`.
- ⚠️ **`mitm_addon.py:110` tem `addons = [MitmAddon()]` no nível do módulo** — é a
  convenção do mitmproxy para descobrir o addon, e instancia `MitmAddon()` (que chama
  `_resolve_capture_path`, `:14-21`) **no momento do import**. Verificado: importar o
  módulo sem a env var `MitmEnv.CAPTURE_PATH_ENV_VAR` definida no processo lança
  `RuntimeError` imediatamente. Como isto nunca foi importado fora do processo do
  `mitmdump` (que a `MitmProxyOrchestrator` sempre lança com a env var setada), é a
  primeira vez que o módulo é importado dentro do processo do pytest — e vai falhar no
  import se a env var não estiver definida antes dele.

**Estado esperado depois:**
- Arquivo novo, no formato dos testes vizinhos (`tests/unit/test_curl_http_transport.py`,
  `tests/unit/test_mitm_proxy_orchestrator.py`): sem classe de teste, funções `test_*` de
  módulo (única isenção ao "nada solto no módulo" do guia de estilo, documentada ali),
  tipos explícitos em toda variável.
- ⚠️ **No topo do arquivo, antes do `from har_reproducer.reproduction.mitm_addon import
  MitmAddon`**, definir a env var com um valor qualquer (o teste nunca escreve nela,
  porque só chama o `@staticmethod _build_content`):
  ```python
  import os

  from har_reproducer.reproduction.mitm_env import MitmEnv

  os.environ.setdefault(MitmEnv.CAPTURE_PATH_ENV_VAR, "/tmp/mitm_addon_test_capture.json")

  from har_reproducer.reproduction.mitm_addon import MitmAddon
  ```
  Verificado que isso é suficiente e que nenhuma alteração em `mitm_addon.py` é necessária
  para viabilizar o teste — a instanciação no import é inofensiva uma vez que a env var
  existe; `_build_content` não usa `self.capture_path` de forma alguma. Não "corrigir" o
  `addons = [MitmAddon()]` para evitar isso: é convenção exigida pelo mitmproxy, não
  descuido do projeto.
- Uma função helper `_response_with_body` (ou nome equivalente) que constrói um
  `mitmproxy.http.Response` para teste:
  ```python
  def _response_with_body(body: bytes, content_encoding: Optional[str] = None) -> Response:
      response: Response = Response.make(200, b"", {"content-type": "text/plain"})
      if content_encoding is not None:
          response.headers["content-encoding"] = content_encoding
      response.raw_content = body
      return response
  ```
- ⚠️ **Não passar `body` como o argumento `content` de `Response.make`** quando
  `content_encoding` também for passado — o setter de `.content` **re-comprime** o valor
  recebido conforme o header já presente, gerando compressão dupla. Sempre `make(...)` com
  corpo vazio e headers, depois atribuir `raw_content` diretamente — é o que simula bytes
  chegando pela rede sem reprocessamento.
- Teste principal, vermelho contra o código atual:
  ```python
  def test_build_content_decompresses_gzip_body_before_deciding_text_or_base64() -> None:
      original: bytes = b"function loadChart(){return 1;}"
      response: Response = _response_with_body(gzip.compress(original), content_encoding="gzip")

      content: Dict[str, Any] = MitmAddon._build_content(response)

      assert content == {"text": original.decode("utf-8"), "mimeType": "text/plain"}
  ```
  Contra o código atual, isso falha: `_build_content` devolve
  `{"text": "<base64 dos bytes gzip>", "mimeType": "text/plain", "encoding": "base64"}`,
  porque `gzip.compress(original)` quase certamente não decodifica como UTF-8 e cai no
  ramo de base64 — o que já é, por si, evidência do defeito (o `mimeType` bate mas o
  `encoding` e o `text` não).
- Testes adicionais, cobrindo os casos de borda da spec §5 (podem estar todos vermelhos
  ainda nesta task, já que nenhum toca o código):
  - `test_build_content_decompresses_brotli_body` — mesma forma, com
    `content_encoding="br"` e a biblioteca `brotli` (já é dependência transitiva do
    `mitmproxy`, verificado instalada no `.venv` do projeto).
  - `test_build_content_falls_back_to_raw_when_content_encoding_is_incoherent` — corpo que
    não é gzip de verdade com `content-encoding: gzip`; a asserção é que o resultado é
    igual ao que se obteria chamando `_build_content` sobre o mesmo corpo **sem** o header
    (cai no mesmo caminho de UTF-8-ou-base64 que existe hoje, sem lançar exceção).
  - `test_build_content_unchanged_when_no_content_encoding_header` — corpo de texto puro
    sem `content-encoding`: resultado idêntico ao comportamento de hoje.
  - `test_build_content_binary_body_without_encoding_still_falls_back_to_base64` — corpo
    binário genuíno (ex.: `bytes(range(256))`), sem `content-encoding`: continua indo para
    base64, exatamente como hoje — é a garantia de não-regressão de que imagens/fontes não
    passam a ser tratadas diferente.
  - `test_build_content_returns_empty_text_for_empty_body` — `raw_content` vazio continua
    devolvendo `{"text": "", "mimeType": ...}`.

**Critérios de aceite:**
- [x] `test_build_content_decompresses_gzip_body_before_deciding_text_or_base64` falha
      contra o código atual (`git stash` da T02, ou rodar antes de implementá-la) com uma
      mensagem que mostra `encoding: "base64"` no resultado obtido.
- [x] Os seis testes acima existem e todos falham ou passam **pelo motivo certo** contra o
      código atual: os que dependem de descompressão (gzip, brotli) falham; os que não
      dependem (sem encoding, binário sem encoding, corpo vazio) já passam, porque
      `get_content(strict=False)` sem `Content-Encoding` e `raw_content` são idênticos —
      registrar explicitamente no PR/commit quais passam já no vermelho, para não confundir
      com teste mal escrito.
- [x] Nenhuma modificação em `har_reproducer/`.

---

## [T02] — `MitmAddon._build_content`: descomprimir antes de decidir texto ou base64

**Depende de:** T01 (os testes que esta task faz passar).
**Arquivos envolvidos:** `har_reproducer/reproduction/mitm_addon.py` (`MitmAddon._build_content`)

**Contexto:**
A fonte dos bytes em `_build_content` é `response.raw_content` (nunca descomprimido). O
mitmproxy já expõe `response.get_content(strict=False)`, que descomprime conforme
`Content-Encoding` e nunca lança — degradando para o bruto exatamente como `raw_content` já
fazia quando a descompressão não é possível. Troca de uma linha, mais a variável local para
não descomprimir duas vezes.

**Estado atual:**
```python
@staticmethod
def _build_content(response: Response) -> Dict[str, Any]:
    mime_type: str = response.headers.get("content-type", "")

    if not response.raw_content:
        return {"text": "", "mimeType": mime_type}

    try:
        text: str = response.raw_content.decode("utf-8")
        return {"text": text, "mimeType": mime_type}
    except UnicodeDecodeError:
        encoded_text: str = base64.b64encode(response.raw_content).decode("ascii")
        return {"text": encoded_text, "mimeType": mime_type, "encoding": "base64"}
```

**Estado esperado depois:**
```python
@staticmethod
def _build_content(response: Response) -> Dict[str, Any]:
    mime_type: str = response.headers.get("content-type", "")
    content: Optional[bytes] = response.get_content(strict=False)

    if not content:
        return {"text": "", "mimeType": mime_type}

    try:
        text: str = content.decode("utf-8")
        return {"text": text, "mimeType": mime_type}
    except UnicodeDecodeError:
        encoded_text: str = base64.b64encode(content).decode("ascii")
        return {"text": encoded_text, "mimeType": mime_type, "encoding": "base64"}
```
- ⚠️ **Não trocar por `response.content`** (a property sem argumento) — ela usa
  `strict=True` por padrão e lançaria `ValueError` num `Content-Encoding` incoerente,
  quebrando o hook `response(flow)` a cada resposta desse tipo em vez de degradar. Tem que
  ser `get_content(strict=False)`, chamado explicitamente.
- ⚠️ Nenhuma outra linha de `mitm_addon.py` muda — `_build_response`, `_headers_list` e o
  resto continuam gravando o header `content-encoding` como veio, que é o formato que todo
  HAR exportado de navegador já usa (corpo descomprimido ao lado do header original).

**Critérios de aceite:**
- [x] Todos os testes de `tests/unit/test_mitm_addon.py` (T01) passam.
- [x] `_build_content` de um corpo gzip válido devolve `{"text": <original decodificado>,
      "mimeType": ...}` — sem `encoding: "base64"`.
- [x] `_build_content` de um corpo brotli válido: mesmo resultado.
- [x] Não-regressão: `_build_content` de um corpo sem `content-encoding` continua
      byte-idêntico ao comportamento anterior à mudança, testado/comparado antes e depois.
- [x] Não-regressão: `_build_content` de um corpo binário genuíno sem `content-encoding`
      continua caindo em `encoding: "base64"`.
- [x] Não-regressão: `pytest tests/unit -q` verde.
- [x] Não-regressão: `pytest --runslow -q` verde, os 27 cenários golden byte-idênticos —
      esperado, já que `CannedHttpHandler` nunca serve resposta comprimida (nenhum deles
      exercita este caminho, o que é consistente com a spec §2, "MitmAddon").
