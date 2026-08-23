# Relatório — Reverificação das correções do `optimize` contra servidor real

**Data:** 23/08/2026
**Relatórios anteriores:** `docs/20260811-3 Teste do Otimizador contra Servidor Real/relatorio.md`
("R1") e `docs/20260817 Reteste do Otimizador contra Servidor Real/relatorio.md` ("R2",
que também tem `correcoes.md` — catálogo de 11 itens de correção derivados de R1). Este
documento reexecuta uma bateria focada contra o código de hoje e confere, item a item,
o catálogo de `correcoes.md`.

**Código sob teste:** `master` em `26917cb` (`Merge branch
'20260821-6-ancoras-tambem-testadas-para-remocao'`), o commit mais recente da árvore no
início desta sessão. Inclui todas as 11 etapas do catálogo de R2, a última delas
(`20260821-6`, item 4) mergeada horas depois da última atualização registrada em
`correcoes.md`.

**Workspace usado:** `arquivos-har/output` (fora do repositório, em
`../arquivos-har/`), regenerado por `run --mode main` sobre `arquivos-har/progressofit.har`
pelo próprio usuário minutos antes desta sessão (23/08/2026, ~11:27). 324 entries no HAR,
320 `.curl.sh` gerados (4 `ws://` pulados por `StepSkipEvaluator`), workspace **sem
nenhum `replay`/`optimize` anterior** — o mesmo HAR e a mesma contagem de entries já
usados na medição da spec de 21/08 que fundamentou o item 4.

**Servidores:** `http://127.0.0.1:8080` (front) + `http://localhost:8090` (API), ambos
no ar durante toda a bateria (`200` e `403` confirmados por `curl` direto antes de
começar).

**Suíte:** `uv run pytest --runslow` → **456 passed** em 28,35s (verde). Para
comparação: R2 mediu 356 em 30/08 — o crescimento reflete os testes novos das 5 etapas
de 21/08 mais a de hoje.

## 1. Metodologia

Não repeti a bateria inteira de R1/R2 (já refeita uma vez em R2). Foquei em confirmar,
com medição fresca contra o servidor real, cada uma das 11 linhas de `correcoes.md` —
na ordem em que o próprio arquivo as declara "✅ feito" — e em especial o item 4, cuja
metade final (`_reduce_anchors`) só foi mergeada às 18:53 de 21/08, depois da última
atualização do restante do catálogo. Usei o mesmo alvo de referência das duas rodadas
anteriores, `233` (`GET /api/weight/weekly/last-months/1`), que hoje é o mesmo step no
HAR atual (confirmado por inspeção do `.curl.sh`).

## 2. Testes executados

### 2.1 Estabilidade do schedule de âncoras

```bash
for i in 1 2 3; do
  uv run python -m har_reproducer.main replay --output ../arquivos-har/output \
    --mode smart --to 233 --config config.json
done
```

Schedule executado nas três chamadas: **`[153, 233]`**, idêntico nas três. Regressão do
bug 3.3 de R1 (já dada como corrigida em R2) permanece corrigida.

### 2.2 `optimize --to 233` — caminho feliz

```bash
uv run python -m har_reproducer.main optimize --output ../arquivos-har/output \
  --to 233 --config config.json --steps-out opt_233.txt
```

```
ReplayOptimizer: worst-case estimate ≈ 41896 requests (...)
[...]
Optimization SUCCESSFUL: 2 step(s) written to opt_233.txt
```

`opt_233.txt` → **`[0, 233]`**, **160 requisições**. Comparando com as duas rodadas
anteriores para o mesmo alvo lógico:

| Rodada | Resultado | Steps |
|---|---|---|
| R1 (11/08) | `[0, 1, 14, 23, 34, 75, 233]` | 7 |
| R2 (17/08) | `[0, 1, 14, 23, 34, 75, 233]` | 7 |
| **Hoje (23/08)** | **`[0, 233]`** | **2** |

Contagem de requisições reconstruída a partir do log (bate com o total observado):

| Fase | Requisições |
|---|---|
| Backbone (`0`…`152`) | 153 |
| Fase 2 — faixa `(153, 233)`, 1ª tentativa | 1 |
| Fase 2 — faixa `(0, 153)`, 1ª tentativa | 2 |
| `_reduce_anchors` — tenta remover a âncora `153` | 2 |
| Confirmação final `[0, 233]` | 2 |
| **Total** | **160** |

Nenhum candidato interior foi retido em nenhuma das duas faixas (mesmo padrão de
R1/R2), e a **âncora `153` foi removida** pela chamada nova a `_reduce_anchors`
(`replay_optimizer.py:60-73`) — é essa remoção que faz o resultado cair de 3 para 2
steps em relação à medição da própria spec de 21/08 (que tinha `[0, 153, 233]` porque
foi feita **antes** do item 4 estar completo).

### 2.3 Minimalidade — verificação com `replay --mode list`

| Conjunto testado | Resultado |
|---|---|
| `[233]` (alvo isolado, sem o piso `0`) | `Step 233 → 200`, `✓ SUCCESS` |
| `[0, 233]` (resultado do `optimize`) | `✓ SUCCESS` |

O alvo passa mesmo sem o piso `--from`. Isso **não é uma inconsistência** — o README
(§ `optimize`, revisado no item 1) já declara que o piso `--from` e o próprio `--to` são
mantidos por construção, como limites explícitos da busca, não por terem sido julgados
necessários. O ponto relevante é outro: a única **âncora real** do fluxo (`153`, origem
do JWT) foi testada e removida. Zero candidatos e zero âncoras não-explícitas sobraram
sem teste — o comportamento descrito no item 4 do catálogo está presente e correto.

### 2.4 Exit codes

| Cenário | Comando | Exit code |
|---|---|---|
| `Optimization SUCCESSFUL` | 2.2 | **0** |
| `Optimization FAILED` (critério de sucesso impossível, `--max-requests 2000`) | `optimize --to 233 --success-criteria '[{"type":"body_contains","expected":"XYZ_NUNCA_EXISTE"}]'` | **1** |
| `Reproduction FAILED` (`replay`, JWT adulterado — ver 2.5) | `replay --mode list --steps-file steps_233_only.txt` sobre clone adulterado | **1** |

Os três cenários do item 3 do catálogo (`optimize` sucesso/falha e `replay` falha) saem
com o código esperado. Confirmado também que `--steps-out` apontando para um arquivo já
existente agora avisa: `[AVISO] <path> já existe e será sobrescrito.` (item 7).

### 2.5 Credencial inválida — clone com JWT adulterado

Clone descartável (`cp -r ../arquivos-har/output <scratch>/ws_tamper`), com o JWT de
todos os 13 `.curl.sh` que carregam `Authorization` substituído por um literal inválido.

**`replay --mode list [233]`** sobre o clone:

```
Recovery successful for step 233. Retrying request...
Step 233 completed with status 403
Replay step results:
  Step 233: ✗ MISMATCH (403 vs original 200)
Replay Validation Result: ✗ FAILURE (steps diverged: 233)
Reproduction FAILED: Target state not reached.
```
Exit code **1**.

**`optimize --to 233 --max-requests 2000`** sobre o mesmo clone: 1067 linhas de log,
com `detected recoverable status in schedule — refreshing backbone before retrying`
disparando **3 vezes** (2 no `optimize`, contadas no `MAX_REACTIVE_REFRESHES`, mais o
disparo equivalente já visto no `replay` isolado), sempre em resposta aos steps
genuinamente adulterados (`233`, depois `224`, `226`–`229`, `231`–`233`) — **nunca** em
resposta ao `403` legítimo do step `75` (`GET /auth/check`), que aparece no meio do
backbone sem provocar nenhuma tentativa de recuperação. Termina em:

```
ReplayOptimizer: aborted — ReplayOptimizer: faixa (153, 233) falhou mesmo com todos os
candidatos incluídos.
Optimization FAILED: unable to find a passing subset (see abort reason above).
```
Exit code **1**.

Isso confirma três coisas do catálogo ao mesmo tempo:

- **Item 6** (recuperabilidade por divergência da referência) dispara de verdade contra
  este servidor — coisa que R2 §3.6/3.10 registrou como "inerte, nunca exercitada" sob a
  lista fixa `{400, 401, 0}`. Hoje dispara porque compara com o status de referência, e
  o `403` legítimo do step `75` não aciona nada porque bate com a referência.
- **Item 3** (exit code) se sustenta mesmo no caminho de recuperação: falha depois de
  tentar recuperar continua saindo com `1`.
- A ressalva que o próprio catálogo fazia ("cuidado ao 'corrigir' isso adicionando `403`
  à lista — toda chamada dispararia 2 recuperações desperdiçando ~150 requisições no
  caminho feliz") não se aplica à implementação real: a solução adotada foi comparação
  contra a referência, não a lista fixa, e o caminho feliz (2.2) não disparou nenhuma
  recuperação.

### 2.6 Proveniência do comentário (`origin_location` no cache hit)

```python
def _origin_status(self, token: DynamicToken) -> Optional[OriginStatusPhrase]:
    extractor: Optional[Extractor] = self.session_store.state.registry.get(token.token_id)
    assert extractor is not None
    if extractor.agent_type == AgentType.LITERAL:
        return OriginStatusPhrase.UNDETERMINED
    ...
```
(`curl_generator.py:83-90`, hoje). A leitura passou a ser feita sobre o `Extractor`
persistido no registry (via `agent_type`), não mais sobre o campo `origin_location` do
candidato — a "primeira opção" que `correcoes.md` item 2 apontava como a que "elimina a
classe do problema", não a correção mínima.

Medição sobre os 320 `.curl.sh` do workspace de hoje:

```
$ grep -h "undetermined" curls/*.curl.sh | wc -l
0
```

**Zero** ocorrências — não há mais nenhuma linha `origin location undetermined`
associada a um extrator determinístico no workspace inteiro (em R2 eram 540 de 757,
71%). Não dá para separar quanto disso é o item 2 e quanto é o item 9/11 (que fez a
maioria das dependências virar `[Static N]`, categoria que nem passa por
`_origin_status`) — mas o mecanismo do item 2 está presente no código e o resultado
observável (nenhuma linha falsa) é consistente com ele.

### 2.7 Proveniência × necessidade: quanto sobrou de fato

```
$ grep -l "^# \[Token" curls/*.curl.sh | wc -l
13
$ grep -h "^# \[Token" curls/*.curl.sh | grep -oP "step \K[0-9]+" | sort -u
0153
$ ls extractors/*.meta.json | wc -l
1
$ cat extractors/extract_9076b011....meta.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['agent_type'], d['verified'], d['origin_step'])"
JSONPathAgent True 153
```

**Um único extrator persistido no workspace inteiro**, apontando para um único step de
origem (`153`, o login) — contra 57 extratores em R1 e 117 em R2. É a consequência
combinada dos itens 9 (literal não vira âncora), 10 (mojibake) e 11 (porta de admissão):
sobrou exatamente a dependência que é genuinamente dinâmica (o JWT muda a cada login),
e nada mais. O `[Static 3] url←0059; header:Content-Type←0023; header:Origin←0075` que
aparece em `req_0233.curl.sh` confirma que a coincidência de baixa entropia do item 8
(`Origin` ← `Access-Control-Allow-Origin`, eco CORS) continua classificada como
`Static`, não como `Token` — não voltou a virar âncora.

### 2.8 `real_responses/` — mojibake (item 10)

Reverifiquei os 4 steps que R2/`correcoes.md` item 10 citava como corrigidos no HAR
atual (`13, 14, 76, 159` no HAR anterior — os índices mudaram de numeração no HAR de
17/08, mas o conteúdo é o mesmo tipo de asset CSS/imagem):

| Response | Tamanho | `U+FFFD` |
|---|---|---|
| CSS (`res_0014.json`) | 1272 chars | 0 |
| CSS (`res_0076.json`) | 102025 chars | 0 |
| CSS (`res_0159.json`) | 2155 chars | 0 |
| JPEG (`res_0013.json`) | 24846 chars | 38,76% |

As três respostas textuais (CSS) estão limpas — confirma o "0" que `correcoes.md`
já reportava para este HAR. A taxa alta no JPEG não é o defeito do item 10: é uma
imagem binária decodificada como texto, presente em ambas as épocas por igual, não uma
regressão introduzida pela captura/persistência do corpo.

## 3. Conclusão — status de `correcoes.md`, item a item

| # | Correção | Status em `correcoes.md` (21/08) | Reverificado hoje contra servidor real |
|---|---|---|---|
| 1 | README: promessa de "mínimo local" | ✅ feito | **Confirmado.** Texto atual bate com o comportamento observado em 2.3. |
| 2 | `origin_location` no cache hit | ✅ feito | **Confirmado, e mais completo que o registrado.** Zero linhas `undetermined` falsas no workspace (2.6) — a fonte de verdade agora é o `Extractor.agent_type` do registry, não o campo do candidato. |
| 3 | Exit code ≠ 0 em `FAILED` | ✅ feito | **Confirmado** nos três cenários (`optimize` sucesso/falha, `replay` falha), inclusive no caminho com recuperação reativa (2.4, 2.5). |
| 4 | Âncora testada para remoção (proveniência × necessidade) | núcleo ✅, fase 2 do `optimize` "continua aberta" | **Fechado.** `_reduce_anchors` (mergeado 21/08 à noite, depois da última atualização do catálogo) testou e removeu a única âncora real (`153`) do alvo principal — `[0,153,233]`→`[0,233]` (2.2). Catálogo precisa de atualização: não está mais aberto. |
| 5 | `Authorization` congelado | ✅ dividido em 9+10+11, todos feitos | **Confirmado.** `Authorization` resolve via `JSONPathAgent` genuíno sobre a resposta do login (step `153`), `verified=true`, não é mais literal congelado (2.7). |
| 6 | Recuperabilidade por divergência, não lista fixa | ✅ feito | **Confirmado e exercitado pela primeira vez contra servidor real** (2.5) — nunca tinha disparado em R1/R2. Não houve falso positivo no `403` legítimo do step `75`. |
| 7 | `--steps-out` avisa antes de sobrescrever | ✅ feito | **Confirmado** (2.4). |
| 8 | Coincidência de baixa entropia (`Origin`↔CORS) | ✅ resolvido pelo item 11 | **Confirmado.** Aparece como `[Static 3]`, não como âncora (2.7). |
| 9 | Extrator literal não deve virar âncora | ✅ feito | **Confirmado.** 1 extrator persistido em todo o workspace; todo o resto é `Static`/`Unresolved` (2.7). |
| 10 | Mojibake em `real_responses/` | ✅ feito | **Confirmado** nas 3 respostas textuais reverificadas (2.8). |
| 11 | Porta de admissão + casamento por fragmento | ✅ feito | **Confirmado** por 5, 8 e 9 combinados. |

**Nenhuma regressão encontrada.** Todos os 11 itens do catálogo se sustentam sob medição
fresca contra o servidor real, incluindo o item 4 — que o próprio `correcoes.md`, na sua
última revisão, ainda registrava como parcialmente aberto (a fase 2 do `optimize`), e que
foi fechado pelo commit mais recente da árvore antes desta sessão. Recomendo apenas
atualizar a linha do item 4 em `correcoes.md` de "fase 2 continua aberta" para "✅ feito
(21/08)", já que a medição desta sessão mostra a lacuna fechada.

Nenhuma alteração de código foi feita nesta sessão — este documento é só reverificação.
O workspace `arquivos-har/output` foi usado como está (recebeu as anotações de replay
normais das execuções de 2.1–2.3); o cenário de credencial inválida (2.5) rodou sobre um
clone descartável em `<scratchpad>/ws_tamper`, sem tocar o workspace real.

## Referência

Qualquer correção derivada deste relatório passa por [[spec-e-plano]] (spec → plano →
tasks) e segue [[guia-de-estilo]]. A confirmação do item 6 (recuperabilidade por
divergência) reforça o princípio de genericidade de [[arquitetura-e-fundamentos]]
citado na etapa que o implementou.
