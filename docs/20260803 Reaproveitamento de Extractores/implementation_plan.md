# Plano de Implementação — Reaproveitamento de Extractors entre Execuções e Detecção de Tokens Estáticos

> Baseado em `spec_reaproveitamento_de_extractors.md`. Ordem das tasks é topológica
> (nenhuma task depende de uma task posterior). Cada task é autocontida — não deveria
> ser necessário reabrir a spec pra executar uma task isolada.

---

## T01 — `Extractor`: campos de persistência/estabilidade
**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/session.py` (`Extractor`)

**Contexto:**
O mecanismo de reaproveitamento (T05) e o contador de estabilidade (T06) precisam de
três campos novos no model que já representa um extractor em memória — sem eles não há
onde guardar o estado persistido entre execuções (spec seção 3.1).

**Estado atual:**
```python
class Extractor(BaseModel):
    token_id: str
    code: str
    verified: bool = False
    agent_type: AgentType
    origin_step: Optional[int] = None
    temp_file_path: Optional[str] = None
```

**Estado esperado depois:**
```python
class Extractor(BaseModel):
    token_id: str
    code: str
    verified: bool = False
    agent_type: AgentType
    origin_step: Optional[int] = None
    temp_file_path: Optional[str] = None
    valid_count: int = 0
    last_value: Optional[str] = None
    ever_changed: bool = False
```
- ⚠️ Só os três campos novos, no fim da classe (manter ordem dos existentes intacta —
  `model_dump_json`/`model_validate_json` de quem já usa `Extractor` por posição
  indireta, ex. testes que comparam dict, não deveriam quebrar).

**Critérios de aceite:**
- [x] `Extractor(token_id="x", code="...", agent_type=AgentType.REGEX)` continua
      funcionando sem passar os três campos novos, com `valid_count == 0`,
      `last_value is None`, `ever_changed is False`.
- [x] `Extractor(..., valid_count=3, last_value="abc", ever_changed=True)` aceita e
      preserva os valores.
- [x] `extractor.model_dump_json()` inclui os três campos novos.
- [x] `Extractor.model_validate_json(extractor.model_dump_json())` reconstrói um objeto
      igual (round-trip).
- [x] Nenhuma regressão em usos existentes de `Extractor` (`CandidateResolver`,
      `BaseAgent.run_tdd_loop`, `TokenResolver`, `PlaceholderApplier`).

---

## T02 — `Workspace`: `extractor_meta_file`
**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/fs_io/workspace.py` (`Workspace`)

**Contexto:**
Precisa de um caminho canônico pro arquivo de metadados de cada extractor, irmão do
`.py` já existente, seguindo exatamente o mesmo padrão dos demais métodos de path
(spec seção 3.2).

**Estado atual:**
```python
@classmethod
def extractor_file(cls, safe_token_id: str) -> Path:
    cls._ensure_initialized()
    return cls.extractors / f"extract_{safe_token_id}.py"
```
Não existe nenhum método equivalente para um arquivo de metadados.

**Estado esperado depois:**
```python
@classmethod
def extractor_meta_file(cls, safe_token_id: str) -> Path:
    cls._ensure_initialized()
    return cls.extractors / f"extract_{safe_token_id}.meta.json"
```
- ⚠️ Mesmo diretório (`cls.extractors`) do `.py` — não cria subpasta nova, não precisa
  de `mkdir` adicional (o diretório pai já existe desde `Workspace.init`).

**Critérios de aceite:**
- [x] `Workspace.extractor_meta_file("abc123")` retorna
      `<output_dir>/extractors/extract_abc123.meta.json`.
- [x] Não lança erro antes de `Workspace.init` ter sido chamado (mesma regra de
      `_ensure_initialized` dos demais métodos — deve lançar `RuntimeError`, não
      silenciar).
- [x] `extractor_file`/`extractor_meta_file` com o mesmo `token_id` retornam caminhos no
      mesmo diretório, nomes diferentes.
- [x] Nenhuma regressão nos demais métodos de `Workspace`.

---

## T03 — `ExtractorMetadataStore`: leitura/escrita do metadado em disco
**Depende de:** T01 (`Extractor` com os campos novos), T02 (`Workspace.extractor_meta_file`)
**Arquivos envolvidos:** `har_reproducer/reproduction/extractor_metadata_store.py` (novo),
`har_reproducer/reproduction/__init__.py`

**Contexto:**
Único ponto de I/O do `.meta.json` — usado tanto por `CandidateResolver` (T05, grava ao
gerar/reaproveitar) quanto por `ReplayTokenResolver` (T06, lê/atualiza o contador). Fica
em `reproduction/` porque é o mesmo pacote de `ExtractorRunner`, o outro componente que
já opera sobre os artefatos de `Workspace.extractors` (spec seção 3.2).

**Estado atual:**
Esse componente não existe.

**Estado esperado depois:**
```python
from pathlib import Path
from typing import Optional

from har_reproducer.fs_io import Workspace
from har_reproducer.models import Extractor


class ExtractorMetadataStore:
    def load(self, token_id: str) -> Optional[Extractor]:
        meta_file: Path = Workspace.extractor_meta_file(token_id)
        if not meta_file.exists():
            return None
        try:
            return Extractor.model_validate_json(meta_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[AVISO] Falha ao carregar metadado do extractor '{token_id}': {e}")
            return None

    def save(self, extractor: Extractor) -> None:
        meta_file: Path = Workspace.extractor_meta_file(extractor.token_id)
        meta_file.write_text(extractor.model_dump_json(indent=2), encoding="utf-8")
```
- ⚠️ `load` trata JSON corrompido/schema incompatível como "não existe metadado" — nunca
  propaga exceção (spec seção 5, mesma filosofia de degradação de
  `CandidateResolver._load_response`).
- Adicionar em `reproduction/__init__.py`:
  ```python
  from har_reproducer.reproduction.extractor_metadata_store import ExtractorMetadataStore
  ```
  e incluir `"ExtractorMetadataStore"` em `__all__`.

**Critérios de aceite:**
- [x] `load(token_id)` sem arquivo existente retorna `None`, sem lançar.
- [x] `save(extractor)` seguido de `load(extractor.token_id)` retorna um `Extractor`
      igual ao salvo (round-trip via disco).
- [x] `load` com um `.meta.json` contendo JSON inválido (`"{ não é json"`) retorna
      `None` e imprime aviso, não lança.
- [x] `load` com um `.meta.json` de schema incompatível (ex. faltando `agent_type`
      obrigatório) retorna `None` e imprime aviso, não lança.
- [x] `ExtractorMetadataStore` importável via `from har_reproducer.reproduction import
      ExtractorMetadataStore`.

---

## T04 — `BaseAgent.run_tdd_loop`: parâmetro `initial_error`
**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/agents/base_agent.py` (`BaseAgent`)

**Contexto:**
Pré-requisito pro fluxo de correção de T05: hoje o loop de TDD sempre começa com
`last_error = None`, mesmo quando já se sabe, de antemão, por que um extractor
persistido falhou — essa informação hoje não tem como entrar no prompt da primeira
tentativa (spec seção 3.4).

**Estado atual:**
```python
def run_tdd_loop(self, max_attempts: Optional[int] = None, origin_step: Optional[int] = None) -> Optional[Extractor]:
    strategies: List[Strategy] = self._get_strategies()
    total: int = len(strategies) if max_attempts is None else max_attempts

    last_error: Optional[str] = None
    for attempt in range(total):
        ...
```

**Estado esperado depois:**
```python
def run_tdd_loop(
        self,
        max_attempts: Optional[int] = None,
        origin_step: Optional[int] = None,
        initial_error: Optional[str] = None,
) -> Optional[Extractor]:
    strategies: List[Strategy] = self._get_strategies()
    total: int = len(strategies) if max_attempts is None else max_attempts

    last_error: Optional[str] = initial_error
    for attempt in range(total):
        ...
```
- ⚠️ Única mudança de fato: `last_error` deixa de começar sempre em `None` e passa a
  começar em `initial_error` (default `None` — comportamento idêntico ao atual quando
  não passado). Nenhuma outra linha do método muda. `generate_code`/`_llm_strategy`/
  `ExtractorPrompt.build` já aceitam `last_error` — nada muda ali.

**Critérios de aceite:**
- [x] `run_tdd_loop()` sem `initial_error` (chamada como hoje) tem comportamento
      idêntico ao atual — regressão zero.
- [x] `run_tdd_loop(initial_error="algum erro")`: a primeira chamada interna de
      `generate_code` recebe `last_error="algum erro"` (verificável via spy/mock em
      `generate_code` ou em `_llm_strategy`).
- [x] Se a primeira tentativa (já com `initial_error` no prompt) tiver sucesso, o
      `Extractor` retornado é idêntico em estrutura ao caso sem `initial_error`.
- [x] Assinatura mantém `max_attempts`/`origin_step` como estavam — só adiciona
      `initial_error` no fim.

---

## T05 — `CandidateResolver`: reaproveitamento e correção via disco
**Depende de:** T01 (`Extractor`), T03 (`ExtractorMetadataStore`), T04 (`initial_error`)
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (`CandidateResolver`)

**Contexto:**
Núcleo da spec: antes de gerar um extractor do zero, verificar se já existe um
persistido em disco (de uma execução anterior de `run`/`dry`) e se ainda é válido
contra o response atual. Se for válido, reaproveita sem chamar o agente/LLM. Se
existir mas falhar, tenta corrigir passando o erro observado como `initial_error`
(T04) em vez de gerar do zero (spec seção 3.3).

**Estado atual:**
```python
class CandidateResolver:
    def __init__(self, responses_dir: Path, session_store: SessionStore, llm: Optional[BaseChatModel]) -> None:
        self.responses_dir = responses_dir
        self.session_store = session_store
        self.llm = llm

    def _process_candidate(self, candidate: DynamicToken) -> DynamicToken:
        origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, candidate.current_value)
        if not origin:
            candidate.status = "NotFound"
            return candidate

        origin_step: int = origin[0]
        candidate.origin_step = origin_step
        candidate.token_id = self._derive_token_id(candidate.path, origin_step)

        existing: Optional[Extractor] = self.session_store.state.registry.get(candidate.token_id)
        if existing is not None and existing.verified:
            candidate.status = "Resolved"
            return candidate

        candidate.status = "UnderReview"
        response_sample: Optional[Dict[str, Any]] = self._load_response(origin_step)
        if response_sample is None:
            return candidate

        candidate.origin_location = TokenLocationDetector.find(candidate.current_value, response_sample)
        self._register_extractor(candidate, response_sample)
        return candidate

    def _register_extractor(self, candidate: DynamicToken, response_sample: Dict[str, Any]) -> None:
        new_extractor: Optional[Extractor] = self._generate_extractor(candidate, response_sample)
        if new_extractor is not None:
            self.session_store.state.registry[candidate.token_id] = new_extractor
            candidate.status = "Resolved"
        else:
            candidate.status = "Unresolved"

    def _generate_extractor(self, candidate: DynamicToken, response_sample: Dict[str, Any]) -> Optional[Extractor]:
        agent_cls: Type[BaseAgent] = self.LOCATION_AGENTS.get(candidate.origin_location, RegexAgent)
        agent: BaseAgent = agent_cls(
            token_id=candidate.token_id,
            response_sample=response_sample,
            expected_value=candidate.current_value,
            path=candidate.path,
            location=candidate.origin_location.value if candidate.origin_location else None,
            llm=self.llm,
        )
        return agent.run_tdd_loop(origin_step=candidate.origin_step)
```
Não constrói `ExtractorRunner`/`ExtractorMetadataStore` — não tem como consultar disco
hoje.

**Estado esperado depois:**
```python
class CandidateResolver:
    def __init__(self, responses_dir: Path, session_store: SessionStore, llm: Optional[BaseChatModel]) -> None:
        self.responses_dir = responses_dir
        self.session_store = session_store
        self.llm = llm
        self.extractor_runner: ExtractorRunner = ExtractorRunner()
        self.metadata_store: ExtractorMetadataStore = ExtractorMetadataStore()

    def _process_candidate(self, candidate: DynamicToken) -> DynamicToken:
        origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, candidate.current_value)
        if not origin:
            candidate.status = "NotFound"
            return candidate

        origin_step: int = origin[0]
        candidate.origin_step = origin_step
        candidate.token_id = self._derive_token_id(candidate.path, origin_step)

        existing: Optional[Extractor] = self.session_store.state.registry.get(candidate.token_id)
        if existing is not None and existing.verified:
            candidate.status = "Resolved"
            return candidate

        initial_error: Optional[str] = None
        persisted: Optional[Extractor] = self.metadata_store.load(candidate.token_id)
        if persisted is not None:
            result: Optional[str] = self.extractor_runner.run_existing(candidate.token_id)
            if result == candidate.current_value:
                self.session_store.state.registry[candidate.token_id] = persisted
                candidate.status = "Resolved"
                return candidate
            initial_error = self._mismatch_error(result, candidate.current_value)

        candidate.status = "UnderReview"
        response_sample: Optional[Dict[str, Any]] = self._load_response(origin_step)
        if response_sample is None:
            return candidate

        candidate.origin_location = TokenLocationDetector.find(candidate.current_value, response_sample)
        self._register_extractor(candidate, response_sample, initial_error)
        return candidate

    @staticmethod
    def _mismatch_error(result: Optional[str], expected: str) -> str:
        if result is None:
            return "Persisted extractor failed to execute (no output)."
        return f"Persisted extractor output mismatch: got {result!r}, expected {expected!r}"

    def _register_extractor(
            self,
            candidate: DynamicToken,
            response_sample: Dict[str, Any],
            initial_error: Optional[str] = None,
    ) -> None:
        new_extractor: Optional[Extractor] = self._generate_extractor(candidate, response_sample, initial_error)
        if new_extractor is not None:
            self.session_store.state.registry[candidate.token_id] = new_extractor
            self.metadata_store.save(new_extractor)
            candidate.status = "Resolved"
        else:
            candidate.status = "Unresolved"

    def _generate_extractor(
            self,
            candidate: DynamicToken,
            response_sample: Dict[str, Any],
            initial_error: Optional[str] = None,
    ) -> Optional[Extractor]:
        agent_cls: Type[BaseAgent] = self.LOCATION_AGENTS.get(candidate.origin_location, RegexAgent)
        agent: BaseAgent = agent_cls(
            token_id=candidate.token_id,
            response_sample=response_sample,
            expected_value=candidate.current_value,
            path=candidate.path,
            location=candidate.origin_location.value if candidate.origin_location else None,
            llm=self.llm,
        )
        return agent.run_tdd_loop(origin_step=candidate.origin_step, initial_error=initial_error)
```
- ⚠️ `ExtractorRunner()`/`ExtractorMetadataStore()` construídos **internamente** no
  `__init__`, não injetados — segue exatamente o precedente já existente em
  `TokenResolver.__init__` (`self.extractor_runner: ExtractorRunner =
  ExtractorRunner()`). Isso evita qualquer mudança em `TokenTracker.__init__` ou
  `Engine.__init__`, que constroem `CandidateResolver`/`TokenTracker` hoje sem passar
  esses objetos.
- ⚠️ `run_existing(candidate.token_id)` **sem** `response_override_dir` — usa o mesmo
  fallback fixo (`real_responses/`) que `run`/`dry` já usam hoje via `TokenResolver`;
  nenhum comportamento de leitura de response muda.
- ⚠️ `response_sample` só é carregado quando `persisted is None` OU a validação falhou
  — deixa de ser carregado incondicionalmente pra todo candidato `UnderReview` como é
  hoje. Efeito colateral desejado (evita I/O redundante), não é o objetivo principal da
  task.
- `_register_extractor` passa a chamar `self.metadata_store.save(new_extractor)` em
  todo sucesso (geração nova OU correção) — hoje esse método só grava no `registry` em
  memória, nunca em disco.

**Critérios de aceite:**
- [ ] `token_id` sem `.meta.json` em disco: comportamento idêntico ao atual (gera do
      zero via agente, `initial_error=None`).
- [ ] `token_id` com `.meta.json` em disco e `run_existing` retornando exatamente
      `candidate.current_value`: `registry[token_id]` é populado com o `Extractor`
      persistido, **sem** chamar `agent.run_tdd_loop`/`_generate_extractor` (verificável
      via spy/mock — chamada zero ao agente).
- [ ] `token_id` com `.meta.json` em disco e `run_existing` retornando valor diferente
      de `candidate.current_value`: `agent.run_tdd_loop` é chamado com
      `initial_error` não-nulo, contendo o valor obtido e o esperado.
- [ ] `token_id` com `.meta.json` em disco e `run_existing` retornando `None`
      (extractor persistido quebrado/erro de execução): mesmo caminho de correção,
      `initial_error` descreve "failed to execute".
- [ ] Após geração/correção bem-sucedida, `Workspace.extractor_meta_file(token_id)`
      existe em disco e é lido de volta como um `Extractor` válido.
- [ ] `existing.verified` já `True` no `registry` em memória (dedupe intra-run, hoje já
      existente): continua tendo prioridade sobre a checagem em disco — disco só é
      consultado quando `existing is None`.
- [ ] Falha total na correção (agente esgota tentativas mesmo com `initial_error`):
      `status = "Unresolved"`, `.meta.json` antigo em disco **não é sobrescrito** (ainda
      inválido, mas presente pra próxima tentativa).
- [ ] Nenhuma regressão no fluxo de `status = "NotFound"` (quando `ResponseGrep.find`
      não encontra origem).

---

## T06 — `ReplayTokenResolver`: contador de estabilidade + detecção de token estático
**Depende de:** T01 (`Extractor`), T03 (`ExtractorMetadataStore`)
**Arquivos envolvidos:** `har_reproducer/replay/replay_token_resolver.py`
(`ReplayTokenResolver`), `har_reproducer/cli/cli_handlers.py` (`_build_replay_runner`)

**Contexto:**
A cada resolução válida de um token durante `replay`, atualiza o metadado persistido
com o valor observado. Depois de `STATIC_CONFIRMATION_THRESHOLD` (5) resoluções válidas
seguidas com o mesmo valor, o token é reportado como provável estático — é o único
lugar do sistema onde surge, repetidamente, uma amostra nova e ao vivo do valor de um
token (spec seções 3.5/3.7).

**Estado atual:**
```python
class ReplayTokenResolver:
    def __init__(
            self,
            session_store: SessionStore,
            extractor_runner: ExtractorRunner,
            dependency_parser: CurlDependencyParser,
    ) -> None:
        self.session_store = session_store
        self.extractor_runner = extractor_runner
        self.dependency_parser = dependency_parser

    def resolve(self, curl_text: str, schedule: Set[int], replay_run_dir: Path, res_refer_dir: Path) -> None:
        dependencies: Dict[str, int] = self.dependency_parser.parse(curl_text)
        token_ids: Set[str] = set(SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text))
        for token_id in token_ids:
            self._resolve_one(token_id, dependencies, schedule, replay_run_dir, res_refer_dir)

    def _resolve_one(self, token_id, dependencies, schedule, replay_run_dir, res_refer_dir) -> None:
        origin_step: Optional[int] = dependencies.get(token_id)
        override_dir: Path = replay_run_dir if origin_step in schedule else res_refer_dir
        value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
        if value is None:
            print(f"Failed to resolve token '{token_id}' during replay: extractor returned no value.")
            return
        self.session_store.set_token(token_id, value)
```

**Estado esperado depois:**
```python
class ReplayTokenResolver:
    STATIC_CONFIRMATION_THRESHOLD: ClassVar[int] = 5

    def __init__(
            self,
            session_store: SessionStore,
            extractor_runner: ExtractorRunner,
            dependency_parser: CurlDependencyParser,
            metadata_store: ExtractorMetadataStore,
    ) -> None:
        self.session_store = session_store
        self.extractor_runner = extractor_runner
        self.dependency_parser = dependency_parser
        self.metadata_store = metadata_store

    def resolve(self, curl_text: str, schedule: Set[int], replay_run_dir: Path, res_refer_dir: Path) -> Set[str]:
        dependencies: Dict[str, int] = self.dependency_parser.parse(curl_text)
        token_ids: Set[str] = set(SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text))
        static_token_ids: Set[str] = set()
        for token_id in token_ids:
            if self._resolve_one(token_id, dependencies, schedule, replay_run_dir, res_refer_dir):
                static_token_ids.add(token_id)
        return static_token_ids

    def _resolve_one(self, token_id, dependencies, schedule, replay_run_dir, res_refer_dir) -> bool:
        origin_step: Optional[int] = dependencies.get(token_id)
        override_dir: Path = replay_run_dir if origin_step in schedule else res_refer_dir
        value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
        if value is None:
            print(f"Failed to resolve token '{token_id}' during replay: extractor returned no value.")
            return False
        self.session_store.set_token(token_id, value)
        return self._record_observation(token_id, value)

    def _record_observation(self, token_id: str, value: str) -> bool:
        persisted: Optional[Extractor] = self.metadata_store.load(token_id)
        if persisted is None:
            return False
        if persisted.last_value is None or persisted.last_value == value:
            persisted.valid_count += 1
        else:
            persisted.ever_changed = True
        persisted.last_value = value
        self.metadata_store.save(persisted)
        return not persisted.ever_changed and persisted.valid_count >= self.STATIC_CONFIRMATION_THRESHOLD
```
- ⚠️ `_record_observation` retorna `False` quando `persisted is None` (token sem
  `.meta.json` — não deveria acontecer em uso normal, já que `replay` só resolve tokens
  cujo `.py` já foi gerado por um `run`/`dry` anterior via `CandidateResolver`/T05, mas
  não trava se acontecer).
- ⚠️ `ever_changed` continua sendo atualizado mesmo depois do threshold já ter sido
  cruzado (contagem não para em 5) — se um token "confirmado estático" mudar de valor
  numa execução futura, `ever_changed` vira `True` e a função para de retornar
  `True` para ele dali em diante (spec seção 5, caso de borda aceito).

Ajuste no único call site (`cli_handlers.py`, `_build_replay_runner`):
```python
metadata_store: ExtractorMetadataStore = ExtractorMetadataStore()
replay_token_resolver: ReplayTokenResolver = ReplayTokenResolver(
    session_store, extractor_runner, dependency_parser, metadata_store
)
```
(import `ExtractorMetadataStore` de `har_reproducer.reproduction`, junto dos demais
imports já existentes desse módulo em `cli_handlers.py`).

**Critérios de aceite:**
- [ ] Primeira resolução válida de um `token_id` com `.meta.json` existente
      (`last_value is None`): `valid_count` vira `1`, `last_value` vira o valor
      resolvido, retorno `False` (ainda longe do threshold).
- [ ] 5 resoluções seguidas com o mesmo valor (mesmo `token_id`, metadado já
      preexistente com `valid_count=4`): a 5ª chamada retorna `True`.
- [ ] Resolução com valor diferente do `last_value` anterior: `ever_changed` vira
      `True`, `valid_count` não incrementa nessa chamada, retorno `False`.
- [ ] Depois de `ever_changed=True`, mesmo com muitas resoluções válidas subsequentes
      (mesmo valor entre elas), a função nunca mais retorna `True` para esse token.
- [ ] `token_id` sem `.meta.json` (`persisted is None`): retorno `False`, nenhuma
      exceção, nenhum arquivo é criado.
- [ ] `resolve(...)` retorna o conjunto de `token_id`s (dentre os presentes no
      `curl_text`) cuja `_resolve_one` retornou `True` nesta chamada — vazio quando
      nenhum cruzou o threshold.
- [ ] Token cujo `extractor_runner.run_existing` retorna `None` (falha de resolução):
      não entra no conjunto retornado, e `_record_observation` não é chamado pra ele.
- [ ] `_build_replay_runner` constrói e passa `ExtractorMetadataStore()` — `replay`
      continua funcionando ponta a ponta sem esse argumento faltando.

---

## T07 — `ReplayRunner`: aviso de token estático no curl
**Depende de:** T06 (`resolve()` retornando `Set[str]`)
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py` (`ReplayRunner`)

**Contexto:**
Última peça: quando `replay_token_resolver.resolve(...)` reporta um `token_id` como
provável estático, editar a linha de comentário de origem já existente no
`req_XXXX.curl.sh` daquele step, acrescentando um sufixo — idempotente, sem inserir
linha nova (spec seção 3.8).

**Estado atual:**
```python
def _run_step(self, index: int, schedule: Set[int]) -> StepResponse:
    curl_text: str = Workspace.curl_file(index).read_text(encoding="utf-8")

    def attempt() -> StepResponse:
        self.replay_token_resolver.resolve(curl_text, schedule, self.replay_run_dir, self.res_refer_dir)
        curl_resolved: str = self.session_store.render(curl_text)
        return self.http_transport.send_request(curl_resolved, index)

    def recover(response: StepResponse) -> bool:
        if response.status_code not in StepRetryPolicy.RECOVERABLE_STATUS_CODES:
            return False
        print(f"Detected {response.status_code}. Attempting deterministic recovery (token refresh)...")
        return True

    response: StepResponse = self.retry_policy.execute(index, attempt, recover)
    Workspace.replay_response_file(self.run_id, index).write_text(
        response.model_dump_json(indent=2), encoding="utf-8"
    )
    print(f"Step {index} completed with status {response.status_code}")
    return response
```

**Estado esperado depois:**
```python
class ReplayRunner:
    STEP_FILENAME_PATTERN: ClassVar[Pattern[str]] = re.compile(r"req_(\d+)\.curl\.sh")
    STATIC_WARNING_SUFFIX: ClassVar[str] = " - probably static"

    ...

    def _run_step(self, index: int, schedule: Set[int]) -> StepResponse:
        curl_text: str = Workspace.curl_file(index).read_text(encoding="utf-8")

        def attempt() -> StepResponse:
            static_token_ids: Set[str] = self.replay_token_resolver.resolve(
                curl_text, schedule, self.replay_run_dir, self.res_refer_dir
            )
            if static_token_ids:
                self._annotate_static_tokens(index, static_token_ids)
            curl_resolved: str = self.session_store.render(curl_text)
            return self.http_transport.send_request(curl_resolved, index)

        def recover(response: StepResponse) -> bool:
            if response.status_code not in StepRetryPolicy.RECOVERABLE_STATUS_CODES:
                return False
            print(f"Detected {response.status_code}. Attempting deterministic recovery (token refresh)...")
            return True

        response: StepResponse = self.retry_policy.execute(index, attempt, recover)
        Workspace.replay_response_file(self.run_id, index).write_text(
            response.model_dump_json(indent=2), encoding="utf-8"
        )
        print(f"Step {index} completed with status {response.status_code}")
        return response

    def _annotate_static_tokens(self, index: int, token_ids: Set[str]) -> None:
        curl_file: Path = Workspace.curl_file(index)
        text: str = curl_file.read_text(encoding="utf-8")
        updated: str = text
        for token_id in token_ids:
            updated = self._mark_token_static(updated, token_id)
        if updated != text:
            curl_file.write_text(updated, encoding="utf-8")

    @classmethod
    def _mark_token_static(cls, text: str, token_id: str) -> str:
        prefix: str = f"# Token {token_id} comes from response of step "
        lines: List[str] = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith(prefix) and not line.endswith(cls.STATIC_WARNING_SUFFIX):
                lines[i] = line + cls.STATIC_WARNING_SUFFIX
                break
        return "\n".join(lines) + "\n"
```
- ⚠️ `curl_text` lido no início de `_run_step` **não é atualizado** com a anotação —
  a anotação só afeta o arquivo em disco, pra leituras futuras (próximo `replay`); a
  execução atual usa o `curl_text` em memória, sem a anotação, o que é irrelevante
  (comentários não afetam `session_store.render`/o corpo do curl enviado).
- ⚠️ `_mark_token_static` sempre retorna texto terminado em `\n` —
  `ExtractorTemplate.render_bash_script` já garante que todo `req_XXXX.curl.sh` gerado
  hoje termina em `\n`, então não há mudança de comportamento observável aqui.
- ⚠️ `attempt()` pode rodar mais de uma vez por step (retry via `StepRetryPolicy`) — a
  anotação é idempotente (`not line.endswith(suffix)` antes de escrever), então
  reexecuções não duplicam o sufixo nem regravam o arquivo à toa quando já anotado.

**Critérios de aceite:**
- [ ] `resolve(...)` retornando conjunto vazio: `Workspace.curl_file(index)` não é
      reescrito (sem I/O de escrita desnecessário).
- [ ] `resolve(...)` retornando `{token_id}` presente no curl: a linha
      `# Token {token_id} comes from response of step {n}` passa a terminar com
      `- probably static`, resto do arquivo inalterado.
- [ ] Chamar `_annotate_static_tokens` duas vezes seguidas com o mesmo `token_id`: o
      arquivo não é reescrito na segunda vez (conteúdo idêntico ao já anotado) e a
      linha não fica com o sufixo duplicado.
- [ ] `token_ids` com múltiplos tokens: cada linha correspondente é anotada
      independentemente, sem afetar as demais.
- [ ] `token_id` que não tem linha de comentário correspondente no arquivo (caso não
      deveria ocorrer em uso normal, mas não pode lançar): `_mark_token_static` retorna
      o texto inalterado.
- [ ] Execução ponta a ponta de `replay --mode all` sobre um workspace com um token já
      com `valid_count=4` em disco: depois da execução, `valid_count=5` e o curl
      correspondente aparece anotado.

---

## T08 — `CliParser`: `--no-reset` vira `--reset` (default invertido)
**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/cli/cli_parser.py`

**Contexto:**
Último passo pra tornar o reaproveitamento (T05) o comportamento padrão: hoje `run`/
`parse` apagam e recriam `output_dir` por default (`--no-reset` pra preservar) — isso
apagaria `extractors/` (e os `.meta.json` novos) antes de cada invocação, a menos que o
usuário lembrasse de passar `--no-reset` toda vez. Inverte pra: preserva por default,
`--reset` apaga explicitamente (spec seção 3.9). `CliHandlers.handle_run`/
`handle_parse` **não mudam** — já leem `args.reset_output_dir` condicionalmente,
independente do nome/default da flag que popula esse valor.

**Estado atual:**
```python
def _build_parse_subparser(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parse_parser: ArgumentParser = subparsers.add_parser("parse")
    parse_parser.add_argument("--har", required=True, help="Path to HAR file")
    parse_parser.add_argument("--output", default=None, help="Output directory (default: <har-dir>/output)")
    parse_parser.add_argument(
        "--no-reset",
        dest="reset_output_dir",
        action="store_false",
        default=True,
        help="Não apagar/recriar o diretório de saída antes de rodar (default: apaga e recria)",
    )
    parse_parser.set_defaults(func=self._handlers.handle_parse)

def _build_run_subparser(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
    run_parser: ArgumentParser = subparsers.add_parser("run")
    run_parser.add_argument("--har", required=True, help="Path to HAR file")
    run_parser.add_argument("--output", default=None, help="Output directory (default: <har-dir>/output)")
    run_parser.add_argument("--mode", choices=[mode.value for mode in EngineMode], default=EngineMode.MAIN.value, help="Engine execution mode")
    run_parser.add_argument("--config", help="Path to project config (JSON)")
    run_parser.add_argument(
        "--no-reset",
        dest="reset_output_dir",
        action="store_false",
        default=True,
        help="Não apagar/recriar o diretório de saída antes de rodar (default: apaga e recria)",
    )
    run_parser.set_defaults(func=self._handlers.handle_run)
```

**Estado esperado depois:**
```python
def _build_parse_subparser(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
    parse_parser: ArgumentParser = subparsers.add_parser("parse")
    parse_parser.add_argument("--har", required=True, help="Path to HAR file")
    parse_parser.add_argument("--output", default=None, help="Output directory (default: <har-dir>/output)")
    parse_parser.add_argument(
        "--reset",
        dest="reset_output_dir",
        action="store_true",
        default=False,
        help="Apagar/recriar o diretório de saída antes de rodar (default: preservar)",
    )
    parse_parser.set_defaults(func=self._handlers.handle_parse)

def _build_run_subparser(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
    run_parser: ArgumentParser = subparsers.add_parser("run")
    run_parser.add_argument("--har", required=True, help="Path to HAR file")
    run_parser.add_argument("--output", default=None, help="Output directory (default: <har-dir>/output)")
    run_parser.add_argument("--mode", choices=[mode.value for mode in EngineMode], default=EngineMode.MAIN.value, help="Engine execution mode")
    run_parser.add_argument("--config", help="Path to project config (JSON)")
    run_parser.add_argument(
        "--reset",
        dest="reset_output_dir",
        action="store_true",
        default=False,
        help="Apagar/recriar o diretório de saída antes de rodar (default: preservar)",
    )
    run_parser.set_defaults(func=self._handlers.handle_run)
```
- ⚠️ `dest="reset_output_dir"` mantido idêntico — é o nome que `CliHandlers` já
  consome; só a flag CLI (`--no-reset` → `--reset`), a `action` (`store_false` →
  `store_true`) e o `default` (`True` → `False`) invertem.
- ⚠️ Esta task não mexe no subparser `replay` (nunca teve essa flag).

**Critérios de aceite:**
- [ ] `run --har x.har` (sem `--reset`): `output_dir` **preservado** (comportamento
      novo, oposto do atual).
- [ ] `run --har x.har --reset`: `output_dir` apagado e recriado.
- [ ] Mesmo comportamento pra `parse`.
- [ ] `args.reset_output_dir` é `False` por default quando nenhuma flag é passada.
- [ ] `--no-reset` deixa de ser uma flag reconhecida (erro de `argparse` se passada).
- [ ] Nenhuma outra parte de `_build_run_subparser`/`_build_parse_subparser` muda
      (`--har`, `--output`, `--mode`, `--config` intactos).
- [ ] `CliHandlers.handle_run`/`handle_parse` continuam funcionando sem nenhuma
      alteração de código.
