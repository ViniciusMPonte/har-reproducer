# Plano de Implementação — Origem Futura de Token Dinâmico

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## T01 — `ResponseGrep`: busca de origem restrita a responses anteriores ao step atual

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/response_grep.py` (`ResponseGrep.find`, `ResponseGrep._grep_single_pattern`, novo `ResponseGrep._eligible_response_files`)

**Contexto:**
`ResponseGrep.find` decide de qual response um valor de token "vem" rodando
`grep -rlF` sobre **todo** o diretório de responses, sem nenhuma noção de qual
step está sendo analisado. Isso permite que um candidato do step 12 receba como
origem uma response do step 75 — impossível de satisfazer numa reprodução
sequencial, seja porque o diretório de output é reaproveitado entre execuções
(`Workspace.init` não limpa nada), seja por qualquer response futura já
presente em disco no momento da análise (spec seção 1, bug reproduzido com o
header `Origin` do browser: `origin_step=75` referenciado desde o step 12).

**Estado atual:**
```python
@classmethod
def find(cls, responses_dir: Path, pattern: str) -> Optional[Tuple[int, str]]:
    for variant in cls.value_variants(pattern):
        match: Optional[Tuple[int, str]] = cls._grep_single_pattern(responses_dir, variant)
        if match is not None:
            return match
    return None

@classmethod
def _grep_single_pattern(cls, responses_dir: Path, pattern: str) -> Optional[Tuple[int, str]]:
    try:
        cmd: List[str] = ["grep", "-rlF", "--include=res_*.json", pattern, str(responses_dir)]
        result: CompletedProcess[str] = subprocess.run(cmd, capture_output=True, text=True, check=True)

        if not result.stdout:
            return None

        first_match_file: str = sorted(result.stdout.splitlines())[0]
        filename: str = Path(first_match_file).name

        step_index: Optional[int] = cls._extract_step_index(filename)
        if step_index is None:
            return None

        return step_index, filename

    except subprocess.CalledProcessError as e:
        if e.returncode == 1:
            return None
        raise
```
`_extract_step_index` (já existente, inalterado) extrai o índice numérico de
`res_NNNN.json`. `first_match_file: str = sorted(result.stdout.splitlines())[0]`
é o que garante "primeira ocorrência" hoje — o `grep -r` retorna os arquivos na
ordem de travessia do filesystem (arbitrária), e é esse `sorted()` que reordena
e pega o menor índice (funciona porque os nomes são zero-padded).

**Estado esperado depois:**
```python
@classmethod
def find(cls, responses_dir: Path, pattern: str, before_step_index: int) -> Optional[Tuple[int, str]]:
    candidate_files: List[Path] = cls._eligible_response_files(responses_dir, before_step_index)
    if not candidate_files:
        return None

    for variant in cls.value_variants(pattern):
        match: Optional[Tuple[int, str]] = cls._grep_single_pattern(candidate_files, variant)
        if match is not None:
            return match
    return None

@classmethod
def _grep_single_pattern(cls, candidate_files: List[Path], pattern: str) -> Optional[Tuple[int, str]]:
    try:
        cmd: List[str] = ["grep", "-lF", pattern, *(str(path) for path in candidate_files)]
        result: CompletedProcess[str] = subprocess.run(cmd, capture_output=True, text=True, check=True)

        if not result.stdout:
            return None

        first_match_file: str = sorted(result.stdout.splitlines())[0]
        filename: str = Path(first_match_file).name

        step_index: Optional[int] = cls._extract_step_index(filename)
        if step_index is None:
            return None

        return step_index, filename

    except subprocess.CalledProcessError as e:
        if e.returncode == 1:
            return None
        raise

@classmethod
def _eligible_response_files(cls, responses_dir: Path, before_step_index: int) -> List[Path]:
    eligible: List[Path] = []
    for path in sorted(responses_dir.glob("res_*.json")):
        step_index: Optional[int] = cls._extract_step_index(path.name)
        if step_index is not None and step_index < before_step_index:
            eligible.append(path)
    return eligible
```
- `before_step_index` é o índice do step cujo request está sendo montado;
  `origin_step` só pode vir de um step **estritamente anterior** (`<`, nunca
  `<=`) — a própria response do step atual ainda não existe no momento em que
  seu request está sendo construído.
- `_eligible_response_files` é calculado **uma vez por chamada de `find()`**,
  reaproveitado pelas 4 tentativas de `value_variants` — não recalcular por
  variante.
- ⚠️ `-r`/`--include=res_*.json` do `grep` saem: a lista de arquivos já vem
  pronta e filtrada, então o comando passa a listar os arquivos explicitamente
  (`grep -lF pattern arquivo1 arquivo2 ...`).
- ⚠️ Isso blinda inclusive contra um `res_{before_step_index:04d}.json` já
  existir em disco (sobra de execução anterior no mesmo diretório de output) —
  esse arquivo nunca entra na lista de elegíveis, porque a regra é sobre
  causalidade, não sobre "o arquivo existe".
- `value_variants`, `try_decode`, `_deduplicate`, `_extract_step_index` não
  mudam.

**Critérios de aceite:**
- [ ] Com um `responses_dir` de teste contendo `res_0000.json`...`res_0011.json`
  (sem o valor) e `res_0075.json` (contendo `"http://127.0.0.1:8080"`),
  `ResponseGrep.find(dir, "http://127.0.0.1:8080", 12)` retorna `None` —
  reproduz e corrige exatamente o bug da spec.
- [ ] No mesmo diretório, `ResponseGrep.find(dir, "http://127.0.0.1:8080", 80)`
  retorna `(75, "res_0075.json")` — a mesma origem passa a ser encontrada
  quando o step que pergunta é posterior a ela (não regressão do caso
  legítimo de referência para trás).
- [ ] `ResponseGrep._eligible_response_files(dir, 12)` retorna exatamente os
  paths de `res_0000.json` a `res_0011.json` (12 arquivos), sem
  `res_0075.json`.
- [ ] `ResponseGrep._eligible_response_files(dir, 0)` retorna lista vazia, e
  `ResponseGrep.find(dir, "qualquer coisa", 0)` retorna `None` sem lançar
  exceção (nenhum arquivo elegível, nenhuma chamada a `grep`).
- [ ] Não regressão: `ResponseGrep.find(dir, "valor_ausente", 238)` continua
  retornando `None` quando o valor não existe em nenhum arquivo (mesmo
  comportamento de "não achei nada" de antes, incluindo o tratamento de
  `CalledProcessError` com `returncode == 1`).
- [ ] Não regressão: `ResponseGrep.value_variants("abc")` e
  `ResponseGrep.try_decode(...)` continuam com o mesmo comportamento/retorno
  de antes desta task.

## T02 — `CandidateResolver`: propaga o step atual até a busca de origem

**Depende de:** T01 (usa a nova assinatura de `ResponseGrep.find`).
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (`CandidateResolver.resolve`, `CandidateResolver._process_candidate`, `CandidateResolver._find_origin`, `CandidateResolver.__init__`)

**Contexto:**
`CandidateResolver.resolve`/`_process_candidate`/`_find_origin` não sabem em
qual step o candidato que estão processando foi detectado, então não têm como
restringir a busca de origem a responses anteriores a ele. Precisam repassar
esse índice até `ResponseGrep.find` (T01). A cache de origem por processo
(`_origin_cache`) também precisa mudar de chave, porque o resultado passa a
depender do step, não só do valor.

**Estado atual:**
```python
def __init__(self, responses_dir, session_store, llm) -> None:
    ...
    self._origin_cache: Dict[str, Optional[Tuple[int, str]]] = {}

def resolve(self, candidates: List[DynamicToken]) -> List[DynamicToken]:
    return [self._process_candidate(candidate) for candidate in candidates]

def _process_candidate(self, candidate: DynamicToken) -> DynamicToken:
    origin: Optional[Tuple[int, str]] = self._find_origin(candidate.current_value)
    if not origin:
        candidate.status = "NotFound"
        return candidate

    candidate.origin_step = origin[0]
    base_token_id: str = self._derive_token_id(candidate.path, candidate.origin_step)

    slot_id: str
    initial_error: Optional[str]
    slot_id, initial_error = self._find_slot(base_token_id, candidate)
    candidate.token_id = slot_id

    if self.session_store.state.registry.get(slot_id) is not None:
        candidate.status = "Resolved"
        return candidate

    return self._generate_new_extractor(candidate, initial_error)

def _find_origin(self, value: str) -> Optional[Tuple[int, str]]:
    if value in self._origin_cache:
        return self._origin_cache[value]
    origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, value)
    self._origin_cache[value] = origin
    return origin
```

**Estado esperado depois:**
```python
def __init__(self, responses_dir, session_store, llm) -> None:
    ...
    self._origin_cache: Dict[Tuple[str, int], Optional[Tuple[int, str]]] = {}

def resolve(self, candidates: List[DynamicToken], step_index: int) -> List[DynamicToken]:
    return [self._process_candidate(candidate, step_index) for candidate in candidates]

def _process_candidate(self, candidate: DynamicToken, step_index: int) -> DynamicToken:
    origin: Optional[Tuple[int, str]] = self._find_origin(candidate.current_value, step_index)
    if not origin:
        candidate.status = "NotFound"
        return candidate

    candidate.origin_step = origin[0]
    base_token_id: str = self._derive_token_id(candidate.path, candidate.origin_step)

    slot_id: str
    initial_error: Optional[str]
    slot_id, initial_error = self._find_slot(base_token_id, candidate)
    candidate.token_id = slot_id

    if self.session_store.state.registry.get(slot_id) is not None:
        candidate.status = "Resolved"
        return candidate

    return self._generate_new_extractor(candidate, initial_error)

def _find_origin(self, value: str, step_index: int) -> Optional[Tuple[int, str]]:
    cache_key: Tuple[str, int] = (value, step_index)
    if cache_key in self._origin_cache:
        return self._origin_cache[cache_key]
    origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, value, step_index)
    self._origin_cache[cache_key] = origin
    return origin
```
- ⚠️ A chave da cache muda de `value` para `(value, step_index)` — chave só
  por `value` deixaria um "não encontrado" cacheado num step cedo vazar
  incorretamente para um step mais tarde, onde a mesma busca já deveria achar
  uma origem legítima (spec decisão 3.2).
- Nenhuma outra lógica do método muda: derivação de `token_id`
  (`_derive_token_id`), `_find_slot`, `_check_slot`/`_check_cached_slot`/
  `_check_persisted_slot`, geração de extractor (`_generate_new_extractor`,
  `_generate_extractor`) — tudo isso continua exatamente igual, só passa a
  operar sobre um `origin_step` já garantidamente causal.

**Critérios de aceite:**
- [ ] `CandidateResolver.resolve([candidate], step_index=12)` para um
  candidato cujo `current_value` só existe em `res_0075.json` retorna o
  candidato com `status == "NotFound"` e `origin_step is None` — nenhum
  extractor é gerado nem registrado em `session_store.state.registry`.
- [ ] `CandidateResolver.resolve([candidate], step_index=80)` para o mesmo
  valor (mesmo `responses_dir` de teste) segue o fluxo normal de resolução
  (`origin_step == 75`, `status` avança para `"UnderReview"`/`"Resolved"` via
  `_generate_new_extractor`) — não regressão do caso de referência legítima
  para trás.
- [ ] Chamar `_find_origin("valor", 12)` (retorna `None`, valor só existe no
  step 20) e depois `_find_origin("valor", 30)` no mesmo `CandidateResolver`
  retorna `(20, "res_0020.json")` na segunda chamada — comprova que a cache
  por `(value, step_index)` não reaproveita incorretamente o resultado
  negativo do step 12 para o step 30.
- [ ] Não regressão: um candidato cujo `origin_step` já era menor que o step
  atual antes desta task (caso comum, ex.: token de sessão extraído do login)
  continua percorrendo `_find_slot`/`_check_persisted_slot` normalmente e
  reaproveitando um extractor já persistido em disco quando o valor bate.

## T03 — `TokenTracker.analyze_step`: repassa o índice do step atual

**Depende de:** T02 (usa a nova assinatura de `CandidateResolver.resolve`).
**Arquivos envolvidos:** `har_reproducer/tracking/token_tracker.py` (`TokenTracker.analyze_step`)

**Contexto:**
Último elo da cadeia: `analyze_step` já recebe `step.index` (usado para
`StepAnalysis.step_index`, duas linhas abaixo), só falta repassar esse mesmo
valor para `candidate_resolver.resolve`.

**Estado atual:**
```python
def analyze_step(self, step: Step, baseline_step: Step) -> StepAnalysis:
    diffs: Dict[str, str] = self.baseline_diff.compare(step, baseline_step)
    candidates: List[DynamicToken] = self.baseline_diff.detect_candidates(diffs)
    tokens: List[DynamicToken] = self.candidate_resolver.resolve(candidates)
    self.placeholder_applier.apply(step.request, tokens)
    template: str = CurlGenerator().generate(step.request, tokens)
    static_values: Dict[str, str] = self.baseline_diff.extract_static_values(step, baseline_step)

    return StepAnalysis(
        step_index=step.index,
        static_values=static_values,
        dynamic_tokens=tokens,
        curl_template=template,
    )
```

**Estado esperado depois:**
```python
def analyze_step(self, step: Step, baseline_step: Step) -> StepAnalysis:
    diffs: Dict[str, str] = self.baseline_diff.compare(step, baseline_step)
    candidates: List[DynamicToken] = self.baseline_diff.detect_candidates(diffs)
    tokens: List[DynamicToken] = self.candidate_resolver.resolve(candidates, step.index)
    self.placeholder_applier.apply(step.request, tokens)
    template: str = CurlGenerator().generate(step.request, tokens)
    static_values: Dict[str, str] = self.baseline_diff.extract_static_values(step, baseline_step)

    return StepAnalysis(
        step_index=step.index,
        static_values=static_values,
        dynamic_tokens=tokens,
        curl_template=template,
    )
```
- ⚠️ Única mudança: o argumento novo em `self.candidate_resolver.resolve(...)`.
  Nada mais neste método muda.

**Critérios de aceite:**
- [ ] `TokenTracker.analyze_step` chama `self.candidate_resolver.resolve` com
  dois argumentos posicionais, o segundo sendo `step.index`.
- [ ] Não regressão: `StepAnalysis.step_index`, `static_values` e
  `curl_template` continuam calculados exatamente como antes desta task.
- [ ] **Verificação fim a fim do bug original:** rodar
  `uv run python -m har_reproducer.main run --har <har original> --output <dir novo> --mode dry`
  contra o HAR que reproduziu o bug da spec (238 steps, header `Origin` do
  browser ecoado pela primeira vez numa response só no step 75) e confirmar:
  - nenhum arquivo `extractors/extract_*.meta.json` é gerado com
    `agent_type` de header/regex para o valor `http://127.0.0.1:8080` nos
    steps anteriores ao 75;
  - os curls gerados para os steps 12–74 que antes referenciavam
    `{{extractor:5809b41abdae40b7eb763e1eaf00f038}}` passam a conter o valor
    literal `http://127.0.0.1:8080` diretamente na URL/headers, sem
    placeholder.
