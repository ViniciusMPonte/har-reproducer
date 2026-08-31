# Spec — Isolamento do Cookie Jar no Reduce Anchors do Optimize

> Fonte única de verdade para gerar o `implementation_plan.md` desta etapa. Assume que
> quem escreve o plano não participou da conversa que chegou a estas decisões — tudo
> que é necessário para entender o "porquê" e o "o quê" está aqui, sem depender de nada
> além do código-fonte atual do projeto (`har_reproducer/`) e do `guia_de_estilo.md`
> ([[guia-de-estilo]]).

## 0. Sumário e glossário

**Sumário.** `ReplayOptimizer._reduce_anchors` (`har_reproducer/optimization/replay_optimizer.py:69-84`)
decide, uma âncora por vez, se ela pode ser removida da lista final que `optimize`
exporta para o `.txt` de schedule. Para testar a remoção, ele reexecuta o alvo via
`_confirm`→`_execute`, mas `_execute` sempre alimenta o `CookieJar` com **todo**
`self.backbone` antes de rodar, independente de quais índices estão de fato na lista
sendo testada naquela chamada (`_feed_cookie_jar_from_backbone_cache`,
`replay_optimizer.py:119-125`, hoje sem nenhum parâmetro que filtre por schedule).
Quando a âncora sendo testada para remoção é ela mesma parte do backbone (o caso comum:
toda âncora com índice ≤ `anchors[-2]` é membro de `self.backbone` por construção), o
cookie que só ela estabelece já está "vazado" no jar antes mesmo do teste rodar — o
teste de remoção não detecta a dependência real, e a âncora é removida por engano. O
`.txt` exportado fica sem um passo indispensável; um `replay --mode list` posterior,
num processo novo sem esse jar "quente", nunca aprende o cookie e falha, mesmo que o
`optimize` tenha reportado sucesso na própria execução.

Esta etapa corrige exatamente esse vazamento, sem alterar o comportamento de
`_run_phase1`/fase 1 nem de `_attempt`/`_resolve_range` (fase 2), onde alimentar o jar
com o backbone inteiro é comportamento correto e intencional (backbone é
pré-requisito fixo dessas duas fases, já executado de verdade antes).

**Glossário** (termos de domínio usados nesta spec, todos já existentes no código):

- **Âncora (`anchor`)**: um índice de passo escolhido por
  `ScheduleExecutor.compute_smart_schedule` como ponto de checagem obrigatório do
  schedule. `anchors` é a lista ordenada dessas âncoras para o intervalo `[from_index,
  to_index]`.
- **Backbone (`self.backbone`)**: a lista de todo índice existente entre `from_index`
  e `anchors[-2]` (penúltima âncora), calculada uma única vez na fase 1
  (`_compute_backbone`, `replay_optimizer.py:98-100`) e tratada como pré-requisito
  fixo — sempre executado antes de qualquer teste de fase 2.
- **Schedule**: o `Set[int]` de índices que uma chamada de `execute_schedule` deve
  considerar como "parte da execução" (usado por `ScheduleExecutor` para decidir
  encadeamento de tokens/cookies dependentes de outros passos do mesmo schedule).
- **Jar (cookie jar)**: instância de `CookieJar` (`har_reproducer/session/cookie_jar.py`)
  que acumula cookies por escopo (`domain`, `port`, `path`) e resolve o conjunto
  "atual" válido para uma requisição via `current()`.
- **Reduce anchors**: a fase final de `optimize()` (`_reduce_anchors`,
  `replay_optimizer.py:69-84`) que tenta remover, uma a uma, âncoras da lista final
  exportada — mantém a âncora só se removê-la fizer o alvo falhar.
- **Vazamento do backbone cache**: o bug desta spec — alimentar o jar com um cookie
  de um índice do backbone que não está de fato presente na lista sendo testada
  naquela chamada específica, mascarando uma dependência real.

## 1. Objetivo

**Problema atual.** `_reduce_anchors` pode concluir, errado, que uma âncora que
estabelece um cookie indispensável para o alvo é removível — porque o teste que ele
usa para decidir (`_confirm`→`_execute`) sempre repovoa o jar com o backbone inteiro,
não com a lista que está sendo efetivamente testada. O `.txt` final exportado por
`optimize` fica sem esse índice. Rodar esse `.txt` depois, sozinho, via `replay --mode
list --steps-file`, num processo novo — sem o jar "quente" daquela mesma execução de
`optimize` — não aprende o cookie que só a âncora removida estabelecia, e a reprodução
falha, mesmo que `optimize` tenha reportado `Optimization SUCCESSFUL`.

**Motivação real (caso Unimed) e origem do mecanismo investigado nesta spec.**
`docs/20260829-2 Correção de Extractores via CRUD no Portal Unimed/README.md`,
"Achado 5 — rotação de `JSESSIONID` no login: limite real do CRUD" (linhas 151-193):
no workspace
`/home/viniciuspontes/Documentos/Trabalho/har-files/teste-unimed/output-fix-verificacao`,
`optimize --to 106` (com `success_criteria` já reforçado, ver "Achado 3" do mesmo
README) passou a falhar de forma intermitente — `Optimization SUCCESSFUL` num run,
`aborted — faixa (87, 106) falhou mesmo com todos os candidatos incluídos` no run
seguinte, mesmo workspace, mesmos fixes. O README isola a causa raiz desse sintoma
intermitente até o step 92 (`POST /PlanodeSaude/login.action`), que às vezes dispara
`Set-Cookie: JSESSIONID=<novo>` (rotação de sessão no login, decisão do servidor), e
confirma um bug relacionado, porém distinto: o header `Cookie` literal emitido por
`CurlGenerator._header_parts` sempre vencia a flag `--cookie` no curl gerado, então o
`JSESSIONID` atualizado pelo `CookieJar` nunca chegava ao servidor via replay
isolado — já corrigido, fora desta spec (ver "O que fica fora de escopo" abaixo). O
README não investiga nem conclui nada sobre `_reduce_anchors`, `_compute_backbone`
ou remoção incorreta de âncora; a frase final do Achado 5 marca essa investigação
como deliberadamente parada ali ("é investigação, não spec de correção de
pipeline"), sem prosseguir para o `optimize`.

A ligação entre esse caso real (instabilidade de sessão do Unimed, que motivou o
extrator de `JSESSIONID` pós-login) e o mecanismo específico descrito nesta seção —
`_feed_cookie_jar_from_backbone_cache` vazando o cookie do backbone para dentro de um
teste de remoção de `_reduce_anchors` — é uma **inferência desta spec**, feita ao
investigar, à parte, por que o step de login às vezes some do `.txt` exportado pelo
`optimize` para esse mesmo fluxo. O README não chega a essa conclusão nem a
menciona; a evidência que sustenta essa spec por si só, independente do caso Unimed,
é o teste vermelho já commitado descrito a seguir.

**Evidência de procedência no próprio repositório (teste vermelho já commitado).** O
teste `tests/unit/test_replay_optimizer.py::test_reduce_anchors_does_not_remove_an_anchor_whose_cookie_the_target_genuinely_needs`
(linhas 469-499, commit `0b31dff`, já presente no branch atual) reproduz o cenário do
Achado 5 com dublês: uma âncora intermediária (step 50, análogo ao login) é a única
fonte de um cookie (`auth`) sem o qual o alvo (step 100) falha com 401; `_reduce_anchors`
remove a âncora 50 mesmo assim. Rodado nesta sessão, contra o branch atual:

```
$ uv run pytest -q tests/unit/test_replay_optimizer.py -k does_not_remove_an_anchor
...
>       assert reduced == [50], (
            f"a âncora 50 foi removida ({reduced!r}) mesmo sendo a única fonte do cookie "
            ...
        )
E       AssertionError: a âncora 50 foi removida ([]) mesmo sendo a única fonte do cookie 'auth' que o alvo exige — _feed_cookie_jar_from_backbone_cache vazou o cookie do backbone para o teste de remoção, mascarando a dependência real.
E       assert [] == [50]
...
1 failed, 43 deselected in 0.19s
```

O teste já define o contrato esperado (`reduced == [50]`) — esta etapa faz esse
teste passar, sem alterar a definição do teste em si.

**Custo de não resolver.** Todo `.txt` de schedule exportado por `optimize` contra um
fluxo cujo backbone estabelece algum cookie de sessão que uma âncora reduzível
"esconde" (rotação de sessão em login, renovação de token no meio do fluxo, etc.) fica
sujeito a reportar sucesso na própria execução de `optimize` e falhar quando
reexecutado isoladamente depois — quebrando a premissa básica do comando (`optimize`
existe para produzir um schedule mínimo que se sustenta sozinho, ver
`ReplayOptimizer.optimize`, `replay_optimizer.py:38-67`).

**O que fica fora de escopo.**

- `_run_phase1` (`replay_optimizer.py:91-96`) e `_attempt`/`_resolve_range`
  (`replay_optimizer.py:173-212`) continuam alimentando o jar com o backbone inteiro,
  sem filtro — é o comportamento correto hoje: nessas duas fases o backbone é sempre
  um pré-requisito fixo, já executado de verdade antes do teste rodar (fase 1 o
  executa diretamente; fase 2 sempre inclui o backbone inteiro dentro do `schedule` de
  cada `_attempt`, `replay_optimizer.py:209`). Nenhuma mudança de assinatura ou
  comportamento nesses métodos.
- A confirmação final de `optimize()` (`replay_optimizer.py:59`,
  `self._confirm(final_list, to_index, success_criteria)`) não muda: depois que
  `_reduce_anchors` decide corretamente quais âncoras ficam, todo índice do backbone
  presente em `final_list` roda de verdade nessa chamada (está em `ordered_indexes`),
  então alimentar o jar a partir do cache não mascara nada ali — ver seção 3.2.
- Não é escopo desta etapa investigar mais a fundo a não-determinística rotação de
  `JSESSIONID` do portal Unimed em si (mencionada como limite de investigação no
  próprio README do Achado 5) — o alvo aqui é só o mecanismo genérico do
  `ReplayOptimizer` que mascara a dependência, não o comportamento específico daquele
  portal.
- Nenhuma alteração em `CurlGenerator`/`_header_parts` (o bug de header `Cookie`
  duplicado descrito no "Achado 2" do mesmo README) — já corrigido em outro commit
  (`e849a2e`, branch `fix/cookie-header-duplicado-no-curl`), não relacionado a esta
  spec.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### 2.1 `ReplayOptimizer._execute` — `replay_optimizer.py:102-117`

```python
def _execute(self, ordered_indexes: List[int], schedule: Set[int]) -> List[Tuple[int, StepResponse]]:
    self.cookie_jar.reset()
    self._feed_cookie_jar_from_backbone_cache()
    refreshes: int = 0
    results: List[Tuple[int, StepResponse]] = self._execute_raw(ordered_indexes, schedule)
    while self._needs_reactive_refresh(results) and refreshes < self.MAX_REACTIVE_REFRESHES:
        refreshes += 1
        print(...)
        self._execute_raw(self.backbone, set(self.backbone), force_refresh=True)
        self.cookie_jar.reset()
        self._feed_cookie_jar_from_backbone_cache()
        results = self._execute_raw(ordered_indexes, schedule)
    return results
```

Ponto único de entrada de execução real usado por `_run_phase1` (via `_execute(self.backbone,
set(self.backbone))`, `replay_optimizer.py:95`), `_attempt` (via `_execute(ordered_indexes,
schedule)`, `replay_optimizer.py:210`) e `_confirm` (via `_execute(final_list, set(final_list))`,
`replay_optimizer.py:87`). Reseta o jar e o repovoa a partir do cache do backbone **duas vezes**
por chamada no pior caso: antes da primeira tentativa e, se algum resultado precisar de
"refresh reativo" (`_needs_reactive_refresh`, `replay_optimizer.py:157-158`), de novo depois de
reexecutar o backbone de verdade.

### 2.2 `ReplayOptimizer._feed_cookie_jar_from_backbone_cache` — `replay_optimizer.py:119-125`

```python
def _feed_cookie_jar_from_backbone_cache(self) -> None:
    for index in sorted(self.backbone):
        response: Optional[StepResponse] = self._backbone_response_cache.get(index)
        if response is None:
            continue
        host, port, _ = RequestUrlScope.parts_for_step(self.workspace, index)
        self.cookie_jar.feed(host, port, response.cookies, response.cookie_attributes)
```

Sem parâmetros — sempre itera `self.backbone` inteiro (a lista calculada uma única vez em
`_run_phase1`, fixa pelo resto de `optimize()`), sem saber qual `ordered_indexes`/`schedule`
está sendo testado pela chamada de `_execute` que a invocou. É este método que precisa saber
filtrar por contexto.

### 2.3 `ReplayOptimizer._confirm` — `replay_optimizer.py:86-89`

```python
def _confirm(self, final_list: List[int], to_index: int, success_criteria: List[SuccessCriterion]) -> bool:
    results: List[Tuple[int, StepResponse]] = self._execute(final_list, set(final_list))
    target_response: StepResponse = next(response for index, response in results if index == to_index)
    return Validator.validate(target_response, success_criteria)
```

Dois chamadores: `_reduce_anchors` (`replay_optimizer.py:82`, um `trial_final_list` por âncora
candidata a remoção) e `optimize()` (`replay_optimizer.py:59`, a confirmação final depois da
redução). Hoje os dois chamam `_confirm` da mesma forma — é essa indistinção que permite o
vazamento: o `_execute` interno não sabe se está testando uma remoção (onde o backbone
completo não deveria ser presumido) ou confirmando uma lista já decidida (onde tanto faz,
porque tudo que importa já está em `final_list`/`ordered_indexes`).

### 2.4 `ReplayOptimizer._reduce_anchors` — `replay_optimizer.py:69-84`

```python
def _reduce_anchors(
        self, anchors: List[int], from_index: int, to_index: int,
        kept: List[int], success_criteria: List[SuccessCriterion],
) -> List[int]:
    removable: List[int] = [anchor for anchor in anchors if anchor not in (from_index, to_index)]
    working: List[int] = list(removable)
    for anchor in reversed(removable):
        trial: List[int] = [a for a in working if a != anchor]
        trial_final_list: List[int] = sorted({from_index, to_index, *trial, *kept})
        if self._confirm(trial_final_list, to_index, success_criteria):
            working = trial
    return working
```

Único chamador de `_confirm` cujo `trial_final_list` pode **excluir** um índice que é membro
de `self.backbone` (toda âncora com índice ≤ `anchors[-2]`, que é exatamente o limite que
define o backbone via `_compute_backbone`, é membro de `self.backbone` por construção). É
exatamente esse caso — testar a ausência de um índice que o jar, hoje, alimenta de qualquer
jeito — que produz o falso positivo.

### 2.5 `ReplayOptimizer._compute_backbone` — `replay_optimizer.py:98-100`

```python
def _compute_backbone(self, from_index: int, anchors: List[int]) -> List[int]:
    boundary: int = anchors[-2] if len(anchors) >= 2 else from_index
    return [i for i in self.schedule_executor.existing_step_indexes() if from_index <= i <= boundary]
```

Confirma a relação âncora↔backbone citada acima: toda âncora exceto a última é `≤ boundary`,
logo membro do backbone.

### 2.6 `CookieJar` — `har_reproducer/session/cookie_jar.py:13-38`

`reset()` limpa `_cookies_by_scope`; `feed(response_host, response_port, cookies,
attributes)` grava cada cookie sob um escopo `(domain, port, path)`; `current(request_host,
request_port, request_path)` mescla os escopos compatíveis com a requisição. Não tem noção de
"schedule" nem de proveniência (qual índice/execução alimentou qual cookie) — é só um
acumulador de estado; a responsabilidade de decidir **o que** alimentar é inteiramente de
`ReplayOptimizer._feed_cookie_jar_from_backbone_cache`.

### 2.7 Teste vermelho de referência — `tests/unit/test_replay_optimizer.py:441-499`

`_CookieGatedScheduleExecutor` (linhas 441-466) simula um servidor que só responde 200 no
índice `gate_index` se `required_cookie` já estiver no jar no momento da chamada.
`test_reduce_anchors_does_not_remove_an_anchor_whose_cookie_the_target_genuinely_needs`
(linhas 469-499) monta `optimizer.backbone = [0, 50]`, popula
`optimizer._backbone_response_cache[50]` com o cookie `auth`, e espera
`optimizer._reduce_anchors([0, 50, 100], 0, 100, [], SUCCESS_CRITERIA) == [50]`. Ver seção 1
para o output exato de rodar esse teste hoje (falha).

Testes vizinhos que travam o comportamento que **não pode mudar** (fora de escopo, seção 1):

- `test_execute_feeds_jar_from_backbone_cache_before_calling_execute_raw`
  (linhas 770-782) — chama `optimizer._execute([5], {5})` diretamente, com
  `optimizer.backbone = [0]` cacheado, e espera que o jar seja alimentado com o cookie do
  índice 0 **mesmo esse índice não estando em `ordered_indexes`/`schedule`
  (`{5}`)** — trava o comportamento "default" de `_execute`/`_feed_cookie_jar_from_backbone_cache`
  (alimentar o backbone inteiro, sem filtro) que `_run_phase1` e `_attempt` continuam
  precisando.
- `test_feed_cookie_jar_from_backbone_cache_populates_jar_for_cached_backbone_indexes` e
  `test_feed_cookie_jar_from_backbone_cache_skips_indexes_without_cached_response`
  (linhas 747-767) — chamam `optimizer._feed_cookie_jar_from_backbone_cache()` sem
  argumento nenhum, travando que essa chamada continua válida e com o comportamento atual
  (alimentar tudo) quando nenhum filtro é passado.
- `test_reduce_anchors_removes_interior_anchor_when_target_alone_still_passes`
  (linhas 412-424) — `_reduce_anchors` continua removendo uma âncora genuinamente
  desnecessária (`optimizer.backbone` fica `[]` nesse teste, então o filtro novo não
  tem efeito nenhum ali; serve de garantia de não-regressão do caso "remoção correta").

## 3. Decisões de arquitetura

### 3.1 `_execute`/`_feed_cookie_jar_from_backbone_cache` passam a aceitar um filtro opcional de índices do backbone a alimentar

**Estado atual → estado esperado.**

`_feed_cookie_jar_from_backbone_cache` não recebe parâmetro algum e sempre itera
`self.backbone` inteiro. Passa a aceitar um `Optional[Set[int]]` — quando `None` (default),
comportamento idêntico ao atual (alimenta tudo); quando um `Set[int]` é passado, alimenta só
os índices do backbone que também estão nesse conjunto:

```python
def _feed_cookie_jar_from_backbone_cache(self, restrict_to: Optional[Set[int]] = None) -> None:
    for index in sorted(self.backbone):
        if restrict_to is not None and index not in restrict_to:
            continue
        response: Optional[StepResponse] = self._backbone_response_cache.get(index)
        if response is None:
            continue
        host, port, _ = RequestUrlScope.parts_for_step(self.workspace, index)
        self.cookie_jar.feed(host, port, response.cookies, response.cookie_attributes)
```

`_execute` ganha o mesmo parâmetro opcional, repassado às duas chamadas internas de
`_feed_cookie_jar_from_backbone_cache` (a inicial e a que roda depois do refresh reativo —
ambas precisam do mesmo filtro dentro de uma mesma chamada de `_execute`, senão o refresh
reativo reintroduziria o vazamento que a primeira chamada evitou):

```python
def _execute(
        self, ordered_indexes: List[int], schedule: Set[int],
        restrict_backbone_feed_to: Optional[Set[int]] = None,
) -> List[Tuple[int, StepResponse]]:
    self.cookie_jar.reset()
    self._feed_cookie_jar_from_backbone_cache(restrict_backbone_feed_to)
    refreshes: int = 0
    results: List[Tuple[int, StepResponse]] = self._execute_raw(ordered_indexes, schedule)
    while self._needs_reactive_refresh(results) and refreshes < self.MAX_REACTIVE_REFRESHES:
        refreshes += 1
        print(...)
        self._execute_raw(self.backbone, set(self.backbone), force_refresh=True)
        self.cookie_jar.reset()
        self._feed_cookie_jar_from_backbone_cache(restrict_backbone_feed_to)
        results = self._execute_raw(ordered_indexes, schedule)
    return results
```

`_confirm` ganha o mesmo parâmetro opcional, repassado a `_execute`:

```python
def _confirm(
        self, final_list: List[int], to_index: int, success_criteria: List[SuccessCriterion],
        restrict_backbone_feed_to: Optional[Set[int]] = None,
) -> bool:
    results: List[Tuple[int, StepResponse]] = self._execute(final_list, set(final_list), restrict_backbone_feed_to)
    target_response: StepResponse = next(response for index, response in results if index == to_index)
    return Validator.validate(target_response, success_criteria)
```

`_reduce_anchors` passa a chamar `_confirm` restringindo o feed exatamente ao
`trial_final_list` que está testando:

```python
if self._confirm(trial_final_list, to_index, success_criteria, restrict_backbone_feed_to=set(trial_final_list)):
    working = trial
```

Todo outro chamador (`_run_phase1`, `_attempt`, e a confirmação final em `optimize()`,
`replay_optimizer.py:59`) continua chamando sem o novo parâmetro — `None`, comportamento
idêntico ao atual, preservado por default de parâmetro (nunca por `if/else` duplicando
lógica).

**Razão da escolha.** O sintoma não é "alimentar o backbone inteiro é errado" — é errado só
quando a própria chamada está testando se um membro *daquele* backbone pode ficar de fora da
lista final. `_run_phase1` executa o backbone de verdade antes de cachear (não há teste de
ausência ali). `_attempt` sempre inclui o backbone inteiro dentro do `schedule` que passa a
`_execute` (`replay_optimizer.py:209`, `schedule = set(backbone) | set(kept_so_far) |
set(ordered_indexes)`) — backbone nunca é "candidato a ausência" em fase 2, é
pré-requisito fixo por definição de fase 2 (spec do próprio algoritmo: fase 2 resolve faixas
*entre* âncoras, assumindo o backbone já estabelecido). Só `_reduce_anchors` testa a ausência
de um índice que é, ele mesmo, parte do backbone. Um parâmetro opcional que by-default
preserva o comportamento atual, e que só o chamador que precisa de semântica diferente
(`_reduce_anchors`) aciona, é a mudança de menor superfície possível — não duplica
`_execute`/`_feed_cookie_jar_from_backbone_cache` em dois métodos quase iguais, e não altera
nenhuma assinatura pública do módulo (`optimize`) nem o contrato de `_run_phase1`/`_attempt`.

**Alternativa descartada: filtrar sempre por `schedule` (o parâmetro que `_execute` já
recebe), sem parâmetro novo.** Foi a primeira hipótese considerada — `_feed_cookie_jar_from_backbone_cache`
filtraria por `schedule ∩ self.backbone` em toda chamada, sem exceção. Descartada porque
quebra o teste `test_execute_feeds_jar_from_backbone_cache_before_calling_execute_raw`
(`tests/unit/test_replay_optimizer.py:770-782`), que chama `_execute([5], {5})` diretamente
com `optimizer.backbone = [0]` cacheado e espera o jar alimentado com o cookie do índice 0
mesmo esse índice não estando em `{5}` — esse teste trava o contrato de que `_execute`, por
si, sempre alimenta o backbone inteiro por default; é o chamador (`_reduce_anchors`) que
precisa pedir explicitamente o comportamento restrito, não `_execute` que precisa adivinhar a
partir de `schedule`. Além disso, mesmo em produção (fora do teste unitário), amarrar o filtro
a `schedule` seria uma coincidência frágil: `schedule` em `_attempt` só inclui o backbone
inteiro porque `_attempt` o constrói assim (`replay_optimizer.py:209`) — mudar essa construção
no futuro quebraria silenciosamente o feed do backbone em fase 2, sem nenhum teste apontando
por quê. Um parâmetro nomeado e opcional é explícito sobre a intenção; um filtro implícito por
`schedule` não seria.

### 3.2 A confirmação final de `optimize()` (`replay_optimizer.py:59`) não muda

**Estado esperado.** `self._confirm(final_list, to_index, success_criteria)` continua sem o
novo parâmetro (`restrict_backbone_feed_to=None`, comportamento atual).

**Razão.** Depois que `_reduce_anchors` (3.1) decide corretamente quais âncoras do backbone
ficam, `final_list = sorted({from_index, to_index, *reduced_anchors, *kept})`
(`replay_optimizer.py:58`) já contém só o que resistiu ao teste de remoção — nenhum índice
removido incorretamente para mascarar. A chamada `_confirm(final_list, ...)` roda `_execute(
final_list, set(final_list))`: todo índice do backbone presente em `final_list` está,
portanto, dentro de `ordered_indexes`, e roda de verdade nessa própria chamada (via
`_execute_raw`) — o que **não** está em cache (ou está com `force_refresh`) é buscado de novo.
Alimentar o jar a partir do cache do backbone antes disso não masca nada, porque o índice vai
rodar de qualquer jeito e sobrescrever/confirmar o mesmo cookie organicamente. É exatamente o
comportamento que, segundo o Achado 5 do README (linha 169-171), já funciona hoje: "o
`CookieJar` aprende essa rotação corretamente (`feed()` roda depois de toda resposta,
`har_reproducer/replay/replay_runner.py:118`)" — um `replay --mode list` real, num processo
novo, reaprende organicamente qualquer índice presente no `.txt` exportado. O problema nunca
foi "o jar não aprende" — foi "o índice não devia ter sido removido do `.txt` para começo de
conversa". Corrigir só a decisão de remoção (3.1) já fecha o problema descrito no Objetivo,
sem precisar tocar na confirmação final.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `ReplayOptimizer._feed_cookie_jar_from_backbone_cache` (`replay_optimizer.py:119-125`) | Ganha parâmetro opcional `restrict_to: Optional[Set[int]] = None`; filtra os índices do backbone alimentados quando não-`None`. Comportamento atual preservado por default. |
| `ReplayOptimizer._execute` (`replay_optimizer.py:102-117`) | Ganha parâmetro opcional `restrict_backbone_feed_to: Optional[Set[int]] = None`, repassado às duas chamadas internas de `_feed_cookie_jar_from_backbone_cache` (inicial e pós-refresh reativo). |
| `ReplayOptimizer._confirm` (`replay_optimizer.py:86-89`) | Ganha parâmetro opcional `restrict_backbone_feed_to: Optional[Set[int]] = None`, repassado a `_execute`. |
| `ReplayOptimizer._reduce_anchors` (`replay_optimizer.py:69-84`) | Chama `_confirm(..., restrict_backbone_feed_to=set(trial_final_list))` — único chamador que passa o filtro. |
| `ReplayOptimizer._run_phase1`, `ReplayOptimizer._attempt`, confirmação final em `optimize()` | Sem alteração de código — continuam chamando sem o novo parâmetro, preservando o comportamento atual (alimentar o backbone inteiro). |

## 5. Casos de borda e comportamento de erro

- **Âncora do backbone que estabelece um cookie que o alvo precisa, e é de fato
  indispensável (caso do Achado 5/teste vermelho da seção 2.7).** Com o filtro em vigor,
  o trial que exclui essa âncora não tem o cookie no jar; o servidor (ou, em teste, o
  `_CookieGatedScheduleExecutor`) recusa o alvo; `_confirm` retorna `False`; a âncora
  permanece em `working` e acaba na lista final. Comportamento esperado, é o que o teste
  vermelho da seção 2.7 fecha.
- **Âncora do backbone que estabelece algum cookie, mas que o alvo não depende de fato
  dele (âncora genuinamente removível, mesmo sendo membro do backbone).** O fix não
  adiciona nenhuma regra que impeça remoção de índices do backbone — ele só para de
  mascarar. Se o alvo passa no critério de sucesso mesmo sem aquele cookie específico no
  jar (porque não depende dele, ou porque outro índice do próprio `trial_final_list`
  estabelece um cookie equivalente ao rodar de verdade), `_confirm` retorna `True` e a
  âncora continua sendo removida normalmente — o teste `test_reduce_anchors_removes_interior_anchor_when_target_alone_still_passes`
  (seção 2.7) é a garantia de não-regressão desse caso (nesse teste `optimizer.backbone`
  é `[]`, então o filtro não interfere, mas o critério "não force manter o que não
  precisa" continua sendo decidido empiricamente pelo `Validator.validate` a cada trial,
  não por uma lista de exceções hardcoded). Distinguir os dois casos não exige lógica
  nova: é o mesmo teste de sucesso/falha que `_reduce_anchors` já fazia, agora só sem o
  vazamento que enviesava o resultado para "sempre passa".
- **Refresh reativo dentro de `_execute` (`_needs_reactive_refresh`,
  `replay_optimizer.py:107-116`) acontecendo durante um trial de `_reduce_anchors`.** O
  filtro (`restrict_backbone_feed_to`) é repassado às duas chamadas de
  `_feed_cookie_jar_from_backbone_cache` dentro de `_execute` (seção 3.1) — a
  reexecução do backbone completo via `_execute_raw(self.backbone, set(self.backbone),
  force_refresh=True)` continua rodando de verdade (não é filtrada; é sempre o backbone
  inteiro reexecutado, comportamento já existente e fora de escopo), mas o **jar** só é
  repovoado, depois disso, com os índices ainda dentro do filtro — sem essa consistência,
  o refresh reativo reintroduziria o mesmo vazamento numa segunda chamada dentro da
  mesma execução de `_execute`.
- **`trial_final_list` no meio de `_reduce_anchors` nunca inclui um índice fora do
  backbone que dependa de outro índice do backbone que não seja o próprio `from_index`/
  `to_index`/`kept`.** Não é um caso novo desta spec — `kept` (resultado de `_run_phase2`)
  já é assumido correto e imutável durante `_reduce_anchors`; esta etapa não reabre essa
  suposição.
- **`self.backbone` vazio ou com um único elemento (`anchors` com menos de 2 itens,
  `_compute_backbone` degenerado, `replay_optimizer.py:98-100`).** `restrict_to`
  filtrando um `self.backbone` vazio não muda nada (`for index in sorted([])` não
  itera) — mesmo comportamento de hoje, sem caso especial a tratar.

## 6. Suposições e pontos a confirmar

Nenhuma — a decisão de arquitetura (seção 3) está totalmente ancorada no código existente e
no teste vermelho já commitado (seção 2.7), sem depender de nenhuma escolha de produto ainda
em aberto.

## 7. Referência

Toda implementação desta spec segue o padrão de código descrito em `guia_de_estilo.md`
([[guia-de-estilo]]) — tipagem explícita em toda assinatura nova (`Optional[Set[int]]`
explícito, nunca `Any`), sem comentários/docstrings, guard clauses em vez de aninhamento, e
sem construir dependências dentro de método que não seja raiz de composição.
