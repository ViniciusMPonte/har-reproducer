# Token de login capturado incorretamente — investigação

**Resumo em uma frase:** o extrator gerado para o cookie de sessão do login (`JSESSIONID`)
lê um script de página (`setCookie('JSESSIONID', '...')`) que apenas *ecoa* a sessão corrente
do servidor — não a origem real do cookie — então, ao rodar em uma execução real diferente,
devolve a sessão daquela execução em vez do valor com que o cookie foi de fato usado durante
a captura original.

## Procedência

| item | valor |
|---|---|
| branch | `20260824-5-evidencia-de-extrator-incorreto-para-o-login` |
| captura | `tests/real/captures/autorizador.unimedriopreto.com.br__20260824/` (gitignored, 233 arquivos por pasta) |
| teste vermelho | `tests/real/test_candidate_resolver_unimedriopreto.py::test_login_session_cookie_extractor_should_capture_the_real_session_value` |
| comando | `uv run pytest tests/real/test_candidate_resolver_unimedriopreto.py -v` |
| código | topo da branch no momento da investigação, commit `6a98f1e` |

```
tests/real/test_candidate_resolver_unimedriopreto.py::test_login_session_cookie_is_resolved_against_the_real_capture PASSED
tests/real/test_candidate_resolver_unimedriopreto.py::test_login_session_cookie_extractor_should_capture_the_real_session_value FAILED
AssertionError: assert 'F38E7F72...3580C067FEAE1' == '68ECB342...5B2E324BFAFCF'
```

## Causa raiz, elo por elo

### 1. O candidato

`BaselineDiff().compare(step(124), step(0))` + `detect_candidates` produz o candidato
`cookie:JSESSIONID`, `current_value='68ECB342335B1F8028F5B2E324BFAFCF'`
(`har_reproducer/tracking/baseline_diff.py`) — esse é o valor de `Cookie: JSESSIONID=...`
que o request do login (step 124) de fato enviou. Confirmado rodando o snippet diretamente:

```python
BaselineDiff().detect_candidates(BaselineDiff().compare(capture.step(124), capture.step(0)))
# -> path='cookie:JSESSIONID' current_value='68ECB342335B1F8028F5B2E324BFAFCF'
```

### 2. `OriginFinder` acha a origem em `original_responses/res_0012.json`, dentro de um `<script>`

`OriginFinder.find` (`har_reproducer/tracking/origin_finder.py:17-42`) varre, em ordem
crescente de step, o texto serializado de cada resposta anterior
(`ResponseCorpus._serialize`, `har_reproducer/tracking/response_corpus.py:58-74`, que junta
headers + cookies + `redirect_url` + body num único blob) procurando o valor **inteiro**.
Primeira ocorrência: step `12`. Confirmado:

```
$ python3 -c "... busca '68ECB342...' em headers/cookies/redirect_url/body de todos os
  original_responses/res_*.json ordenados ..."
res_0012.json ['body']    # primeira ocorrência — nenhuma antes
res_0022.json ['body']
res_0124.json ['body']    # (o próprio login)
res_0172.json ['body']
res_0231.json ['body']
res_0232.json ['body']
```

E o trecho do body em `res_0012.json` (offset 10915):

```
<script type="text/javascript">setCookie('JSESSIONID', '68ECB342335B1F8028F5B2E324BFAFCF');</script>
```

`OriginMatch.origin_key`/`origin_container` ficam `None` para esse match
(`origin_finder.py:86-99`, `_exact_key` procura o valor em `cookies`/`headers` do response
de origem — em `res_0012.json` ambos estão vazios: `cookies: {}`, sem chave `set-cookie` em
`headers`). O único container real ali é o corpo HTML.

### 3. `CandidateResolver` classifica a localização como `SCRIPT` e escolhe `RegexAgent`

`_generate_new_extractor` (`har_reproducer/tracking/candidate_resolver.py:148-157`) chama
`TokenLocationDetector.find`, que remove blocos `<script>` do HTML para testar `BODY_HTML`
primeiro, não encontra o valor fora do script, testa dentro do script e retorna
`TokenLocation.SCRIPT` (`har_reproducer/tracking/token_location_detector.py:82-88`).
`AgentFactory.create` (`har_reproducer/agents/construction/agent_factory.py:18-24,44-46`)
mapeia `TokenLocation.SCRIPT -> RegexAgent`.

### 4. `RegexAgent` gera uma regex ancorada no prefixo literal daquele único script

`RegexAgent._context_pattern` (`har_reproducer/agents/regex_agent.py:26-38`) pega os 20
caracteres antes do valor **na mesma amostra de descoberta** (`res_0012.json`) e monta:

```
okie\('JSESSIONID',\ '([\w\-.]+?)(?=')
```

Extrator final registrado (rodado de fato nesta investigação):

```python
def extract_t_a24faaee063577da6e995b65aa37d04c(response: dict) -> str:
    body = response.get('body', '')
    if isinstance(body, bytes):
        body = body.decode('utf-8', errors='replace')
    match = re.search("okie\\('JSESSIONID',\\ '([\\w\\-.]+?)(?=')", body, re.DOTALL)
    if not match:
        raise Exception("Token not found via regex")
    return match.group(1)
```

`agent_type = AgentType.REGEX`. É uma regex de posição, não de conteúdo: ela devolve **o que
estiver ali**, seja qual for o valor.

### 5. Por que a verificação passou mesmo o extrator sendo, na prática, errado

`BaseAgent.run_tdd_loop` → `_verify_code` (`har_reproducer/agents/base_agent.py:151-197`)
executa o código gerado contra `self.response_sample`, que é exatamente
`discovery_corpus.response(candidate.origin_step)` — a **mesma** `res_0012.json` de onde o
prefixo da regex foi extraído (`candidate_resolver.py:151-156`, `regex_agent.py:30`). A
verificação é tautológica: constrói a regex a partir do texto de uma amostra e depois
confirma que a mesma regex, aplicada à mesma amostra, devolve o mesmo texto. Ela nunca
executa o extrator contra uma **segunda observação real** do mesmo step para checar se a
posição continua identificando o mesmo dado com significado estável. Não há, em nenhum
lugar do laço TDD, uso do `execution_corpus` — só o `discovery_corpus` entra na verificação.

### 6. Por que a origem do valor não é estável — confirmado empiricamente sem rede

Comparando o **mesmo step 12** nas duas pastas já capturadas em disco desta mesma captura:

```
$ python3 -c "... extrai o valor de setCookie('JSESSIONID', '...') do body de
  original_responses/res_0012.json e de real_responses/res_0012.json ..."
original setCookie value: 68ECB342335B1F8028F5B2E324BFAFCF
real setCookie value:     F38E7F72FEED62613BA3580C067FEAE1
original cookies dict: {}
real cookies dict: {'JSESSIONID': 'F38E7F72FEED62613BA3580C067FEAE1'}
```

E, examinando os headers crus de `real_responses/res_0012.json`:

```
set-cookie: JSESSIONID=F38E7F72FEED62613BA3580C067FEAE1; Path=/PlanodeSaude; HttpOnly
```

Ou seja: no mesmo ponto do fluxo, a segunda execução (`real_responses`, capturada pelo
próprio `mitmdump` do projeto ao reproduzir a sequência de requests — ver
`har_reproducer/reproduction/mitm_addon.py:47-79`) recebeu do servidor um `Set-Cookie` **novo**
e teve esse valor novo ecoado no mesmo `setCookie('JSESSIONID', ...)` do script. O script na
posição 12 não é a fonte do cookie — é um reflexo do estado de sessão vigente no momento em
que aquela resposta específica foi renderizada. `original_responses/res_0012.json` nunca teve
um header `set-cookie` (nenhum dos 233 `original_responses/` desta captura tem — verificado
por busca por `"cookie"` em `headers` de todos os arquivos, zero ocorrências), então o valor
`68ECB342...` já estava associado à sessão do navegador **antes** do que este HAR capturou:
ele aparece em `real_requests/req_0011.json` em diante como `Cookie: JSESSIONID=68ECB342...`,
antes mesmo do primeiro eco em `res_0012.json`. O texto casado em `res_0012.json` é efeito,
não causa.

### 7. Por que a porta de admissão (`_admission_gate_rejects`) não pegou isso

```python
# har_reproducer/tracking/candidate_resolver.py:75-82
def _admission_gate_rejects(self, candidate: DynamicToken) -> bool:
    if self.execution_corpus is None:
        return False
    execution_text = self.execution_corpus.searchable_text(candidate.origin_step)
    if not execution_text:
        return True
    return candidate.extracted_value in execution_text
```

Documentado em `docs/20260821-2 Porta de Admissão por Mudança entre Épocas/spec.md:36`: "só
vira extrator o texto casado que **difere** entre as duas épocas no mesmo blob do step de
origem". A porta rejeita (marca `Static`) exatamente quando o valor **continua** presente na
época de execução — ou seja, quando ele não mudou. Neste caso o valor mudou (68ECB342 →
F38E7F72 no mesmo step 12), então `candidate.extracted_value in execution_text` é `False`, a
porta **não** rejeita, e a geração do extrator segue — confirmado rodando o gate
manualmente:

```
$ python3 -c "ResponseCorpus(real_responses,4).searchable_text(12); print('68ECB342...' in text)"
False
```

A porta está fazendo exatamente o que a spec dela pede: distinguir valor congelado
(`Static`, correto para constantes) de valor genuinamente variável (deixa passar para gerar
extrator). O problema é que "o texto casado mudou entre duas execuções" e "esta posição é
uma fonte confiável/estável para reobter o valor certo" são coisas diferentes — a porta só
mede a primeira. Um valor que muda porque é *reflexo de um estado ambiente que o próprio
teste não controla* (a sessão que o servidor decidiu atribuir àquela execução) passa pelo
mesmo critério que um valor que muda porque é genuinamente o dado dinâmico certo a
rastrear.

## É defeito isolado deste site, ou limitação estrutural?

É estrutural. A cadeia completa — `OriginFinder` (casamento por substring bruta em texto
serializado, sem preferência por container), `TokenLocationDetector`
(`har_reproducer/tracking/token_location_detector.py`, que classifica `SCRIPT` mas nada além
disso faz com essa classificação), `AgentFactory` (mapeia `SCRIPT -> RegexAgent` sem
distinção de confiança) e `RegexAgent`/`BaseAgent._verify_code` (verificação contra a mesma
amostra da qual o padrão foi extraído) — nunca modela a diferença entre:

- um valor que **se origina** ali (ex.: um header `Set-Cookie` real, um `origin_container`
  preenchido — `har_reproducer/models` tem `OriginContainer.COOKIE`/`HEADER` para isso, mas
  só é preenchido quando o valor bate **exatamente** com uma chave de `cookies`/`headers` da
  resposta de origem, `origin_finder.py:86-99`); e
- um valor que **é apenas ecoado** ali (embutido em HTML/JS/corpo, refletindo estado de
  sessão ou de request que já existia antes daquele step).

Qualquer site que ecoe, num template de página, um valor de sessão/CSRF/timestamp
determinado pelo estado ambiente do momento da renderização (padrão comum de frameworks Java
antigos, exatamente o que este `setCookie(...)` faz) reproduz o mesmo problema: a origem
"encontrada" é a primeira ocorrência textual, não a fonte causal, e nada no pipeline testa a
extração contra uma segunda observação real antes de aceitar o extrator.

## Sinal disponível e ignorado

`real_responses/res_0012.json` **tem** um header `set-cookie` genuíno
(`JSESSIONID=F38E7F72...; Path=/PlanodeSaude; HttpOnly`) e um `cookies` dict populado com a
mesma chave — sinal gravado por `mitm_addon.py:58,75-79` a partir da resposta HTTP real. Esse
sinal:

- não é comparado, em nenhum ponto, ao `origin_location`/`origin_container` que o
  `CandidateResolver` calculou a partir do `discovery_corpus` (`original_responses`) — os
  dois corpora nunca são cruzados por container, só por presença de substring
  (`_admission_gate_rejects`, item 7 acima);
- não é usado para re-derivar/confirmar o container de origem quando o `discovery_corpus`
  não tem `Set-Cookie` para aquele step (que é exatamente o caso aqui: `original_responses`
  nunca tem header `set-cookie` nesta captura inteira, mas `real_responses` tem, em quatro
  steps — `0000`, `0012`, `0023`, `0173` — confirmado por busca em todos os `real_responses/*.json`);
- `TokenLocation.SCRIPT` em si já é um sinal de baixa confiança (é o único container que
  `TokenLocationDetector` só atinge depois de descartar cookie/header/redirect/HTML puro) que
  o `CandidateResolver` calcula mas não usa para nada alem de escolher o agente — não influi
  na porta de admissão nem na aceitação do extrator.

## Possíveis direções de correção (esboço, não decisão de design)

1. **Preferir container sobre posição textual na busca de origem.** Ao escolher entre
   ocorrências elegíveis, dar peso a um match cujo `origin_container` seja `COOKIE`/`HEADER`
   real (valor idêntico a uma chave de `cookies`/`headers` daquele step) sobre um match que só
   existe dentro do corpo/script — hoje `OriginFinder._find_variant` para no primeiro step,
   sem essa preferência.
2. **Cruzar `execution_corpus` também por container, não só por texto solto.** Se
   `execution_corpus.response(origin_step)` tiver `cookies`/`headers` reais para a mesma
   chave (`JSESSIONID`), isso é um sinal mais forte do que a busca textual — poderia informar
   a porta de admissão ou a escolha de agente (preferir `CookieAgent`/`HeaderAgent` lendo do
   header real, em vez de `RegexAgent` lendo do script) mesmo quando o `discovery_corpus`
   não tem o container.
3. **Verificar o extrator contra uma segunda amostra antes de aceitar.** Hoje
   `BaseAgent._verify_code` só roda contra a amostra de descoberta. Rodar também contra
   `execution_corpus.response(origin_step)` (quando existir) e exigir que o resultado seja
   consistente com o que a própria porta de admissão está tentando garantir — mudança de
   verificação, não de geração, então mais barata de isolar.

Nenhuma das três é a decisão final — servem de ponto de partida para quem escrever a spec
da correção.

## Limites desta investigação

- Não foi feita nenhuma requisição nova contra `autorizador.unimedriopreto.com.br` — toda
  evidência vem dos arquivos já presentes em `tests/real/captures/.../{original_responses,
  real_responses,real_requests}`.
- Não foi confirmado **onde**, antes do início desta captura (step 0), o valor
  `68ECB342335B1F8028F5B2E324BFAFCF` foi originalmente emitido pelo servidor (provavelmente
  um `Set-Cookie` de uma navegação anterior, fora da janela do HAR) — isso exigiria uma
  captura mais ampla (HAR começando antes do login) ou uma nova gravação, não apenas leitura
  do que já está em disco.
- Não foi investigado se os outros três steps com `Set-Cookie` real em `real_responses`
  (`0000`, `0023`, `0173`) representam rotação de sessão pelo próprio servidor (proteção
  contra fixação de sessão) ao longo do fluxo — relevante para entender se mesmo um extrator
  "correto" (lendo o header real em vez do script) enfrentaria o mesmo problema de
  instabilidade; ficaria para uma investigação futura sobre o comportamento do servidor, não
  sobre o código deste projeto.
- Os números de "primeira ocorrência" e "quatro steps com Set-Cookie real" foram obtidos com
  scripts Python ad hoc rodados nesta sessão, não versionados — não há arquivo de medição
  reaproveitável nesta pasta (diferente da convenção de `medições/` de
  `docs/20260820 Investigação da Porta de Admissão/`); os comandos exatos estão citados
  inline em cada seção acima e podem ser reexecutados sobre a mesma captura em disco.
