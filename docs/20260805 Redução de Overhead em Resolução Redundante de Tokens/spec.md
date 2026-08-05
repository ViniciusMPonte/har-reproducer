# Spec — Redução de Overhead em Resolução Redundante de Tokens

> Fonte única de verdade para gerar o `implementation_plan.md` desta etapa. Assume que
> quem escreve o plano não participou da conversa que chegou a estas decisões — tudo
> que é necessário para entender o "porquê" e o "o quê" está aqui, sem depender de nada
> além do código-fonte atual do projeto (`har_reproducer/`) e do `guia_de_estilo.md`.

## 1. Objetivo

Rodando `run --mode dry` contra um HAR de 238 entries (`arquivos-har/progressofit.har`),
o tempo por step cresce de forma perceptível conforme a execução avança — sem relação
com geração de extractor via LLM (que já tem custo esperado e conhecido). A causa são
dois pontos do fluxo de tracking que fazem trabalho proporcional ao **histórico
acumulado** (tamanho do registry de tokens / quantidade de responses já persistidas) em
vez de trabalho proporcional só ao step atual — ou seja, custo O(n²) ao longo de uma run
de n steps.

Medido neste ambiente: spawn de um subprocess Python no `.venv` do projeto custa
**~10-13ms**; uma chamada `grep -rlF` sobre o diretório de responses já persistido custa
**~2-5ms**. Numa run anterior deste mesmo HAR (`arquivos-har/output`), o registry de
tokens chegou a **74 extractors**. Isso já é suficiente para o Ponto 1 abaixo custar
`~74 × 10ms ≈ 750ms` extras por step, repetido a cada step seguinte.

**Ponto 1 — `TokenResolver.resolve_all()` chamado incondicionalmente a cada step.**
`Engine._process_entry` chama `resolve_all()` depois de todo `analyze_step`, não só
quando há recuperação de erro. `resolve_all()` itera **todo** o registry de tokens já
resolvidos e, para cada um, spawna um subprocess para reexecutar o extractor — mesmo
quando nada mudou. Em `dry` (`DryEngine.USES_NETWORK = False`), nenhuma requisição é
enviada e nenhum arquivo de response é reescrito depois de criado, então o resultado de
qualquer extractor já resolvido **não pode mudar** — a chamada é 100% redundante nesse
modo.

**Ponto 2 — `ResponseGrep.find()` re-varre o diretório de responses a cada step, mesmo
para valores já resolvidos.** `BaselineDiff.compare` compara cada step contra o
**primeiro** entry do HAR (baseline fixo), não contra o step anterior — então qualquer
header/cookie que mudou uma vez (ex.: cookie de sessão setado após login) e permanece
igual dali em diante continua aparecendo como "diff" em **todo** step seguinte, virando
um novo `candidate` toda vez. `CandidateResolver._process_candidate` chama
`ResponseGrep.find()` (até 4 subprocessos `grep`, um por variante do valor) **antes** de
qualquer cache — o cache existente (`_validated_values`) só é consultado depois, dentro
de `_check_slot`, e não evita o grep em si.

Fora de escopo (não implementar agora): qualquer mudança no comportamento de
`resolve_all()` para o engine "live"/rede (`Engine` base, usado por `run --mode main`).
Esse engine roda com um proxy `mitm` capturando tráfego em paralelo, e não há evidência
suficiente aqui de que um response já persistido nunca é afetado por captura assíncrona
fora do loop principal — mexer nesse caminho sem essa garantia mudaria comportamento
observável do modo que já funciona hoje. O Ponto 1 é corrigido especificamente para
`DryEngine` (via `USES_NETWORK`, já existente). O Ponto 2 é seguro para os dois modos
(ver seção 2, `responses_dir` é append-only nos dois).

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

- **`Engine._process_entry`** (`engines/engine.py:89-109`) — laço principal, uma
  chamada por step do HAR:
  ```python
  step.analysis = self.tracker.analyze_step(step, first_entry)
  self.token_resolver.resolve_all()

  response: StepResponse = self.execute_step(step)
  self._persist_response_step(index, response)
  ```
  `resolve_all()` roda **sempre**, para os dois engines (`Engine` e `DryEngine`, que não
  sobrescreve `_process_entry`, só `execute_step`/`_persist_response_step`).

- **`Engine.USES_NETWORK`** (`engines/engine.py:24`) — `ClassVar[bool] = True` na base;
  `DryEngine.USES_NETWORK` (`engines/dry_engine.py:8`) sobrescreve para `False`. Já é o
  hook usado em `_build_http_transport` (`engine.py:57-63`) para decidir se instancia
  `CurlHttpTransport` — mesmo padrão reaproveitado aqui, nenhum conceito novo.

- **`Engine.handle_recovery`** (`engines/engine.py:132-141`) — chamado só por
  `execute_step`/`StepRetryPolicy.execute` (`reproduction/step_retry_policy.py:16-23`)
  quando o status da resposta é 400/401. `DryEngine.execute_step`
  (`engines/dry_engine.py:10-12`) **não** passa por `retry_policy` — retorna
  `step.response` direto — então `handle_recovery` (e a chamada de `resolve_all()`
  dentro dele) nunca é acionado em modo `dry`. Esta spec não toca nesse caminho.

- **`TokenResolver.resolve_all`** (`tracking/token_resolver.py:15-18`):
  ```python
  def resolve_all(self) -> None:
      for token_id, extractor in self.session_store.state.registry.items():
          if self._should_refresh_token(extractor):
              self._refresh_token(token_id, extractor)
  ```
  Itera **todo** `session_store.state.registry` (só cresce ao longo da run); para cada
  extractor `verified` com `origin_step` não nulo, `_refresh_token` chama
  `extractor_runner.run(extractor, responses_dir)` — um `subprocess.run` novo por
  chamada (`reproduction/extractor_runner.py:52-71`).

- **`CandidateResolver._process_candidate`** (`tracking/candidate_resolver.py:49-69`) —
  primeira linha do método:
  ```python
  origin: Optional[Tuple[int, str]] = ResponseGrep.find(
      self.responses_dir, candidate.current_value
  )
  ```
  Chamado por `resolve()` (`candidate_resolver.py:46-47`), um `_process_candidate` por
  candidato retornado por `BaselineDiff.detect_candidates` — que por sua vez usa
  `BaselineDiff.compare` (`tracking/baseline_diff.py:9-15`), sempre `step` vs. o
  **primeiro** entry do HAR (`first_entry`, fixo, passado por `Engine._reproduce`,
  `engine.py:81,85`).

- **`ResponseGrep.find`** (`tracking/response_grep.py:11-17`):
  ```python
  @classmethod
  def find(cls, responses_dir: Path, pattern: str) -> Optional[Tuple[int, str]]:
      for variant in cls.value_variants(pattern):
          match: Optional[Tuple[int, str]] = cls._grep_single_pattern(responses_dir, variant)
          if match is not None:
              return match
      return None
  ```
  `value_variants` (`response_grep.py:37-45`) gera até 4 variantes (valor bruto,
  decodificado — url/base64 —, url-encoded, base64) e cada uma passa por
  `_grep_single_pattern` (`response_grep.py:57-78`), que spawna um `subprocess.run(["grep",
  "-rlF", "--include=res_*.json", pattern, str(responses_dir)])`. Nenhum cache — toda
  chamada a `find` refaz a varredura completa do diretório, do zero.

- **`CandidateResolver._check_slot`/`_check_cached_slot`**
  (`candidate_resolver.py:86-100`) — cache **existente**, mas só entra em ação **depois**
  que `origin_step` já foi determinado via `ResponseGrep.find` (linha 50) e o
  `base_token_id` derivado (`_derive_token_id`, linha 58) — ou seja, o grep já rodou
  antes desse cache ser consultado. Este cache (`self._validated_values: Dict[str,
  str]`, `candidate_resolver.py:44`) é por `slot_id`, não por valor — não serve para
  evitar o Ponto 2, só para evitar reprocessamento de agente depois que o `origin_step`
  já é conhecido.

- **Persistência de responses durante `run`/`dry`** (`engine.py:111-119`) —
  `_persist_request_step`/`_persist_original_response_step`/`_persist_response_step`
  escrevem, cada uma, exatamente um arquivo por `index`, uma única vez, dentro do laço
  sequencial de `_process_entry`. Nenhum outro ponto do fluxo principal (`run`/`dry`)
  reescreve um arquivo de response já persistido para um índice anterior — o diretório
  usado por `ResponseGrep`/`CandidateResolver`
  (`self.tracking_responses_dir`/`self.responses_dir`, `engine.py:40`,
  `candidate_resolver.py:39`) é **append-only** dentro dessa run, para os dois engines.
  Isso é o que garante que cachear por valor (seção 3.2) não muda o resultado de
  `ResponseGrep.find` em nenhum caso do fluxo `run`/`dry`.

## 3. Decisões de arquitetura

### 3.1 `resolve_all()` só roda por step quando o engine usa rede

Estado atual (`engine.py:99-100`):
```python
step.analysis = self.tracker.analyze_step(step, first_entry)
self.token_resolver.resolve_all()
```

Estado esperado:
```python
step.analysis = self.tracker.analyze_step(step, first_entry)
if self.USES_NETWORK:
    self.token_resolver.resolve_all()
```

`DryEngine.USES_NETWORK = False` já existe (`dry_engine.py:8`) — reaproveitado, nenhum
flag novo. Efeito: em `dry`, a chamada por step desaparece por completo (era 100%
redundante, seção 1); em `main` (engine base, `USES_NETWORK = True`), comportamento
**idêntico** ao atual — nenhuma mudança observável nesse modo, dado o "fora de escopo"
da seção 1.

`handle_recovery` (`engine.py:140`) não é afetado — continua chamando `resolve_all()`
incondicionalmente quando aciona uma recuperação; isso só acontece via `retry_policy`,
que `DryEngine` nunca invoca (seção 2).

### 3.2 Cache de origem por valor em `CandidateResolver`

Estado atual (`candidate_resolver.py:49-52`):
```python
def _process_candidate(self, candidate: DynamicToken) -> DynamicToken:
    origin: Optional[Tuple[int, str]] = ResponseGrep.find(
        self.responses_dir, candidate.current_value
    )
```

Estado esperado — novo atributo no `__init__` (ao lado de `self._validated_values`,
`candidate_resolver.py:44`):
```python
self._origin_cache: Dict[str, Optional[Tuple[int, str]]] = {}
```

Novo método privado, único ponto que chama `ResponseGrep.find`:
```python
def _find_origin(self, value: str) -> Optional[Tuple[int, str]]:
    if value in self._origin_cache:
        return self._origin_cache[value]
    origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, value)
    self._origin_cache[value] = origin
    return origin
```

`_process_candidate` passa a chamar `self._find_origin(candidate.current_value)` em vez
de `ResponseGrep.find(...)` diretamente.

⚠️ O cache é por **valor**, não por `path`/candidato — isso preserva exatamente a
semântica atual, porque `ResponseGrep.find` já ignora `path` na assinatura de hoje (só
recebe `responses_dir` e o valor). Se dois candidatos de `path`s diferentes tiverem o
mesmo `current_value`, o código atual (sem cache) já retornaria a mesma origem para os
dois — o cache só evita repetir o trabalho de achar essa origem, não muda quem recebe
o resultado. Isso também cobre o caso comum que motiva esta spec: o mesmo header/cookie
com o mesmo valor aparecendo como "diff" em dezenas de steps seguidos (seção 1) passa a
resolver a origem uma única vez, depois é sempre cache hit.

Cachear também o resultado `None` (não encontrado) é intencional — um valor que nunca
foi emitido por nenhum response não vai passar a ser encontrado numa consulta futura
dentro da mesma run sem que um novo response com aquele conteúdo seja persistido
primeiro (e `responses_dir` só cresce por índice novo, nunca por reescrita de um índice
já varrido).

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `Engine._process_entry` | chamada a `self.token_resolver.resolve_all()` passa a ser condicionada a `if self.USES_NETWORK:` |
| `CandidateResolver` | novo atributo `_origin_cache: Dict[str, Optional[Tuple[int, str]]]`; novo método privado `_find_origin(value)`; `_process_candidate` passa a chamar `_find_origin` em vez de `ResponseGrep.find` diretamente |

## 5. Casos de borda e comportamento de erro

- **`run --mode main` (engine com rede)**: nenhuma mudança de comportamento — `resolve_all()`
  continua rodando a cada step exatamente como hoje (seção 3.1, "fora de escopo").
- **`handle_recovery` durante `main`**: não afetado — continua chamando `resolve_all()`
  incondicionalmente na recuperação de 400/401 (`engine.py:140`), independente da
  mudança em `_process_entry`.
- **Mesmo `current_value` vindo de candidatos com `path`s diferentes no mesmo step ou em
  steps diferentes**: cache hit correto — mesma origem que o código sem cache já
  retornaria (ver ⚠️ na seção 3.2).
- **Valor de candidato nunca encontrado em nenhum response (`origin is None`)**:
  cacheado como `None` — próxima consulta com o mesmo valor, na mesma run, retorna
  `None` direto, sem novo `grep`. Comportamento observável idêntico ao atual
  (`candidate.status = "NotFound"` nos dois casos).
- **`--mode dry` com HAR pequeno (poucos steps, registry pequeno)**: ganho da seção 3.1
  é proporcionalmente pequeno (registry nunca cresce o suficiente para pesar), mas
  correto e sem custo de manutenção adicional — não é uma otimização condicionada a
  tamanho de HAR, só remove trabalho que já era sempre redundante em `dry`.

## 6. Referência

Implementação deve seguir `guia_de_estilo.md`: tipagem explícita em tudo, guard clauses,
zero comentários/docstrings, um conceito por arquivo, e a garantia de que nenhuma
mudança desta spec altera comportamento observável de `run --mode main` (seção 3.1) nem
o resultado de qualquer resolução de candidato em `dry` (seção 3.2) — só remove trabalho
redundante.
