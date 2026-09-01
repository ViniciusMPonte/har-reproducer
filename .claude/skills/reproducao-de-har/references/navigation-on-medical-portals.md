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
- **Step 0 e o passo de login não são protegidos de graça pelo `optimize`, e removê-los sem perceber é o falso positivo mais perigoso deste padrão de fluxo.** `optimize` só mantém automaticamente o piso (`--from`, padrão `0`) e o alvo (`--to`) — qualquer outro passo, incluindo o de login, só sobrevive à busca se o resolver identificar que o alvo depende dele via algum token dinâmico. Se o token de acesso parecer "fixo" na amostra capturada (não mudou entre as respostas que o pipeline viu, ou a resolução caiu no fallback do `captured_value`), o login deixa de ser reconhecido como origem de qualquer coisa e vira só mais um candidato removível — mesmo que na realidade a sessão seja obrigatória e o valor só pareça estático porque a amostra é pequena. "Pareceu fixo neste HAR" nunca é prova de que é fixo de verdade (mesma advertência de `analysis-strategies.md` contra generalizar de uma gravação só, e o mesmo tipo de confirmação que `extractor-crud-strategies.md` exige antes de aceitar um extrator como "inútil").
  - **Depois de qualquer `optimize` sobre um fluxo de login, conferir se o `.txt` de saída inclui o índice do primeiro passo (tipicamente `0`) e o índice do passo de autenticação.** Se algum sumiu, tratar como sinal de falso positivo — não como confirmação de que era dispensável — e investigar por que o resolver não reconheceu a dependência antes de aceitar o schedule.
  - **Step 0 carrega uma segunda função que nenhum token consumido reflete**: é a checagem implícita de que o portal está no ar antes de qualquer outra coisa. Um schedule minimizado sem ele não detecta "o site caiu inteiro" — só teria como sintoma o próprio passo de login falhando, sem isolar se a causa foi o portal fora do ar ou uma sessão mal resolvida.
  - Se precisar garantir os dois por fora do que a busca decide: rodar `optimize --from <índice do login>` protege o login e tudo abaixo dele como piso; devolver o step 0 manualmente e revalidar com `replay --mode list --steps-file` antes de aceitar o resultado.

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

