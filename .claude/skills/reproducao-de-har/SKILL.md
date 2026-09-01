---
name: reproducao-de-har
description: Manual operacional para pilotar `run`/`replay`/`optimize`/`extractor` deste projeto (`har_reproducer`) a partir de um arquivo `.har` cru até a menor sequência de passos, com extratores corretos, que reproduz com sucesso a requisição alvo (geralmente a última do fluxo capturado). Cobre organização do workspace por HAR, guardrails contra efeito colateral real, o fluxo de decisão entre comandos, diagnóstico de divergência e correção de extratores via o comando `extractor`. Use SEMPRE que o usuário pedir para reproduzir, automatizar, minimizar ou "encontrar os passos mínimos" de um fluxo HTTP a partir de um `.har` — inclusive fluxos de portais médicos (login, consulta de valores pagos, extração analítica de guias/protocolos) — ou pedir ajuda operando este projeto contra um HAR específico.
---

# Reprodução mínima de HAR — manual operacional para agentes

Esta skill governa **como usar** o `har_reproducer` (não como ele é construído —
para isso, ver [[arquitetura-e-fundamentos]]). O objetivo de qualquer sessão que
usa esta skill é sempre o mesmo: partir de um `.har` cru e chegar a um `.txt` de
passos (via `optimize`, consumível por `replay --mode list --steps-file`) que
reproduz a requisição alvo de forma confiável, com o menor número de passos e
extratores que resolvem os tokens dinâmicos corretamente — não só "roda sem
erro", mas "roda com o conteúdo certo, de forma repetível, num processo novo".

Cada seção abaixo é a síntese operacional de um texto de referência em
`references/`; leia o texto completo antes de agir na etapa correspondente, não
só o resumo aqui.

## Antes de tudo: guardrails

Todo comando além de `parse` e das ações de leitura do `extractor`
(`list`/`get`/`test`) tem risco real — de rede (`run --mode main`, `replay`,
`optimize` executam contra o servidor de terceiro) ou de corromper artefatos
persistidos que a próxima etapa vai confiar (`extractor create`/`update`/
`delete`/`bind`/`unbind`). Ler **[references/guardrails.md](references/guardrails.md)**
por completo antes da primeira execução real num HAR novo — em especial:

- Perguntar ao usuário sobre efeito colateral não-idempotente antes do primeiro
  `run --mode main`/`replay --mode all`, a menos que o contexto já deixe claro
  que o fluxo é só leitura/consulta.
- `optimize` nunca roda sem supervisão explícita a cada execução — é busca
  gulosa, pode repetir o mesmo passo várias vezes.
- Nunca aumentar `--max-requests` sem pedido explícito do usuário.
- Nunca explorar o portal fora do que o HAR já capturou (nada de endpoint novo
  "só pra confirmar uma hipótese" sem perguntar antes).
- Este projeto automatiza **portais médicos** — ver
  **[references/navigation-on-medical-portals.md](references/navigation-on-medical-portals.md)**
  para os três padrões de fluxo mais comuns (login, valores pagos, analítico) e
  os riscos de sessão/efeito colateral que cada um carrega. Um fluxo analítico
  (centenas de downloads, sessão de vida longa) pede calibração de risco
  diferente de uma consulta única — entrar já sabendo qual dos três padrões o
  HAR representa evita subestimar o risco de um fluxo que parece simples.

## Passo 0 — organizar o workspace

Antes de rodar qualquer comando: seguir
**[references/workspace-setup.md](references/workspace-setup.md)**.

1. Perguntar ao usuário a raiz onde os workspaces vivem (só na primeira vez;
   reaproveitar depois).
2. Criar `<raiz>/<domínio>__<AAAAMMDD>/` (data da **captura** do HAR, não de
   hoje) com uma cópia do `.har` original + `output/`.
3. Inicializar git dentro de `output/` (só `output/`, não a pasta inteira) e
   commitar a cada alteração feita ali — é esse histórico que sustenta poder
   editar `extractors/`/`config.json` livremente durante diagnóstico (ver
   Passo 3), com rollback e branches por hipótese disponíveis.

Antes do primeiro `run`, vale ler
**[references/workspace-structure.md](references/workspace-structure.md)** —
o mapa do que cada pasta de `output/` (`curls/`, `extractors/`,
`real_responses/`, `original_responses/`, `replays/`, etc.) vai conter depois
que os comandos rodarem. Os textos dos passos seguintes citam essas pastas
assumindo que esse mapa já é conhecido.

## Passo 1 — descoberta inicial (`run`)

Seguir **[references/decision-flow.md](references/decision-flow.md)** seção 1–2
para decidir o modo:

- Padrão: `run --mode main`. Já gera `real_responses/`, a referência preferida
  de `replay`/`optimize`.
- `run --mode dry` só como preparação (não como destino) quando o fluxo parecer
  depender bastante do LLM fallback (muitos tokens sem padrão óbvio de
  regex/JSONPath/CSS, ou sinal de sensibilidade a tempo entre passos) — resolve
  os tokens offline primeiro, depois roda `main` sem a latência do LLM no meio
  do fluxo real.
- `parse` sozinho raramente é o primeiro comando — só quando o objetivo é só
  inspecionar a estrutura bruta do HAR antes de decidir mais nada.

## Passo 2 — validar (`replay --mode all`)

**Sempre o primeiro comando depois de qualquer `run`**, antes de qualquer
análise fina ou de partir para `optimize` — reexecutar tudo pode revelar falso
positivo do `run` (deu certo na hora, mas não reexecuta) e problemas de tempo de
resposta do portal. Ver [references/decision-flow.md](references/decision-flow.md)
seção 3.

Se `all` já confirma o fluxo de ponta a ponta sem divergência: seguir para o
Passo 4 (`optimize`). Se divergir: Passo 3.

Os outros três modos de `replay` (`smart`/`slice`/`list`) não são etapas
sequenciais — são ferramentas de análise de trecho, usadas conforme a pergunta
do momento (ver tabela na seção 3 da referência), tanto antes quanto depois do
`optimize`.

## Passo 3 — diagnosticar e corrigir divergência

1. **Classificar a causa** antes de agir — ver
   **[references/diagnostics.md](references/diagnostics.md)** seção 3: extrator
   de baixa qualidade, dependência não capturada, efeito colateral já
   consumido, `success_criteria` mal definido, mudança do lado do portal, ou
   falha de conexão (essa última: parar e reportar, não repetir sozinho).
2. **Nunca aceitar sucesso só pelo `status_code`** — muitos portais respondem
   200 tanto pro conteúdo certo quanto pra uma página de erro/sessão expirada.
   Reforçar `success_criteria` com `body_contains` assim que um trecho
   distintivo do estado certo for identificado. Ver
   **[references/analysis-strategies.md](references/analysis-strategies.md)**
   para as técnicas de investigação (diff byte a byte entre esperado/obtido,
   rastrear um valor ao longo do fluxo, checagem estatística sobre o conjunto
   inteiro de curls/respostas antes de confiar numa hipótese isolada).
3. **Corrigir extrator via o comando `extractor`** — nunca editando
   `.py`/`.meta.json` à mão. Ver
   **[references/extractor-crud-strategies.md](references/extractor-crud-strategies.md)**
   para os três padrões (extrator incorreto → `update`; extrator inútil →
   `unbind` + `delete`; extrator ausente → `create` só depois de confirmar a
   origem contra pelo menos duas amostras) e o uso de `get`/`test` como
   instrumento de diagnóstico antes de qualquer escrita.
4. Depois de corrigir, reexecutar só o mínimo necessário para confirmar
   (`replay --mode smart` ou `--mode list` com o passo único) — não o fluxo
   inteiro de novo.
5. **Registrar a estratégia usada** (sintoma, causa, ação, resultado) num
   arquivo de conhecimento acumulado dentro do próprio workspace, versionado
   como qualquer outro arquivo ali — para não repetir a investigação do zero
   numa sessão futura. Ver [references/diagnostics.md](references/diagnostics.md)
   seção 7.

Se a divergência persistir depois de uma tentativa de correção, ou o agente
identificar um bug real no código do projeto (não um extrator de baixa
qualidade): parar e reportar ao usuário — nunca alterar `har_reproducer/`
diretamente, nem insistir indefinidamente sozinho.

## Passo 4 — minimizar (`optimize`)

Só depois que `replay --mode all` confirmou o fluxo de ponta a ponta. Ver
[references/decision-flow.md](references/decision-flow.md) seção 4 e
[references/guardrails.md](references/guardrails.md) seção 2–3 para os riscos
(efeito colateral repetido, teto de `--max-requests`) — **rodar com supervisão
explícita a cada execução**, nunca em loop autônomo sem o usuário sabendo.

⚠️ Em fluxos de login, `optimize` pode remover o próprio passo de login (e o
step 0) sem perceber, se o token de acesso parecer estático na amostra
capturada — ver [references/navigation-on-medical-portals.md](references/navigation-on-medical-portals.md),
seção "Fluxo de login", pra como detectar e evitar esse falso positivo
específico.

## Passo 5 — validar que o schedule mínimo se sustenta sozinho

Antes de considerar o `.txt` do `optimize` como entregável final: testá-lo
isolado via `replay --mode list --steps-file`, **num contexto que não reaproveite
nenhum estado (cache/jar) da execução do `optimize` que o gerou** — um schedule
pode passar "quente" durante a busca e falhar num processo novo. Ver
[references/analysis-strategies.md](references/analysis-strategies.md), primeira
seção.

## Referências

| Arquivo | Cobre |
|---|---|
| [workspace-setup.md](references/workspace-setup.md) | Organização de pastas por HAR, convenção de nome, workspace como repo git |
| [workspace-structure.md](references/workspace-structure.md) | O que tem dentro de `output/` — cada subpasta gerada por `run`/`replay`/`optimize`/`extractor` e para que serve |
| [decision-flow.md](references/decision-flow.md) | Qual comando/modo escolher em cada etapa (`parse`/`run`/`replay`/`optimize`) |
| [guardrails.md](references/guardrails.md) | Limites de segurança, quando parar e perguntar, risco por comando |
| [diagnostics.md](references/diagnostics.md) | Categorias de causa de divergência, onde procurar evidência, o que pode/não pode corrigir |
| [analysis-strategies.md](references/analysis-strategies.md) | Técnicas forenses de investigação (diff, rastreamento no tempo, checagem estatística) |
| [extractor-crud-strategies.md](references/extractor-crud-strategies.md) | Uso do comando `extractor` para diagnosticar e corrigir extratores |
| [navigation-on-medical-portals.md](references/navigation-on-medical-portals.md) | Padrões de fluxo de portais médicos (login, valores pagos, analítico) e seus requisitos |

## Checkpoint — aprendizado generalizável (fim do diagnóstico ou do optimize)

Depois de resolver uma divergência (Passo 3) ou fechar uma minimização (Passo 5),
parar e perguntar: **essa investigação revelou uma estratégia — de análise ou de
uso das ferramentas do projeto — que valeria pra qualquer HAR futuro, não só pra
este?** Não é obrigatório que a resposta seja sim; a maioria dos diagnósticos não
gera atualização nenhuma aqui, e isso é esperado. É esse checkpoint que faz a
skill ficar mais esperta com o tempo em vez de reaprender a mesma coisa em toda
sessão nova — sem ele, é fácil o agente nunca parar pra registrar o que
descobriu no meio de um diagnóstico.

- **Vale** propor diff para a referência correspondente: um padrão de
  investigação que funcionou (→ `analysis-strategies.md`), um uso não óbvio do
  comando `extractor` que resolveu uma classe de problema (→
  `extractor-crud-strategies.md`), um critério novo pra escolher entre
  comandos/modos (→ `decision-flow.md`), um risco de guardrail não coberto (→
  `guardrails.md`), um padrão de portal não descrito (→
  `navigation-on-medical-portals.md`), ou uma etapa deste manual que não bateu
  com o comportamento real do `har_reproducer` (→ este arquivo).
- **Não vale**: um detalhe específico deste HAR/portal (nome de campo, formato
  de token daquele site específico) — isso já tem lugar: o registro de
  estratégias do próprio workspace ([references/diagnostics.md](references/diagnostics.md)
  seção 7), não a skill.

Nunca editar os textos de referência ou este arquivo sem mostrar o diff
proposto e esperar aprovação explícita do usuário antes de aplicar.
