# Spec — Recuperação por Divergência da Referência

## 0. Sumário

Três lugares do projeto decidem "esta resposta merece uma tentativa de recuperação?"
comparando o status HTTP contra uma lista fixa (`{400, 401}`, ou `{400, 401, 0}` no
`optimize`). Contra um servidor que sinaliza falha de autenticação com `403` — como o
usado nos testes de rede deste projeto — a lista nunca casa, e a recuperação nunca
dispara, mesmo quando ela resolveria o problema. Medido: com um JWT inválido, o `optimize`
executou 232 requisições, viu `403` em 10 steps, e nunca imprimiu a mensagem de
recuperação (`docs/20260817 Reteste do Otimizador contra Servidor Real/relatorio.md`,
§3.6). A correção troca a lista fixa por uma comparação contra o status de **referência**
daquele step específico — que `ReplayResultComparator` já sabe calcular — nos três lugares:
`Engine.handle_recovery` (`run`), o `recover()` de `ReplayRunner._run_step` (`replay`), e
`ReplayOptimizer._needs_reactive_refresh` (`optimize`).

### Glossário

| termo | significado nesta spec |
|---|---|
| **status de referência** | O status HTTP que aquele step produziu na gravação original (`.har`) ou, quando disponível, na execução mais recente — o que `ReplayResultComparator.original_status_code` já calcula, com a mesma ordem de prioridade que ele já usa hoje. |
| **divergência** | `response.status_code != status_de_referência(step)`, só quando a referência é conhecida. É a base do novo critério de recuperação — mas não o critério inteiro (ver `needs_recovery`, §2). |
| **`needs_recovery`** | Método novo em `ReplayResultComparator`: falha de transporte (`status_code == 0`) é sempre recuperável; senão, só se a referência for conhecida **e** divergir. Referência desconhecida → **não** recuperável — é a correção de uma premissa errada da primeira versão desta spec (§2). |
| **recuperação** | A ação de reexecutar tokens já resolvidos contra a resposta mais recente (`token_resolver.resolve_all(force=True)` em `run`; um novo `attempt()` com os mesmos extratores em `replay`/`optimize`). Esta spec **não muda o que a recuperação faz** — só quando ela é considerada necessária. |

---

## 1. Objetivo

### 1.1 O problema, com os três lugares onde ele existe

```python
# har_reproducer/engines/engine.py:129-131 (Engine.handle_recovery)
if response.status_code not in self.retry_policy.RECOVERABLE_STATUS_CODES:  # {400, 401}
    return False

# har_reproducer/replay/replay_runner.py:112-114 (ReplayRunner._run_step.recover)
if response.status_code not in StepRetryPolicy.RECOVERABLE_STATUS_CODES:  # {400, 401}
    return False

# har_reproducer/optimization/replay_optimizer.py:19,103-105 (ReplayOptimizer)
RECOVERABLE_STATUS_CODES: ClassVar[Set[int]] = StepRetryPolicy.RECOVERABLE_STATUS_CODES | {0}
...
return any(response.status_code in cls.RECOVERABLE_STATUS_CODES for _, response in results)
```

Os três testam pertinência a um conjunto fixo de códigos. Medido contra um servidor real
(`docs/20260817 .../relatorio.md`, §3.6): a API sinaliza falha de autenticação com `403`,
não `{400, 401}`. Com um JWT adulterado, `optimize` executou 232 requisições, viu `403` em
10 steps distintos (`75`, `151`, `224`, `227`–`233`) e nunca considerou nenhum recuperável.

⚠️ **A correção não é acrescentar `403` à lista.** O step `75`
(`GET /auth/check`) responde `403` **legitimamente** em toda execução bem-sucedida — está
assim no HAR, e o `replay` já o marca `✓ matched (403 vs original 403)`. Com `403` na
lista, **toda** execução deste fluxo dispararia recuperação no step 75, cada uma
reexecutando o backbone inteiro (76 requisições no `optimize` deste HAR) — desperdício no
caminho feliz. A correção certa muda o critério: não é "este código está na lista", é "este
código é diferente do que **este step específico** produziu quando passou".

### 1.2 O que esta etapa cobre

1. Os três lugares passam a decidir recuperação via `ReplayResultComparator.needs_recovery`
   (método novo, não uma inversão de `matches_original` — ver §2 por quê).
2. `status_code == 0` (falha de transporte) continua um caso explícito, agora unificado
   nos três lugares — hoje só `ReplayOptimizer` tratava `0` como recuperável.
3. `Engine.handle_recovery` ganha o índice do step como parâmetro (hoje só recebe a
   resposta — não dá para comparar contra uma referência sem saber qual step é).

### 1.3 Fora de escopo

- **O que a recuperação faz** quando dispara. Continua sendo "reexecutar com os extratores
  que já existem" nos três lugares — não é isto que muda.
- **Redescoberta reativa** (criar um extrator novo quando a recuperação por refresh não
  resolve porque o extrator nunca existiu). É a etapa maior que este item viabiliza, mas
  não a implementa — está registrada como trabalho futuro em
  `docs/20260817 .../correcoes.md`.
- **`StepRetryPolicy.MAX_STEP_ATTEMPTS`/`ReplayOptimizer.MAX_REACTIVE_REFRESHES`** — os
  limites de tentativa não mudam.

---

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `ReplayResultComparator` — `har_reproducer/replay/replay_result_comparator.py` (41 linhas, arquivo inteiro)

```python
class ReplayResultComparator:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace: Workspace = workspace

    def matches_original(self, index: int, response: StepResponse) -> bool:
        original: Optional[int] = self.original_status_code(index)
        if original is None:
            print(f"Could not find status_code in original response for step {index} to compare.")
            return False
        return original == response.status_code

    def original_status_code(self, index: int) -> Optional[int]:
        ...
```

`original_status_code` já faz a leitura que esta etapa precisa, com a ordem de prioridade
certa: tenta `real_responses/` primeiro (a execução mais recente, se existir), cai para
`original_responses/` (o `.har`) senão. **Nem ele, nem `matches_original`, mudam.**

⚠️ **`matches_original` não é reaproveitado diretamente, e é por isso que a spec ganhou um
método novo em vez de só inverter este.** `matches_original` devolve `False` ("não bate")
quando não acha referência nenhuma — comportamento **correto** para o seu uso atual (o
veredito final de um replay inteiro, onde "não consigo confirmar" deveria mesmo aparecer
como não-confirmado). Usar essa mesma regra como gatilho de recuperação **durante** a
execução tem um efeito colateral sério, encontrado ao verificar os testes existentes: a
maioria dos testes de `test_replay_runner.py` nunca grava `original_responses/`, então
**toda** chamada trataria "não sei" como "divergiu", disparando recuperação em
absolutamente qualquer step, mesmo um `200` perfeitamente saudável — e, com
`StubHttpTransport`, isso consome respostas extras da lista do stub e contamina a resposta
do **step seguinte** (verificado num teste concreto:
`test_execute_schedule_returns_index_response_pairs_without_comparator` esperaria
`[200, 404]` e passaria a receber `[404, 404]`).

**Estado esperado:** `ReplayResultComparator` ganha um método novo, `needs_recovery`, que
não herda essa armadilha:
```python
def needs_recovery(self, index: int, response: StepResponse) -> bool:
    if response.status_code == 0:
        return True
    reference: Optional[int] = self.original_status_code(index)
    if reference is None:
        return False
    return response.status_code != reference
```
Falha de transporte (`status_code == 0`) é sempre recuperável, **explicitamente** — não
por acaso "0 nunca bate com uma referência real" (isso deixaria de valer se, por exemplo,
a referência também fosse desconhecida). Referência desconhecida devolve `False` — "não
sei" não é "diverge". Só quando a referência é conhecida **e** diverge, `True`.

### `Engine.handle_recovery` — `har_reproducer/engines/engine.py:129-138`

```python
def handle_recovery(self, response: StepResponse) -> bool:
    if response.status_code not in self.retry_policy.RECOVERABLE_STATUS_CODES:
        return False
    print(f"Detected {response.status_code}. Attempting deterministic recovery (token refresh)...")
    self.token_resolver.resolve_all(force=True)
    return True

def execute_step(self, step: Step) -> StepResponse:
    return self.retry_policy.execute(step.index, lambda: self._attempt_step(step), self.handle_recovery)
```

`handle_recovery` é passado como referência de método (`self.handle_recovery`) para
`StepRetryPolicy.execute`, que o chama com só a `response` (`recovery_fn: Callable[[StepResponse], bool]`,
`step_retry_policy.py:14`). Por isso hoje ele não sabe qual step é — nunca precisou saber,
porque a lista fixa não depende de contexto.

⚠️ **A referência já está em disco quando `handle_recovery` roda.**
`Engine._process_entry` (`engine.py:69-96`) chama `_persist_original_response_step`
**antes** de `execute_step` — então `original_responses/res_<index>.json` já existe no
momento em que a primeira tentativa falha, mesmo que seja a primeira tentativa do `run`.

### `ReplayRunner._run_step` — `har_reproducer/replay/replay_runner.py:96-123`

```python
def recover(response: StepResponse) -> bool:
    if response.status_code not in StepRetryPolicy.RECOVERABLE_STATUS_CODES:
        return False
    print(f"Detected {response.status_code}. Attempting deterministic recovery (token refresh)...")
    return True
```

`recover` é uma closure local, já tem `index` no escopo (parâmetro de `_run_step`) e já tem
`self.comparator: ReplayResultComparator` como atributo de instância — não precisa de
nenhuma injeção nova, só trocar o corpo do `if`.

### `ReplayOptimizer` / contrato `ScheduleExecutor` — `har_reproducer/contracts/schedule_executor.py`, `har_reproducer/optimization/replay_optimizer.py:18-19,103-105`

```python
class ScheduleExecutor(Protocol):
    def execute_schedule(self, ordered_indexes, schedule, annotate=True) -> List[Tuple[int, StepResponse]]: ...
    def compute_smart_schedule(self, from_index, to_index) -> Tuple[List[int], Set[int]]: ...
    def existing_step_indexes(self) -> List[int]: ...
```

`ReplayOptimizer.schedule_executor` é, na composição real
(`cli_handlers.py:152`, `schedule_executor=runner`), sempre uma instância de `ReplayRunner`
— que já tem `self.comparator`. `ReplayOptimizer` em si não tem `Workspace` nem
`ReplayResultComparator` próprios, e não deveria precisar — o contrato já é o lugar certo
para expor a comparação, porque quem o implementa (`ReplayRunner`) já sabe fazê-la.

### `EngineFactory.create` — `har_reproducer/engines/construction/engine_factory.py:59-92`

Já importa `CurlTokenComment` de `har_reproducer.replay` (`:14`) — não há restrição de
camada entre `engines/` e `replay/` neste projeto; construir um `ReplayResultComparator`
aqui e passar para `Engine` é consistente com o que já existe.

---

## 3. Decisões de arquitetura

### 3.1 — `ScheduleExecutor`: novo método `needs_recovery`

**Estado atual:** o `Protocol` tem três métodos; nenhum expõe decisão de recuperação.

**Estado esperado:**
```python
class ScheduleExecutor(Protocol):
    def execute_schedule(self, ordered_indexes, schedule, annotate=True) -> List[Tuple[int, StepResponse]]: ...
    def compute_smart_schedule(self, from_index, to_index) -> Tuple[List[int], Set[int]]: ...
    def existing_step_indexes(self) -> List[int]: ...
    def needs_recovery(self, index: int, response: StepResponse) -> bool: ...
```

`ReplayRunner` implementa delegando ao `self.comparator.needs_recovery` (2, o método novo,
**não** `matches_original`):
```python
def needs_recovery(self, index: int, response: StepResponse) -> bool:
    return self.comparator.needs_recovery(index, response)
```

Nenhum parâmetro novo no construtor de `ReplayRunner` — `comparator` já é injetado.

### 3.2 — `ReplayOptimizer._needs_reactive_refresh`: divergência em vez de lista fixa

**Estado atual:**
```python
RECOVERABLE_STATUS_CODES: ClassVar[Set[int]] = StepRetryPolicy.RECOVERABLE_STATUS_CODES | {0}

@classmethod
def _needs_reactive_refresh(cls, results: List[Tuple[int, StepResponse]]) -> bool:
    return any(response.status_code in cls.RECOVERABLE_STATUS_CODES for _, response in results)
```

**Estado esperado:**
```python
def _needs_reactive_refresh(self, results: List[Tuple[int, StepResponse]]) -> bool:
    return any(self.schedule_executor.needs_recovery(index, response) for index, response in results)
```

`RECOVERABLE_STATUS_CODES` é removido de `ReplayOptimizer` (deixa de existir — não é usado
em outro lugar; confirmado por busca no projeto). `_needs_reactive_refresh` deixa de ser
`@classmethod` (agora usa `self.schedule_executor`).

⚠️ **`status_code == 0` é tratado dentro de `needs_recovery` (2), não aqui.** A união
`| {0}` que só o `ReplayOptimizer` tinha desaparece porque o caso já está coberto no lugar
certo, de forma explícita — não como propriedade emergente de "0 nunca bate com uma
referência". `Engine`/`ReplayRunner` ganham essa cobertura pela primeira vez, pelo mesmo
método compartilhado.

### 3.3 — `ReplayRunner._run_step`: `recover` usa `self.comparator`

**Estado esperado:**
```python
def recover(response: StepResponse) -> bool:
    if not self.comparator.needs_recovery(index, response):
        return False
    print(f"Detected {response.status_code} (reference expects a different status). "
          f"Attempting deterministic recovery (token refresh)...")
    return True
```

`index` já está no escopo da closure (parâmetro de `_run_step`). Nenhuma mudança de
assinatura, nenhuma injeção nova.

### 3.4 — `Engine.handle_recovery`: ganha o índice do step, usa `ReplayResultComparator`

**Estado atual:** `handle_recovery(self, response: StepResponse) -> bool`, chamado via
`self.retry_policy.execute(step.index, lambda: self._attempt_step(step), self.handle_recovery)`.

**Estado esperado:**
```python
def handle_recovery(self, step_index: int, response: StepResponse) -> bool:
    if not self.comparator.needs_recovery(step_index, response):
        return False
    print(f"Detected {response.status_code} (reference expects a different status). "
          f"Attempting deterministic recovery (token refresh)...")
    self.token_resolver.resolve_all(force=True)
    return True

def execute_step(self, step: Step) -> StepResponse:
    return self.retry_policy.execute(
        step.index, lambda: self._attempt_step(step), lambda response: self.handle_recovery(step.index, response)
    )
```

`Engine.__init__` ganha `comparator: ReplayResultComparator` como novo parâmetro (depois
de `validator`, antes de `success_criteria` — posição exata ajustável).

⚠️ **`StepRetryPolicy.execute` não muda.** Seu parâmetro `recovery_fn: Callable[[StepResponse], bool]`
continua recebendo só a resposta — é a lambda em `execute_step` que absorve `step.index`,
não uma mudança de contrato do `StepRetryPolicy`.

### 3.5 — `EngineFactory.create`: constrói e injeta o `ReplayResultComparator`

**Estado esperado:** `EngineFactory.create` (`engine_factory.py:59-92`) constrói
```python
comparator: ReplayResultComparator = ReplayResultComparator(self.workspace)
```
e passa para `engine_cls(..., comparator, ...)` na posição correspondente à nova
assinatura de `Engine.__init__` (3.4). `DryEngine` (que estende `Engine`) recebe o mesmo
parâmetro sem lógica adicional — em `--mode dry`, `handle_recovery` continua alcançável
(não é `USES_NETWORK`-condicional), mas como não há requisição de rede real em dry, o
caminho de recuperação nunca é exercitado ali; não é preciso tratamento especial.

---

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `replay/replay_result_comparator.py` → `ReplayResultComparator` | novo método `needs_recovery(index, response) -> bool` — não muda `matches_original`/`original_status_code` (§2) |
| `contracts/schedule_executor.py` → `ScheduleExecutor` | novo método `needs_recovery(index, response) -> bool` (3.1) |
| `replay/replay_runner.py` → `ReplayRunner` | implementa `needs_recovery` delegando ao `comparator.needs_recovery`; `recover()` usa divergência (3.1, 3.3) |
| `optimization/replay_optimizer.py` → `ReplayOptimizer` | `_needs_reactive_refresh` usa `schedule_executor.needs_recovery`; `RECOVERABLE_STATUS_CODES` removido (3.2) |
| `engines/engine.py` → `Engine` | `handle_recovery` ganha `step_index`; usa `comparator` em vez da lista fixa; `__init__` ganha `comparator` (3.4) |
| `engines/construction/engine_factory.py` → `EngineFactory` | constrói e injeta o `ReplayResultComparator` (3.5) |

`StepRetryPolicy`, `ReplayResultComparator`, `ScheduleExecutor.execute_schedule`/`compute_smart_schedule`/`existing_step_indexes`
— **não mudam.**

---

## 5. Casos de borda e comportamento de erro

**5.1 Step sem referência disponível** (nem `real_responses/`, nem `original_responses/`
têm o arquivo, ou o JSON não tem `status_code`). `needs_recovery` devolve `False` — "não
sei" não é "diverge" (§2, é a correção central desta etapa em relação à primeira versão
da spec). **Não** dispara recuperação por esse motivo — precisão verificada contra os
testes existentes: nenhum teste de `test_replay_runner.py` grava referência, e nenhum
precisa mudar por causa disso.

**5.2 `status_code == 0` (falha de transporte).** Sempre recuperável, por um `if`
explícito dentro de `needs_recovery` — não depende de haver referência. Comportamento
idêntico ao que `ReplayOptimizer` já tinha (união explícita com `{0}`);
`Engine`/`ReplayRunner` passam a tratar esse caso pela primeira vez (hoje não tratavam) —
mudança que só amplia recuperação, nunca reduz.

**5.3 Step legitimamente instável entre execuções** (ex.: `ETag` que muda no deploy, sem
relação com autenticação). O status HTTP em si não muda por isso (ainda seria `200`/`304`
nas duas épocas) — este item não cria nem resolve esse caso; é o mesmo domínio da
redescoberta reativa, fora de escopo (§1.3).

**5.4 `--mode dry`.** `Engine.handle_recovery` continua alcançável, mas
`DryEngine._persist_response_step`/`execute_step` não fazem requisição de rede real — o
caminho nunca é exercitado com uma resposta que divirja de verdade. Sem mudança de
comportamento observável em dry.

---

## 6. Suposições e pontos a confirmar

- **Posição do parâmetro `comparator` em `Engine.__init__`** — proposta depois de
  `validator`; ajustável.
- **Texto da mensagem impressa** em `handle_recovery`/`recover` — ajustável; a spec propõe
  incluir "(reference expects a different status)" para diferenciar da mensagem antiga no
  log, mas o texto exato não é uma decisão de arquitetura.
- **`StepRetryPolicy.RECOVERABLE_STATUS_CODES` (`{400, 401}`) fica sem uso depois desta
  etapa.** Confirmado por busca: depois de 3.3 e 3.4 removerem as duas únicas leituras em
  produção (`replay_runner.py:113`, `engine.py:130`), nenhum código de produção nem de
  teste referencia essa constante. Pelo guia de estilo, código morto se avisa antes de
  remover, não se decide em silêncio — **proposta: remover no plano**, já que ela não tem
  nenhum outro papel (não é configuração exposta, não é documentada como API pública), mas
  fica registrado aqui para confirmação antes da task correspondente.

---

## 7. Referência

Toda alteração de código desta spec segue [[guia-de-estilo]]. A decisão é uma aplicação
direta do princípio de genericidade de [[arquitetura-e-fundamentos]]: uma lista fixa de
códigos de status é conhecimento de protocolo hardcoded ("falha de auth é sempre 400 ou
401"); comparar contra a referência descobre o que é uma falha **a partir do próprio
dado** — o mesmo status que já indicou sucesso na gravação original.
