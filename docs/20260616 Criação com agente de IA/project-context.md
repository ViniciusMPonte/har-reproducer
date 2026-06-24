# HAR Flow Reproducer — Contexto do Projeto

Este documento resume o projeto para ser usado como contexto inicial em novas conversas.
Documentos completos: `har-flow-reproducer-sdd.md` (SDD completo) e `token-tracker-plan.md` (plano detalhado do Token Tracker).

---

## O que é

Ferramenta Python que lê um arquivo `.har` capturado pelo browser e **reproduz o fluxo HTTP completo contra o servidor real na internet**, chegando ao mesmo estado final. O desafio central é que valores dinâmicos (JWT, cookies de sessão, CSRF tokens) mudam a cada execução — a ferramenta precisa rastrear de onde cada valor vem e propagá-lo corretamente entre as requisições.

**Não é** um proxy, load tester ou ferramenta de captura. Trabalha a partir de um HAR já gravado.

---

## Stack

- **Python** — linguagem principal
- **httpx** — cliente HTTP (HTTP/1.1 + HTTP/2)
- **Pydantic** — modelos de dados e validação
- **BeautifulSoup4** — parsing de HTML
- **jsonpath-ng** — extração de valores em JSON
- **pytest + pytest-httpx** — testes com servidor mock
- **OpenCode** — agentes LLM
- **grep (subprocess)** — busca de tokens nas responses (eficiência de memória)

---

## Fluxo de execução

O processo é **entrelaçado**: o Token Tracker não roda todo upfront — ele analisa `req[N+1]` usando a response real que acabou de chegar de `req[N]`, e só então executa `req[N+1]`. Análise e execução andam juntas, step a step.

```
HAR Parser (uma vez, sem rede):
  arquivo.har → steps/req_NNNN.json + steps/res_NNNN.json

Loop de execução:

  req[0] → servidor real → real_res[0]
  (executada como-está, sem análise — é o baseline)

  Para N = 1, 2, ..., último:
    ┌─ Token Tracker ──────────────────────────────────────┐
    │  compara req[N] vs req[0] → candidatos dinâmicos     │
    │  grep em real_res[0..N-1] → encontra origens         │
    │  TDD + agente especializado → gera extrator          │
    │  testa extrator contra real_res[M] → verifica        │
    │  monta curl de req[N] com {{placeholders}}           │
    └──────────────────────────────────────────────────────┘
         ↓
    req[N] → servidor real → real_res[N]
    aplica extratores em real_res[N] → Session Store
         ↓ (se falhar)
    regras determinísticas de recovery
         ↓ (se ainda falhar)
    LLM Agent → diagnóstico + patch → retry
         ↓
    próximo step

  Success Validator → critério atingido?
```

**Modo `--dry-run`:** roda o Token Tracker contra os arquivos do HAR (sem rede) para inspecionar o plano antes de executar. Útil para debug e auditoria do dependency graph.

---

## Módulos

### HAR Parser (`parser.py`)
Roda uma vez, sem rede. Lê `arquivo.har` e gera `steps/req_NNNN.json` + `steps/res_NNNN.json` para cada entry, em ordem. Índice com padding de 4 dígitos (garante sort lexicográfico correto). Bodies em base64 são decodificados. Entries com `OPTIONS` são marcadas com `skip: true`.

### Token Tracker (`tracker.py`)
**Módulo mais crítico.** Roda a cada step, durante a execução, usando a response real recebida. Para `req[N]` (N ≥ 1):
1. Compara todos os valores de `req[N]` com `req[0]` (o baseline).
2. Valores iguais ao baseline → **estáticos** (preenchidos diretamente no curl).
3. Valores diferentes → **candidatos dinâmicos** (viram `{{placeholder}}` no curl).
4. Para cada candidato, usa `grep` nas responses reais já coletadas (`real_res[0..N-1]`) para encontrar a origem.
5. Quando encontra, cria um **extrator testado** via TDD + agente especializado, testado contra a response real.
6. Se não encontra, trata como estático com aviso de `unresolved`.

**Pré-condição de uso:** o HAR deve ser gravado em janela anônima, com `req[0]` sendo a primeira requisição da sessão (estado zero, sem cookies ou tokens acumulados).

**`req[0]` nunca é analisado** — é executado exatamente como está no HAR.

**Busca com grep:** `subprocess` chamando `grep -rn` nas responses reais já salvas em disco. Eficiente em memória para bodies grandes. Retorna linha e contexto para gerar a regex de captura.

**Agentes especializados por tipo de extração:**
- `CookieAgent` → `Set-Cookie` headers
- `HeaderAgent` → outros response headers
- `JSONPathAgent` → body JSON (`jsonpath-ng`)
- `CSSAgent` → body HTML (BeautifulSoup, CSS selector)
- `RegexAgent` → caso geral / `<script>` / texto puro

Cada agente segue TDD: o teste é gerado primeiro (usando o valor real encontrado pelo grep como `expected`), depois o agente escreve o extrator e fica em loop até o teste passar (máximo 5 tentativas).

**Output por step:**
- `curls/req_NNNN.curl.sh` — arquivo curl com estáticos preenchidos e `{{token_id}}` para dinâmicos
- `extractors/extract_<token_id>.py` — função Python standalone com assinatura fixa: `extract_<token_id>(response: dict) -> str`

### Session Store (`session.py`)
Estado em memória durante a execução: guarda os valores **reais** de todos os tokens extraídos até o momento. Renderiza templates `{{token_id}}` → valor real. Integrado com o cookie jar do httpx.

### Request Engine (`engine.py`)
Orquestra o loop de execução. Para cada step N ≥ 1:
1. Chama o Token Tracker para analisar `req[N]` e gerar o curl.
2. Renderiza o curl com os valores reais do Session Store.
3. Executa a requisição HTTP via httpx → salva `real_res[N]` em disco.
4. Aplica os extratores na response real → alimenta o Session Store.
5. Valida o resultado.

**Regras de recovery determinísticas** (antes do LLM): 401/403 → injetar JWT disponível; redirect inesperado → seguir; 400 com "csrf" no body → injetar csrf token disponível.

### LLM Agent (`agent.py`)
Ativado apenas quando o engine esgota as regras determinísticas. Recebe o contexto da falha e usa tools para diagnosticar e propor um patch. **Não executa requisições** — só analisa e propõe.

**Tools do agente:** `read_step_file`, `search_in_steps` (grep), `get_session_state`, `propose_extraction_rule`, `propose_injection`, `propose_token_override`.

### Success Validator (`validator.py`)
Verifica se o critério de sucesso foi atingido ao final. Tipos: `url_match`, `status_code`, `body_contains`, `html_element_present`, `composite`.

---

## Arquivos gerados durante o processo

```
steps/
  req_0000.json, res_0000.json   ← HAR splittado (referência, gerado upfront)
  req_0001.json, res_0001.json
  ...

real_responses/
  res_0000.json                  ← responses reais recebidas durante execução
  res_0001.json
  ...

curls/
  req_0001.curl.sh               ← template curl com {{placeholders}}, gerado por step
  req_0002.curl.sh
  ...

extractors/
  extract_jwt_main.py            ← função Python gerada por agente (TDD)
  extract_csrf_token.py
  ...
```

---

## Fases de implementação

| Fase | Escopo | Critério de conclusão |
|---|---|---|
| 1 | HAR Parser | Steps gerados corretamente para `complex_flow.har`, todos os testes passam |
| 2 | Token Tracker + Request Engine entrelaçados + Session Store + Success Validator | Engine executa fixtures contra servidor mock e atinge critério de sucesso |
| 3 | LLM Agent integrado ao engine | Engine com LLM resolve `jwt_in_html.har` (token em `<script>`) contra mock |
| 4 | Teste ponta a ponta com HAR real | `har-reproducer run --har real.har` chega na última página |

---

## Decisões de design relevantes

- **Processo entrelaçado** (Token Tracker + execução juntos, step a step): feedback imediato por step; extratores são testados contra valores reais, não os do HAR; falhas têm contexto preciso de onde ocorreram.
- **`req[0]` como baseline absoluto** (não `req[N-1]`): evita falsos positivos em tokens que coincidem por acaso entre requests consecutivas.
- **grep em responses reais** (não nas do HAR): o extrator é criado e verificado contra o valor que o servidor realmente retornou naquela execução.
- **grep via subprocess** (não leitura em memória): suporta bodies grandes sem degradação.
- **TDD para extratores**: o valor real encontrado pelo grep é o `expected` do teste — o agente não pode gerar código que não extrai o valor correto.
- **Extratores como funções standalone**: contrato fixo `(response: dict) -> str` desacopla o agente gerador do Request Engine.
- **LLM como diagnóstico, não execução**: o engine permanece determinístico e testável; o LLM só propõe patches.
- **`--dry-run`**: roda Token Tracker contra os arquivos do HAR (sem rede) para auditar o plano antes de executar.

---

## CLIs disponíveis (ao final do projeto)

```bash
har-reproducer parse     --har arquivo.har --output ./steps
har-reproducer run       --har arquivo.har
har-reproducer run       --har arquivo.har --dry-run
har-reproducer diagnose  --steps ./steps --real-responses ./real_responses
```
