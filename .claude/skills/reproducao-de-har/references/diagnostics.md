# Diagnóstico de problemas comuns — har-reproducer

Este texto orienta um agente sobre como investigar e agir quando um `run`
ou `replay` reporta divergência: onde procurar evidência, o que pode (ou
não pode) corrigir, e como deixar rastro para investigações futuras.
Pressupõe os guardrails e o fluxo de decisão já lidos.

## 1. Workspace versionado com git

O `output/` de cada HAR é um repositório git, com commit a cada alteração
(definido no texto de configuração do workspace). É esse versionamento que
sustenta tudo o que vem a seguir neste texto: os arquivos do workspace,
sensíveis (`extractors/`, `config.json`) ou não, podem ser alterados
livremente durante os testes, porque qualquer problema tem rollback
disponível. Também abre espaço para o agente usar branches ao testar
hipóteses concorrentes — criar uma branch por hipótese, descartar a que não
funcionar, manter/mesclar a que resolver — em vez de precisar decidir de
antemão qual caminho seguir.

## 2. O que é uma divergência

Ao final de um `run`/`replay`, o resultado do último passo executado é
comparado com a referência (`success_criteria` do `config.json`, ou — na
ausência de critério — o status code da resposta de referência, lida de
`real_responses/` ou, na sua falta, `original_responses/`). Divergência é
esse resultado não bater com o esperado.

## 3. Categorias prováveis de causa

Antes de qualquer correção, o agente deve tentar classificar a divergência
numa dessas categorias — a ação certa depende de qual é:

- **Extrator de baixa qualidade**: o token foi resolvido, mas com o valor
  errado, porque o padrão do extrator (regex/JSONPath/CSS/etc.) era estreito
  demais para o caso atual (ex: funcionou na captura original, mas não numa
  variação de formato da resposta real).
- **Dependência não capturada**: o passo testado precisava de um token que
  vem de um passo anterior fora do conjunto executado (comum em `slice`/
  `list` mal montados, que não incluem toda a cadeia de dependência).
- **Efeito colateral já consumido**: um passo anterior não-idempotente já
  rodou antes (nesta ou numa execução passada) e alterou o estado do lado do
  portal (ex: recurso já existe, sessão já usada) — a resposta muda mesmo
  com tudo "correto" do lado do fluxo.
- **`success_criteria` mal definido**: o critério configurado não reflete de
  fato o que conta como sucesso para aquele passo/fluxo.
- **Mudança do lado do portal**: o comportamento real do servidor mudou
  desde a captura do HAR (não é algo o agente corrige — é um sinal de que o
  HAR está desatualizado).
- **Falha de conexão**: timeout/erro de rede, não uma divergência de
  conteúdo — não tentar de novo automaticamente (ver guardrails, seção 3).

## 4. Onde procurar evidência

Investigar uma divergência é exploratório, não um passo a passo fixo — o
agente decide a ordem conforme o caso, mas precisa saber onde a informação
está:

- **Saída do terminal (`stdout`) do `run`/`replay`**: reporta o resultado
  passo a passo e indica em qual passo e contra qual critério a divergência
  aconteceu — geralmente o primeiro lugar a olhar.
- **`original_responses/`**: a resposta que estava gravada no HAR original.
- **`real_responses/`** (quando existir, de um `run --mode main` anterior):
  a resposta real mais recente contra o servidor — comparar com
  `original_responses/` ajuda a ver se o portal mudou algo desde a captura.
- **A resposta do passo que divergiu no `replay`/`run` atual**: comparar
  contra as duas anteriores ajuda a isolar se o problema é o valor extraído
  (token errado sendo enviado) ou uma mudança de comportamento do portal.
- **`curls/*.curl.sh`** do passo em questão: mostra a requisição
  parametrizada, com o placeholder (`{{extractor:token_id}}`) no lugar de
  cada valor dinâmico — não o valor já resolvido, isso só acontece em tempo
  de execução. Útil para ver a estrutura da requisição e quais campos
  dependem de qual extrator; o valor de fato enviado fica na saída do
  terminal (primeiro item desta lista).
- **`extractors/`** do passo: mostra o padrão/lógica usada para resolver o
  token — é onde olhar se a causa provável for qualidade do extrator
  (seção 3).

## 5. O que o agente pode corrigir

- **`extractors/` de um workspace** (saída gerada, não código do projeto):
  o agente corrige um extrator existente **através do comando `extractor`**
  (`update`/`bind`/`unbind`/`delete`+`create`, conforme o padrão do
  problema — ver texto dedicado `extractor-crud-strategies.md` para os três
  padrões típicos e a sequência de ações de cada um), nunca editando
  `.py`/`.meta.json` diretamente à mão. O comando já impõe as mesmas
  garantias que valeriam numa edição manual — validar o `code` contra uma
  resposta real antes de persistir, recusar `delete` de um token ainda
  referenciado por algum curl a menos que `--force` — então usá-lo em vez de
  tocar os arquivos por fora é estritamente mais seguro, não só mais
  conveniente.
- **`config.json` do workspace**: o agente mantém um `config.json` dentro
  do próprio workspace (`<output>/config.json`), separado de qualquer
  config compartilhado do projeto — usado principalmente para afinar
  `success_criteria` com mais precisão conforme o diagnóstico avança.
  Passado via `--config` nas chamadas daquele workspace.

Ambos ficam livres para editar por causa do versionamento da seção 1: se a
mudança não resolver, o agente reverte.

## 6. O que o agente nunca deve fazer

- **Alterar o código-fonte do projeto** (`har_reproducer/`, o pacote em si).
  Isso vale mesmo que o agente tenha certeza da causa e da correção.
- **Editar `.py`/`.meta.json` de um extrator diretamente no sistema de
  arquivos.** O comando `extractor` existe justamente para isso (seção 5) —
  editar por fora abre mão da validação que o comando já faz antes de
  persistir, e é a única razão pela qual essa restrição existe (não é um
  limite de permissão, é evitar persistir uma correção não testada).

Se o agente identificar um bug real no código do projeto (não um extrator
de baixa qualidade, mas um problema na lógica do `har_reproducer/` em si),
ele **relata em texto** — não corrige. Convenção: um arquivo por bug em
`bugs-report/<AAAAMMDD>-<descrição-curta>.md`, com o que foi observado,
como reproduzir, e a hipótese de causa — para análise humana depois.

## 7. Registro de estratégias (documentação reativa)

Conforme o agente resolve problemas de diagnóstico, ele deve registrar a
estratégia usada num arquivo de conhecimento acumulado, para que agentes
futuros (ou o mesmo agente numa sessão diferente) não repitam a
investigação do zero. Cada entrada deve conter, de forma breve:

- Sintoma observado (ex: "passo 7 diverge com status 403 depois de rodar
  `all`, mas passa isolado em `smart`").
- Causa identificada (uma das categorias da seção 3).
- Ação tomada (ex: "ajustado extrator X, mesmo índice/tipo/placeholder").
- Resultado (resolveu / não resolveu / parcialmente).

Esse registro fica no próprio workspace, versionado como qualquer outro
arquivo ali (seção 1) — o que também deixa rastreável quando cada entrada
foi adicionada.
