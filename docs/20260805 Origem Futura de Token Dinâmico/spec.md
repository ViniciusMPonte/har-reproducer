# Spec — Origem Futura de Token Dinâmico

## 1. Objetivo

Hoje, quando o `CandidateResolver` decide de qual step um token dinâmico "vem"
(`origin_step`), ele busca o valor em **todas** as responses presentes em
`responses_dir` — sem nenhuma restrição de que a response de origem precisa
pertencer a um step anterior ao step que está sendo analisado no momento. Isso
permite que um candidato do step 12 receba `origin_step=75`: um extractor gerado
para ler a resposta de um step que, do ponto de vista de uma reprodução
sequencial (seja o próprio `run`/`reproduce` numa reexecução, seja o `replay`),
**ainda não aconteceu** quando o step 12 precisa daquele valor.

Isso foi reproduzido rodando `uv run python -m har_reproducer.main replay
--mode all` contra um HAR real (`arquivos-har/output`, 238 steps). O log mostra
falhas encadeadas a partir do step 11/12:

```
Failed to resolve token '5809b41abdae40b7eb763e1eaf00f038' during replay: extractor returned no value.
Network error while executing step 12 message: curl: (3) nested brace in URL position 2:
{{extractor:5809b41abdae40b7eb763e1eaf00f038}}/src/app.js
```

Inspecionando `arquivos-har/output/extractors/extract_5809b41abdae40b7eb763e1eaf00f038.meta.json`,
o extractor tem `origin_step: 75` mas é referenciado em `curls/req_0012.curl.sh`
(e em outros ~20 steps entre 12 e 74). O valor (`http://127.0.0.1:8080`, o
próprio header `Origin` do browser) é confirmadamente ausente de toda response
antes do step 75 (`grep -rlF "http://127.0.0.1:8080" original_responses/` só
retorna `res_0075.json` em diante) — ou seja, o `origin_step=75` não é um
resultado "quase certo, só um pouco impreciso": é estruturalmente impossível de
satisfazer para os ~20 steps que o referenciam antes do step 75 existir.

A causa raiz é dupla e concentrada em `CandidateResolver._find_origin` →
`ResponseGrep.find`: (1) a função não recebe nem usa o índice do step que está
sendo analisado, e (2) a varredura roda sobre o diretório de responses inteiro,
que pode conter arquivos de steps futuros — seja porque o diretório de output é
reaproveitado entre execuções (`Workspace.init` nunca limpa os diretórios,
`har_reproducer/fs_io/workspace.py:20-26`), seja por qualquer outro cenário em
que uma response de step futuro já exista em disco no momento da análise.

**O que essa mudança cobre:**
- `ResponseGrep.find` passa a receber o índice do step sendo analisado e só
  considera como origem responses de steps estritamente anteriores a ele.
- `CandidateResolver` propaga esse índice desde `TokenTracker.analyze_step`
  (que já o recebe via `step.index`) até a chamada de `ResponseGrep.find`.
- Um valor cuja única ocorrência em disco está numa response de step igual ou
  posterior ao step analisado passa a ser tratado como origem **não
  encontrada** (`NotFound`) — o mesmo status já usado hoje para "grep não achou
  em lugar nenhum" — em vez de gerar um extractor com dependência impossível de
  satisfazer.

**Fora de escopo (não implementar agora):**
- **`ReplayTokenResolver._resolve_one`** (`har_reproducer/replay/replay_token_resolver.py:41-60`) —
  hoje decide de qual diretório ler a response de um token comparando
  `origin_step` com o `schedule` inteiro da run (`origin_step in schedule`), o
  que em `--mode all` é sempre verdadeiro mesmo que aquele step ainda não tenha
  rodado nesta execução. Essa é uma segunda camada de defesa (útil mesmo com
  `origin_step` sempre causal, ex.: se o step de origem falhar por motivo
  alheio ao token) e fica para uma spec separada.
- **Reprocessar o HAR já capturado em `arquivos-har/output`.** Esta spec corrige
  o `CandidateResolver`, usado na fase de construção (`run`/`reproduce`), não o
  `replay`. Os curls e metadados de extractor já gerados nesse diretório foram
  produzidos com o bug presente e não são reescritos retroativamente — validar
  a correção requer rodar `run`/`reproduce` de novo a partir do `.har` original
  (idealmente com `--reset-output-dir`, ver seção 5).
- **`BaselineDiff._diff_headers` sempre comparar contra um baseline fixo**
  (`baseline_diff.py:24-29`, já documentado como fora de escopo em
  `docs/20260803 Origem de Token Não Determinada/spec.md`) — é o que faz um
  header de sessão constante do browser (`Origin`, no caso do bug reproduzido)
  virar candidato a cada step em que o baseline não o carrega. Essa spec não
  muda essa heurística; o `NotFound` resultante da correção acima já é
  suficiente para não gerar um extractor quebrado a partir dela (ver seção 5).

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `CandidateResolver._process_candidate`/`_find_origin` — `har_reproducer/tracking/candidate_resolver.py:47-75`
```python
def resolve(self, candidates: List[DynamicToken]) -> List[DynamicToken]:
    return [self._process_candidate(candidate) for candidate in candidates]

def _process_candidate(self, candidate: DynamicToken) -> DynamicToken:
    origin: Optional[Tuple[int, str]] = self._find_origin(candidate.current_value)
    if not origin:
        candidate.status = "NotFound"
        return candidate

    candidate.origin_step = origin[0]
    base_token_id: str = self._derive_token_id(candidate.path, candidate.origin_step)
    ...

def _find_origin(self, value: str) -> Optional[Tuple[int, str]]:
    if value in self._origin_cache:
        return self._origin_cache[value]
    origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, value)
    self._origin_cache[value] = origin
    return origin
```
`_origin_cache: Dict[str, Optional[Tuple[int, str]]]` (linha 45) é uma cache de
processo, chaveada só pelo valor — hoje isso é seguro porque o resultado de
`ResponseGrep.find` não depende de mais nada além do valor. A decisão 3.1 muda
isso: o resultado passa a depender também do step sendo analisado, então a
chave da cache precisa mudar junto (decisão 3.2).

`if not origin: candidate.status = "NotFound"` já é o caminho existente para
"não achei de onde isso vem" — é o mesmo status que a decisão 3.1 passa a
produzir também para origens futuras, sem precisar de um `status` novo.

### `TokenTracker.analyze_step` — `har_reproducer/tracking/token_tracker.py:30-41`
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
        ...
    )
```
`step.index` já está disponível neste método (usado duas linhas abaixo para
`StepAnalysis.step_index`) — é só reaproveitar o mesmo valor na chamada a
`self.candidate_resolver.resolve(...)`, sem precisar buscar o índice em nenhum
lugar novo.

### `ResponseGrep.find`/`_grep_single_pattern`/`_extract_step_index` — `har_reproducer/tracking/response_grep.py:11-88`
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

@staticmethod
def _extract_step_index(filename: str) -> Optional[int]:
    try:
        index_str: str = filename.split("_")[1].split(".")[0]
        return int(index_str)
    except (IndexError, ValueError) as e:
        print(f"[AVISO] Falha ao extrair step index do arquivo '{filename}': {e}")
        return None
```
`grep -rlF --include=res_*.json ... responses_dir` varre recursivamente **todo**
o diretório — é aqui que um `res_0075.json` já presente em disco entra na busca
de um candidato do step 12. `_extract_step_index` já sabe extrair o índice
numérico de um nome de arquivo `res_NNNN.json`; a decisão 3.1 reaproveita esse
mesmo método para filtrar a lista de arquivos elegíveis **antes** de rodar o
`grep`, em vez de rodar o `grep` sobre o diretório inteiro e só depois olhar o
índice do único resultado já escolhido (linha 66, `sorted(...)[0]`).

Os diretórios passados como `responses_dir` (`Workspace.real_responses` e
`Workspace.original_responses`) são sempre planos — `Workspace.response_file`/
`original_response_file` (`har_reproducer/fs_io/workspace.py:66-73`) escrevem
direto em `cls.real_responses`/`cls.original_responses`, sem subpastas por
step. A recursão do `-r` no `grep` atual não tem efeito prático nesse layout;
a decisão 3.1 troca a varredura por uma listagem direta desse diretório plano
(`Path.glob("res_*.json")`), sem mudar onde os arquivos são procurados.

⚠️ `first_match_file: str = sorted(result.stdout.splitlines())[0]` (linha 66)
é o que garante "primeira ocorrência" hoje — **não** é uma varredura sequencial
que para no primeiro achado: o `grep -r` retorna os arquivos batidos na ordem
de travessia do filesystem (arbitrária), e é o `sorted()` logo depois que
reordena esses nomes e pega o menor. Isso só funciona porque os nomes são
zero-padded (`res_0000.json`, `res_0001.json`, ...), então ordenar como string
equivale a ordenar numericamente. A decisão 3.1 preserva esse mesmo mecanismo
(mesma linha, mesmo `sorted()[0]`) sobre um conjunto de arquivos menor — não
muda a forma como "primeira ocorrência" é decidida, só reduz de quais arquivos
ela pode vir.

### `PlaceholderApplier._apply_token` — `har_reproducer/tracking/placeholder_applier.py:20-32`
```python
def _apply_token(self, request: StepRequest, token: DynamicToken) -> None:
    if not token.current_value:
        return

    extractor: Optional[Extractor] = self._verified_extractor(token.token_id)
    if extractor is None:
        return
    ...
```
Confirma o comportamento seguro já existente para candidatos que não viram
extractor: sem um `Extractor` verificado registrado para aquele `token_id`,
nada é substituído no request — o curl final mantém o valor literal do HAR.
É esse caminho que os candidatos `NotFound` gerados pela decisão 3.1 já
percorrem hoje (nenhuma mudança necessária aqui): o header `Origin` do
exemplo reproduzido, ao virar `NotFound`, simplesmente permanece com o valor
literal `http://127.0.0.1:8080` no curl gerado — correto, já que é uma
constante de sessão do browser, não algo que precise ser extraído em runtime.

## 3. Decisões de arquitetura

### 3.1 `ResponseGrep.find` passa a receber o step atual e só busca em responses anteriores a ele

**Estado atual:** `find`/`_grep_single_pattern` não recebem nenhuma noção de
"step atual" e rodam o `grep` sobre `responses_dir` inteiro (seção 2).

**Estado esperado:**
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
- `before_step_index` é o índice do step cujo request está sendo montado —
  `origin_step` só pode ser um step **estritamente anterior** (`<`, nunca
  `<=`): a response do próprio step ainda não existe no momento em que o
  request dele está sendo construído, então nunca pode ser origem de um valor
  usado nesse mesmo request.
- ⚠️ Isso também blinda contra o caso de um `res_{before_step_index:04d}.json`
  já existir em disco (sobra de uma execução anterior no mesmo diretório de
  output) — mesmo esse arquivo do "próprio step atual" é excluído, porque a
  regra é sobre causalidade (o que já aconteceu antes deste request), não
  sobre "o arquivo existe ou não".
- `_eligible_response_files` é calculado **uma vez por chamada de `find()`**,
  não uma vez por variante — o recorte de arquivos elegíveis só depende de
  `before_step_index`, não do valor/variante sendo buscado, então recalculá-lo
  a cada uma das 4 variantes de `value_variants` seria trabalho redundante.
  Se não houver nenhum arquivo elegível, `find()` retorna `None` de imediato,
  sem sequer tentar as variantes.
- `-r`/`--include=res_*.json` do `grep` viram desnecessários: a lista de
  arquivos já vem pronta e filtrada de `_eligible_response_files`, então o
  comando de `grep` passa a listar os arquivos explicitamente
  (`grep -lF pattern arquivo1 arquivo2 ...`) em vez de varrer o diretório.
- `subprocess.CalledProcessError` com `returncode == 1` continua significando
  "nenhum arquivo bateu" (comportamento padrão do `grep`) — nenhuma mudança
  nesse tratamento.
- `value_variants`, `try_decode`, `_deduplicate`, `_extract_step_index` não
  mudam.

### 3.2 `CandidateResolver` propaga o índice do step atual até `ResponseGrep.find`

**Estado atual:** `resolve`/`_process_candidate`/`_find_origin` (seção 2) não
recebem nem repassam nenhum índice de step; `_origin_cache` é chaveada só pelo
valor.

**Estado esperado:**
```python
def resolve(self, candidates: List[DynamicToken], step_index: int) -> List[DynamicToken]:
    return [self._process_candidate(candidate, step_index) for candidate in candidates]

def _process_candidate(self, candidate: DynamicToken, step_index: int) -> DynamicToken:
    origin: Optional[Tuple[int, str]] = self._find_origin(candidate.current_value, step_index)
    if not origin:
        candidate.status = "NotFound"
        return candidate

    candidate.origin_step = origin[0]
    ...  # resto do método inalterado

def _find_origin(self, value: str, step_index: int) -> Optional[Tuple[int, str]]:
    cache_key: Tuple[str, int] = (value, step_index)
    if cache_key in self._origin_cache:
        return self._origin_cache[cache_key]
    origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, value, step_index)
    self._origin_cache[cache_key] = origin
    return origin
```
- `_origin_cache: Dict[str, Optional[Tuple[int, str]]]` (linha 45) muda para
  `Dict[Tuple[str, int], Optional[Tuple[int, str]]]` — ⚠️ chave só por `value`
  deixaria de ser segura: o mesmo valor pode não ter origem elegível quando
  analisado num step cedo (ex.: step 12) e ter uma origem legítima quando
  analisado num step mais tarde (ex.: step 30, se algo o expôs numa response
  entre os dois), então um "não encontrado" cacheado sob a chave antiga
  vazaria incorretamente para o step seguinte.
- Nenhuma outra lógica de `_process_candidate` (derivação de `token_id`,
  `_find_slot`, geração de extractor) muda — o `origin_step` que chega até ali
  já vem garantidamente causal.

### 3.3 `TokenTracker.analyze_step` repassa `step.index` já disponível

**Estado atual:** `self.candidate_resolver.resolve(candidates)` (seção 2, sem
argumento de step).

**Estado esperado:**
```python
tokens: List[DynamicToken] = self.candidate_resolver.resolve(candidates, step.index)
```
Única mudança neste método — `step.index` já existe e já é usado duas linhas
abaixo, não precisa de nenhum valor novo vindo de fora.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `ResponseGrep.find` / `_grep_single_pattern` | Ganham parâmetro `before_step_index`; busca restrita a responses de steps `< before_step_index` via novo `_eligible_response_files`, em vez de `grep -r` no diretório inteiro. |
| `CandidateResolver.resolve` / `_process_candidate` / `_find_origin` | Ganham/propagam parâmetro `step_index`; `_origin_cache` passa a ser chaveada por `(value, step_index)`. |
| `TokenTracker.analyze_step` | Passa `step.index` para `self.candidate_resolver.resolve(...)`. |

## 5. Casos de borda e comportamento de erro

- **Valor sem nenhuma response elegível anterior ao step atual** (o bug
  reproduzido: `Origin` do browser, só ecoado numa response a partir do step
  75, referenciado desde o step 12) — vira `NotFound`, mesmo caminho já
  existente para "grep não achou nada"; `PlaceholderApplier` mantém o valor
  literal no curl (seção 2). Comportamento esperado e correto, não uma
  limitação.
- **Diretório de output reaproveitado entre execuções** (`Workspace.init` não
  limpa `real_responses`/`original_responses` entre runs) — responses de steps
  futuros deixadas por uma execução anterior deixam de contaminar a busca de
  origem de qualquer step da execução atual, independentemente de terem
  sobrado de uma run completa anterior ou de uma run parcial/interrompida.
- **Extractors já persistidos em disco com `origin_step` futuro** (gerados
  antes desta correção, ex.: `arquivos-har/output/extractors/extract_5809b41....meta.json`
  com `origin_step: 75` usado desde o step 12) — não são migrados nem
  apagados por esta mudança. Numa reexecução de `run`/`reproduce` sobre o
  mesmo diretório de output, `_check_persisted_slot` (`candidate_resolver.py:108-118`)
  só reaproveita um extractor persistido se o `slot_id` (hash de
  `path:origin_step`) bater — como o novo `origin_step` computado para o mesmo
  `path` deixa de ser 75 (vira `None`/`NotFound`, seção acima), o `slot_id`
  muda e o arquivo antigo simplesmente fica órfão (não referenciado por nenhum
  curl novo), sem quebrar nada. Recomenda-se `--reset-output-dir` para uma
  reconstrução limpa quando se quiser evitar esses órfãos.
- **Cache de origem (`_origin_cache`) por processo** — como cada valor pode
  ter resultados diferentes dependendo do `step_index` de quem pergunta
  (decisão 3.2), a cache passa a ter uma entrada por combinação
  `(valor, step_index)` em vez de uma por valor; isso reduz um pouco a taxa de
  acerto da cache (candidatos com o mesmo valor em steps diferentes não
  compartilham mais entrada), mas elimina o risco de resultado incorreto —
  troca aceita, já que o volume de candidatos por HAR é pequeno (dezenas a
  poucas centenas) e cada chamada de `ResponseGrep.find` já é barata (grep
  sobre um recorte pequeno de arquivos, não o diretório inteiro de novo).
- **Step 0 (baseline) analisado contra si mesmo** — `before_step_index=0` faz
  `_eligible_response_files` retornar lista vazia antes de qualquer `grep`
  rodar; na prática nem chega a acontecer, porque comparar o step 0 com ele
  mesmo como baseline não produz nenhum diff/candidato (`BaselineDiff.compare`,
  seção 2 de `docs/20260803 Origem de Token Não Determinada/spec.md`).

## 6. Referência

Implementação segue [[guia-de-estilo]].
