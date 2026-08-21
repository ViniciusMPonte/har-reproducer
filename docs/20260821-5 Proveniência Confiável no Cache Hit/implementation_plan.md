# Plano de Implementação — Proveniência Confiável no Cache Hit

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `CurlGenerator`: `_origin_status` lê `Extractor.agent_type` do registry, não `DynamicToken.origin_location`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/reproduction/curl_generator.py` (`CurlGenerator.__init__`,
`CurlGenerator._origin_status`), `tests/unit/test_curl_generator.py` (todos os testes)

**Contexto:**
`_origin_status` hoje decide a frase de proveniência olhando `token.origin_location`/
`token.extraction_exhausted` — campos que só são escritos no caminho de criação de um
extrator novo (`CandidateResolver._generate_new_extractor`). Todo token resolvido por
cache hit (extrator já existia no `session_store.state.registry`, desta sessão ou de uma
execução anterior persistida) nunca passa por ali, então esses campos ficam no default
(`None`/`False`) e o comentário mostra "undetermined" mesmo quando o extrator é
determinístico. A correção move a leitura para `Extractor.agent_type`, que é escrito uma
única vez na criação e persiste — a mesma fonte, seja o token novo ou reaproveitado.

**Estado atual:**
```python
# reproduction/curl_generator.py
class CurlGenerator:
    def __init__(self, curl_token_comment: CurlTokenComment) -> None:
        self.curl_token_comment: CurlTokenComment = curl_token_comment

    @staticmethod
    def _origin_status(token: DynamicToken) -> Optional[OriginStatusPhrase]:
        if token.origin_location is None:
            return OriginStatusPhrase.UNDETERMINED
        if token.extraction_exhausted:
            return OriginStatusPhrase.EXTRACTION_EXHAUSTED
        return None
```

**Estado esperado depois:**
```python
from har_reproducer.models import AgentType, DynamicToken, Extractor, StepRequest
from har_reproducer.session import SessionStore

class CurlGenerator:
    def __init__(self, curl_token_comment: CurlTokenComment, session_store: SessionStore) -> None:
        self.curl_token_comment: CurlTokenComment = curl_token_comment
        self.session_store: SessionStore = session_store

    def _origin_status(self, token: DynamicToken) -> Optional[OriginStatusPhrase]:
        extractor: Optional[Extractor] = self.session_store.state.registry.get(token.token_id)
        assert extractor is not None
        if extractor.agent_type == AgentType.LITERAL:
            return OriginStatusPhrase.UNDETERMINED
        if extractor.agent_type == AgentType.LITERAL_FALLBACK:
            return OriginStatusPhrase.EXTRACTION_EXHAUSTED
        return None
```
`_token_comments` chama `self._origin_status(token)` — já é uma chamada de instância
(`self.curl_token_comment.format_dependency_line(..., self._origin_status(token))`), não
precisa mudar.

⚠️ O `assert` reflete uma garantia já existente (spec §3.1): todo token com `status ==
"Resolved"` — o único filtro que chega a `_origin_status`, em `_token_comments` — teve seu
`token_id` gravado no registry antes de virar `"Resolved"`, tanto no cache hit quanto na
criação. Não substituir por um `if extractor is None: return UNDETERMINED` silencioso —
isso esckonderia a mesma classe de bug que esta task corrige.
⚠️ `DynamicToken.origin_location`/`extraction_exhausted` **não mudam** — continuam sendo
escritos e lidos exatamente como hoje dentro de `_generate_new_extractor`/`AgentFactory`.
Esta task só troca o que `CurlGenerator` lê para decidir o comentário.

**Critérios de aceite (TDD — escrever os testes abaixo, confirmar que falham pelo motivo
certo contra o código atual, só então implementar):**
- [x] Todo teste de `tests/unit/test_curl_generator.py` que hoje monta um `DynamicToken`
  com `origin_location`/`extraction_exhausted` passa a montar também um `SessionStore`
  com o `Extractor` correspondente em `session_store.state.registry[token_id]`
  (`agent_type=AgentType.LITERAL` no lugar de `origin_location=None`,
  `agent_type=AgentType.LITERAL_FALLBACK` no lugar de `extraction_exhausted=True`,
  qualquer outro `AgentType` no lugar de um `origin_location` não-`None` sem
  `extraction_exhausted`), e passa esse `SessionStore` para `CurlGenerator(...)`.
- [x] Teste novo: um token com `status == "Resolved"` cujo `Extractor` no registry tem
  `agent_type=AgentType.HEADER` produz uma linha `# [Token ... comes from response of
  step NNNN]` **sem** nenhuma frase de proveniência anexada (nem "undetermined" nem
  "extraction exhausted") — este é o cenário de cache hit sobre extrator determinístico
  que a spec descreve como o bug (§1.1), e que nenhum teste cobre hoje.
- [x] Teste novo: um token `"Resolved"` cujo `Extractor` tem `agent_type=LITERAL_FALLBACK`
  continua produzindo "extraction exhausted" — não-regressão do caso que já existia,
  agora vindo do registry em vez de `extraction_exhausted=True` no candidato.
- [x] Não-regressão: `test_generate_without_commentable_tokens_reports_them_as_unresolved`,
  `test_generate_appends_unresolved_line_after_the_dependency_lines` e os demais testes
  que não giram em torno da frase de proveniência continuam passando com a nova
  assinatura de `CurlGenerator`.

---

## [T02] — `EngineFactory._build_tracker`: repassa `session_store` para `CurlGenerator`

**Depende de:** T01 (a assinatura nova de `CurlGenerator.__init__` já precisa existir).
**Arquivos envolvidos:** `har_reproducer/engines/construction/engine_factory.py` (`_build_tracker`)

**Contexto:**
`_build_tracker` já recebe `session_store` como parâmetro e o usa para construir
`PlaceholderApplier(session_store)` na mesma chamada de `TokenTracker(...)`. Depois de T01,
`CurlGenerator(curl_token_comment)` deixa de compilar (assinatura exige `session_store`) —
esta task só repassa o que já está no escopo, sem nenhuma construção nova.

**Estado atual:**
```python
# engines/construction/engine_factory.py:118-123
curl_token_comment: CurlTokenComment = CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH)
return TokenTracker(
    BaselineDiff(), candidate_resolver, PlaceholderApplier(session_store), CurlGenerator(curl_token_comment),
    flow_vocabulary,
)
```

**Estado esperado depois:**
```python
curl_token_comment: CurlTokenComment = CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH)
return TokenTracker(
    BaselineDiff(), candidate_resolver, PlaceholderApplier(session_store),
    CurlGenerator(curl_token_comment, session_store), flow_vocabulary,
)
```

**Critérios de aceite:**
- [x] `uv run python -c "import har_reproducer.engines.construction.engine_factory"` (ou
  equivalente compile-check) não levanta `TypeError` de assinatura.
- [x] `uv run pytest tests/unit -q` continua 100% verde (nenhum teste unitário de
  `EngineFactory` monta `CurlGenerator` diretamente — a task não deveria quebrar nada ali).
- [x] Não-regressão: `uv run pytest --runslow -q` (suíte completa, inclusive golden trees)
  passa sem nenhuma árvore precisando de regeneração — confirmado na spec (§2/§5.3) que
  nenhum fixture atual exercita o cache hit sobre extrator determinístico.
