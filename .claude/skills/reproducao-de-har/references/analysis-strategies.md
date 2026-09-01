## Desconfiar do veredito da própria ferramenta

- **Nunca aceitar `Reproduction SUCCESSFUL`/`Optimization SUCCESSFUL` só pelo `status_code`.** Muitos portais respondem 200 tanto pro conteúdo esperado quanto pra uma página de erro/sessão expirada/"faça login de novo" — o `status_code` sozinho não distingue os dois. Comparar o corpo de verdade (`original_responses/res_NNNN.json` esperado vs. `real_responses/`/`replays/<run_id>/res_NNNN.json` obtido) é o primeiro passo, sempre, antes de aceitar qualquer veredito de sucesso.
- **`success_criteria` fraco mascara falha silenciosamente.** Se o `config.json` só tem `status_code`, reforçar com `body_contains` (um trecho que só aparece no estado genuinamente certo, ex. um título de página autenticada) assim que esse trecho for identificado — sem isso, tanto `replay` quanto `optimize` podem reportar sucesso mesmo caindo numa página de erro.
- **Um schedule "mínimo" reportado por `optimize` pode não se sustentar sozinho.** Antes de confiar no `.txt` exportado, testar esse mesmo schedule isolado, via `replay --mode list --steps-file`, num contexto que não reaproveite nenhum estado da execução do `optimize` que o gerou — cache/jar "quente" de uma busca pode fazer um schedule passar ali e falhar depois, num processo novo.

## Localizar exatamente onde a divergência começa

- **Diff byte a byte entre esperado e obtido**, em vez de ler o corpo inteiro: percorrer os dois textos em paralelo e reportar o primeiro índice onde divergem, com uma janela de contexto ao redor. Leva direto ao trecho relevante (um valor de sessão embutido, um contador, um id) sem exigir leitura manual de HTML grande.

  ```python
  import json

  esperado = json.load(open("original_responses/res_0106.json")).get("body", "")
  obtido = json.load(open("real_responses/res_0106.json")).get("body", "")

  for i, (a, b) in enumerate(zip(esperado, obtido)):
      if a != b:
          print("primeira diferença no índice", i)
          print("esperado:", repr(esperado[max(0, i - 60):i + 100]))
          print("obtido  :", repr(obtido[max(0, i - 60):i + 100]))
          break
  else:
      print("um é prefixo do outro; comparar os tamanhos:", len(esperado), "vs", len(obtido))
  ```

- **Comparar o tamanho do corpo entre uma execução "boa" e uma "ruim", passo a passo**, antes de aprofundar em qualquer uma — o primeiro índice onde o tamanho diverge já indica onde investigar o conteúdo de perto, evitando vasculhar dezenas de respostas idênticas.

  ```python
  import json

  run_bom = "replays/20260829_181247"
  run_ruim = "replays/20260829_183925"

  for n in range(0, 107):
      arquivo = f"res_{n:04d}.json"
      try:
          bom = json.load(open(f"{run_bom}/{arquivo}")).get("body", "")
          ruim = json.load(open(f"{run_ruim}/{arquivo}")).get("body", "")
      except FileNotFoundError:
          continue
      if len(bom) != len(ruim):
          print(f"{arquivo}: bom={len(bom)} ruim={len(ruim)} bytes -- DIVERGE")
  ```
- **Ler o contexto ao redor de um match textual, nunca só a linha do match.** Achar uma string de erro ("senha inválida", "código incorreto") não confirma por si só que aquele erro está ativo — pode estar dentro de um bloco `display: none`/template inerte, sempre presente na página independente do que aconteceu. Confirmar se o elemento está genuinamente visível/disparado (ex.: o handler que o *esconde*, não que o *mostra*) antes de concluir.

## Rastrear a evolução de um valor ao longo do tempo, não só numa foto

- **Percorrer as respostas em ordem cronológica, imprimindo só quando um valor muda** (um cookie, um id de sessão, um contador) — revela um padrão de estabilidade ou instabilidade que nenhuma resposta isolada mostra. Um valor que muda a cada passo é qualitativamente diferente de um que muda uma vez e nunca mais.

  ```python
  import glob
  import json
  import re

  campo = "JSESSIONID"  # ou qualquer chave de response.cookies / outro campo rastreável
  arquivos = sorted(
      glob.glob("real_responses/res_*.json"),
      key=lambda p: int(re.search(r"res_(\d+)", p).group(1)),
  )

  anterior = None
  for arquivo in arquivos:
      indice = int(re.search(r"res_(\d+)", arquivo).group(1))
      valor = json.load(open(arquivo)).get("cookies", {}).get(campo)
      if valor != anterior:
          print(indice, "->", campo, "muda para", valor)
          anterior = valor
  ```
- **Comparar o mesmo rastreamento entre duas execuções do mesmo fluxo** para decidir se uma instabilidade é sistemática (sempre acontece, é bug de código) ou intermitente (decisão do servidor, ex. rotação de sessão só às vezes) — a resposta muda completamente qual tipo de correção faz sentido.
- **Comparar timestamps de arquivo (mtime) para medir tempo real decorrido** entre passos — descarta ou confirma explicações baseadas em tempo (ex. "expirou por inatividade") sem depender de suposição.

## Testar uma hipótese estatisticamente sobre o conjunto inteiro, não sobre um exemplo

- Antes de concluir que um valor "parece" dinâmico ou estático, **buscar esse valor/padrão em todos os artefatos do mesmo tipo** (todos os curls, todas as respostas) e observar a distribuição. Um valor que varia de forma explicável por outro fator já conhecido (tipo de recurso, ordem do passo) é evidência de que é decidido no cliente, não extraído de uma resposta do servidor — mesmo que a descoberta automática o tenha classificado como dinâmico.
- Essa checagem em massa é mais barata e mais conclusiva do que analisar um caso isolado — um padrão claro sobre 100 ocorrências é mais forte do que uma inferência sobre uma.

## Procurar o que os campos estruturados do pipeline não capturam

- O pipeline estrutura cookies/headers a partir do que reconhece via `Set-Cookie` e cabeçalhos HTTP — qualquer coisa definida do lado do cliente (JavaScript) fica **invisível** por padrão nos campos já parseados.
- Buscar por padrões de atribuição no próprio corpo da resposta (funções de manipulação de cookie do próprio site, atribuição direta ao armazenamento do navegador) é o único jeito de achar esse tipo de dependência — e vale revisitar essa busca especificamente depois de já ter "fechado" a investigação pelos campos estruturados, porque é fácil dar por encerrado sem perceber essa classe inteira de dependência.

## Verificar o comportamento real de uma ferramenta externa em vez de supor

- Quando o comportamento de uma peça de baixo nível (como precedência entre duas formas de especificar a mesma coisa numa chamada de rede) é incerto, **reproduzir a dúvida isoladamente** — um servidor mínimo local e uma chamada real da ferramenta em questão — em vez de confiar em memória ou suposição. É rápido, decisivo, e evita gastar tempo investigando a hipótese errada.

## Ler o código-fonte do projeto lado a lado com a evidência empírica

- Toda vez que uma investigação empírica aponta pra um sintoma, **ler o código real do componente envolvido** antes de propor uma correção — entender o mecanismo exato (por que o comportamento acontece, não só que ele acontece) é o que distingue uma correção de um remendo. Uma hipótese só empírica pode acertar o sintoma e errar a causa.
- Isso também é o que permite avaliar se uma correção proposta é segura: ler todos os chamadores reais de um método antes de mudar sua assinatura ou comportamento evita quebrar um uso legítimo que a investigação não tinha em mente.

## Transformar uma hipótese observada ao vivo em prova reproduzível

- Depois de suspeitar de um bug numa execução real (cara, lenta, não-determinística — sujeita a decisões de servidor fora do controle de quem investiga), **escrever um teste com dublês que force exatamente o cenário suspeito**, isolado do sistema real. Isso faz três coisas: confirma que a hipótese é de fato suficiente para causar o sintoma (não só compatível com ele); vira uma evidência que sustenta uma decisão de correção sem depender de acesso ao ambiente real de novo; e detecta regressão futura automaticamente.

## Sinais que valem seguir mesmo sem uma pista óbvia

- **Dois runs idênticos do mesmo fluxo dão resultados diferentes**: não presumir "bug determinístico" só porque o código não mudou — considerar decisão do servidor (rotação de sessão, balanceamento de carga, limite de tentativas) como hipótese válida, e testar rastreando o valor relevante entre as duas execuções.
- **Um header/cookie estruturalmente correto ainda assim não "vinga"**: procurar por uma segunda fonte do mesmo dado no mesmo request/response (dois headers com o mesmo nome, um deles sendo descartado silenciosamente por uma regra de precedência de baixo nível) antes de assumir que o dado simplesmente não chegou.
- **Uma âncora/passo necessário "some" de um schedule reduzido/otimizado**: suspeitar de vazamento de estado entre a fase de exploração (que pode legitimamente reaproveitar cache/contexto mais amplo) e a fase de decisão final (que precisa refletir só o que está genuinamente sendo testado) — é uma classe de bug estrutural, não um erro de configuração isolado.
- **Uma mensagem de erro relevante aparece no meio de uma página enorme**: sempre ler a estrutura ao redor (título da página, se o formulário de origem ainda está presente, se o elemento está de fato ativo) antes de tratar a presença da string como confirmação — texto de template inerte é comum em páginas de portais mais antigos.
