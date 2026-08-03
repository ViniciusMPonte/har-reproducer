---
name: spec-e-plano
description: Fluxo de planejamento deste projeto — spec.md seguido de implementation_plan.md com tasks no formato padrão. Use SEMPRE que o usuário pedir para planejar uma feature/mudança nova, escrever uma spec, ou quebrar um plano em tasks de implementação.
---

# Spec + Plano de Implementação — fluxo de planejamento do projeto

Este projeto planeja toda feature ou mudança não trivial em duas etapas sequenciais,
sempre dentro de uma pasta nova em `docs/`: primeiro uma **spec** (o "o quê" e o
"porquê", ancorada no código real), depois um **plano de implementação** (o "como",
quebrado em tasks autocontidas). Ninguém implementa nada antes de ambos os documentos
existirem e a spec estar aprovada.

Todo código citado em qualquer um dos dois documentos segue [[guia-de-estilo]].

## Passo 0 — pasta da etapa

Criar `docs/AAAAMMDD Nome da Feature/` (data de hoje + nome curto em title case,
mesmo padrão de `docs/20260803 Reaproveitamento de Extractores/`). Os dois arquivos
(`spec.md` e `implementation_plan.md`) vivem lá dentro.

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
