# Spec — Casamento por Fragmento e Comparação entre Épocas

> Etapa que fecha o item 5 de `docs/20260817 Reteste do Otimizador contra Servidor
> Real/correcoes.md` (`Authorization` congelado). Todo número deste documento foi
> **medido** em 17–18/08/2026 sobre o HAR atual e sobre um workspace gerado para esta
> spec; nada foi herdado do relatório de 17/08, porque o HAR foi regravado depois que
> ele foi escrito (ver 1.8). O documento passou por revisão adversarial própria e por
> uma revisão independente de contexto limpo — o que as duas mudaram está em §7.

## 1. Objetivo

O header `Authorization: Bearer <JWT>` nunca é modelado como token dinâmico: o valor
fica congelado como literal nos `.curl.sh`, o step do login nunca vira origem de
ninguém, e o trecho autenticado do fluxo só funciona enquanto aquele JWT não expirar.
São **duas causas independentes**, ambas medidas abaixo, e nenhuma resolve sozinha.

No caminho, a etapa também resolve o inverso: hoje o projeto cria extrator para valor
que **nunca muda**, inflando o schedule do `smart`/`optimize` com steps que não fazem
diferença nenhuma. A regra de admissão de 3.4 trata os dois problemas com o mesmo
critério.

### 1.1 O problema, reproduzido

Workspace `arquivos-har/ws_20260817_main`, gerado para esta spec (ver 1.8):

```
$ grep -l "Authorization: Bearer eyJ" curls/*.curl.sh | wc -l      # literal congelado
13
$ grep -l "Authorization: {{extractor" curls/*.curl.sh | wc -l     # token dinâmico
0
$ grep -h "comes from response of step 0153" curls/*.curl.sh | wc -l   # login como origem
0
```

`req_0224.curl.sh` é o retrato do problema — e, de bônus, do problema inverso:

```bash
#!/bin/bash
# [Token b63fc1ef... comes from response of step 0023] origin location undetermined — using literal captured value; probably static
# [Token 5809b41a... comes from response of step 0075] origin location undetermined — using literal captured value
# [Unresolved 4] url; header:Accept; header:Authorization; header:Referer
curl -X GET \
     http://localhost:8090/auth/check \
     -H 'Accept: */*' \
     -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJhdXRoLWFwaSIsInN1YiI6InZpbmljaXVzLm1wb250ZUBnbWFpbC5jb20iLCJleHAiOjE4MDI1NjQwODl9.mzGnF1hIwsxuLsOGWK1v0zXmot9mLS_fd1O2my_xPxM' \
     -H 'Content-Type: {{extractor:b63fc1ef...}}' \
     -H 'Origin: {{extractor:5809b41a...}}' \
     -H 'Referer: {{extractor:5809b41a...}}/' \
     ...
```

O token que precisava ser dinâmico está congelado; e dois valores que **nunca mudam**
(`Content-Type: application/json` e `Origin: http://127.0.0.1:8080`) viraram extrator,
arrastando os steps `23` e `75` para o schedule de qualquer alvo que use esse curl. O
próprio replay já anotou um deles como `probably static`.

São 13 steps com `Authorization` (`224`, `226`–`229`, `231`–`233`, `236`, `309`, `311`,
`312`, `314`), **um único** valor distinto, e o login é o step `153`
(`POST http://localhost:8090/auth/login`).

**Prazo do risco (corrigido).** O JWT do HAR atual tem `exp: 1802564089` —
**13/02/2027 21:14:49** (horário local). O relatório de 17/08 registrou `28/12/2026`,
que era o `exp` do HAR **antigo** (`1798419171`); esse prazo não vale mais.

**O fluxo hoje só passa porque o JWT congelado ainda é aceito:**

```
$ ... replay --output ../arquivos-har/ws_20260817_main --mode smart --to 224
Step 23 completed with status 200 | Step 75 completed with status 403 | Step 224 completed with status 200
Replay Validation Result: ✓ SUCCESS
```

Simulando o dia seguinte à expiração (cópia do workspace com a assinatura do JWT
adulterada nos 13 `.curl.sh`): `Step 224 → 403`, `✗ MISMATCH (403 vs original 200)`.
E **incluir o login à mão não resolve** (`--mode list` com `[23, 75, 153, 224]`):

```
Step 153 completed with status 200      ← o login roda e devolve um token novo…
Step 224 completed with status 403      ← …que nenhum .curl.sh consome
```

A resposta do login gravada pelo replay (`replays/<RUN_ID>/res_0153.json`) traz
`{"token":"eyJ..."}` — o dado certo, obtido na hora, jogado fora por falta de uma
aresta que o consuma.

### 1.2 Causa A — a busca de origem exige o valor **inteiro**

`OriginFinder._find_variant` (`har_reproducer/tracking/origin_finder.py:27-33`) testa
`variant not in text`: o valor do candidato precisa aparecer **por inteiro** no texto
pesquisável da resposta.

```python
def _find_variant(self, eligible: List[int], variant: str, is_raw: bool) -> Optional[OriginMatch]:
    for step_index in eligible:
        text: Optional[str] = self.corpus.searchable_text(step_index)
        if text is None or variant not in text:
            continue
        return self._build_match(step_index, variant, is_raw)
    return None
```

O request manda `Bearer <jwt>`; a resposta do login traz `{"token":"<jwt>"}`. Medido
com as classes reais do projeto, corpus da época do HAR:

| busca | resultado |
|---|---|
| `find('Bearer eyJ…xPxM', 0, 224)` | `None` |
| `find('eyJ…xPxM', 0, 224)` (só o JWT) | `step_index=153` |
| `'Bearer <jwt>' in searchable_text(153)` | `False` |
| `'<jwt>' in searchable_text(153)` | `True` |

⚠️ **`text` não é "a resposta"; é um blob.** `ResponseCorpus._serialize` concatena
headers, cookies, `redirect_url` e o **body cru, inclusive binário**. Então o
casamento "de valor inteiro" **já é busca por substring dentro de um blob** — não é
evidência estrutural. Medido: onde cada valor "inteiro" de hoje realmente casou:

```
'?1'               step 4  → dentro de BYTES BINÁRIOS do corpo de uma fonte: ...x?1\xb8k...
'same-origin'      step 14 → dentro de 'cross-origin-opener-policy: same-origin-allow-popups'
'application/json' step 23 → dentro do código JS: 'Content-Type': 'application/json',
'document'         step 0  → dentro do JS: document.getElementsByTagName("link")
'127.0.0.1:8080'   step 75 → dentro de 'access-control-allow-origin: http://127.0.0.1:8080'
```

Nenhum deles casou com um header ou cookie de valor exato. A consequência de projeto é
direta: **a força da evidência é contínua em comprimento e entropia, não binária** — não
existe uma fronteira "inteiro é confiável / pedaço é suspeito", e por isso a regra de
admissão de 3.4 vale para os dois casos.

### 1.3 Causa B — valor e resposta consultada são de épocas diferentes

`EngineFactory.create` (`engines/construction/engine_factory.py:70-76`) escolhe o corpus
de descoberta pelo modo da engine:

```python
tracking_responses_dir: Path = (
    self.workspace.real_responses if engine_cls.USES_NETWORK else self.workspace.original_responses
)
response_corpus: ResponseCorpus = ResponseCorpus(tracking_responses_dir, Workspace.STEP_INDEX_WIDTH)
```

Em `--mode main` o corpus é `real_responses/` — respostas **da execução de agora** —
enquanto o valor procurado vem do HAR, **da época da gravação**. Para um valor que muda
a cada sessão, os dois nunca casam. Medido:

| JWT | `exp` | data |
|---|---|---|
| do HAR (valor procurado) | `1802564089` | 13/02/2027 21:14:49 |
| de `real_responses/res_0153.json` | `1802566209` | 13/02/2027 21:50:09 |

Compartilham **123 caracteres** de prefixo e divergem nos dígitos do `exp`
(`…QwODl9.mzGnF` × `…YyMDl9.ttzG7`).

Confirmado contra o servidor: **três logins seguidos devolvem três tokens diferentes**
(`exp` 1802575104 / 1802575105 / 1802575107).

### 1.4 As duas causas estão entrelaçadas — medição

Simulei o laço de descoberta do `CandidateResolver` sobre o HAR inteiro (324 entries,
mesmas classes do projeto, com cache positivo e cache de negativos com janela):

| variante | corpus | casamento | acha o `Authorization`? | o que acha |
|---|---|---|---|---|
| V1 (hoje, `--mode main`) | `real_responses` | valor inteiro | **não** | — |
| V2 | `original_responses` | valor inteiro | **não** | — |
| V3 | `original_responses` | inteiro + fragmento | **sim** | o JWT inteiro (173 de 180 chars, sobra 7) |
| V4 | `real_responses` | inteiro + fragmento | sim, **errado** | os 123 chars antes do `exp` (sobra 57) |

V4 é a armadilha: sem a troca de época, o fragmento é o prefixo comum aos dois JWT, e a
reconstrução monta prefixo fresco + assinatura velha, que nenhum servidor aceita. E a
troca de corpus **sozinha** (V1 → V2) é rigorosamente neutra: mesmos 17 pares
`(path, value)` com origem, mesmos steps de origem, 254 ocorrências, 0 ganhos, 0 perdas.

### 1.5 A regra de admissão: mudou entre observações

O critério para um candidato virar extrator passa a ser **evidência de que o valor
muda**, não a força do casamento:

> Um candidato só vira extrator se o texto casado **difere** entre a resposta gravada no
> HAR (`original_responses/`) e a resposta obtida na execução (`real_responses/`) do
> mesmo step de origem. Se for idêntico nas duas, o valor fica literal.

Medido no fluxo inteiro, com o algoritmo de fragmento de 3.1:

| | quantidade | veredito da porta |
|---|---|---|
| casamentos de valor inteiro (por valor distinto) | 15 | **15 idênticos → todos rejeitados** |
| casamentos por fragmento (fragmento de 32 chars ou mais) | 2 | 1 idêntico → rejeitado; **1 mudou → admitido** |
| **extratores criados** | | **1** — `header:Authorization`, origem step `153` |

O workspace sai de **17 extratores e 254 linhas de dependência** para **1 extrator e 13
linhas** — e a única aresta que sobra é a que faltava.

Por que a porta é o desenho certo, e não uma etiqueta: um extrator cujo valor não muda
é **cerimônia**. `ReplayTokenResolver._resolve_one`
(`replay/replay_token_resolver.py:56-61`) só lê a resposta fresca quando o step de
origem está no schedule; fora do schedule ele lê a resposta congelada em
`real_responses/` — devolvendo exatamente o que um literal devolveria. Ou seja: ou a
aresta ancora (e paga o custo que ela não justifica), ou o extrator não faz diferença
nenhuma.

**O custo desta decisão, declarado.** Requisição condicional é o caso que perde: medido,
`ETag` é idêntico entre as épocas em **285/285** casos e `Last-Modified` em **292/296**
(no workspace do HAR anterior, 210/210 e 215/218). Eles mudam no deploy, não entre duas
execuções separadas por minutos — então a porta os deixa literais, e depois de um deploy
o replay acusa `200` onde esperava `304` sem aresta que explique. É exatamente o que a
**redescoberta reativa** resolve, e é por isso que ela é a etapa seguinte (1.7).

### 1.6 O que esta mudança cobre

- **Casamento por fragmento** (3.1, 3.2): aceitar como origem o maior pedaço contíguo do
  valor que a resposta contém, deixando o resto literal.
- **Descoberta e verificação sempre na época do HAR** (3.3): o corpus de `OriginFinder`,
  do `TokenLocationDetector` e do laço TDD dos agentes passa a ser `original_responses/`
  nos dois modos; a execução dos extratores continua lendo a época corrente.
- **Porta de admissão por mudança entre observações** (3.4), com o registro do que foi
  pulado (3.5) — que é o insumo da etapa reativa.
- **Duas consequências obrigatórias** da separação de épocas: parar de semear o token com
  o valor da época do HAR (3.7) e cair para o `captured_value` quando a extração falha na
  época da execução (3.8).
- **Rede de caracterização**: os fixtures precisam passar a divergir entre as duas épocas,
  senão a porta zera a cobertura de todo o pipeline de descoberta (3.9).

### 1.7 Fora de escopo (decidido explicitamente)

- **Redescoberta reativa** — detectar que um step que antes passava parou de passar
  (divergência contra o status de referência, que `ReplayResultComparator` já calcula) e,
  nesse ponto, refazer a descoberta com as respostas frescas em mão, criando o extrator
  que a porta havia dispensado. **É a etapa seguinte**, e é o que fecha o buraco das duas
  amostras (ETag no deploy, chave na rotação, JWT na expiração). Absorve o item 6 de
  `correcoes.md` (recuperabilidade por divergência em vez de lista fixa de status).
  Fica registrado que ela é viável sem passar o `.har` para o `replay`: medido, o
  workspace basta — `real_requests/req_0224.json` guarda o request **literal**, com o JWT
  cru e sem placeholder (é gravado antes da análise), e as duas épocas estão em disco.
- **Item 4** (`optimize`: proveniência × necessidade). A porta de 3.4 **entrega o núcleo
  dele por construção**: toda aresta que passa a existir é, por definição, necessidade
  (o valor muda), então proveniência nunca vira âncora porque proveniência nunca vira
  aresta. Medido: das âncoras de hoje, nenhuma é necessidade — `replay --mode list` com
  **só** o step `224` devolve `200 ✓ matched`. O que sobra do item 4 é a fase 2 do
  `optimize` testar as âncoras para remoção, que continua fora daqui.
- **Item 2** (`origin_location` no cache hit): fora. Com 1 extrator no fluxo, sobra 1
  linha correta (step `224`) e 12 linhas com a frase enganosa nos steps seguintes.
- **Item 8** (coincidência de baixa entropia no `origin_key`): resolvido de lado, sem
  spec própria. Medido: o token `5809b41a` (`Origin` ← `Access-Control-Allow-Origin`) é
  referenciado **576 vezes** nos 320 curls e é rejeitado pela porta — ele deixa de
  existir. Isso remove um risco real: num servidor configurado com
  `Access-Control-Allow-Origin: *`, o replay hoje montaria `Origin: *` e
  `Referer: */dashboard/` em 576 lugares.
- **`BaselineDiff` comparar contra a primeira entry do HAR** — a causa raiz do lixo, e
  ela é pior do que a documentação sugere: a entry 0 deste HAR tem **6 headers**
  (`Accept`, `Upgrade-Insecure-Requests`, `User-Agent`, `sec-ch-ua`, `sec-ch-ua-mobile`,
  `sec-ch-ua-platform`), então todo `Sec-Fetch-*`, `Host`, `Origin`, `Referer`,
  `Cache-Control`, `Pragma` e `Content-Type` de qualquer step posterior é candidato para
  sempre. A porta de 3.4 corta o efeito (não viram extrator), não a causa. Continua fora
  de escopo desde 04/08; vale spec própria.
- **Gate de LLM** para decidir admissão. Avaliado e descartado com medição: o modelo do
  `config.json` (`google/gemini-3.1-flash-lite`) acerta 5/5 quando recebe as duas épocas
  no prompt, e **15/18 quando decide sem elas** — o erro é estável (3 de 3 vezes promove
  `http://127.0.0.1:8080` a token dinâmico). Como o dado responde a pergunta e a LLM é
  opcional no projeto (`ProjectConfig.llm` default `None`, e nenhum dos 27 cenários
  golden a configura), a admissão fica determinística.
- **Reconstruir um valor a partir de vários fragmentos** (cobertura mínima). Avaliado com
  implementação de verdade: no corpus da época do HAR o `Authorization` cobre em 2 peças
  (`'Bearer '` + o JWT), exatamente como a proposta previa; mas **156 dos 157 candidatos
  do fluxo são cobríveis**, e entre os 23 que cobrem em 2 peças estão `*/*` (`'*/'`+`'*'`)
  e `navigate` (`'navigat'`+`'e'`) — o número de peças não separa evidência de
  coincidência. Fora de escopo; o mecanismo de um fragmento por candidato (3.1) resolve o
  caso medido.

### 1.8 Nota de metodologia

O HAR foi **regravado** depois do relatório de 17/08. Tudo aqui foi remedido sobre
`arquivos-har/progressofit.har` (5.232.351 bytes, gravado 17/08/2026 21:14) e sobre o
workspace `arquivos-har/ws_20260817_main`, gerado com o código de `master` (`07028f4`) e
o `config.json` da raiz:

```
uv run python -m har_reproducer.main run --har ../arquivos-har/progressofit.har \
    --output ../arquivos-har/ws_20260817_main --mode main --config config.json   # 2m24s
```

| fato | relatório 17/08 (HAR antigo) | HAR atual (medido) |
|---|---|---|
| entries | 238 | **324** |
| steps pulados (`ws://`) | 3 | **4** (`81`, `155`, `240`, `251`) |
| `.curl.sh` gerados | 235 | **320** |
| step do login | `154` | **`153`** |
| corpo da resposta do login gravado no HAR | **não** | **sim** (185 bytes) |
| entries sem corpo gravado | 13 | **12** |
| steps com `Authorization` | 9 | **13** |
| extratores persistidos | 117 | **17** |
| `If-None-Match` no HAR | 63 | **0** |

⚠️ Consequências para quem implementa:

1. **O diagnóstico de `--mode dry` do relatório caiu**: o corpo da resposta do login
   **está** gravado no HAR atual, e é por isso que a Causa A é demonstrável isoladamente.
2. **Os 63 `If-None-Match`/`ETag` da etapa de 13/08 não existem neste HAR.** A queda de
   117 para 17 extratores é outro HAR, não regressão.
3. `arquivos-har/output` **já foi regerado** do HAR novo (320 curls, 17 extratores). O
   workspace do HAR anterior é `arquivos-har/output(original)` — e ele é **pré-mudança de
   13/08** (gerado 16:40, código mergeado 21:07), então não contém nenhum extrator de
   `ETag`, apesar de ter 126 curls com `If-None-Match` literal.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `OriginFinder` — `har_reproducer/tracking/origin_finder.py` (arquivo inteiro, 65 linhas)

Ponto único de descoberta. Filtra os steps elegíveis (janela
`[from_step_index, before_step_index)`), percorre as variantes de encoding
(`ValueVariants.of`) e procura o valor inteiro no texto pesquisável de cada resposta, em
ordem crescente de step, devolvendo o **primeiro** que casar. `_build_match`/`_origin_key`
(`:35-58`) só tentam descobrir a chave de origem quando a variante casada é o valor cru,
comparando por igualdade exata contra cookies e depois headers.

Importa porque é onde entra o passe de fragmento (3.2), e porque `_origin_key` passa a
operar sobre o texto casado.

### `ResponseCorpus` — `har_reproducer/tracking/response_corpus.py` (arquivo inteiro, 89 linhas)

Corpus sobre um diretório de respostas, com memoização por step. `searchable_text`
serializa headers (`Nome: valor`), cookies (`nome=valor`), `redirect_url` e body numa
string só — é o blob de 1.2. `eligible_indexes` varre `res_*.json` e devolve os índices
menores que o step atual.

Importa porque as duas épocas de 3.3/3.4 são duas instâncias desta classe, apontando para
diretórios diferentes. A classe não muda.

### `CandidateResolver` — `har_reproducer/tracking/candidate_resolver.py:42-79, 112-141, 157-200`

Acha origem (cache positivo por valor, cache de negativos com janela), deriva o `token_id`
do slot, reusa o extrator persistido se ele reproduzir o valor do candidato, senão gera um
novo.

```python
def _process_candidate(self, candidate: DynamicToken, step_index: int) -> DynamicToken:
    origin: Optional[OriginMatch] = self._find_origin(candidate.current_value, step_index)
    if origin is None:
        candidate.status = "NotFound"
        return candidate

    candidate.origin_step = origin.step_index
    candidate.origin_key = origin.origin_key
    candidate.origin_container = origin.origin_container
    base_token_id: str = self._derive_token_id(candidate.path, candidate.origin_step)
    ...
```

Três pontos que a mudança toca, todos no trecho abaixo — o diretório passado ao
`run_existing`, a comparação contra `candidate.current_value`, e a semeadura do token:

```python
    result: Optional[str] = self.extractor_runner.run_existing(slot_id, self.response_corpus.responses_dir)
    if result != candidate.current_value:
        return SlotStatus.MISMATCH, self._mismatch_error(result, candidate.current_value)
    ...
    self.session_store.state.registry[slot_id] = persisted
    self.session_store.set_token(slot_id, result)              # ← semeia o token
    self._validated_values[slot_id] = result
```

⚠️ **O `_find_origin` só cacheia negativo com janela** (`:72-76`): um valor que não achou
origem no step `N` só volta a ser procurado a partir de `N`. Consequência: o passe de
fragmento **e** a porta de admissão têm que rodar na mesma chamada do passe de valor
inteiro — como uma segunda tentativa posterior, a janela negativa já teria excluído o
step `153` para todos os steps depois do `224`.

### `TokenResolver` — `har_reproducer/tracking/token_resolver.py` (arquivo inteiro, 36 linhas)

Resolve, contra o diretório de respostas da **execução**, todo token registrado que ainda
não tem valor:

```python
def resolve_all(self, force: bool = False) -> None:
    for token_id, extractor in self.session_store.state.registry.items():
        if not force and token_id in self.session_store.state.tokens:
            continue
        if self._should_refresh_token(extractor):
            self._refresh_token(token_id, extractor)
```

⚠️ Duas propriedades load-bearing, ambas verificadas com sonda em processo:

- **Token já semeado nunca é atualizado**: com `tokens["t1"]` preenchido, `resolve_all()`
  faz **0** chamadas ao runner; sem semear, faz 1 e grava o valor fresco. É o que torna
  3.7 obrigatório.
- **Falha na resolução deixa o placeholder cru**: `_refresh_token` retorna sem gravar e
  `SessionStore._resolve_token_placeholder` (`session/session_store.py:22-26`) devolve
  `match.group(0)` — o request sairia com `{{extractor:…}}` dentro do header. É o que
  torna 3.8 obrigatório.

### `PlaceholderApplier` — `har_reproducer/tracking/placeholder_applier.py:12-58`

Substitui **cada ocorrência do valor do token** pelo placeholder, em ordem decrescente de
tamanho, em url, headers, cookies e body.

⚠️ A substituição já é por substring, e o efeito "fragmento dinâmico + afixo literal" já
existe no workspace atual sem feature nova: `-H 'Referer: {{extractor:5809b41a…}}/'` em
`req_0224.curl.sh` — o token vale `http://127.0.0.1:8080` e a barra ficou literal. A
mecânica de saída que o fragmento precisa **já está pronta**.

### `AgentFactory.create` / `BaseAgent` — `agents/construction/agent_factory.py:42-63`, `agents/base_agent.py:20-55, 135-202`

`create` monta o agente pela `origin_location` e passa
`expected_value=candidate.current_value` (`:48`). `run_tdd_loop` gera código, executa
contra `response_sample` e só aceita quando a saída bate exatamente com `expected_value`
(`_execute_script`, `:198-202`). Importa porque o par (valor esperado, resposta de
verificação) tem que ser da mesma época.

### `TokenLocationDetector.find` — `tracking/token_location_detector.py:12-30`

Decide a `TokenLocation` procurando o valor em cookies → headers → `redirect_url` → body,
e é quem escolhe o agente. Medido para o JWT: `BODY_JSON` com a resposta da época do HAR;
`None` com a da execução.

### `ReplayTokenResolver._resolve_one` — `replay/replay_token_resolver.py:47-67`

```python
        if origin_step in schedule:
            override_dir: Path = replay_run_dir
        else:
            override_dir = self._reference_dir_for_step(origin_step, res_refer_dir, original_responses_dir)
```

⚠️ É a razão de 3.4 ser porta e não etiqueta: **fora do schedule, o extrator lê a resposta
congelada** e devolve o mesmo valor que um literal devolveria.

### `EngineFactory.create` / `_build_tracker` — `engines/construction/engine_factory.py:59-110`

Raiz de composição do ramo `run`. Hoje um único `tracking_responses_dir` alimenta duas
coisas de naturezas diferentes: o corpus da descoberta e o `TokenResolver` da execução
(`:70-83`). É esse casamento que 3.3 desfaz.

### `Engine._process_entry` — `har_reproducer/engines/engine.py:70-96`

```python
self._persist_request_step(index, step.request)
self._persist_original_response_step(index, step.response)      # ← época do HAR, antes da análise
if skip_reason is not None:
    return self._skip_entry(index, skip_reason)
step.analysis = self.tracker.analyze_step(step, first_entry)    # ← descoberta
self.token_resolver.resolve_all()                               # ← execução
response: StepResponse = self.execute_step(step)
self._persist_response_step(index, response)                    # ← época da execução
```

⚠️ Em `--mode main`, quando o step `N` é analisado, `real_responses/` já contém as
respostas dos steps `< N` desta execução — é o que torna a porta de 3.4 calculável no
lugar certo. Em `--mode dry`, `_persist_response_step` é um no-op (`DryEngine`) e
`real_responses/` fica **vazio** (medido: 0 arquivos), o que define o comportamento de
3.4 nesse modo.

### `Extractor.valid_count` / `ever_changed` / `ReplayStatusPhrase.PROBABLY_STATIC`

`ReplayTokenResolver._record_observation` (`:96-106`) já acumula observações por token e o
`ReplayRunner` já anota `probably static` no `.curl.sh` depois de 5 observações iguais.
**Nada consome essa anotação.** É o mesmo sinal da porta de 3.4 com mais amostras — e o
precedente que justifica a porta agir em vez de só rotular.

## 3. Decisões de arquitetura

### 3.1 — `FragmentMatcher`: fragmento comum a partir de uma âncora fixa

**Componente novo**, `har_reproducer/tracking/fragment_matcher.py`, sem estado: dado o
valor do candidato e o texto pesquisável de uma resposta, devolve o maior pedaço contíguo
que os dois compartilham, ou `None`.

Um único parâmetro, `ANCHOR_LENGTH: ClassVar[int] = 16`, e dele sai o tamanho mínimo do
fragmento (`2 * ANCHOR_LENGTH = 32`):

1. Se `len(valor) < 2 * ANCHOR_LENGTH`, devolve `None`.
2. Âncora = `valor[ANCHOR_LENGTH : 2 * ANCHOR_LENGTH]` — sempre os caracteres 16–31.
3. Para cada ocorrência da âncora no texto, expandir para os dois lados enquanto os
   caracteres coincidirem; guardar a maior expansão.
4. Devolver a maior expansão, se ela tiver ao menos `2 * ANCHOR_LENGTH` caracteres e não
   for o valor inteiro (esse caso é do passe anterior).

**Por que uma âncora fixa basta.** Um fragmento aceitável `valor[a:b]` tem
`b - a >= 2*ANCHOR`, logo `b >= 2*ANCHOR`; e `a <= b - 2*ANCHOR`, com `a >= 0`. O bloco
`valor[ANCHOR:2*ANCHOR]` está contido em qualquer fragmento que comece em `a <= ANCHOR` e
termine em `b >= 2*ANCHOR` — e todo fragmento de tamanho mínimo satisfaz a segunda
condição, então basta buscar as ocorrências desse bloco e expandir. Expansão maximal só
aumenta o fragmento, então tomar a maior nunca descarta um fragmento que passaria.

⚠️ A invariante que sustenta isso é `MIN >= 2 * ANCHOR_LENGTH`, e ela fica escrita junto
da constante. Mexer no mínimo sem revisar a âncora quebra a garantia em silêncio.

**Sem teto de sobra e sem limiar de proporção.** A revisão anterior desta spec propunha `MAX_AFFIX_LENGTH = 16`; medido, ele é redundante depois da porta de 3.4 — com
`|frag| >= 32` e a porta, sobra exatamente 1 candidato admitido neste fluxo, com ou sem o
teto. Fica de fora: menos um número arbitrário.

O tamanho mínimo **não** é um critério semântico ("grande logo confiável"); é o piso de
granularidade da busca, e existe para não gerar extrator de pedaço de 4 caracteres. Numa
revisão independente, com uma regra de fragmento de piso 4 e delimitadores, um fragmento
`'gzip'` sobreviveu à porta de época (o `content-encoding` do step 14 difere entre as
épocas por causa do proxy) — o piso de 32 é o que evita essa classe.

### 3.2 — `OriginFinder`: passe de fragmento depois do passe de valor inteiro

`find` ganha um segundo passe, **na mesma chamada**, executado só quando o passe atual
(valor inteiro, todas as variantes) não achou nada.

- **Estado atual:** devolve o primeiro step elegível cujo texto contém o valor inteiro, ou
  `None`.
- **Estado esperado:** idem; se `None`, percorre **todos** os steps elegíveis aplicando
  `FragmentMatcher` ao valor cru e devolve `OriginMatch` com o fragmento preenchido, ou
  `None`.

Regras:

1. **Desempate: maior fragmento; em empate, o step mais recente** (decisão registrada na
   spec de 13/08, §6). Diferente do passe de valor inteiro, que devolve o step mais
   antigo: lá todos os steps que casam trazem a mesma evidência; aqui a evidência **é** o
   tamanho do pedaço.
2. **Sem `ValueVariants`.** O passe de fragmento roda só sobre o valor cru, por motivo
   estrutural: o fragmento precisa ser substring do valor **como ele aparece no request**,
   senão `PlaceholderApplier` não consegue substituí-lo.
3. **`origin_key` calculado sobre o texto casado**, não sobre o valor inteiro —
   `_origin_key(step_index, matched_text)`. Neste fluxo o fragmento mora no body e o
   resultado é `origin_key=None`, medido.
4. **Custo:** o passe extra só roda para valores de ≥ 32 caracteres que já falharam por
   inteiro. Medido na simulação do fluxo completo (324 steps): **1,67 s → 2,69 s**, contra
   um `run` de 2m24s.

### 3.3 — Descoberta e verificação sempre na época do HAR

**Estado atual** (`engine_factory.py:70-83`): um diretório só, escolhido pelo modo, serve
descoberta e execução.

**Estado esperado:** dois papéis explícitos.

```python
discovery_responses_dir: Path = self.workspace.original_responses          # sempre a época do HAR
execution_responses_dir: Path = (
    self.workspace.real_responses if engine_cls.USES_NETWORK else self.workspace.original_responses
)
```

O `CandidateResolver` recebe **os dois** corpora: o de descoberta (usado por
`OriginFinder`, `TokenLocationDetector`, pela verificação do agente e pela identidade de
slot) e o de execução (usado **só** pela porta de 3.4). O `TokenResolver` continua
recebendo o diretório de execução.

Por que essa é a única pareação com significado: o valor procurado vem do request gravado
no HAR; não existe "o valor de agora" de um campo de request antes de a requisição ser
montada. A comparação atual em `--mode main` é (valor do HAR, resposta de agora), que só
funciona para valor estável entre épocas — e é exatamente o que a porta agora rejeita de
propósito.

Consequência medida: a troca é neutra para a descoberta (mesmos 17 pares, mesmas origens,
1.4), e os 17 extratores atuais produzem o mesmo valor sobre os dois corpora (17/17).

⚠️ Renomear `CandidateResolver.response_corpus` para `discovery_corpus` faz parte da
mudança — o nome atual não distingue os dois papéis, e é o mal-entendido que produziu o
defeito. `tests/unit/test_engine_factory.py:40,52` afirmam o casamento antigo e mudam
junto.

### 3.4 — Porta de admissão: só vira extrator o que mudou entre observações

**Estado atual:** todo candidato com origem encontrada vira extrator (ou literal, quando
a `TokenLocation` não é determinada).

**Estado esperado:** depois de achar a origem e antes de procurar o slot, o
`CandidateResolver` consulta o corpus de **execução** no mesmo step de origem:

| situação | veredito |
|---|---|
| o texto casado **não** aparece na resposta da execução | **mudou** → segue para o slot e gera extrator |
| o texto casado aparece igual nas duas | **estático** → não cria extrator; valor fica literal, e o candidato é registrado (3.5) |
| a resposta da execução não existe ou está vazia | **indeterminado** → não cria extrator; registrado igual |
| `--mode dry` (não há corpus de execução) | **porta não se aplica** → comportamento de hoje |

Números desta decisão (1.5): 15 casamentos inteiros e 2 fragmentos entram, **1 extrator**
sai. Os 9 extratores de coincidência de 1.2 desaparecem, e com eles as âncoras `23` e
`75` que hoje qualquer alvo autenticado arrasta.

⚠️ **`--mode dry` fica sem porta, e isso é deliberado.** Medido: em dry,
`real_responses/` tem 0 arquivos, e o dry produz hoje exatamente o mesmo conjunto de 17
extratores que o main. Sem segunda observação não há como provar que algo é estático, e a
porta significa "provado estático, pula". A alternativa (fail-closed) zeraria os
extratores em dry, inclusive o `Authorization`, que é o objetivo desta spec.

⚠️ A porta **não** substitui o piso de tamanho do fragmento nem herda a semântica de
"dinâmico" para sempre: ela é uma amostra de duas observações, e o que ela não vê está em
1.5 (custo declarado) e em 1.7 (etapa reativa).

⚠️ Terceiro caso, medido no workspace do HAR anterior: `header:Priority` = `'u=0'` foi
extraído de um header `priority` de resposta que **não existe** na época da execução. Pela
regra de texto, "não aparece" = "mudou", então a porta o admitiria e o extrator falharia
em todo replay. O fallback de 3.8 degrada isso para o literal, com aviso — é uma das
razões de 3.8 não ser opcional.

### 3.5 — Registrar no `.curl.sh` o que a porta dispensou

Sem registro, a informação "havia origem, mas o valor não muda" morre — e ela é o insumo
da etapa reativa (1.7) e da investigação humana.

- **Estado atual:** `CurlGenerator._token_comments` (`reproduction/curl_generator.py:61-71`)
  emite uma linha de dependência por token com origem e uma linha `[Unresolved N]` com os
  paths sem origem.
- **Estado esperado:** os candidatos dispensados pela porta saem numa **terceira**
  categoria, com o step de origem preservado — algo como
  `# [Static 2] header:Content-Type←0023; header:Origin←0075`. `header:Authorization` sai
  da linha `[Unresolved]` (passa a ter aresta) e os 9 valores de coincidência entram na
  linha nova em vez de sumirem sem explicação.

⚠️ As três frases (`DependencyPhrase`, `[Unresolved N]`, a nova) não podem se casar
cruzado nos padrões de `CurlTokenComment` — `DEPENDENCY_PATTERN` é o que
`compute_smart_schedule` usa para achar âncoras, e a categoria nova **não** pode virar
âncora.

### 3.6 — `OriginMatch.fragment`, `DynamicToken.origin_fragment` e `extracted_value`

```python
class OriginMatch(BaseModel):            # models/analysis.py:8-11
    step_index: int
    origin_key: Optional[str] = None
    origin_container: Optional[OriginContainer] = None
    fragment: Optional[str] = None       # None = casou o valor inteiro

class DynamicToken(BaseModel):           # models/session.py:51-61
    ...
    origin_fragment: Optional[str] = None

    @property
    def extracted_value(self) -> str:
        return self.origin_fragment or self.current_value
```

`current_value` continua sendo **o que o request carrega naquele path**;
`extracted_value` é **o que o extrator tem que produzir**. Consumidores que passam a usar
a propriedade:

| lugar | hoje | depois |
|---|---|---|
| `CandidateResolver._check_cached_slot` (`:108`) | `cached_value == candidate.current_value` | `== candidate.extracted_value` |
| `CandidateResolver._check_persisted_slot` (`:118-119`) | `result != candidate.current_value` | `!= candidate.extracted_value` |
| `CandidateResolver._generate_new_extractor` (`:139`) | `TokenLocationDetector.find(candidate.current_value, …)` | `…find(candidate.extracted_value, …)` |
| `CandidateResolver._register_extractor` (`:165`) | `captured_value = candidate.current_value` | `= candidate.extracted_value` |
| `CandidateResolver._build_literal_extractor` (`:196`) | `return {candidate.current_value!r}` | `{candidate.extracted_value!r}` |
| `AgentFactory.create` (`:48`) | `expected_value=candidate.current_value` | `=candidate.extracted_value` |
| `PlaceholderApplier._apply_token` / `_ordered_by_value_length` (`:17-32`) | substitui/ordena por `current_value` | por `extracted_value` |
| a porta de 3.4 | — | compara `candidate.extracted_value` contra a resposta da execução |

⚠️ A atribuição de `origin_fragment` acontece em `_process_candidate`, logo depois de
`_find_origin` e **antes** da porta e do `_find_slot` — inclusive no caminho de cache
positivo, senão os 12 steps seguintes ao `224` substituiriam pelo valor errado.
`_origin_cache` continua chaveado pelo valor inteiro e passa a guardar o `OriginMatch`
com fragmento.

⚠️ O afixo nunca entra no código do extrator: ele fica literal no `.curl.sh`. A
alternativa (extrator devolvendo `Bearer ` + valor) foi descartada — assa no extrator um
pedaço que é do request, não da resposta, e desalinha o `captured_value`.

### 3.7 — `_accept_persisted_slot` deixa de semear o token

- **Estado atual:** ao reaproveitar slot persistido, grava o valor extraído no
  `SessionStore` (`candidate_resolver.py:129`). Como o corpus era o da execução, o valor
  semeado era o fresco — certo por acidente.
- **Estado esperado:** a linha `self.session_store.set_token(slot_id, result)` sai. O
  registro no `registry` e o cache `_validated_values` continuam (identidade de slot,
  época do HAR); quem semeia valor é `TokenResolver.resolve_all()`, que roda em seguida
  (`engine.py:87`) lendo a época da execução.

Sem isso, o token da época do HAR entraria no `SessionStore` e nunca seria atualizado
(medido: 0 chamadas ao runner quando o token já está semeado) — o `Authorization`
congelado de novo, por outro caminho.

⚠️ Nada dentro de `analyze_step` consome `state.tokens`: `PlaceholderApplier` olha o
`registry` e a renderização só acontece em `Engine._attempt_step` (`engine.py:145`).

### 3.8 — `TokenResolver`: fallback para `captured_value` quando a extração falha

- **Estado atual:** `_refresh_token` desiste em silêncio e o token fica sem valor — o
  request sai com `{{extractor:…}}` literal dentro do header.
- **Estado esperado:** ao desistir, usar `extractor.captured_value` com aviso no stdout —
  o que `ReplayTokenResolver._fallback_to_captured` (`:69-82`) já faz no `replay`. Sem
  `captured_value`, mantém o comportamento atual.

Medido: nenhum dos 17 extratores atuais precisaria do fallback (17/17 portáveis entre
épocas) e o extrator novo do JWT também não. É rede de segurança para as duas classes que
esta spec passa a permitir criar: extrator verificado numa época e executado em outra
(3.3) e o terceiro caso da porta (3.4).

### 3.9 — Os fixtures precisam divergir entre as épocas

Consequência mais pesada da porta, e ela **tem** que estar no plano: hoje o servidor
canned devolve exatamente os mesmos valores que o HAR sintético gravou. Medido no cenário
golden `run_main`: os 7 valores dinâmicos têm origem, chave de origem, container e
`TokenLocation` idênticos nas duas épocas, e 7/7 extratores são portáveis. **Com a porta,
esse cenário passa a produzir 0 extratores** — e a rede de caracterização de todo o
pipeline de descoberta (agentes, extratores, placeholders, comentários de dependência)
apaga junto.

- **Estado atual:** `tests/fixtures/synthetic_flow.har` (10 entries) + `minimal_flow.har`,
  servidos por `CannedHttpHandler.CANNED_RESPONSES`
  (`tests/support/canned_http_handler.py:11-39`), um dicionário
  `(método, path) → CannedResponse` fixo e idêntico ao gravado no HAR.
- **Estado esperado:** os valores que devem continuar dinâmicos passam a **divergir** de
  forma determinística entre o HAR e o servidor canned (ex.: o HAR grava
  `SESSIONID=abc123sess` e o servidor devolve `SESSIONID=abc123live`). Isso é mais fiel ao
  mundo real — token de sessão muda a cada execução — e mantém a cobertura de
  `CookieAgent`/`CSSAgent`/`JSONPathAgent`/`RegexAgent`/`HeaderAgent`.
- **Mais um fixture** (`tests/fixtures/auth_flow.har`) para a classe desta spec: um `POST`
  de login cuja resposta é `{"token": "<TOKEN_DO_HAR>"}`, um `GET` seguinte com
  `Authorization: Bearer <TOKEN_DO_HAR>`, e endpoints canned que devolvem
  **sempre** `{"token": "<TOKEN_VIVO>"}` (≠ `<TOKEN_DO_HAR>`, ambos com ≥ 32 caracteres) e
  respondem `200` no recurso protegido **só** com `Bearer <TOKEN_VIVO>`, `403` caso
  contrário. É o teste que falha hoje (literal do HAR → `403`) e passa depois.

⚠️ Os cenários golden de `--mode dry` **não** mudam por causa da porta (ela não se aplica
lá), mas mudam por causa dos valores novos do fixture; e todos os cenários de rede
(`run_main`, `replay_*`) são regerados. Isso é regeneração esperada, não regressão — mas o
plano tem que declarar, cenário por cenário, o que mudou e por quê.

### 3.10 — O que explicitamente **não** muda

- **`replay` e `optimize`.** `ReplayTokenResolver` já resolve pela resposta do replay
  quando a origem está no schedule, e `compute_smart_schedule`
  (`replay/replay_runner.py:160-186`) já lê as linhas de dependência. A aresta nova entra
  sozinha nos dois; as arestas removidas saem sozinhas.
- **`ValueVariants`, `ResponseCorpus`, `BaselineDiff`, os agentes.** Nenhum muda. O agente
  que resolve o JWT é o `JSONPathAgent` existente: verificado ponta a ponta com as classes
  reais, `run_tdd_loop` devolve um `Extractor` `AgentType.JSONPATH` com `data['token']`,
  que produz o JWT do HAR sobre `original_responses/` e o JWT fresco sobre
  `real_responses/` — e esse valor fresco é aceito pelo servidor
  (`GET /api/user` → `200`; sem token → `403`).
- **A estimativa de pior caso do `optimize`.** Medido: âncoras **reduzem** a estimativa
  (`[23,75,224]` → 37.831; `[224]` → 49.730) porque particionam a busca, e aumentam o
  backbone (76 steps → 1). A porta remove âncoras, então o backbone encolhe e a estimativa
  sobe; nenhum dos dois efeitos muda o resultado do comando, e nenhum ajuste de
  `--max-requests` faz parte desta spec.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `tracking/fragment_matcher.py` → `FragmentMatcher` | **novo**: maior fragmento comum expandido da âncora `valor[16:32]`, mínimo `2 * ANCHOR_LENGTH`, invariante escrita (3.1) |
| `tracking/origin_finder.py` → `OriginFinder` | passe de fragmento após o de valor inteiro, na mesma chamada; desempate por maior fragmento e step mais recente; `_origin_key` sobre o texto casado (3.2) |
| `models/analysis.py` → `OriginMatch` | campo `fragment` (3.6) |
| `models/session.py` → `DynamicToken` | campo `origin_fragment` + propriedade `extracted_value` (3.6) |
| `tracking/candidate_resolver.py` → `CandidateResolver` | recebe corpus de descoberta **e** de execução; propaga o fragmento (inclusive no cache positivo); **porta de admissão** (3.4); usa `extracted_value`; `_accept_persisted_slot` deixa de semear o token (3.4, 3.6, 3.7) |
| `tracking/placeholder_applier.py` → `PlaceholderApplier` | substitui e ordena por `extracted_value` (3.6) |
| `agents/construction/agent_factory.py` → `AgentFactory` | `expected_value=candidate.extracted_value` (3.6) |
| `tracking/token_resolver.py` → `TokenResolver` | fallback para `captured_value` (3.8) |
| `engines/construction/engine_factory.py` → `EngineFactory` | separa `discovery_responses_dir` de `execution_responses_dir` e passa os dois corpora ao resolver (3.3) |
| `replay/curl_token_comment.py` → `CurlTokenComment` + `CurlGenerator` | terceira categoria de linha, para o candidato dispensado pela porta, sem casar com `DEPENDENCY_PATTERN` (3.5) |
| `tests/support/canned_http_handler.py`, `tests/fixtures/synthetic_flow.har`, `tests/fixtures/auth_flow.har` | valores dinâmicos passam a divergir entre HAR e servidor canned; fixture novo da classe `Bearer` (3.9) |
| golden de `run_main` e `replay_*`, `tests/unit/test_engine_factory.py`, `test_candidate_resolver.py`, `test_origin_finder.py`, `test_token_resolver.py`, `tests/support/recording_origin_finder.py` | regeneração e acompanhamento de assinatura |

## 5. Casos de borda e comportamento de erro

**5.1 Fragmento admitido com `TokenLocation` indeterminada.** Vira `LiteralAgent` com o
**fragmento** como literal — mesmo comportamento que o valor inteiro já tem hoje. Sob a
porta, esse caminho só é alcançado por valor que muda entre observações, então é raro por
construção.

**5.2 Fragmento maximal que "vaza" além do token.** A expansão é maximal e pode incluir um
caractere vizinho compartilhado por acaso; o agente não consegue extrair exatamente aquele
texto, o laço TDD esgota e cai em `LITERAL_FALLBACK` com o fragmento. Não observado neste
fluxo.

**5.3 O fragmento de um token aparece dentro do valor de outro candidato.**
`PlaceholderApplier` substitui todas as ocorrências, então o placeholder de um token pode
aparecer dentro do header de outro — é o `-H 'Referer: {{extractor:5809b41a…}}/'` de hoje,
onde `header:Referer` não tem origem própria e ainda aparece em `[Unresolved 4]`. O
fragmento herda a borda sem alargá-la. Fora de escopo.

**5.4 Extração falha na época da execução.** Cai para `captured_value` com aviso (3.8);
o request sai com o literal, nunca com `{{extractor:…}}` cru.

**5.5 Origem existe só na época da execução.** Deixa de ser encontrada (o corpus de
descoberta muda de época). Medido: 0 pares nessa situação neste fluxo, e no golden
`run_main` a descoberta é idêntica nas duas épocas para os 7 valores.

**5.6 Steps pulados como origem.** `original_responses/` guarda a resposta gravada no HAR
também para os steps pulados (`engine.py:80-84`), enquanto `real_responses/` guarda
`status_code=0` sem corpo. A porta trata isso como **indeterminado** (3.4) e não cria
extrator — o que também elimina a classe "extrator cuja origem o replay nunca executa".

**5.7 `--mode dry`.** Sem porta (5 linhas acima). O `Authorization` passa a ter aresta e
extrator resolvendo para o valor do próprio HAR — correto: o dry não tem outra época para
consultar.

**5.8 Workspaces gerados antes desta etapa.** Continuam com as arestas antigas; `replay`/
`optimize` sobre eles seguem como hoje. Não há migração — é preciso rodar `run` de novo.

**5.9 Custo.** Passe de fragmento: 1,67 s → 2,69 s no fluxo completo (324 steps). A porta
custa uma leitura memoizada de `searchable_text` por candidato com origem. A memória não
muda de classe, mas agora **dois** `ResponseCorpus` ficam memoizados por execução (6,6 MB
cada neste workspace) em vez de um.

**5.10 Um valor genuinamente dinâmico que veio igual nas duas observações.** A porta o
deixa literal, e ele quebra no dia em que mudar. Medido que não acontece com o token
deste fluxo (3 logins → 3 tokens diferentes) e que **acontece** com requisição condicional
(`ETag` idêntico em 285/285). É o custo declarado em 1.5, e é o que a etapa reativa de 1.7
existe para resolver. O registro de 3.5 é o que torna esse caso diagnosticável por `grep`
em vez de virar mistério.

## 6. Suposições e pontos a confirmar

- **Nomes** (`FragmentMatcher`, `ANCHOR_LENGTH`, `OriginMatch.fragment`,
  `DynamicToken.origin_fragment`, `extracted_value`, `discovery_corpus`) — ajustáveis.
- **Texto e formato da linha nova de 3.5** (`[Static N]` e a seta `path←step`) —
  ajustável. **Não** é ajustável a garantia de que ela não case com `DEPENDENCY_PATTERN`.
- **`ANCHOR_LENGTH = 16`** — confirmado por medição neste fluxo; é o piso de granularidade,
  não um critério semântico. Fica `ClassVar`, não configuração de `config.json`.
- **Renomear `response_corpus` → `discovery_corpus`** custa churn em teste; confirmar se
  entra aqui.
- **Formato dos fixtures de 3.9** (quais valores divergem, quantas entries no
  `auth_flow.har`) — proposta na decisão; a exigência dura é divergência determinística e
  recurso protegido que só aceita o token vivo.
- **Ordem das etapas**: esta spec entrega a porta e a aresta; a redescoberta reativa (1.7)
  vem depois. Se a preferência for entregar as duas juntas, o plano muda de tamanho e o
  `replay` passa a receber maquinaria de descoberta — decisão de planejamento, não de
  arquitetura.

## 7. O que as revisões mudaram

**Revisão adversarial própria** (sobre a primeira redação desta spec):

| # | Antes | Depois | Origem |
|---|---|---|---|
| 1 | prazo `28/12/2026`, herdado de `correcoes.md` | **13/02/2027**, medido no `exp` do HAR atual | HAR regravado |
| 2 | "o HAR não gravou o corpo da resposta do login" | o corpo **está** gravado; o login é o step `153` | medição |
| 3 | baseline de 117 extratores / 63 `If-None-Match` | **17 e 0** — números do relatório não valem para este HAR | medição |
| 4 | "trocar o corpus resolve metade do problema" | a troca é **neutra** sozinha; quem acha o JWT é o fragmento | simulação V1×V2 |
| 5 | sementes a cada 16 caracteres | **âncora única `valor[16:32]`**, provada exata; mesmo resultado, mais rápido (2,69 s contra 3,52 s) | revisão do algoritmo |
| 6 | passe de fragmento como "segunda tentativa" | tem que rodar **na mesma chamada** — o cache de negativos com janela já teria excluído o step do login | leitura de `_find_origin` |
| 7 | (ausente) | `_accept_persisted_slot` semeando o token **congelaria** o valor da época do HAR (sonda: 0 chamadas ao runner) | sonda em processo |
| 8 | (ausente) | falha de extração deixaria `{{extractor:…}}` cru no request → fallback obrigatório | leitura de `SessionStore.render` |
| 9 | LLM como porta ou complemento | **descartada**: 5/5 com as duas épocas no prompt, **15/18 sem elas**, com erro estável (promove `http://127.0.0.1:8080` 3 de 3 vezes) | medição contra o modelo do `config.json` |
| 10 | cobertura mínima por várias peças (proposta alternativa) | **descartada**: 156 de 157 candidatos são cobríveis, e `*/*` cobre em 2 peças igual ao JWT | implementação da cobertura mínima |

**Revisão independente, contexto limpo** (subagente com acesso ao código e aos workspaces,
sem saber qual posição era de quem):

| # | O que ela derrubou ou corrigiu |
|---|---|
| 11 | **A premissa central da versão anterior era falsa.** "Casar o valor inteiro é evidência completa de origem" — não é: `searchable_text` é um blob com body binário, e os casamentos de hoje aconteceram dentro de bytes de fonte, dentro de `same-origin-allow-popups`, dentro de código JS. Reverificado por mim (1.2). É o que derrubou a assimetria "porta só para fragmentos" e levou à porta única de 3.4 |
| 12 | **Minha prova sobre `ETag` estava errada**: `output(original)` é workspace **pré-mudança** de 13/08 (gerado 16:40, código mergeado 21:07), não tem nenhum extrator de `ETag`. A conclusão sobreviveu por outra medição — headers `ETag` idênticos entre épocas em 285/285 |
| 13 | "~12 dos 17 são lixo semântico" → **9**, com os `token_id` revertidos por força bruta; os outros 8 são URL de CDN, inúteis mas não coincidência |
| 14 | "extratores desnecessários inflam o `optimize`" → **de trás para frente** no termo dominante: âncoras reduzem a estimativa de pior caso (37.831 contra 49.730) e aumentam o backbone (76 contra 1 step) |
| 15 | A porta de época **sozinha** não elimina coincidência: com piso de fragmento 4, `'gzip'` sobrevive. Daí o piso de `2 * ANCHOR_LENGTH` continuar existindo (3.1) |
| 16 | A regra tem **três** saídas, não duas: `header:Priority` "difere" só porque o header não existe na época da execução (3.4, 5.6) |
| 17 | O canal "registrar sem apagar" já existe e **não tem consumidor** (`valid_count`/`probably static`) — precedente que sustenta porta em vez de etiqueta |
| 18 | Risco latente hoje: o token do `Origin` é referenciado **576 vezes**; com `Access-Control-Allow-Origin: *` o replay mandaria `Origin: *` em 576 lugares. A porta o remove (1.7) |
| 19 | A entry 0 do HAR tem **6 headers** — a causa raiz do lixo é maior do que a documentação sugere |

## Referência

Toda alteração de código desta spec segue o padrão descrito em [[guia-de-estilo]]
(`.claude/skills/guia-de-estilo`). As decisões respeitam o princípio de genericidade de
[[arquitetura-e-fundamentos]]: `Bearer ` não é conhecido pelo código em lugar nenhum, e o
critério de "dinâmico" deixa de ser aparência (formato, tamanho, nome de header) e passa a
ser **evidência observada** — o valor mudou de uma execução para outra. O único número que
sobra é o piso de granularidade da busca por fragmento, declarado e medido.
