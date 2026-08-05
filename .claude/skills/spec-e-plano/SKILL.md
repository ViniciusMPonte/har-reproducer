---
name: spec-e-plano
description: Fluxo de planejamento e implementação deste projeto — spec.md, depois implementation_plan.md com tasks no formato padrão, depois implementação task a task com um commit padronizado por task. Use SEMPRE que o usuário pedir para planejar uma feature/mudança nova, escrever uma spec, quebrar um plano em tasks, implementar tasks de um plano já aprovado, ou fazer commit de progresso de uma feature.
---

# Spec + Plano de Implementação — fluxo de planejamento e execução do projeto

Este projeto planeja e executa toda feature ou mudança não trivial em etapas
sequenciais, sempre dentro de uma pasta nova em `docs/`: primeiro uma **spec** (o "o
quê" e o "porquê", ancorada no código real), depois um **plano de implementação** (o
"como", quebrado em tasks autocontidas), depois a **implementação task a task**, cada
uma virando um commit padronizado. Ninguém implementa nada antes de ambos os
documentos existirem e a spec estar aprovada.

Todo código citado em qualquer um dos dois documentos segue [[guia-de-estilo]].

## Passo 0 — pasta da etapa e branch

Criar `docs/AAAAMMDD Nome da Feature/` (data de hoje + nome curto em title case,
mesmo padrão de `docs/20260803 Reaproveitamento de Extractores/`). Os dois arquivos
(`spec.md` e `implementation_plan.md`) vivem lá dentro.

Na sequência, criar o branch de trabalho a partir da `master`, **sempre**, nunca
implementar direto na `master` nem usar prefixos como `fix/`, `feature/` etc. O nome
do branch é derivado 1:1 do nome da pasta que acabou de ser criada:

```
AAAAMMDD-slug-do-nome-da-feature
```

Onde `slug-do-nome-da-feature` é o "Nome da Feature" da pasta: minúsculo, sem
acentos/cedilha (á→a, ã→a, ç→c, ...), espaços e demais separadores trocados por
hífen. Exemplos reais já usados no repo:

| Pasta em `docs/`                                                  | Branch                                                        |
|---------------------------------------------------------------------|----------------------------------------------------------------|
| `20260803 Reaproveitamento de Extractores`                          | `20260803-reaproveitamento-de-extractores`                      |
| `20260804 Desambiguação de Identidade de Token Dinâmico`             | `20260804-desambiguacao-de-identidade-de-token-dinamico`        |
| `20260804 Extração por Substring e Fallback de Exaustão`            | `20260804-extracao-por-substring-e-fallback-de-exaustao`        |

Se já existir branch com a mesma data para outra feature (duas etapas no mesmo dia),
inserir um número sequencial entre a data e o slug: `AAAAMMDD-2-slug-...` (ver
`20260623-2-Atualização-do-readme`).

Comando (a partir da `master` atualizada):

```bash
git checkout master
git checkout -b AAAAMMDD-slug-do-nome-da-feature
```

⚠️ Não inventar um nome "descritivo" alternativo (ex.: `fix/colisao-...`) — o slug
tem que casar com o nome da pasta, mesmo que outro nome pareça mais claro. É isso que
permite achar o branch de uma feature só olhando `docs/`.

## Passo 1 — `spec.md`

Fonte única de verdade para gerar o plano depois — escreva como se quem for ler
não tivesse participado desta conversa. Tudo que for necessário para entender o
"porquê" e o "o quê" tem que estar no documento, sem depender de mais nada além do
código-fonte atual do projeto e do guia de estilo.

Estrutura (adaptar seções conforme a feature, mas manter esta espinha dorsal):

1. **Objetivo** — o problema atual, o custo de não resolvê-lo, o que a mudança cobre.
   Deixar explícito o que fica **fora de escopo** (inclusive "feature futura, não
   implementar agora" quando aplicável).
2. **Componentes existentes reaproveitados (estado atual, não redesenhar)** — para
   cada classe/função relevante que já existe, citar `arquivo.py:linha`, o
   comportamento atual (com trecho de código quando ajuda) e por que ele importa para
   a mudança. Esta seção é o que ancora a spec no código real em vez de em suposições —
   leia os arquivos antes de escrever aqui, nunca invente assinatura ou comportamento.
3. **Decisões de arquitetura** — numeradas (`3.1`, `3.2`, ...), uma decisão por
   subseção. Cada uma mostra estado atual → estado esperado (trecho de código quando
   fizer sentido) e a razão da escolha, incluindo alternativas descartadas quando
   relevante. É aqui que mudanças de model, novos componentes, e alterações de
   assinatura são especificados em detalhe suficiente para virarem tasks depois.
4. **Novos componentes e alterações — resumo** — tabela `Componente | Mudança`
   consolidando a seção 3, para referência rápida.
5. **Casos de borda e comportamento de erro** — cada caso de borda identificado, o
   comportamento esperado, e se é uma limitação aceita ou algo que a implementação
   precisa tratar.
6. **Suposições e pontos a confirmar** (quando houver) — decisões que dependem de
   confirmação do usuário antes do plano ser escrito.
7. **Referência** — linha final apontando para `guia_de_estilo.md`/[[guia-de-estilo]]
   como padrão de implementação obrigatório.

Regra de processo: **apresentar a spec e esperar aprovação do usuário antes de
escrever o `implementation_plan.md`.** Perguntas de esclarecimento (equivalente ao
`/speckit.clarify`) acontecem antes da aprovação, não depois.

## Passo 2 — `implementation_plan.md`

Só depois da spec aprovada. Cabeçalho padrão:

```
# Plano de Implementação — <Nome da Feature>

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.
```

Cada task usa exatamente este template (ver `docs/20260724 Requisições via
curl/task template.md`):

```markdown
## [ID_DA_TASK] — `NomeDaClasseOuComponente`: Resumo da Ação em Uma Linha

**Depende de:** [ID_DE_OUTRA_TASK ou "Nenhuma"] (Contexto de pré-requisito).
**Arquivos envolvidos:** `caminho/do/arquivo/nome_do_arquivo.py` (Classes ou funções impactadas)

**Contexto:**
[Explicar brevemente o panorama geral: o que o componente faz hoje de forma macro e qual é o problema ou a nova necessidade que motivou essa alteração].

**Estado atual:**
- [Comportamento ou retorno do Método A hoje]
- [Comportamento ou retorno do Método B hoje]
- [O que está faltando ou não é tocado atualmente]

**Estado esperado depois:**
- [Como o Método A deve se comportar/retornar]
- [Regras de negócio novas: ordenações, filtros, loops, algoritmos]
- [Novos métodos ou funções que precisam ser criados]
- [⚠️ Alertas, validações de arquitetura ou pontos de atenção/checagem no modelo atual]

**Critérios de aceite:**
- [ ] `metodo_exemplo("input")` retorna `"output_esperado"`.
- [ ] [Cenário de Teste 1: Validação de comportamento isolado].
- [ ] [Cenário de Teste 2: Validação de caso de borda ou pegadinha (ex: substrings, nulos)].
- [ ] [Cenário de Teste 3: Integração ou efeito colateral esperado].
- [ ] [Garantia de não-regressão: o que já funcionava e DEVE continuar funcionando].
```

Regras ao preencher:
- IDs sequenciais `T01`, `T02`, ... — ordem topológica real (uma task nunca depende de
  uma task de número maior).
- "Estado atual"/"Estado esperado depois" citam código real (trecho atual do arquivo,
  não paráfrase) sempre que a task altera uma classe/método existente.
- `⚠️` marca decisões não óbvias que alguém implementando a task isoladamente,
  sem ter lido a spec inteira, poderia errar (ex.: "não reordenar campos existentes",
  "usar o mesmo fallback fixo que X já usa hoje").
- Critérios de aceite são verificáveis (comportamento de função com input/output
  concreto, não "deve funcionar corretamente"), e sempre incluem pelo menos uma
  garantia explícita de não-regressão quando a task toca código existente.
- Cada task referencia a seção da spec que a originou quando ajuda a rastrear o
  "porquê" (ex.: "spec seção 3.3").

## Passo 3 — Implementação: uma task, um commit

Depois do plano aprovado, a implementação segue a ordem das tasks (`T01`, `T02`, ...)
do `implementation_plan.md`. Cada task vira **exatamente um commit** — não acumular
várias tasks num commit só, mesmo que pareçam pequenas ou relacionadas (excessão: duas
tasks triviais, sequenciais e do mesmo componente podem ir juntas — usar com
moderação, não como padrão).

Ao terminar uma task (código + validação dos critérios de aceite), commitar
imediatamente e seguir para a próxima. Não empilhar tasks sem commitar entre elas, e
não pedir confirmação a cada commit — a aprovação já foi dada na spec/plano; commitar
faz parte de implementar a task. Só parar para perguntar se um critério de aceite não
passar ou exigir uma decisão fora do que o plano previu.

### Mensagem de commit

```
<tipo>: T0N — Componente/Método: resumo objetivo da mudança em uma linha

[Corpo opcional — 1 a 3 linhas, só quando o assunto não é suficiente para entender
o "porquê". Reaproveitar a explicação do "Contexto"/"Estado esperado depois" da
task, nunca reescrever do zero.]
```

- `<tipo>` segue Conventional Commits e **nunca é omitido**:
  - `feat:` — a task adiciona/altera comportamento observável.
  - `fix:` — corrige um bug descoberto durante a implementação, fora do escopo das
    tasks do plano (não leva `T0N`, é um commit à parte).
  - `refactor:` — task é puramente estrutural, sem mudança de comportamento
    observável.
- `T0N` é o ID exato da task no plano — permite achar a task original só lendo
  `git log --oneline`.
- `Componente/Método` repete o nome do cabeçalho da task
  (`## [T0N] — \`Componente\`: ...`) — não abreviar nem trocar por sinônimo.
- O resumo do assunto descreve **o que muda**, nunca "implementa T0N" — quem lê o
  log sem abrir o plano precisa entender a mudança sem contexto adicional.
- Corpo é opcional, mas preferível a inflar o assunto quando a task tem um "porquê"
  não óbvio (motivo de uma decisão de arquitetura, efeito colateral em outro
  componente, trade-off descartado).

Exemplo sem corpo (assunto já basta):
```
feat: T05 — CookieAgent: estratégia determinística de substring na própria chave
```

Exemplo com corpo (o "porquê" ajuda quem lê depois):
```
feat: T06 — CandidateResolver: fallback para extrator literal quando o Agent esgota tentativas

Evita reprocessar a mesma extração indefinidamente quando o Agent já esgotou as
tentativas configuradas — cai para o extrator literal em vez de repetir a chamada
ao LLM a cada resolução (spec seção 3.2).
```

⚠️ Nunca commitar uma task sem o prefixo de tipo (ex. `T08 — Componente: ...` sem
`feat:`) — já aconteceu no histórico e quebra o hábito de filtrar o log por tipo.

## Passo 4 — Fechamento do plano

Depois que a última task foi commitada e todos os critérios de aceite do plano foram
verificados, marcar todos os checkboxes de "Critérios de aceite" do
`implementation_plan.md` como `[x]` e commitar essa atualização separada, como `doc:`:

```
doc: marcando tasks concluídas
```

Esse commit sinaliza "plano encerrado". Se alguma task ficou com critério de aceite
não verificado, não marcar — avisar o usuário antes de considerar o plano fechado.

## Passo 5 — Retro de convenção e arquitetura

Depois do commit de fechamento (Passo 4), antes de considerar a etapa encerrada,
parar um momento e perguntar duas coisas. Não é obrigatório que a resposta seja
"sim" — a maioria das specs não gera nenhuma atualização aqui, e isso é o esperado,
não uma falha do processo.

1. **Surgiu uma convenção de processo nova, ou uma correção a algo já escrito
   nesta skill?** (ex.: um formato de nome, uma regra de quando dividir uma task em
   duas, um caso de commit que a seção de mensagens não cobria). Se sim, e se for
   algo que se repetiria em qualquer feature futura — não específico do domínio
   desta spec — propor um diff para este arquivo (`spec-e-plano/SKILL.md`).
2. **Surgiu uma decisão de arquitetura/domínio que reflete (ou viola) o princípio
   de genericidade do projeto, ou documenta um ponto de dívida técnica novo ou já
   conhecido?** Se sim, propor um diff para [[arquitetura-e-fundamentos]].

Critério para decidir se algo "vale" propor (evita inflar as skills com a decisão
de um caso só):
- **Vale**: algo que um novo colaborador — ou uma nova sessão do Claude, sem ter
  visto esta conversa — precisaria saber para não repetir o mesmo erro ou
  redescobrir a mesma decisão do zero.
- **Não vale**: detalhe específico de uma classe/feature isolada que já está
  documentado na própria spec/plano da etapa (`docs/AAAAMMDD .../spec.md`) — isso já
  tem um lugar, não precisa duplicar na skill.

⚠️ Nunca editar `spec-e-plano/SKILL.md` nem `arquitetura-e-fundamentos/SKILL.md`
sem antes mostrar o diff proposto e esperar aprovação explícita do usuário — mesmo
já tendo aprovação da spec/plano da etapa, ela não se estende a mudanças nas skills
que governam o processo. Se o usuário não responder ou recusar, a etapa fecha
normalmente, sem a atualização.
