# Plano de Implementação — Regressão de Cache de Origem no CandidateResolver

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `CandidateResolver`: `_origin_cache` volta a cachear por `value`, só resultados positivos

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (`CandidateResolver.__init__`, `CandidateResolver._find_origin`)

**Contexto:**
`_find_origin` é chamado por `_process_candidate` para todo candidato de todo step,
mesmo quando o candidato acaba batendo com um `token_id` já resolvido em
`session_store.state.registry` duas linhas depois. Hoje a cache de origem é chaveada
por `(value, step_index)`, o que nunca dá cache hit entre steps diferentes — todo
valor estável redetectado como candidato (spec seção 1) refaz `ResponseGrep.find`
(glob + grep sobre uma janela de arquivos que cresce a cada step) em todo step
subsequente, mesmo já tendo uma origem encontrada e nunca mudando. Essa task restaura
o cache hit para o caso comum sem reabrir o bug de origem futura que motivou a chave
composta (spec seção 3.1, prova de monotonicidade).

**Estado atual:**
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

**Estado esperado depois:**
```python
self._validated_values: Dict[str, str] = {}
self._origin_cache: Dict[str, Tuple[int, str]] = {}
```
```python
def _find_origin(self, value: str, step_index: int) -> Optional[Tuple[int, str]]:
    cached_origin: Optional[Tuple[int, str]] = self._origin_cache.get(value)
    if cached_origin is not None:
        return cached_origin
    origin: Optional[Tuple[int, str]] = ResponseGrep.find(self.responses_dir, value, step_index)
    if origin is not None:
        self._origin_cache[value] = origin
    return origin
```
- A assinatura de `_find_origin` não muda (continua recebendo `value` e `step_index`,
  ainda necessário para a chamada a `ResponseGrep.find` em cache miss).
- ⚠️ Resultado negativo (`origin is None`) nunca é gravado em `_origin_cache` — é o que
  garante que a correção de origem futura da spec anterior continua valendo (spec
  seção 5, segundo e terceiro casos de borda). Não adicionar um `else` que grave
  `None` na cache.
- Nenhum outro método de `CandidateResolver` muda — `_process_candidate`,
  `_find_slot`, `_check_slot`, `_generate_new_extractor` etc. continuam exatamente
  como estão.

**Critérios de aceite:**
- [x] Duas chamadas a `_find_origin("valor-x", step_index=5)` e depois
  `_find_origin("valor-x", step_index=9)`, com `ResponseGrep.find` retornando
  `(2, "res_0002.json")` na primeira chamada: a segunda chamada retorna
  `(2, "res_0002.json")` sem invocar `ResponseGrep.find` novamente (verificável
  mockando `ResponseGrep.find` e contando invocações).
- [x] `_find_origin("valor-y", step_index=3)` com `ResponseGrep.find` retornando
  `None`, seguido de `_find_origin("valor-y", step_index=8)` com `ResponseGrep.find`
  retornando `(6, "res_0006.json")`: a segunda chamada invoca `ResponseGrep.find` (não
  usa cache, porque a primeira foi negativa) e retorna `(6, "res_0006.json")`.
- [x] Uma terceira chamada `_find_origin("valor-y", step_index=10)` após o cenário
  acima retorna `(6, "res_0006.json")` da cache, sem nova invocação de
  `ResponseGrep.find`.
- [x] `_process_candidate` continua retornando o mesmo `DynamicToken` (mesmo
  `origin_step`, `token_id`, `status`) para qualquer candidato, cacheado ou não — não
  há mudança de comportamento observável em `CandidateResolver.resolve`, só
  eliminação de chamadas redundantes a `ResponseGrep.find`.
