# Relatório — Teste do comando `optimize` contra servidor real

**Data:** 11/08/2026
**Feature testada:** `optimize` (introduzida em `docs/20260811-2 Otimizador de Sequência Mínima de Replay`, commits `T01`–`T10`, merge já em `master`).
**Workspace usado:** gerado por

```bash
uv run python -m har_reproducer.main run \
  --har /home/vinicius/Documentos/Trabalho/har-flow-reproducer/arquivos-har/progressofit.har \
  --config /home/vinicius/Documentos/Trabalho/har-flow-reproducer/har-reproducer-project/config.json \
  --mode main
```

Fluxo real de um app de acompanhamento de peso/treino ("ProgressoFit"), servido em
`http://127.0.0.1:8080` (front-end estático) + `http://localhost:8090` (API), ambos
localhost — os testes abaixo dispararam requisições reais contra os dois, conforme
autorizado. Workspace resultante: 235 steps (`req_0000`…`req_0234`), 238 respostas
reais capturadas em `real_responses/`.

## 1. Metodologia

Antes de rodar `optimize`, mapeei o fluxo com `replay --mode smart` para dois
propósitos: (a) confirmar que o workspace estava íntegro (`curls/` + respostas de
referência populadas) e (b) ter um baseline do schedule de âncoras que `optimize`
usaria como ponto de partida, para poder avaliar se o resultado fazia sentido.

Identifiquei as únicas chamadas de API relevantes do fluxo (`localhost:8090`):

| Step | Método | Endpoint |
|---|---|---|
| 75, 151, 224 | GET | `/auth/check` (todas com `403` no HAR original) |
| **154** | **POST** | **`/auth/login`** (único `POST` de todo o fluxo) |
| 227 | GET | `/api/user` |
| 228–233, 237 | GET | `/api/statistics/*`, `/api/goals/*`, `/api/weight/*` |

`154` (login) era o candidato natural para um teste de "passo de efeito colateral
sem token consumido depois" — exatamente o cenário que o `optimize` foi desenhado
para detectar (ver README, seção do comando).

## 2. Testes executados

### 2.1 Caminho feliz — alvo `233` (`/api/weight/weekly/last-months/1`)

```bash
uv run python -m har_reproducer.main optimize \
  --output arquivos-har/output --to 233 --config config.json
```

Schedule de âncoras (`replay --mode smart --to 233`, calculado antes de qualquer
mutação de estado — ver seção 3.3): `[0, 1, 14, 23, 34, 75, 233]`.

Resultado: **`Optimization SUCCESSFUL: 7 step(s)`**, arquivo `.txt` com exatamente
essa lista de âncoras — nenhum step extra fora do schedule precisou ser mantido
(`kept = []` em todas as 6 faixas testadas entre âncoras).

### 2.2 Caminho feliz — alvo `227` (`/api/user`)

Mesmo padrão: âncoras `[0, 1, 14, 23, 34, 75, 227]`, resultado `6 step(s)` — o
schedule de âncoras já vinha minimal (novamente `kept = []`).

### 2.3 `--success-criteria` estrito, sobrescrevendo o `config.json`

```bash
uv run python -m har_reproducer.main optimize \
  --output arquivos-har/output --to 233 \
  --success-criteria '[{"type":"status_code","expected":200},{"type":"body_contains","expected":"weekOfYear"}]'
```

Confirma que a flag realmente sobrescreve o critério (o `config.json` do projeto só
tem `status_code`) e que a fase de confirmação final (`ReplayOptimizer._confirm`)
valida o corpo de fato, não só o status — o body da resposta real de `233` contém
`weekOfYear` (campo do JSON de estatísticas semanais), então o critério passou.
Resultado: `6 step(s)` (ver seção 3.3 sobre por que esse número difere do 2.1).

### 2.4 Round-trip com `replay --mode list`

```bash
uv run python -m har_reproducer.main replay \
  --output arquivos-har/output --mode list --steps-file <optimized.txt> --config config.json
```

O `.txt` gerado em 2.3 foi consumido diretamente por `replay --mode list` e reproduziu
`✓ SUCCESS` — confirma que o formato de saída (`optimized_steps_file`, um índice por
linha) é exatamente o que `replay --mode list --steps-file` espera, sem transformação
manual.

### 2.5 Erros — validação antes de qualquer rede

| Cenário | Comando | Resultado |
|---|---|---|
| Sem `success_criteria` (nem `--config`, nem `--success-criteria`) | `optimize --output ... --to 233` | `ValueError: ... success_criteria vazio — informe --success-criteria ou configure success_criteria no config.json` — nenhuma requisição disparada antes do erro. |
| `--from` fora do workspace | `optimize --output ... --to 233 --from 999999 --config config.json` | `ValueError: ReplayOptimizer: step(s) [999999] não existem no workspace ...` — mesma garantia, falha antes de qualquer rede. |

Ambos propagam como exceção não tratada (traceback completo, exit code ≠ 0) — comportamento
consistente com a regra do guia de estilo ("fora das bordas de I/O, não engolir
exceção") e com os testes já existentes em `tests/test_cli_optimize.py`.

### 2.6 Abort por `--max-requests`

```bash
uv run python -m har_reproducer.main optimize \
  --output arquivos-har/output --to 233 --config config.json --max-requests 5
```

A fase 1 (execução da "backbone", 75 requisições de `0` a `74`) já ultrapassa o teto
de 5 antes de a busca sequer começar a fase 2. Resultado:
`ValueError: ReplayOptimizer: teto de requisições atingido (76/5) — abortando a busca.`
— nenhum `.txt` escrito. Confirma que o teto é respeitado mesmo dentro de uma única
fase, e que a estimativa impressa no início (`worst-case estimate ≈ 41892 requests`)
é consistente com o tamanho real do backbone.

## 3. Achados relevantes (além de "funcionou")

### 3.1 O login (`step 154`) nunca é considerado necessário — causa raiz identificada: `ResponseGrep` não reconhece o prefixo `"Bearer "`

Em nenhum dos alvos testados (`227`, `233`) o `optimize` manteve o step `154`. O header
`Authorization: Bearer <JWT>` **nunca é tratado como token dinâmico** em nenhum `.curl.sh`
do workspace — é sempre um literal hardcoded:

```bash
grep -l "Authorization: {{extractor" arquivos-har/output/curls/*.curl.sh   # → 0 arquivos
```

Investigando o pipeline de `run` (`tracking/`), a causa não é o HAR ter uma única
sessão contínua — `BaselineDiff._diff_headers` (`baseline_diff.py:25-30`) compara contra
o request baseline por igualdade e **detecta corretamente** o `Authorization` como
candidato dinâmico em todo request autenticado (a baseline, `step 0`, não tem esse
header, logo `None != "Bearer eyJ..."` já basta para gerar o candidato). O problema
está um passo depois, em `CandidateResolver._find_origin` → `ResponseGrep.find`
(`response_grep.py:11-21`): a busca da origem faz `grep -lF` do **valor inteiro** do
candidato (`"Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`") contra as respostas
anteriores, testando só variantes de *encoding* (`value_variants`, linhas 42-49: cru,
URL-decode, URL-encode, base64-encode/decode). A resposta do login (`step 154`) devolve
`{"token":"eyJhbGci..."}` — o JWT **sem** o prefixo `"Bearer "`. Nenhuma das variantes de
encoding remove um prefixo textual (`"Bearer "` não é um encoding, é uma convenção de
protocolo, RFC 6750), então o `grep -lF` nunca bate e `ResponseGrep.find` retorna `None`.

Isso propaga em cascata: `_find_origin` sem resultado → `_process_candidate` marca
`candidate.status = "NotFound"` e retorna **antes** de chamar `_generate_new_extractor`
(`candidate_resolver.py:43-47`) → nada é salvo em `session_store.state.registry` → em
`PlaceholderApplier._apply_token` (`placeholder_applier.py:20-26`),
`_verified_extractor(token.token_id)` não encontra nada no registry e o método sai sem
substituir nada → o literal capturado no HAR (o JWT daquele instante) permanece
gravado no `.curl.sh` para sempre, nunca dependente de `154`.

Em outras palavras: o pipeline reconhece perfeitamente que `Authorization` é dinâmico —
ele só não consegue **confirmar a origem**, porque compara o valor byte-a-byte contra as
respostas e o padrão `Bearer <token>` é o único formato deste fluxo em que o valor
enviado tem um prefixo textual que a resposta de origem não carrega. Isso não depende
de o JWT ter ficado constante durante a captura — mesmo que o HAR tivesse múltiplos
logins com JWTs diferentes, cada um teria o mesmo problema de correspondência.

Consequência prática: o schedule mínimo encontrado por `optimize`/`replay --mode smart`
para os alvos autenticados deste fluxo só funciona hoje porque o JWT capturado no HAR
ainda está válido contra o servidor real (expiração em 2026, ainda não vencida). Se esse
JWT expirar, `replay`/`optimize` vão falhar com `401`/`403` sem nenhum sinal de que a
causa é a ausência do login — nada no schedule aponta para `154` como dependência.

Isso é uma lacuna concreta, e mais específica do que qualquer limitação já catalogada
em [[arquitetura-e-fundamentos]]: `ResponseGrep.value_variants` cobre transformações de
*encoding* (URL, base64) mas nenhuma de *wrapping* textual — e `Bearer `/`Token `/`Basic `
são prefixos padrão de `Authorization` extremamente comuns, não uma particularidade
deste app. Fica registrado aqui como achado; nenhuma alteração de código foi feita
nesta rodada (o usuário optou por só documentar, sem abrir uma spec de correção).

### 3.2 Correção: a leitura inicial ("quase todo token caiu em fallback literal") estava errada — é um bug de acurácia do comentário, não do resultado

Nesta seção eu tinha afirmado, com base nos comentários `# Token ... origin location
undetermined — using literal captured value` presentes em `req_0154.curl.sh` e
`req_0233.curl.sh`, que praticamente todo token deste fluxo caiu em fallback literal.
Investigando o registro real de extratores persistidos (`extractors/*.meta.json`, 57
no total), o quadro é o oposto:

```
HeaderAgent          22
CSSAgent             13
LiteralAgent         11
RegexAgent            7
LiteralFallbackAgent  4
```

**42/57 (74%) são extratores genuinamente deterministas** — só 15/57 (26%,
`LiteralAgent` + `LiteralFallbackAgent`) são literais de fato. Conferindo o `.py`
persistido do próprio token citado como exemplo (`b63fc1ef9b73f9b1c04af908af821991`,
usado no header `Content-Type` de `154`/`233`):

```python
match = re.search(r"'Content-Type':\s*'([^']+)'", body)
```

É um `RegexAgent` funcional, que extrai o valor de um bundle JS capturado no `step 23`
— não um literal. O comentário no `.curl.sh`, porém, diz o contrário em **toda**
ocorrência deste token no fluxo, inclusive a primeira (`req_0075.curl.sh`, o passo
mais antigo que o referencia).

Causa raiz: `CandidateResolver._process_candidate` (`candidate_resolver.py:57-59`)
retorna direto quando o `token_id` (derivado de `path:origin_step`, logo idêntico para
qualquer step que precise do mesmo header vindo da mesma origem) já está no
`session_store.state.registry` — seja porque já foi resolvido antes nesta mesma
rodada, seja porque `extractors/` nunca é limpo entre execuções de `run` e o slot já
existia de uma rodada anterior sobre o mesmo `--output`. Esse caminho de retorno
**nunca seta `candidate.origin_location`** — o campo fica no default do Pydantic
(`None`, `models/session.py:51`). `CurlGenerator._token_comments`
(`curl_generator.py:64-65`) decide o texto do comentário só olhando esse campo:

```python
if token.origin_location is None:
    lines.append(f"# Token {token.token_id} origin location undetermined — using literal captured value")
```

Como o campo nunca é preenchido num *cache hit*, o comentário sempre imprime "usando
literal", **mesmo quando o extrator real referenciado pelo `{{extractor:...}}` é um
`RegexAgent`/`HeaderAgent`/`CSSAgent` de verdade**. É um bug de acurácia do
comentário — cosmético, não afeta a resolução em si (o placeholder continua apontando
para o extrator correto, `replay`/`optimize` funcionam certo) — mas é enganoso para
quem lê o `.curl.sh` tentando entender a proveniência real de um token, e foi a causa
direta da minha conclusão errada nesta seção.

O que continua válido da observação original: como o `optimize` opera sobre um HAR
onde a maior parte dos steps não introduz um candidato genuinamente novo (a maioria já
está resolvida por reaproveitamento), toda faixa testada nas rodadas da seção 2
convergiu para `kept = []`. Isso não é porque os tokens são literais — é porque, neste
fluxo específico, nenhum step fora do schedule de âncoras carrega um efeito colateral
funcional que os steps seguintes dependam de fato (o único candidato a isso, o login,
tem seu próprio problema à parte, ver seção 3.1). A árvore de decisão da fase 2 do
`optimize` (remoção reversa um a um, `replay_optimizer.py:138-143`) segue sem ter sido
exercitada num cenário onde a remoção de um candidato falha e ele precisa ser mantido.

### 3.3 Bug confirmado: a própria anotação `- probably static` do `replay` quebra o parser de dependências usado por `compute_smart_schedule`/`optimize`

Este é o achado mais importante do relatório — e a explicação anterior desta seção
("resposta real sobrescrita muda a proveniência") estava incompleta: fui verificar a
mecânica exata e a causa é outra, mais grave, e reprodutível de forma determinística
(não depende de o servidor devolver algo diferente entre chamadas).

`replay --mode smart --to 233`, executado três vezes ao longo desta sessão de testes,
retornou um schedule de âncoras **encolhendo progressivamente**:

```
1ª chamada:  [0, 1, 14, 23, 34, 75, 233]
2ª chamada:  [0, 1,     23, 34, 75, 233]     (step 14 desapareceu)
3ª chamada:  [                    233]      (todas as âncoras desapareceram)
```

Causa raiz: `ReplayRunner._annotate_static_tokens`/`_annotate_fallback_tokens`
(`replay_runner.py:127-143`) anexam um sufixo (`" - probably static"` ou
`" - could not extract value from response, using captured value"`) **na própria
linha** `# Token <id> comes from response of step <N>` de dentro do `.curl.sh`,
toda vez que `ReplayTokenResolver` classifica aquele token como estático ou como
fallback durante um `replay` (comportamento documentado, ver
[[arquitetura-e-fundamentos]]). O problema é que `CurlDependencyParser`, usado por
`compute_smart_schedule` (`replay_runner.py:166-189`) — a mesma função que tanto
`replay --mode smart` quanto a fase 1 do `optimize` (`replay_optimizer.py:68`) usam
para achar as âncoras — exige que essa linha termine **exatamente** em `\d+$`:

```python
DEPENDENCY_PATTERN: ClassVar[Pattern[str]] = re.compile(
    r"^# Token (?P<token_id>[a-z0-9]+) comes from response of step (?P<origin_step>\d+)$",
    re.MULTILINE,
)
```

Depois que o sufixo é anexado, a linha deixa de terminar em `\d+` — o regex nunca
mais bate. Confirmei isso diretamente no arquivo real, depois das rodadas de teste
desta sessão:

```bash
$ grep "comes from response" arquivos-har/output/curls/req_0233.curl.sh
# Token b63fc1ef... comes from response of step 23 - probably static
# Token 5eb3fa29... comes from response of step 34 - probably static
# Token 5809b41a... comes from response of step 75 - probably static
# Token 6add66a6... comes from response of step 1 - probably static

$ python3 -c "import re; ...DEPENDENCY_PATTERN.finditer(texto)..."
matches: 0
```

Ou seja: assim que um `replay` anota um token como estático (o que acontece
silenciosamente, em qualquer chamada normal, sempre que `annotate=True` — o padrão
de `replay`; `optimize` usa `annotate=False` internamente e não introduz o problema
por conta própria, mas **herda** o estrago se `replay` já rodou antes no mesmo
workspace), aquele step desaparece **permanentemente** (é gravado em disco) do grafo
de dependência que `compute_smart_schedule` consegue enxergar. O `.curl.sh` continua
resolvendo o token certo na hora de executar — o placeholder `{{extractor:...}}` não
é tocado, só o comentário — então o efeito não é uma requisição quebrada, é um
**schedule de âncoras incompleto silenciosamente aceito como correto**.

Impacto concreto para `optimize`: o fluxo natural descrito no próprio README é rodar
`optimize` a partir do schedule que `replay --mode smart` calcularia — se `replay`
já rodou antes sobre o mesmo `--output` (uso normal, não um caso extremo), parte das
dependências reais já pode estar invisível para a fase 1 do `optimize` antes mesmo
de ele começar a rodar. Como o resultado ainda passa pela validação de
`success_criteria` no final, `optimize` não vai avisar que perdeu rastro de uma
dependência — ele só vai reportar `Optimization SUCCESSFUL` com um schedule menor do
que deveria, e esse schedule menor só continua funcionando enquanto os valores
literais/capturados remanescentes (ver seção 3.1) ainda forem válidos contra o
servidor real. É a mesma classe de risco da seção 3.1 (dependência real mascarada
por um fallback que "ainda funciona hoje"), mas com uma causa mecânica e determinística
diferente, e que **o próprio uso normal do `replay` introduz no workspace** — não é
preciso nenhuma condição rara para disparar.

Recomendação prática até uma correção existir: para um `optimize` cujo resultado
precisa ser confiável, rodar a partir de um `--output` que ainda não recebeu nenhuma
chamada de `replay` (só `run`), ou tratar qualquer resultado de `optimize` sobre um
workspace já usado por `replay` como suspeito de estar sub-dimensionado.

### 3.4 `--from` alto pode substituir dependências reais por fallback literal sem avisar

Testei `optimize --to 233 --from 36` (o floor documentado como "que nenhuma âncora
nem faixa cruza") e o resultado foi `Optimization SUCCESSFUL: 2 step(s)` — só
`[36, 233]`. Isso é o comportamento documentado (`--from` corta a recursão de
dependências abaixo do floor), mas a consequência prática não é só "menos passos":
quando a recursão para em `36`, qualquer token cuja origem real ficasse abaixo do
floor deixa de ser resolvido dinamicamente e cai para o `captured_value` literal do
extractor já persistido (o mesmo mecanismo de fallback da seção 3.1) — e `optimize`
reporta sucesso do mesmo jeito, sem sinalizar que parte da resolução passou a
depender de valores congelados do HAR original em vez de dados frescos do servidor.
Combinado com o achado da seção 3.3, um `--from` mal calibrado pode produzir um
schedule "mínimo" que só funciona hoje, pelo motivo errado.

### 3.5 Cobertura que esta rodada não exercitou

Nem tudo do `ReplayOptimizer` foi posto à prova nos testes acima — registro aqui em
vez de deixar implícito:

- **Recuperação reativa** (`_needs_reactive_refresh`, `MAX_REACTIVE_REFRESHES = 2`,
  `replay_optimizer.py:81-89`) — dispara quando um passo do schedule volta
  `400`/`401`/`0`. Em nenhum teste desta rodada um passo voltou um desses códigos, então
  esse caminho (reexecutar a backbone inteira e tentar de novo) nunca rodou de
  verdade.
- **Abort na confirmação final** (`ReplayOptimizer._confirm` retornando `False` depois
  que todas as faixas passaram individualmente, `replay_optimizer.py:54-55`) — nunca
  observado; todos os meus testes convergiram para sucesso na primeira confirmação.
- **Remoção reversa de candidato com retenção genuína** (`_resolve_range`,
  `replay_optimizer.py:138-143`) — como já registrado na seção 3.2, nenhuma faixa
  testada teve um candidato que precisasse ser mantido; a árvore de decisão de
  "remove e reverifica, mantém se falhar" nunca chegou a manter nada.
- **Interação com `skip_rules`** — o HAR usado não tem nenhuma requisição `OPTIONS`
  (o único método pulado por padrão), então não pude checar se a classe de bug já
  documentada em `docs/20260805 Steps Pulados Quebram o Schedule do Replay Smart/List/Slice`
  também afeta `_candidates_between`/`existing_step_indexes` do `optimize`.
- **Colisão de `--steps-out`** — não testei rodar `optimize` duas vezes para o mesmo
  caminho de saída explícito.

## 4. Conclusão

O comando `optimize` funcionou corretamente em todos os cenários testados contra o
servidor real:
- Caminho feliz em dois alvos distintos, produzindo um `.txt` válido e consumível
  por `replay --mode list` (round-trip confirmado).
- `--success-criteria` sobrescreve o `config.json` e a validação final de fato
  inspeciona o corpo da resposta, não só o status code.
- As três validações de erro (`success_criteria` ausente, `--from` inválido, teto de
  `--max-requests`) falham antes de qualquer requisição desnecessária, com mensagens
  claras.

Nenhum dos achados abaixo é um bug do algoritmo de busca do `optimize` propriamente
dito (a lógica de âncoras → faixas → remoção reversa → confirmação se comportou como
o código descreve em todos os testes). O risco está em quão confiável é a entrada que
essa lógica recebe:

1. **(Cosmético)** `CandidateResolver`/`CurlGenerator` produzem um comentário de
   proveniência (`origin location undetermined — using literal captured value`) que é
   **falso para todo token reaproveitado** — a maioria dos tokens deste fluxo (74% dos
   extratores persistidos) são genuinamente deterministas, não literais, mas o
   comentário só é preenchido no primeiro cache-miss (seção 3.2). Não afeta a
   resolução real, só a leitura humana do `.curl.sh`.
2. **(Risco de correção, já real neste HAR)** `ResponseGrep` não reconhece o prefixo
   `"Bearer "` do header `Authorization` como variante de busca válida, então o JWT de
   autenticação nunca é modelado como dependente do login (`step 154`) e cai em literal
   hardcoded — o schedule mínimo encontrado só funciona hoje porque esse JWT específico
   ainda não expirou (seção 3.1).
3. **(Bug confirmado, maior severidade)** a anotação `- probably static`/`- could not
   extract...` que o próprio `replay` grava no `.curl.sh` quebra, de forma permanente e
   determinística, o regex que `compute_smart_schedule` usa para achar dependências —
   qualquer step anotado desaparece do grafo de dependência visível para `optimize` e
   `replay --mode smart` a partir daquele ponto, sem nenhum aviso (seção 3.3). Diferente
   dos itens 1 e 2, este não depende de nenhuma peculiaridade deste HAR — reproduz em
   qualquer workspace onde `replay` já rodou antes.
4. **(Amplificador dos itens 2 e 3)** `--from` alto silenciosamente troca dependências
   reais por fallback literal sem sinalizar isso no resultado (seção 3.4).

Também vale registrar o que a seção 3.5 lista: recuperação reativa, abort de
confirmação final, e retenção genuína de candidato na fase 2 não foram exercitados em
nenhum teste desta rodada — não porque falharam, mas porque nenhum cenário testado
produziu as condições (`400`/`401`, uma faixa que realmente precisa de um passo extra)
para acioná-los.
