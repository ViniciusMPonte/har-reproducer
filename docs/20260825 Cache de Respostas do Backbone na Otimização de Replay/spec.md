# Spec — Cache de Respostas do Backbone na Otimização de Replay

## 0. Sumário

`ReplayOptimizer.optimize()` busca o menor conjunto de steps que ainda reproduz o
alvo (`--to`). Para isso, ele reexecuta repetidamente contra o servidor real um
prefixo fixo de steps (o "backbone", que cobre de `from_index` até a última âncora
antes do alvo) como pré-requisito de cada tentativa — inclusive `from_index`
sozinho, que entra em **toda** confirmação feita por `_confirm` (chamada uma vez
por âncora testada para remoção, mais uma vez ao final de `optimize()`). Contra um
site cujo `from_index` é uma página que sempre inicia uma sessão nova a cada hit
real (comportamento do site, não bug do projeto), cada uma dessas reexecuções
emite uma sessão diferente da que um login mais adiante na sequência autenticou —
e sobrescreve, em disco, a única cópia da resposta daquele step que os extratores
de steps posteriores conseguem ler. Quando o alvo finalmente roda, o cookie de
sessão que seu extrator lê nunca é o que o login autenticou; a resposta volta
deslogada e nenhum subconjunto de candidatos resolve isso, porque a base já mudou
debaixo da busca a cada tentativa.

Medido em 25/08/2026, rodando `optimize --to 106` contra um workspace real (site de
autorização de plano de saúde, fora deste repositório): a otimização falhou mesmo
incluindo todos os candidatos entre âncoras, incluindo um login real
(`POST .../login.action`) cuja resposta, testada isoladamente, reproduz quase byte
a byte a gravação original — a falha não está no login, está em `from_index` (step
`0`) ser reexecutado de verdade repetidas vezes ao longo da mesma busca, cada vez
com uma sessão nova, sem que nada congele qual dessas sessões é "a" que o login
autenticou. Não há uma contagem exata de requisições dessa investigação além do
que está descrito aqui — a medição é qualitativa (a busca falha de forma
consistente, não uma contagem reproduzível de tentativas).

A correção adiciona, dentro de uma única chamada a `optimize()`, um cache de
respostas restrito aos índices do **backbone** — a primeira execução real de cada
índice do backbone fica congelada para o resto da busca, e só é substituída
explicitamente pelo mecanismo de recuperação reativa (`_needs_reactive_refresh`)
já existente, que passa a forçar a reexecução ignorando o cache quando decide que
o backbone precisa de refresh. Fora do backbone (candidatos, âncoras, o próprio
alvo), nada muda — essas respostas continuam sendo executadas ao vivo a cada
tentativa, porque variar entre tentativas é o próprio mecanismo de busca do
`optimize` (ver §3.1 sobre por que isso não pode ser generalizado para "todo
índice").

### Glossário

| termo | significado nesta spec |
|---|---|
| **backbone** | `self.backbone: List[int]`, calculado uma vez por `_run_phase1`/`_compute_backbone`: os steps existentes entre `from_index` e a penúltima âncora (`anchors[-2]`), inclusive. É o prefixo fixo que toda tentativa de busca assume como pré-requisito. |
| **cache do backbone** | O dicionário novo desta spec, `Dict[int, StepResponse]`, que guarda a primeira resposta real "saudável" de cada índice do backbone dentro de uma chamada de `optimize()`, para servir em reexecuções seguintes do mesmo índice sem bater na rede de novo. |
| **congelar** | Servir, para um índice do backbone, a resposta já guardada no cache em vez de reexecutar o step contra o servidor. É o comportamento novo desta spec. |
| **forçar reexecução** (`force_refresh`) | Ignorar o cache do backbone para uma chamada específica e bater na rede de verdade, sobrescrevendo a entrada de cache correspondente com a resposta nova. É como a recuperação reativa (mecanismo já existente) invalida o cache quando decide que o backbone mudou. |
| **saudável** (para fins de cache) | Uma resposta para a qual `schedule_executor.needs_recovery(index, response)` devolve `False` — não diverge da referência conhecida daquele step (ou a referência é desconhecida, caso já tratado como "não recuperável" pelo mecanismo existente) e não é falha de transporte (`status_code == 0`). Reaproveita o método já implementado em `docs/20260821-3 Recuperação por Divergência da Referência/spec.md` — esta spec não redefine o que "saudável" significa, só o usa como filtro de admissão ao cache. |
| **recuperação reativa** | O mecanismo já implementado em `ReplayOptimizer._execute`: quando alguma resposta do lote mais recente "precisa de recuperação" (`_needs_reactive_refresh`), o backbone é reexecutado antes de tentar de novo, até `MAX_REACTIVE_REFRESHES` vezes. Esta spec **não muda o que esse mecanismo decide** — só o ponto em que ele bate na rede em vez de servir do cache. |

---

## 1. Objetivo

### 1.1 O problema

`ReplayOptimizer._confirm` (`har_reproducer/optimization/replay_optimizer.py:80-83`)
monta, a cada chamada, um `final_list` que sempre inclui `from_index`:

```python
# replay_optimizer.py:52 (dentro de optimize()) e :75 (dentro de _reduce_anchors)
final_list: List[int] = sorted({from_index, to_index, *trial, *kept})
```

`_confirm` é chamado uma vez por âncora candidata a remoção dentro de
`_reduce_anchors` (`:63-78`, um loop `for anchor in reversed(removable)`), mais uma
vez ao final de `optimize()` (`:53`). Cada uma dessas chamadas passa `final_list`
para `_execute`, que acaba em `_execute_raw`
(`:109-119`), que por sua vez chama
`self.schedule_executor.execute_schedule(ordered_indexes, schedule, annotate=False)`
— **sempre uma execução real contra o servidor**, para todo índice em
`ordered_indexes`, sem exceção. Como `from_index` está em todo `final_list`, ele é
reexecutado de verdade uma vez por âncora testada, mais uma vez no final.

Contra um site cujo `from_index` é uma página que sempre emite uma sessão nova a
cada hit real (comportamento do site, verificado nesta investigação — não uma
suposição), cada uma dessas reexecuções sobrescreve, em disco, a única cópia
persistida da resposta daquele step para o `run_id` corrente
(`ReplayRunner._run_step`, `har_reproducer/replay/replay_runner.py:121-124`,
escreve em `self.workspace.replay_response_file(self.run_id, index)` — um único
arquivo por índice por `run_id`, sobrescrito a cada `_run_step`). Um login mais
adiante na sequência de steps autentica **a sessão que existia no momento em que
ele rodou**; quando um step posterior (ex.: o alvo `--to 106`) precisa do cookie de
sessão, seu extrator (`origin_step=0`) resolve lendo esse mesmo arquivo
(`ReplayTokenResolver._resolve_one`,
`har_reproducer/replay/replay_token_resolver.py:47-67`, e
`_reference_dir_for_step`, `:84-94`, que prioriza o diretório da execução corrente
quando `origin_step in schedule`) — mas o arquivo já foi sobrescrito por uma
reexecução de `from_index` posterior ao login, com uma sessão diferente da que foi
autenticada. O alvo volta deslogado. Nenhum subconjunto de candidatos resolve isso,
porque a base (`from_index`) muda debaixo da busca a cada tentativa testada.

### 1.2 O que esta etapa cobre

1. Um cache de respostas, restrito aos índices do **backbone**
   (`self.backbone`), vivo durante uma única chamada a `optimize()`: a primeira
   execução real e saudável de cada índice do backbone fica congelada; qualquer
   reexecução do mesmo índice, dentro da mesma chamada de `optimize()`, é servida
   do cache em vez de bater na rede de novo.
2. O único ponto de ajuste na recuperação reativa já existente
   (`ReplayOptimizer._execute`, `:96-107`): a chamada que reexecuta o backbone
   para recuperação (`self._execute_raw(self.backbone, set(self.backbone))`,
   `:105`) passa a forçar a reexecução real, ignorando e sobrescrevendo o cache
   das entradas do backbone. `_needs_reactive_refresh` (`:121-122`) — o que decide
   se a recuperação é necessária — **não muda**.
3. Uma regra de admissão ao cache: só entra no cache uma resposta "saudável"
   (§0, glossário) — nunca uma que `needs_recovery` já sinalizaria como
   recuperável. Isso evita que um erro transitório (timeout, blip de rede) num
   índice do backbone fique congelado como se fosse a resposta definitiva pelo
   resto da busca.

### 1.3 Fora de escopo

- **Cache para qualquer índice fora do backbone** (candidatos, âncoras, o próprio
  `to_index`). Ver §3.1 — generalizar o cache para "qualquer índice reexecutado"
  quebraria o próprio mecanismo de busca do `optimize`, que depende de reexecutar
  o mesmo `to_index` sob diferentes combinações de candidatos e observar respostas
  diferentes.
- **Persistir o cache entre chamadas de `optimize()`.** O cache vive só durante
  uma chamada; uma nova invocação do comando `optimize` começa com cache vazio (a
  instância de `ReplayOptimizer` já é construída uma por chamada em
  `cli_handlers.py:155` — não há reuso de instância a proteger).
- **Mudar o que `_needs_reactive_refresh`/`needs_recovery` decidem.** Este item já
  foi resolvido em `docs/20260821-3 Recuperação por Divergência da Referência/spec.md`
  (comparação contra o status de referência do step, não uma lista fixa de
  códigos) — esta spec só reaproveita o método, não o redesenha.
- **Redescoberta reativa de extrator** (criar um extrator novo quando o refresh de
  sessão não resolve porque o extrator nunca existiu). Já registrada como trabalho
  futuro em specs anteriores; não é implementada aqui.
- **Mudar `ScheduleExecutor` (o `Protocol`) ou `ReplayRunner`.** O cache vive
  inteiramente dentro de `ReplayOptimizer`, usando só os dois métodos que o
  contrato já expõe (`execute_schedule`, `needs_recovery`) — nenhuma assinatura de
  `contracts/schedule_executor.py` ou `replay/replay_runner.py` muda.
- **`MAX_REACTIVE_REFRESHES`/`StepRetryPolicy.MAX_STEP_ATTEMPTS`.** Limites de
  tentativa não mudam.

---

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `ReplayOptimizer` — `har_reproducer/optimization/replay_optimizer.py` (206 linhas, arquivo inteiro)

```python
# :17-30
class ReplayOptimizer:
    MAX_REACTIVE_REFRESHES: ClassVar[int] = 2

    def __init__(
            self,
            schedule_executor: ScheduleExecutor,
            metadata_store: SilentExtractorMetadataStore,
            max_requests: int = 500,
    ) -> None:
        self.schedule_executor: ScheduleExecutor = schedule_executor
        self.metadata_store: SilentExtractorMetadataStore = metadata_store
        self.max_requests: int = max_requests
        self.requests_made: int = 0
        self.backbone: List[int] = []
```

`self.backbone` já é um atributo de instância, populado uma vez por
`_run_phase1` (`:85-90`) e reaproveitado por `_execute` (`:105`, na recuperação
reativa). `self.requests_made`/`self.max_requests` já seguem a mesma convenção que
o cache novo vai seguir: estado escopado a "uma chamada de `optimize()`", vivendo
como atributo de instância sem reset explícito, porque a instância em si só existe
para uma chamada (`cli_handlers.py:155-159`, construída dentro de
`handle_optimize`).

```python
# :92-94
def _compute_backbone(self, from_index: int, anchors: List[int]) -> List[int]:
    boundary: int = anchors[-2] if len(anchors) >= 2 else from_index
    return [i for i in self.schedule_executor.existing_step_indexes() if from_index <= i <= boundary]
```

O backbone é sempre um prefixo — todo índice nele é `<= boundary`, e `boundary` é
sempre anterior a qualquer candidato testado em `_candidates_between` (`:186-187`,
que só olha índices estritamente entre `left` e `right` de faixas que começam
depois do boundary). Isso é o que torna seguro cachear o backbone e não o resto:
nenhum índice do backbone jamais é, ao mesmo tempo, um candidato/âncora/alvo cuja
resposta a busca precisa observar variando entre tentativas (ver §3.1).

```python
# :96-107
def _execute(self, ordered_indexes: List[int], schedule: Set[int]) -> List[Tuple[int, StepResponse]]:
    refreshes: int = 0
    results: List[Tuple[int, StepResponse]] = self._execute_raw(ordered_indexes, schedule)
    while self._needs_reactive_refresh(results) and refreshes < self.MAX_REACTIVE_REFRESHES:
        refreshes += 1
        print(
            f"ReplayOptimizer: detected recoverable status in schedule — refreshing backbone before "
            f"retrying (attempt {refreshes}/{self.MAX_REACTIVE_REFRESHES})..."
        )
        self._execute_raw(self.backbone, set(self.backbone))
        results = self._execute_raw(ordered_indexes, schedule)
    return results
```

Este é o único método que decide "o backbone pode estar desatualizado, reexecute
antes de tentar de novo" — a linha `:105` é o único ponto de ajuste desta spec
dentro de `_execute` (§3.5). `_needs_reactive_refresh` em si (`:121-122`) não é
tocado.

```python
# :109-119
def _execute_raw(self, ordered_indexes: List[int], schedule: Set[int]) -> List[Tuple[int, StepResponse]]:
    results: List[Tuple[int, StepResponse]] = self.schedule_executor.execute_schedule(
        ordered_indexes, schedule, annotate=False
    )
    self.requests_made += len(ordered_indexes)
    if self.requests_made > self.max_requests:
        raise ValueError(...)
    return results
```

Hoje `_execute_raw` bate na rede para **todo** índice em `ordered_indexes`, sempre,
e conta cada um contra `requests_made`/`max_requests`. É este método que ganha o
cache (§3.3).

```python
# :162-176 (_attempt, chamado por _resolve_range dentro de _run_phase2)
ordered_indexes: List[int] = sorted(set([right, to_index, *kept_so_far, *extra_candidates]))
schedule: Set[int] = set(backbone) | set(kept_so_far) | set(ordered_indexes)
results: List[Tuple[int, StepResponse]] = self._execute(ordered_indexes, schedule)
```

`_attempt` nunca inclui `from_index`/backbone em `ordered_indexes` — só em
`schedule` (o conjunto usado para decidir, na resolução de token, se um
`origin_step` está "disponível na execução corrente" ou precisa cair para a
referência; `ReplayTokenResolver._resolve_one`, abaixo). Confirmado lendo
`_ranges_target_to_from` (`:178-184`): toda faixa testada em `_run_phase2` começa
depois do boundary do backbone, exceto a última (`from_index`, `anchors[0]`), cujo
`right` é `anchors[0]` — nunca `from_index` em si. Ou seja: **`_attempt` nunca
reexecuta um índice do backbone de verdade** — só `_confirm` faz isso, através de
`from_index` em `final_list` (§1.1). É por isso que o cache pode ser restrito ao
backbone sem tocar no caminho de busca por candidatos.

### `ReplayResultComparator.needs_recovery` / `ScheduleExecutor.needs_recovery` — já implementado

```python
# har_reproducer/contracts/schedule_executor.py:6-17 (Protocol completo)
class ScheduleExecutor(Protocol):
    def execute_schedule(
            self, ordered_indexes: List[int], schedule: Set[int], annotate: bool = True
    ) -> List[Tuple[int, StepResponse]]: ...
    def compute_smart_schedule(
            self, from_index: Optional[int], to_index: Optional[int]
    ) -> Tuple[List[int], Set[int]]: ...
    def existing_step_indexes(self) -> List[int]: ...
    def needs_recovery(self, index: int, response: StepResponse) -> bool: ...
```

```python
# har_reproducer/replay/replay_result_comparator.py (implementação real, via ReplayRunner)
def needs_recovery(self, index: int, response: StepResponse) -> bool:
    if response.status_code == 0:
        return True
    reference: Optional[int] = self.original_status_code(index)
    if reference is None:
        return False
    return response.status_code != reference
```

Já implementado por `docs/20260821-3 Recuperação por Divergência da Referência/spec.md`.
`ReplayOptimizer._needs_reactive_refresh` (`:121-122`) já delega para
`self.schedule_executor.needs_recovery(index, response)` por índice — o protocolo
já expõe exatamente o predicado que esta spec reaproveita como filtro de admissão
ao cache (§3.4). **Nenhuma mudança nesse método ou no `Protocol` é necessária** —
o cache é construído inteiramente em cima do que já existe.

### `ReplayTokenResolver._resolve_one` / `_reference_dir_for_step` — `har_reproducer/replay/replay_token_resolver.py:47-94`

```python
def _resolve_one(self, token_id, dependencies, schedule, replay_run_dir, res_refer_dir, original_responses_dir):
    origin_step: Optional[int] = dependencies.get(token_id)
    if origin_step in schedule:
        override_dir: Path = replay_run_dir
    else:
        override_dir = self._reference_dir_for_step(origin_step, res_refer_dir, original_responses_dir)
    value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
    ...
```

Isto é o que lê, em disco, a resposta mais recente do `origin_step` de um token
(`replay_run_dir / f"res_{origin_step:04d}.json"`,
`har_reproducer/fs_io/workspace.py:64-70`). O cache desta spec **não muda este
método nem o arquivo em disco** — ele age uma camada acima, decidindo se
`ReplayRunner._run_step` (que é quem escreve esse arquivo,
`replay_runner.py:121-124`) chega a rodar de novo para um dado índice. Ao evitar
uma reexecução real de `from_index`, o arquivo em disco correspondente também
para de ser sobrescrito — é assim que o cache resolve o problema descrito em
§1.1, sem precisar tocar na resolução de tokens.

---

## 3. Decisões de arquitetura

### 3.1 — Escopo do cache: restrito aos índices do backbone

**Por que não "qualquer índice reexecutado dentro de uma chamada de `optimize()`":**
a busca de `_run_phase2`/`_resolve_range` (`:137-160`) depende, por construção, de
reexecutar o **mesmo** `to_index` várias vezes com diferentes combinações de
candidatos incluídos em `ordered_indexes`, e de observar respostas **diferentes**
para a mesma combinação de índice — é assim que ela descobre quais candidatos são
necessários. Um teste existente comprova isso concretamente:
`tests/unit/test_replay_optimizer.py::test_run_phase2_elimination_keeps_only_the_necessary_candidate_closest_to_left`
executa `_attempt` quatro vezes, duas delas (`call[0]` e `call[3]`) com
`ordered_indexes == [9]` idêntico — mas essas duas chamadas ocorrem em pontos
diferentes da busca, com `schedule`/candidatos incluídos diferentes por trás, e a
resposta simulada é a mesma (404) só porque o cenário de teste faz sentido assim,
não porque índice-9-implica-sempre-a-mesma-resposta. Um cache chaveado por índice
sozinho, aplicado a `to_index`/candidatos, serviria a resposta da primeira
execução de `9` para sempre — inclusive quando a combinação de candidatos ao redor
muda e a resposta real deveria mudar junto. Isso quebraria silenciosamente o
próprio mecanismo de busca (a eliminação de candidatos passaria a operar sobre
dados congelados, não sobre o resultado real de cada combinação testada).

**Estado esperado:** o cache só guarda e só serve respostas para índices que
pertencem a `self.backbone` no momento da chamada. Nenhum índice fora dessa lista
(candidatos, âncoras, `to_index`) é elegível — nem para gravação, nem para leitura.
Isso é seguro porque, como mostrado em §2, nenhum índice do backbone é jamais um
`right`/`to_index`/candidato numa mesma busca (backbone e faixas de busca não se
sobrepõem, por construção de `_compute_backbone`) — cachear o backbone nunca
interfere no sinal que a busca por candidatos precisa observar variando.

### 3.2 — Novo atributo: `_backbone_response_cache`

**Estado atual:** `ReplayOptimizer.__init__` (`:20-30`) não tem nenhum cache.

**Estado esperado:**
```python
def __init__(self, schedule_executor: ScheduleExecutor, metadata_store: SilentExtractorMetadataStore, max_requests: int = 500) -> None:
    ...
    self.backbone: List[int] = []
    self._backbone_response_cache: Dict[int, StepResponse] = {}
```

Vive como atributo de instância, na mesma classe, sem reset explícito em nenhum
outro ponto — segue exatamente a convenção já usada por `self.backbone`/
`self.requests_made` (§2): estado escopado a "uma chamada de `optimize()`" porque a
instância de `ReplayOptimizer` só existe para uma chamada (`cli_handlers.py:155`).

### 3.3 — `_execute_raw`: consulta e alimenta o cache do backbone

**Estado atual (`:109-119`):** bate na rede para todo índice em `ordered_indexes`,
sempre.

**Estado esperado:** para cada índice em `ordered_indexes`, `_execute_raw` só bate
na rede se (a) o índice não está em `self._backbone_response_cache`, ou (b) a
chamada pede reexecução forçada (`force_refresh=True`, §3.5). Índices fora do
backbone nunca entram no cache (§3.1), então essa checagem já os deixa sempre
"ausentes do cache" — sempre reexecutados, sem precisar de uma checagem adicional
de pertencimento ao backbone neste método.

```python
def _execute_raw(
        self, ordered_indexes: List[int], schedule: Set[int], force_refresh: bool = False
) -> List[Tuple[int, StepResponse]]:
    missing: List[int] = [
        index for index in ordered_indexes
        if force_refresh or index not in self._backbone_response_cache
    ]
    fresh_by_index: Dict[int, StepResponse] = {}
    if missing:
        fresh: List[Tuple[int, StepResponse]] = self.schedule_executor.execute_schedule(
            missing, schedule, annotate=False
        )
        self.requests_made += len(missing)
        if self.requests_made > self.max_requests:
            raise ValueError(...)  # mesma mensagem/condição de hoje
        fresh_by_index = dict(fresh)
        self._remember(fresh)
    return [
        (index, fresh_by_index[index] if index in fresh_by_index else self._backbone_response_cache[index])
        for index in ordered_indexes
    ]
```

⚠️ `requests_made` passa a contar só requisições que de fato bateram na rede
(`len(missing)`, não `len(ordered_indexes)`) — ver §3.6, é uma mudança de
comportamento aceita e desejada, não um efeito colateral a evitar.

### 3.4 — Admissão ao cache: só resposta saudável (`not needs_recovery`)

**Por quê:** sem este filtro, uma falha transitória (timeout, erro de rede) na
primeira execução real de um índice do backbone ficaria congelada como se fosse a
resposta definitiva pelo resto da busca — pior que o comportamento de hoje, onde
cada reexecução tem uma chance nova de dar certo. Isso transformaria um blip
pontual (hoje absorvido pelo retry de `StepRetryPolicy`/pela recuperação reativa)
num erro permanente para o resto da chamada de `optimize()`.

**Estado esperado:**
```python
def _remember(self, fresh: List[Tuple[int, StepResponse]]) -> None:
    for index, response in fresh:
        if index in self.backbone and not self.schedule_executor.needs_recovery(index, response):
            self._backbone_response_cache[index] = response
```

Reaproveita exatamente o mesmo predicado que `_needs_reactive_refresh` já usa
(`:121-122`) — nenhuma noção nova de "saudável" é inventada; é a mesma que já
decide recuperação reativa. `status_code == 0` (falha de transporte) nunca é
cacheado, incondicionalmente — está coberto dentro de `needs_recovery` (§2). Uma
resposta cujo índice não tem referência conhecida (`original_status_code is None`)
é tratada como "não recuperável" por `needs_recovery` (comportamento herdado, não
redefinido aqui) e portanto **é** cacheável — isso é aceitável porque todo índice
do backbone vem do HAR original, então tem `original_responses/res_<index>.json`
por construção; a única forma de não ter referência é o workspace estar com esse
arquivo ausente, o que já seria um problema de integridade do workspace anterior a
esta spec (ver §5.2).

### 3.5 — Invalidação: a chamada de refresh dentro de `_execute` força reexecução

**Estado atual (`:96-107`):**
```python
self._execute_raw(self.backbone, set(self.backbone))
```

**Estado esperado:**
```python
self._execute_raw(self.backbone, set(self.backbone), force_refresh=True)
```

Único ajuste em `_execute`/na recuperação reativa. `_needs_reactive_refresh`
(`:121-122`, o predicado que decide **se** um refresh é necessário) não muda —
só o ponto em que, uma vez decidido que é necessário, o backbone é reexecutado de
verdade em vez de (potencialmente) servir do cache. Como `_remember` (§3.4) roda
de novo para essa execução forçada, o cache de cada índice do backbone é
sobrescrito com a resposta nova assim que ela é saudável — sessões que realmente
mudaram (recuperação disparada por divergência genuína) passam a valer para as
próximas leituras do cache dentro da mesma busca.

### 3.6 — Efeito colateral aceito: `requests_made` conta só requisições reais

`ReplayOptimizer.max_requests`/`requests_made` (`:24,28`, teto configurável de
requisições) hoje conta cada índice em `ordered_indexes` como uma requisição,
mesmo quando o cache (uma vez implementado) evitaria a chamada de rede. Com esta
spec, `requests_made` passa a refletir requisições de rede reais — um número
**menor ou igual** ao de hoje para a mesma busca, nunca maior. Isso é desejado (o
teto existe para limitar carga real no servidor, não chamadas evitáveis) mas é uma
mudança de comportamento observável: o mesmo workspace, com o mesmo
`--max-requests`, pode agora completar uma busca que antes estourava o teto só por
causa da reexecução redundante do backbone. `_print_estimate`
(`:199-205`, estimativa de pior caso impressa antes da fase 2) já é
explicitamente "worst case" e não inclui refreshes reativos — continua sendo um
limite superior válido depois desta mudança, só que agora mais folgado do que
antes em relação ao número real de requisições.

---

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `optimization/replay_optimizer.py` → `ReplayOptimizer.__init__` | novo atributo `_backbone_response_cache: Dict[int, StepResponse]` (3.2) |
| `optimization/replay_optimizer.py` → `ReplayOptimizer._execute_raw` | ganha parâmetro `force_refresh: bool = False`; consulta o cache do backbone antes de bater na rede, executa só os índices ausentes (ou todos, se forçado), atualiza `requests_made` só com o que de fato executou (3.3, 3.6) |
| `optimization/replay_optimizer.py` → `ReplayOptimizer._remember` (novo método privado) | admite no cache apenas respostas de índices do backbone que `schedule_executor.needs_recovery` não sinaliza como recuperáveis (3.4) |
| `optimization/replay_optimizer.py` → `ReplayOptimizer._execute` | a chamada de refresh do backbone (linha `:105` hoje) passa `force_refresh=True` (3.5) |
| `contracts/schedule_executor.py` → `ScheduleExecutor` | **sem mudança** — `needs_recovery`/`execute_schedule` já expõem tudo que o cache precisa |
| `replay/replay_runner.py`, `replay/replay_token_resolver.py` | **sem mudança** — o cache age uma camada acima; ao evitar uma reexecução real, evita indiretamente que `_run_step` sobrescreva o arquivo em disco daquele índice, sem precisar alterar como o arquivo é lido |

---

## 5. Casos de borda e comportamento de erro

**5.1 Cache nunca invalidado e a sessão expira de verdade no meio de uma busca
longa, sem reativar a recuperação.** O gatilho de recuperação
(`needs_recovery`) compara só `status_code` contra a referência (§2) — isto já é
uma limitação do mecanismo de recuperação reativa existente, não introduzida por
esta spec. Como `to_index` **nunca** é cacheado (§3.1), toda tentativa continua
verificando o alvo ao vivo, e `Validator.validate` (que pode checar mais do que
status) continua vendo a resposta real a cada tentativa — uma sessão realmente
inválida que produz um `status_code` diferente do de referência ainda dispara
recuperação normalmente. O caso não coberto é mais estreito: se a expiração real
do servidor se manifesta com o **mesmo** `status_code` que a referência (ex.: uma
página de "sessão expirada" que também responde `200`, como uma tela de login que
substitui silenciosamente o dashboard esperado), `needs_recovery` não percebe a
divergência, e o cache do backbone segue servindo a sessão antiga congelada. Nesse
cenário, `_attempt`/`_confirm` ainda podem falhar corretamente via
`Validator.validate` (se o critério de sucesso checa corpo/conteúdo, não só
status) — mas a falha seria atribuída à combinação de candidatos testada (`optimize`
pode manter candidatos desnecessários, ou abortar uma faixa com
`ReplayOptimizerAborted` achando que "faltam candidatos"), quando a causa real é a
sessão congelada no cache estar desatualizada. **Aceito como limitação conhecida,
não uma regressão desta spec**: o mesmo cenário (sessão que expira de forma
silenciosa no status) já não era coberto pela recuperação reativa hoje; o cache só
move o ponto onde a sessão desatualizada é servida (de "toda reexecução bate a
sessão mais recente, boa ou ruim" para "a sessão capturada uma vez fica congelada
até um refresh explícito"). Recurso disponível ao usuário: rerodar `optimize` (uma
nova chamada começa com cache vazio, §1.3).

**5.2 Cache guardando uma resposta de erro/timeout.** Coberto pela regra de
admissão (§3.4): `status_code == 0` nunca entra no cache, incondicionalmente; uma
resposta que diverge de uma referência conhecida também não. O caso residual —
índice do backbone sem referência conhecida (`original_status_code is None`) — é
tratado como "não recuperável" por `needs_recovery` (comportamento herdado da spec
`20260821-3`, não redefinido aqui) e portanto seria admitido no cache mesmo sendo,
em tese, um erro. Isso só acontece se o workspace estiver sem
`original_responses/res_<index>.json` para um índice que `_compute_backbone`
incluiu — um problema de integridade do workspace anterior e independente desta
spec (todo índice do backbone vem do HAR original, que sempre grava esse arquivo).
Não é tratado como um caso a mitigar aqui.

**5.3 Recuperação reativa esgota `MAX_REACTIVE_REFRESHES` sem corrigir o
backbone.** Comportamento inalterado: `_execute` (`:96-107`) já hoje devolve o
último resultado obtido depois de esgotar as tentativas, sem lançar exceção — quem
chama (`_confirm`/`_attempt`) trata isso como uma resposta que falha os critérios,
normalmente. Com o cache, a única diferença é que a resposta "ruim" da última
tentativa forçada **não** fica congelada (§3.4 a rejeitaria por divergir da
referência) — a próxima leitura do backbone, se houver, tenta de novo, exatamente
como antes desta spec.

**5.4 `from_index == to_index` (faixa degenerada).** Já coberto por
`test_optimize_final_list_has_no_duplicate_when_to_index_equals_from_index`.
Neste caso o backbone é `[from_index]` e `final_list` de toda `_confirm` é
`{from_index}` — ou seja, o único índice testado É o índice do backbone, cacheado
depois da primeira execução em `_run_phase1`. A confirmação final passa a não
gerar nenhuma requisição de rede adicional (é servida inteiramente do cache). Isso
é uma consequência aceita de §3.1: numa busca sem faixa nenhuma para explorar, não
há um "alvo distinto do backbone" a reverificar ao vivo — o teste existente já
teria de continuar passando sem mudança de asserção (só o número de chamadas reais
ao `schedule_executor` diminui, o que nenhum teste hoje verifica para este caso).

**5.5 Múltiplos índices do backbone (backbone com mais de um elemento).** O caso
descrito em §1.1 usa `from_index` como exemplo porque é o único membro do backbone
que `_confirm` reexecuta de verdade fora da fase 1 — mas o cache cobre qualquer
índice do backbone igualmente, caso algum outro ponto da busca venha a reexecutar
um deles no futuro. Nenhum caminho de código atual faz isso hoje além de
`_confirm`/`from_index` e da própria recuperação reativa (§2, `_attempt` nunca
inclui backbone em `ordered_indexes`).

---

## 6. Suposições e pontos a confirmar

- **Nome do atributo (`_backbone_response_cache`) e do método privado
  (`_remember`)** — seguem a convenção de nomes descritivos do guia de estilo, mas
  são ajustáveis na implementação se um nome mais claro surgir ao escrever o
  plano.
- **Mensagem de erro do teto de requisições em `_execute_raw`** (hoje
  `f"ReplayOptimizer: teto de requisições atingido ({self.requests_made}/{self.max_requests}) — abortando a busca."`)
  não muda de texto — só o valor de `requests_made` que ela reporta passa a ser
  menor com mais frequência (§3.6).

---

## 7. Referência

Toda alteração de código desta spec segue [[guia-de-estilo]]: tipagem explícita em
`_backbone_response_cache: Dict[int, StepResponse]` e no parâmetro
`force_refresh: bool = False`, decomposição em um método privado pequeno
(`_remember`) para a regra de admissão, zero comentários/docstrings no código
final (o texto explicativo vive nesta spec, não no código).
