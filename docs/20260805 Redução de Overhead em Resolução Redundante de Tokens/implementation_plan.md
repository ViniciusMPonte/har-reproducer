# Plano de Implementação — Redução de Overhead em Resolução Redundante de Tokens

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `Engine._process_entry`: condicionar `resolve_all()` a `USES_NETWORK`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/engines/engine.py` (`Engine._process_entry`)

**Contexto:**
`_process_entry` é o método chamado uma vez por step do HAR, para os dois engines
(`Engine` e `DryEngine`, que não o sobrescreve). Hoje ele chama
`self.token_resolver.resolve_all()` incondicionalmente, mesmo em `DryEngine`, onde
nenhuma requisição é enviada e nenhum arquivo de response é reescrito depois de criado
— então o resultado de qualquer extractor já resolvido não pode mudar dentro da run, e
a chamada é puro trabalho redundante que cresce com o tamanho do registry de tokens a
cada step (spec seção 1, Ponto 1).

**Estado atual:**
```python
def _process_entry(
        self,
        index: int,
        entry: Dict[str, Any],
        first_entry: Step,
) -> StepResponse:
    step: Step = HARParser.parse_entry(entry, index)
    self._persist_request_step(index, step.request)
    self._persist_original_response_step(index, step.response)

    step.analysis = self.tracker.analyze_step(step, first_entry)
    self.token_resolver.resolve_all()

    response: StepResponse = self.execute_step(step)
    self._persist_response_step(index, response)
    print(f"Step {index} completed with status {response.status_code}")

    if response.status_code != 0:
        self._persist_template_curl(index, step.analysis.curl_template)

    return response
```
- `self.token_resolver.resolve_all()` roda sempre, para `Engine` (`USES_NETWORK = True`)
  e `DryEngine` (`USES_NETWORK = False`, `engines/dry_engine.py:8`).
- `Engine.handle_recovery` (`engine.py:132-141`) também chama `resolve_all()`, mas só é
  acionado via `StepRetryPolicy`/`execute_step` em recuperação de 400/401 — caminho que
  `DryEngine.execute_step` nunca invoca (retorna `step.response` direto,
  `dry_engine.py:10-12`).

**Estado esperado depois:**
- A chamada de `resolve_all()` dentro de `_process_entry` passa a ser:
  ```python
  step.analysis = self.tracker.analyze_step(step, first_entry)
  if self.USES_NETWORK:
      self.token_resolver.resolve_all()
  ```
- Nenhuma outra linha de `_process_entry` muda.
- `handle_recovery` não é tocado — continua chamando `resolve_all()` incondicionalmente
  quando aciona uma recuperação.
- ⚠️ Não trocar `if self.USES_NETWORK:` por checar o tipo do engine (`isinstance`) nem
  por uma flag nova — `USES_NETWORK` já é o `ClassVar` usado para essa mesma distinção
  em `_build_http_transport` (`engine.py:57-63`); reaproveitar o hook existente.
- ⚠️ Não alterar `DryEngine.USES_NETWORK` nem `Engine.USES_NETWORK` — os valores atuais
  (`False`/`True`, respectivamente) já são exatamente os desejados para este gate.

**Critérios de aceite:**
- [ ] Rodando `run --mode dry`, `token_resolver.resolve_all()` nunca é chamado dentro de
  `_process_entry` (verificável por instrumentação/print temporário durante o teste
  manual, ou por leitura do código — `self.USES_NETWORK` é `False` em `DryEngine`).
- [ ] Rodando `run --mode main`, `token_resolver.resolve_all()` continua sendo chamado
  exatamente uma vez por step dentro de `_process_entry`, na mesma posição do fluxo
  (depois de `analyze_step`, antes de `execute_step`) — comportamento idêntico ao atual,
  sem regressão.
- [ ] `handle_recovery` continua chamando `resolve_all()` normalmente em qualquer modo,
  sem nenhuma mudança de condição.
- [ ] `python -m py_compile har_reproducer/engines/engine.py` sem erros.

---

## [T02] — `CandidateResolver`: cache de origem por valor, evitando regrep

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (`CandidateResolver.__init__`, `CandidateResolver._process_candidate`)

**Contexto:**
`BaselineDiff.compare` (`tracking/baseline_diff.py:9-15`) compara cada step contra o
**primeiro** entry do HAR, não contra o step anterior — então um header/cookie que
mudou uma vez (ex.: cookie de sessão após login) e permanece igual dali em diante
continua aparecendo como "diff" em todo step seguinte, virando um novo `candidate` toda
vez com o mesmo `current_value`. `_process_candidate` chama `ResponseGrep.find` (até 4
subprocessos `grep` por candidato, um por variante do valor — `response_grep.py:37-45`)
como primeiro passo, sem nenhum cache — o cache existente (`_validated_values`) só é
consultado depois, dentro de `_check_slot`, quando o `origin_step` já foi determinado
(spec seção 1, Ponto 2, e seção 2).

**Estado atual:**
```python
def __init__(
        self,
        responses_dir: Path,
        session_store: SessionStore,
        llm: Optional[BaseChatModel],
) -> None:
    self.responses_dir: Path = responses_dir
    self.session_store: SessionStore = session_store
    self.llm: Optional[BaseChatModel] = llm
    self.extractor_runner: ExtractorRunner = ExtractorRunner()
    self.metadata_store: ExtractorMetadataStore = ExtractorMetadataStore()
    self._validated_values: Dict[str, str] = {}

def resolve(self, candidates: List[DynamicToken]) -> List[DynamicToken]:
    return [self._process_candidate(candidate) for candidate in candidates]

def _process_candidate(self, candidate: DynamicToken) -> DynamicToken:
    origin: Optional[Tuple[int, str]] = ResponseGrep.find(
        self.responses_dir, candidate.current_value
    )
    if not origin:
        candidate.status = "NotFound"
        return candidate

    candidate.origin_step = origin[0]
    ...
```
- Toda chamada a `_process_candidate` refaz a varredura completa de `responses_dir` via
  `ResponseGrep.find`, mesmo quando `candidate.current_value` já foi visto (e resolvido)
  em um step anterior da mesma run.
- `responses_dir` é append-only dentro de uma run de `run`/`dry` (spec seção 2 — cada
  índice de response é escrito exatamente uma vez, nunca reescrito para um índice
  anterior) — condição que torna seguro cachear o resultado de `ResponseGrep.find` por
  valor, pelo tempo de vida do `CandidateResolver` (um por `Engine`/run).

**Estado esperado depois:**
- Novo atributo em `__init__`, ao lado de `self._validated_values`:
  ```python
  self._origin_cache: Dict[str, Optional[Tuple[int, str]]] = {}
  ```
- Novo método privado, único ponto que chama `ResponseGrep.find`:
  ```python
  def _find_origin(self, value: str) -> Optional[Tuple[int, str]]:
      if value in self._origin_cache:
          return self._origin_cache[value]
      origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, value)
      self._origin_cache[value] = origin
      return origin
  ```
- `_process_candidate` passa a chamar `self._find_origin(candidate.current_value)` em
  vez de `ResponseGrep.find(self.responses_dir, candidate.current_value)` diretamente —
  única linha alterada nesse método, nenhuma outra lógica de `_process_candidate` muda.
- ⚠️ O cache é por **valor** (`candidate.current_value`), não por `path`/candidato —
  preserva a semântica atual porque `ResponseGrep.find` já ignora `path` na assinatura
  de hoje. Não adicionar `path` como parte da chave do cache.
- ⚠️ Cachear também o resultado `None` (valor não encontrado) é intencional — não tratar
  `None` como "ainda não cacheado" (não usar `.get(value)` sem checar `in` primeiro, ou
  o cache nunca vai de fato evitar regrep para valores não encontrados).

**Critérios de aceite:**
- [ ] Duas chamadas a `_process_candidate` com candidatos de `current_value` idêntico
  (mesmo que `path` diferente) resultam em uma única chamada real a
  `ResponseGrep.find`/`grep` (verificável isolando `ResponseGrep.find` com um mock/spy em
  teste manual, ou por leitura do fluxo).
- [ ] Um valor que não é encontrado por `ResponseGrep.find` (`origin is None`) é
  cacheado como `None` e a segunda consulta com o mesmo valor não dispara novo `grep`.
- [ ] `candidate.status` resultante ("NotFound", "Resolved", "UnderReview",
  "Unresolved") para qualquer candidato é idêntico ao que seria produzido sem o cache
  (nenhuma mudança de resultado, só de quantidade de trabalho repetido) — não-regressão
  do fluxo de resolução completo (`resolve()` → `_process_candidate` →
  `_find_slot`/`_check_slot`).
- [ ] `python -m py_compile har_reproducer/tracking/candidate_resolver.py` sem erros.
