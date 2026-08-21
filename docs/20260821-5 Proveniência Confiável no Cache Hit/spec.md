# Spec — Proveniência Confiável no Cache Hit

## 0. Sumário

`CurlGenerator` decide se um `.curl.sh` mostra a proveniência de um token dinâmico
("origin location undetermined — using literal captured value") olhando um campo do
próprio `DynamicToken` (`origin_location`) que só é preenchido no caminho de **criação**
de um extrator novo. Todo token cujo extrator já existia (extrator persistido em disco de
uma execução anterior, ou já registrado nesta mesma sessão por um step anterior) pula esse
preenchimento e o campo fica `None` — fazendo `CurlGenerator` mentir "undetermined" mesmo
quando o extrator é um `HeaderAgent`/`CSSAgent`/`RegexAgent` que sabe exatamente de onde o
valor vem. Medido no relatório de 17/08 (§3.3): de 757 comentários "undetermined" em 865
linhas de dependência, **540 (71%) referenciam um extrator determinístico persistido** —
não um `LiteralAgent`. A correção move a decisão para a fonte que já carrega esse fato de
forma estável: o `agent_type` do `Extractor` persistido, em vez do `origin_location`
transiente do candidato.

### Glossário

| termo | significado nesta spec |
|---|---|
| **cache hit** | Quando `CandidateResolver._process_candidate` encontra que o slot do token já tem um `Extractor` no `session_store.state.registry` (seja porque outro step desta mesma execução já o criou, seja porque `_check_persisted_slot` carregou e revalidou um extrator salvo de uma execução anterior) — nesse caso o método retorna sem passar por `_generate_new_extractor`. |
| **proveniência determinística** | Um `Extractor` cujo `agent_type` não é `LiteralAgent` nem `LiteralFallbackAgent` — significa que um agente encontrou e verificou uma regra de extração real (header, cookie, JSONPath, CSS, regex) a partir da resposta de origem. |
| **`origin_location`** | Campo de `DynamicToken` (`Optional[TokenLocation]`), preenchido por `TokenLocationDetector.find` só dentro de `_generate_new_extractor`. Usado hoje por `AgentFactory` para escolher qual agente tentar, e por `CurlGenerator` para decidir a frase de proveniência do comentário — são dois usos independentes que esta spec separa. |

---

## 1. Objetivo

### 1.1 O problema

`CurlGenerator._origin_status` (`reproduction/curl_generator.py:82-87`):
```python
@staticmethod
def _origin_status(token: DynamicToken) -> Optional[OriginStatusPhrase]:
    if token.origin_location is None:
        return OriginStatusPhrase.UNDETERMINED
    if token.extraction_exhausted:
        return OriginStatusPhrase.EXTRACTION_EXHAUSTED
    return None
```
decide a frase olhando `token.origin_location`/`token.extraction_exhausted` — campos que
só são escritos em `CandidateResolver._generate_new_extractor`
(`tracking/candidate_resolver.py:148-157`), o caminho de **criação**. Todo `DynamicToken`
novo nasce com `origin_location=None` (default do modelo,
`models/session.py:56`); se o slot já existir no registry, `_process_candidate` devolve o
candidato em `"Resolved"` sem tocar nesses campos:
```python
# tracking/candidate_resolver.py:69-71
if self.session_store.state.registry.get(slot_id) is not None:
    candidate.status = "Resolved"
    return candidate
```
Resultado: **todo** token resolvido por cache hit (a maioria, numa sessão de replay longa
ou num fluxo com o mesmo header repetido em vários steps) mostra "undetermined", mesmo
quando o extrator por trás dele é um `HeaderAgent` que sabe exatamente que o valor vem do
header `Set-Cookie` da resposta do step 12.

### 1.2 Custo de não corrigir

Cosmético para a execução — `{{extractor:...}}` já aponta para o extrator certo
independentemente do texto do comentário — mas o comentário é a única forma prática de
auditar proveniência num `.curl.sh` sem abrir o `.meta.json` ao lado. Ele hoje convive, no
mesmo arquivo, com a linha `[Unresolved N]` (auditoria verdadeira de token sem origem
alguma) — fazendo uma mentira de "não sei de onde vem" parecer tão grave quanto um caso
real de origem desconhecida. Qualquer investigação futura de proveniência (itens 4 e 5 do
backlog de 17/08) fica mais cara enquanto esse ruído existir.

### 1.3 Fora de escopo

- **Item 4** (âncoras do `optimize` nunca testadas para remoção) — usa a proveniência do
  `.curl.sh` como uma das entradas, mas essa etapa não altera `compute_smart_schedule` nem
  `ReplayOptimizer`.
- Mudar o texto das duas frases (`OriginStatusPhrase.UNDETERMINED`/`EXTRACTION_EXHAUSTED`)
  — só a condição que dispara cada uma muda, não a redação.
- Persistir `origin_location`/`extraction_exhausted` em `Extractor` — a spec resolve o
  problema sem precisar disso (§3.1).

---

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `har_reproducer/models/session.py` — `Extractor`, `DynamicToken`, `AgentType`

```python
class AgentType(str, Enum):
    COOKIE = "CookieAgent"
    HEADER = "HeaderAgent"
    JSONPATH = "JSONPathAgent"
    CSS = "CSSAgent"
    REGEX = "RegexAgent"
    LITERAL = "LiteralAgent"
    LITERAL_FALLBACK = "LiteralFallbackAgent"

class Extractor(BaseModel):
    token_id: str
    code: str
    verified: bool = False
    agent_type: AgentType
    origin_step: Optional[int] = None
    ...

class DynamicToken(BaseModel):
    ...
    origin_location: Optional[TokenLocation] = None
    ...
    extraction_exhausted: bool = False
```
`Extractor.agent_type` é gravado uma única vez, na criação (`_build_literal_extractor`
ou o retorno de `agent.run_tdd_loop`), e persiste em disco (`.meta.json`) e no
`session_store.state.registry` — ao contrário de `DynamicToken.origin_location`, que é
recriado do zero (e não recalculado) a cada `DynamicToken` novo instanciado para cada
step. `AgentType.LITERAL` corresponde exatamente a "origin_location era `None`" e
`AgentType.LITERAL_FALLBACK` corresponde exatamente a "origin_location foi encontrado mas
a extração esgotou tentativas" — são os dois casos que hoje disparam as frases de aviso.

### `CandidateResolver._process_candidate`/`_generate_new_extractor` — `tracking/candidate_resolver.py:47-73,148-157`

```python
def _process_candidate(self, candidate: DynamicToken, step_index: int) -> DynamicToken:
    ...
    slot_id, initial_error = self._find_slot(base_token_id, candidate)
    candidate.token_id = slot_id

    if self.session_store.state.registry.get(slot_id) is not None:
        candidate.status = "Resolved"
        return candidate

    return self._generate_new_extractor(candidate, initial_error)

def _generate_new_extractor(self, candidate: DynamicToken, initial_error: Optional[str]) -> DynamicToken:
    candidate.status = "UnderReview"
    response_sample: Optional[Dict[str, Any]] = self.discovery_corpus.response(candidate.origin_step)
    if response_sample is None:
        return candidate
    candidate.origin_location = TokenLocationDetector.find(candidate.extracted_value, response_sample)
    self._register_extractor(candidate, response_sample, initial_error)
    return candidate
```
Confirmado por leitura completa de `agents/construction/agent_factory.py`: `origin_location`
e `extraction_exhausted` só são lidos dentro deste mesmo caminho de criação
(`AgentFactory.create`, que só é chamado por `_generate_extractor`, chamado só por
`_register_extractor`, chamado só por `_generate_new_extractor`). Nenhum consumidor lê
esses dois campos no caminho de cache hit — a única leitura fora da criação é
`CurlGenerator._origin_status` (§2 abaixo). Isso significa que preencher
`origin_location` artificialmente no cache hit (a opção descartada, §3.2) não teria
nenhum outro efeito além de alimentar esse método.

### `CurlGenerator` — `reproduction/curl_generator.py` (arquivo inteiro relevante)

```python
class CurlGenerator:
    def __init__(self, curl_token_comment: CurlTokenComment) -> None:
        self.curl_token_comment: CurlTokenComment = curl_token_comment

    def _token_comments(self, tokens: List[DynamicToken]) -> List[str]:
        lines: List[str] = [
            self.curl_token_comment.format_dependency_line(
                token.token_id, token.origin_step, self._origin_status(token)
            )
            for token in tokens if token.status == "Resolved"
        ]
        ...

    @staticmethod
    def _origin_status(token: DynamicToken) -> Optional[OriginStatusPhrase]:
        if token.origin_location is None:
            return OriginStatusPhrase.UNDETERMINED
        if token.extraction_exhausted:
            return OriginStatusPhrase.EXTRACTION_EXHAUSTED
        return None
```
Instanciado em `EngineFactory._build_tracker`
(`engines/construction/engine_factory.py:118-123`), que já tem `session_store` no escopo
local (passado a `_build_tracker` como parâmetro e usado para construir
`PlaceholderApplier(session_store)` na mesma linha) — a injeção de mais uma dependência
aqui não exige nenhuma nova construção de objeto, só passar o que já existe.

### Medição de que os golden fixtures atuais não escondem o defeito nem o corrigem

Busca em todo `tests/golden/`: nenhum extrator com `agent_type` diferente de
`LiteralAgent`/`LiteralFallbackAgent` aparece referenciado em mais de um `.curl.sh` — ou
seja, nenhum fixture hoje exercita um cache hit sobre um extrator determinístico. As 15
ocorrências existentes de "undetermined" em `tests/golden/*/curls/req_0006.curl.sh` são
todas `LiteralAgent` genuíno (conferido via `.meta.json`), então **nenhum golden precisa
ser regenerado** por esta correção — o defeito só se manifesta num fluxo com reuso de
token entre steps, que os fixtures atuais não cobrem. A cobertura nova entra via teste
unitário (§3.1).

---

## 3. Decisões de arquitetura

### 3.1 — `CurlGenerator` deriva a frase do `agent_type` do extrator, não do candidato

**Estado esperado:**
```python
class CurlGenerator:
    def __init__(self, curl_token_comment: CurlTokenComment, session_store: SessionStore) -> None:
        self.curl_token_comment: CurlTokenComment = curl_token_comment
        self.session_store: SessionStore = session_store

    def _token_comments(self, tokens: List[DynamicToken]) -> List[str]:
        lines: List[str] = [
            self.curl_token_comment.format_dependency_line(
                token.token_id, token.origin_step, self._origin_status(token)
            )
            for token in tokens if token.status == "Resolved"
        ]
        ...

    def _origin_status(self, token: DynamicToken) -> Optional[OriginStatusPhrase]:
        extractor: Optional[Extractor] = self.session_store.state.registry.get(token.token_id)
        assert extractor is not None
        if extractor.agent_type == AgentType.LITERAL:
            return OriginStatusPhrase.UNDETERMINED
        if extractor.agent_type == AgentType.LITERAL_FALLBACK:
            return OriginStatusPhrase.EXTRACTION_EXHAUSTED
        return None
```
`_origin_status` deixa de ser `@staticmethod` (passa a ler `self.session_store`). O
`assert` reflete uma garantia já existente no código, não uma checagem nova: todo token
com `status == "Resolved"` (o único filtro que chega a `_origin_status`) teve seu
`token_id` gravado no registry antes de virar `"Resolved"` — tanto no cache hit
(`_process_candidate:69-71`, que só marca `"Resolved"` depois de confirmar
`registry.get(slot_id) is not None`) quanto na criação
(`_register_extractor:173-186`, que grava no registry e só marca `"Resolved"` se
`new_extractor is not None`). Não existe hoje nenhum caminho que produza `status ==
"Resolved"` sem essa gravação.

**Por que esta opção, e não preencher `origin_location` também no cache hit:** a
alternativa mínima seria fazer `_process_candidate` também chamar
`TokenLocationDetector.find`/marcar `extraction_exhausted` no ramo de cache hit,
mantendo `CurlGenerator` como está. Descartada porque (a) exigiria reexecutar
`TokenLocationDetector.find` contra a resposta de origem a cada cache hit, um trabalho que
a criação já fez uma vez e que o cache hit existe justamente para evitar; e (b) como §2
mostrou, `origin_location`/`extraction_exhausted` não têm nenhum outro consumidor fora da
criação — preencher esses campos só para alimentar `CurlGenerator` duplicaria, em dois
lugares (`DynamicToken.origin_location` e `Extractor.agent_type`), uma informação que já
existe de forma estável e correta em um só. Mover a leitura para `agent_type` elimina a
classe do problema: qualquer caminho futuro que chegue a `status == "Resolved"` sem passar
por `_generate_new_extractor` (não só o cache hit de hoje) já sai correto, porque a fonte
é o `Extractor` persistido, não um campo que precisa ser lembrado de preencher em cada
caminho novo.

### 3.2 — `EngineFactory` passa `session_store` para `CurlGenerator`

**Estado atual:**
```python
# engines/construction/engine_factory.py:118-123
curl_token_comment: CurlTokenComment = CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH)
return TokenTracker(
    BaselineDiff(), candidate_resolver, PlaceholderApplier(session_store), CurlGenerator(curl_token_comment),
    flow_vocabulary,
)
```
**Estado esperado:**
```python
curl_token_comment: CurlTokenComment = CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH)
return TokenTracker(
    BaselineDiff(), candidate_resolver, PlaceholderApplier(session_store),
    CurlGenerator(curl_token_comment, session_store), flow_vocabulary,
)
```
`session_store` já é parâmetro de `_build_tracker` — nenhuma construção nova, só repassar.

---

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `reproduction/curl_generator.py` → `CurlGenerator` | ganha `session_store` no construtor; `_origin_status` deixa de ser `@staticmethod`, passa a ler `Extractor.agent_type` do registry em vez de `DynamicToken.origin_location`/`extraction_exhausted` (§3.1) |
| `engines/construction/engine_factory.py` → `_build_tracker` | repassa `session_store` para `CurlGenerator` (§3.2) |
| `tests/unit/test_curl_generator.py` | todos os testes que hoje constroem `DynamicToken` com `origin_location`/`extraction_exhausted` passam a montar um `SessionStore` com o `Extractor` correspondente no registry; teste novo cobrindo o cenário de cache hit (token `"Resolved"` cujo `Extractor` é `HeaderAgent` não mostra frase alguma) |

`DynamicToken.origin_location`/`extraction_exhausted` continuam existindo no modelo e
continuam sendo escritos/lidos exatamente como hoje dentro de `_generate_new_extractor`/
`AgentFactory` — nenhuma mudança ali.

---

## 5. Casos de borda e comportamento de erro

**5.1 Token `"Resolved"` sem entrada no registry.** Não deveria acontecer (ver garantia em
§3.1) — o `assert` torna essa violação de invariante visível (crash com traceback) em vez
de silenciosamente mostrar "undetermined" errado de novo. Se algum caminho futuro
conseguir produzir esse estado, o teste vai crashar apontando exatamente onde.

**5.2 `Extractor.agent_type == AgentType.LITERAL_FALLBACK` vindo de um cache hit.** Mesmo
comportamento de hoje na criação: mostra "extraction exhausted" — o cache hit só troca
*onde* a informação é lida, não decide nada diferente para esse caso.

**5.3 Nenhum golden precisa mudar** (§2) — confirmado por busca em todo `tests/golden/`.
Se a implementação encontrar algum golden que mude mesmo assim, é sinal de que a busca
desta spec ficou incompleta — parar e avisar antes de regenerar.

---

## 6. Referência

Toda alteração de código desta spec segue [[guia-de-estilo]]. A decisão de mover a leitura
para `Extractor.agent_type` em vez de duplicar o dado em `DynamicToken` segue o princípio
de fonte única de verdade já aplicado em outras partes do projeto (ex.: `Extractor`
persistido é a fonte de verdade de `captured_value`, não o candidato transiente).
