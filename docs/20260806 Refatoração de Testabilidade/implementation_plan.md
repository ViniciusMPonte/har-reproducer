# Plano de Implementação — Refatoração de Testabilidade

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## Regras que valem para todas as sete tasks

1. **Portão de aceite: `uv run pytest --runslow` — 39 testes verdes, sem
   regravar nada.** Baseline medido: `39 passed in ~32s`.
2. **`HAR_REPRODUCER_UPDATE_GOLDEN=1` nunca é setado.** Se uma task faz o golden
   divergir, **a task está errada, não o golden**.
3. **O `pytest` default (28 testes) não serve como portão.** Nenhum dos 28
   offline alcança `CliHandlers._build_replay_runner` (`cli_handlers.py:98`) —
   os três cenários de erro de `replay` com workspace real levantam `ValueError`
   antes, em `:106`, `:110` e `:116`. Uma quebra de assinatura no ramo `replay`
   deixa a rodada default **inteiramente verde**. E o projeto **não tem mypy,
   ruff nem pyright**: quebra de assinatura só aparece em runtime.
4. **Nenhum arquivo em `tests/` muda.** Se uma task parecer exigir isso, a task
   está errada.
5. **Toda task é `refactor:`** — comportamento observável não muda, nem em caso
   de borda. Se aparecer um bug de verdade no caminho, é commit `fix:` separado,
   fora da numeração `T0N`.
6. **Nunca use default para dependência** (`def __init__(self, x: X = None)`).
   O default esconde a construção e vira andaime permanente. Única exceção
   prevista neste plano: `http_transport` em T03, que é assinatura
   **intermediária** e some em T04.
7. Estilo: `.claude/skills/guia-de-estilo/SKILL.md`. Tipagem explícita em todo
   parâmetro, retorno e atributo; `ClassVar` para constante de classe; `Path`
   para caminho; uma classe por arquivo; zero comentário e zero docstring;
   guard clauses; máximo dois níveis de indentação.

---

## [T01] — `AgentFactory`: extrair a construção de agent do `CandidateResolver`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/agents/construction/__init__.py` (novo, vazio), `har_reproducer/agents/construction/agent_factory.py` (novo, `AgentFactory`), `har_reproducer/agents/__init__.py` (export), `har_reproducer/tracking/candidate_resolver.py` (`CandidateResolver.__init__`, `LOCATION_AGENTS`, `_generate_extractor`), `har_reproducer/tracking/token_tracker.py` (`TokenTracker.__init__`)

**Contexto:**
`CandidateResolver` é a maior classe do projeto (214 linhas) e acumula duas
responsabilidades: decidir de onde vem um token e **construir o agent** que vai
extraí-lo. A construção do agent é o que impede testar a primeira parte sem
disparar o loop TDD real, com subprocesso e `time.sleep`. Esta task move só a
construção; a decisão de origem fica onde está.

**Estado atual:**
- `CandidateResolver` carrega o mapa (`:25-31`):
  ```python
  LOCATION_AGENTS: ClassVar[Dict[TokenLocation, Type[BaseAgent]]] = {
      TokenLocation.COOKIE: CookieAgent,
      TokenLocation.HEADER: HeaderAgent,
      TokenLocation.BODY_JSON: JSONPathAgent,
      TokenLocation.BODY_HTML: CSSAgent,
      TokenLocation.SCRIPT: RegexAgent,
  }
  ```
- `__init__` (`:33-45`) recebe `(responses_dir, session_store, llm)` e guarda
  `self.llm` (`:41`).
- `_generate_extractor` (`:177-203`) instancia inline (`:186-195`):
  ```python
  agent_cls: Type[BaseAgent] = self.LOCATION_AGENTS.get(candidate.origin_location, RegexAgent)

  agent: BaseAgent = agent_cls(
      token_id=candidate.token_id,
      response_sample=response_sample,
      expected_value=candidate.current_value,
      path=candidate.path,
      location=candidate.origin_location.value if candidate.origin_location else None,
      llm=self.llm,
  )
  ```
- `TokenTracker.__init__` (`:16-28`) recebe `llm` e o repassa em `:27`:
  `CandidateResolver(responses_dir, session_store, llm)`.
- `token_tracker.py:27` é o **único** call site de `CandidateResolver` no
  projeto inteiro (verificado por grep; nenhum teste o instancia).

**Estado esperado depois:**
- `agents/construction/agent_factory.py` com `AgentFactory`:
  - `LOCATION_AGENTS: ClassVar[Dict[TokenLocation, Type[BaseAgent]]]` — o mapa
    movido, sem alteração;
  - `DEFAULT_AGENT: ClassVar[Type[BaseAgent]] = RegexAgent`;
  - `__init__(self, llm: Optional[BaseChatModel]) -> None`;
  - `create(self, candidate: DynamicToken, response_sample: Dict[str, Any]) -> BaseAgent`,
    reproduzindo **exatamente** os seis argumentos de hoje.
- `CandidateResolver.__init__(responses_dir, session_store, agent_factory)`;
  perde `self.llm`, `LOCATION_AGENTS` e os **cinco** imports de subclasse de
  agent. `_generate_extractor` passa a chamar
  `agent: BaseAgent = self.agent_factory.create(candidate, response_sample)`.
- `TokenTracker.__init__` continua recebendo `llm`, constrói
  `AgentFactory(llm)` e o injeta no `CandidateResolver`. É andaime de uma task
  só: T02 sobe essa construção para o `Engine`.
- `agents/__init__.py` exporta `AgentFactory`.

⚠️ **`agent_factory.py` importa as cinco subclasses por submódulo direto**
(`from har_reproducer.agents.cookie_agent import CookieAgent`, …), **nunca**
`from har_reproducer.agents import CookieAgent`. Com o export em
`agents/__init__.py` e a ordem alfabética (`construction` precede
`cookie_agent`), o import pelo pacote produz
`ImportError: cannot import name 'CookieAgent' from partially initialized module`
— reproduzido em sandbox, e derruba os **39** testes no import, porque
`candidate_resolver.py:9` importa `har_reproducer.agents`.
`engines/construction/engine_factory.py:4-6` já segue essa regra.

⚠️ **`CandidateResolver` continua importando `BaseAgent`** — ele anota o tipo da
variável do agent. Saem só as cinco subclasses.

⚠️ **`TokenLocation.URL_PARAM` não está no mapa** e cai no `DEFAULT_AGENT`. O
`.get(..., RegexAgent)` de hoje tem que virar `.get(..., self.DEFAULT_AGENT)`,
não um `if/elif`.

⚠️ **A expressão de `location` é copiada literalmente**, com o ternário
inclusive: `candidate.origin_location.value if candidate.origin_location else None`.
Na prática `_generate_extractor` já garante `origin_location is not None` antes
(`:183-184` devolve extrator literal quando é `None`), mas simplificar o
ternário é mudança de comportamento em código defensivo — não simplificar.

**Critérios de aceite:**
- [ ] `uv run pytest --runslow` → 39 passed, sem regravar golden.
- [ ] `uv run python -c "import har_reproducer.agents"` não levanta `ImportError`.
- [ ] `grep -n LOCATION_AGENTS har_reproducer/tracking/candidate_resolver.py` não
      retorna nada; `grep -rn "LOCATION_AGENTS" har_reproducer/` só acha
      `agent_factory.py`.
- [ ] `grep -n "CookieAgent\|CSSAgent\|HeaderAgent\|JSONPathAgent\|RegexAgent" har_reproducer/tracking/candidate_resolver.py`
      não retorna nada; `BaseAgent` continua importado.
- [ ] Os sete `extractors/*.meta.json` de `tests/golden/run_dry_default/`
      continuam com os mesmos `agent_type` (`CookieAgent`, `CSSAgent`,
      `HeaderAgent`, `JSONPathAgent`, `RegexAgent`, `LiteralAgent`,
      `LiteralFallbackAgent`) — é o que prova que o mapa e o default foram
      reproduzidos.
- [ ] Não-regressão: `tests/golden/run_main/stdout.txt` continua idêntico,
      incluindo as duas linhas `Attempt 1 failed for …`.

---

## [T02] — `TokenTracker`/`CandidateResolver`/`TokenResolver`: receber colaboradores por construtor

**Depende de:** T01 (a `AgentFactory` já existe e já é injetada no `CandidateResolver`).
**Arquivos envolvidos:** `har_reproducer/tracking/token_tracker.py`, `har_reproducer/tracking/candidate_resolver.py`, `har_reproducer/tracking/token_resolver.py`, `har_reproducer/engines/engine.py` (`Engine.__init__`)

**Contexto:**
As três classes de tracking constroem seus colaboradores dentro do `__init__`,
o que as torna não-substituíveis em teste. O ramo `replay` já faz o oposto
(`ReplayRunner.__init__`, `replay/replay_runner.py:19-41`: dez parâmetros, dez
atributos, nenhuma construção). Esta task leva as três ao mesmo formato. Quem
monta continua sendo o `Engine`; mudar isso é T04.

**Estado atual:**
- `TokenResolver.__init__` (`:10-13`) constrói `ExtractorRunner()`.
- `CandidateResolver.__init__` (`:42-43`) constrói **outro** `ExtractorRunner()`
  e um `ExtractorMetadataStore()`.
- `TokenTracker.__init__` (`:26-28`) constrói `BaselineDiff()`,
  `CandidateResolver(...)` e `PlaceholderApplier(session_store)`.
- `TokenTracker.analyze_step` (`:35`) constrói um `CurlGenerator()` **a cada
  chamada**, dentro do método.
- `Engine.__init__` monta em `:53` (`TokenResolver`) e `:57` (`TokenTracker`).

**Estado esperado depois:**
- `TokenResolver.__init__(responses_dir, session_store, extractor_runner)`.
- `CandidateResolver.__init__(responses_dir, session_store, extractor_runner, metadata_store, agent_factory)`.
- `TokenTracker.__init__(baseline_diff, candidate_resolver, placeholder_applier, curl_generator)`
  — **quatro** parâmetros. `analyze_step` passa a usar `self.curl_generator`.
- `Engine.__init__` monta o grafo, nesta ordem:
  1. junto de `:44-46`: `ExtractorRunner` e `ExtractorMetadataStore` —
     **uma instância de cada**, compartilhada;
  2. `llm` continua em `:56`;
  3. entre `:56` e `:57`: `AgentFactory`, `BaselineDiff`, `CandidateResolver`,
     `PlaceholderApplier`, `CurlGenerator`, e por fim o `TokenTracker`.

⚠️ **`ExtractorRunner` tem que ser construído antes da linha que hoje é `:53`.**
`TokenResolver` passa a exigi-lo ali, e a cabeça leva a montar o grafo de
tracking perto de `:57` — na ordem errada, `:53` estoura.

⚠️ **Uma instância de `ExtractorRunner` e uma de `ExtractorMetadataStore`**,
compartilhadas entre `TokenResolver` e `CandidateResolver`. As duas classes são
sem estado — nenhuma tem `__init__`, nenhum método escreve atributo de
instância. É o que `_build_replay_runner` já faz no ramo `replay`.

⚠️ **Uma única `SessionStore` no grafo inteiro**, atravessando `Engine`,
`TokenResolver`, `CandidateResolver` e `PlaceholderApplier`. Hoje a unicidade é
garantida pela cadeia de repasse; com a montagem plana, duplicá-la por engano
deixa os tokens resolvidos invisíveis para quem renderiza o curl. `SessionStore`
é o **único** colaborador com estado mutável do grafo.

⚠️ **`TokenTracker` perde três atributos, todos mortos:** `responses_dir`
(`:22`) e `llm` (`:24`) já são mortos hoje — `:27` repassa os *parâmetros*, nunca
os atributos —, e `session_store` (`:23`) morre agora, porque só existia para
construir `CandidateResolver` e `PlaceholderApplier`. `analyze_step` (`:30-43`)
não lê nenhum dos três.

⚠️ **Hoistar o `CurlGenerator` é seguro:** ele não tem `__init__` e nenhum método
escreve atributo de instância — verificado.

⚠️ **`tracking_responses_dir` passa a ter dois consumidores**, `TokenResolver` e
`CandidateResolver`; o `TokenTracker` deixa de recebê-lo. Errar **um** dos dois
em modo `main` pode passar verde: os dois diretórios candidatos divergem
(`real_responses/res_0000.json` tem `Server`, `Date` e `Content-Length` que
`original_responses/` não tem), mas o `HeaderAgent` da fixture tem origem em
`Content-Type`, presente nos dois. Conferir os dois explicitamente.

**Critérios de aceite:**
- [ ] `uv run pytest --runslow` → 39 passed, sem regravar golden.
- [ ] `grep -n "ExtractorRunner()\|ExtractorMetadataStore()\|BaselineDiff()\|PlaceholderApplier(\|CurlGenerator()" har_reproducer/tracking/`
      não retorna nada.
- [ ] `TokenTracker.__init__` tem exatamente quatro parâmetros e nenhuma
      construção no corpo.
- [ ] `grep -n "self.responses_dir\|self.llm\|self.session_store" har_reproducer/tracking/token_tracker.py`
      não retorna nada.
- [ ] `Engine.__init__` constrói **uma** `SessionStore`, **um** `ExtractorRunner`
      e **um** `ExtractorMetadataStore`, e os mesmos objetos chegam aos dois
      consumidores de cada.
- [ ] Não-regressão: os sete `extractors/*.meta.json` de `run_dry_default` e o
      `stdout.txt` de `run_main` continuam idênticos.

---

## [T03] — `HttpTransport`: tirar a construção do transporte de dentro da `Engine`

**Depende de:** Nenhuma tecnicamente, mas vem depois de T02 na ordem do plano.
**Arquivos envolvidos:** `har_reproducer/contracts/http_transport.py` (novo, `HttpTransport`), `har_reproducer/contracts/__init__.py` (export), `har_reproducer/engines/engine.py` (`__init__`, `_build_http_transport`), `har_reproducer/engines/construction/engine_factory.py` (`create`), `har_reproducer/cli/cli_handlers.py` (`_run_without_proxy`, `_run_with_proxy`), `har_reproducer/replay/replay_runner.py` (tipo do atributo)

**Contexto:**
`Engine` decide sozinha se existe transporte e o constrói, o que amarra qualquer
teste de `Engine` a um `curl` de verdade via subprocess. O ramo `replay` já
recebe o transporte pronto (`cli_handlers.py:134`). Esta task alinha o ramo
`run`. **Ela precisa vir antes de T04**: `Engine.__init__` não pode virar
atribuição pura enquanto `_build_http_transport` existir, então T04 executaria
esta costura de qualquer jeito, e esta task chegaria vazia.

**Estado atual:**
- `engine.py:52`:
  ```python
  self.http_transport: Optional[CurlHttpTransport] = self._build_http_transport(proxy_port, ca_cert_path)
  ```
- `engine.py:59-65`:
  ```python
  def _build_http_transport(self, proxy_port, ca_cert_path) -> Optional[CurlHttpTransport]:
      if not self.USES_NETWORK:
          return None
      assert proxy_port is not None
      return CurlHttpTransport(proxy_port, ca_cert_path)
  ```
- `EngineFactory.create` (`:20-36`) recebe `proxy_port`/`ca_cert_path` e os
  repassa; `cli_handlers.py:53` e `:62-69` são os dois call sites.
- `ReplayRunner` tipa `http_transport: CurlHttpTransport` (`:23`, `:34`).

**Estado esperado depois:**
- `contracts/http_transport.py`:
  ```python
  class HttpTransport(Protocol):
      def send_request(self, curl_literal: str, step_index: int) -> StepResponse: ...
  ```
- `Engine.__init__` troca `(proxy_port, ca_cert_path)` por
  `http_transport: Optional[HttpTransport]` e apenas atribui.
  `_build_http_transport` e o `assert proxy_port is not None` somem de `Engine`.
- **Assinatura intermediária** — `EngineFactory` continua `@classmethod` nesta
  task:
  ```python
  @classmethod
  def create(cls, mode, har_path, output_dir, config_path,
             http_transport: Optional[HttpTransport] = None) -> Engine:
      engine_cls: Type[Engine] = cls.resolve_class(mode)
      transport: Optional[HttpTransport] = http_transport if engine_cls.USES_NETWORK else None
      if engine_cls.USES_NETWORK:
          assert transport is not None
      return engine_cls(har_path, output_dir, config_path=config_path, http_transport=transport)
  ```
- `_run_with_proxy` constrói
  `CurlHttpTransport(orchestrator.port, orchestrator.ca_cert_path)` e o passa;
  `_run_without_proxy` não passa nada.
- `ReplayRunner.http_transport` passa a ser tipado `HttpTransport`.

⚠️ **A invariante tem que ficar dentro de `create`, não na convenção do
chamador.** `_build_http_transport` devolve `None` quando `USES_NETWORK` é falso
**independente dos argumentos** — é isso que impede uma `DryEngine` de receber
transporte. Delegar a decisão a quem chama perde a garantia.

⚠️ **`http_transport=None` como default é exceção deliberada à regra 6** deste
plano, e só existe nesta task: T04 elimina o default ao reescrever a factory.

⚠️ **`engine.py` para de importar `CurlHttpTransport`, mas continua importando
`StepRetryPolicy` e `StepSkipEvaluator`** do mesmo pacote (`:16`). Não apagar a
linha inteira.

⚠️ **`CurlHttpTransport` passa a nascer antes de `Workspace.init`** (que nesta
task ainda está em `engine.py:37`). É inócuo: `CurlHttpTransport.__init__`
(`:16-18`) são duas atribuições, sem I/O — e é exatamente o que
`_build_replay_runner:134` já faz hoje.

**Critérios de aceite:**
- [ ] `uv run pytest --runslow` → 39 passed, sem regravar golden.
- [ ] `grep -n "_build_http_transport\|proxy_port" har_reproducer/engines/engine.py`
      não retorna nada.
- [ ] `grep -n "CurlHttpTransport" har_reproducer/engines/` não retorna nada.
- [ ] `run --mode dry` continua com `engine.http_transport is None`; `run --mode
      main` continua com um transporte real.
- [ ] Não-regressão: `tests/golden/run_main/` e os 10 goldens de `replay`
      continuam idênticos — é o que prova que o transporte real não mudou de
      comportamento.

---

## [T04] — `EngineFactory`: virar a raiz de composição do ramo `run`

**Depende de:** T02 (as três classes de tracking já recebem colaboradores) e T03 (o transporte já chega pronto).
**Arquivos envolvidos:** `har_reproducer/engines/construction/engine_factory.py` (reescrita), `har_reproducer/engines/engine.py` (`__init__`, `_build_llm`), `har_reproducer/cli/cli_handlers.py` (`handle_run`, `_run`, `_run_without_proxy`, `_run_with_proxy`)

**Contexto:**
`Engine.__init__` (`:26-57`) faz, num bloco só: inicializar estado global, ler
config do disco, construir um cliente de LLM que pode lançar, e montar oito
colaboradores. Esta task o reduz a atribuição pura, no formato de
`ReplayRunner.__init__`, e concentra a montagem na `EngineFactory` — que já
existe e já instancia a `Engine`. O corte: **a CLI possui o que vem de argv e do
processo** (paths, `--reset`, config, porta do mitmdump, transporte); **a factory
possui o que vem do domínio**.

**Estado atual:**
- `engine.py:35` `self.output_dir`; `:37` `Workspace.init(output_dir)`;
  `:38-42` cinco atributos de diretório; `:48` `ProjectConfigLoader.load`;
  `:56` `_build_llm`; `:67-76` o `_build_llm` com o `print`.
- `cli_handlers.py:47` lê `USES_NETWORK` via `self._engine_factory.resolve_class(mode)`;
  `:57` carrega o config **de novo** para o proxy (duas cargas em modo `main`).
- `EngineFactory` é toda `@classmethod` (`:15-36`).

**Estado esperado depois:**
- `EngineFactory` em forma de **instância, sem nenhum `@classmethod`**:
  - `__init__(self, project_config: ProjectConfig) -> None` — **um** parâmetro
    nesta task; constrói e guarda `self.llm`, absorvendo `_build_llm` de
    `engine.py:67-76` **com o `print` intacto**;
  - `resolve_class(self, mode)` vira método de instância lendo o `ClassVar
    _STRATEGIES`;
  - `create(self, mode, har_path, http_transport)` calcula
    `tracking_responses_dir` (`real_responses` se `USES_NETWORK`, senão
    `original_responses`), monta o grafo em métodos privados pequenos, aplica a
    invariante de transporte de T03 e devolve a `Engine`.
- `Engine.__init__` vira atribuição pura:
  ```python
  def __init__(self, har_path, session_store, tracker, token_resolver,
               skip_evaluator, retry_policy, validator, success_criteria,
               http_transport) -> None:
  ```
- `handle_run`: `output_dir` → `--reset` → `Workspace.init(output_dir)` →
  `ProjectConfigLoader.load` → `EngineFactory(project_config)` → dispatch.
- **Carga única de config**: `_run_with_proxy` usa o `ProjectConfig` que já
  recebe, em vez de carregar de novo.
- Código morto removido de `Engine`: `output_dir` (`:35`), `curls_dir`,
  `original_responses_dir`, `extractors_dir`, `temp_extractors_dir`
  (`:38-42`). `tracking_responses_dir` não é morto — muda de dono, indo para a
  factory.

⚠️ **A factory é construída exatamente uma vez, em `handle_run`, e repassada aos
dois ramos.** `_run` precisa dela antes do branch, para chamar `resolve_class`.
Se `_run_with_proxy`/`_run_without_proxy` construírem outra, o LLM nasce duas
vezes e a linha `LLM fallback enabled from config: …` **sai duplicada** — e
nenhum dos 39 testes pega, porque nenhum cenário golden configura `llm`.

⚠️ **`Workspace.init(output_dir)` continua sendo `@classmethod` nesta task** —
só muda de lugar, de `engine.py:37` para `handle_run`, depois do `--reset`. Ele
precisa rodar antes da factory, porque `create` lê `Workspace.real_responses` /
`Workspace.original_responses`, atributos que só existem depois do `setattr` de
`workspace.py:23-26`. T07 troca essa linha por `Workspace(output_dir)`.

⚠️ **`handle_parse` não muda e não pode ganhar `Workspace`.** Ele usa
`HARParser.split_har`, que cria só `<output>/parse/`. Construir um `Workspace`
ali criaria os oito subdiretórios e quebraria os quatro goldens de `parse`, que
contêm apenas `parse/` e `stdout.txt`.

⚠️ **`--reset` (`cli_handlers.py:180-183`) roda antes do `Workspace`**, senão
apaga o que acabou de criar.

⚠️ **Ordem obrigatória: workspace primeiro, LLM depois.** Hoje `Workspace.init`
(`:37`) precede `_build_llm` (`:56`) dentro do mesmo `__init__`, e é isso que
garante que um provider inválido falhe **com a árvore já em disco**. Sem
cobertura nos 39 testes — nenhum configura `llm`.

⚠️ **A carga única muda uma coisa em caso de borda:** com `--config` malformado,
o traceback do fail-soft saía duas vezes em modo `main` e passa a sair uma.
Nenhum dos 9 cenários de `tests/test_cli_config.py` usa JSON malformado.

⚠️ **Não "otimizar" pulando `_apply_defaults` em modo `dry`.** Ele chama
`Workspace.get_mitmproxy_ca_path()`, que faz `mkdir` de `<repo>/.mitmproxy` —
fora de `--output`, portanto invisível ao `GoldenWorkspace`. Pular deixaria de
criar o diretório e nada falharia.

⚠️ **`_run_without_proxy` e `_run_with_proxy` (`:52`, `:56`) estão sem anotação
de tipo hoje.** Ao reescrevê-los, tipar — é exigência do guia.

⚠️ **`main.py` não muda.** `CliHandlers` continua recebendo
`Type[EngineFactory]` e passa a instanciá-lo dentro de `handle_run`, nunca no
`__init__`.

**Critérios de aceite:**
- [ ] `uv run pytest --runslow` → 39 passed, sem regravar golden.
- [ ] `grep -n "@classmethod" har_reproducer/engines/construction/engine_factory.py`
      não retorna nada.
- [ ] `Engine.__init__` não contém nenhuma chamada de construtor nem
      `ProjectConfigLoader` nem `Workspace`.
- [ ] `grep -rn "ProjectConfigLoader.load" har_reproducer/` retorna **duas**
      linhas, ambas em `cli_handlers.py` (uma em `handle_run`, uma em
      `handle_replay`), contra três hoje — `cli_handlers.py:57`, `:92` e
      `engine.py:48`.
- [ ] `grep -n "curls_dir\|extractors_dir\|temp_extractors_dir\|self.output_dir" har_reproducer/engines/engine.py`
      não retorna nada.
- [ ] `EngineFactory` é instanciada **uma** vez por invocação de `handle_run` —
      conferir lendo `_run`, `_run_with_proxy` e `_run_without_proxy`.
- [ ] `run --mode dry` e `run --mode main` recebem `tracking_responses_dir`
      diferentes (`original_responses` e `real_responses`), e o valor chega
      **idêntico** a `TokenResolver` e `CandidateResolver`.
- [ ] Não-regressão: `tests/golden/run_dry_default/`, `run_dry_reset_removes_litter/`,
      `run_dry_skip_rules_methods/`, `run_main/` e os 4 de `parse` idênticos.

---

## [T05] — `ScriptExecutor`: encapsular o `subprocess.run([sys.executable, ...])` duplicado

**Depende de:** T01 (a `AgentFactory` é o funil até o `BaseAgent`) e T04 (a raiz é quem constrói o executor).
**Arquivos envolvidos:** `har_reproducer/models/execution.py` (novo, `ScriptExecutionResult`), `har_reproducer/models/__init__.py`, `har_reproducer/reproduction/script_executor.py` (novo, `ScriptExecutor`), `har_reproducer/reproduction/__init__.py`, `har_reproducer/agents/base_agent.py` (`_execute_script`, `__init__`), `har_reproducer/reproduction/extractor_runner.py` (`_execute_extractor_script`, novo `__init__`), `har_reproducer/agents/construction/agent_factory.py`, `har_reproducer/engines/construction/engine_factory.py`, `har_reproducer/cli/cli_handlers.py`

**Contexto:**
`subprocess.run([sys.executable, str(path)], capture_output=True, text=True, …)`
aparece cru em dois lugares. Enquanto estiver assim, nenhum teste de
`BaseAgent.run_tdd_loop` ou de `ExtractorRunner` roda sem gerar processo. O ganho
aqui é **a costura, não o reuso**: o trecho genuinamente comum são ~6 linhas.

**Estado atual — e as quatro divergências que precisam sobreviver:**

| | `BaseAgent._execute_script` (`:181-200`) | `ExtractorRunner._execute_extractor_script` (`:52-71`) |
|---|---|---|
| exceção capturada | só `subprocess.TimeoutExpired` (`:189`) | `Exception` (`:66`) |
| retorno | `Tuple[bool, Optional[str]]` | `Optional[str]` |
| `env` | não passa (herda do pai) | passa `env=` (`:64`) |
| timeout | literal `5` (`:187`) | `EXTRACTOR_TIMEOUT_SECONDS: ClassVar[int]` (`:14`) |

**Estado esperado depois:**
- `models/execution.py`:
  ```python
  class ScriptExecutionResult(BaseModel):
      timed_out: bool
      return_code: int
      stdout: str
      stderr: str
  ```
- `reproduction/script_executor.py` com `ScriptExecutor`,
  `TIMEOUT_RETURN_CODE: ClassVar[int] = -1`, e
  `run(self, script_path: Path, timeout_seconds: float, env: Optional[Dict[str, str]] = None) -> ScriptExecutionResult`
  capturando **exclusivamente** `subprocess.TimeoutExpired`.
- `BaseAgent.__init__` recebe `script_executor`; `_execute_script` chama
  `run(path, 5)` sem `env`, testa `result.timed_out` como guard clause
  (imprimindo `[AVISO] Timeout ao verificar extrator para {token_id}` e
  devolvendo `(False, "Timeout during verification")`), e mantém o resto igual.
- `ExtractorRunner` ganha `__init__(self, script_executor: ScriptExecutor)` e
  mantém o **seu próprio** `try/except Exception` em volta da chamada a
  `ScriptExecutor.run`.
- `AgentFactory` e `EngineFactory` recebem e repassam `script_executor`;
  `handle_run` constrói um.
- **`handle_replay` constrói o seu próprio `ScriptExecutor`** e o passa ao
  `ExtractorRunner` de `cli_handlers.py:126`.

⚠️ **Não unificar as divergências "já que está mexendo".** Em `BaseAgent` um
`OSError` **propaga**; em `ExtractorRunner` vira `None`. O literal `5` de
`base_agent.py:187` **continua literal** — a assimetria literal-vs-`ClassVar`
faz parte do que está congelado.

⚠️ **Num timeout, `ExtractorRunner` continua devolvendo `None`** pelo caminho
`return_code == -1` → `if result.return_code != 0: return None`, que é o mesmo
resultado do `except Exception` de hoje.

⚠️ **`env=None` herda o ambiente do pai** — exatamente o comportamento atual de
`BaseAgent`, que não passa `env`. Passar `None` explicitamente preserva isso.

⚠️ **`ExtractorRunner` tem dois call sites depois de T04**: o novo, dentro da
`EngineFactory`, e `cli_handlers.py:126`, no ramo `replay`. **Esquecer o
segundo produz `TypeError` que os 28 testes offline não pegam** — só o
`--runslow`.

**Critérios de aceite:**
- [ ] `uv run pytest --runslow` → 39 passed, sem regravar golden.
- [ ] `grep -rn "subprocess.run(\[sys.executable" har_reproducer/` só acha
      `script_executor.py`.
- [ ] `BaseAgent._execute_script` não tem `except Exception`;
      `ExtractorRunner._execute_extractor_script` tem.
- [ ] `grep -n "ExtractorRunner(" har_reproducer/` acha exatamente **dois** call
      sites, e os dois passam `script_executor`.
- [ ] Não-regressão: `tests/golden/run_dry_default/temp_extractors/` continua com
      os **5** arquivos, e `run_main/temp_extractors/` continua vazio — é o que
      prova que o momento de `_cleanup_script`/`_cleanup_temp_file` não mudou.
- [ ] Não-regressão: `run_main/stdout.txt` mantém as duas linhas
      `Attempt 1 failed for …`.

---

## [T06] — `Sleeper`: costura de espera para `BaseAgent` e `CurlHttpTransport`

**Depende de:** T01, T03 e T04 (a `AgentFactory` é o funil até o `BaseAgent`; a partir de T03 o `CurlHttpTransport` do ramo `run` nasce no `CliHandlers`; a raiz é quem constrói o `Sleeper`).
**Arquivos envolvidos:** `har_reproducer/reproduction/sleeper.py` (novo, `Sleeper`), `har_reproducer/reproduction/__init__.py`, `har_reproducer/agents/base_agent.py` (`run_tdd_loop`, `__init__`), `har_reproducer/reproduction/curl_http_transport.py` (`_read_captured_response`, `__init__`), `har_reproducer/agents/construction/agent_factory.py`, `har_reproducer/engines/construction/engine_factory.py`, `har_reproducer/cli/cli_handlers.py`

**Contexto:**
Dois `time.sleep` custam tempo de parede real em qualquer teste que passe por
eles: `BaseAgent.run_tdd_loop:161` (5 s por tentativa falha) e
`CurlHttpTransport._read_captured_response:67` (5 × 0,1 s por step). Esta costura
permite que os unitários da Etapa C não paguem essa espera.

**Estado atual:**
- `base_agent.py:161`: `time.sleep(self.RETRY_DELAY_SECONDS)` (5 s).
- `curl_http_transport.py:62-68`: laço de `CAPTURE_READ_ATTEMPTS = 5` com
  `time.sleep(self.CAPTURE_READ_RETRY_INTERVAL_SECONDS)` (0,1 s).

**Estado esperado depois:**
- `reproduction/sleeper.py`:
  ```python
  class Sleeper:

      @staticmethod
      def sleep(seconds: float) -> None:
          time.sleep(seconds)
  ```
- `BaseAgent.__init__` e `CurlHttpTransport.__init__` recebem `sleeper: Sleeper`;
  as duas chamadas viram `self.sleeper.sleep(...)`.
- `AgentFactory` e `EngineFactory` recebem e repassam; `handle_run` constrói um.
- **`handle_replay` constrói o seu próprio `Sleeper`** e o passa ao
  `CurlHttpTransport` de `cli_handlers.py:134`.

⚠️ **`MitmProxyOrchestrator._wait_until_ready:101` fica de fora.** É supervisão
de processo externo, fora das cinco costuras — não "aproveitar" para incluí-lo.

⚠️ **Esta costura não acelera a suíte.** Os testes golden entram por `main()`,
que monta o `Sleeper` de produção: os ~32 s continuam. Quem esperar ~12 s depois
desta task vai achar que algo quebrou. (A §3.7 da spec da Etapa A prometeu o
contrário; a §2.7 desta spec corrige.)

⚠️ **`CurlHttpTransport` tem dois call sites depois de T03**: o de
`_run_with_proxy` e `cli_handlers.py:134`. Esquecer o segundo produz `TypeError`
invisível aos 28 offline.

⚠️ **`@staticmethod` porque `sleep` não usa estado de instância**, como o guia
exige. Não atrapalha o dublê da Etapa C: uma subclasse pode sobrescrever com
método de instância e contar chamadas.

**Critérios de aceite:**
- [ ] `uv run pytest --runslow` → 39 passed, sem regravar golden.
- [ ] `grep -rn "time.sleep" har_reproducer/` acha exatamente **dois** pontos:
      `sleeper.py` e `mitm_proxy_orchestrator.py:101`.
- [ ] `grep -n "CurlHttpTransport(" har_reproducer/` acha **dois** call sites, e
      os dois passam `sleeper`.
- [ ] O tempo de `uv run pytest --runslow` **não cai** de forma relevante —
      continua na casa dos ~32 s. Uma queda para ~12 s significa que o `Sleeper`
      de produção virou no-op por engano.
- [ ] Não-regressão: `run_main/stdout.txt` e os 10 goldens de `replay` idênticos.

---

## [T07] — `Workspace`: deixar de ser singleton e virar instância injetada

**Depende de:** T01 a T06 (nesta ordem, as três classes de tracking já não referenciam `Workspace` e as duas raízes já existem para receber a instância).
**Arquivos envolvidos:** `har_reproducer/fs_io/workspace.py` (reescrita), `har_reproducer/cli/cli_handlers.py`, `har_reproducer/engines/construction/engine_factory.py`, `har_reproducer/engines/engine.py`, `har_reproducer/agents/base_agent.py`, `har_reproducer/agents/construction/agent_factory.py`, `har_reproducer/reproduction/extractor_runner.py`, `har_reproducer/reproduction/extractor_metadata_store.py`, `har_reproducer/reproduction/curl_http_transport.py`, `har_reproducer/reproduction/mitm_proxy_orchestrator.py`, `har_reproducer/replay/replay_runner.py`, `har_reproducer/replay/replay_result_comparator.py`

**Contexto:**
`Workspace` é a última fonte de estado global do projeto: os oito atributos de
diretório são só anotações, materializadas por `setattr` de atributo de classe
quando `init()` roda. Não há `reset`, o estado vaza entre invocações no mesmo
processo, e nada disso é verificável estaticamente. Esta é a task que fecha a
etapa. Vem por último de propósito: nesta ordem, `CandidateResolver`,
`TokenResolver` e `TokenTracker` **não precisam ser tocados** — verificado, as
três têm zero referências a `Workspace`.

**Estado atual:**
```python
class Workspace:
    _output_dir: Optional[Path] = None

    curls: Path
    real_responses: Path
    ...

    @classmethod
    def init(cls, output_dir: Path) -> None:
        cls._output_dir = Path(output_dir)
        cls._output_dir.mkdir(parents=True, exist_ok=True)
        for workspace_dir in WorkspaceDir:
            path: Path = cls._output_dir / workspace_dir.value
            path.mkdir(parents=True, exist_ok=True)
            setattr(cls, workspace_dir.value, path)
```
Mais `_ensure_initialized` (`:28-33`), onze métodos de caminho `@classmethod`, e
dois `@staticmethod` que **não** dependem de `output_dir`: `get_root_path`
(`:35-37`) e `get_mitmproxy_ca_path` (`:39-43`).

**Estado esperado depois:**
- `Workspace` vira classe comum:
  ```python
  def __init__(self, output_dir: Path) -> None:
      self.output_dir: Path = Path(output_dir)
      self.output_dir.mkdir(parents=True, exist_ok=True)

      self.curls: Path = self._prepare_dir(WorkspaceDir.CURLS)
      self.real_responses: Path = self._prepare_dir(WorkspaceDir.REAL_RESPONSES)
      self.original_responses: Path = self._prepare_dir(WorkspaceDir.ORIGINAL_RESPONSES)
      self.real_requests: Path = self._prepare_dir(WorkspaceDir.REAL_REQUESTS)
      self.extractors: Path = self._prepare_dir(WorkspaceDir.EXTRACTORS)
      self.temp_extractors: Path = self._prepare_dir(WorkspaceDir.TEMP_EXTRACTORS)
      self.mitm_capture: Path = self._prepare_dir(WorkspaceDir.MITM_CAPTURE)
      self.replays: Path = self._prepare_dir(WorkspaceDir.REPLAYS)

  def _prepare_dir(self, workspace_dir: WorkspaceDir) -> Path:
      path: Path = self.output_dir / workspace_dir.value
      path.mkdir(parents=True, exist_ok=True)
      return path
  ```
- Os onze métodos de caminho viram de instância. `_output_dir`, `init()` e
  `_ensure_initialized()` deixam de existir.
- `get_root_path` e `get_mitmproxy_ca_path` **continuam `@staticmethod` na
  classe**, e `config/project_config_loader.py` **não muda**.
- Recebem `workspace` por construtor: `Engine`, `EngineFactory`, `AgentFactory`
  → `BaseAgent`, `ExtractorRunner`, `ExtractorMetadataStore` (que ganha
  `__init__` pela primeira vez), `CurlHttpTransport`, `MitmProxyOrchestrator`,
  `ReplayRunner`, `ReplayResultComparator`.
- `handle_run`: a linha `Workspace.init(output_dir)` de T04 vira
  `workspace: Workspace = Workspace(output_dir)`.
- `handle_replay`, nesta ordem exata: validar flags → `output_dir.exists()` →
  `Workspace(output_dir)` → checar `req_*.curl.sh` → carregar config →
  orquestrador → runner. `_prepare_replay_workspace` passa a **devolver** o
  `Workspace`.

⚠️ **As oito atribuições seguem a ordem de declaração de `WorkspaceDir`**
(`fs_io/workspace_dir.py:5-12`), que é a ordem em que o `for` de hoje cria os
diretórios.

⚠️ **Materialização *eager* é contrato golden.** Os oito diretórios existem e são
comparados nos goldens de `run`, `replay` e `criteria` — `GoldenWorkspace` grava
todo diretório como `<EMPTY_DIR>` (`golden_workspace.py:76-78`). Um `Workspace`
preguiçoso quebra a suíte.

⚠️ **A checagem `output_dir.exists()` de `handle_replay` (`:105-106`) precede a
construção do `Workspace`.** O construtor cria o diretório; invertido, o
`ValueError("Workspace directory does not exist: …")` nunca dispararia e
`test_replay_workspace_does_not_exist` cairia.

⚠️ **A checagem de curls (`:109-110`) vem depois do `Workspace`**, que cria os
subdiretórios faltantes — como `init()` faz hoje. `test_replay_workspace_has_no_curl_files`
parte de um `output_dir` vazio e depende disso.

⚠️ **Dois `@staticmethod` fora do `CliHandlers` deixam de ser estáticos**, porque
passam a precisar de `self.workspace`:
- `CurlHttpTransport._try_read_capture` (`:70-71`);
- `ReplayResultComparator._read_reference_text` (`:23-24`).

⚠️ **Os três métodos de replay do `CliHandlers` continuam `@staticmethod`**,
recebendo `workspace` por parâmetro. `CliHandlers` não guarda workspace — ele é
por invocação —, então torná-los de instância contrariaria o guia.

⚠️ **`ReplayRunner` mantém os três parâmetros `Path` que já recebe**
(`replay_run_dir`, `res_refer_dir`, `original_responses_dir`), em vez de
derivá-los do `workspace`. `replay_run_dir` é criado **eagerly** em
`_build_replay_runner` (`:144`), antes de `orchestrator.run` — e continua
existindo, vazio, quando `_require_all_existing` levanta `ValueError`. Derivá-lo
preguiçosamente faria o diretório sumir nesse caminho, e
`test_replay_missing_step` não assere árvore. `res_refer_dir` pode vir do
`config.json`, não do workspace.

⚠️ **Conferência final por grep, obrigatória.** Sem checador estático, é a única
rede para os pontos que nenhum dos 39 testes exercita. `grep -rn "Workspace\." har_reproducer/`
deve sobrar apenas `project_config_loader.py:37` e o uso interno em
`workspace.py`. **Dois pontos merecem verificação manual**, porque a suíte não
passa por eles:
1. `MitmProxyOrchestrator._build_early_exit_message` (`:113`) — só roda quando o
   `mitmdump` morre antes de ficar pronto;
2. `ReplayRunner._annotate_static_tokens` (`:102`) — só roda quando
   `valid_count >= STATIC_CONFIRMATION_THRESHOLD = 5`
   (`replay_token_resolver.py:11,84`). Medido: cada cenário de `replay` parte de
   cópia fresca, `valid_count` é **1** nos sete `.meta.json` de
   `tests/golden/replay_all/`, e `probably static` não aparece em golden nenhum.
   É o único caminho que reescreve `curls/` durante um replay.

⚠️ **`templates/extractor_template.py` não muda** — importa só o enum
`WorkspaceDir` (`:3`, `:56`). Mas note que o script gerado resolve a resposta por
`Path(__file__).resolve().parent.parent / "real_responses"`: ele **assume que
mora em `<output>/extractors/`**. O layout continua contrato do arquivo gerado.

**Critérios de aceite:**
- [ ] `uv run pytest --runslow` → 39 passed, sem regravar golden.
- [ ] `grep -rn "Workspace\." har_reproducer/` retorna apenas
      `config/project_config_loader.py:37` e as ocorrências internas de
      `fs_io/workspace.py`.
- [ ] `grep -n "init\|_ensure_initialized\|_output_dir\|classmethod" har_reproducer/fs_io/workspace.py`
      não retorna nada.
- [ ] `Workspace(tmp_path)` num REPL cria os oito subdiretórios e devolve um
      objeto cujos oito atributos são `Path` existentes — sem nenhuma chamada
      prévia.
- [ ] Duas instâncias de `Workspace` sobre diretórios diferentes coexistem sem
      interferência (é o que o singleton impedia).
- [ ] `replay` sobre diretório inexistente continua levantando
      `ValueError("Workspace directory does not exist: …")` **e não cria o
      diretório**.
- [ ] `replay` sobre `output_dir` vazio continua levantando
      `ValueError("Workspace has no curl files: …")` **depois** de criar os oito
      subdiretórios.
- [ ] Conferência manual dos dois pontos não exercitados
      (`_build_early_exit_message` e `_annotate_static_tokens`) — nenhuma
      referência a `Workspace` sobrando neles.
- [ ] Não-regressão: os 25 diretórios de `tests/golden/` idênticos, incluindo os
      `<EMPTY_DIR>` de `mitm_capture/`, `real_responses/`, `replays/` e
      `temp_extractors/`.

---

## Fechamento

Depois da T07: marcar os checkboxes deste plano, commitar como
`doc: marcando tasks concluídas`, e fechar a etapa com
`git checkout master && git merge --no-ff 20260806-2-refatoracao-de-testabilidade`.

Na retro (Passo 5 de [[spec-e-plano]]), dois itens já identificados:
1. **`arquitetura-e-fundamentos`** — o mapa descreve `Workspace` como
   "centraliza os caminhos do diretório de output" sem dizer que é singleton;
   depois desta etapa, vale registrar a injeção. E o "Riscos aceitos" #2 da spec
   da Etapa A ("a suíte não pode rodar em paralelo nem com ordem aleatória")
   deixa de valer.
2. **`guia-de-estilo`** — já atualizado antes desta etapa começar, para não
   confundir a implementação: a linha de dependências agora diz "recebidas por
   construtor", e a de `@classmethod` trocou `Workspace`/`EngineFactory` por
   `LLMFactory`/`HARParser`/`ResponseGrep`/`TokenLocationDetector`. Confirmar na
   retro que o texto bate com o código final.
