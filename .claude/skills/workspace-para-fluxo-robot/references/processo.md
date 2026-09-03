# Processo — do workspace ao código do robô

## 1. Montar o mapa de captura a partir do workspace

`captura-navegacao.md` define o mapa de captura como o artefato de trabalho
que fecha a Fase 1 (sessão ao vivo/HAR) e alimenta a Fase 2 (escrita do
código). Aqui a Fase 1 inteira é substituída por leitura de arquivo — o
formato do mapa continua o mesmo, só a coluna "origem" muda.

Para cada índice em `replays/optimized_<run_id>.txt`, preencha uma etapa:

```markdown
## Etapa: {inferir do propósito da URL/parâmetros — ex.: "login", "lista de guias"}
- Requisição: {método} {url} — de `original_requests/req_NNNN.json`
- Parâmetros: {nome: origem} — literal do HAR, ou `{{extractor:<token_id>}}` →
  origem no passo anterior (ver `curls/req_NNNN.curl.sh`, comentário
  "Token <id> comes from response of step <n>")
- Extratores desta resposta: {token_id: agent_type} — de `extractors/*.meta.json`
  cujo `origin_step` é este índice
- Resposta: formato (JSON/HTML/arquivo) — de `real_responses/res_NNNN.json`
- Tarefa DSL correspondente: {a decidir na tradução}
```

Diferença prática em relação à sessão ao vivo: não há "requisição de ruído"
para filtrar — `optimize` já removeu do `.txt` qualquer passo que o `replay`
provou ser dispensável. Todo índice que sobra é, por definição, necessário.

Diferença em relação ao fallback HAR puro: os parâmetros dinâmicos já vêm
identificados e resolvidos (não é preciso comparar `postData params` a olho
para achar o que muda entre requisições — o `curl` já marca exatamente isso).

Com o mapa montado, siga o resto de `oficina-de-fluxos` normalmente a partir
da Fase 2 de `captura-navegacao.md` ("Do mapa ao código"): escolha de tipos
de tarefa, Helper, autenticação — nada disso é específico desta origem.

## 2. Casos que o mapa não resolve sozinho

- **Passo cuja única função é obter cookie/token que o `usarCookiesAutomaticos`
  já cobre automaticamente** (ex.: um `GET` inicial só para receber
  `JSESSIONID`): ainda vira uma `Tarefa` — o robô também precisa fazer essa
  requisição para a sessão existir, mesmo sem extrator explícito associado a
  ela.
- **Token cujo `origin_step` não está mais na lista otimizada** (o passo que
  gerava o valor foi removido pelo `optimize` porque o valor também aparecia
  capturável em outro lugar mais barato): confie na escolha do `optimize` —
  ele já validou isso via `replay`. A `Tarefa` que usa o token aponta pro
  `origin_step` que sobreviveu, não pro índice original do HAR.
- **`config.json` ausente ou sem `success_criteria` no workspace**: não
  invente um Validador correspondente — significa que o critério de sucesso
  daquele fluxo nunca foi formalizado no `har_reproducer` (o `run`/`replay`
  só checou `status_code` implícito). Proponha ao usuário reforçar o
  `config.json` do workspace antes de exportar, ou aceite que o fluxo no
  robô nasce só com as validações padrão de login/erro genérico do checklist
  de `padroes-e-boas-praticas.md`.

## 3. Checklist de correspondência (específico desta origem)

Além do checklist canônico de `padroes-e-boas-praticas.md` e da Fase 3 de
`captura-navegacao.md` (que continuam valendo integralmente), confira:

- [ ] Todo índice de `replays/optimized_<run_id>.txt` virou exatamente uma
      `Tarefa` (ou foi absorvido pelo padrão Login Cache, se for o passo de
      login).
- [ ] Todo `token_id` referenciado em algum `curls/*.curl.sh` tem, ou (a) um
      extrator correspondente na `Tarefa` do seu `origin_step`, ou (b) uma
      entrada explícita na lista de lacunas (`LiteralAgent`/
      `LiteralFallbackAgent`, seção 4 de `mapa-de-traducao.md`) com decisão
      registrada.
- [ ] Todo `success_criteria` do `config.json` do passo alvo virou um
      Validador ou foi conscientemente descartado (com justificativa — ex.:
      já coberto por `validacaoLogin`/`validacaoLoginInvalido` padrão).
- [ ] Nenhum parâmetro de `original_requests/req_NNNN.json` foi esquecido no
      Helper — mesma checagem que a Fase 3 de `captura-navegacao.md` já
      pede, só que a fonte é o JSON do workspace em vez da aba de rede.
