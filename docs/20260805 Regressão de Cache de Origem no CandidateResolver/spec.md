# Spec — Regressão de Cache de Origem no CandidateResolver

> Fonte única de verdade para gerar o `implementation_plan.md` desta etapa. Assume que
> quem escreve o plano não participou da conversa que chegou a estas decisões — tudo
> que é necessário para entender o "porquê" e o "o quê" está aqui, sem depender de nada
> além do código-fonte atual do projeto (`har_reproducer/`), do `guia_de_estilo.md` e da
> spec anterior, `docs/20260805 Origem Futura de Token Dinâmico/spec.md` (referida
> abaixo como "spec anterior").

## 1. Objetivo

A spec anterior corrigiu uma dependência impossível de satisfazer (`origin_step`
apontando para um step futuro) restringindo `ResponseGrep.find` a só considerar
responses de steps estritamente anteriores ao step sendo analisado
(`before_step_index`), e propagou esse índice até `CandidateResolver._find_origin`.
Como parte dessa mudança, a cache de origem (`_origin_cache`) passou de chaveada só
por `value` para chaveada por `(value, step_index)` — decisão registrada na spec
anterior (seção 3.2) com a justificativa de que um "não encontrado" cacheado sob a
chave antiga poderia vazar incorretamente para um step seguinte, caso o valor só
ganhe uma origem legítima mais adiante na run.

Essa mudança de chave é correta para resultados **negativos** (nenhuma origem
encontrada), mas tem um efeito colateral não avaliado na spec anterior: ela também
elimina o cache hit para resultados **positivos** (origem já encontrada) — e isso é o
caso comum. Todo valor redetectado como candidato em múltiplos steps consecutivos
(qualquer header/cookie que difere do baseline uma vez e depois se mantém estável —
comportamento já documentado como limitação aceita de `BaselineDiff.compare`, que
sempre compara contra a primeira entry do HAR, `docs/20260803 Origem de Token Não
Determinada/spec.md`) passa a recalcular sua origem do zero em **todo** step
subsequente, mesmo já tendo sido encontrada e nunca mudando.

Rodando o comando reportado como lento —
```
uv run python -m har_reproducer.main replay --output arquivos-har/output \
    --config config.json --mode all
```
— contra uma run de `run`/`reproduce` já persistida deste mesmo HAR
(`arquivos-har/output/`, 137 `.curl.sh`), a investigação desta spec confirma que o
`replay` em si não recalcula origem alguma (não importa `CandidateResolver` nem
`ResponseGrep` — todo acesso a response em `replay/` é por caminho exato, ver seção 2).
O ponto de recálculo redundante existe em `run`/`reproduce` (`TokenTracker.analyze_step`
→ `CandidateResolver.resolve`, chamado a cada step por `Engine._process_entry`), e é lá
que a lentidão gradual observada tem origem estrutural — cada step redetecta os mesmos
2 a 4 candidatos estáveis (contagem real observada em `arquivos-har/output/curls/*.curl.sh`,
via `grep -c '^# Token .* comes from response of step'`) e, para cada um, refaz a
varredura completa de `ResponseGrep._eligible_response_files` (glob + filtro sobre uma
lista que cresce em 1 arquivo por step) seguida de um `grep -lF` sobre essa lista.

**Confirmação empírica.** Em `arquivos-har/original_responses/` desta mesma run (138
arquivos, 2.4MB no total, arquivos pequenos — a maioria abaixo de 5KB), o custo de um
`grep -lF` sobre uma janela de 10 arquivos vs. 130 arquivos aumenta de forma modesta
por chamada (~5.2ms → ~6.4ms, medido com 20 repetições de cada), porque os arquivos são
pequenos — o custo dominante por chamada é o *spawn* do subprocess, não a leitura dos
arquivos. O problema não é uma chamada isolada ficar lenta: é o **número de chamadas
redundantes**, que cresce com o número de steps restantes da run a partir do momento em
que cada valor estável se fixa — o mesmo padrão O(n²) (custo proporcional ao histórico
acumulado da run, não só ao step atual) que as duas specs anteriores de overhead já
identificaram e corrigiram em `TokenResolver.resolve_all` e `ResponseGrep.find`, agora
reaberto por esta spec em `CandidateResolver._find_origin`.

**O que essa mudança cobre:**
- `CandidateResolver._origin_cache` volta a funcionar como cache efetivo entre steps
  para o caso comum (origem já encontrada, valor estável) — sem reabrir o bug que a
  spec anterior corrigiu (nenhum resultado negativo passa a ser cacheado
  permanentemente; a restrição de causalidade de `ResponseGrep.find` continua sendo
  chamada normalmente sempre que a origem ainda não foi encontrada).

**Fora de escopo (não implementar agora):**
- **Otimizar o caso em que um valor nunca é encontrado** (permanece `NotFound` do
  primeiro ao último step em que aparece como candidato) — esse caminho continua
  recalculando a cada step, exatamente como hoje, porque cachear um resultado negativo
  de forma permanente reabriria a inconsistência que a spec anterior corrigiu (um valor
  pode legitimamente passar de "sem origem elegível" para "origem encontrada" conforme
  a janela de responses elegíveis cresce — seção 3 detalha a prova). Esse caso já era
  igualmente custoso antes desta spec; não piora, e corrigi-lo exigiria um mecanismo de
  janela incremental (rastrear até que step um valor já foi checado sem sucesso e
  buscar só o incremento) que não tem evidência de ser necessário para o caso relatado
  como lento — os candidatos observados na run de referência (seção 2) são todos
  eventualmente encontrados.
- **`BaselineDiff` redetectar o mesmo valor estável como candidato em todo step** —
  já documentado como limitação aceita em `docs/20260803 Origem de Token Não
  Determinada/spec.md` e reafirmado em `docs/arquitetura-e-fundamentos`. Esta spec não
  muda essa heurística; ela só corrige o custo de resolver a origem de um candidato
  redetectado, não a redetecção em si.
- **Qualquer mudança no pacote `replay/`** — investigação confirma que `replay` não
  chama `CandidateResolver`/`ResponseGrep` em nenhum caminho (seção 2); o bug é
  exclusivo do pipeline `run`/`reproduce`.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `CandidateResolver.__init__`/`_find_origin` — `har_reproducer/tracking/candidate_resolver.py:44-45,70-76`
```python
self._validated_values: Dict[str, str] = {}
self._origin_cache: Dict[Tuple[str, int], Optional[Tuple[int, str]]] = {}
```
```python
def _find_origin(self, value: str, step_index: int) -> Optional[Tuple[int, str]]:
    cache_key: Tuple[str, int] = (value, step_index)
    if cache_key in self._origin_cache:
        return self._origin_cache[cache_key]
    origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, value, step_index)
    self._origin_cache[cache_key] = origin
    return origin
```
`_find_origin` é chamado por `_process_candidate` (linha 51) para **todo** candidato de
**todo** step — inclusive candidatos que, duas linhas abaixo (linha 64), acabam batendo
com um `token_id` já presente em `session_store.state.registry` e retornando
`"Resolved"` sem nenhum trabalho adicional. É esse caminho — origem já resolvida,
extractor já registrado — que a chave `(value, step_index)` torna impossível de
cachear entre steps diferentes, mesmo sendo sempre o mesmo resultado.

### `ResponseGrep.find`/`_eligible_response_files` — `har_reproducer/tracking/response_grep.py:11-21,84-91`
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
```
```python
@classmethod
def _eligible_response_files(cls, responses_dir: Path, before_step_index: int) -> List[Path]:
    eligible: List[Path] = []
    for path in sorted(responses_dir.glob("res_*.json")):
        step_index: Optional[int] = cls._extract_step_index(path.name)
        if step_index is not None and step_index < before_step_index:
            eligible.append(path)
    return eligible
```
`_eligible_response_files` retorna os arquivos em ordem ascendente de step (o `glob`
não garante ordem, mas o `sorted()` sobre os `Path` — cujo nome de arquivo é
zero-padded — ordena por step corretamente). `_eligible_response_files(before_step_index=S)`
é sempre um subconjunto de `_eligible_response_files(before_step_index=S')` para
qualquer `S' > S` — a janela só cresce, nunca perde arquivos já elegíveis. Essa
propriedade de monotonicidade é o que sustenta a decisão 3.1: uma origem já encontrada
numa janela menor continua sendo a origem correta (menor step, seção 3.1) em qualquer
janela maior computada depois.

### `CandidateResolver._process_candidate` — `har_reproducer/tracking/candidate_resolver.py:50-68`
```python
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
```
Nenhuma lógica deste método muda — a decisão 3.1 só altera o que `_find_origin`
devolve mais rápido (mesmo valor, sem custo de busca) quando a origem já foi
encontrada antes. O `origin_step` derivado do cache continua correto (é literalmente
o mesmo valor que `ResponseGrep.find` devolveria de novo, seção acima).

### Ausência de `CandidateResolver`/`ResponseGrep` no pacote `replay/` — confirmado por
busca em `har_reproducer/replay/` e `har_reproducer/cli/cli_handlers.py`: nenhum dos
dois é importado ou instanciado nesse caminho. `ReplayTokenResolver.resolve`
(`replay/replay_token_resolver.py:25-39`) resolve tokens exclusivamente via
`ExtractorRunner.run_existing` sobre extractors já persistidos em disco — não há
busca de origem em tempo de replay. Confirma que esta spec (e seu fix) afeta somente
`run`/`reproduce`, nunca `replay`.

## 3. Decisões de arquitetura

### 3.1 `CandidateResolver._origin_cache` volta a cachear por `value`, mas só resultados positivos

**Estado atual** (seção 2): `_origin_cache: Dict[Tuple[str, int], Optional[Tuple[int, str]]]`
— guarda tanto resultados positivos quanto negativos, chaveados por `(value, step_index)`,
o que nunca dá cache hit entre steps diferentes.

**Estado esperado:**
```python
self._origin_cache: Dict[str, Tuple[int, str]] = {}

def _find_origin(self, value: str, step_index: int) -> Optional[Tuple[int, str]]:
    cached_origin: Optional[Tuple[int, str]] = self._origin_cache.get(value)
    if cached_origin is not None:
        return cached_origin
    origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, value, step_index)
    if origin is not None:
        self._origin_cache[value] = origin
    return origin
```
- A cache passa a guardar só o par `(origin_step, filename)` de resultados
  **positivos** — o tipo do dict deixa de ter `Optional` no valor porque `None` nunca
  é armazenado.
- Resultados negativos (`origin is None`) nunca são gravados na cache — toda chamada
  com um valor ainda não encontrado recalcula via `ResponseGrep.find`, exatamente como
  hoje. Isso preserva 100% do comportamento que a spec anterior corrigiu: um valor sem
  origem elegível no step atual continua sendo reavaliado nos steps seguintes, podendo
  legitimamente passar a `Found` quando uma response nova entrar na janela elegível.
- **Prova de que cachear positivos por `value` (sem o `step_index`) é seguro**: seja
  `origin = (S, filename)` o resultado de `ResponseGrep.find(responses_dir, value, before_step_index=A)`
  para algum `A`. Por definição de `_eligible_response_files` (seção 2), `S` é o menor
  step index, entre os arquivos com step `< A`, cujo conteúdo contém `value` (ou uma
  variante). Para qualquer `B > A`, a janela elegível de `before_step_index=B` é a de
  `A` mais os arquivos com step em `[A, B)` — todos com step `>= A > S`. Logo, nenhum
  arquivo novo pode conter um match com step menor que `S`; o resultado
  `ResponseGrep.find(responses_dir, value, before_step_index=B)` é garantidamente
  `(S, filename)` de novo. Retornar o valor cacheado em vez de recalcular não muda o
  resultado observável em nenhum step futuro.
- ⚠️ Isso não é uma suposição nova: é a mesma garantia de monotonicidade que a spec
  anterior já usa implicitamente ao restringir a busca a `step < before_step_index`
  (o "antes" de um step maior sempre contém o "antes" de um step menor) — esta spec só
  formaliza a consequência para o caso de cache.

### 3.2 Nenhuma mudança em `ResponseGrep`, `BaselineDiff` ou `TokenTracker`

`ResponseGrep.find`/`_eligible_response_files`/`_grep_single_pattern` (seção 2) não
mudam — a decisão 3.1 é inteiramente local a `CandidateResolver`, e a restrição de
causalidade introduzida pela spec anterior continua sendo a única regra de quais
arquivos entram na busca quando ela de fato precisa rodar (cache miss).
`BaselineDiff` (redetecção do candidato a cada step) e `TokenTracker.analyze_step`
(propagação de `step.index`) também não mudam — nenhum dos dois participa da causa
raiz desta regressão.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `CandidateResolver.__init__` | `_origin_cache` muda de `Dict[Tuple[str, int], Optional[Tuple[int, str]]]` para `Dict[str, Tuple[int, str]]` |
| `CandidateResolver._find_origin` | Chave de cache volta a ser só `value`; só resultados positivos (`origin is not None`) são gravados na cache — resultados negativos continuam sendo recalculados a cada chamada |

## 5. Casos de borda e comportamento de erro

- **Valor estável encontrado uma vez e nunca mais mudando** (o caso comum e o motivo
  desta spec, ex.: cookie de sessão pós-login) — primeira chamada com aquele valor
  paga o custo de `ResponseGrep.find`; todas as chamadas seguintes, em qualquer step
  posterior, retornam da cache em O(1), independentemente de quantos steps faltam na
  run. Elimina o crescimento O(n²) descrito na seção 1 para este caso.
- **Valor sem origem elegível que nunca aparece em nenhuma response da run** (ex.:
  constante do browser como o `Origin` do exemplo reproduzido na spec anterior) —
  continua sendo recalculado a cada step em que é redetectado como candidato, com o
  mesmo custo de hoje. Não piora, não melhora — explicitamente fora de escopo (seção 1).
- **Valor sem origem elegível nos primeiros steps, que passa a ter origem legítima mais
  tarde na run** (o caso que a spec anterior corrigiu, seção 3.2 dela) — continua
  funcionando de forma idêntica: como resultados negativos nunca são cacheados
  (decisão 3.1), a chamada no step em que a origem finalmente existe roda
  `ResponseGrep.find` normalmente e encontra o resultado positivo, que **a partir
  daquele ponto** passa a ser cacheado. Nenhuma regressão da correção anterior.
- **Dois candidatos com paths diferentes e o mesmo valor literal** (ex.: o mesmo token
  aparecendo simultaneamente como cookie e como header) — a cache é chaveada só por
  `value`, então o segundo candidato reaproveita a origem já encontrada pelo primeiro.
  Este já era o comportamento do projeto antes da spec anterior introduzir a chave
  composta (`docs/20260805 Redução de Overhead em Resolução Redundante de
  Tokens/spec.md`, onde `_origin_cache` original era `Dict[str, ...]`) — esta spec só
  reaplica esse comportamento já validado, sem introduzir um caso novo.
- **`--mode dry`/`--mode main`** — ambos passam por `TokenTracker.analyze_step` →
  `CandidateResolver.resolve`; a correção vale para os dois, sem distinção (a causa
  raiz não depende de `Engine.USES_NETWORK`).

## 6. Suposições e pontos a confirmar

Nenhuma — a mudança é local, o comportamento observável esperado para cada caso de
borda já está coberto na seção 5, e a prova de correção (seção 3.1) não depende de
nenhuma decisão de produto pendente.

## 7. Referência

Implementação deve seguir `guia_de_estilo.md`: tipagem explícita em tudo (incluindo o
novo tipo de `_origin_cache`), zero comentários/docstrings, e a garantia de que
nenhum resultado observável de `_find_origin`/`CandidateResolver.resolve` muda para
qualquer candidato — só se elimina o recálculo redundante de um resultado que já era
garantidamente idêntico (seção 3.1).
