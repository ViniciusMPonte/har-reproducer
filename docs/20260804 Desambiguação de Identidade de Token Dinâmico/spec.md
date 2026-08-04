# Spec — Desambiguação de Identidade de Token Dinâmico

> Fonte única de verdade para gerar o `implementation_plan.md` desta etapa. Assume que
> quem escreve o plano não participou da conversa que chegou a estas decisões — tudo
> que é necessário para entender o "porquê" e o "o quê" está aqui, sem depender de nada
> além do código-fonte atual do projeto (`har_reproducer/`), do `guia_de_estilo.md` e do
> `spec.md` de `docs/20260803 Reaproveitamento de Extractores/` (mecanismo de
> persistência entre execuções, já implementado, reaproveitado e corrigido aqui).

## 1. Objetivo

Hoje, `CandidateResolver._derive_token_id(path, origin_step)`
(`tracking/candidate_resolver.py:93-95`) deriva o `token_id` de um token dinâmico
**só** a partir de `(path, origin_step)` — a posição estrutural onde o valor foi
encontrado (nome do header/cookie, ou a chave constante `"url"`/`"body"`) e o índice do
step de origem. **O valor real do token nunca entra nessa conta.**

Isso causa colisão sempre que dois tokens **realmente diferentes** compartilham o mesmo
`(path, origin_step)` — o que acontece na prática sempre que dois requests distintos
usam o mesmo nome de header/cookie (ou têm diffs de URL/body) cujos valores dinâmicos
foram encontrados na mesma resposta de origem. Caso real observado, rodando
`run --mode main` sobre um HAR de produção:

- Step 1: header `Sec-Fetch-Dest: style` → `path="header:Sec-Fetch-Dest"`,
  `origin_step=0` → `token_id = md5("header:Sec-Fetch-Dest:0") = b774bbe7...`. Resolvido
  corretamente (extractor via `CSSAgent`, retorna `"style"`).
- Step 4: header `Sec-Fetch-Dest: image` → **mesmo** `path`, **mesmo** `origin_step=0`
  (o valor "image" também aparece na resposta do step 0) → **mesmo**
  `token_id = b774bbe7...`. `CandidateResolver._reuse_verified_in_memory`
  (`candidate_resolver.py:62-67`) encontra esse `token_id` já `verified=True` no
  registry (setado ao processar o step 1) e marca `status="Resolved"` **sem checar se o
  extractor cacheado (o de "style") produz o valor esperado por este candidato
  ("image")**. O curl do step 4 é gerado usando o extractor errado, e falha em runtime
  (`PlaceholderApplier` propaga o valor errado para URL, `Accept` e `Sec-Fetch-Dest`
  desse step, por já substituir `current_value` globalmente em todos os campos do
  request — `tracking/placeholder_applier.py:20-32` — comportamento que não muda nesta
  spec).

Um segundo caminho do mesmo bug, mais destrutivo, existe na reutilização **entre
execuções** (`_reuse_persisted_from_disk`, `candidate_resolver.py:69-80`): se um
processo novo encontra, para o mesmo `token_id` colidido, um extractor persistido em
disco que não bate com `candidate.current_value`, ele cai em
`_generate_new_extractor`/`_register_extractor`
(`candidate_resolver.py:82-91`/`103-116`), que **grava o extractor novo sob o mesmo
`token_id`** — sobrescrevendo em disco (`extract_{token_id}.py` e `.meta.json`) o
extractor de um token diferente que outro step, já processado com sucesso, continua
referenciando no seu `.curl.sh`. Não é só "usa o valor errado uma vez": é "pode destruir
silenciosamente um extractor correto de outro step".

Esta spec corrige a causa raiz: **a identidade de um token passa a ser resolvida por um
mecanismo que valida o valor antes de aceitar reaproveitamento, e nunca sobrescreve um
slot já ocupado por um valor diferente — em vez disso, cria um slot novo (fork
determinístico) para o valor que não bate.**

**Fora de escopo** (não implementar agora):

- Separar respostas originais do HAR das respostas reais de execução (`real_responses/`
  hoje é sobrescrito a cada `run`). É um problema real, discutido separadamente, mas
  ortogonal a este: mesmo com respostas originais preservadas, a colisão de
  `token_id` aconteceria do mesmo jeito, porque a causa é a fórmula de identidade, não a
  fonte da resposta.
- Redesenhar a granularidade de `BaselineDiff._diff_url`/`_diff_body`
  (`tracking/baseline_diff.py:18-21`/`39-50`) para decompor por segmento de URL ou por
  campo JSON. Não é necessário: o mecanismo de desambiguação desta spec elimina a
  colisão **independente de quão grosseiro o `path` for** — inclusive para os casos
  `"url"`/`"body"` (chave constante, o pior caso), sem tocar em `BaselineDiff`.
- Impor um teto artificial de quantos valores distintos podem compartilhar o mesmo
  `(path, origin_step)` (ver seção 5).

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

- **`CandidateResolver._process_candidate`** (`candidate_resolver.py:40-60`) — fluxo
  atual:
  ```python
  def _process_candidate(self, candidate: DynamicToken) -> DynamicToken:
      origin: Optional[Tuple[int, str]] = ResponseGrep.find(
          self.responses_dir, candidate.current_value
      )
      if not origin:
          candidate.status = "NotFound"
          return candidate

      candidate.origin_step = origin[0]
      candidate.token_id = self._derive_token_id(candidate.path, candidate.origin_step)

      if self._reuse_verified_in_memory(candidate):
          return candidate

      reused: bool
      initial_error: Optional[str]
      reused, initial_error = self._reuse_persisted_from_disk(candidate)
      if reused:
          return candidate

      return self._generate_new_extractor(candidate, initial_error)
  ```
  É exatamente aqui, na atribuição direta `candidate.token_id = self._derive_token_id(...)`
  seguida das duas checagens de reuso, que a colisão acontece — ver seção 3.

- **`CandidateResolver._reuse_verified_in_memory`** (`candidate_resolver.py:62-67`) —
  ```python
  def _reuse_verified_in_memory(self, candidate: DynamicToken) -> bool:
      existing: Optional[Extractor] = self.session_store.state.registry.get(candidate.token_id)
      if existing is None or not existing.verified:
          return False
      candidate.status = "Resolved"
      return True
  ```
  Não valida o valor — é o caminho que aceitou silenciosamente o extractor errado no
  caso real relatado. **Será removido** (substituído pelo mecanismo da seção 3).

- **`CandidateResolver._reuse_persisted_from_disk`** (`candidate_resolver.py:69-80`) —
  ```python
  def _reuse_persisted_from_disk(self, candidate: DynamicToken) -> Tuple[bool, Optional[str]]:
      persisted: Optional[Extractor] = self.metadata_store.load(candidate.token_id)
      if persisted is None:
          return False, None
      result: Optional[str] = self.extractor_runner.run_existing(candidate.token_id)
      if result == candidate.current_value:
          self.session_store.state.registry[candidate.token_id] = persisted
          candidate.status = "Resolved"
          return True, None
      return False, self._mismatch_error(result, candidate.current_value)
  ```
  Este **já valida** o valor (é o que a spec de Reaproveitamento introduziu) — mas ao
  falhar, o chamador segue para `_generate_new_extractor`, que grava por cima do mesmo
  `token_id` (vetor de corrupção descrito na seção 1). **Será removido** (a validação
  que ele faz é reaproveitada dentro do novo mecanismo unificado, seção 3.3).

- **`CandidateResolver._derive_token_id`** (`candidate_resolver.py:93-95`) —
  ```python
  @staticmethod
  def _derive_token_id(path: str, origin_step: int) -> str:
      return hashlib.md5(f"{path}:{origin_step}".encode("utf-8")).hexdigest()
  ```
  **Mantido sem alteração** — continua sendo a base determinística (mesmo `path` +
  mesmo `origin_step` em execuções diferentes geram o mesmo id-base). A correção não
  troca essa fórmula, só deixa de tratar o resultado dela como definitivo sem validação.

- **`CandidateResolver._generate_new_extractor`/`_register_extractor`**
  (`candidate_resolver.py:82-91`/`103-116`) — **mantidos sem alteração de assinatura**.
  `_generate_new_extractor(candidate, initial_error)` já aceita o erro da tentativa
  anterior como contexto pro LLM (mecanismo de correção da spec de Reaproveitamento);
  esta spec só muda **qual `token_id`** já está setado em `candidate` no momento em que
  esses métodos são chamados (o slot livre encontrado pela busca da seção 3.3, nunca
  necessariamente o id-base).

- **`ExtractorMetadataStore.load`/`save`** (`reproduction/extractor_metadata_store.py`)
  — único ponto de I/O do `.meta.json`, chaveado só por `token_id`
  (`Workspace.extractor_meta_file`). Reaproveitado sem alteração — a busca de slot da
  seção 3.3 chama `load` para cada slot candidato na sequência de tentativas.

- **`ExtractorRunner.run_existing`** (`reproduction/extractor_runner.py:21-29`) —
  executa o `.py` já persistido em `Workspace.extractor_file(token_id)`, retorna
  `stdout` ou `None` em qualquer falha. Reaproveitado sem alteração.

- **`Workspace.extractor_file`/`extractor_meta_file`** (`fs_io/workspace.py:49-57`) —
  caminho derivado só de `token_id` (`extract_{token_id}.py`/`.meta.json`). Reaproveitado
  sem alteração — todo slot (id-base ou fork) usa o mesmo par de arquivos, só muda o
  valor de `token_id` usado para nomeá-los.

- **`SessionStore.TOKEN_PLACEHOLDER_PATTERN`** (`session/session_store.py:9`) —
  ```python
  TOKEN_PLACEHOLDER_PATTERN: ClassVar[Pattern[str]] = re.compile(r"\{\{extractor:([a-f0-9]+)\}\}")
  ```
  **Restrição crítica**: só aceita `[a-f0-9]+` (hex). Qualquer novo formato de id (fork)
  tem que produzir uma string hex válida para continuar renderizável — ver seção 3.1.

- **`CurlDependencyParser.DEPENDENCY_PATTERN`** (`replay/curl_dependency_parser.py:7-10`)
  — `r"^# Token (?P<token_id>[a-z0-9]+) comes from response of step (?P<origin_step>\d+)$"`.
  Mesma restrição de formato (hex é subconjunto de `[a-z0-9]+`, compatível). Usado pelo
  replay para descobrir dependências (`_schedule_smart`) — não muda, só passa a ver ids
  de fork como qualquer outro id.

- **`SessionStore.state.tokens`/`render`** (`session_store.py:14-41`) — dict achatado
  `token_id -> valor`, sem noção de "por step". `render()` substitui
  `{{extractor:id}}` pelo que estiver em `state.tokens[id]`, igual em qualquer curl que
  referencie aquele id. Confirma por que a correção tem que ser na **identidade**: sem
  isso, dois tokens diferentes que dividem um id sempre renderizam para o mesmo valor
  "vencedor", não importa qual step está sendo montado.

- **`TokenResolver.resolve_all`** (`tracking/token_resolver.py:14-20`) — chamado uma vez
  por step (`Engine._process_entry`, `engine.py:98`, e de novo em `handle_recovery`),
  reexecuta **todo** `session_store.state.registry` e faz
  `session_store.set_token(token_id, value)`. Relevante para a seção 3.3: garante que,
  ao processar um step posterior, qualquer slot registrado num step anterior **já tem
  o `.py` escrito em disco** (via `ExtractorRunner.run`, chamado por este método) antes
  do próximo step ser processado — não existe janela onde um slot criado num step
  anterior ainda esteja "só na memória, sem `.py` em disco" quando um step posterior
  tenta reaproveitá-lo.

- **`ReplayTokenResolver._resolve_one`/`_record_observation`**
  (`replay/replay_token_resolver.py:40-67`) — atualiza `valid_count`/`last_value`/
  `ever_changed` no `.meta.json` por `token_id`, usado pra detectar token "falso
  dinâmico" durante `replay`. Não muda nesta spec — mas passa a se beneficiar
  automaticamente da correção: hoje, dois tokens colididos compartilham (e
  contaminam) o mesmo histórico; depois, cada slot tem o seu.

## 3. Decisões de arquitetura

### 3.1 Sequência determinística de slots por `(path, origin_step)`

Hoje existe só **um** slot possível por `(path, origin_step)` (o id-base). Passa a
existir uma sequência: o id-base (tentativa 1) e, se ele já estiver ocupado por um valor
diferente, forks subsequentes (tentativa 2, 3, ...), cada um um `token_id` hex distinto
e determinístico:

```python
@staticmethod
def _fork_token_id(base_token_id: str, attempt: int) -> str:
    return hashlib.md5(f"{base_token_id}:{attempt}".encode("utf-8")).hexdigest()
```

`attempt == 1` usa o próprio `base_token_id` (sem essa função); `attempt >= 2` usa
`_fork_token_id`. Saída sempre hex (`hashlib.md5(...).hexdigest()`), compatível com
`SessionStore.TOKEN_PLACEHOLDER_PATTERN`/`CurlDependencyParser.DEPENDENCY_PATTERN` (seção
2) sem exigir mudança nesses regexes.

Determinístico entre execuções **desde que a ordem dos steps do HAR não mude**: o
primeiro valor realmente distinto encontrado para um `(path, origin_step)`, na ordem em
que os steps são processados, sempre ocupa a tentativa 1; o segundo valor distinto,
tentativa 2; e assim por diante — igual em qualquer execução nova sobre o mesmo HAR,
porque `Engine._reproduce` sempre processa os entries na mesma ordem (`engine.py:83-84`).

### 3.2 Novo enum `SlotStatus`

```python
class SlotStatus(str, Enum):
    MATCH = "Match"
    MISMATCH = "Mismatch"
    FREE = "Free"
```

Terceiro estado que `_reuse_verified_in_memory`/`_reuse_persisted_from_disk` (booleanos)
não representavam de forma unificada. Definido em `candidate_resolver.py` — uso interno
e exclusivo desta classe, sem necessidade de virar um conceito de `models/`.

### 3.3 Busca unificada de slot — substitui os dois métodos de reuso

Novo fluxo em `_process_candidate`:

```python
def _process_candidate(self, candidate: DynamicToken) -> DynamicToken:
    origin: Optional[Tuple[int, str]] = ResponseGrep.find(
        self.responses_dir, candidate.current_value
    )
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
```

```python
def _find_slot(self, base_token_id: str, candidate: DynamicToken) -> Tuple[str, Optional[str]]:
    attempt: int = 1
    last_error: Optional[str] = None
    while True:
        slot_id: str = base_token_id if attempt == 1 else self._fork_token_id(base_token_id, attempt)
        status: SlotStatus
        error: Optional[str]
        status, error = self._check_slot(slot_id, candidate)
        if status == SlotStatus.MATCH:
            return slot_id, None
        if status == SlotStatus.FREE:
            return slot_id, last_error
        last_error = error
        attempt += 1
```

```python
def _check_slot(self, slot_id: str, candidate: DynamicToken) -> Tuple[SlotStatus, Optional[str]]:
    cached_value: Optional[str] = self._validated_values.get(slot_id)
    if cached_value is not None:
        if cached_value == candidate.current_value:
            return SlotStatus.MATCH, None
        return SlotStatus.MISMATCH, self._mismatch_error(cached_value, candidate.current_value)

    persisted: Optional[Extractor] = self.metadata_store.load(slot_id)
    if persisted is None:
        return SlotStatus.FREE, None

    result: Optional[str] = self.extractor_runner.run_existing(slot_id)
    if result == candidate.current_value:
        self.session_store.state.registry[slot_id] = persisted
        self.session_store.set_token(slot_id, result)
        self._validated_values[slot_id] = result
        return SlotStatus.MATCH, None
    return SlotStatus.MISMATCH, self._mismatch_error(result, candidate.current_value)
```

`_reuse_verified_in_memory` e `_reuse_persisted_from_disk` são **removidos** — toda a
lógica de validação que `_reuse_persisted_from_disk` já tinha (rodar o extractor e
comparar) é reaproveitada dentro de `_check_slot`, agora aplicada uniformemente ao
slot-base **e** a cada fork.

### 3.4 Cache de valores validados nesta run — `_validated_values`

Novo atributo de instância:
```python
self._validated_values: Dict[str, str] = {}
```
(inicializado vazio no `__init__` de `CandidateResolver`, junto dos atributos já
existentes).

Por quê: sem esse cache, todo candidato — mesmo os que já bateram em algum slot antes,
no caso comum sem colisão nenhuma — passaria a rodar um subprocess
(`extractor_runner.run_existing`) a cada step, em vez do `dict.get` + checagem de
`verified` que `_reuse_verified_in_memory` fazia hoje. É uma troca deliberada
(subprocess é mais caro que um lookup em dict), aceita porque elimina o bug relatado;
o cache reduz o custo ao mínimo necessário: **um** `run_existing` por slot por execução
de `run`/`dry` (a resposta de origem não muda dentro de uma mesma execução — mesma
premissa já documentada na spec de Reaproveitamento, seção "Por quê só em `replay`"),
não um por step que referencia aquele slot. Nenhuma chamada de LLM adicional é
introduzida — o custo caro (Agent/LLM) continua evitado exatamente como hoje.

### 3.5 Mecanismo de correção redirecionado para slot novo, nunca sobrescreve

Consequência do fluxo 3.3: quando **nenhum** slot da sequência bate com
`candidate.current_value`, `_find_slot` para no primeiro `FREE` e devolve
`initial_error` = erro do **último** slot ocupado testado (não `None`). Isso preserva o
mecanismo de correção da spec de Reaproveitamento (`BaseAgent.run_tdd_loop(initial_error=...)`,
sem mudança de assinatura) — o LLM ainda recebe o contexto de por que a tentativa
anterior não bateu — mas o código gerado é escrito num slot **novo**, nunca por cima do
slot que já tinha um extractor funcional para outro valor.

Efeito prático nos dois cenários que hoje se confundiam:
- **Extractor de um slot único quebrou de verdade** (site mudou, mesma token
  semântica): `_find_slot` tenta a tentativa 1 (mismatch), não existe tentativa 2 →
  gera na tentativa 2, com o erro da tentativa 1 como contexto. A tentativa 1 fica
  "morta" (nunca mais vai bater), custo aceito: uma comparação a mais por execução
  (seção 5).
- **Token realmente diferente colide** (bug relatado): idêntico ao caso acima do ponto
  de vista do código — `_find_slot` não distingue os dois cenários, e não precisa: em
  ambos, a ação correta é a mesma (não sobrescrever, gerar num slot novo).

### 3.6 Efeito colateral positivo — detecção de token estático por slot

Sem mudança de código adicional em `ReplayTokenResolver` (seção 2): como cada slot
(base ou fork) agora tem seu próprio `.meta.json`, `valid_count`/`last_value`/
`ever_changed` deixam de ser compartilhados entre tokens que hoje colidem — a
heurística de "token provavelmente estático" (`replay_token_resolver.py:57-67`) passa a
refletir o histórico de um único token real, não uma mistura de dois.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `CandidateResolver` (`__init__`) | + atributo `self._validated_values: Dict[str, str] = {}` |
| `CandidateResolver._process_candidate` | reescrito: usa `_find_slot` em vez de `_reuse_verified_in_memory`/`_reuse_persisted_from_disk` |
| `CandidateResolver._reuse_verified_in_memory` | removido |
| `CandidateResolver._reuse_persisted_from_disk` | removido (validação reaproveitada em `_check_slot`) |
| `CandidateResolver._find_slot` (novo) | percorre tentativas 1, 2, 3, ... até achar `MATCH` ou `FREE` |
| `CandidateResolver._check_slot` (novo) | valida um slot específico (cache em memória → disco+execução), classifica `SlotStatus` |
| `CandidateResolver._fork_token_id` (novo, `@staticmethod`) | deriva id de fork determinístico e hex-compatível |
| `SlotStatus` (novo enum, em `candidate_resolver.py`) | `MATCH` / `MISMATCH` / `FREE` |
| `CandidateResolver._derive_token_id` | sem alteração |
| `CandidateResolver._generate_new_extractor`/`_register_extractor` | sem alteração de assinatura/comportamento |

## 5. Casos de borda e comportamento de erro

- **Mesmo valor reaparecendo em vários steps** (uso legítimo do mesmo token em N
  requests): `_find_slot` bate `MATCH` na tentativa 1 sempre — comportamento idêntico ao
  reuso de hoje, sem custo extra de LLM, e (a partir da 2ª checagem na mesma run) sem
  subprocess extra graças a `_validated_values` (seção 3.4).
- **Dois valores diferentes no mesmo `(path, origin_step)` (bug relatado)**: primeiro
  valor ocupa a tentativa 1; segundo valor não bate na tentativa 1, não existe tentativa
  2 → gera extractor novo na tentativa 2. Nenhum arquivo do slot 1 é tocado.
- **Terceiro valor distinto aparecendo depois no mesmo `(path, origin_step)`**:
  `_find_slot` testa tentativa 1 (mismatch), tentativa 2 (mismatch), acha tentativa 3
  livre → gera lá. Sem teto artificial (seção 1) — se um `path` gerar muitos valores
  realmente distintos (sintoma de `path` pouco granular, ex. `"url"`/`"body"`
  constantes), o sistema continua correto, só faz mais comparações; redesenhar a
  granularidade do diff fica fora de escopo (seção 1).
- **Execução nova (processo do zero) depois que forks já existem em disco**: mesma
  ordem de steps ⇒ mesma sequência de tentativas ⇒ mesmo mapeamento valor→slot já
  persistido é reencontrado e reaproveitado (nenhuma tentativa de LLM), incluindo os
  forks — `_check_slot` também consulta `metadata_store.load`/`extractor_runner.run_existing`
  para tentativas `>= 2`, não só a tentativa 1.
- **`.meta.json` existe mas `extract_{slot_id}.py` não (ou vice-versa) para um slot
  específico**: mesmo tratamento já definido na spec de Reaproveitamento — `run_existing`
  retorna `None`, `_check_slot` trata como `MISMATCH` (não como `FREE`, já que
  `metadata_store.load` achou o metadado) com erro "no output"; `_find_slot` segue pra
  próxima tentativa. Isso significa que uma inconsistência manual nesse slot específico
  nunca é tratada como vaga livre por engano — sempre avança para a próxima tentativa,
  preservando o mesmo comportamento de degradação sem sobrescrever nada indevidamente.
- **`--reset` passado em `run`/`parse`**: apaga `extractors/` inteiro — todos os slots
  (base e forks) somem, próxima execução recomeça do zero para todo `(path, origin_step)`.
  Comportamento herdado sem mudança.
- **Custo de subprocess por execução**: aceito e documentado (seção 3.4) — um
  `run_existing` por slot único por execução de `run`/`dry`/`replay`, não por
  step/uso do slot.

## 6. Referência

Implementação deve seguir `guia_de_estilo.md`: tipagem explícita em tudo, `ClassVar`
para constantes de classe, `Enum(str, Enum)` para conjunto fechado de valores
(`SlotStatus`), um conceito por arquivo/classe, guard clauses, zero
comentários/docstrings, `except Exception` amplo só em bordas de I/O/subprocess (sempre
com print de aviso + degradação, nunca crash silencioso), e o processo de "propor
decomposição → aprovação → gerar arquivo → compile-check" para cada task do plano.
