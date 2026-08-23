# Correções necessárias — em ordem de prioridade

> Derivado de `relatorio.md` (mesma pasta, 17/08/2026). Cada item aponta a seção do
> relatório que o sustenta, o código afetado e o escopo sugerido. Nenhum deles foi
> implementado — cada um vira uma spec própria via [[spec-e-plano]] quando for a hora.

**Critério de ordenação:** primeiro o que corrige uma afirmação falsa do produto a
custo baixo (itens 1–3), depois as duas mudanças estruturais que decidem se o
`optimize` é confiável de verdade (4–5), depois o resto. Dentro do mesmo nível, ganha
quem tem prazo real.

| # | Correção | Severidade | Custo | Prazo | Status |
|---|---|---|---|---|---|
| 1 | README: a promessa de "mínimo local" do `optimize` está errada | Alta | Trivial | — | ✅ feito (21/08) |
| 2 | `origin_location` não é setada no cache hit → 71% dos comentários de proveniência mentem | Média | Pequeno | — | ✅ feito (21/08) — `CurlGenerator` passou a ler `Extractor.agent_type` do registry em vez de `DynamicToken.origin_location` |
| 3 | `Optimization FAILED` / `Reproduction FAILED` saem com exit code 0 | Média | Pequeno | — | ✅ feito (21/08) |
| 4 | `optimize` nunca testa as âncoras — proveniência tratada como necessidade | **Alta** | Grande | — | ✅ feito (21/08) — fase 2 fechada por `docs/20260821-6 Âncoras Também Testadas para Remoção/`; reverificado contra servidor real em 23/08 |
| 5 | `Authorization` congelado: comparação entre épocas + casamento parcial | **Alta** | Grande | ~~28/12/2026~~ 13/02/2027 (JWT atual) | ✅ dividido em 9+10+11, todos feitos |
| 6 | Recuperabilidade por lista fixa de status (`{400,401,0}`) em vez de divergência da referência | Média | Médio | — | ✅ feito (21/08) — não é a redescoberta reativa: era só o gatilho de recuperação nos três lugares que já reexecutam extrator existente. A redescoberta reativa (criar extrator novo quando isso não basta) continua sem spec própria. |
| 7 | `--steps-out` sobrescreve arquivo existente sem aviso | Baixa | Trivial | — | ✅ feito (21/08) |
| 8 | Coincidência de baixa entropia no `origin_key` (`Origin` ← `Access-Control-Allow-Origin`) | Baixa | — | **não agir isoladamente** | ✅ resolvido pelo item 11 (a porta rejeita o token, ele nunca vira extrator) |
| 9 | Extrator literal congelado não deveria virar âncora | **Alta** | Médio | — | ✅ feito (20/08) |
| 10 | `real_responses/` guarda corpo comprimido como mojibake | Média | Pequeno | — | ✅ feito (21/08) |
| 11 | Porta de admissão + casamento por fragmento (o item 5 propriamente) | **Alta** | Grande | — | ✅ feito (21/08) |

---

## 1. README: corrigir a promessa de minimalidade do `optimize`

**Evidência:** relatório §3.5.

O README afirma que o resultado é "um mínimo local (nenhum passo isolado pode ser
removido)". Medido contra o servidor real: `[233]` sozinho passa com `200`, `[227]`
sozinho passa, `[83]` sozinho devolve `304` — e o `optimize` devolve 7, 7 e 4 steps
respectivamente. **Qualquer** passo isolado do resultado pode ser removido nos três
alvos testados.

**Onde:** `README.md`, seção do comando `optimize` (parágrafo do ⚠️).

**Escopo:** trocar a frase por uma descrição fiel — mínimo local **dentro das faixas
entre âncoras**; as âncoras entram por construção como garantia de proveniência (o
valor vem de resposta obtida agora, não de resposta congelada em `real_responses/`) e
nunca são testadas para remoção.

**Por que é o primeiro:** é a única correção que fecha a distância entre promessa e
comportamento hoje, sem depender do item 4. Enquanto o item 4 não existir, o README é
o único lugar onde alguém pode descobrir que o número devolvido não significa o que
parece.

---

## 2. `origin_location` no caminho de cache hit

**Evidência:** relatório §3.3. **865** linhas de dependência nos `.curl.sh`, **757**
com `origin location undetermined — using literal captured value`, das quais **540
(71%) referenciam um extrator determinístico** (`HeaderAgent`/`CSSAgent`/`RegexAgent`).

**Onde:**
- `tracking/candidate_resolver.py:61-63` — o retorno antecipado quando o slot já está
  em `session_store.state.registry` nunca seta `candidate.origin_location`.
- `tracking/candidate_resolver.py:139` — único ponto que preenche o campo hoje
  (`_generate_new_extractor`).
- `reproduction/curl_generator.py:73-79` — `_origin_status` decide o texto olhando só
  esse campo.

**Escopo sugerido:** derivar o status de proveniência do `Extractor` persistido
(que já carrega `agent_type`) em vez do campo do candidato, ou preencher
`origin_location` também no cache hit. A primeira opção elimina a classe do problema;
a segunda é menor.

⚠️ Regenerar os golden (`HAR_REPRODUCER_UPDATE_GOLDEN=1 uv run pytest --runslow`) —
o texto do comentário muda em praticamente todo fixture.

**Por que aqui:** é cosmético para a execução (o `{{extractor:...}}` sempre apontou
para o extrator certo), mas ficou pior desde a etapa de 13/08: a linha falsa agora
convive com a linha `[Unresolved N]`, que é auditoria verdadeira, no mesmo arquivo.
Custo pequeno, benefício direto em qualquer investigação futura de proveniência —
inclusive nas dos itens 4 e 5.

---

## 3. Exit code ≠ 0 quando o comando falha

**Evidência:** relatório §3.7.

| Cenário | Exit code hoje |
|---|---|
| `Optimization SUCCESSFUL` | 0 |
| `Optimization FAILED` | **0** |
| `Reproduction FAILED` (`run`/`replay`) | **0** |
| `ValueError` de validação | 1 |

**Onde:** `main.py:17-18` (`args.func(args)`, sem tradução de resultado em código de
saída), `cli/cli_handlers.py:190-196` (`_print_optimize_result`) e
`cli/cli_handlers.py:97-101` (`_print_result`).

**Escopo sugerido:** os handlers passam a devolver o resultado e `main()` traduz para
`sys.exit(0|1)`. Decisão a tomar na spec: se `replay` com divergência é falha de
processo (exit 1) ou resultado legítimo de diagnóstico (exit 0) — hoje os dois
comandos são inconsistentes com as próprias validações, que já saem com 1.

**Impacto colateral:** os golden de `stdout` não mudam, mas a suíte que invoca `main()`
precisa passar a esperar `SystemExit`.

---

## 4. `optimize`: separar proveniência de necessidade — ✅ feito, 21/08/2026

Fase 2 (teste de remoção das âncoras) implementada em `docs/20260821-6 Âncoras Também
Testadas para Remoção/` (spec + 2 tasks: `ReplayOptimizer._reduce_anchors` + correção do
parágrafo ⚠️ do README, mergeado em `master`). Reverificado contra servidor real em
23/08/2026 (`docs/20260823 Reverificação das Correções do Otimizador/relatorio.md`):
para o alvo `233`, `optimize` passou a devolver `[0, 233]` em vez de `[0, 153, 233]` — a
única âncora real do fluxo (`153`, origem do JWT) foi testada e removida.

**Evidência original:** relatório §3.5 e §3.8. Já previsto na spec de 13/08, §6
("classificação da aresta em proveniência × necessidade …, com proveniência **nunca**
virando âncora de `compute_smart_schedule`").

**O problema:** a fase 2 (`optimization/replay_optimizer.py:107-143`) só tenta remover
os steps **entre** âncoras (`_candidates_between`, `:169-170`). As âncoras entram no
resultado por construção (`:53`) e nunca são submetidas a nenhuma tentativa de remoção.
Uma âncora removida não quebra nada porque `ReplayTokenResolver._resolve_one`
(`replay/replay_token_resolver.py:56-61`) lê a resposta de referência armazenada quando
a origem não está no schedule — ou seja, o token resolve a partir de dado congelado em
disco.

**Medição que dá o tamanho do problema:** neste fluxo, **100% das âncoras são
proveniência pura e nenhuma é necessidade** — 6 dos 7 steps do resultado do alvo
principal são removíveis sem efeito observável. §3.8 mostra ainda uma âncora
(`75`) sustentada por uma aresta semanticamente invertida (o header de requisição
`Origin` extraído do `Access-Control-Allow-Origin` da resposta, que é o eco CORS do
próprio valor enviado).

**Escopo sugerido para a spec:** classificar cada aresta como proveniência ou
necessidade comparando as duas épocas (`original_responses` × `real_responses`);
proveniência não vira âncora de `compute_smart_schedule`; o resultado do `optimize`
passa a declarar qual garantia cada step carrega, em vez de devolver uma lista plana.

**Depende de:** nada tecnicamente, mas se beneficia do item 2 (proveniência confiável
no `.curl.sh`). **Entrega o item 1 de verdade** — o item 1 é o remendo textual até
esta correção existir.

---

## 5. `Authorization`: comparação entre épocas + casamento parcial

**Evidência:** relatório §3.2. **Prazo real: 28/12/2026** — é quando expira o JWT
congelado do HAR (`exp: 1798419171`). Depois disso, todo alvo autenticado deste fluxo
(`224`, `227`–`233`, `237`) falha com `403`, e nem `replay --mode smart` nem
`optimize` conseguem apontar a causa: a faixa que falha contém o login (`154`), e
incluí-lo **não resolve**, porque nenhum `.curl.sh` consome a resposta dele.

**Correção do diagnóstico antigo:** casamento parcial (tratar o prefixo `"Bearer "`)
sozinho **não** resolve. Medido nos dois modos:

- `--mode dry`: o HAR não gravou o corpo da resposta do login (`content` sem `text`;
  `original_responses/res_0154.json` com `body: ""`). Já reportado pelo aviso novo
  (`fs_io/har_parser.py:14`, impresso em `engines/engine.py:59-64`): 13 de 238 entries.
- `--mode main`: o corpo existe em `real_responses/res_0154.json`, mas traz um JWT de
  **outra época** (`exp` 13/02/2027) que o valor procurado, vindo do HAR (`exp`
  28/12/2026) — 121 caracteres de prefixo em comum, divergindo a partir do `exp`.
  Igualdade exata, com ou sem prefixo, não casa.

**Escopo sugerido para a spec:** casamento por fragmento com âncora expandida, mais a
comparação entre as duas épocas — exatamente o conjunto já decidido e registrado na
spec de 13/08, §6 (incluindo os desempates e o que foi descartado com motivo).

**Relação com o item 4:** a spec de 13/08 amarra os dois assuntos no mesmo parágrafo.
Podem virar uma etapa só ou duas em sequência — decisão de planejamento, não de
arquitetura. Se forem duas, esta vem depois, porque a classificação proveniência ×
necessidade é o vocabulário que esta usa.

---

## 6. Recuperabilidade: divergência da referência em vez de lista fixa de status — ✅ feito, 21/08/2026

Implementado em `docs/20260821-3 Recuperação por Divergência da Referência/` (spec + 5
tasks, mergeado em `master`). Os três lugares (`Engine.handle_recovery`,
`ReplayRunner._run_step`, `ReplayOptimizer._needs_reactive_refresh`) decidem recuperação
via `ReplayResultComparator.needs_recovery` — método novo, não uma inversão do
`matches_original` já existente (a primeira tentativa de reaproveitar `matches_original`
diretamente foi desenhada, verificada contra os testes reais, e descartada antes da spec
ser aprovada: "sem referência" tinha que significar "não sei", não "diverge", senão
qualquer step sem `original_responses/` gravado dispararia recuperação por engano).

⚠️ **Isto não é a redescoberta reativa.** Esta correção só troca o **gatilho** de quando
reexecutar extratores que já existem (`token_resolver.resolve_all(force=True)` em `run`,
o mesmo mecanismo de sempre em `replay`/`optimize`). Criar um extrator **novo** quando o
refresh não resolve — porque a porta do item 11 marcou o candidato como `"Static"` e
nenhum extrator jamais existiu — continua sem spec própria, é maior, e foi deliberadamente
separado desta etapa.

**Evidência:** relatório §3.6.

`ReplayOptimizer.RECOVERABLE_STATUS_CODES` (`optimization/replay_optimizer.py:19`) é
`StepRetryPolicy.RECOVERABLE_STATUS_CODES | {0}` = `{400, 401, 0}`
(`reproduction/step_retry_policy.py:8`). A API deste fluxo sinaliza falha de
autenticação com **`403`** — verificado com `curl` direto: token ausente, inválido e
adulterado, todos `403`. Com o JWT adulterado, o `optimize` disparou 232 requisições,
viu `403` em 10 steps e **nunca** entrou em recuperação reativa
(`replay_optimizer.py:78-89`, caminho que segue sem nunca ter rodado contra servidor
real).

⚠️ **Não resolver adicionando `403` à lista.** O step `75` (`GET /auth/check`) responde
`403` **legitimamente** em toda execução bem-sucedida (está assim no HAR, e o replay o
marca `✓ matched (403 vs original 403)`). Com `403` na lista, toda chamada de
`_execute` deste fluxo dispararia as 2 recuperações, cada uma reexecutando o backbone
de 76 requisições — ~150 requisições desperdiçadas no caminho feliz.

**Escopo sugerido:** decidir recuperabilidade comparando o status obtido com o status
de referência daquele step (comparação que `ReplayResultComparator` já faz), em vez de
uma lista fixa de códigos. É também mais coerente com o princípio de genericidade de
[[arquitetura-e-fundamentos]]: uma lista fixa de códigos é conhecimento de protocolo
hardcoded; a divergência contra a referência é descoberta a partir do próprio dado.

**Por que não é mais alto:** o caminho está inerte, não errado — nenhum teste desta
bateria falhou por causa dele. Vira urgente se/quando o item 5 fizer o fluxo
autenticado depender de sessão fresca.

---

## 7. `--steps-out`: não sobrescrever silenciosamente

**Evidência:** relatório §2.8. Rodar `optimize` apontando `--steps-out` para um arquivo
que já existe sobrescreve sem aviso nem backup
(`optimization/replay_optimizer.py:59`, `destination.write_text(...)`).

**Escopo sugerido:** avisar no stdout quando o destino já existe (mínimo), ou recusar
sem uma flag explícita (mais rígido). Decisão de produto, não de arquitetura.

---

## 8. Coincidência de baixa entropia no `origin_key` — **não agir isoladamente**

**Evidência:** relatório §3.8. Risco declarado e aceito na spec de 13/08 (§7, item 6:
a regra de igualdade exata "não evita coincidência de baixa entropia"). Está
materializado: `-H 'Origin: {{extractor:5809b41a…}}'` em `req_0233.curl.sh`, resolvido
por um `HeaderAgent` com `target = 'Access-Control-Allow-Origin'` sobre a resposta do
step `75`.

Funcionalmente correto (o valor extraído é o certo, o extrator é determinístico), mas
cria uma aresta invertida que vira âncora. **A correção certa não é apertar a regra do
`origin_key`** — é o item 4 deixar de tratar essa aresta como necessidade. Registrado
aqui para não ser "corrigido" por engano numa spec própria.

---

## Não são correções — dívida de cobertura

Registrado em `relatorio.md` §3.10, repetido aqui para não se perder:

- **Recuperação reativa** — inexercitável contra este servidor (item 6).
- **Abort na confirmação final** (`replay_optimizer.py:54-55`) — nunca observado.
- **Retenção genuína de candidato na fase 2** (`replay_optimizer.py:138-143`) — nunca
  reteve nada, e neste HAR é estrutural: o único candidato plausível a efeito colateral
  necessário é o login, que ninguém consome (item 5).
- **`skip_rules.methods`** — o HAR não tem `OPTIONS`; só a variante por scheme (`ws://`)
  foi coberta, e essa passou (`relatorio.md` §3.9).


---

# Adendo de 20/08/2026 — o que a investigação da porta de admissão descobriu

> Esta seção foi acrescentada depois de uma investigação de 20/08/2026 que projetou a
> correção do item 5, submeteu o desenho a duas revisões adversariais de contexto limpo, e
> mediu tudo sobre **duas** gravações: `arquivos-har/progressofit.har` (324 entries) e
> `progressofit(antigo).har` (238 entries), com workspaces gerados contra o servidor real.
> O resultado foi que o item 5 se divide em três etapas, e que a primeira delas não é
> sobre o `Authorization`.

## 5.1 — Correções aos números do item 5 acima

Reverificado em 20/08/2026, o item 5 tem três afirmações que não valem mais:

- **O prazo de 28/12/2026 é de outro HAR.** O HAR foi regravado em 17/08/2026 e o JWT
  congelado agora tem `exp: 1802564089` — **13/02/2027**.
- **"Todo alvo autenticado falha com 403" é falso hoje.** Medido contra o servidor no ar:
  `replay --mode list [23, 75, 153, 224]` devolve `200` no step 224, e
  `GET /auth/check` com o JWT congelado do `.curl.sh` devolve `200`. O fluxo **não está
  quebrado**; ele quebra quando o token expirar. A razão da etapa é o prazo, não uma falha
  atual — e o critério de aceite dela não pode ser "224 passa a dar 200", porque já dá.
- **O login passou a ter corpo gravado.** No HAR de 17/08 a resposta do step 153 traz
  `{"token":"eyJ…"}` (185 bytes). O diagnóstico de `--mode dry` do item 5 vale só para o
  HAR anterior, onde o login é o step 154 e o corpo tem 0 bytes.

## 9. Extrator literal congelado não deveria virar âncora — **em andamento**

Descoberto ao medir o item 5, e é maior do que ele. Quando o projeto não aprende a
recalcular um valor, ele cria um extrator `AgentType.LITERAL`/`LITERAL_FALLBACK` cujo
código é `return '<literal>'`, e emite no `.curl.sh` uma linha de dependência com o sufixo
`origin location undetermined — using literal captured value`.
`ReplayRunner._expand_pending` lê a cláusula e ignora o sufixo, então o step de origem vira
âncora e é executado — embora o extrator devolva o mesmo literal com ou sem ele.

Medido: **89% a 96% das linhas de dependência** dos três workspaces examinados são desse
tipo. Corrigir derruba o replay de um alvo típico de 2,38 → 1,03 requisições no HAR atual e
de 6,48 → 1,32 no anterior; as âncoras caem de 8 → 5 e de 69 → 65, e os curls que arrastam
âncora caem de 219/320 → 7/320 e de 232/235 → 68/235.

⚠️ Isso reordena a prioridade do item 4: **a maior parte do custo que o item 4 atribui a
"proveniência tratada como necessidade" é esta linha**, e resolver aqui não exige nenhuma
mudança de arquitetura, nem de formato de artefato, nem regerar workspace.

Etapa própria, em andamento: `docs/20260820 Extrator Literal Não Vira Âncora/`.

## 10. `real_responses/` guarda corpo comprimido como mojibake

Defeito de persistência descoberto ao investigar falsos positivos. Em algumas respostas, a
época da execução grava o corpo **ainda comprimido** (`content-encoding: br`/`gzip`),
persistido como texto com 39% a 44% de U+FFFD, enquanto a época do HAR tem o mesmo corpo
decodificado. Medido no workspace do HAR anterior: 4 respostas legíveis numa época e
ilegíveis na outra (steps 13, 14, 76, 159); no workspace do HAR atual, 0.

Consequência: qualquer comparação entre as duas épocas lê "esta substring desapareceu" e
conclui "o valor é dinâmico". Os steps 13, 14, 76 e 159 são exatamente as origens dos
falsos positivos que o desenho da porta de admissão produziu naquela gravação. **É
pré-requisito do item 11**: a porta não é confiável enquanto isso existir.

## 11. Porta de admissão + casamento por fragmento (o item 5 propriamente) — ✅ feito, 21/08/2026

O que sobrava do item 5 depois de 9 e 10. Implementado em
`docs/20260821-2 Porta de Admissão por Mudança entre Épocas/` (spec + 12 tasks, mergeado em
`master`). ⚠️ Duas decisões do meio da investigação — que este item descrevia numa versão
anterior deste documento — foram desenhadas, medidas e **descartadas antes da versão
final**: "evidência posicional" (generalizar a busca de container por igualdade para
contenção) e "admissão por dois lados" para requisição condicional. As duas reabriam uma
classe de coincidência sem limiar limpo que as separasse; o registro de por que caíram está
em `docs/20260820 Investigação da Porta de Admissão/medições.md`. O que foi de fato
implementado:

- **Casamento por fragmento** é o único mecanismo que acha o `Authorization`: o request
  manda `Bearer <jwt>` e a resposta do login traz só `<jwt>`, então o fragmento cobre 173
  de 180 caracteres (96%). Confirmado com fixture dedicada (`tests/fixtures/auth_flow.har`,
  cenário golden `run_auth_flow`): o `.curl.sh` gerado tem
  `Authorization: Bearer {{extractor:...}}`, não mais o literal.
- **Descoberta e verificação sempre na época do HAR.** Na época da execução o fragmento
  seria o prefixo comum aos dois JWT (123 de 180, 68%) — prefixo fresco com assinatura
  velha, que nenhum servidor aceita. Decisão que sobreviveu intacta a toda a investigação.
- **Critérios de admissão do fragmento, na versão final:** cobertura mínima (50%, que é
  também o limite de poda da busca) e piso absoluto (4 caracteres) — **aplicados também ao
  casamento inteiro**, e vocabulário de endereços do próprio fluxo, condicionado à ordem de
  aparição (para não vetar subdomínio dinâmico por engano). A ubiquidade do lado do
  fragmento foi medida e cortada — não rejeita nada nas duas gravações disponíveis.
- **A porta compara pelo blob de sempre** (o texto casado aparece na resposta de execução?)
  — a generalização para container por igualdade/contenção foi medida como desnecessária
  (o piso já mata o único falso positivo conhecido) e arriscada (reabre coincidência).
- **Requisição condicional (`If-None-Match`/`If-Modified-Since`) fica sem tratamento
  especial** — decisão explícita, não lacuna: rebaixa a literal como qualquer valor
  estático. É uma regressão medida (84 extratores da gravação anterior, que funcionam hoje
  via `HeaderAgent`) e aceita, porque nenhum discriminador testado (ubiquidade do valor,
  reuso do valor entre candidatos) separou de forma limpa "header de protocolo constante"
  de "validador genuíno" nesta escala de amostra. Custo aceito: +0,30 requisição por
  replay no primeiro deploy. Fica para a redescoberta reativa (item 6 do topo desta lista).
- **A porta não se aplica em `--mode dry`** — `execution_corpus: Optional[ResponseCorpus]`
  chega como `None` nesse modo, sinal explícito, não "o diretório está vazio".
- **Consequências obrigatórias, implementadas:** `_accept_persisted_slot` parou de semear
  o token; `TokenResolver` cai para `captured_value` quando a extração falha, só quando o
  token ainda não tem valor (nunca sobrescreve na recuperação de 401/403).
- **Candidato dispensado pela porta não vira âncora**: novo status `"Static"` em
  `DynamicToken`, categoria `[Static N]` no `.curl.sh`, que não casa com o padrão que
  `compute_smart_schedule` usa para expandir o schedule.

⚠️ **A limitação do HAR sem corpo de login continua valendo, sem solução — é dado, não
código**: no HAR anterior, o login não tem corpo de resposta gravado, então aquela
gravação nunca poderia validar este objetivo, com ou sem porta. Não é algo a corrigir.

Dependeu de 9 e 10. **Absorve o item 8** (o token do `Origin`, coincidência com
`Access-Control-Allow-Origin`, agora corretamente rejeitado pela porta — casamento inteiro,
idêntico entre as épocas, `status="Static"`, nunca virou extrator) **e o núcleo do item 4**
em `--mode main`/`replay`/`optimize` (toda aresta que sobrevive à porta é, por construção,
necessidade — o valor mudou; ⚠️ não vale em `--mode dry`, onde a porta não se aplica e
proveniência ainda pode virar aresta sem checagem). **Não absorve o item 2** — verificado
no código atual: `_accept_persisted_slot` (cache hit de slot) continua sem popular
`candidate.origin_location`, então um extrator determinístico reaproveitado entre steps
ainda pode aparecer com a frase `origin location undetermined` na linha de dependência.
Item 2 continua em aberto, sem relação com esta etapa.
