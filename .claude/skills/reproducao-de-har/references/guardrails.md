# Guardrails — har-reproducer

Este texto define os limites de segurança que um agente operando o `har-reproducer`
via CLI deve respeitar. Objetivo: evitar que o agente cause dano fora do chat
(efeitos colaterais reais contra servidores de terceiros) por excesso de autonomia.

## 1. Comandos e o que eles tocam

| Comando | Toca rede real? | Risco |
|---|---|---|
| `parse` | Não | Nenhum — só decompõe o HAR em arquivos locais |
| `run --mode dry` | Não (portal) | Não toca a rede do portal alvo. Se houver LLM fallback configurado em `config.json`, ainda pode enviar dados para o provedor de LLM |
| `run --mode main` | **Sim** | Executa cada passo do fluxo de verdade, via curl real |
| `replay` (qualquer modo) | **Sim** | Reexecuta curls salvos contra o servidor real |
| `optimize` | **Sim, repetidamente** | Pode reexecutar o mesmo passo várias vezes durante a busca |
| `extractor list`/`get`/`test` | Não | Nenhum — só lê o workspace local (`test` roda o `code` contra amostras já em disco, sem rede) |
| `extractor create`/`update`/`delete`/`bind`/`unbind` | Não | Não fala com o portal, mas **edita artefatos persistidos** (`.py`/`.meta.json`/`.curl.sh`) que `replay`/`optimize` vão usar depois — um erro aqui não afeta o servidor real, mas pode fazer a próxima reprodução falhar ou (pior) "passar" com um valor errado. Mitigado pelo versionamento do workspace (ver diagnóstico) e pela validação que o próprio comando já faz antes de persistir — mas ainda é uma escrita, não uma leitura, e vale conferir o resultado (`extractor get` depois) antes de seguir |

Regra geral: **`parse`, e as ações de leitura/teste de `extractor`
(`list`/`get`/`test`), são sempre seguros de rodar sem pedir confirmação; as
ações de escrita de `extractor` (`create`/`update`/`delete`/`bind`/`unbind`)
não têm risco de rede mas merecem a mesma atenção de "confira o efeito"
que qualquer escrita merece; e `run --mode dry` é seguro em relação ao
portal alvo** (mas ver seção 5 sobre o fallback de LLM). Isso não significa
que `dry` seja necessariamente "melhor" ou preferível a `main` — são modos
com propósitos diferentes (análise offline vs. execução real); a escolha
entre eles depende do que o agente precisa validar, não de qual é "mais
seguro". Qualquer coisa que dispare `--mode main`, `replay` ou `optimize` é
uma ação com efeito no mundo real e deve ser tratada com cautela.

## 2. Efeitos colaterais não-idempotentes

Um fluxo capturado pode conter passos que não são seguros de repetir — criar um
recurso, disparar um pagamento, enviar um e-mail, etc. O `har-reproducer` **não
sabe distinguir isso sozinho**; ele só executa o que está no HAR.

- Antes de rodar `run --mode main`, `replay` ou `optimize` pela primeira vez
  num HAR novo, o agente deve avisar o usuário que passos serão executados de
  verdade contra o servidor de origem, e perguntar se algum passo do fluxo tem
  efeito colateral conhecido (criação de registro, cobrança, envio de
  notificação, etc.) — **a menos que o contexto já dado pelo usuário deixe
  claro que o fluxo é só de leitura/consulta** (ex: "consultar guia X"), caso
  em que o agente pode pular a pergunta.
- Se o usuário confirmar que existe efeito colateral não-idempotente, essa
  confirmação já cobre o `run --mode main` inicial e o `replay --mode all`
  obrigatório que vem logo depois dele (ver fluxo de decisão) — não é
  necessário parar de novo só para rodar o `all`. O agente decide, com
  julgamento, se vale perguntar de novo antes do `all` (ex: se algo
  inesperado apareceu no `run`) ou se pode seguir direto.
- Onde a cautela extra realmente se aplica é em `optimize`: nesse fluxo, o
  agente **não deve** rodar sem supervisão explícita a cada execução — o
  próprio README do projeto avisa que a busca é gulosa e pode reexecutar o
  mesmo passo várias vezes tentando remover candidatos do schedule, o que
  agrava o risco de repetir o efeito colateral.

## 3. Custo / limites de execução

- `optimize` tem `--max-requests` (padrão 500) como teto de segurança. O
  agente nunca deve aumentar esse teto sem o usuário pedir explicitamente —
  é o limite que existe justamente para conter o custo de uma busca gulosa
  contra um servidor real.
- Rodar contra o mesmo alvo repetidamente em pouco tempo pode disparar rate
  limiting ou bloqueio do lado do servidor. Se um `run`/`replay` começar a
  falhar de forma consistente (não só divergência de conteúdo, mas erro de
  conexão/timeout), o agente deve parar e reportar em vez de tentar de novo
  automaticamente.
- **Se o usuário der mais liberdade ao agente para disparar requisições reais
  em sequência sem confirmar cada uma** (ex: autorizar todo um `optimize` ou
  uma sequência de `replay` de uma vez, em vez de aprovar passo a passo), isso
  não elimina o cuidado com o ritmo — só desloca de "pedir confirmação a cada
  requisição" para "espaçar as requisições sozinho". Intervalo de referência:
  algo entre ~1 e ~10 minutos entre requisições reais, mais conservador (mais
  perto de 10 min ou mais) quanto maior o volume de requisições, quanto mais
  sensível o portal (produção real, sem indicação de ambiente de teste) e
  quanto menos o agente souber sobre o comportamento esperado do fluxo. Não é
  um número fixo — é uma calibração de risco, igual às outras desta seção.
- **Latência crescente entre requisições é o sinal mais direto de que o
  volume está afetando o portal** — se o tempo de resposta começar a aumentar
  de forma consistente ao longo de uma sequência (não uma variação pontual),
  tratar como sinal de estresse no servidor: espaçar ainda mais as próximas
  requisições, ou parar e avisar o usuário, em vez de simplesmente continuar
  no mesmo ritmo.

## 4. Escopo de exploração restrito ao HAR

Durante diagnóstico ou correção de um extrator, o agente pode precisar testar
uma requisição real contra o portal para validar uma hipótese (ex: confirmar
onde um token aparece na resposta). Isso é esperado, mas tem limite:

- O agente só pode montar/disparar requisições a partir dos curls **já
  gerados pelo `har-reproducer`** a partir do HAR (`curls/*.curl.sh`) ou de
  variações pontuais deles (ex: mudar um header pra testar uma hipótese). O
  agente **não deve explorar o portal livremente** — não inventar endpoints
  novos, não navegar rotas que não estavam no HAR original, mesmo que pareçam
  relacionadas. Se a hipótese exigir uma requisição fora do conjunto
  capturado no HAR, o agente para e pergunta ao usuário antes de disparar
  algo novo contra o servidor.
- Para testar uma correção, preferir reexecutar só o passo mínimo necessário
  (`replay --mode smart` ou `--mode list` com um único passo) em vez de rodar
  o fluxo inteiro de novo — reduz tanto o risco de repetir efeito colateral
  quanto o consumo de requisições reais.
- Se o passo sendo testado é conhecido como não-idempotente (seção 2), o
  agente deve avaliar quantas tentativas de correção/reexecução contra o
  servidor real fazem sentido **de acordo com o contexto**, não um número
  fixo — considerando o quão arriscado é o passo (ex: um portal médico tem
  risco maior que um endpoint de leitura pública) e qualquer orientação
  explícita já dada pelo usuário sobre aquele fluxo. Na dúvida ou na ausência
  de contexto suficiente para decidir, o agente deve preferir parar cedo e
  perguntar ao usuário em vez de arriscar repetir o efeito colateral. Este
  projeto será usado para automação de portais médicos — ver
  `navigation-on-medical-portals.md` para os padrões de fluxo (login, valores
  pagos, analítico) e os requisitos de cada um que mais frequentemente geram
  esse tipo de efeito colateral ou risco de sessão.

## 5. Dados sensíveis (tokens, cookies, sessões)

- O fluxo captura tokens, cookies e sessões reais de terceiros. O agente
  nunca deve expor esse conteúdo em texto solto na conversa (ex: colar o
  corpo de um `res_XXXX.json` inteiro) além do necessário para diagnosticar
  um problema pontual.
- O fallback de LLM (quando configurado em `config.json`) envia trechos de
  resposta capturada para um provedor externo para tentar resolver um token.
  O agente deve estar ciente de que isso significa dado real de terceiro
  saindo para fora do ambiente local — não deve habilitar/alterar essa
  configuração por conta própria sem o usuário saber que isso está ativo.

## 6. Quando parar e perguntar

O agente deve interromper e pedir confirmação do usuário, em vez de decidir
sozinho, quando:

- For a primeira execução de `--mode main` sobre um HAR novo.
- O comando a rodar for `optimize`.
- Uma divergência persistir após uma tentativa de correção (ver
  `diagnostics.md`) — não insistir indefinidamente sozinho.
- O alvo do fluxo parecer ser um ambiente de produção real (não um ambiente
  de teste/sandbox) e a ação puder ter efeito colateral.
