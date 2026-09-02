## Fluxo de login

**Características HTTP**
- Começa com uma ou mais requisições contra páginas **não autenticadas** (home, tela de login). Frequentemente uma dessas respostas já contém elementos que a requisição de login vai precisar devolver: um cookie de sessão anônima, um token de formulário (CSRF), ou um campo de estado de página (comum em portais baseados em postback, tipo JSF/ASP.NET) que muda a cada carregamento.
- A requisição de autenticação em si é um POST com usuário/senha e, quando aplicável, aqueles tokens capturados na etapa anterior. A resposta é o que credencia a sessão: pode vir como um novo cookie, um token no corpo (JWT ou similar), ou apenas um HTML/redirect que sinaliza sucesso.
- Segue-se tipicamente uma requisição de confirmação — acessar algo da área logada — porque a resposta do login por si só nem sempre garante que autenticou (alguns portais respondem "200 OK" tanto para sucesso quanto para falha, e o erro só aparece no conteúdo).

**Requisitos para funcionar**
- **Continuidade de sessão entre as próprias requisições do login**: se a página inicial gerou um cookie de sessão temporário, ele precisa ser reenviado nas requisições seguintes — muitos portais invalidam a tentativa de login se o cookie mudar no meio do caminho.
- **Tokens de uso único**: o token/estado de página capturado na tela inicial costuma ter vida curta e é específico daquela sessão — não pode ser reaproveitado de uma navegação anterior, tem que ser sempre o mais recente.
- **Distinção entre "resposta HTTP ok" e "login realmente aceito"**: como o corpo da resposta é frequentemente o único lugar onde aparece "usuário ou senha inválidos", é preciso inspecionar o conteúdo, não só o código de status.
- **Sensibilidade a login simultâneo**: vários portais invalidam a sessão anterior quando um novo login acontece com a mesma credencial — então logins concorrentes com o mesmo usuário podem se atropelar, exigindo serializar essas tentativas.
- **Expiração e renovação**: a sessão obtida tem um tempo de vida; se ela expirar no meio de uma navegação mais longa (nos outros dois fluxos), o sintoma costuma ser sutil — a página volta a mostrar conteúdo de "não logado" ou lança de volta para a tela de login, e isso precisa ser distinguido de "não há mais dados a mostrar".
- **A requisição da tela inicial e o passo de login não são protegidos de graça pelo `optimize`, e removê-los sem perceber é o falso positivo mais perigoso deste padrão de fluxo.** `optimize` só mantém automaticamente o piso (`--from`, padrão `0`) e o alvo (`--to`) — qualquer outro passo, incluindo o de login, só sobrevive à busca se o resolver identificar que o alvo depende dele via algum token dinâmico. Se o token de acesso parecer "fixo" na amostra capturada (não mudou entre as respostas que o pipeline viu, ou a resolução caiu no fallback do `captured_value`), o login deixa de ser reconhecido como origem de qualquer coisa e vira só mais um candidato removível — mesmo que na realidade a sessão seja obrigatória e o valor só pareça estático porque a amostra é pequena. "Pareceu fixo neste HAR" nunca é prova de que é fixo de verdade (mesma advertência de `analysis-strategies.md` contra generalizar de uma gravação só, e o mesmo tipo de confirmação que `extractor-crud-strategies.md` exige antes de aceitar um extrator como "inútil").
  - **Não esperar o falso positivo acontecer para agir — em qualquer fluxo de login, declarar `--required-steps-file` com o índice da requisição da tela inicial e o índice do passo de autenticação *antes* da primeira chamada a `optimize`, por padrão.** Não é uma correção reativa a aplicar só depois de ver o login sumir do `.txt` — dado que os dois passos quase sempre são obrigatórios num fluxo de login (ver os dois motivos abaixo), o custo de declará-los de saída é baixo e elimina de vez essa classe de falso positivo, em vez de arriscar um schedule quebrado na primeira tentativa.
  - **Qual é "a requisição da tela inicial"**: a que estabelece a sessão anônima que o login vai reaproveitar — normalmente a primeira requisição do HAR contra o domínio do portal, o que na prática costuma cair no índice `0`. Mas isso não é uma garantia estrutural do formato HAR nem deste projeto — identificar pelo papel que a requisição exerce no fluxo (é dela que sai o cookie/token que o `POST` de login reenvia), não assumir o índice `0` de cabeça sem checar; num HAR com redirecionamentos, chamadas de health-check, ou capturas que começam no meio de uma navegação, pode ser outro índice.
  - **Motivo 1 — a requisição da tela inicial carrega uma função que nenhum token consumido reflete**: é a checagem implícita de que o portal está no ar antes de qualquer outra coisa. Um schedule minimizado sem ela não detecta "o site caiu inteiro" — só teria como sintoma o próprio passo de login falhando, sem isolar se a causa foi o portal fora do ar ou uma sessão mal resolvida.
  - **Motivo 2 — o passo de login é o único que credencia a sessão**: sem ele, não há requisição alguma que efetivamente autentique; qualquer outro passo do fluxo depende, direta ou indiretamente, do que ele produz.
  - **Forma recomendada:** declarar o índice da requisição da tela inicial e o
    do login num `.txt` (um índice por linha) e passar via
    `optimize --required-steps-file <arquivo>` — o `ReplayOptimizer` nunca tenta
    remover esses índices, independente do que o resolver de tokens concluir
    sozinho. Preferível a `--from <índice do login>`, que descarta tudo antes do
    login (inclusive a própria requisição da tela inicial).
  - **Mesmo declarando de saída, continuar conferindo o `.txt` de saída de qualquer `optimize` sobre um fluxo de login** — como rede de segurança, não como único mecanismo: confirma que os dois índices realmente aparecem no resultado (proteção contra engano na identificação do índice certo, ou erro no `required-steps-file`). Se algum sumiu apesar do `required-steps-file`, é sinal de bug/config errada, não de que era dispensável.

## Fluxo de valores pagos

**Características HTTP**
- Pressupõe uma sessão já autenticada.
- Envolve normalmente poucas requisições de navegação intermediária antes de chegar ao dado — telas ou endpoints que preparam contexto (selecionar uma unidade, um convênio, um período) antes da consulta valer.
- Uma requisição de filtro/consulta, com parâmetros como intervalo de datas ou número de protocolo.
- Uma requisição final que entrega o resultado — seja como arquivo para download (planilha, XML, JSON) ou como uma página cujo conteúdo é lido diretamente.
- Volume de requisições geralmente **baixo**: uma consulta, talvez algumas poucas páginas de resultado.

**Requisitos para funcionar**
- **Estado de navegação no servidor**: em muitos portais mais antigos, cada tela intermediária não é apenas visual — ela grava algo do lado do servidor (o filtro selecionado, o contexto ativo) que a requisição seguinte depende. Pular uma etapa "que parece não fazer nada" pode fazer a consulta final falhar ou retornar dados errados/vazios, mesmo com os parâmetros certos.
- **Ordem estrita, sem paralelismo**: como o estado é acumulado passo a passo do lado do servidor, essas requisições geralmente não podem ser paralelizadas nem reordenadas — a segunda depende do efeito colateral da primeira.
- **Processamento assíncrono do lado do portal**: quando a consulta dispara um relatório que o servidor gera em segundo plano, a resposta imediata só confirma que o pedido foi aceito; é preciso consultar novamente depois de um intervalo até o conteúdo (ou um link de download) estar de fato pronto — o que exige esperar e tentar de novo, não apenas uma requisição só.
- **Tempo de espera dimensionado para consulta, não para navegação simples**: uma busca com filtro amplo (período longo, muitos protocolos) pode levar bem mais tempo para responder do que uma navegação comum, então o tempo de espera tolerado antes de considerar "travou" precisa ser maior aqui.

## Fluxo analítico

**Características HTTP**
- Compartilha o mesmo início do fluxo de valores pagos (sessão autenticada, navegação de contexto, filtro/consulta).
- A diferença central: o resultado da consulta não é um único arquivo, mas uma **lista de itens** (protocolos, guias, competências), e cada item da lista exige sua própria sequência de requisições para ser obtido — abrir o detalhe daquele item e então baixar o arquivo correspondente. Isso se repete para cada item da lista.
- Volume de requisições **muito maior e mais variável** que o fluxo de valores pagos: pode ir de poucos a centenas de downloads numa única execução, dependendo de quantos itens a consulta retornou.
- Frequentemente há paginação da própria lista de itens (a busca retorna páginas de resultado, e é preciso percorrer todas para não perder itens).

**Requisitos para funcionar**
- **Sessão precisa se manter estável por muito mais tempo/requisições**: como o número de chamadas é grande, o risco de a sessão expirar no meio do processo é maior — e se expirar, é preciso detectar isso e reautenticar antes de continuar, em vez de simplesmente interpretar a ausência de dados como "acabaram os itens".
- **Continuar de onde parou / não perder o que já foi obtido**: dado o volume, uma falha pontual (um item que não baixa) não deveria descartar todos os itens já baixados com sucesso — o ideal é registrar/guardar progressivamente, item a item, e não só ao final de tudo.
- **Paginação completa da listagem**: é preciso garantir que todas as páginas da lista de itens sejam percorridas antes de considerar a coleta completa — parar cedo demais (por timeout ou por engano na contagem de páginas) faz itens serem silenciosamente ignorados.
- **Degradação de desempenho do portal sob volume**: portais que atendem bem a poucas requisições podem ficar visivelmente mais lentos (sem chegar a falhar) quando centenas de downloads são feitos em sequência numa mesma sessão — o que exige tolerância maior a demora e, às vezes, espaçar as requisições para não sobrecarregar.
- **Concorrência ainda mais sensível**: como a sessão é usada por muito mais tempo, o custo de uma segunda sessão (do mesmo usuário) invalidar a primeira no meio do processo é maior — reforça a necessidade de nunca ter duas execuções concorrentes usando a mesma credencial nesse tipo de fluxo.

