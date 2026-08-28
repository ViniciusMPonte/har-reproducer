# Spec — Correção do Bug de `request.url` Templado no `CookieJar`

## 0. Sumário e glossário

`docs/20260828 Reteste do Portal Unimed com Jar de Cookies/README.md` (seção
"Bug real encontrado — regressão causada pela integração do jar") documentou,
com reprodução real e determinística contra o portal Unimed Rio Preto, um
`ValueError` não tratado que derruba o comando `run` inteiro (exit code 1)
sempre que a URL real de um step é *idêntica* ao `captured_value` de um token
dinâmico já extraído em um step anterior. A causa é `Engine._attempt_step`
(`har_reproducer/engines/engine.py:155`) ler `step.request.url` depois que
esse campo já foi mutado in-place, em memória, por
`PlaceholderApplier._replace_in_url` — substituído por um placeholder de
extractor não resolvido (`{{extractor:<token_id>}}`) — e passar essa string
templada para `RequestUrlScope.parts`, que chama `urlparse(...).port` e
explode ao tentar interpretar o trecho depois do placeholder como número de
porta.

Esta spec corrige exclusivamente esse ponto de leitura errado no `Engine`,
sem tocar em nenhum modelo de dado (nenhum campo novo, nenhum impacto em
golden trees) e sem mudar a ordem de operações do pipeline de `run`. A
investigação desta spec (seção 2/3) confirma, lendo o código real, que os
outros dois pontos de integração do jar (`ReplayRunner._run_step` e
`ReplayOptimizer._feed_cookie_jar_from_backbone_cache`) **já** leem a URL de
uma fonte segura (o arquivo persistido em disco, escrito antes da mutação) —
não precisam de correção. O `Engine` é o único dos três que, por já ter
`step.request.url` disponível em memória, usou esse campo diretamente em vez
de reaproveitar o mesmo utilitário (`RequestUrlScope.parts_for_step`) que os
outros dois já usam — essa assimetria não intencional é a causa raiz de fundo.

Glossário:

- **URL templada**: valor de `step.request.url` depois que
  `PlaceholderApplier._replace_in_url` substitui, em memória, qualquer
  substring igual ao `extracted_value` de um token dinâmico já verificado por
  um placeholder de texto `{{extractor:<token_id>}}`. É o valor correto e
  esperado para montar `curl_template` (resolvido de volta por
  `SessionStore.render` antes de virar tráfego real) — mas é a URL errada
  para qualquer código que precise da URL *real* do HAR.
- **URL persistida**: o conteúdo de `Workspace.request_file(index)` — grava a
  `StepRequest` completa (inclusive `.url`) no disco, em
  `Engine._persist_request_step` (`engine.py:111-112`), chamado **antes** de
  `TokenTracker.analyze_step` mutar `step.request.url`. É sempre a URL real
  do HAR, nunca a templada.
- **Escopo de request**: a tripla `(host, port, path)` que
  `RequestUrlScope.parts`/`parts_for_step` derivam de uma URL, usada por
  `CookieJar.feed`/`CookieJar.current` para casar cookies com requests.

## 1. Objetivo

**Problema atual:** `Engine._attempt_step` chama
`RequestUrlScope.parts(step.request.url)` (`engine.py:155`) num momento em
que `step.request.url` pode já estar templado (mutado por
`PlaceholderApplier._replace_in_url` dentro de `TokenTracker.analyze_step`,
chamado em `_process_entry`, `engine.py:93`, antes de `execute_step`,
`engine.py:96`). Isso é comportamento pré-existente e inofensivo até a
integração do jar (`docs/20260827 Jar de Cookies Determinístico entre
Steps/spec.md`), porque nada antes disso rodava `urlparse(...).port` sobre
esse campo — `CurlGenerator._curl_parts` (`curl_generator.py:24`) também lê
`request.url` depois da mutação, mas só para embuti-lo como texto num
template de curl, nunca para fazer parsing estrutural de porta.

**Custo de não resolver:** qualquer HAR real em que a URL de algum step
coincida, como substring completa, com o `captured_value` de um token
dinâmico já extraído (cenário confirmado real, não hipotético — step 104 do
HAR do portal Unimed, seção 3 abaixo) derruba o processo inteiro do `run`
antes de terminar, sem nenhum veredito final de sucesso/falha. Isso é uma
regressão: a mesma execução, sobre o mesmo HAR, completava 107/107 steps
antes da integração do jar.

**O que esta mudança cobre:** trocar a fonte da URL usada por
`Engine._attempt_step` para calcular o escopo do jar — de `step.request.url`
em memória (potencialmente templado) para a URL persistida em
`Workspace.request_file(step.index)` (sempre real, nunca templada) — usando
o mesmo utilitário (`RequestUrlScope.parts_for_step`) que `ReplayRunner` e
`ReplayOptimizer` já usam hoje para o mesmo propósito. Nenhuma outra classe
muda.

**Fora de escopo nesta etapa:**

- **Tornar `RequestUrlScope.parts` tolerante a placeholders não resolvidos**
  (ex.: capturar `ValueError` e degradar para algum valor default). Cogitado
  e descartado — ver seção 3.2: mascararia o sintoma em vez de corrigir a
  causa, e esconderia silenciosamente qualquer chamada futura que cometa o
  mesmo erro de ler a URL errada.
- **Remover ou redesenhar `PlaceholderApplier`/o padrão de mutação in-place
  de `StepRequest`.** A mutação in-place é usada deliberadamente por todo o
  pipeline de `run` (`TokenTracker.analyze_step` monta `curl_template` a
  partir do `StepRequest` já templado) — seção 3 confirma que, fora do ponto
  corrigido aqui, nenhum outro consumidor de `step.request.url` depois da
  mutação espera a URL real (todos ou leem antes da mutação, ou esperam
  legitimamente o texto templado). Redesenhar esse padrão está fora do
  escopo de uma correção de bug pontual.
- **Mudar `ReplayRunner`/`ReplayOptimizer`.** Confirmado na investigação
  (seção 3) que os dois já leem de `Workspace.request_file` via
  `RequestUrlScope.parts_for_step` — fonte já segura, sem o mesmo bug.
  Nenhuma alteração necessária nesses dois componentes.

## 2. Componentes existentes reaproveitados

### `RequestUrlScope.parts_for_step` — `har_reproducer/reproduction/request_url_scope.py:20-25`

```python
@staticmethod
def parts_for_step(workspace: Workspace, index: int) -> Tuple[str, int, str]:
    request: StepRequest = StepRequest.model_validate_json(
        workspace.request_file(index).read_text(encoding="utf-8")
    )
    return RequestUrlScope.parts(request.url)
```

Já existe, já é usado por `ReplayRunner._run_step`/`attempt()`
(`replay_runner.py:115`) e por
`ReplayOptimizer._feed_cookie_jar_from_backbone_cache`
(`replay_optimizer.py:124`) — é o componente que esta spec reaproveita para
o `Engine`, sem nenhuma mudança na própria classe `RequestUrlScope`.

### `Engine._persist_request_step` — `har_reproducer/engines/engine.py:111-112`

```python
def _persist_request_step(self, index: int, request: StepRequest) -> None:
    self.workspace.request_file(index).write_text(request.model_dump_json(indent=2), encoding="utf-8")
```

Chamado em `_process_entry` (`engine.py:87`) **antes** de
`self.tracker.analyze_step(step, first_entry)` (`engine.py:93`, que é onde a
mutação acontece — ver próximo componente). Isso é o fato central que torna
a correção possível sem reordenar nada: o arquivo em
`Workspace.request_file(index)` já é escrito, hoje, sempre com a URL real —
mesmo para o step 104 do HAR do portal Unimed, cujo `step.request.url` em
memória fica templado logo em seguida. Confirmado lendo a ordem exata de
`_process_entry`:

```python
def _process_entry(self, index, entry, first_entry) -> StepResponse:
    step: Step = HARParser.parse_entry(entry, index)
    skip_reason: Optional[str] = self.skip_evaluator.skip_reason(step.request)
    step.request.is_skippable = skip_reason is not None

    self._persist_request_step(index, step.request)          # ← URL real, ainda não mutada
    self._persist_original_response_step(index, step.response)

    if skip_reason is not None:
        return self._skip_entry(index, skip_reason)

    step.analysis = self.tracker.analyze_step(step, first_entry)  # ← muta step.request.url aqui
    self.token_resolver.resolve_all()

    response: StepResponse = self.execute_step(step)          # ← _attempt_step lê step.request.url já mutado
    ...
```

### `PlaceholderApplier._replace_in_url` — `har_reproducer/tracking/placeholder_applier.py:44-46`

```python
@staticmethod
def _replace_in_url(request: StepRequest, value: str, placeholder: str) -> None:
    request.url = request.url.replace(value, placeholder)
```

Chamado por `PlaceholderApplier._apply_token`, por sua vez chamado por
`PlaceholderApplier.apply` (`placeholder_applier.py:12-14`), por sua vez
chamado por `TokenTracker.analyze_step` (`token_tracker.py:32`) — a mutação
em si, confirmada como a origem do valor templado. Nenhuma mudança nesta
classe: ela está correta para o propósito dela (montar `curl_template`);
o bug é só o `Engine` ler `step.request.url` depois dela sem saber que o
campo mudou de forma.

### `RequestUrlScope.parts` — `har_reproducer/reproduction/request_url_scope.py:12-18`

```python
@staticmethod
def parts(url: str) -> Tuple[str, int, str]:
    parsed: ParseResult = urlparse(url)
    host: str = parsed.hostname or ""
    port: int = parsed.port or RequestUrlScope.DEFAULT_PORT_BY_SCHEME.get(parsed.scheme, 443)
    path: str = parsed.path or "/"
    return host, port, path
```

`parsed.port` é uma `property` de `urlparse` que faz `int()` sobre o trecho
depois do último `:` no netloc — é aqui que o `ValueError` documentado no
README acontece, quando o netloc é
`autorizador.unimedriopreto.com.br{{extractor:1ffddbb23226d78793a396c2f6044705}}`
(sem `/` separando host de placeholder). Nenhuma mudança nesta classe: ela
está correta — o bug é a string de entrada, não o parsing.

### `Engine._attempt_step` — `har_reproducer/engines/engine.py:152-159` (estado atual, o bug)

```python
def _attempt_step(self, step: Step) -> StepResponse:
    assert self.http_transport is not None
    curl_literal: str = self.session_store.render(step.analysis.curl_template)
    host, port, path = RequestUrlScope.parts(step.request.url)
    curl_with_jar: str = self.cookie_jar_curl_override.apply(curl_literal, host, port, path)
    response: StepResponse = self.http_transport.send_request(curl_with_jar, step.index)
    self.cookie_jar.feed(host, port, response.cookies, response.cookie_attributes)
    return response
```

A linha `RequestUrlScope.parts(step.request.url)` é o único ponto a mudar
nesta spec (seção 3.1).

## 3. Decisões de arquitetura

### 3.1 `Engine._attempt_step` passa a usar `RequestUrlScope.parts_for_step`

**Estado atual** (`engine.py:155`):

```python
host, port, path = RequestUrlScope.parts(step.request.url)
```

**Estado esperado:**

```python
host, port, path = RequestUrlScope.parts_for_step(self.workspace, step.index)
```

`self.workspace` já é atributo existente de `Engine` (`engine.py:35`) —
nenhuma dependência nova. `RequestUrlScope.parts_for_step` já existe, sem
alteração (seção 2). O resto de `_attempt_step` (linha do `curl_literal`,
aplicação do override, envio, `feed`) não muda.

**Por que esta opção, e não as alternativas consideradas:**

- **Extrair `host`/`port`/`path` do `curl_literal`** (já resolvido por
  `session_store.render`, disponível na mesma função). Descartada: exigiria
  reimplementar, dentro de `Engine`, uma forma de achar a URL dentro de um
  comando `curl` já tokenizado (a primeira posição depois de `curl -X
  <METHOD>` — `CurlGenerator._curl_parts`, `curl_generator.py:23-24`, é o
  único lugar que hoje sabe esse formato), duplicando conhecimento de
  estrutura do curl que `RequestUrlScope`/`CookieJarCurlOverride` não têm
  hoje e que o guia de estilo pede para não duplicar ("duplicação de lógica
  vira constante/coleção"). Também acopla `RequestUrlScope` ao formato
  específico de texto que `CurlGenerator` produz — o oposto do princípio de
  genericidade do projeto (não assumir formato fixo).
- **Guardar a URL original num campo novo do modelo** (ex.:
  `StepRequest.original_url`), populado antes da mutação e lido por
  `_attempt_step`. Descartada: qualquer campo novo em `StepRequest` é
  serializado por `_persist_request_step`
  (`request.model_dump_json(indent=2)`) e aparece em todo `req_*.json` — que
  é comparado byte a byte pelos testes golden de ponta a ponta (`tests/golden/`,
  README do projeto, seção "Testes"). Isso obrigaria regravar toda árvore
  golden que inclui um `req_*.json` (já aconteceu antes, de forma análoga,
  com `cookie_attributes` em `StepResponse` — `implementation_plan.md` da
  spec de 20260827 registra que essa regeneração só foi percebida ao rodar a
  suíte `--runslow`, não ao planejar a task). Um campo novo é estritamente
  mais invasivo do que reaproveitar um utilitário que já lê exatamente o
  arquivo que esse campo duplicaria.
- **Fazer `RequestUrlScope.parts` tolerante a `ValueError`** (capturar a
  exceção e devolver algum host/port/path default). Descartada: mascara o
  sintoma sem corrigir a causa — a URL continuaria errada (templada), só o
  crash desapareceria, e o jar aplicaria/consultaria cookies pelo escopo
  errado silenciosamente (pior do que crashar, porque não é mais visível).
  Viola a regra do guia de estilo de não "simplificar" defensivamente um
  caso sem avisar — aqui seria pior, seria esconder um bug real atrás de um
  fallback.
- **Reordenar `_process_entry` para calcular o escopo antes de
  `analyze_step` rodar, e repassar `host`/`port`/`path` como parâmetros até
  `_attempt_step`.** Funcionaria (a URL ainda não estaria templada nesse
  ponto), mas exigiria mudar a assinatura de `execute_step`/`_attempt_step` e
  do `lambda` passado a `StepRetryPolicy.execute` (`engine.py:148-150`) para
  carregar três valores adicionais, só para reproduzir uma leitura que
  `RequestUrlScope.parts_for_step` já faz de forma equivalente e mais barata
  (reaproveitando o arquivo que já é escrito de qualquer forma). Também
  quebraria a simetria com `ReplayRunner`/`ReplayOptimizer` (seção 3.2): os
  três modos passariam a calcular o escopo de formas estruturalmente
  diferentes, em vez de todos reaproveitarem o mesmo `parts_for_step`.
- **A opção escolhida** (`parts_for_step`) tem o menor diff possível (uma
  linha), não toca modelo nenhum (zero impacto em golden trees), e alinha o
  `Engine` ao mesmo padrão que `ReplayRunner`/`ReplayOptimizer` já usam —
  fechando a assimetria que a seção 0 aponta como causa raiz de fundo (o
  `Engine` foi o único dos três, na spec original do jar, a não usar
  `parts_for_step` só porque `step.request.url` "já estava em mãos").

⚠️ **Efeito colateral observável, aceito deliberadamente**: com essa mudança,
o escopo do jar para o `Engine` passa a vir sempre da URL bruta do HAR (a
persistida em `request_file`), nunca de uma URL que o próprio step tenha
resolvido dinamicamente via token (ex.: um segmento de path templado por um
extractor). Isso já é o comportamento aceito e não questionado de
`ReplayRunner`/`ReplayOptimizer` desde a spec original do jar
(`docs/20260827 Jar de Cookies Determinístico entre Steps/spec.md`, seção
3.3, já usa `parts_for_step` para os dois) — esta mudança só torna o
`Engine` consistente com uma escolha de design que os outros dois modos já
tomaram, não introduz um comportamento novo no projeto.

### 3.2 Nenhuma mudança em `ReplayRunner`/`ReplayOptimizer` — confirmado seguro

A tarefa desta investigação pediu para checar os três pontos de integração
do jar, não presumir que só o `Engine` está exposto. Resultado da checagem:

**`ReplayRunner._run_step`/`attempt()` (`replay_runner.py:101-119`):**

```python
def attempt() -> StepResponse:
    ...
    curl_resolved: str = self.session_store.render(curl_text)
    host, port, path = RequestUrlScope.parts_for_step(self.workspace, index)
    curl_with_jar: str = self.cookie_jar_curl_override.apply(curl_resolved, host, port, path)
    ...
```

Já usa `parts_for_step`, que lê `workspace.request_file(index)` — o mesmo
arquivo que `Engine._persist_request_step` grava **antes** da mutação do
`PlaceholderApplier` (seção 2). Como `ReplayRunner` roda sobre um workspace
que um `run` anterior já produziu (o mesmo `request_file` gravado naquela
execução), a leitura é sempre da URL real, nunca da templada. Sem bug.

**`ReplayOptimizer._feed_cookie_jar_from_backbone_cache`
(`replay_optimizer.py:119-125`):**

```python
def _feed_cookie_jar_from_backbone_cache(self) -> None:
    for index in sorted(self.backbone):
        response: Optional[StepResponse] = self._backbone_response_cache.get(index)
        if response is None:
            continue
        host, port, _ = RequestUrlScope.parts_for_step(self.workspace, index)
        self.cookie_jar.feed(host, port, response.cookies, response.cookie_attributes)
```

Mesmo padrão — `parts_for_step` sobre o `workspace` (`ReplayOptimizer`
recebe `workspace` por construtor desde a spec de 20260827, seção 3.7, item
1). Mesmo raciocínio de segurança do parágrafo anterior. Sem bug.

**Conclusão da checagem**: dos três pontos de integração descritos na spec
original (`Engine`, `ReplayRunner`, `ReplayOptimizer`), só o `Engine` lia a
URL de uma fonte insegura (`step.request.url` em memória, pós-mutação). Os
outros dois já usavam a fonte seringura desde a implementação original —
não por proteção deliberada contra este bug especificamente, mas porque a
única forma de `ReplayRunner`/`ReplayOptimizer` obterem a URL de um step é
lendo o arquivo (eles não têm o objeto `Step` em memória, diferente do
`Engine` — spec de 20260827, seção 2, nota sobre `Workspace.request_file`:
"`ReplayRunner` e `ReplayOptimizer` podem ler esse arquivo pra obter a URL
de cada step sem precisar reparsear o texto do `.curl.sh`").

### 3.3 Varredura de todo consumidor de `step.request.url` — nenhum outro ponto quebrado hoje

A tarefa também pediu para não presumir que a mutação in-place do
`PlaceholderApplier` só afeta o jar. Todo uso de `request.url`/
`step.request.url` no código de produção (fora de `tests/`), varrido com
`grep -rn "request\.url\b"`:

| Local | Lê antes ou depois da mutação? | Espera URL real ou templada? | Está correto? |
|---|---|---|---|
| `token_tracker.py:28` (`flow_vocabulary.observe`) | Antes (`analyze_step` linha 28, mutação só na linha 32) | Real | ✅ |
| `baseline_diff.py:20,22` (`BaselineDiff.compare`) | Antes (chamado na linha 29 de `analyze_step`, antes da mutação) | Real | ✅ |
| `placeholder_applier.py:46` | É a própria mutação | — | ✅ (é a origem, não um consumidor) |
| `curl_generator.py:24` (`_curl_parts`, via `shlex.quote(request.url)`) | Depois (chamado na linha 33 de `analyze_step`, depois de `placeholder_applier.apply` na linha 32) | **Templada, de propósito** | ✅ — é assim que `curl_template` fica com o placeholder embutido, resolvido depois por `SessionStore.render` |
| `step_skip_evaluator.py:14` (`skip_reason`) | Antes (`_process_entry`, `engine.py:84`, antes de `analyze_step` na linha 93) | Real | ✅ |
| `mitm_addon.py:46` | N/A — não é `StepRequest`, é o `Request` do mitmproxy durante captura ao vivo, objeto diferente | Real (é a request de fato enviada pela rede) | ✅ — sem relação com `PlaceholderApplier` |
| `engine.py:155` (`RequestUrlScope.parts`) | Depois (linha 155, depois de `analyze_step` na linha 93) | Real (mas recebe templada) | ❌ — **o bug, corrigido na seção 3.1** |

**Conclusão**: fora do ponto corrigido nesta spec, não há outro consumidor
de `request.url` no código de produção que leia a versão errada. O único
outro consumidor pós-mutação (`CurlGenerator._curl_parts`) espera
corretamente a versão templada — é o comportamento desejado, não um bug
irmão.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `Engine._attempt_step` (`engines/engine.py:152-159`) | Troca `RequestUrlScope.parts(step.request.url)` por `RequestUrlScope.parts_for_step(self.workspace, step.index)`. Única mudança de código de produção desta spec. |
| `RequestUrlScope` | Sem alteração — `parts`/`parts_for_step` já existem e já são usados por `ReplayRunner`/`ReplayOptimizer`. |
| `PlaceholderApplier` | Sem alteração — a mutação in-place continua sendo o comportamento correto para o propósito dela (seção 3.3). |
| `ReplayRunner`/`ReplayOptimizer` | Sem alteração — já seguros (seção 3.2). |
| `tests/unit/test_engine.py` | 4 testes que chamam `engine._attempt_step(step)`/`engine.execute_step(step)` diretamente, sem passar por `_process_entry`, precisam persistir `workspace.request_file(step.index)` antes de chamar — ver seção 5. |

## 5. Casos de borda e comportamento de erro

- **Testes unitários existentes que chamam `_attempt_step`/`execute_step`
  diretamente, sem `_persist_request_step` ter rodado antes**
  (`tests/unit/test_engine.py`,
  `test_attempt_step_overrides_curl_cookie_with_jar_state_before_sending`,
  `test_attempt_step_feeds_jar_from_response_set_cookie`,
  `test_attempt_step_adds_cookie_flag_when_curl_has_none_but_jar_has_cookie`,
  `test_execute_step_retry_feeds_jar_from_first_attempt_before_second_attempt_sends`,
  todas construindo o `Step` via `_step_with_curl` e chamando
  `engine._attempt_step(step)`/`engine.execute_step(step)` sem escrever
  `workspace.request_file(step.index)`). ⚠️ Depois da mudança da seção 3.1,
  `RequestUrlScope.parts_for_step` tentaria ler um arquivo que não existe
  (`FileNotFoundError`) — esses 4 testes precisam ser ajustados para
  escrever `engine.workspace.request_file(step.index).write_text(step.request.model_dump_json(), encoding="utf-8")`
  antes de chamar `_attempt_step`/`execute_step`, replicando o que
  `_process_entry` já faz em produção. Isso não é um efeito colateral
  indesejado — é a task tornar explícito, no próprio teste, o invariante que
  a produção já garante (arquivo escrito antes do consumo). Fica detalhado
  no `implementation_plan.md` (task a definir depois da aprovação desta
  spec).
- **Step 0 (baseline)**: `request_file(0)` é sempre persistido antes de
  `analyze_step` rodar sobre o step 0 (mesma ordem de `_process_entry`) —
  nenhum tratamento especial necessário, mesmo fluxo dos demais steps.
- **Retry de step (`StepRetryPolicy.execute`, até 2 tentativas)**: cada
  tentativa chama `_attempt_step` de novo, e cada chamada relê
  `workspace.request_file(step.index)` — arquivo não muda entre tentativas
  (só é escrito uma vez, antes da primeira tentativa), então todas as
  tentativas resolvem o mesmo escopo, de forma determinística. Nenhuma
  mudança de comportamento em relação ao que a spec de 20260827 já
  documentava para retry (seção 3.5 daquela spec).
- **Step pulado (`skip_reason is not None`)**: `_skip_entry` retorna antes de
  `execute_step` ser chamado — `_attempt_step` nunca roda para esses steps,
  `RequestUrlScope.parts_for_step` nunca é chamado. Comportamento inalterado.
- **HAR cujo primeiro step já tem URL colidindo com algum token (caso
  degenerado, não observado em nenhum HAR real até hoje)**: mesmo raciocínio
  do caso geral — `request_file(0)` grava a URL real antes de qualquer
  mutação acontecer, então mesmo esse caso extremo funciona corretamente com
  a correção desta spec.

## 6. Suposições e pontos a confirmar

- Assumimos que `Workspace.request_file(index)` está sempre disponível no
  disco no momento em que `_attempt_step` roda em produção — verdade hoje,
  garantida pela ordem de `_process_entry` (seção 2), e não alterada por
  esta spec. Se uma refatoração futura do `Engine` reordenar
  `_persist_request_step` para depois de `execute_step`, essa garantia
  quebra silenciosamente (o arquivo não existiria ainda) — vale um teste de
  regressão que capture essa ordem, a incluir no `implementation_plan.md`.
- Não identificamos, na varredura da seção 3.3, nenhum HAR real (das capturas
  em `tests/golden`/`docs/`) que hoje dependa de um comportamento diferente
  do que a correção produz — mas a varredura foi sobre código de produção,
  não sobre toda captura real disponível no ambiente do projeto; o
  `implementation_plan.md` deveria prever rodar a suíte `--runslow`/os HARs
  reais de `docs/20260828 Reteste do Portal Unimed com Jar de Cookies`
  (mesmo comando da tabela de procedência daquele README) como critério de
  aceite de não-regressão, confirmando que os 107/107 steps completam sem o
  `ValueError`.

## 7. Referência

Toda implementação desta spec segue `guia-de-estilo` (tipagem explícita,
dependências por construtor, métodos privados pequenos, zero comentários no
código, tratamento de erro só nas bordas de I/O, etc.) — ver
[[guia-de-estilo]].
