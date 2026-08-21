# Spec — Descompressão do Corpo Capturado pelo Mitmproxy

## 0. Sumário

Quando a resposta real de um servidor vem comprimida (`Content-Encoding: br`/`gzip`), o
projeto grava em `real_responses/` o corpo **ainda comprimido**, disfarçado de texto UTF-8
com até 44% dos caracteres substituídos por `�` (U+FFFD). A causa é uma linha em
`MitmAddon._build_content`: ela lê `response.raw_content` — os bytes exatamente como
chegaram pela rede — quando devia ler o corpo já descomprimido que o próprio mitmproxy
disponibiliza. A correção é trocar essa fonte de bytes; o resto do pipeline (base64 para
binário genuíno, texto para o resto) já está certo e não muda.

Isso importa porque toda comparação entre a época do HAR e a época da execução lê o corpo
como texto. Uma resposta comprimida na execução e descomprimida no HAR (que é como todo
HAR exportado de navegador já vem) faz qualquer comparação concluir "o valor mudou", quando
na verdade ninguém comparou nada — comparou-se texto contra lixo binário. É pré-requisito
de qualquer decisão futura que compare respostas entre duas execuções.

### Glossário

| termo | significado nesta spec |
|---|---|
| **corpo comprimido / corpo descomprimido** | O corpo de uma resposta HTTP como ele viaja na rede (comprimido, se o servidor usa `Content-Encoding`) versus o mesmo corpo depois de aplicado o algoritmo de descompressão declarado nesse header. |
| **`raw_content`** | Atributo do `Response` do mitmproxy: os bytes exatamente como chegaram pela rede, nunca descomprimidos, nunca lança exceção. |
| **`get_content(strict=False)`** | Método do `Response` do mitmproxy que devolve o corpo **descomprimido** conforme `Content-Encoding`; se a descompressão falhar (header incoerente com o conteúdo), devolve os bytes crus em vez de lançar. |
| **mojibake** | Texto corrompido produzido ao decodificar bytes que não são texto (aqui, bytes comprimidos) como se fossem UTF-8 com `errors="replace"` — cada byte problemático vira `�` (U+FFFD). |
| **época do HAR / época da execução** | A resposta gravada no `.har` original (`original_responses/`) versus a resposta obtida ao reproduzir o fluxo agora (`real_responses/`). Todo HAR exportado de navegador grava o corpo **já descomprimido**, por especificação do formato HAR. |

---

## 1. Objetivo

### 1.1 O problema, com causa exata

`har_reproducer/reproduction/mitm_addon.py:90-101`:

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

`response.raw_content` é o corpo **exatamente como chegou pela rede** — se o servidor
respondeu com `Content-Encoding: br`, esses bytes são brotli comprimido, não texto. O
mitmproxy já traz o descompressor pronto: `Response.get_content(strict=False)` devolve o
corpo decodificado conforme o `Content-Encoding`, e nunca lança — se a descompressão falhar,
devolve os bytes crus, do mesmo jeito que `raw_content` já fazia. Verificado com os
codecs reais instalados neste projeto (`mitmproxy.net.encoding`, que cobre gzip, brotli,
deflate e zstd):

```
corpo original: b'function loadChart(){return xxx...xxx;}'   (529 bytes)
comprimido com gzip: 60 bytes

MitmAddon._build_content de hoje (usa raw_content):
    UnicodeDecodeError -> cai no base64 -> grava o comprimido em base64

HARParser.decode_body, ao ler esse base64 de volta (fs_io/har_parser.py:41-49):
    base64.b64decode(...).decode("utf-8", errors="replace")
    -> decodifica o base64 e recai nos MESMOS 60 bytes comprimidos
    -> decodificar bytes comprimidos como UTF-8 com errors="replace" produz:
       '\x1f�\x08\x00\r)�j\x02�K+�K.�...'
    -> 54 caracteres, 17 são U+FFFD (31%)

com response.get_content(strict=False) no lugar de raw_content:
    descomprime primeiro -> 'function loadChart(){return xxx...xxx;}'
    decodifica limpo como UTF-8 -> bate byte a byte com o original
```

O corpo original **nunca é recuperado** pelo caminho de hoje — a descompressão simplesmente
não acontece em lugar nenhum do pipeline. `HARParser.decode_body`, que faz o base64 → utf-8
com `errors="replace"`, está correto para o que ele foi desenhado a fazer: decodificar
binário genuíno (imagem, por exemplo) da melhor forma possível para permitir busca de
substring. O defeito é que um corpo de **texto comprimido** chega até ele como se fosse
binário genuíno.

### 1.2 O tamanho do problema, medido

Sobre o workspace de referência (`arquivos-har/ws_20260817_main`, HAR de 324 entries) e sobre
o workspace de uma gravação anterior do mesmo site (238 entries, preservado em
`docs/20260820 Investigação da Porta de Admissão/`), com
`docs/20260820 Investigação da Porta de Admissão/medições/epocas.py`:

| | gravação atual (324 entries) | gravação anterior (238 entries) |
|---|---|---|
| corpos ilegíveis (>5% de caracteres U+FFFD) na época do HAR | 26/311 | 11/98 |
| corpos ilegíveis na época da execução | 26/311 | **19/102** |
| respostas legíveis numa época e **ilegíveis só na outra** | **0** | **4** |
| `ETag` idêntico entre as épocas | 285/285 | 210/210 |
| `Last-Modified` idêntico entre as épocas | 292/296 | 215/218 |

As 26 (atual) e 11 (anterior) respostas ilegíveis **nas duas épocas** são conteúdo binário
genuíno (imagens, fontes) — correto ficarem ilegíveis como texto, e não são o defeito desta
etapa. As **4 que só ficam ilegíveis na execução**, na gravação anterior, são:

```
step  13 enc=br    HAR  80821 chars (0% U+FFFD) | execução  23259 chars (43% U+FFFD)
step  14 enc=gzip  HAR   1272 chars (0% U+FFFD) | execução    430 chars (39% U+FFFD)
step  76 enc=br    HAR 102025 chars (0% U+FFFD) | execução  17750 chars (44% U+FFFD)
step 159 enc=br    HAR 208522 chars (0% U+FFFD) | execução  67879 chars (44% U+FFFD)
```

Mesmo recurso, mesmo `Content-Encoding` declarado, a época do HAR (exportada por um
navegador, que descomprime antes de escrever o `.har`, por especificação do formato) está
limpa e a época da execução (passada por este projeto) está corrompida. Não há steps deste
tipo na gravação atual — é uma questão de qual recurso comprimido apareceu em cada gravação,
não de o defeito ter sido corrigido; o mecanismo (§1.1) independe do conteúdo.

Uma investigação anterior atribuiu esses 4 casos a "bundles de CDN de terceiros que encolhem
entre as épocas" — os números de tamanho pareciam sustentar isso (80821 → 23259 caracteres).
**Essa foi uma leitura errada, corrigida aqui.** O corpo não encolhe: ele é o mesmo recurso,
e a diferença de tamanho é só o efeito de codificar em UTF-8-com-substituição um blob de
bytes que, sem compressão, teria ~3,5× mais bytes que caracteres visíveis depois da
substituição. `docs/20260820 Investigação da Porta de Admissão/revisões-adversariais.md`
(§1.2) registra a correção.

### 1.3 Por que isso é pré-requisito de qualquer decisão futura

Qualquer componente que compare o corpo de duas respostas do mesmo recurso em épocas
diferentes — origem de token, detecção de mudança, o que for — vai ler "o texto mudou" nesses
4 casos, quando o que houve foi falha de descompressão, não mudança de conteúdo. O defeito
não depende de nenhuma feature nova: ele já afeta qualquer coisa que hoje leia
`real_responses/` de um recurso comprimido — inclusive, hoje, os agentes de extração que
usam o corpo da resposta como amostra (`TokenLocationDetector`, os agentes de
`tracking/`), que podem falhar em achar um valor dentro de um corpo que devia estar limpo.

### 1.4 Fora de escopo

- **O corpo de request** (`_build_post_data`, `mitm_addon.py:82-86`) tem a mesma classe
  de defeito, do lado do request — sem descompressão e sem fallback para base64. Medido: 0
  das entries dos dois HARs desta investigação têm `Content-Encoding` no request, então não
  há evidência de que isso produza mojibake hoje. Detalhado, com o que motivaria reabrir o
  assunto, em `problemas-encontrados.md` nesta mesma pasta — não corrigido aqui sem caso
  medido.
- **`HARParser.decode_body`** não muda. Ele está correto para o que decodifica — binário
  genuíno chegando como base64. O defeito é o que chega até ele vindo de `MitmAddon`, não
  como ele decodifica.
- **Regravar workspaces existentes.** Esta etapa corrige a captura daqui para a frente; um
  workspace já gerado com o defeito não é migrado. É preciso rodar `run` de novo.
- **A porta de admissão e o casamento por fragmento** (item 11 do backlog em
  `docs/20260817 Reteste do Otimizador contra Servidor Real/correcoes.md`) continuam fora
  desta etapa. Esta é o pré-requisito deles, não eles.

---

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `MitmAddon` — `har_reproducer/reproduction/mitm_addon.py` (109 linhas, arquivo inteiro)

Único addon do `mitmdump` que este projeto usa (`reproduction/mitm_proxy_orchestrator.py`
sobe o processo com `-s mitm_addon.py`). `response(flow)` (`:24-29`) é o hook chamado pelo
mitmproxy a cada resposta interceptada; monta um envelope no formato de uma entry de `.har`
(`_build_entry` → `_build_request`/`_build_response`) e grava em
`Workspace.mitm_capture_file()`. `_build_response` (`:54-63`) monta `content` chamando
`_build_content` (`:90-101`, citado em 1.1) — é o único produtor do campo `content` que
`CurlHttpTransport` e, por extensão, `real_responses/res_*.json`, vão consumir.

Importa notar que **não existe teste de unidade para esta classe** (`grep -rn MitmAddon
tests/` não acha nada além de golden tests de rede, e os fixtures de rede
(`tests/support/canned_http_handler.py`) nunca servem resposta comprimida — `CannedResponse`
guarda o corpo como `str` puro). É por isso que este defeito nunca apareceu na suíte.

### `mitmproxy.http.Response` — biblioteca de terceiros (`mitmproxy==11.1.3`, já instalado)

Dois atributos relevantes, verificados no código-fonte instalado
(`.venv/.../mitmproxy/http.py:313-401`):

```python
@property
def raw_content(self) -> bytes | None:
    return self.data.content

def get_content(self, strict: bool = True) -> bytes | None:
    if self.raw_content is None:
        return None
    ce = self.headers.get("content-encoding")
    if ce:
        try:
            content = encoding.decode(self.raw_content, ce)
            if isinstance(content, str):
                raise ValueError(f"Invalid Content-Encoding: {ce}")
            return content
        except ValueError:
            if strict:
                raise
            return self.raw_content
    else:
        return self.raw_content
```

`content` (a property, sem argumento) chama `get_content()` com `strict=True` — lançaria
`ValueError` num `Content-Encoding` incoerente. `get_content(strict=False)` é a variante que
nunca lança: sem `Content-Encoding`, devolve o mesmo que `raw_content` (nenhuma mudança de
comportamento nesse caso); com `Content-Encoding` reconhecido, devolve descomprimido; com
`Content-Encoding` presente mas incoerente com o conteúdo, devolve o bruto — exatamente a
degradação segura que `raw_content` já oferecia.

Verificado com os quatro casos de borda relevantes, usando a biblioteca real do projeto:

```
gzip válido ............ descomprime e bate byte a byte com o original
brotli válido .......... descomprime e bate byte a byte com o original
identity ............... passa o corpo como está
Content-Encoding mentiroso (diz "gzip", bytes não são gzip) -> devolve os bytes crus, sem lançar
sem Content-Encoding ... devolve os bytes crus (idêntico ao raw_content de hoje)
```

### `HARParser.decode_body` — `har_reproducer/fs_io/har_parser.py:41-49`

```python
@staticmethod
def decode_body(body_content: str, encoding: Optional[str] = None) -> str:
    if not body_content:
        return ""
    if encoding == "base64":
        try:
            return base64.b64decode(body_content).decode("utf-8", errors="replace")
        except Exception as e:
            print(f"[AVISO] Falha ao decodificar body base64: {e}. Retornando conteúdo original.")
            return body_content
    return body_content
```

Não muda. Importa porque é o consumidor que materializa o mojibake — mas ele está fazendo
exatamente o que deveria com o que recebe: decodificar da melhor forma um corpo verdadeiramente
binário. O `errors="replace"` aqui é apropriado para esse caso (binário genuíno nunca vai
decodificar limpo como UTF-8; a alternativa seria lançar, e o projeto já prefere degradar).

### `ResponseCorpus._serialize` / `_decode_body` — `har_reproducer/tracking/response_corpus.py:57-72`

Consumidor final do corpo, junto com `TokenLocationDetector`. Nenhum dos dois olha o header
`content-encoding` para decidir nada — tratam o campo `body` como texto pronto. É por isso
que a correção cabe inteira em `MitmAddon`: uma vez que o corpo chega descomprimido até o
JSON de `real_responses/`, todo o resto do pipeline já trata esse corpo do mesmo jeito que
trata um corpo vindo de `original_responses/` (que sempre chegou descomprimido, por
especificação do HAR).

---

## 3. Decisões de arquitetura

### 3.1 — `MitmAddon._build_content`: descomprimir antes de decidir texto ou base64

**Estado atual** (`mitm_addon.py:90-101`, citado por completo em 1.1): usa
`response.raw_content` — os bytes como chegaram pela rede, comprimidos quando o servidor
declarou `Content-Encoding`.

**Estado esperado:**

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

A mudança é a fonte dos bytes: `response.raw_content` → `response.get_content(strict=False)`,
capturada uma única vez em `content` e usada nos dois pontos que hoje leem `raw_content`
(o teste de vazio e o `.decode`), para não descomprimir duas vezes.

Efeito, verificado com os codecs reais do projeto (2.2): corpo comprimido com
`Content-Encoding` válido passa a chegar descomprimido e decodifica limpo como UTF-8 (era o
caso que ia para base64 e virava mojibake); corpo sem `Content-Encoding` não muda em nada,
porque `get_content(strict=False)` devolve exatamente `raw_content` nesse caso; corpo binário
genuíno sem `Content-Encoding` continua indo para base64 exatamente como hoje; corpo com
`Content-Encoding` incoerente com o conteúdo (raro, mas possível com um servidor mal
comportado) degrada para o bruto em vez de lançar, preservando o comportamento defensivo que
`raw_content` já tinha.

⚠️ **Não usar `response.content`** (a property sem argumento): ela chama `get_content()` com
`strict=True` por padrão e lança `ValueError` no caso de `Content-Encoding` incoerente — isso
faria o hook `response(flow)` do mitmproxy propagar uma exceção a cada resposta desse tipo, em
vez de degradar. `get_content(strict=False)` é o que preserva a garantia que o código de hoje
já tinha ("nunca lança") com a descompressão a mais.

⚠️ **O header `content-encoding` continua sendo gravado como está** em `_build_response`
(`_headers_list`, sem mudança) — o corpo descomprimido ao lado de um header que ainda diz
`br`/`gzip` é exatamente o formato que todo HAR exportado de navegador já usa (verificado em
1.1/2.1: a entry real do HAR de referência tem `content-encoding: br` no header e o texto do
corpo já descomprimido). Nenhum consumidor do projeto lê esse header para decidir descompressão
(`grep -rin content-encoding har_reproducer/` não acha nenhum, fora do próprio `MitmAddon`), então
não há inconsistência a resolver.

### 3.2 — Cobertura de teste: unidade sobre `_build_content`, sem precisar do `mitmdump`

**Estado atual:** zero testes de `MitmAddon`. O único caminho que exercitaria isto hoje é a
suíte de rede (`@pytest.mark.slow`), e ela nunca serve resposta comprimida — `CannedResponse`
não tem noção de `Content-Encoding` (2, "MitmAddon").

**Estado esperado:** `tests/unit/test_mitm_addon.py`, testando `MitmAddon._build_content`
diretamente contra um `mitmproxy.http.Response` construído em memória — sem subir `mitmdump`,
sem servidor, sem rede. A construção do `Response` para teste:

```python
response: Response = Response.make(200, b"", {"content-type": "text/plain"})
response.headers["content-encoding"] = "gzip"
response.raw_content = gzip.compress(b"conteudo de teste")
```

⚠️ **Usar `Response.make(...)` seguido de atribuir `raw_content` diretamente** — não passar
o corpo comprimido como o argumento `content` de `Response.make`, porque o setter de
`.content`/`.make` **re-codifica** o valor recebido conforme o `content-encoding` já presente
nos headers (verificado: gera compressão dupla e o teste passaria por engano). Setar
`raw_content` depois de `make` simula fielmente o que o mitmproxy faz ao receber bytes da
rede — atribuição direta, sem reprocessar.

Isso cobre a etapa inteira sem depender de infraestrutura de rede, e é consistente com o
projeto não ter, até hoje, nenhum teste desse componente.

---

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `reproduction/mitm_addon.py` → `MitmAddon._build_content` | troca a fonte dos bytes de `response.raw_content` para `response.get_content(strict=False)` (3.1) |
| `tests/unit/test_mitm_addon.py` | **novo arquivo** — cobertura de unidade que hoje não existe (3.2) |

Nenhum outro arquivo muda. `HARParser`, `ResponseCorpus`, `CurlHttpTransport`,
`TokenLocationDetector` e os agentes de `tracking/` continuam exatamente como estão — o
defeito estava isolado num único método, e a correção não precisa deles saberem de nada
novo.

---

## 5. Casos de borda e comportamento de erro

**5.1 Resposta sem `Content-Encoding`.** `get_content(strict=False)` devolve exatamente
`raw_content` — comportamento idêntico ao de hoje, verificado em 2.2. É a maioria das
respostas dos dois HARs desta investigação: 309 de 324 entries na gravação atual, 228 de 238
na anterior.

**5.2 Corpo binário genuíno (imagem, fonte) sem compressão.** Sem `Content-Encoding`, cai no
mesmo caso de 5.1: `get_content(strict=False)` devolve o bruto, que continua indo para base64
exatamente como hoje. Nenhuma imagem passa a ser "descomprimida" por engano — só corpos que
de fato declaram `Content-Encoding` são afetados.

**5.3 `Content-Encoding` presente mas incoerente com o conteúdo** (servidor mal comportado, ou
proxy que já descomprimiu sem atualizar o header). `get_content(strict=False)` devolve o bruto
em vez de lançar — mesmo comportamento defensivo que o código de hoje já tinha com
`raw_content`. Não observado nos dois HARs desta investigação; comportamento verificado
sinteticamente em 2.2.

**5.4 `Content-Encoding: identity`.** Verificado: `get_content(strict=False)` devolve o corpo
como está, sem tentar descomprimir. Sem efeito sobre esta mudança.

**5.5 Corpo vazio.** `not content` continua cobrindo `None` e `b""`, como `not response.
raw_content` já cobria — nenhuma mudança de comportamento.

**5.6 O corpo de request permanece com o defeito irmão** (1.4) — decisão explícita de não
corrigir sem caso medido, não descuido.

**5.7 Workspaces já gerados.** Continuam com o corpo comprimido gravado. Não há migração;
`run` de novo resolve.

**5.8 Custo.** Descompressão de brotli/gzip é ordens de magnitude mais rápida que qualquer
chamada de rede do próprio `run`; nenhuma medição de tempo é necessária para esta etapa.

---

## 6. Suposições e pontos a confirmar

- **Cobertura adicional de ponta a ponta.** Esta spec propõe só o teste de unidade de 3.2, que
  já reproduz o defeito e a correção com fidelidade aos codecs reais. Uma alternativa seria
  estender `CannedHttpHandler`/`CannedResponse` para servir uma rota comprimida e cobrir o
  caminho completo (`mitmdump` real → captura → `real_responses/res_*.json`) num cenário
  golden novo. Não incluída no plano por padrão: exigiria ensinar o servidor de teste a
  negociar compressão HTTP de verdade (cabeçalhos, `Content-Length`), o que é uma alteração de
  infraestrutura de teste maior que o defeito que está sendo corrigido. Avisar se a preferência
  for incluir.
- **O defeito irmão do request** está documentado em `problemas-encontrados.md`, não no
  backlog global — decisão tomada: fica local a esta etapa, porque é achado da investigação
  desta spec e não item de produto pendente.

---

## 7. Referência

Toda alteração de código desta spec segue o padrão descrito em [[guia-de-estilo]]
(`.claude/skills/guia-de-estilo`). A decisão não introduz suposição nova sobre formato de
protocolo ou de site — usa exatamente o mecanismo de descompressão que a própria biblioteca
HTTP do projeto já expõe, e o header que determina qual mecanismo usar já é lido diretamente
da resposta real, nunca hardcoded ([[arquitetura-e-fundamentos]]).
