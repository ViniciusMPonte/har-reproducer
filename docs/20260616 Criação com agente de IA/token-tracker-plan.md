# Token Tracker — Plano de Implementação

**Módulo:** `har_reproducer/tracker.py`  
**Depende de:** saída do HAR Parser (`steps/req_NNNN.json`) + responses reais já coletadas (`real_responses/res_NNNN.json`)  
**Integrado com:** Request Engine (roda a cada step, durante a execução)

---

## 1. Objetivo do módulo

Para cada `req[N]` (N ≥ 1), **antes de executá-la**, analisar o que ela precisa, descobrir de onde cada valor dinâmico vem nas responses reais já recebidas, e entregar ao Request Engine um curl pronto com extratores verificados.

O Token Tracker não roda upfront sobre todo o HAR — ele roda a cada step, entrelaçado com a execução. Quando `req[N]` precisa ser executada, o Token Tracker recebe `req[N]` (do HAR) e as responses reais `real_res[0..N-1]` já coletadas, produz o curl e os extratores para esse step, e devolve o controle ao engine.

A vantagem desta abordagem: extratores são criados e testados contra valores **reais** do servidor, não os valores do HAR. Se o servidor retornar um formato diferente, a falha é detectada antes de tentar a requisição, com contexto preciso de onde está o problema.

Este é o módulo mais arriscado do projeto — é onde a heurística pode falhar silenciosamente (token não detectado = falha em runtime, sem aviso prévio). O plano abaixo prioriza tornar essas falhas **visíveis e debugáveis** em vez de tentar eliminá-las por completo.

---

## 2. Pré-condição de uso

**O HAR deve ser capturado em uma janela anônima, com `req[0]` sendo a primeira requisição da sessão**, sem cookies, sem tokens acumulados, sem estado anterior. Isso é fundamental porque `req[0]` é o baseline absoluto do sistema — o estado zero.

Esta não é uma limitação do código: é um requisito de captura que deve ser documentado claramente para o usuário. Um HAR capturado no meio de uma sessão já autenticada produzirá resultados incorretos, pois `req[0]` já carregará tokens que o sistema interpretará como estáticos.

---

## 3. Conceito central — `req[0]` como baseline

A classificação de um valor como **estático** ou **dinâmico** é feita sempre por comparação direta com `req[0]`:

- **Igual ao valor em `req[0]`** → estático. Vai direto para o curl como valor fixo.
- **Diferente do valor em `req[0]`** (ou ausente em `req[0]`) → candidato a dinâmico. Vai para o curl como `{{placeholder}}` e precisa de um extrator.

Esta abordagem funciona porque `req[0]` é uma requisição limpa: tudo que ela carrega é o que o browser leva "do nada" — headers padrão, parâmetros fixos de URL, nada de sessão. Qualquer coisa que mude a partir daí veio de alguma response intermediária.

**`req[0]` em si nunca passa pelo Token Tracker** — é executada exatamente como está no HAR, sem análise.

---

## 4. Estruturas de dados

### 4.1 Candidate

Valor de `req[N]` que diverge de `req[0]` e precisa de um extrator.

```python
@dataclass
class Candidate:
    step_index: int
    location: str       # "header" | "cookie" | "body_field" | "query_param"
    name: str           # nome do header/cookie/campo/param
    value: str          # valor observado no HAR (referência, não o valor real)
```

### 4.2 TokenOrigin

Onde o valor de um Candidate foi encontrado pela primeira vez nas responses reais.

```python
@dataclass
class TokenOrigin:
    step_index: int     # índice do real_res_NNNN.json onde foi encontrado
    location: str       # "set_cookie" | "header" | "body_json" | "body_html"
                        # | "body_regex" | "redirect_url"
    # campos específicos por destination_location:
    header_name: str | None = None
    cookie_name: str | None = None
    json_path: str | None = None
    selector: str | None = None
    attribute: str | None = None
    regex: str | None = None
    real_matched_value: str | None = None  # valor real encontrado (usado no teste TDD)
    grep_line: str | None = None           # linha retornada pelo grep (para debug)
```

### 4.3 Extractor

Código Python gerado por agente especializado para extrair um valor dinâmico em runtime.

```python
@dataclass
class Extractor:
    token_id: str
    origin: TokenOrigin
    extractor_type: str     # "set_cookie" | "header" | "jsonpath" | "css" | "regex"
    code: str               # código Python gerado pelo agente
    test_code: str          # teste pytest gerado antes do código (TDD)
    expected_value: str     # valor REAL encontrado pelo grep (não o do HAR)
    verified: bool          # True se o teste passou contra a response real
```

### 4.4 CurlTemplate

Representação de uma requisição como arquivo curl com placeholders.

```python
@dataclass
class CurlTemplate:
    step_index: int
    method: str
    url: str
    static_headers: dict[str, str]     # valores fixos já preenchidos
    dynamic_headers: dict[str, str]    # nome → "{{token_id}}"
    static_cookies: dict[str, str]
    dynamic_cookies: dict[str, str]
    static_body_fields: dict[str, str]
    dynamic_body_fields: dict[str, str]
    body_mime: str | None
```

### 4.5 StepAnalysis

Output do Token Tracker para um único step.

```python
@dataclass
class StepAnalysis:
    step_index: int
    curl_template: CurlTemplate
    extractors: list[Extractor]        # extratores prontos e verificados
    unresolved: list[Candidate]        # candidatos sem origem encontrada
    static_values: list[Candidate]     # descartados como estáticos (para auditoria)
```

---

## 5. Pipeline do módulo

O Token Tracker expõe uma função chamada a cada step pelo Request Engine:

```
analyze_step(step_index: int, steps_dir: str, real_responses_dir: str) -> StepAnalysis

ETAPA 1 — Carregar baseline e step atual
  ler req_0000.json → baseline (dict de todos os valores de req[0])
  ler req_{N:04d}.json → step atual

ETAPA 2 — SPLIT do step atual
  extrair todos os valores de req[N]:
    headers, cookies, body fields (JSON / form-urlencoded), query params

ETAPA 3 — COMPARAÇÃO COM BASELINE
  para cada valor extraído:
    se (name, value) existe identicamente em baseline → STATIC
    senão → CANDIDATE
  exceção: nomes conhecidos como dinâmicos (.*token.*, .*csrf.*, .*jwt.*, etc.)
           nunca são descartados como estáticos mesmo que coincidam com baseline

ETAPA 4 — GERAR CURL TEMPLATE (rascunho)
  criar rascunho do curl para req[N]:
    valores STATIC → preenchidos diretamente
    valores CANDIDATE → substituídos por {{token_id_provisório}}

ETAPA 5 — BUSCAR ORIGEM DE CADA CANDIDATE (via grep nas responses reais)
  para cada candidate:
    rodar grep nos arquivos real_responses/res_0000.json ... res_{N-1:04d}.json
    registrar o primeiro arquivo onde o valor é encontrado (menor índice primeiro —
    "mais próximo" significa mais próximo de req[0], não de req[N])
    identificar localização precisa (header, JSON path, CSS selector, regex)
    se encontrado → registrar TokenOrigin com real_matched_value
    se não encontrado → adicionar a unresolved

ETAPA 6 — CRIAR EXTRATORES (TDD + agentes)
  para cada candidate com origem identificada:
    verificar se já existe extrator com mesmo token_id no registry do engine
      (token_id é derivado do nome do campo — ex: "Authorization" → "jwt_main")
    se já existe e verified = True → reutilizar extrator existente, pular criação
    se não existe:
      gerar teste TDD (expected = real_matched_value da response real)
      ativar agente especializado
      loop até teste passar (máx. 5 tentativas)
      se verificado → registrar no registry do engine + adicionar à lista de extratores
      se não verificado → mover para unresolved

ETAPA 7 — FINALIZAR CURL TEMPLATE
  substituir placeholders provisórios pelos token_ids definitivos
  valores unresolved → reverter para valor estático do HAR + comentário de aviso

ETAPA 8 — Salvar curl em curls/req_{N:04d}.curl.sh
           Salvar extratores em extractors/extract_<token_id>.py

retornar StepAnalysis
```

### 5.1 Registry de extratores (deduplicação entre steps)

O `token_id` é derivado do nome do campo que carrega o valor dinâmico (ex.: o header `Authorization` origina `jwt_main`, o cookie `session` origina `cookie_session`). Como o mesmo token tende a ser exigido em múltiplos steps consecutivos, o Request Engine mantém um registry em memória:

```python
extractor_registry: dict[str, Extractor]  # token_id → Extractor verificado
```

Antes de acionar um agente para criar um novo extrator (Etapa 6), o Token Tracker consulta esse registry. Se já existe um `Extractor` com `verified = True` para aquele `token_id`, ele é reutilizado diretamente — sem nova chamada ao LLM. O registry é passado ao `analyze_step` como parâmetro e atualizado pelo engine após cada step.

---

## 6. Estratégia de busca com grep

A busca de origem usa o comando `grep` do sistema operacional diretamente via `subprocess`. Isso evita carregar todos os arquivos em memória e permite tratar os arquivos de response como streams de texto.

**A busca é feita nas responses reais** (`real_responses/`), não nas do HAR. Isso garante que os extratores sejam criados e verificados contra o que o servidor realmente retornou nesta execução.

### 6.1 Chamada base

```python
import subprocess

def grep_in_real_responses(
    value: str,
    real_responses_dir: str,
    max_step: int
) -> list[GrepMatch]:
    """
    Busca `value` nos arquivos res_0000.json até res_{max_step-1:04d}.json
    dentro de real_responses_dir.
    Retorna lista de matches com filename e linha encontrada.
    """
    result = subprocess.run(
        ["grep", "-Frn", "--include=res_*.json", "-m", "1", value, real_responses_dir],
        capture_output=True,
        text=True
    )
    return parse_grep_output(result.stdout, max_step)
```

O flag `-m 1` limita a um match por arquivo. O `-n` retorna o número da linha para identificar contexto.

### 6.2 Caso `Authorization: Bearer X`

Se o valor do candidato começa com `"Bearer "` ou `"Token "`, extrair o valor interno (`V_inner`) e fazer o grep com `V_inner`. O extrator gerado vai reconstruir o prefixo na injeção: `Authorization: Bearer {{token_id}}`.

### 6.3 Ordem de busca dentro do arquivo encontrado

Quando o grep confirma que `real_res_M.json` contém o valor, uma segunda etapa determina **onde exatamente**:

1. Verificar se está nos headers → `set_cookie` ou `header`.
2. Verificar se está no body, pelo `body_mime`:
   - `application/json` → tentar JSONPath.
   - `text/html` → tentar CSS selector (BeautifulSoup).
   - Qualquer outro → regex genérica com contexto.
3. Verificar se está na URL de redirect (`redirect_url`).

---

## 7. Criação dos extratores (TDD + agentes)

Para cada Candidate com origem identificada, o processo segue TDD estrito:

### 7.1 Passo 1 — Gerar o teste

O teste usa o **valor real** encontrado pelo grep como `expected_value` — não o valor do HAR. Isso garante que o extrator funciona para o que o servidor realmente retornou nesta execução.

```python
# Exemplo de teste gerado para um JWT em JSON body
def test_extract_jwt_main():
    with open("real_responses/res_0000.json") as f:
        response = json.load(f)
    result = extract_jwt_main(response)
    assert result == "<valor_real_encontrado_pelo_grep>"
```

### 7.2 Passo 2 — Ativar agente especializado

Com o teste em mãos, um agente LLM especializado recebe:
- O arquivo `real_responses/res_M.json` (ou trecho relevante via grep).
- O `real_matched_value` (valor real a extrair).
- O teste gerado.
- Instruções restritas ao seu domínio.

Os agentes especializados disponíveis:

| Agente | Domínio | Quando ativado |
|---|---|---|
| `RegexAgent` | Escreve extratores com `re.search()` | Caso geral, body de texto, `<script>` |
| `CSSAgent` | Escreve extratores com BeautifulSoup | Body HTML (`body_mime == text/html`) |
| `JSONPathAgent` | Escreve extratores com `jsonpath-ng` | Body JSON (`body_mime == application/json`) |
| `CookieAgent` | Escreve extratores de `Set-Cookie` | Valor encontrado em headers de response |
| `HeaderAgent` | Escreve extratores de headers simples | Valor encontrado em outros response headers |

Cada agente recebe apenas o contexto relevante para seu domínio.

### 7.3 Passo 3 — Loop até o teste passar

O agente gera o código. O sistema roda o teste. Se falhar, o erro é devolvido ao agente com o output do pytest. Repete até:
- O teste passar → `Extractor.verified = True`.
- Atingir o limite de tentativas (padrão: 5) → `verified = False`, candidato vai para `unresolved`, código da última tentativa salvo para inspeção.

### 7.4 Output do extrator

Salvo em `extractors/extract_<token_id>.py`. Assinatura fixa:

```python
def extract_<token_id>(response: dict) -> str:
    """
    response: dict com campos 'headers', 'cookies', 'body', 'body_mime', 'redirect_url'
    Retorna o valor extraído como string.
    Lança ExtractorError se não encontrar.
    """
    ...
```

Essa assinatura fixa é o contrato entre o extrator gerado e o Request Engine.

---

## 8. Formato do arquivo curl

Cada step (exceto req[0]) produz `curls/req_NNNN.curl.sh`:

```bash
# step 3 — POST /api/submit
# tokens dinâmicos: jwt_main (extraído de real_res_0000), csrf_token (extraído de real_res_0001)
# ⚠ unresolved: X-Request-Signature (tratado como estático — valor do HAR)

curl -X POST "https://example.com/api/submit" \
  -H "Authorization: Bearer {{jwt_main}}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "User-Agent: Mozilla/5.0 ..." \
  -H "X-Request-Signature: a1b2c3..." \
  -b "session={{cookie_session}}; theme=dark" \
  -d '{"_csrf":"{{csrf_token}}","action":"submit"}'
```

O arquivo serve dois propósitos: artefato de debug humanamente legível, e template usado pelo Request Engine para construir a requisição real em runtime.

---

## 9. Modo `--dry-run`

No modo dry-run, o Token Tracker roda contra os arquivos do HAR (`steps/res_NNNN.json`) em vez das responses reais, sem executar nenhuma requisição. Útil para auditar o plano completo antes de rodar de verdade.

Neste modo:
- O `expected_value` dos testes vem do HAR (não de responses reais).
- Os extratores são gerados e testados normalmente, mas contra os dados do HAR.
- O resultado é um relatório do que o sistema fará, não do que ele fez.

---

## 10. Casos de teste (fixtures dedicadas)

Cada fixture tem um teste unitário verificando o `StepAnalysis` exatamente e confirmando que todos os extratores gerados passam em seus testes.

Os testes do Token Tracker isolado usam responses pré-gravadas como "respostas reais" (simulando o que o servidor teria retornado). Isso mantém o módulo testável sem rede.

| Fixture | O que valida |
|---|---|
| `tracker_jwt_body.har` | JWT em `body.token` (JSON), usado como `Authorization: Bearer ...`. Valida JSONPathAgent + caso Bearer (6.2). |
| `tracker_set_cookie.har` | `Set-Cookie: session=...` usado como cookie. Valida CookieAgent. |
| `tracker_csrf_html.har` | CSRF token em `<input name="_csrf" value="...">`, consumido em body de POST. Valida CSSAgent. |
| `tracker_redirect_param.har` | Token na URL de redirect (`Location: /next?session=...`). Valida busca em redirect_url. |
| `tracker_script_token.har` | Token dentro de `<script>var token = "..."</script>`. Valida RegexAgent + nota de aviso gerada. |
| `tracker_static_headers.har` | `User-Agent`, `Accept-Language` idênticos ao baseline — devem ir para `static_values`, não para candidatos. |
| `tracker_unknown_origin.har` | Header dinâmico que não aparece em nenhuma response real — deve ir para `unresolved`, tratado como estático no curl com aviso. |
| `tracker_ambiguous.har` | Valor aparece em duas responses anteriores — valida que a mais próxima (menor índice) é escolhida. |
| `tracker_complex_flow.har` | Combinação de todos os casos em um fluxo de 8+ steps. Teste de integração completo do módulo. |

---

## 11. Saída de diagnóstico por step

Durante a execução, o Token Tracker imprime para cada step analisado:

```
[Token Tracker] req_0001 — analisando (baseline: req_0000)
  2 candidatos dinâmicos, 14 estáticos

  ✓ jwt_main         origem: real_res_0000, body JSON ($.token)       JSONPathAgent  ✓ teste ok
  ✓ cookie_session   origem: real_res_0000, Set-Cookie                CookieAgent    ✓ teste ok

  curl salvo em: curls/req_0001.curl.sh

[Token Tracker] req_0003 — analisando
  ⚠ token_script_1   origem: real_res_0002, <script> (regex)          RegexAgent     ✓ teste ok
                      nota: valor em <script> — verificar se é client-side se falhar

  ⚠ UNRESOLVED: header "X-Request-Signature" — tratado como estático (valor do HAR)
```

---

## 12. Critério de conclusão desta fase

- [ ] Todas as 9 fixtures da seção 10 passam com asserções exatas (ver estrutura em seção 13).
- [ ] Todos os extratores gerados para `tracker_complex_flow.har` têm `verified = True`.
- [ ] Os arquivos curl gerados são sintaticamente válidos (`bash -n curls/req_NNNN.curl.sh`).
- [ ] O `StepAnalysis` é consumível pelo Request Engine sem transformação adicional (schema validado via Pydantic).
- [ ] Em modo `--dry-run`, o Token Tracker roda sobre todo o `complex_flow.har` sem execução de rede e produz relatório legível.

---

## 13. Estrutura de arquivos do módulo

A árvore abaixo mostra todos os arquivos relevantes ao Token Tracker — código-fonte, testes, fixtures e artefatos gerados em runtime.

```
har_reproducer/
├── __init__.py
├── tracker.py                        # core — analyze_step() e pipeline completo
│   # Candidate · TokenOrigin · Extractor · CurlTemplate · StepAnalysis
├── models.py                         # modelos Pydantic compartilhados
│   # Candidate · TokenOrigin · Extractor · CurlTemplate · StepAnalysis
└── agents/
    ├── base.py                       # classe base dos agentes (loop TDD, contrato)
    ├── cookie_agent.py               # extrai de Set-Cookie headers
    ├── header_agent.py               # extrai de outros response headers
    ├── jsonpath_agent.py             # extrai de body JSON via jsonpath-ng
    ├── css_agent.py                  # extrai de body HTML via BeautifulSoup
    └── regex_agent.py                # caso geral, <script>, texto puro

tests/
└── tracker/
    ├── test_jwt_body.py              # JWT em body JSON → Authorization: Bearer | JSONPathAgent
    ├── test_set_cookie.py            # Set-Cookie: session=... → cookie | CookieAgent
    ├── test_csrf_html.py             # <input name="_csrf"> em HTML → body POST | CSSAgent
    ├── test_redirect_param.py        # token em Location: /next?session=... | redirect_url
    ├── test_script_token.py          # var token="..." em <script> | RegexAgent + aviso
    ├── test_static_headers.py        # User-Agent, Accept-Language → static_values
    ├── test_unknown_origin.py        # header dinâmico sem origem → unresolved + aviso
    ├── test_ambiguous.py             # valor em 2 responses → escolhe menor índice
    └── test_complex_flow.py          # integração: todos os casos em fluxo de 8+ steps

tests/fixtures/tracker/
├── tracker_jwt_body/
│   ├── steps/                        # req_0000.json, req_0001.json, ...
│   └── real_responses/               # res_0000.json (body JSON com {token: ...})
├── tracker_set_cookie/
│   ├── steps/
│   └── real_responses/               # res com Set-Cookie: session=...
├── tracker_csrf_html/
│   ├── steps/
│   └── real_responses/               # res com <input name="_csrf" value="...">
├── tracker_redirect_param/
│   ├── steps/
│   └── real_responses/               # res com Location: /next?session=...
├── tracker_script_token/
│   ├── steps/
│   └── real_responses/               # res com <script>var token="..."</script>
├── tracker_static_headers/
│   ├── steps/
│   └── real_responses/
├── tracker_unknown_origin/
│   ├── steps/
│   └── real_responses/
├── tracker_ambiguous/
│   ├── steps/
│   └── real_responses/               # res_0000.json + res_0001.json com mesmo valor
└── tracker_complex_flow/
    ├── steps/                        # req_0000.json … req_0008.json
    └── real_responses/               # res_0000.json … res_0007.json

# — artefatos gerados em runtime (exemplo após uma execução completa) —

curls/
├── req_0001.curl.sh                  # template curl com {{placeholders}}
├── req_0002.curl.sh
└── ...

extractors/
├── extract_jwt_main.py               # def extract_jwt_main(response: dict) -> str
├── extract_csrf_token.py
├── extract_cookie_session.py
└── ...

extractor_tests/                      # testes TDD gerados antes do código do extrator
├── test_extract_jwt_main.py
├── test_extract_csrf_token.py
└── ...

# — configuração e infra —

pyproject.toml                        # deps: httpx · pydantic · beautifulsoup4 · jsonpath-ng · pytest · pytest-httpx
pytest.ini
conftest.py                           # fixtures compartilhadas: tmp_steps_dir · tmp_real_responses_dir · load_fixture
```

**Notas sobre a estrutura:**

- `agents/` é um subpacote separado. Cada agente tem seu próprio arquivo e herda de `base.py`. A lógica de seleção de agente e o loop TDD ficam em `tracker.py`, não espalhados pelos agentes.
- `models.py` é isolado dos módulos com lógica. Pode ser importado pelo engine sem criar dependência circular com `tracker.py`.
- `extractor_tests/` é um diretório próprio para os testes TDD gerados em runtime — separado de `extractors/` e dos testes unitários do módulo. Permite rodar `pytest extractor_tests/` isoladamente para verificar que os extratores continuam passando após um re-run.
- Cada fixture em `tests/fixtures/tracker/` replica a estrutura de runtime (`steps/` + `real_responses/`) dentro de sua própria pasta. O código de teste chama `analyze_step()` com os mesmos paths que usaria em produção, sem adaptação especial.

---

## 14. Riscos conhecidos e mitigação

| Risco | Mitigação |
|---|---|
| `req[0]` capturado no meio de uma sessão (janela não-anônima) | Pré-condição documentada. O sistema não tem como detectar isso automaticamente — o usuário é responsável pela captura. |
| Falso estático: valor que coincide com `req[0]` por acaso mas é dinâmico | Nomes conhecidos como dinâmicos (`.*token.*`, `.*csrf.*`, etc.) nunca são descartados como estáticos mesmo que coincidam com baseline. |
| Server retorna formato diferente do HAR (estrutura JSON mudou, HTML reorganizado) | O extrator é testado contra a response real — a falha é detectada antes de tentar `req[N]`, com contexto preciso. O agente recebe o erro e tenta corrigir. |
| grep não encontra o valor porque está encodado (base64, URL-encoding) | Segunda passagem de busca com o valor decodificado/re-encodado nas variantes comuns. Se ainda não encontrar, vai para `unresolved`. |
| Agente entra em loop gerando código que nunca passa no teste | Limite de 5 tentativas. Após o limite, `verified = False`, código da última tentativa salvo. Valor vai para `unresolved`. |
| Token realmente gerado 100% client-side (não está em nenhuma response real) | Vai para `unresolved`, tratado como estático no curl com aviso. LLM Agent (Fase 3) recebe esses casos com prioridade quando `req[N]` falha. |
| Body binário sendo varrido por grep | HAR Parser marca bodies não-textuais com `body_mime` binário. Token Tracker pula esses arquivos na busca. |