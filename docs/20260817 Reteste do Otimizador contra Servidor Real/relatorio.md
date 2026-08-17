# Relatório — Reteste do comando `optimize` contra servidor real

**Data:** 17/08/2026
**Relatório anterior:** `docs/20260811-3 Teste do Otimizador contra Servidor Real/relatorio.md`
(daqui em diante, "R1"). Este documento reexecuta a bateria do R1 sobre o código de
hoje e reavalia, um a um, os achados que ele registrou.

**Código sob teste:** `master` em `9867c4c`, que inclui duas etapas mergeadas depois
do R1:

| Etapa | Branch mergeado | O que endereça do R1 |
|---|---|---|
| `docs/20260812 Correção da Anotação de Token Estático que Quebra o Parser de Dependências` | `eebba86` | Achado 3.3 do R1 (o mais grave) |
| `docs/20260813 Corpus Estruturado de Respostas e Chave de Origem` | `8fb13bf` | Achado 3.1 do R1 (parcialmente — o `Bearer` propriamente dito ficou explicitamente fora de escopo) |

**Workspace usado:** `arquivos-har/output`, regenerado por `run --mode main` sobre
`arquivos-har/progressofit.har` em 17/08/2026 às 19:21–19:27, com o código atual.
238 entries no HAR, 235 `.curl.sh` gerados (os steps `78`, `90` e `166` são `ws://` e
são pulados por `StepSkipEvaluator`), 238 respostas reais em `real_responses/`.

**Servidores:** `http://127.0.0.1:8080` (front estático) + `http://localhost:8090`
(API), ambos em localhost e no ar durante todos os testes — todas as requisições
abaixo foram disparadas de verdade contra eles.

**Suíte:** `uv run pytest --runslow` → **356 passed** em 30,27s (verde antes e depois
da bateria).

## 1. Metodologia

Mesma estrutura do R1: primeiro `replay --mode smart` para confirmar integridade do
workspace e obter o schedule de âncoras de referência, depois a bateria de `optimize`.
Três diferenças deliberadas em relação ao R1:

1. O R1 rodou `replay --mode smart --to 233` três vezes e usou o encolhimento do
   schedule como sintoma. Aqui a repetição é o **teste de regressão** do bug 3.3 —
   rodei as três chamadas de propósito, sobre um workspace que **já tinha anotações
   de replay gravadas em disco** (o pior caso do R1).
2. Além da bateria do R1, testei três cenários que o R1 listou como não exercitados
   (seção 3.5 do R1): alvo cuja faixa falha mesmo com todos os candidatos, colisão de
   `--steps-out`, e o caminho de recuperação reativa.
3. Testei a **minimalidade** do resultado do `optimize`, coisa que o R1 não fez —
   ele verificou que o `.txt` funciona, não que ele é mínimo. É de onde vem o achado
   novo mais relevante deste relatório (seção 3.5).

Para o cenário de credencial inválida usei um **clone** do workspace
(`cp -r arquivos-har/output <scratchpad>/ws_expired`) com o JWT adulterado nos 9
`.curl.sh` que carregam `Authorization`, para não contaminar o workspace real.

## 2. Testes executados

### 2.1 Estabilidade do schedule de âncoras (regressão do bug 3.3 do R1)

```bash
for i in 1 2 3; do
  uv run python -m har_reproducer.main replay \
    --output ../arquivos-har/output --mode smart --to 233 --config config.json
done
```

| Chamada | Schedule executado (R1) | Schedule executado (hoje) |
|---|---|---|
| 1ª | `[0, 1, 14, 23, 34, 75, 233]` | `[0, 1, 14, 23, 34, 75, 233]` |
| 2ª | `[0, 1, 23, 34, 75, 233]` | `[0, 1, 14, 23, 34, 75, 233]` |
| 3ª | `[233]` | `[0, 1, 14, 23, 34, 75, 233]` |

**Corrigido.** Detalhe em 3.1.

### 2.2 Caminho feliz — alvo `233` (`/api/weight/weekly/last-months/1`)

```bash
uv run python -m har_reproducer.main optimize \
  --output ../arquivos-har/output --to 233 --config config.json --steps-out opt_233.txt
```

`Optimization SUCCESSFUL: 7 step(s)` → `[0, 1, 14, 23, 34, 75, 233]`, igual ao R1.
**94 requisições reais em 12,4s**, decompostas assim (contadas no log):

| Fase | Requisições |
|---|---|
| Backbone (`0`…`75`) | 76 |
| 6 faixas × 1ª tentativa com `extra_candidates = []` | 11 (a faixa `(75, 233)` custa 1, as outras 5 custam 2) |
| Confirmação final | 7 |
| **Total** | **94** |

`kept = []` em todas as 6 faixas, como no R1. A estimativa de pior caso impressa caiu
de `≈ 41892` (R1) para `≈ 40872` — reflexo de o grafo de dependências estar diferente,
não de mudança na fórmula (`_estimate_worst_case_requests`,
`replay_optimizer.py:172-180`).

### 2.3 Caminho feliz — alvo `227` (`/api/user`)

`Optimization SUCCESSFUL: **7** step(s)` → `[0, 1, 14, 23, 34, 75, 227]`, 94 requisições.

⚠️ **Mudou em relação ao R1**, que reportou `6 step(s)` para o mesmo alvo listando 7
âncoras — a inconsistência do próprio R1 é explicada retroativamente pelo bug 3.3: o
schedule já tinha perdido uma âncora entre a medição e a execução. Hoje os dois números
batem, nas duas rodadas.

### 2.4 `--success-criteria` estrito, sobrescrevendo o `config.json`

```bash
uv run python -m har_reproducer.main optimize \
  --output ../arquivos-har/output --to 233 \
  --success-criteria '[{"type":"status_code","expected":200},{"type":"body_contains","expected":"weekOfYear"}]'
```

`7 step(s)`, mesmo conjunto. Confirma que a flag sobrescreve o `config.json` (que só
tem `status_code`) e que `ReplayOptimizer._confirm` (`replay_optimizer.py:62-65`)
valida o corpo de fato. **Diferente do R1**, aqui o resultado é idêntico ao de 2.2 —
no R1 os dois números divergiam (`7` vs `6`) por causa do bug 3.3, não por causa do
critério.

### 2.5 Round-trip com `replay --mode list`

O `.txt` de 2.4 consumido direto por `replay --mode list --steps-file` → `✓ SUCCESS`.
Formato de saída continua sendo exatamente o que o `--steps-file` espera.

### 2.6 Erros — validação antes de qualquer rede

| Cenário | Resultado | Requisições disparadas | Exit code |
|---|---|---|---|
| Sem `success_criteria` | `ValueError: handle_optimize: success_criteria vazio — informe --success-criteria ou configure success_criteria no config.json antes de rodar optimize.` (`cli_handlers.py:174`) | 0 | 1 |
| `--from 999999` | `ValueError: ReplayOptimizer: step(s) [999999] não existem no workspace ...` (`cli_handlers.py:184`) | 0 | 1 |
| `--max-requests 5` | `ValueError: ReplayOptimizer: teto de requisições atingido (76/5) — abortando a busca.` | 76 (aborta dentro do backbone) | 1 |

Nenhum `.txt` escrito no caso do teto. Idêntico ao R1.

### 2.7 `--from 36`

`Optimization SUCCESSFUL: **3** step(s)` → `[36, 75, 233]`, 46 requisições.
O R1 obteve `[36, 233]` (2 steps). A âncora `75` voltou porque a aresta que a
sustentava tinha sido apagada pelo bug 3.3 no workspace do R1 — ver 3.4.

### 2.8 Colisão de `--steps-out` (não exercitado no R1)

Rodar `optimize --to 227 --steps-out <arquivo já existente com o resultado de 233>`
**sobrescreve silenciosamente**, sem aviso nem backup (`replay_optimizer.py:59`,
`destination.write_text(...)`). Comportamento aceitável, mas não documentado no README.

### 2.9 Alvo intermediário que responde `304` — alvo `83` (não exercitado no R1)

O step `83` é um `GET` de asset estático com `If-None-Match`, e agora esse header é
resolvido dinamicamente (ver 3.2). Contra o servidor real ele responde `304`:

| Comando | Resultado |
|---|---|
| `optimize --to 83 --config config.json` | `Optimization FAILED` — `faixa (14, 83) falhou mesmo com todos os candidatos incluídos` (o `success_criteria` do `config.json` exige `200`) |
| `optimize --to 83 --success-criteria '[{"type":"status_code","expected":304}]'` | `Optimization SUCCESSFUL: 4 step(s)` → `[0, 1, 14, 83]`, 24 requisições |

Isso **não é um defeito** — é o motivo de `--success-criteria` existir (o README já diz
isso). Vale registrar porque é o primeiro cenário em que a mensagem de abort do
`optimize` aparece contra o servidor real, e porque o `304` é a prova de ponta a ponta
de que a cadeia `ETag → If-None-Match` reproduz corretamente (3.2).

### 2.10 Credencial inválida — clone do workspace com JWT adulterado (não exercitado no R1)

Nos 9 `.curl.sh` que carregam `Authorization`, o JWT recebeu um sufixo `TAMPERED`.
`optimize --to 233` sobre esse clone:

```
232 requisições, 49,1s
Step 233 completed with status 403   (nas duas execuções que o alcançaram)
ReplayOptimizer: aborted — ReplayOptimizer: faixa (75, 233) falhou mesmo com todos os
candidatos incluídos.
Optimization FAILED: unable to find a passing subset (see abort reason above).
```

Três coisas caem daqui, todas em 3.6/3.7: a faixa `(75, 233)` **contém o step 154**
(o login) e foi testada com ele incluído, sem sucesso; a recuperação reativa **não
disparou nenhuma vez**; e o processo terminou com **exit code 0**.

## 3. Achados

### 3.1 R1 §3.3 (anotação `- probably static` quebra o parser) — **CORRIGIDO**

A etapa de 12/08 não corrigiu o regex: trocou o contrato. A cláusula que a máquina lê
passou a ser delimitada por `[...]` e o status humano vive depois do `]`
(`curl_token_comment.py:26-31`), com uma classe única dona do formato — escrita e
leitura (`CurlTokenComment`, que substituiu `CurlDependencyParser`).

Evidência direta sobre o arquivo real, **já anotado por replays desta sessão**:

```
$ grep "^#" arquivos-har/output/curls/req_0233.curl.sh
# [Token b63fc1ef9b73f9b1c04af908af821991 comes from response of step 0023] origin location undetermined — using literal captured value; probably static
# [Token 5eb3fa291ebc69f66c9012e8e4a7dfef comes from response of step 0034] origin location undetermined — using literal captured value; probably static
# [Token 5809b41abdae40b7eb763e1eaf00f038 comes from response of step 0075] origin location undetermined — using literal captured value; probably static
# [Token 6add66a68f40dd363bab9f12346bd729 comes from response of step 0001] origin location undetermined — using literal captured value; probably static
# [Unresolved 6] url; header:Accept; header:Authorization; header:Referer; header:Sec-Fetch-Mode; header:Sec-Fetch-Site

>>> CurlTokenComment(step_index_width=4).parse(texto)
{'b63fc1ef...': 23, '5eb3fa29...': 34, '5809b41a...': 75, '6add66a6...': 1}
```

O R1 mediu `matches: 0` no mesmo tipo de arquivo. Hoje são 4 arestas, com as anotações
de replay presentes. O schedule estável de 2.1 é a consequência observável disso.

Vale notar que o R1 recomendava "rodar `optimize` só sobre um `--output` que nunca
recebeu `replay`". **Essa recomendação está revogada** — o workspace desta bateria
recebeu 9 `replay` e 8 `optimize` ao longo da sessão e o schedule não se moveu.

### 3.2 R1 §3.1 (`Authorization: Bearer`) — endereçado em volta, **não no alvo**; e o diagnóstico do R1 estava incompleto

A etapa de 13/08 nasceu deste achado, mas ao investigar encontrou duas falhas
anteriores e independentes na descoberta de origem, corrigiu essas duas, e deixou o
casamento parcial (o `Bearer ` propriamente dito) explicitamente para a spec seguinte
(spec de 13/08, §1.5).

**O que melhorou, medido no workspace real:**

| Métrica | R1 (11/08) | Hoje (17/08) |
|---|---|---|
| Extratores persistidos | 57 | **117** |
| `HeaderAgent` | 22 | **86** |
| `CSSAgent` | 13 | 13 |
| `RegexAgent` | 7 | 7 |
| `LiteralAgent` | 11 | 9 |
| `LiteralFallbackAgent` | 4 | **2** |
| **Determinísticos** | 42/57 = **74%** | **106/117 = 90,6%** |

Os 63 extratores novos são **exatamente** os `If-None-Match` que a spec previu, e a
chave que eles miram na resposta de origem é descoberta, não hardcoded:

| Chave de origem (`origin_key`) | Extratores | Previsto na spec |
|---|---|---|
| `ETag` | 63 | 63 |
| `Last-Modified` | 21 | 21 |
| `Access-Control-Allow-Origin` | 2 | 2 (a spec estimou `Pragma`) |
| **Total `HeaderAgent`** | **86** | **86** |

126 dos 235 `.curl.sh` passaram a carregar uma aresta de dependência por `ETag`, e o
número de steps distintos que aparecem como origem de algum token subiu para 69.
Exemplo de ponta a ponta, `req_0083.curl.sh`:

```
# [Token 23519db2... comes from response of step 0001]   →  HeaderAgent, target = 'Last-Modified'
# [Token 1903f503... comes from response of step 0001]   →  HeaderAgent, target = 'ETag'
```

O step `1` só é âncora de `83` por causa dessas duas arestas — sem elas o schedule
seria `[0, 14, 83]`. E o `304` de 2.9 é a confirmação contra o servidor real de que a
requisição condicional é reproduzida com valor fresco.

**O que continua exatamente como no R1:**

```
$ grep -l "Authorization: {{extractor" arquivos-har/output/curls/*.curl.sh | wc -l
0
$ grep -h "comes from response of step 0154" arquivos-har/output/curls/*.curl.sh | wc -l
0
```

O login (`step 154`) continua não sendo origem de nenhum token, e o JWT continua
literal congelado nos 9 steps que o usam (`224`, `227`–`233`, `237`).

**Correção ao diagnóstico do R1.** O R1 afirmou que a causa é `ResponseGrep` não
reconhecer o prefixo `"Bearer "`. Isso é verdade, mas **não é suficiente** — medindo os
dois modos:

- **`--mode dry`** (corpus = `original_responses/`): o HAR **não gravou o corpo da
  resposta do login**. `entry[154].response.content` tem `size: -1` e nenhum campo
  `text`; `original_responses/res_0154.json` tem `body: ""`. Nenhum tratamento de
  prefixo acharia a origem de um valor que não está no corpus. Esse caso agora é
  reportado pelo aviso novo de `HARParser.entries_missing_response_body`
  (`har_parser.py:14`, impresso por `engine.py:59-64`): **13 de 238 entries** sem corpo
  gravado, excluídos `101/204/304` — e o step `154` é uma delas, junto com `75`, `151`,
  `228`, `229`, `231`, `232`, `237` (API) e `104`, `105`, `161`, `164`, `234`
  (assets de CDN).
- **`--mode main`** (corpus = `real_responses/`, que é o caso desta bateria): o corpo
  **está** lá (`real_responses/res_0154.json` traz `{"token":"eyJ..."}`), mas é um JWT
  **diferente** do que o `.curl.sh` procura, porque o valor buscado vem do HAR
  (época da captura) e a resposta vem da execução (época do run):

  | Origem do JWT | `exp` do payload | Data |
  |---|---|---|
  | HAR (valor procurado) | `1798419171` | **28/12/2026** |
  | Resposta real do login desta rodada | `1802557573` | 13/02/2027 |

  Os dois compartilham 121 caracteres de prefixo (cabeçalho JWT + início do payload) e
  divergem a partir do `exp`. Igualdade exata — com ou sem `Bearer ` — não casa.

Ou seja: **casamento parcial sozinho também não resolve este token**. O que resolveria
é a comparação entre as duas épocas (`original_responses` × `real_responses`) já
registrada na §6 da spec de 13/08 como decidido-para-a-spec-seguinte. Este relatório
adiciona a medição que sustenta aquela decisão.

**Prazo concreto do risco:** o schedule mínimo dos alvos autenticados continua
funcionando só porque o JWT congelado do HAR ainda é aceito. Ele expira em
**28/12/2026**. Confirmei contra o servidor real: `token do HAR → 200`,
`token adulterado → 403`, `sem token → 403`.

**Ganho colateral real:** a linha `[Unresolved N]` (decisão 3.9 da spec de 13/08) tornou
isso auditável por `grep`, coisa que o R1 não tinha:

```
$ grep -l "Unresolved.*header:Authorization" arquivos-har/output/curls/*.curl.sh | wc -l
9
```

Medida da linha no workspace: **232 dos 235 curls** a têm, 1022 ocorrências, 18 paths
distintos, maior linha 208 caracteres. A limitação que a própria spec declarou se
confirma — 17 dos 18 paths são header de contexto de navegador (`Referer` 226, `url`
221, `Accept` 215, `Sec-Fetch-Mode` 215, `Origin` 60, …) e `header:Authorization`
aparece em 9. A linha vale como trilha de `grep`, não como alarme.

### 3.3 R1 §3.2 (comentário de proveniência mentiroso) — **NÃO corrigido**, e agora quantificado

O R1 registrou como cosmético. Continua existindo, com a mesma causa raiz, agora no
formato novo. `CandidateResolver._process_candidate` retorna cedo quando o slot já está
no registry (`candidate_resolver.py:61-63`) e esse caminho **nunca seta
`candidate.origin_location`** — o campo só é preenchido em `_generate_new_extractor`
(`candidate_resolver.py:139`). `CurlGenerator._origin_status`
(`curl_generator.py:73-79`) decide o texto só olhando esse campo:

```python
if token.origin_location is None:
    return OriginStatusPhrase.UNDETERMINED
```

Medição sobre os 235 `.curl.sh`, cruzando cada `token_id` com o `agent_type` do
`extractors/*.meta.json` correspondente:

| | |
|---|---|
| Linhas de dependência | 865 |
| …com `origin location undetermined — using literal captured value` | 757 |
| …**dessas, cujo extrator real é determinístico** (`Header`/`CSS`/`Regex`) | **540 (71%)** |

Os campeões, com o número de `.curl.sh` em que a afirmação falsa aparece:

| Token | Agente real | Ocorrências |
|---|---|---|
| `54b6cdd4…` | `CSSAgent` | 176 |
| `5809b41a…` | `HeaderAgent` (`Access-Control-Allow-Origin`) | 132 |
| `4ec4bb24…` | `HeaderAgent` | 25 |
| `b63fc1ef…` / `5eb3fa29…` | `RegexAgent` | 11 cada |

Continua sem efeito sobre a resolução (o `{{extractor:...}}` aponta para o extrator
certo; `replay`/`optimize` funcionam), mas o custo subiu: agora a linha convive com a
linha `[Unresolved N]`, que é uma trilha de auditoria **verdadeira** no mesmo arquivo.
Ter uma cláusula de auditoria confiável ao lado de uma afirmação falsa em 71% dos
casos é pior do que era no R1, quando não havia a confiável para comparar.

Correção parece barata e local: setar `candidate.origin_location` também no caminho de
cache hit (é a informação que o `Extractor` persistido já carrega em `agent_type`), ou
derivar o status do extrator em vez do campo do candidato.

### 3.4 R1 §3.4 (`--from` alto troca dependência por literal) — melhorou por consequência, ressalva permanece

`--from 36` hoje devolve `[36, 75, 233]` em vez de `[36, 233]`. A âncora `75` voltou
porque a aresta que a sustenta parou de ser apagada pelo bug 3.1 deste relatório. A
ressalva do R1 continua válida em tese — um `--from` acima da origem real de um token
faz esse token cair no valor de referência armazenado — mas a demonstração do R1 estava
contaminada pelo bug 3.3, então o efeito era maior do que o mecanismo de `--from`
justifica sozinho.

### 3.5 **NOVO — o "mínimo" do `optimize` nunca desafia as âncoras; neste fluxo o mínimo real é 1 step**

Este é o achado mais relevante do relatório.

A fase 2 (`_run_phase2` → `_resolve_range`, `replay_optimizer.py:107-143`) só testa a
remoção de steps que estão **entre** duas âncoras consecutivas
(`_candidates_between`, `replay_optimizer.py:169-170`). As âncoras em si entram no
resultado final por construção (`final_list = sorted({from_index, *anchors, *kept})`,
`replay_optimizer.py:53`) e **nunca são submetidas a nenhuma tentativa de remoção**.

Testei a minimalidade do resultado com `replay --mode list`:

| Alvo | `optimize` devolve | Verificação com só o alvo | Resultado |
|---|---|---|---|
| `233` | `[0, 1, 14, 23, 34, 75, 233]` (7) | `[233]` | `Step 233 → 200`, `✓ SUCCESS` |
| `227` | `[0, 1, 14, 23, 34, 75, 227]` (7) | `[227]` | `Step 227 → 200`, `✓ SUCCESS` |
| `83` | `[0, 1, 14, 83]` (4) | `[83]` e `[0, 14, 83]` | `Step 83 → 304`, `✓ SUCCESS` nos dois |

**Em todos os alvos testados, o mínimo real é 1 step e o `optimize` devolve 4 a 7.**

Mecanismo, confirmado no código: `ReplayTokenResolver._resolve_one`
(`replay_token_resolver.py:56-61`) usa o diretório do replay corrente **só quando a
origem está no schedule**; fora disso lê a resposta de referência armazenada
(`real_responses/`, gravada num run anterior). Então uma âncora removida não quebra
nada — o token é resolvido a partir de dado congelado em disco.

Isso significa que a âncora é uma garantia de **frescor/proveniência** (o valor vem de
uma resposta obtida agora), não de **necessidade** (sem esse step o alvo falha). O
`optimize` mistura as duas coisas: gasta requisições testando necessidade só nos steps
não-âncora e aceita as âncoras sem teste.

⚠️ **O README está impreciso sobre isso.** Ele afirma que o resultado é um "mínimo
local (nenhum passo isolado pode ser removido)". Nos três alvos acima, **qualquer**
passo isolado pode ser removido e o alvo continua passando. A frase correta seria algo
como "mínimo local *dentro das faixas entre âncoras*; as âncoras são preservadas por
construção, como garantia de proveniência".

Não é um bug de implementação — o código faz o que a spec de 11/08 descreve. É um
descompasso entre o que o comando promete no README e o que ele garante, e agora tem
medida: **6 dos 7 steps** do resultado do alvo principal são preserváveis sem teste e
removíveis sem efeito observável.

Isso também casa com o que a spec de 13/08 já registrou para a spec seguinte
(§6: "classificação da aresta em proveniência × necessidade …, com proveniência
**nunca** virando âncora de `compute_smart_schedule`"). Este relatório fornece a
medição que falta: hoje, **100% das âncoras deste fluxo são proveniência pura, zero são
necessidade**.

### 3.6 **NOVO — a recuperação reativa não pode disparar contra este servidor: ele sinaliza falha de auth com `403`**

`ReplayOptimizer.RECOVERABLE_STATUS_CODES` (`replay_optimizer.py:19`) é
`StepRetryPolicy.RECOVERABLE_STATUS_CODES | {0}` = `{400, 401, 0}`
(`step_retry_policy.py:8`). A API do ProgressoFit responde **`403`** para token
ausente, token inválido e token adulterado (verificado com `curl` direto).

Consequência, medida em 2.10: com o JWT inválido, `optimize` executou 232 requisições,
viu `403` em 10 steps distintos (`75`, `151`, `224`, `227`–`233`) e **nunca imprimiu
`detected recoverable status in schedule — refreshing backbone`**. O caminho
`_execute` → `_needs_reactive_refresh` → reexecução do backbone
(`replay_optimizer.py:78-89`) segue sem nunca ter rodado contra servidor real — não por
falta de cenário, mas porque este servidor nunca produz um código da lista.

⚠️ **Cuidado ao "corrigir" isso adicionando `403` à lista.** O step `75`
(`GET /auth/check`) responde `403` **legitimamente** em toda execução bem-sucedida
(está no HAR como `403` e o replay o marca `✓ matched (403 vs original 403)`). Com
`403` na lista de recuperáveis, **toda** chamada de `_execute` deste fluxo dispararia
as 2 recuperações reativas, cada uma reexecutando o backbone inteiro de 76
requisições — ~150 requisições desperdiçadas por tentativa, em um caminho feliz.
A decisão certa não é ampliar a lista fixa: é comparar o status obtido com o status de
referência daquele step (que o `ReplayResultComparator` já sabe fazer), o que também é
mais coerente com o princípio de genericidade de [[arquitetura-e-fundamentos]] do que
uma lista fixa de códigos.

**Correlato:** com o JWT inválido, a faixa que falha é `(75, 233)` — que **contém o
step 154**, e o abort acontece depois de testar a faixa **com todos os candidatos
incluídos**, login inclusive. Ou seja, a previsão do R1 se confirma e é pior do que ele
sugeria: quando o JWT expirar, incluir o login no schedule **não** conserta, porque
nenhum `.curl.sh` consome a resposta do login (3.2). A mensagem de abort aponta a
faixa, não a credencial.

### 3.7 **NOVO — `Optimization FAILED` sai com exit code 0**

`main()` (`main.py:17-18`) chama `args.func(args)` e não converte resultado em código de
saída; `_print_optimize_result` (`cli_handlers.py:190-196`) só imprime. Medido:

| Cenário | Saída | Exit code |
|---|---|---|
| `Optimization SUCCESSFUL` | `.txt` escrito | 0 |
| `Optimization FAILED` (2.10) | nenhum `.txt` | **0** |
| `ValueError` de validação (2.6) | traceback | 1 |
| `Reproduction FAILED` do `replay` | — | **0** |

Um script/CI que encadeie `optimize && replay --mode list` não distingue sucesso de
falha pelo exit code — só pelo `.txt` não existir, ou fazendo `grep` no stdout. As
falhas de *validação* saem com `1`, o que torna o comportamento inconsistente dentro
do mesmo comando.

### 3.8 **NOVO — o risco de coincidência de baixa entropia declarado na spec de 13/08 se materializou**

A spec de 13/08 aceitou explicitamente (§7, item 6) que a regra de igualdade exata do
`origin_key` "não evita coincidência de baixa entropia". Um caso concreto está no
workspace, e ele participa do alvo principal deste relatório:

```
req_0233.curl.sh:  -H 'Origin: {{extractor:5809b41abdae40b7eb763e1eaf00f038}}'
extract_5809b41a….meta.json:  HeaderAgent, origin_step = 75, target = 'Access-Control-Allow-Origin'
real_responses/res_0075.json: {'Access-Control-Allow-Origin': 'http://127.0.0.1:8080'}
```

O header de requisição `Origin` passou a ser extraído do
`Access-Control-Allow-Origin` da resposta do step `75` — que é o **eco CORS do próprio
valor enviado**. O valor extraído está certo e o extrator é determinístico, então não
há defeito funcional. Mas a aresta é semanticamente invertida (o servidor não é a fonte
do `Origin`; ele o repete), e é ela que sustenta a âncora `75` para o alvo `233` — a
mesma âncora que 3.5 mostra ser removível sem efeito. Esse token responde por 132 das
540 linhas de comentário falsas de 3.3.

Registro como confirmação empírica de um risco já declarado e aceito, não como
surpresa. É mais um dado a favor de separar proveniência de necessidade (3.5).

### 3.9 Steps pulados × `optimize` (pendência do R1 §3.5) — **verificado, sem defeito**

O R1 não conseguiu checar a interação com steps pulados porque o HAR não tem `OPTIONS`.
Mas ele **tem** 3 steps pulados por scheme (`78`, `90`, `166`, todos `ws://`), sem
`.curl.sh` em disco. Na rodada de 2.10, a faixa `(75, 233)` foi executada com **todos**
os candidatos incluídos — a única execução desta bateria que percorre esse intervalo
inteiro — e os três steps não aparecem uma única vez no log. `_candidates_between` e
`_compute_backbone` filtram por `schedule_executor.existing_step_indexes()`
(`replay_optimizer.py:76,170`), então a classe de bug catalogada em
`docs/20260805 Steps Pulados Quebram o Schedule do Replay …` **não afeta** o
`optimize`. Pendência do R1 encerrada.

### 3.10 Cobertura que esta rodada ainda não exercitou

- **Recuperação reativa** — continua sem rodar, e agora se sabe por quê (3.6). Só será
  exercitável contra um servidor que devolva `400`/`401`, ou depois de mudar o critério
  de recuperabilidade.
- **Abort na confirmação final** (`replay_optimizer.py:54-55`) — nunca observado. Exige
  que todas as faixas passem individualmente e o conjunto final falhe; não ocorreu.
- **Retenção genuína de candidato na fase 2** (`_resolve_range`,
  `replay_optimizer.py:138-143`) — continua sem nunca reter nada. Neste fluxo isso é
  estrutural, não acidental: o único candidato plausível a "efeito colateral
  necessário" é o login, e ele não é consumido por ninguém (3.2). Enquanto o
  `Authorization` não for modelado como dependência, essa árvore de decisão não tem
  como ser exercitada por este HAR.
- **`skip_rules.methods`** — o HAR não tem `OPTIONS`; só a variante por scheme foi
  coberta (3.9).

## 4. Conclusão

**Do R1, o que fechou:**

1. **§3.3 (severidade alta) — corrigido e verificado.** O schedule de âncoras é estável
   sob repetição, sobre um workspace já anotado por replays. A recomendação do R1 de
   "só rodar `optimize` sobre workspace virgem de `replay`" está revogada (3.1).
2. **§3.5 (steps pulados) — verificado, sem defeito** no `optimize` (3.9).

**Do R1, o que continua aberto:**

3. **§3.1 (`Authorization`)** — o pipeline melhorou muito em volta (117 extratores
   contra 57; 90,6% determinísticos contra 74%; 63 dependências `ETag` reais que antes
   viravam literal), mas o JWT continua congelado e o login continua não sendo
   dependência de ninguém. E o diagnóstico do R1 estava incompleto: **casamento parcial
   sozinho não resolve** — em `dry` o corpo do login não está no HAR (agora reportado
   pelo aviso de 13 entries sem corpo), e em `main` o valor procurado é de outra época
   que a resposta disponível. Prazo do risco agora é datado: **28/12/2026** (3.2).
4. **§3.2 (comentário mentiroso)** — não corrigido; agora medido em **540 de 757 linhas
   (71%)** e mais incômodo do que era, por conviver com a linha `[Unresolved N]`, que é
   auditoria de verdade (3.3).

**Novo neste relatório:**

5. **(Maior severidade dos novos)** O resultado do `optimize` **não é mínimo** no
   sentido que o README promete: as âncoras nunca são testadas para remoção, e neste
   fluxo o mínimo real é 1 step contra os 4–7 devolvidos. A âncora garante
   proveniência, não necessidade, e o comando não distingue as duas coisas (3.5).
6. A recuperação reativa **não pode** disparar contra este servidor (`403` ∉
   `{400, 401, 0}`), e ampliar a lista fixa seria pior do que o problema — o step `75`
   responde `403` legitimamente em todo caminho feliz (3.6).
7. `Optimization FAILED` e `Reproduction FAILED` saem com **exit code 0**, enquanto as
   falhas de validação saem com `1` (3.7).
8. A coincidência de baixa entropia declarada e aceita na spec de 13/08 se materializou
   (`Origin` ← `Access-Control-Allow-Origin`) e sustenta uma âncora do alvo principal
   (3.8).
9. `--steps-out` sobrescreve arquivo existente sem aviso (2.8).

**Candidatos a spec, em ordem de valor:**

| # | Assunto | Base |
|---|---|---|
| 1 | Separar **proveniência** de **necessidade** na fase 1/2 do `optimize` (âncora deixa de ser preservada por construção) e alinhar o README | 3.5, já previsto na §6 da spec de 13/08 |
| 2 | Comparação entre épocas (`original_responses` × `real_responses`) como caminho para o `Authorization` — mais casamento parcial | 3.2 |
| 3 | `origin_location` no caminho de cache hit (correção pequena, 71% das linhas de comentário) | 3.3 |
| 4 | Recuperabilidade por divergência do status de referência em vez de lista fixa de códigos | 3.6 |
| 5 | Exit code diferente de zero para `FAILED` em `optimize`/`replay` | 3.7 |

Nenhuma alteração de código foi feita nesta rodada — este documento é só medição e
diagnóstico. O workspace `arquivos-har/output` foi usado como está (recebeu as
anotações de replay normais das execuções acima); o cenário de credencial inválida
rodou sobre um clone descartável.

## Referência

Qualquer correção derivada deste relatório passa por [[spec-e-plano]] (spec → plano →
tasks) e segue [[guia-de-estilo]]. Os pontos 1, 4 e 6 da conclusão tocam diretamente o
princípio de genericidade descrito em [[arquitetura-e-fundamentos]].
