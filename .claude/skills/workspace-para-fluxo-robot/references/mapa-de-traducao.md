# Mapa de tradução — workspace `har_reproducer` → DSL `http-robot-service`

Este arquivo é a fonte de verdade da tradução campo a campo. As duas skills de
origem descrevem cada lado isoladamente; aqui está a correspondência entre
eles, que não existe em nenhuma delas porque cada uma ignora a existência da
outra.

## 1. Estrutura: workspace → insumo da DSL

| Artefato do workspace | Insumo correspondente na DSL |
|---|---|
| `replays/optimized_<run_id>.txt` (lista ordenada dos índices de passo sobreviventes) | Uma `Tarefa` por índice, na mesma ordem — encadeadas pela sequência natural do fluxo (`tarefaAlvo`/roteamento), não por reconstrução manual da ordem |
| `original_requests/req_NNNN.json` + `curls/req_NNNN.curl.sh` daquele índice | Método, URL, headers e corpo daquela `Tarefa`. O `curl` já mostra o `{{extractor:<token_id>}}` no lugar exato de cada valor dinâmico — é o comentário `# Token <id> comes from response of step <n>` que diz de qual `Tarefa` anterior extrair |
| `extractors/extract_<token_id>.py` + `.meta.json` (campo `agent_type`) | Um extrator na `Tarefa` do `origin_step` do token — ver tabela 2 para o tipo exato |
| `config.json` → `success_criteria` do passo alvo | Um ou mais Validadores na `Tarefa` correspondente — ver tabela 3 |
| `real_responses/res_NNNN.json` de cada passo | Fonte dos valores reais para os asserts do replay spec (`references/testes-de-eficacia.md`) — não precisa reconsultar o portal para saber o que uma resposta contém |

Índice de login (se houver, identificado no `--required-steps-file` do
`optimize` ou perguntado ao usuário): vira `TarefaLogin` num fluxo
`_login_cache.groovy` separado, nunca inline no fluxo principal — regra
normal de `oficina-de-fluxos` (`references/autenticacao.md`), sem
particularidade aqui.

## 2. `agent_type` → extrator da DSL

| `agent_type` (`.meta.json`) | Extrator no robô | Observações |
|---|---|---|
| `RegexAgent` | `extratorRegex` | Mesma expressão. Confira `posicaoGrupo` — o código gerado pelo `har_reproducer` (ver `.py` do extrator) mostra explicitamente qual grupo/posição usa; não assuma grupo 1 por padrão. |
| `JSONPathAgent` | `extratorJson` | O `har_reproducer` guarda o caminho em sintaxe JSONPath (ex.: `$.data.accessToken`); a DSL usa caminho separado por ponto sem o prefixo `$.` (`data.accessToken`). Remover o prefixo é a única transformação necessária no caso comum; um JSONPath com filtro/wildcard (`$.items[*].id`) não tem equivalente direto em `extratorJson` — nesse caso use `extratorMultiploJson`. |
| `CSSAgent` | `extratorCss` | Seletor e `attr` (se houver) são diretos. |
| `HeaderAgent` | **Sem extrator dedicado.** Ler no hook `posExtrair` via `variaveis.respostaRequisicao.getFirstHeader('<Nome>').value` e salvar com `fluxo.adicione(...)` (ver `dsl.md` §6 "Acesso à Resposta HTTP") | O corpo do hook continua sendo um one-liner delegando pro Helper, como qualquer outro hook — a lógica de leitura de header vai no método do Helper, não inline. |
| `CookieAgent` | Normalmente **nada a fazer** — ligue `usarCookiesAutomaticos: true` no fluxo e o robô gerencia o cookie de sessão sozinho, do jeito que o navegador/mitmproxy fez na captura | Só monte uma extração explícita (mesmo padrão de `HeaderAgent`, mas lendo `cookies` da resposta) se o valor do cookie for usado **fora** do jar automático — por exemplo, colado dentro da URL ou do corpo de outro passo. |
| `LiteralAgent` / `LiteralFallbackAgent` | **Não traduzir automaticamente — é uma lacuna, não um extrator.** | Ver seção 4. |

## 3. `success_criteria` → Validador da DSL

| `type` em `config.json` | Validador no robô | Observações |
|---|---|---|
| `status_code` | `validacaoBasica` comparando `fluxo.tarefaAtual.responseStatusCode` com o `expected` | Não existe um validador dedicado a status code na DSL — o executor trata status via Status Handlers (`dsl.md` §6), não via Validador. `responseStatusCode` é o campo que expõe o valor pra uma checagem explícita. |
| `body_contains` | `validacaoRegex` ou `validacaoBasica` com `Validacao.CONTEM_EXPRESSAO` | Tradução direta — o `expected` do har vira a `expressao`/o texto buscado. |
| `html_element_present` | `validacaoCss` (se o `expected` for seletor CSS) ou `validacaoXpath` (se for XPath) com `Validacao.CONTEM_EXPRESSAO` | Confira no `config.json`/no extrator relacionado qual convenção o critério usa antes de escolher entre os dois — os dois tipos existem na DSL e não são intercambiáveis. |
| `url_match` | **Sem validador dedicado.** Mesmo padrão de `HeaderAgent`: ler a URL final (ex.: `Location` de um redirect, via `getFirstHeader`) num `posExtrair` e comparar em `validacaoBasica` | O Apache `HttpResponse` exposto em `variaveis.respostaRequisicao` não carrega a URL final da requisição diretamente — só headers da resposta. Se o `url_match` do har checava a URL *da própria requisição* (não um redirect), o valor já é conhecido estaticamente pela `Tarefa` e não precisa de validador nenhum: é a URL que você já escreveu. |

## 4. Lacunas: `LiteralAgent`/`LiteralFallbackAgent` como sinal, não como valor

Esses dois `agent_type` significam que o `har_reproducer` não encontrou (ou
recorreu ao LLM para decidir) nenhuma derivação estrutural determinística
(regex/JSONPath/CSS/header/cookie) para aquele token — ele ficou resolvido
pelo valor literal observado na amostra capturada. Isso é exatamente o tipo
de lacuna que o usuário pediu para os testes comprovarem, então trate cada
ocorrência como uma pergunta em aberto, não como um valor pronto para colar
no Helper:

- **Pode ser genuinamente estático** (versão de API, client ID fixo, valor de
  configuração do portal) — nesse caso, hardcodar como constante no Helper é
  correto, mas documente no PR/ticket que a origem é "observado numa amostra
  só, sem confirmação de estabilidade" (mesmo espírito de
  `extractor-crud-strategies.md` em `reproducao-de-har`: extrator ausente só
  se cria depois de confirmar contra pelo menos duas amostras — aqui a
  amostra é uma só, a do HAR original).
- **Pode ser uma dependência não capturada** que só parece estática porque o
  HAR tem uma única sessão — nesse caso hardcodar quebra silenciosamente na
  próxima execução com dado diferente.

`references/testes-de-eficacia.md` seção 3 descreve como o replay spec deve
expor essa incerteza em vez de escondê-la atrás de um valor fixo que "passa"
no primeiro teste.
