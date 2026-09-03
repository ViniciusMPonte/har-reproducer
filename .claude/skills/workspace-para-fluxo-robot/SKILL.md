---
name: workspace-para-fluxo-robot
description: Converte um workspace `har_reproducer` já finalizado (replay mínimo validado a frio — ver [[reproducao-de-har]], Passo 5) num fluxo Groovy do `http-robot-service` (DSL compilada — ver a skill `oficina-de-fluxos` daquele repositório) e no respectivo replay spec de teste. Usa o workspace como fonte única de verdade — sequência mínima de requisições, tokens dinâmicos já resolvidos por extrator tipado (`agent_type`), `success_criteria` já validado contra o portal real — em vez de sessão ao vivo ou HAR bruto (os dois mecanismos de `captura-navegacao.md`, que este fluxo substitui quando já existe um workspace pronto). Use SEMPRE que o usuário pedir para "levar esse HAR/workspace pro robot", "gerar o fluxo do robot a partir dessa reprodução", "criar o fluxo Groovy com base no que o har_reproducer já validou", "provar que o robot reproduz esse fluxo com teste", ou terminar uma sessão de `reproducao-de-har` perguntando "e agora, como isso vira um fluxo do robô?".
---

# Workspace `har_reproducer` → Fluxo `http-robot-service`

Esta skill é uma **ponte**, não um manual completo de nenhum dos dois lados. Ela
depende de duas skills de origem, e **é responsabilidade desta skill garantir
que as duas estejam carregadas antes do Processo (seção abaixo) começar** —
não presuma que já estão só porque a sessão já mexeu em HAR ou no robô antes:

- [[reproducao-de-har]] — carregue via `Skill` normalmente (vive neste mesmo
  projeto). Dá o significado de cada pasta/arquivo do workspace e o critério
  objetivo de "finalizado" (Passo 5 daquela skill).
- `oficina-de-fluxos` — vive no repositório `http-robot-service`, **fora
  deste projeto**, então não pode ser invocada via `Skill`. Assim que o
  caminho do checkout for conhecido (ver "Pré-condição" abaixo), **leia o
  arquivo `{checkout}/.claude/skills/oficina-de-fluxos/SKILL.md` com a
  ferramenta de leitura de arquivo antes de continuar** — é de lá que vêm a
  sintaxe da DSL, o padrão de Helper, o processo de triagem de ticket e o
  checklist de entrega que os passos 2, 4 e 6 do Processo pressupõem. Trate
  essa leitura como parte obrigatória do início da tarefa, não como um
  "carregar se for preciso depois".

Tudo que já está resolvido nessas duas skills **não é repetido aqui**. Esta
skill cobre só a tradução entre os dois modelos e o que isso implica de
diferente em relação ao processo normal de cada uma.

## Por que o workspace substitui sessão ao vivo/HAR bruto

`oficina-de-fluxos` tem dois mecanismos de captura
(`references/captura-navegacao.md`): sessão ao vivo e fallback HAR com
`har_dump.py`. Um workspace `har_reproducer` finalizado é um **terceiro
mecanismo, estritamente mais forte** que os dois quando já existe:

| | Sessão ao vivo / HAR bruto | Workspace `har_reproducer` finalizado |
|---|---|---|
| Tokens dinâmicos | Inferidos na hora, por leitura humana do JS/HTML | Já resolvidos por extrator tipado (`agent_type`), com `captured_value` conferido |
| Sequência de passos | O que o usuário navegou (pode ter ruído: estáticos, analytics) | Já minimizada por `optimize` — só passos que o `replay` prova serem necessários |
| Validação de sucesso | Nenhuma, ou "pareceu certo" | `success_criteria` testado a frio (Passo 5 de `reproducao-de-har`) |
| Resposta real por passo | Só a request atual (o resto se perde ao navegar) | `real_responses/res_NNNN.json` de todos os passos, permanente |

Isso não elimina a Fase 0/triagem de `oficina-de-fluxos` (ver Passo 2 abaixo)
— só substitui a **Fase 1** (a captura em si) de `captura-navegacao.md` por
leitura de arquivo em vez de navegador.

## Pré-condição: o workspace precisa estar finalizado

Antes de continuar, confirme (ou faça o usuário confirmar) que o workspace já
passou pelo Passo 5 de `reproducao-de-har`: existe um
`replays/optimized_<run_id>.txt` e ele já foi validado com `replay --mode list
--steps-file` **num contexto frio** (sem cache/jar reaproveitado do
`optimize`). Se isso não aconteceu, **pare e volte para `reproducao-de-har`**
— gerar fluxo a partir de um workspace ainda quente/não validado propaga pro
robô os mesmos passos supérfluos ou extratores não confirmados que o Passo 5
existe pra pegar.

Se o caminho do checkout de `http-robot-service` ainda não foi informado
nesta sessão, pergunte (é um repositório separado, fora deste projeto) e
reaproveite depois. **Assim que tiver o caminho, leia
`{checkout}/.claude/skills/oficina-de-fluxos/SKILL.md`** (ver seção acima) —
só depois disso o Processo abaixo deve começar.

## Processo

1. **Montar o mapa de captura a partir do workspace** (não do navegador) —
   ver [references/processo.md](references/processo.md) seção 1. O
   resultado é o mesmo artefato "mapa de captura" que `captura-navegacao.md`
   já define — só a origem dos dados muda.
2. **Rodar a triagem normal de `oficina-de-fluxos`** sobre o convênio/portal
   alvo (fluxo novo vs. adaptativa, plataforma genérica, fluxo de pagamento)
   — seção da skill "Triagem: identifique o tipo de ticket". Esta skill não
   substitui essa decisão, só entrega o insumo pronto pra ela.
3. **Traduzir cada elemento do workspace para a sintaxe da DSL** — tarefas,
   extratores, validadores — usando a tabela de
   [references/mapa-de-traducao.md](references/mapa-de-traducao.md) como
   referência campo a campo. É aqui que aparecem as **lacunas** (extrator sem
   correspondência determinística, critério de sucesso sem validador
   dedicado) — sinalize cada uma explicitamente, não resolva por adivinhação.
4. **Escrever a DSL compilada + Helper**, seguindo `references/dsl.md` +
   `references/dsl-compilada-sintaxe.md` + `references/padroes-e-boas-praticas.md`
   de `oficina-de-fluxos` normalmente (regra de ouro dos hooks, Helper por
   convênio, etc. — nada disso muda por a origem ser um workspace).
5. **Gerar o replay spec e provar eficácia** — ver
   [references/testes-de-eficacia.md](references/testes-de-eficacia.md). É
   aqui que mora o "teste comprovando eficácia do robô": os cenários nascem
   diretamente das respostas reais gravadas no workspace, e a gravação do
   cache do robô contra o portal real pode ser feita nesta própria sessão
   quando (e só quando) as duas condições do guardrail abaixo valem.
6. **Checklist final** — o checklist canônico continua sendo o de
   `padroes-e-boas-praticas.md`; some a ele os itens específicos de origem
   listados no fim de `references/processo.md` (cada passo sobrevivente do
   `optimize` virou exatamente uma Tarefa, cada token virou exatamente um
   extrator ou uma lacuna documentada).

## Guardrail específico desta ponte

Gravar cache de replay spec contra o portal real (`FixtureMode.RECORD`) é uma
ação de rede não-idempotente com efeito num sistema de terceiro. Esta skill
pode fazer isso **sem perguntar a cada vez** somente quando as duas condições
valem ao mesmo tempo:

1. **O fluxo é de leitura/consulta** (login, extração, download) — nunca
   transmissão/recurso/qualquer POST que produza efeito no portal. Para
   fluxo de escrita, `oficina-de-fluxos` já é taxativo: a homologação é
   decisão do usuário/time, nunca decisão automática do agente. Essa regra
   não muda aqui.
2. **As credenciais usadas para gerar o workspace original** (as mesmas que
   autenticaram a sessão capturada no `.har`) **estão disponíveis nesta
   sessão**, fornecidas explicitamente pelo usuário para esse fim.

Fora dessas duas condições — fluxo de escrita, ou credencial ausente/expirada
— pare e pergunte, exatamente como o runbook de `oficina-de-fluxos` já faz
para qualquer fluxo novo.

## Referências

| Arquivo | Cobre |
|---|---|
| [references/mapa-de-traducao.md](references/mapa-de-traducao.md) | Tabela campo a campo: pasta do workspace → insumo da DSL; `agent_type` → extrator; `success_criteria` → validador. O núcleo novo desta skill. |
| [references/processo.md](references/processo.md) | Como montar o mapa de captura a partir do workspace, e o checklist de correspondência 1:1 (passo → Tarefa, token → extrator) específico desta origem. |
| [references/testes-de-eficacia.md](references/testes-de-eficacia.md) | Como o replay spec nasce das respostas reais do workspace, protocolo de gravação de cache nesta sessão, e como transformar cada lacuna da tradução num teste que a expõe em vez de escondê-la. |

## Checkpoint — aprendizado generalizável

Mesmo critério de `reproducao-de-har`: ao fim de uma exportação, pare e
pergunte se a sessão revelou um padrão de tradução que valeria para qualquer
workspace futuro (não só para este convênio) — um `agent_type` sem entrada na
tabela, um tipo de `success_criteria` novo, uma armadilha na correspondência
passo↔Tarefa. Se sim, proponha o diff para `references/mapa-de-traducao.md`
ou `references/processo.md` e espere aprovação antes de aplicar. Um detalhe
específico do convênio (nome de campo, URL) não entra aqui — isso é registro
do PR/ticket do robô, não desta skill.
