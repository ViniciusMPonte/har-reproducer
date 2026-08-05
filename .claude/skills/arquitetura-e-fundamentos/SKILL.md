---
name: arquitetura-e-fundamentos
description: Mapa dos componentes do projeto (pipeline dos comandos run/parse/replay, papel e conexão de cada módulo) e o princípio de genericidade que guia decisões de design — descobrir padrões em runtime em vez de assumir formatos fixos de protocolo/site. Use ao explicar como o projeto funciona, ao decidir onde encaixar um componente novo, ou ao avaliar se uma mudança está reforçando ou violando a genericidade do projeto.
---

# Arquitetura e Fundamentos — mapa do código e princípio de design

## O que este projeto faz

`har_reproducer` reproduz um fluxo HTTP inteiro a partir de um arquivo `.har`
gravado de forma completa (com o body de toda requisição, sem omissões) — sem
saber de antemão nada sobre o site de origem: nem quais headers ele usa para
sessão, nem onde ficam tokens de CSRF, nem que formato de cache ele adota.
Cada `.har` é uma amostra única; o sistema tem que **descobrir** os valores
dinâmicos daquele fluxo específico (o que muda entre requests: cookies de
sessão, tokens de autenticação, headers de cache) e aprender como
recalculá-los antes de repetir cada request. Isso é o que a seção "Princípio
de genericidade" (mais abaixo) descreve em detalhe — vale ler antes de
adicionar heurística nova a qualquer componente deste mapa.

## Mapa do código

### Modelos e armazenamento de estado

- **`har_reproducer/models/`** (`http.py`, `session.py`, `config.py`,
  `criteria.py`, `analysis.py`) — os dados que atravessam o pipeline:
  `Step`/`StepRequest`/`StepResponse` (um request+response do HAR),
  `DynamicToken`/`Extractor`/`TokenLocation`/`AgentType` (o que descreve um
  valor dinâmico e como extraí-lo), `ProjectConfig`/`LLMSettings`/
  `SkipRulesConfig`/`SuccessCriterion` (config.json), `StepAnalysis` (saída da
  análise de um step).
- **`har_reproducer/session/session_store.py`** — `SessionStore` guarda
  `SessionState` (`tokens: Dict[str,str]`, `registry: Dict[str,Extractor]`) e
  resolve placeholders `{{extractor:<hash>}}` em templates de curl via
  `render`/`render_dict` (`TOKEN_PLACEHOLDER_PATTERN`). É o ponto único onde um
  `token_id` (hash) se torna um valor literal na hora de montar o request real.
- **`har_reproducer/fs_io/workspace.py`** — `Workspace` centraliza os
  caminhos do diretório de output (`curls/`, `real_responses/`,
  `original_responses/`, `extractors/`, `replays/`, `mitm_capture/`). Nunca
  limpa nada entre execuções — reaproveitar o mesmo `--output` entre rodadas
  deixa arquivos de rodadas anteriores no disco (relevante para qualquer
  componente que varre esses diretórios em busca de arquivos por índice de
  step).

### Pipeline do comando `run` (`parse` + `reproduce`)

1. `CliParser`/`CliHandlers.handle_run` (`har_reproducer/cli/`) — parseia
   `--har`/`--output`/`--mode`/`--config`/`--reset`, carrega `config.json`
   (`ProjectConfigLoader`) e decide se a engine escolhida usa rede
   (`EngineMode`/`EngineFactory` → `Engine` ou `DryEngine`).
2. Se usa rede: `MitmProxyOrchestrator` (`reproduction/mitm_proxy_orchestrator.py`)
   sobe um `mitmdump` com o addon `MitmAddon` (`reproduction/mitm_addon.py`),
   que grava cada request/response real interceptado em
   `Workspace.mitm_capture_file()` — é assim que o pipeline vê a resposta
   *real* do servidor, não a resposta gravada no `.har` original.
3. `Engine._reproduce` (`engines/engine.py`) itera as entries do HAR
   (`HARParser.get_entries`/`parse_entry`, `fs_io/har_parser.py`), na ordem
   original, e por step:
   - `StepSkipEvaluator` decide se pula o step (scheme inválido, método na
     lista de skip rules do `config.json`).
   - `TokenTracker.analyze_step` (`tracking/`) — o núcleo da descoberta de
     padrões: `BaselineDiff` compara o request atual contra o request
     baseline (primeira entry do HAR) para achar candidatos a valor dinâmico;
     `CandidateResolver` decide de onde cada candidato "vem" (`ResponseGrep`
     busca a resposta de origem, restrita a steps anteriores ao step atual —
     nunca uma response futura, o que garantiria uma dependência impossível
     de satisfazer numa reprodução sequencial) e delega a um `Agent`
     (`agents/`, escolhido por `TokenLocation` via `LOCATION_AGENTS`) a
     geração do código Python que extrai aquele valor daquela resposta.
   - Cada `Agent` (`CookieAgent`/`HeaderAgent`/`JSONPathAgent`/`CSSAgent`/
     `RegexAgent`, todos em `agents/`, base comum `BaseAgent`) roda um loop
     TDD (`run_tdd_loop`): tenta estratégias determinísticas específicas do
     tipo de location primeiro, e só recorre a LLM (`ExtractorPrompt.build` +
     `BaseChatModel.invoke`, `prompts/extractor_prompt.py`) depois de esgotá-las
     — cada tentativa é validada de fato executando o código gerado contra a
     resposta real antes de aceitar (nunca "parece certo", sempre "roda e bate
     com o valor esperado").
   - `TokenResolver.resolve_all()` resolve os tokens pendentes desse step
     (populando `SessionStore`); `SessionStore.render` substitui os
     placeholders no template de curl gerado por `CurlGenerator`.
   - `CurlHttpTransport.send_request` executa o curl roteado pelo proxy;
     `StepRetryPolicy` tenta de novo (até 2x) em caso de `400`/`401`, disparando
     `Engine.handle_recovery` → `TokenResolver.resolve_all(force=True)`.
4. `Validator.validate` (`validation/validator.py`) checa os
   `success_criteria` do `config.json` contra a última resposta não pulada.

### Pipeline do comando `replay`

Reexecuta os `.curl.sh` já gerados por um `run` anterior, sem rodar `Agent`s
de novo — só resolve tokens usando os extractors já persistidos
(`ExtractorRunner.run_existing`, `ExtractorMetadataStore`) e um
`SessionStore` novo. `CliHandlers.handle_replay`/`_build_replay_runner`
monta o `ReplayRunner` com `CurlDependencyParser` (lê os comentários
`# Token <id> comes from response of step <n>` de cada `.curl.sh`),
`ReplayTokenResolver` (decide de qual diretório ler a resposta de origem de
cada token) e `ReplayResultComparator` (compara a última resposta do replay
com uma resposta de referência, em vez dos `success_criteria` do `Validator`).
Suporta 4 modos (`all`/`slice`/`smart`/`list`, ver `ReplayRunner._schedule_*`).

### Módulos de suporte

- **`config/project_config_loader.py`** — carrega/valida `config.json`
  (fail-soft: erro de parse retorna `ProjectConfig()` vazio, nunca crasha).
- **`llm/`** — `LLMFactory` + `LLMProvider`/`providers.py` (Ollama, Google,
  OpenAI, Anthropic) resolvem o `BaseChatModel` concreto a partir de
  `LLMSettings.provider`; é o `BaseChatModel` que `BaseAgent._llm_strategy`
  invoca como último recurso.
- **`templates/`** — `ExtractorTemplate` serializa o código de um extractor em
  3 variantes de script (bash final, verificação em memória durante o TDD
  loop, script final que lê `res_NNNN.json` real); `IdentifierSanitizer` gera
  nomes de função Python válidos a partir de um `token_id` (hash hex).

## Princípio de genericidade

A decisão de design mais importante do projeto, e a que mais frequentemente
é violada por acidente ao adicionar uma feature nova:

> **O código nunca deveria assumir de antemão como um site específico se
> comporta — ele deve descobrir isso a partir da evidência que o próprio HAR
> fornece.** Nenhum header, formato de token, ou convenção de cache é
> hardcoded como "é sempre assim"; o sistema compara, busca origem, e só então
> decide.

Onde esse princípio já está encarnado no código:

- **`BaselineDiff`** não sabe o que é um "token de sessão" — ele só sabe
  comparar o request atual contra um baseline e marcar como candidato
  qualquer coisa que difira. A descoberta de *que tipo* de coisa é (cookie,
  header, cache) vem depois, olhando a evidência, não de uma suposição prévia.
  ⚠️ Isso é genérico só até certo ponto: o baseline usado é sempre a primeira
  entry do HAR (`BaselineDiff.compare`, `tracking/baseline_diff.py`) — um
  header constante do client que essa primeira entry não carrega (ex.: um
  header que só aparece em requests via `fetch`/XHR, não na navegação inicial
  do documento) é redetectado como candidato dinâmico em todo step
  subsequente, mesmo sendo estático.
- **`ResponseGrep`** não recebe uma lista de "de onde tokens costumam vir" —
  ele varre respostas de fato em busca do valor literal (ou variantes
  decodificadas), restringindo a busca por causalidade temporal (só considera
  respostas de steps anteriores ao step que está sendo analisado), não por
  uma regra de protocolo.
- **`TokenLocationDetector`/`LOCATION_AGENTS`** despacham para o `Agent`
  certo (`Cookie`/`Header`/`JSONPath`/`CSS`/`Regex`) só depois de checar onde
  o valor de fato apareceu na resposta amostrada — não por suposição de
  content-type ou convenção de API.
- **Determinístico antes de LLM** (`BaseAgent.deterministic_strategies` →
  `_llm_strategy` como último recurso) — mesmo quando é preciso "inteligência"
  para achar o padrão, o sistema prefere um padrão estrutural genérico
  (posição, chave, regex de contexto) a uma regra específica de um site, e só
  recorre ao LLM quando a estrutura não é reconhecível de forma determinística.
- **Extractor literal como fallback, não como padrão** (`AgentType.LITERAL`/
  `LITERAL_FALLBACK`) — quando a origem não pode ser determinada com
  confiança, o sistema admite isso (mantém o valor literal do HAR) em vez de
  inventar uma regra específica só para "resolver" aquele caso.

## Retro de arquitetura (auto-atualização)

Este arquivo é vivo — ele deveria acompanhar o código, não descrever uma foto
antiga dele. O gatilho normal de atualização é o **Passo 5** de
[[spec-e-plano]] (fechamento de uma spec/plano): ao fechar uma etapa, se a
mudança implementada alterou a forma como algum componente deste mapa se
encaixa no pipeline, corrigiu uma limitação descrita aqui, ou revelou um novo
lugar onde o código assume algo fixo em vez de descobrir — propor um diff para
este arquivo, atualizando a descrição do componente afetado para refletir o
comportamento atual.

⚠️ Mesma regra de [[spec-e-plano]]: nunca editar este arquivo sem mostrar o
diff proposto e esperar aprovação explícita do usuário antes de aplicar. E a
atualização é sempre sobre o que o código **faz hoje** — esta skill não é
lugar para lista de tarefas pendentes; se algo vale corrigir, isso é assunto
de uma spec nova, não desta skill.
