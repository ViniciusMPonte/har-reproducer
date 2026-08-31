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
  valor dinâmico e como extraí-lo; `Extractor.captured_value` guarda o literal
  capturado no HAR, usado como fallback no replay), `ProjectConfig`/`LLMSettings`/
  `SkipRulesConfig`/`SuccessCriterion` (config.json), `StepAnalysis` (saída da
  análise de um step).
- **`har_reproducer/session/session_store.py`** — `SessionStore` guarda
  `SessionState` (`tokens: Dict[str,str]`, `registry: Dict[str,Extractor]`) e
  resolve placeholders `{{extractor:<hash>}}` em templates de curl via
  `render`/`render_dict` (`TOKEN_PLACEHOLDER_PATTERN`). É o ponto único onde um
  `token_id` (hash) se torna um valor literal na hora de montar o request real.
- **`har_reproducer/fs_io/workspace.py`** — `Workspace` centraliza os
  caminhos do diretório de output (`curls/`, `real_responses/`,
  `original_responses/`, `extractors/`, `replays/`, `mitm_capture/`). É uma
  instância comum, não singleton: o construtor recebe `output_dir` e
  materializa os oito subdiretórios eagerly; cada comando (`run`/`replay`)
  constrói a sua própria e a repassa por construtor a quem precisa de um
  caminho (`Engine`, `EngineFactory`, `AgentFactory`, `BaseAgent`, e aos
  colaboradores de `reproduction/`/`replay/`). Nunca limpa nada entre
  execuções — reaproveitar o mesmo `--output` entre rodadas deixa arquivos de
  rodadas anteriores no disco (relevante para qualquer componente que varre
  esses diretórios em busca de arquivos por índice de step).

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
     (`agents/`, escolhido por `TokenLocation` via
     `AgentFactory.LOCATION_AGENTS`, `agents/construction/agent_factory.py`)
     a geração do código Python que extrai aquele valor daquela resposta.
   - Cada `Agent` (`CookieAgent`/`HeaderAgent`/`JSONPathAgent`/`CSSAgent`/
     `RegexAgent`, todos em `agents/`, base comum `BaseAgent`) roda um loop
     TDD (`run_tdd_loop`): tenta estratégias determinísticas específicas do
     tipo de location primeiro, e só recorre a LLM (`ExtractorPrompt.build` +
     `BaseChatModel.invoke`, `prompts/extractor_prompt.py`) depois de esgotá-las
     — cada tentativa é validada de fato executando o código gerado contra a
     resposta real antes de aceitar (nunca "parece certo", sempre "roda e bate
     com o valor esperado"). ⚠️ `run_tdd_loop` deriva o `agent_type` do
     `Extractor` gerado a partir do próprio nome da classe
     (`AgentType(self.__class__.__name__)`, `agents/base_agent.py`) — qualquer
     subclasse de `BaseAgent` (produção ou dublê de teste) só funciona nesse
     método se `__class__.__name__` coincidir exatamente com um valor do enum
     `AgentType` (`CookieAgent`, `HeaderAgent`, `JSONPathAgent`, `CSSAgent`,
     `RegexAgent`, `LiteralAgent`, `LiteralFallbackAgent`).
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
cada token; se a extração dinâmica falhar, cai para o `captured_value`
persistido e devolve os conjuntos `(static, fallback)` — token que caiu no
fallback nunca é anotado como estático) e `ReplayResultComparator` (compara a
última resposta do replay com uma resposta de referência, em vez dos
`success_criteria` do `Validator`). `ReplayRunner` anota no `.curl.sh` o token
que caiu no fallback (` - could not extract value from response, using
captured value`), reporta cada step (`Replay step results:`) e aplica o
veredito híbrido: `✓ SUCCESS` só se o último step casar e nenhum intermediário
tiver `status_code == 0`.
Suporta 4 modos (`all`/`slice`/`smart`/`list`, ver `ReplayRunner._schedule_*`).

### Pipeline do comando `extractor`

Único ponto de entrada que **edita** artefatos já persistidos por um `run` anterior
(`.curl.sh`, `extract_<id>.py`/`.meta.json`) em vez de gerá-los do zero a partir do
HAR — `run`/`dry` criam, `replay`/`optimize` só leem e reexecutam, `extractor` é o
único que também escreve de volta sobre o que já existe. `ExtractorCliHandlers`
(`cli/extractor_cli_handlers.py`) expõe 8 ações (`list`/`get`/`create`/`update`/
`delete`/`bind`/`unbind`/`test`) para correção pontual de extractors — sem rodar
`Agent`/LLM de novo, sem subir o proxy/mitm. Toda escrita (`create`/`update`) só
acontece depois de validar o `code` fornecido contra pelo menos uma resposta real
(`ExtractorValidator`), nunca via `ExtractorRunner.run()` (que escreve o `.py` antes
de comparar — ver ⚠️ abaixo). `ExtractorCurlBinder` edita um `.curl.sh` persistido em
lugar (bind/unbind de um placeholder), reaproveitando o mesmo padrão de tokenização
por `shlex` de `CookieJarCurlOverride`, mas separando as linhas de comentário do
corpo antes de tokenizar — a saída aqui é persistida, não efêmera como a de
`CookieJarCurlOverride.apply`, então perder uma linha de comentário de outro token
seria uma regressão real, não um detalhe sem efeito.

⚠️ `ExtractorRunner.run(extractor)` escreve `extract_<id>.py` em disco **antes** de
executar e comparar o resultado (`_write_extractor_script` roda primeiro) — não serve
como "validar antes de aceitar". Qualquer novo consumidor que precise validar um
`code` contra uma resposta sem arriscar deixar um `.py` quebrado persistido deve usar
`ExtractorValidator.run_against_samples` (escreve só em `temp_extractors/`, nunca em
`extractors/`), não `ExtractorRunner.run()`. Ver `docs/20260829 CRUD de Extractors/spec.md`,
seção 3.4, para o raciocínio completo.

### Jar de cookies (`CookieJar`)

`run`, `replay` e `optimize` compartilham um `CookieJar` (`session/cookie_jar.py`) que simula a
propagação automática de cookies de um navegador: toda resposta lida (fresca ou cacheada)
alimenta o jar via `feed()` com os cookies e atributos (`domain`/`path`/`expired`) que o
`Set-Cookie` declarou; toda request subsequente cujo host/porta/path casem com o escopo de um
cookie conhecido tem esse cookie sobreposto ao que o HAR gravou, via `CookieJarCurlOverride`
(`reproduction/cookie_jar_curl_override.py`), que reescreve o `--cookie` de um `.curl.sh` já
resolvido tokenizando por regras de shell (`shlex`), nunca por regex de texto livre.
`RequestUrlScope` (`reproduction/request_url_scope.py`) deriva `(host, porta, path)` de uma URL —
compartilhado pelos três modos.

⚠️ `ReplayOptimizer` é o único ponto que precisa resetar e realimentar o jar manualmente
(`_feed_cookie_jar_from_backbone_cache`), porque o mesmo `schedule_executor`/jar atravessa todas
as tentativas de uma busca — sem isso, cookies de uma tentativa vazariam pra próxima. A
alimentação a partir do backbone cacheado precisa acontecer **antes** de qualquer tráfego novo da
tentativa, não depois — inverter essa ordem faz a feature virar no-op silencioso.

⚠️ `_feed_cookie_jar_from_backbone_cache`/`_execute`/`_confirm` aceitam um filtro opcional
(`restrict_to`/`restrict_backbone_feed_to`, default `None` = alimenta o backbone inteiro) —
usado só por `_reduce_anchors`, restringindo o feed ao `trial_final_list` que está sendo testado
naquela chamada. É indispensável ali porque `_reduce_anchors` é o único caso em que o índice
sendo testado para remoção é, ele mesmo, membro do backbone: sem o filtro, o cookie que só esse
índice estabelece já estaria no jar antes do teste rodar, mascarando a dependência e fazendo uma
âncora indispensável ser removida do `.txt` exportado por engano. `_run_phase1` e
`_attempt`/`_resolve_range` continuam chamando sem o filtro (backbone é pré-requisito fixo
nessas duas fases, nunca candidato a ausência) — não generalizar o filtro pra elas.

⚠️ Dívida técnica aceita conscientemente, replicando limitações do próprio `stickycookie` do
mitmproxy (usado como referência de implementação): sem regra de precedência determinística entre
dois escopos que colidem no mesmo nome de cookie, e casamento de path por prefixo simples
(`startswith`), não pelo algoritmo exato do RFC 6265 — um cookie `Path=/foo` também vaza para
`/foobar`. Ver `docs/20260827 Jar de Cookies Determinístico entre Steps/spec.md`, seções 1 e 5,
para os casos de borda completos.

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
- **Fallback para o valor capturado no replay** — quando a extração dinâmica
  falha no replay, o sistema usa o literal que o servidor realmente enviou
  naquele ponto do fluxo original (`Extractor.captured_value`), em vez de
  marcar o token como falho ou inventar regra específica de site.

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
