# Verificação do fechamento — Token de login capturado incorretamente

**Resumo em uma frase:** o defeito específico observado em 24/08 (extrator do `JSESSIONID`
de login lendo um eco em `<script>` em vez do cookie real) está corrigido nesta nova
gravação — a causa foi puramente a captura antiga nunca ter um `Set-Cookie` real, e a
correção veio inteiramente do `har-recorder` (troca para `mitmproxy` real), sem tocar em
nenhum arquivo do pipeline de resolução do `har-reproducer`; a limitação estrutural mais
ampla (verificação tautológica em `BaseAgent._verify_code`, e o critério de sucesso que não
distingue página logada de deslogada) continua exatamente como estava, sem ter sido
acionada aqui só porque o sinal de entrada, desta vez, estava presente.

## Procedência

| item | valor |
|---|---|
| branch | `20260824-5-evidencia-de-extrator-incorreto-para-o-login` (mesma da investigação original) |
| captura nova | `/home/viniciuspontes/Documentos/Trabalho/har-files/teste-unimed/captura_20260825_184021_reduzido.har` (107 entradas) |
| ferramenta de gravação | `har-recorder`, commit `a1bcfa6` ("grava via mitmproxy real em vez de interceptar e refazer a resposta") |
| saída do `run --mode main` | `/home/viniciuspontes/Documentos/Trabalho/har-files/teste-unimed/output/` |
| config usado | `/home/viniciuspontes/Documentos/Trabalho/har-reproducer/config.json` |

## 1. A gravação nova tem `Set-Cookie` real?

Sim. Busca direta no `.har` (`log.entries[].response.headers`, filtrando `set-cookie`) e
confirmação cruzada em `output/original_responses/res_*.json` (campo `headers['set-cookie']`
e `cookies`):

| step | URL | `Set-Cookie` |
|---|---|---|
| 0 | `.../PlanodeSaude/` | `JSESSIONID=9760F3F75532F8765755431F77C8B31B; Path=/PlanodeSaude; HttpOnly` e `SERVERID=ms1; path=/` |
| 14 | `.../Wheb_Config/wheb_rodape.jsp` | `JSESSIONID=60C24DDABF08B692114B40B5B7198304; Path=/Wheb_Config; HttpOnly` |

Só esses 2 dos 107 `original_responses/*.json` têm `set-cookie`/`cookies` populados — mas
2 já é mais que os **0 em 233** da captura original (`tests/real/captures/...`, onde
nenhuma das 233 respostas tinha esse header em nenhum step, conforme a investigação de
24/08). O site usa **dois** cookies de sessão `JSESSIONID` com escopo (`Path`) diferente,
um por aplicação Java (`/PlanodeSaude` e `/Wheb_Config`).

## 2. Os extratores gerados para `JSESSIONID` agora são `CookieAgent`?

Sim, os dois. Lidos em `output/extractors/*.meta.json`:

| token_id | `agent_type` | `origin_step` | `captured_value` |
|---|---|---|---|
| `f41911849a637da03174142e36746942` | `CookieAgent` | 0 | `9760F3F75532F8765755431F77C8B31B` |
| `4366abcaced3482b036c0cde39ec3fd3` | `CookieAgent` | 14 | `60C24DDABF08B692114B40B5B7198304` |

Código de ambos (idêntico ao de `har_reproducer/agents/cookie_agent.py`, estratégia
`_by_name`):

```python
def extract_t_...(response: dict) -> str:
    cookies = response.get('cookies', {})
    value = cookies.get('JSESSIONID')
    if not value:
        raise Exception("Token not found in cookies")
    return value
```

Nenhum `RegexAgent` sobre `JSESSIONID` nesta execução — os únicos `RegexAgent`/`CSSAgent`
gerados (`46dfd744...`, `1ffddbb2...`, `e9167622...`) são para outros tokens (um valor
de callback DWR e dois caminhos de asset), não relacionados a sessão.

## 3. O valor extraído bate com o que os requests reais enviaram — respeitando o escopo?

Sim, e a divisão por `Path` é exata. Varrendo `output/real_requests/req_*.json` (campo
`cookies['JSESSIONID']`) em todos os steps posteriores à origem, agrupando por segmento de
path da URL:

| segmento da URL | valor de `JSESSIONID` enviado | bate com extrator |
|---|---|---|
| `/PlanodeSaude/...` (steps 9, 12, 15, 35–101 exceto os listados abaixo, incluindo o login `92` e a página final `106 pls_montarDadosPrestador.action`) | `9760F3F75532F8765755431F77C8B31B` | extrator `origin_step=0` |
| `/Wheb_Config/...` (steps 34, 59, 95, 102) | `60C24DDABF08B692114B40B5B7198304` | extrator `origin_step=14` |

Nenhum request de um segmento usou o valor do outro segmento — os dois `CookieAgent`
serviram exatamente o escopo certo, sem mistura. Em particular, o step 106
(`pls_montarDadosPrestador.action`, a mesma página final usada na investigação original)
recebeu `9760F3F75532F8765755431F77C8B31B`, que é o valor do extrator `origin_step=0`, e
esse mesmo valor é o que a resposta real (`output/real_responses/res_0106.json`) devolveu
com `status_code: 200`.

## 4. A ordem de prioridade cookies → headers → redirect_url → body já existia? (não foi um bugfix no pipeline)

Confirmado por leitura do código atual e por `git log`:

- `har_reproducer/tracking/token_location_detector.py::TokenLocationDetector.find` — ordem
  `_find_in_cookies` → `_find_in_headers` → `_find_in_redirect_url` → `_find_in_body`
  (linhas 12–29), igual à descrita na investigação original.
- `har_reproducer/agents/construction/agent_factory.py::AgentFactory.LOCATION_AGENTS` —
  mapeamento `TokenLocation.COOKIE: CookieAgent`, `TokenLocation.SCRIPT: RegexAgent`
  (linhas 17–22), igual.
- `git log --oneline -- har_reproducer/tracking/token_location_detector.py
  har_reproducer/agents/construction/agent_factory.py` — o commit mais recente que toca
  qualquer um dos dois arquivos é `8f6c8a3`/`43f8f8e` (série T05/T06), datado de
  **21/08/2026** (`git log -1 --format=%cd`). Nenhum commit dessa data até hoje
  (25/08/2026) tocou esses arquivos — o commit mais recente do repositório inteiro é
  `29f18cf`, de 25/08/2026, e é só a doc da investigação original.

Ou seja: a causa raiz era puramente ausência de sinal na captura de entrada (nenhum
`Set-Cookie` real em nenhuma das 233 respostas), não um bug de priorização no
`har-reproducer`. Com o sinal presente, o mesmo pipeline — sem alteração — escolheu
`COOKIE`/`CookieAgent` corretamente.

## 5. O que a investigação original apontou como "sinal ignorado"/"direção de correção" — mudou?

Não. Verificado por leitura direta do código hoje:

- `har_reproducer/agents/base_agent.py::BaseAgent._verify_code` (linhas 174–177) continua
  chamando `_execute_script` só contra `self._write_temp_script`, que serializa
  `self.response_sample` — e `response_sample` é passado por
  `CandidateResolver._generate_extractor`
  (`har_reproducer/tracking/candidate_resolver.py:151`) como
  `self.discovery_corpus.response(candidate.origin_step)`. `execution_corpus` não aparece
  em nenhum ponto de `AgentFactory.create` nem de `_verify_code` — seu único uso no arquivo
  inteiro é `_admission_gate_rejects` (linhas 76–82), a porta de admissão. A verificação
  continua tautológica: roda a regra gerada contra a mesma amostra de onde ela foi
  derivada, nunca contra uma segunda observação real.
- Essa limitação **não foi acionada** nesta verificação, porque o `origin_location` já saiu
  `COOKIE` direto da amostra de descoberta — não houve necessidade de cruzar com
  `execution_corpus` para corrigir a classificação. Isso não prova que o problema foi
  corrigido em geral: continua sendo estrutural, e voltaria a se manifestar em qualquer
  site/cenário onde a captura de descoberta também não tenha o sinal real (`Set-Cookie`,
  header de origem) mas o valor apareça ecoado em outro lugar do corpo/script.

## 6. Critério de sucesso ainda não distingue logado de deslogado?

Confirmado: `config.json` na raiz do `har-reproducer` define
`"success_criteria": [{"type": "status_code", "expected": 200}]` — nada além disso. A
pasta `docs/20260824 Sessão Congelada e Resultado Vazio do Otimizador/` **não existe** neste
repositório (só existem `docs/20260824 Sistema de Testes com Capturas Reais/` e
`docs/20260824-6 Token de Login Capturado Incorretamente/`) — não foi possível localizar
essa investigação específica para conferir o que ela levantou; o ponto é registrado aqui
apenas como observação independente, sem se aprofundar: o step 106 desta execução devolveu
`status_code: 200` com corpo HTML não vazio, mas nada nesta verificação confirmou que o
conteúdo reflete de fato uma sessão autenticada (não era o foco desta verificação).

## Antes / depois

| | 24/08 (captura antiga, `tests/real/captures/.../`) | 25/08 (captura nova, `har-files/teste-unimed/`) |
|---|---|---|
| respostas com `Set-Cookie` real | 0 de 233 | 2 de 107 (steps 0 e 14) |
| origem do `JSESSIONID` de login | eco em `<script>setCookie(...)</script>` | `Set-Cookie` genuíno |
| `origin_location` calculado | `SCRIPT` | `COOKIE` |
| agente gerado | `RegexAgent` (regex ancorada em posição) | `CookieAgent` (lê `cookies['JSESSIONID']`) |
| valor extraído vs. valor real usado depois | divergiam (`68ECB342...` extraído vs.
  `F38E7F72...` realmente enviado, no reteste da investigação) | coincidem em 100% dos
  requests verificados, respeitando os dois escopos de `Path` |
| ferramenta responsável pela mudança | — | `har-recorder`, troca de `route.fulfill` por
  proxy `mitmproxy` real |
| arquivo do `har-reproducer` alterado para a correção | — | nenhum |

## O que não foi corrigido / continua sendo risco estrutural

- `BaseAgent._verify_code` continua verificando qualquer extrator só contra a amostra de
  descoberta, nunca contra uma segunda observação real (`execution_corpus`). Um site que
  ecoe um valor de sessão/CSRF/timestamp num corpo HTML/JS, sem nunca expor um `Set-Cookie`
  ou header real para esse valor, reproduziria o mesmo problema documentado em 24/08 — esta
  correção resolveu o caso concreto porque a nova captura passou a ter o sinal, não porque
  o pipeline aprendeu a lidar com a ausência dele.
- `OriginFinder` continua sem preferência por container (cookie/header real) sobre posição
  textual bruta ao escolher a primeira ocorrência — as três "direções de correção" listadas
  na investigação original (preferir container na busca de origem, cruzar `execution_corpus`
  por container, verificar contra uma segunda amostra) não foram implementadas; nenhuma
  delas era necessária para este caso, mas nenhuma foi endereçada.
- O critério de sucesso (`status_code: 200`) não distingue página logada de deslogada —
  risco relacionado, mas fora do escopo desta verificação, e a pasta de investigação onde
  isso teria sido levantado (`docs/20260824 Sessão Congelada e Resultado Vazio do Otimizador/`)
  não existe neste repositório para conferência.

## Limites desta verificação

- Não foi feita nenhuma requisição nova contra `autorizador.unimedriopreto.com.br` — toda
  evidência vem dos arquivos já em disco (`.har`, `output/original_responses`,
  `output/real_requests`, `output/real_responses`, `output/extractors`) e da leitura do
  código-fonte do `har-reproducer` e do `har-recorder` (incluindo `git log`).
- Não foi verificado se o conteúdo da página final (`pls_montarDadosPrestador.action`,
  `status_code: 200`) reflete de fato dados de um prestador autenticado, ou uma página de
  erro/redirecionamento disfarçada de 200 — ver ponto 6 acima; ficaria para quem revisitar
  a investigação de "Sessão Congelada" (se ela existir em outro lugar) ou para uma
  verificação de conteúdo dedicada.
- Não foi testado o comportamento do pipeline num terceiro cenário (site diferente, ou esta
  mesma captura com o `Set-Cookie` artificialmente removido) para reproduzir a limitação
  estrutural apontada no item 5 "de propósito" — isso exigiria uma nova captura ou
  manipulação deliberada de dados, fora do que esta verificação (só leitura do que já está
  gravado) se propôs a fazer.
- Os números desta verificação foram obtidos com scripts Python ad hoc rodados nesta
  sessão, não versionados — os comandos exatos estão citados inline em cada seção acima e
  podem ser reexecutados sobre os mesmos artefatos em disco.
