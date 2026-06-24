# HAR Flow Reproducer — Prompts do Spec Kit

Copie cada bloco no comando indicado, na ordem apresentada.

---

## FASE 0 — Constitution

**Comando:** `/speckit.constitution`

```
Criar a constituição do projeto HAR Flow Reproducer com os seguintes princípios:

QUALIDADE DE CÓDIGO
- Todo código novo deve ter testes unitários cobrindo os caminhos feliz e os casos de erro explícitos no plano.
- Funções com mais de 30 linhas devem ser decompostas, exceto quando a complexidade for de lógica de domínio inquebrável (ex.: o pipeline de 8 etapas do Token Tracker).
- Nenhum módulo importa de outro que dependa dele (sem dependências circulares). A hierarquia de dependências é: models.py ← session.py, grep_utils.py ← tracker.py, agents/ ← engine.py ← cli.py.
- Toda função pública deve ter docstring com: o que recebe, o que retorna, e a pré-condição não óbvia (se houver).

PADRÕES DE TESTE
- Fixtures de teste replicam a estrutura de runtime exata (steps/ + real_responses/ dentro de cada pasta de fixture). O código de teste chama as funções com os mesmos paths que usaria em produção.
- Testes que dependem de disco usam diretórios temporários (tmp_path do pytest). Nenhum teste escreve em paths fixos fora de tmp_path.
- Testes do Token Tracker não fazem chamadas de rede. As responses "reais" são arquivos pré-gravados nas fixtures.
- O loop TDD dos agentes (run_tdd_loop) é testado com mocks da API Anthropic — nunca chamando a API real nos testes.
- pytest-httpx é a única forma de mockar o servidor HTTP nos testes do engine.

GESTÃO DE DEPENDÊNCIAS
- Gerenciador de pacotes: uv exclusivamente. Nenhum pip install direto.
- Dependências de produção: httpx, pydantic, beautifulsoup4, jsonpath-ng.
- Dependências de desenvolvimento: pytest, pytest-httpx.
- Adicionar dependências com uv add <dep> ou uv add --dev <dep>.

MODELOS DE DADOS
- Todos os modelos de dados públicos são Pydantic BaseModel (não dataclass), exceto onde explicitamente justificado. Isso garante validação automática e serialização JSON consistente.
- Nenhum dict genérico atravessa a fronteira entre módulos. Módulos trocam Pydantic models.

TRATAMENTO DE ERROS
- Erros esperados (token não encontrado, extrator que não passa no teste) são parte do fluxo normal e nunca levantam exceções não tratadas. São representados em campos dos modelos (ex.: verified = False, unresolved: list[Candidate]).
- Erros inesperados (arquivo não encontrado, JSON inválido) levantam exceções específicas com mensagem descritiva indicando o path do arquivo e o step atual.
- O LLM Agent é o último recurso — só é ativado após as regras determinísticas de recovery falharem.

CLI
- Subcomandos: parse, run, diagnose. Nenhum comportamento padrão sem subcomando.
- Flags com -- prefix. Nenhuma flag posicional ambígua.
- Saída de progresso vai para stdout. Erros vão para stderr.
- O modo --dry-run nunca faz chamadas de rede nem modifica arquivos fora do diretório de saída especificado.

ARTEFATOS GERADOS EM RUNTIME
- curls/req_NNNN.curl.sh: um arquivo por step, índice com padding de 4 dígitos.
- extractors/extract_<token_id>.py: assinatura fixa extract_<token_id>(response: dict) -> str, nunca alterada pelo agente.
- extractor_tests/: testes TDD gerados antes do código, rodam isoladamente com pytest extractor_tests/.
- real_responses/res_NNNN.json: nunca sobrescreve um arquivo já salvo na mesma execução.
```

---

## FASE 1 — Specify

**Comando:** `/speckit.specify`

```
Desenvolver o HAR Flow Reproducer, uma ferramenta de linha de comando em Python que lê um arquivo .har capturado pelo browser e reproduz o fluxo HTTP completo contra o servidor real na internet, chegando ao mesmo estado final da sessão original.

O PROBLEMA QUE ELA RESOLVE
Quando um desenvolvedor ou engenheiro de QA precisa reproduzir um fluxo autenticado — login seguido de uma sequência de requisições que chegam a uma página específica — ele enfrenta um obstáculo: valores como JWTs, cookies de sessão e CSRF tokens mudam a cada execução. O HAR gravado contém os valores que o servidor retornou naquela sessão, mas numa nova execução o servidor vai retornar valores diferentes. A ferramenta precisa detectar automaticamente quais valores são dinâmicos, descobrir de onde cada um veio (em qual response anterior o servidor o enviou) e propagá-los corretamente entre as requisições.

O QUE A FERRAMENTA FAZ

Parsing do HAR
O usuário fornece um arquivo .har capturado em janela anônima — condição obrigatória documentada claramente. A ferramenta lê o arquivo e divide cada entry em dois arquivos JSON separados: um para o request e um para a response, com índice de 4 dígitos (req_0000.json, res_0000.json, ...). Bodies em base64 são decodificados. Requisições OPTIONS são marcadas para serem puladas.

Reprodução entrelaçada
A primeira requisição (req[0]) é executada exatamente como está no HAR — ela é o baseline absoluto, o estado zero da sessão. A partir da segunda requisição, antes de cada execução o sistema analisa o que aquela requisição precisa: compara seus valores com os valores de req[0] e classifica cada valor como estático (igual ao baseline, vai direto) ou dinâmico (diferente do baseline, precisa vir de alguma response anterior).

Rastreamento de tokens dinâmicos
Para cada valor classificado como dinâmico, o sistema busca esse valor nas responses reais já coletadas até aquele momento — não nas responses do HAR, mas nas que o servidor realmente retornou nesta execução. A busca usa grep nos arquivos em disco para suportar bodies grandes sem degradação de memória. Quando encontra a origem, identifica onde exatamente o valor está: em um Set-Cookie header, em outro header de response, em um campo de um body JSON, em um atributo de um elemento HTML, ou dentro de uma tag script.

Geração de extratores verificados
Para cada token dinâmico com origem identificada, a ferramenta gera um extrator: uma função Python standalone que sabe buscar aquele valor específico na response onde ele aparece. A geração segue TDD estrito — o teste é escrito primeiro usando o valor real encontrado pelo grep como expected, depois um agente LLM especializado escreve o código do extrator e fica em loop até o teste passar, com no máximo 5 tentativas. Cada tipo de extração tem um agente dedicado: Set-Cookie headers, outros headers de response, body JSON com JSONPath, body HTML com CSS selectors, e caso geral com regex.

Execução e propagação
Após a análise, a requisição é executada com os valores estáticos preenchidos e os dinâmicos substituídos pelos valores reais extraídos das responses anteriores. O resultado real é salvo em disco e os extratores são aplicados sobre ele para alimentar o estado da sessão com os novos tokens que ele retornou.

Recovery de falhas
Quando uma requisição falha, o sistema tenta primeiro regras determinísticas: 401/403 injeta um JWT disponível na sessão; redirect inesperado segue o redirect; 400 com "csrf" no body injeta o csrf token disponível. Se as regras determinísticas não resolverem, um agente LLM de diagnóstico recebe o contexto completo da falha (request tentado, response recebida, estado da sessão, extratores usados) e usa ferramentas para ler os arquivos de step, buscar valores, e propor um patch — uma correção de extrator ou injeção manual de valor. O agente não executa requisições, apenas propõe correções.

Critério de sucesso
O usuário define antecipadamente o critério que indica que o fluxo chegou ao destino: URL que deve bater, status code esperado, texto que deve estar no body, elemento HTML que deve estar presente, ou combinação de critérios. O sistema confirma ao final se o critério foi atingido.

Modo dry-run
Antes de executar de verdade, o usuário pode rodar a análise completa do HAR sem fazer nenhuma requisição de rede. O sistema usa as responses do próprio HAR para simular o que faria, e produz um relatório legível mostrando: quantos candidatos dinâmicos foram detectados por step, quais origens foram encontradas, quais não foram encontradas (unresolveds), e qual agente seria ativado para cada um.

INTERFACE DE LINHA DE COMANDO
- har-reproducer parse --har arquivo.har --output ./steps — divide o HAR em arquivos de step
- har-reproducer run --har arquivo.har — executa o fluxo completo
- har-reproducer run --har arquivo.har --dry-run — analisa sem executar
- har-reproducer diagnose --steps ./steps --real-responses ./real_responses — diagnóstico do último step que falhou

USUÁRIOS
Desenvolvedores e engenheiros de QA que precisam reproduzir fluxos autenticados a partir de arquivos HAR gravados. O usuário sabe capturar um HAR no browser e entende o básico de HTTP. Não precisa saber como JWTs ou CSRF tokens funcionam internamente — a ferramenta cuida disso.

FORA DO ESCOPO
A ferramenta não captura tráfego (não é um proxy). Não é um load tester (reproduz uma execução por vez). Não modifica o servidor. Não lida com autenticação OAuth com fluxo de browser (popup, redirect externo). Não suporta WebSockets.
```

---

## FASE 2 — Clarify

**Comando:** `/speckit.clarify`

> Execute este comando e responda as perguntas geradas pelo agente. Depois use os refinamentos abaixo para completar pontos que provavelmente não serão cobertos automaticamente.

**Refinamentos a adicionar após o /clarify:**

```
Complementando a especificação com decisões de design já tomadas:

SOBRE O BASELINE (req[0])
req[0] é sempre executada exatamente como está no HAR, sem nenhuma análise. Ela nunca passa pelo Token Tracker. Isso é intencional: ela representa o estado zero da sessão, e qualquer coisa que ela carrega (headers padrão do browser, parâmetros fixos de URL) é tratada como estática para todo o resto do fluxo.

A comparação de cada req[N] é sempre feita contra req[0], não contra req[N-1]. Isso evita falsos positivos onde dois valores consecutivos coincidem por acaso mas são de fato dinâmicos.

SOBRE NOMES CONHECIDOS COMO DINÂMICOS
Certos nomes de campos nunca são classificados como estáticos, mesmo que o valor coincida com req[0]. Os padrões são: .*token.*, .*csrf.*, .*jwt.*, .*auth.*, .*session.*, .*nonce.*, .*secret.*, .*key.*. Se o nome do campo bater com qualquer um desses padrões (case-insensitive), ele vai para candidatos independentemente do valor.

SOBRE A BUSCA COM GREP
A busca usa grep -Frn --include=res_*.json -m 1 via subprocess. O -m 1 limita a um match por arquivo. Os arquivos buscados são sempre os de real_responses/, nunca os do HAR. A ordem de preferência quando o valor aparece em múltiplos arquivos é sempre o de menor índice (mais próximo de req[0]).

Se o valor começa com "Bearer " ou "Token ", o grep é feito com o valor interno (sem o prefixo). O extrator gerado reconstrói o prefixo na injeção: o campo no curl fica Authorization: Bearer {{jwt_main}}.

Se o grep não encontra o valor literal, tenta novamente com o valor URL-decoded e depois com o valor base64-decoded. Se nenhuma variante encontrar, o candidato vai para unresolved.

SOBRE TOKENS UNRESOLVED
Candidatos sem origem encontrada são tratados como estáticos no arquivo curl — o valor do HAR é usado diretamente — e um comentário de aviso é adicionado no arquivo. Eles aparecem no log de diagnóstico com símbolo de aviso. O LLM Agent (Fase 3) recebe esses casos com prioridade quando a requisição falha.

SOBRE REUTILIZAÇÃO DE EXTRATORES
O token_id é derivado do nome do campo que carrega o valor dinâmico. O engine mantém um registry de extratores em memória durante toda a execução. Se um extrator com verified = True já existe para um token_id, ele é reutilizado sem nova chamada ao LLM. Isso é crítico para performance: o JWT de autenticação, por exemplo, costuma aparecer em dezenas de steps consecutivos.

SOBRE O FORMATO DOS EXTRATORES
Cada extrator é uma função Python standalone salva em extractors/extract_<token_id>.py com assinatura fixa:

def extract_<token_id>(response: dict) -> str

O response dict tem os campos: headers (dict), cookies (dict), body (str), body_mime (str), redirect_url (str | None). A função lança ExtractorError se não encontrar o valor. Nenhuma outra interface é aceita — o agente que gerar código com assinatura diferente terá o teste rejeitado automaticamente.

SOBRE O LLM AGENT DE DIAGNÓSTICO
O agente de diagnóstico não é um chatbot — é um agente com tools específicas: ler arquivos de step, fazer grep nos steps, ver o estado atual da sessão, propor uma regra de extração, propor injeção direta de valor, propor substituição de um extrator. Ele recebe o FailureContext (step que falhou, request tentado, response recebida, estado da sessão, extratores usados) e retorna um Patch. O engine aplica o patch e tenta o step novamente. Limite de 1 tentativa de LLM por step.

SOBRE O CRITÉRIO DE SUCESSO
O critério é definido pelo usuário antes de rodar. Tipos suportados: url_match (regex contra a URL final), status_code (código exato), body_contains (substring no body), html_element_present (CSS selector via BeautifulSoup), composite (AND de critérios). O validator roda apenas no último step — não valida steps intermediários.
```

---

## FASE 3 — Plan

**Comando:** `/speckit.plan`

```
Stack técnico e decisões de implementação:

LINGUAGEM E RUNTIME
Python 3.11+. Gerenciador de pacotes: uv. O projeto é inicializado com uv init har-reproducer, que cria o pyproject.toml e o .python-version. O virtualenv fica em .venv local ao projeto.

DEPENDÊNCIAS DE PRODUÇÃO
- httpx: cliente HTTP com suporte a HTTP/1.1 e HTTP/2. É o único cliente HTTP usado — nenhum requests ou urllib direto.
- pydantic: todos os modelos de dados públicos são Pydantic BaseModel. Validação automática na instanciação.
- beautifulsoup4: parsing de HTML nos extratores CSSAgent e nas buscas de origem em body HTML.
- jsonpath-ng: extração de valores em bodies JSON no JSONPathAgent.

DEPENDÊNCIAS DE DESENVOLVIMENTO
- pytest: runner de testes.
- pytest-httpx: mock do servidor HTTP nos testes do engine. É a única forma de simular respostas HTTP nos testes.

ESTRUTURA DO PACOTE
har_reproducer/
├── __init__.py
├── cli.py              ← entry point (har-reproducer = "har_reproducer.cli:main")
├── models.py           ← todos os Pydantic models compartilhados
├── parser.py           ← HAR Parser (split_har, load_har, parse_entry, decode_body)
├── session.py          ← SessionStore (set, get, render, render_dict, all)
├── grep_utils.py       ← grep_in_real_responses, parse_grep_output, grep_variants
├── tracker.py          ← analyze_step e pipeline completo (8 etapas)
├── engine.py           ← run, execute_step, recovery rules, apply_extractors
├── validator.py        ← SuccessCriteria, validate, check_* functions
└── agents/
    ├── __init__.py
    ├── base.py         ← BaseAgent, run_tdd_loop, run_pytest_in_memory
    ├── cookie_agent.py
    ├── header_agent.py
    ├── jsonpath_agent.py
    ├── css_agent.py
    └── regex_agent.py

tests/
├── __init__.py
├── conftest.py         ← fixtures compartilhadas: tmp_steps_dir, tmp_real_responses_dir, load_fixture
├── fixtures/
│   ├── simple_flow.har
│   ├── complex_flow.har
│   ├── jwt_in_html.har  ← usada nos testes do LLM Agent (Fase 3)
│   └── tracker/
│       ├── tracker_jwt_body/       (steps/ + real_responses/)
│       ├── tracker_set_cookie/
│       ├── tracker_csrf_html/
│       ├── tracker_redirect_param/
│       ├── tracker_script_token/
│       ├── tracker_static_headers/
│       ├── tracker_unknown_origin/
│       ├── tracker_ambiguous/
│       └── tracker_complex_flow/
├── test_models.py
├── test_session.py
├── test_grep_utils.py
├── test_validator.py
├── parser/
│   ├── test_load_har.py
│   ├── test_decode_body.py
│   ├── test_parse_entry.py
│   ├── test_options_skip.py
│   ├── test_split_har.py
│   └── test_complex_flow.py
├── tracker/
│   ├── test_compare_baseline.py
│   ├── test_find_origin.py
│   ├── test_curl_template.py
│   ├── test_jwt_body.py
│   ├── test_set_cookie.py
│   ├── test_csrf_html.py
│   ├── test_redirect_param.py
│   ├── test_script_token.py
│   ├── test_static_headers.py
│   ├── test_unknown_origin.py
│   ├── test_ambiguous.py
│   ├── test_complex_flow.py
│   └── test_dry_run.py
├── agents/
│   ├── test_base.py
│   ├── test_cookie_agent.py
│   ├── test_jsonpath_agent.py
│   ├── test_css_agent.py
│   └── test_regex_agent.py
├── engine/
│   ├── test_build_request.py
│   ├── test_apply_extractors.py
│   ├── test_recovery.py
│   └── test_run_simple_flow.py
└── agent/
    ├── test_diagnose_jwt_html.py
    └── test_apply_patch.py

ARTEFATOS GERADOS EM RUNTIME (fora do pacote Python)
steps/            ← gerado pelo comando parse
real_responses/   ← gerado pelo comando run durante a execução
curls/            ← gerado pelo tracker durante a execução
extractors/       ← gerado pelos agentes durante a execução
extractor_tests/  ← testes TDD gerados antes dos extratores

IMPLEMENTAÇÃO DO CLI
Entry point: har-reproducer = "har_reproducer.cli:main" no pyproject.toml.
Subcomandos implementados com argparse:
- parse: chama split_har(har_path, output_dir), imprime número de steps gerados
- run: chama engine.run(har_path, config), suporta --dry-run
- diagnose: chama agent.diagnose(context, steps_dir, real_responses_dir), imprime patch proposto

IMPLEMENTAÇÃO DO TOKEN TRACKER — pipeline de 8 etapas
A função principal é analyze_step(step_index, steps_dir, real_responses_dir, extractor_registry) -> StepAnalysis.

Etapa 1: carregar req_0000.json (baseline) e req_{N:04d}.json (step atual).
Etapa 2: extrair todos os valores de req[N] em dict plano nome→valor, cobrindo headers, cookies, body fields (JSON e form-urlencoded), query params.
Etapa 3: comparar com baseline. Valores iguais → static. Valores diferentes ou ausentes no baseline → candidate. Nomes que batem com ALWAYS_DYNAMIC_PATTERNS nunca vão para static.
Etapa 4: gerar rascunho do CurlTemplate com estáticos preenchidos e candidatos como {{token_id_provisório}}.
Etapa 5: para cada candidate, chamar grep_in_real_responses(value, real_responses_dir, max_step=step_index). Se não encontrar, tentar grep_variants com URL-decoded e base64-decoded. Se ainda não encontrar, mover para unresolved.
Etapa 6: para cada candidate com origem: verificar registry. Se extrator verificado já existe, reutilizar. Se não, gerar teste TDD com expected=real_matched_value, ativar agente especializado por tipo de origem, rodar run_tdd_loop (máx 5 tentativas). Se verificado, registrar no registry. Se não, mover para unresolved.
Etapa 7: finalizar CurlTemplate — substituir provisórios por token_ids definitivos, reverter unresolveds para valor estático do HAR com comentário de aviso.
Etapa 8: salvar curls/req_{N:04d}.curl.sh e extractors/extract_<token_id>.py. Imprimir log de diagnóstico no formato definido.

IMPLEMENTAÇÃO DO REQUEST ENGINE
A função run(har_path, config) -> bool orquestra:
1. Chama split_har para gerar steps/ (idempotente se já existir).
2. Executa req[0] diretamente com httpx, salva real_responses/res_0000.json.
3. Para N = 1, 2, ..., último step não-skip:
   a. Chama analyze_step(N, steps_dir, real_responses_dir, extractor_registry).
   b. Renderiza o curl template com session.render().
   c. Constrói httpx.Request a partir do CurlTemplate renderizado.
   d. Executa via httpx, salva real_responses/res_{N:04d}.json.
   e. Aplica extratores na response real → alimenta SessionStore.
   f. Se falhar: tenta recovery determinístico → tenta LLM agent → loga falha.
4. Chama validator.validate(last_response, criteria) e retorna resultado.

INTEGRAÇÃO COM API ANTHROPIC
Os agentes especializados (CookieAgent, HeaderAgent, JSONPathAgent, CSSAgent, RegexAgent) chamam a API Anthropic com o modelo claude-sonnet-4-6 para gerar código Python. O agente de diagnóstico também usa a API com tool_use.
A chave de API é lida de ANTHROPIC_API_KEY no ambiente — nunca hardcoded.
Nos testes, a API é sempre mockada. Nenhum teste faz chamada real à API.

CONFIGURAÇÃO DO PYTEST
pytest.ini com testpaths = tests e pythonpath = .
conftest.py na raiz de tests/ com fixtures compartilhadas:
- tmp_steps_dir: diretório temporário para steps
- tmp_real_responses_dir: diretório temporário para real_responses
- load_fixture(fixture_name): carrega steps e real_responses de tests/fixtures/tracker/<fixture_name>/
```

---

## FASE 4 — Tasks

**Comando:** `/speckit.tasks`

> Rode sem argumentos adicionais. O agente vai gerar o tasks.md a partir do plan.md. O arquivo tasks.md já existe e está detalhado — o agente deve usá-lo como referência e pode incorporá-lo diretamente ou reorganizá-lo conforme a estrutura do spec kit.

---

## FASE 5 — Implement

**Comando:** `/speckit.implement`

> Rode sem argumentos adicionais. O agente vai executar as tarefas em ordem, respeitando as dependências definidas.

**Pontos de atenção para validar durante a implementação:**

Após a Fase 1 (HAR Parser), validar manualmente:
```bash
uv run har-reproducer parse --har tests/fixtures/simple_flow.har --output /tmp/steps
ls /tmp/steps   # deve mostrar req_0000.json, res_0000.json, req_0001.json, ...
```

Após a Fase 2 (Token Tracker + Engine), validar:
```bash
uv run pytest tests/           # todos os testes devem passar
uv run har-reproducer run --har tests/fixtures/simple_flow.har --dry-run
# deve imprimir relatório com candidatos detectados e origens encontradas
```

Após a Fase 3 (LLM Agent), validar:
```bash
uv run pytest tests/agent/     # testes com mock da API devem passar
```

Após a Fase 4 (ponta a ponta), validar:
```bash
uv run pytest                  # 100% de todos os testes
bash -n curls/req_0001.curl.sh # sintaxe do curl válida
uv run har-reproducer run --har real.har
# Success Validator deve confirmar critério atingido
```
