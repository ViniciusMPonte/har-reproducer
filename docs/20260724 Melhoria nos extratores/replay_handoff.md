# Handoff — Ferramenta de Replay a partir de Curls Salvos

> Ponto de partida para uma conversa nova. Não é um PRD de produto — é um resumo técnico do que já existe, pra não precisar redescobrir nada, mais a lista do que ainda está em aberto especificamente para esta ferramenta.

## Objetivo desta próxima etapa

Construir uma ferramenta que reexecuta o fluxo **a partir dos curls já salvos em disco** (`req_XXXX.curl.sh`, com placeholders `{{extractor:token_id}}`), em vez de rodar o `Engine` inteiro contra o `.har` original — para um step específico ou para todos. Esse era o objetivo final declarado desde o início do projeto; as 18 tasks já concluídas (ver `implementation_plan.md`) construíram a base que viabiliza isso, mas não entregam a ferramenta em si.

## Estado atual do sistema (já implementado, tratar como dado, não redesenhar)

- **`CurlGenerator.generate(request, tokens)`** — formata um `StepRequest` em texto de curl. Com `tokens` preenchido, gera com placeholders + comentários de origem; com `tokens=[]`, gera literal. Usado tanto para o template salvo quanto para o curl literal executado internamente pelo transporte.
- **`PlaceholderApplier`** — muta um `StepRequest` trocando valor literal por `{{extractor:token_id}}` em headers, cookies, body **e URL**.
- **`SessionStore.render(texto)`** — resolve `{{extractor:token_id}}` em **qualquer string**, não só em `StepRequest`. Isso importa muito para o replay: dá pra ler o `.curl.sh` salvo como texto puro e chamar `render()` direto nele, sem precisar fazer parsing do curl de volta pra um objeto estruturado.
- **`TokenResolver`** (arquivo próprio, `har_reproducer/tracking/token_resolver.py`) — única lógica de resolução de token (reexecuta `Extractor.code` contra response salva em disco, atualiza `SessionStore`). Usada pelo `Engine` hoje, e é exatamente a peça pensada para ser reaproveitada aqui.
- **`ExtractorRunner.run_existing(token_id)`** — roda um extractor **só a partir do `token_id`**, sem precisar do model `Extractor` nem do registry inteiro em memória. Cada `extract_{token_id}.py` em disco já é autocontido (código + `step_index` embutidos no próprio arquivo).
- **`CurlHttpTransport`** — executa curl de verdade via `subprocess`, atrás de um `mitmproxy` já em execução, captura a resposta via HAR e devolve `StepResponse`. Essa é a via de execução real que a ferramenta de replay também deveria usar (não faz sentido reimplementar execução via `httpx` de novo).
- **`MitmProxyOrchestrator`** — sobe/derruba o `mitmdump`. Hoje desenhado para envolver `engine.run()`; para o replay, precisa envolver uma chamada diferente (não existe um "Engine" rodando um `.har`).
- **`Workspace`** — tem `curl_file(index)`, `response_file(index)`, `extractor_file(token_id)`, `mitm_capture_file()` já formalizados.

## Perguntas específicas do replay, ainda não respondidas — usar como ponto de partida da conversa nova

1. **Replay de um step isolado**: se o token daquele step depende da response de um step *anterior* que não está sendo reexecutado nessa sessão, de onde vem o valor atualizado — do `res_XXXX.json` já salvo em disco da execução original (provavelmente), ou isso precisa de alguma outra fonte?
2. **Replay de todos os steps**: precisa repetir a sequência completa do `Engine` (analisar → resolver token → montar request final → executar → persistir), ou como o template e os extractors já existem prontos em disco, o fluxo pode ser mais enxuto (só resolver + executar, sem reanálise)?
3. **Retry/erro**: mantém o mesmo comportamento de `MAX_STEP_ATTEMPTS`/`RECOVERABLE_STATUS_CODES` do `Engine`, ou o replay tem uma política própria?
4. **Onde persistir o resultado do replay** — sobrescreve `res_XXXX.json`/`req_XXXX.json` originais, ou grava em diretório paralelo para não perder o histórico da execução original?
5. **Formato de entrada da CLI** — novo subcomando (ex. `har-reproducer replay --output <dir> --step N` / `--all`)? Onde isso se encaixa em `cli_parser.py`/`cli_handlers.py`?
6. **`MitmProxyOrchestrator`** — reaproveitável como está, ou precisa de ajuste para envolver uma função diferente de `engine.run()`?

## Arquivos recomendados para anexar na conversa nova

Priorize as versões **atuais, pós-implementação** (não as antigas mostradas nesta conversa) de: `curl_generator.py`, `placeholder_applier.py`, `session_store.py`, `token_resolver.py`, `extractor_runner.py`, `curl_http_transport.py`, `mitm_proxy_orchestrator.py`, `workspace.py`, `workspace_dir.py`, `cli_handlers.py`, `cli_parser.py`. Mais `spec.md` e `implementation_plan.md` como referência de decisões já tomadas.

## Como iniciar a conversa nova

Anexe este documento + os arquivos acima, e diga algo como: *"Aqui está o contexto de um projeto em andamento. Quero planejar [a ferramenta de replay descrita no documento]. Vamos seguir o mesmo processo: você me pergunta o que precisa saber antes de propor qualquer spec."* Isso reproduz o mesmo modo de trabalho desta conversa, sem carregar o histórico inteiro.
