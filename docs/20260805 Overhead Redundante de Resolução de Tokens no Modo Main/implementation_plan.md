# Plano de Implementação — Overhead Redundante de Resolução de Tokens no Modo Main

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `TokenResolver`: `resolve_all()` ganha `force`, pula tokens já resolvidos por padrão

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/token_resolver.py` (`TokenResolver.resolve_all`)

**Contexto:**
`resolve_all()` é chamado uma vez por step em `main` (`Engine.USES_NETWORK = True`) e,
incondicionalmente, dentro de `handle_recovery` em qualquer modo. Hoje ele reexecuta o
extractor de **todo** token `verified` com `origin_step` no `registry`, mesmo quando o
valor daquele `token_id` já está resolvido e presente em `session_store.state.tokens`
de uma chamada anterior — trabalho redundante que cresce com o tamanho do registry a
cada step (spec seção 1). Isso é seguro de eliminar porque `res_{origin_step:04d}.json`
nunca é reescrito depois de criado (spec seção 1 e seção 2, "Persistência de responses
durante run/dry") — reexecutar o mesmo extractor sobre o mesmo arquivo produz,
deterministicamente, o mesmo valor.

**Estado atual:**
```python
def resolve_all(self) -> None:
    for token_id, extractor in self.session_store.state.registry.items():
        if self._should_refresh_token(extractor):
            self._refresh_token(token_id, extractor)

def _should_refresh_token(self, extractor: Extractor) -> bool:
    return extractor.verified and extractor.origin_step is not None

def _refresh_token(self, token_id: str, extractor: Extractor) -> None:
    if not (self.responses_dir / f"res_{extractor.origin_step:04d}.json").exists():
        return

    try:
        value: Optional[str] = self.extractor_runner.run(extractor, self.responses_dir)
    except Exception as e:
        print(f"Failed to refresh token '{token_id}': {e}")
        return

    if value:
        self.session_store.set_token(token_id, value)
```
- Nenhum parâmetro em `resolve_all()`; nenhum filtro por "já resolvido" antes de chamar
  `_should_refresh_token`/`_refresh_token`.
- `_refresh_token` só chama `set_token` em caso de sucesso (linha final) — um
  `token_id` sem valor em `session_store.state.tokens` é sinal de que ainda não foi
  resolvido com sucesso nenhuma vez (extractor novo, ou falha silenciosa anterior).

**Estado esperado depois:**
- Novo parâmetro `force: bool = False`:
  ```python
  def resolve_all(self, force: bool = False) -> None:
      for token_id, extractor in self.session_store.state.registry.items():
          if not force and token_id in self.session_store.state.tokens:
              continue
          if self._should_refresh_token(extractor):
              self._refresh_token(token_id, extractor)
  ```
- `_should_refresh_token` e `_refresh_token` não mudam — o novo filtro é uma checagem
  adicional **antes** deles, não uma substituição.
- Comportamento com `force=True`: idêntico ao `resolve_all()` de hoje (reprocessa
  todo o registry, sem exceção) — usado por `handle_recovery` (T02).
- Comportamento com `force=False` (novo padrão, usado pelo call site por-step em
  `Engine._process_entry`, que não muda nesta task): só processa `token_id` que ainda
  **não** está em `session_store.state.tokens` — ou seja, tokens recém-adicionados ao
  `registry` neste step via `CandidateResolver._register_extractor`
  (`candidate_resolver.py:150-162`, que não chama `set_token`), ou tokens cuja
  resolução anterior falhou silenciosamente (seção 5 da spec, "borda").
- ⚠️ A checagem `token_id in self.session_store.state.tokens` deve vir **antes** de
  `_should_refresh_token`, não depois — o objetivo é pular o trabalho de
  `_refresh_token` inteiro (subprocess + reescrita de arquivo), não só decidir se
  chama `set_token` no fim.
- ⚠️ Não usar `.get(token_id)` para a checagem — um valor de token pode legitimamente
  ser string vazia em algum cenário futuro; `in` é a checagem correta de presença,
  igual ao padrão já usado em `SessionStore._resolve_token_placeholder`
  (`session_store.py:39`).

**Critérios de aceite:**
- [x] `resolve_all()` chamado sem argumento (`force` no valor padrão) não reexecuta o
  extractor de um `token_id` já presente em `session_store.state.tokens` — verificável
  isolando `ExtractorRunner.run`/`_refresh_token` com um spy em teste manual, ou por
  leitura do fluxo (guard clause antes de `_should_refresh_token`).
- [x] `resolve_all()` chamado sem argumento continua processando (chamando
  `_refresh_token`) qualquer `token_id` que esteja no `registry` mas ainda não em
  `session_store.state.tokens` — nenhuma regressão para tokens recém-registrados.
- [x] `resolve_all(force=True)` reprocessa **todo** o registry que satisfaz
  `_should_refresh_token`, independente de já estar em `session_store.state.tokens` —
  comportamento idêntico ao `resolve_all()` de antes desta task, sem exceção.
- [x] Um `token_id` cuja `_refresh_token` falhou (exceção capturada ou arquivo de
  origem inexistente) continua fora de `session_store.state.tokens` e, portanto,
  continua sendo reprocessado em toda chamada seguinte com `force=False` — nenhuma
  mudança nesse comportamento de retry implícito.
- [x] `python -m py_compile har_reproducer/tracking/token_resolver.py` sem erros.

---

## [T02] — `Engine.handle_recovery`: chama `resolve_all(force=True)`

**Depende de:** T01 (o parâmetro `force` precisa existir em `TokenResolver.resolve_all`).
**Arquivos envolvidos:** `har_reproducer/engines/engine.py` (`Engine.handle_recovery`)

**Contexto:**
Com o novo padrão de `resolve_all()` (T01, `force=False` pula tokens já resolvidos),
o único call site que precisa continuar reprocessando o registry inteiro,
incondicionalmente, é `handle_recovery` — acionado em recuperação de 400/401
(`StepRetryPolicy.RECOVERABLE_STATUS_CODES`, `step_retry_policy.py:8`). Sem essa
mudança, `handle_recovery` herdaria o novo comportamento padrão (pular tokens já
resolvidos) por chamar `resolve_all()` sem argumento — uma mudança de comportamento
não coberta pela spec, que explicitamente mantém esse caminho intocado (spec seção
3.1, "Por que `handle_recovery` mantém `force=True`").

**Estado atual:**
```python
def handle_recovery(self, response: StepResponse) -> bool:
    if response.status_code not in self.retry_policy.RECOVERABLE_STATUS_CODES:
        return False

    print(
        f"Detected {response.status_code}. "
        f"Attempting deterministic recovery (token refresh)..."
    )
    self.token_resolver.resolve_all()
    return True
```

**Estado esperado depois:**
```python
def handle_recovery(self, response: StepResponse) -> bool:
    if response.status_code not in self.retry_policy.RECOVERABLE_STATUS_CODES:
        return False

    print(
        f"Detected {response.status_code}. "
        f"Attempting deterministic recovery (token refresh)..."
    )
    self.token_resolver.resolve_all(force=True)
    return True
```
- Única linha alterada: `self.token_resolver.resolve_all()` →
  `self.token_resolver.resolve_all(force=True)`.
- Nenhuma outra lógica de `handle_recovery` muda (condição de status code, prints,
  retorno).
- `Engine._process_entry` **não** é tocado nesta task — a chamada por step
  (`if self.USES_NETWORK: self.token_resolver.resolve_all()`, `engine.py:110-111`) já
  está correta como está: sem argumento, herda o novo padrão `force=False` de T01.

**Critérios de aceite:**
- [x] `handle_recovery` chama `self.token_resolver.resolve_all(force=True)` — todo o
  registry é reprocessado na recuperação de 400/401, mesmo para `token_id` já presente
  em `session_store.state.tokens`, exatamente como o comportamento anterior a T01.
- [x] `handle_recovery` continua retornando `True`/`False` na mesma condição
  (`response.status_code` em `RECOVERABLE_STATUS_CODES`) — nenhuma mudança de fluxo de
  controle.
- [x] `Engine._process_entry` continua chamando `resolve_all()` sem argumento (não
  `force=True`) — não-regressão: o call site por-step usa o novo padrão de T01, só
  `handle_recovery` é forçado.
- [x] `python -m py_compile har_reproducer/engines/engine.py` sem erros.
