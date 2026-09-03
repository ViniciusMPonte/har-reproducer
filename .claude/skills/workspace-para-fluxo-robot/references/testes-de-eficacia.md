# Testes de eficácia — provar que o fluxo do robô reproduz o workspace

O padrão de teste (`ExecucaoScripts{Convenio}Spec`, `FixtureMode`,
`getCachePath`, ciclo RECORD→PLAY) já está inteiramente descrito em
`oficina-de-fluxos` — seção "Fluxo novo → spec de replay no mesmo ticket" e
o runbook completo dentro do passo 10 do `SKILL.md` ("Como gravar o cache").
Nada disso é repetido aqui. Este arquivo cobre só o que muda quando a fonte
é um workspace `har_reproducer` em vez de credenciais fornecidas na hora.

## 1. Os asserts nascem do workspace, não de um `println` de diagnóstico

O runbook padrão do robô grava o cache primeiro com um `println` de
diagnóstico no `then:`, porque normalmente não se sabe o valor real antes de
gravar. Aqui já se sabe: `real_responses/res_NNNN.json` de cada passo é a
resposta real que o portal deu durante a reprodução do HAR. Antes de gravar
qualquer cache do robô:

1. Extraia do `real_responses/` do passo alvo os valores que o fluxo deveria
   produzir (contagem de itens, campos de um DTO, presença de uma mensagem).
2. Escreva o `then:`/`and:` do cenário **com esses valores já como
   asserções reais**, não como `println`.
3. Grave o cache do robô (seção 2) e confirme que os mesmos valores batem.

Isso muda o papel da gravação: em vez de "descobrir o que o fluxo faz",
ela vira "confirmar que o fluxo escrito produz o que o workspace já provou
que o portal responde". Uma divergência aqui é sinal de erro de tradução
(passo 3 de `processo.md`), não de portal instável — investigue a tradução
antes de suspeitar do portal.

## 2. Gravação de cache nesta sessão

Sujeito ao guardrail do `SKILL.md` (fluxo de leitura + credencial fornecida
nesta sessão): siga o ciclo RECORD→PLAY exatamente como
`oficina-de-fluxos` descreve (`cacheMode: FIXTURE_MODE_RECORD` +
`TRABALHO=1`, depois `FIXTURE_MODE_CLASSE_INTEIRA` para confirmar). A única
diferença de origem é que **as credenciais já são conhecidas** (foram usadas
para gerar o `.har` original) — não há necessidade de pedir ao usuário
"como você quer validar", como o runbook padrão faz para fluxo novo sem
workspace prévio; a resposta já está decidida pela existência do workspace.

Se a gravação divergir do que `real_responses/` previa (outro status, outro
formato, campo ausente): pare antes de "consertar" o assert para bater com a
gravação nova. Isso costuma significar uma de duas coisas:

- O portal mudou entre a captura do HAR e agora (`diagnostics.md` de
  `reproducao-de-har` tem a lista de causas prováveis) — cabe ao usuário
  decidir se o `.har` precisa ser recapturado.
- A tradução (passo 3/4 de `processo.md`) tem um erro — a `Tarefa` não está
  reproduzindo fielmente o que o `curl`/extrator do workspace descrevia.

## 3. Cada lacuna vira um teste que a expõe, não um valor escondido

Esta é a parte que corresponde diretamente ao pedido de "testes para validar
eventuais lacunas". Para cada token resolvido por `LiteralAgent`/
`LiteralFallbackAgent` (seção 4 de `mapa-de-traducao.md`) que virou constante
no Helper:

- Escreva (ou confirme que já existe) um cenário cujo `real_responses/`
  contém um valor **diferente** do literal hardcoded para aquele campo, se
  esse cenário existir no workspace (ex.: o HAR tem mais de uma amostra do
  mesmo endpoint com valores diferentes — raro, mas quando existe é prova
  direta de que o campo não era estático).
- Quando só existe uma amostra (o caso comum): não é possível provar
  automaticamente que o valor é estático. Documente essa limitação no PR/
  ticket do robô (mesmo texto da seção 4 de `mapa-de-traducao.md`) em vez de
  deixar a suposição implícita só no código — um teste verde aqui prova que
  o fluxo funciona **com aquela amostra**, não que o valor é imutável.

Para cada `success_criteria` que não teve validador dedicado (seção 3 de
`mapa-de-traducao.md` — `status_code` via `responseStatusCode`, `url_match`
via `Location`): garanta que o cenário de replay spec cobre também o caminho
de **falha** (o mesmo teste de mutação manual que `oficina-de-fluxos` já
pede no checklist — desfaça a validação, confirme que o spec falha, restaure)
— um `validacaoBasica` customizado escrito à mão tem mais chance de ter um
bug sutil (comparação sempre `true`, campo nulo tratado como sucesso) do que
um validador nativo da DSL já testado pelo projeto.

## 4. Escopo: o que "eficácia" prova e o que não prova

Um replay spec verde prova que a `Tarefa`/extrator/Validador escritos
reproduzem **a sequência exata** capturada no `.har` original, com as
respostas gravadas no cache. Ele não prova:

- Que o fluxo continua funcionando se o portal mudar depois da gravação
  (mesma limitação que qualquer replay spec do robô já tem — ver
  `captura-navegacao.md` "Fase 0.5" sobre fixture antiga vs. recém-gravada).
- Que um token resolvido por `LiteralAgent` é de fato estático entre sessões
  diferentes (seção 3 acima).
- Que o fluxo se comporta corretamente fora do caminho feliz que o `.har`
  capturou (erro de rede, sessão expirada no meio, paginação) — a menos que
  o workspace tenha mais de uma amostra cobrindo esses casos.

Declare esse escopo explicitamente no PR/ticket, no mesmo espírito de "sem
silenciar cobertura" — não deixe o revisor do devcheck presumir mais do que
o teste garante.
