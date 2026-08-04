# Plano de Implementação — Desambiguação de Identidade de Token Dinâmico

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## T01 — `CandidateResolver`: enum `SlotStatus` e cache `_validated_values`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (topo do arquivo, `CandidateResolver.__init__`)

**Contexto:**
As próximas tasks (T02-T05) substituem o reuso hoje feito por
`_reuse_verified_in_memory`/`_reuse_persisted_from_disk` por uma busca de slot que
precisa classificar três resultados possíveis (bateu, não bateu, vago) e de um cache
em memória pra não reexecutar o mesmo extractor a cada step que o referencia dentro da
mesma execução (spec seção 3.2 e 3.4). Esta task só prepara o terreno: nenhum
comportamento observável muda ainda.

**Estado atual:**
```python
import hashlib
import json
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Type
...
class CandidateResolver:
    LOCATION_AGENTS: ClassVar[Dict[TokenLocation, Type[BaseAgent]]] = {
        ...
    }

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
```

**Estado esperado depois:**
```python
import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Type
...
class SlotStatus(str, Enum):
    MATCH = "Match"
    MISMATCH = "Mismatch"
    FREE = "Free"


class CandidateResolver:
    LOCATION_AGENTS: ClassVar[Dict[TokenLocation, Type[BaseAgent]]] = {
        ...
    }

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
```
`SlotStatus` fica no módulo `candidate_resolver.py`, fora da classe (mesmo padrão de
`Enum(str, Enum)` de `TokenLocation`/`AgentType` em `models/session.py`, só que aqui é
um detalhe de implementação interno a este arquivo, não um conceito de `models/`).
⚠️ Nenhum outro atributo/método existente muda de posição ou de valor.

**Critérios de aceite:**
- [x] `from har_reproducer.tracking.candidate_resolver import SlotStatus` funciona;
  `SlotStatus.MATCH.value == "Match"`, `SlotStatus.MISMATCH.value == "Mismatch"`,
  `SlotStatus.FREE.value == "Free"`.
- [x] `CandidateResolver(responses_dir, session_store, llm)._validated_values == {}`
  logo após a construção.
- [x] Nenhum teste/uso existente de `CandidateResolver.__init__` quebra — os quatro
  atributos já existentes (`responses_dir`, `session_store`, `llm`, `extractor_runner`,
  `metadata_store`) continuam com os mesmos valores/tipos (não regressão).
- [x] `py_compile har_reproducer/tracking/candidate_resolver.py` passa sem erro.

## T02 — `CandidateResolver`: `_fork_token_id` — id de fork determinístico e hex-compatível

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (`CandidateResolver`, novo método estático)

**Contexto:**
Quando um slot já ocupado por um valor diferente é encontrado (spec seção 3.1), o
próximo slot a tentar precisa de um `token_id` novo, determinístico entre execuções
(mesma ordem de steps ⇒ mesma sequência de tentativas, spec seção 3.1) e compatível com
`SessionStore.TOKEN_PLACEHOLDER_PATTERN` (`session_store.py:9`,
`r"\{\{extractor:([a-f0-9]+)\}\}"`) e `CurlDependencyParser.DEPENDENCY_PATTERN`
(`curl_dependency_parser.py:7-10`, `[a-z0-9]+`) — ou seja, tem que ser uma string hex.

**Estado atual:**
Não existe. `_derive_token_id` (`candidate_resolver.py:93-95`) só produz o id-base,
sem noção de "tentativa".

**Estado esperado depois:**
```python
@staticmethod
def _fork_token_id(base_token_id: str, attempt: int) -> str:
    return hashlib.md5(f"{base_token_id}:{attempt}".encode("utf-8")).hexdigest()
```
Adicionado logo abaixo de `_derive_token_id` (`candidate_resolver.py:93-95`), mesmo
estilo (`@staticmethod`, `hashlib.md5(...).hexdigest()`). ⚠️ `attempt` é sempre `>= 2`
por convenção de uso (T04) — `attempt == 1` corresponde ao próprio `base_token_id`, sem
passar por esta função; este método não precisa (nem deve) tratar `attempt == 1`.

**Critérios de aceite:**
- [x] `CandidateResolver._fork_token_id("abc123", 2)` retorna uma string que casa
  inteiramente com o regex `^[a-f0-9]+$` (32 caracteres hex, saída de md5).
- [x] `CandidateResolver._fork_token_id("abc123", 2) != CandidateResolver._fork_token_id("abc123", 3)`
  (tentativas diferentes geram ids diferentes).
- [x] `CandidateResolver._fork_token_id("abc123", 2)` retorna o mesmo valor toda vez
  que é chamado com os mesmos argumentos (determinístico, sem estado).
- [x] `CandidateResolver._fork_token_id("x", 2) != CandidateResolver._fork_token_id("y", 2)`
  (bases diferentes geram ids diferentes na mesma tentativa).

## T03 — `CandidateResolver`: `_check_slot` — validação unificada de um slot (memória → disco → execução)

**Depende de:** T01 (`SlotStatus`, `_validated_values`).
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (`CandidateResolver`, novo método; `_reuse_verified_in_memory`/`_reuse_persisted_from_disk` permanecem por enquanto, removidos só na T05)

**Contexto:**
Reúne, num único método reaproveitável tanto pelo id-base quanto por qualquer fork
(spec seção 3.3), a validação que hoje está espalhada entre
`_reuse_verified_in_memory` (não valida valor — a causa do bug) e
`_reuse_persisted_from_disk` (já valida, mas só é chamado para o id-base). A validação
por execução real (`extractor_runner.run_existing`) que `_reuse_persisted_from_disk`
já faz é reaproveitada aqui sem mudança de comportamento; o que muda é que passa a ser
chamada para **qualquer** slot da sequência (T04), e passa a ter um cache em memória
(`_validated_values`) pra não reexecutar o mesmo slot duas vezes na mesma run (spec
seção 3.4).

**Estado atual:**
Não existe como método único — lógica equivalente (sem o cache, e só para o id-base)
está em `_reuse_persisted_from_disk` (`candidate_resolver.py:69-80`):
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

**Estado esperado depois:**
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
⚠️ `self.session_store.set_token(slot_id, result)` é uma chamada nova nesta classe
(antes só `TokenResolver`/`ReplayTokenResolver` chamavam `set_token`) — não requer
nenhuma mudança em `SessionStore` (`session_store.py:14-16`, método já público e sem
pré-condição além de `token_id`/`value` serem `str`). ⚠️ `_mismatch_error`
(`candidate_resolver.py:97-101`) não muda — reaproveitado como está, inclusive para o
ramo do cache em memória (`cached_value` nunca é `None` ali, só é populado dentro do
próprio `if result == candidate.current_value`).

**Critérios de aceite:**
- [x] Slot sem `.meta.json` em disco e sem entrada em `_validated_values`: retorna
  `(SlotStatus.FREE, None)`.
- [x] Slot com `.meta.json`/`.py` em disco cujo extractor retorna exatamente
  `candidate.current_value`: retorna `(SlotStatus.MATCH, None)`; após a chamada,
  `session_store.state.registry[slot_id]` está populado com o `Extractor` carregado,
  `session_store.state.tokens[slot_id] == candidate.current_value`, e
  `self._validated_values[slot_id] == candidate.current_value`.
- [x] Slot com `.meta.json`/`.py` em disco cujo extractor retorna um valor diferente de
  `candidate.current_value`: retorna `(SlotStatus.MISMATCH, <mensagem de erro não
  vazia>)`; `session_store.state.registry` **não** é alterado para esse `slot_id`.
- [x] Chamar `_check_slot` duas vezes seguidas para o mesmo `slot_id` que já bateu
  (`MATCH`) na primeira chamada: a segunda chamada retorna `(SlotStatus.MATCH, None)`
  **sem** invocar `extractor_runner.run_existing` de novo (verificável checando que o
  resultado vem do branch de `cached_value`, não do branch de disco) — não regressão
  de custo (spec seção 3.4).
- [x] Extractor em disco que falha na execução (`extractor_runner.run_existing`
  retorna `None`): retorna `(SlotStatus.MISMATCH, "Persisted extractor failed to
  execute (no output).")` — mesma mensagem que `_mismatch_error(None, ...)` já produz
  hoje (não regressão de comportamento de erro).

## T04 — `CandidateResolver`: `_find_slot` — sequência de tentativas até `MATCH` ou `FREE`

**Depende de:** T02 (`_fork_token_id`), T03 (`_check_slot`).
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (`CandidateResolver`, novo método)

**Contexto:**
Orquestra a sequência determinística de slots (id-base, depois forks) descrita na
spec seção 3.1/3.3: tenta o id-base primeiro; se ocupado por um valor diferente,
avança para o próximo fork; para no primeiro `MATCH` (reaproveita) ou primeiro `FREE`
(vago — candidato a receber um extractor novo). Não há teto de tentativas (spec seção
5) — o laço termina porque `metadata_store.load` eventualmente não encontra nada em
disco para algum fork (nenhum processo anterior gerou tantos forks).

**Estado atual:**
Não existe — a atribuição de `candidate.token_id` hoje é direta e única
(`candidate_resolver.py:49`): `candidate.token_id = self._derive_token_id(candidate.path, candidate.origin_step)`.

**Estado esperado depois:**
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
⚠️ O `initial_error` devolvido quando o slot achado é `FREE` é o erro do **último**
slot ocupado testado (não `None`, exceto quando o próprio id-base já estava `FREE` na
primeira tentativa — nesse caso `last_error` continua `None`, idêntico ao
comportamento de hoje para um candidato genuinamente novo).

**Critérios de aceite:**
- [x] `base_token_id` livre (nenhum slot ocupado): retorna `(base_token_id, None)` na
  primeira iteração, sem chamar `_fork_token_id`.
- [x] `base_token_id` ocupado por um valor igual a `candidate.current_value`: retorna
  `(base_token_id, None)` — comportamento idêntico ao reuso de hoje (não regressão do
  caso comum, sem colisão).
- [x] `base_token_id` ocupado por um valor diferente, nenhum fork existente ainda:
  retorna `(_fork_token_id(base_token_id, 2), <erro do mismatch em base_token_id>)`.
- [x] `base_token_id` ocupado por um valor diferente **e** `_fork_token_id(base_token_id, 2)`
  já ocupado por um terceiro valor diferente de `candidate.current_value`: retorna
  `(_fork_token_id(base_token_id, 3), <erro do mismatch na tentativa 2>)` — a busca
  continua além da primeira tentativa de fork (regressão do caso "dois valores
  diferentes colidindo" coberto, mas o caso de três valores também precisa funcionar).
- [x] `base_token_id` ocupado por um valor diferente, e `_fork_token_id(base_token_id, 2)`
  já ocupado pelo **mesmo** valor de `candidate.current_value`: retorna
  `(_fork_token_id(base_token_id, 2), None)` — reaproveita o fork já existente em vez
  de criar um terceiro desnecessariamente.

## T05 — `CandidateResolver`: `_process_candidate` usa `_find_slot`; remove `_reuse_verified_in_memory`/`_reuse_persisted_from_disk`

**Depende de:** T04 (`_find_slot`).
**Arquivos envolvidos:** `har_reproducer/tracking/candidate_resolver.py` (`CandidateResolver._process_candidate`, remoção de `_reuse_verified_in_memory` e `_reuse_persisted_from_disk`)

**Contexto:**
Ponto de integração final: troca a atribuição direta e sem validação de
`candidate.token_id` pelo resultado de `_find_slot`, e remove os dois métodos que essa
task substitui — fechando o bug relatado na spec (seção 1): um valor diferente que
compartilhava `(path, origin_step)` com um token já resolvido deixa de ser aceito
silenciosamente, e passa a cair num slot novo sem sobrescrever o antigo.

**Estado atual:**
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

def _reuse_verified_in_memory(self, candidate: DynamicToken) -> bool:
    existing: Optional[Extractor] = self.session_store.state.registry.get(candidate.token_id)
    if existing is None or not existing.verified:
        return False
    candidate.status = "Resolved"
    return True

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

**Estado esperado depois:**
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
`_reuse_verified_in_memory` e `_reuse_persisted_from_disk` são **removidos** (toda a
validação que faziam já está em `_check_slot`, chamada de dentro de `_find_slot`).
⚠️ `_generate_new_extractor`/`_register_extractor`/`_derive_token_id`/`_mismatch_error`
(`candidate_resolver.py:82-116`, `93-101`) não mudam — só passam a ser chamados com o
`slot_id` livre encontrado por `_find_slot`, que pode ou não ser o `base_token_id`.

**Critérios de aceite:**
- [ ] `CandidateResolver._reuse_verified_in_memory`/`_reuse_persisted_from_disk` não
  existem mais na classe (`hasattr(CandidateResolver, "_reuse_verified_in_memory") is False`).
- [ ] Candidato cujo valor já foi resolvido antes (mesmo `path`/`origin_step`, mesmo
  valor): `status == "Resolved"`, nenhuma chamada a `_generate_new_extractor` — não
  regressão do caminho de reuso comum.
- [ ] **Caso do bug relatado, reproduzido**: dois candidatos com o mesmo `path`
  (`"header:Sec-Fetch-Dest"`) e o mesmo `origin_step` (`0`), um com
  `current_value="style"` e outro com `current_value="image"`, processados nessa
  ordem — o segundo recebe um `token_id` **diferente** do primeiro
  (`candidate.token_id != <token_id do primeiro>`), `status == "Resolved"` (ou
  `"Unresolved"` se a geração falhar, nunca `"Resolved"` com o extractor do primeiro),
  e o `.py`/`.meta.json` do `token_id` do primeiro candidato **não é sobrescrito**
  (conteúdo idêntico ao de antes de processar o segundo candidato).
- [ ] **Regressão end-to-end**: rodar `uv run python -m har_reproducer.main run --har
  /home/vinicius/Documentos/Trabalho/har-flow-reproducer/arquivos-har/progressofit.har
  --config /home/vinicius/Documentos/Trabalho/har-flow-reproducer/har-reproducer-project/config.json
  --mode main --reset` até o fim: o `req_0004.curl.sh` gerado não deve mais referenciar
  o `token_id` do extractor de `"style"` (`b774bbe7479e9c91042c3f09a2aea7b7`, ou
  qualquer que seja o id-base equivalente nesta nova execução) para os placeholders de
  `image` — o curl do step 4 deve usar um `token_id` próprio, cujo extractor retorna
  `"image"`.
- [ ] `py_compile har_reproducer/tracking/candidate_resolver.py` passa sem erro.

## Correção adicional (fora das tasks originais) — mismatch de identificador em scripts de extractor persistidos

Encontrada durante a implementação da T04, ao escrever os testes manuais de
`_find_slot`/`_check_slot`: um bug pré-existente, anterior a esta branch, e ortogonal à
spec, mas que interferia diretamente na validação de slots (`_check_slot` chama
`extractor_runner.run_existing`, e este bug fazia `run_existing` retornar `None` — falso
`MISMATCH`/erro de execução — para uma fração grande dos `token_id` possíveis).

**Causa raiz**: três pontos do código geram a função Python do extractor com o nome
`extract_{sanitize_identifier(token_id)}` (`BaseAgent.__init__`, usado pelos agents
LLM, e `CandidateResolver._build_literal_extractor`, usado nos extractors literais) —
`sanitize_identifier` prefixava `t_` condicionalmente, só quando o `token_id` (um hash
md5, hex) começava por dígito. Só que `ExtractorRunner._write_extractor_script`
(`reproduction/extractor_runner.py:31-42`), ao persistir o `.py` final em disco, montava
a chamada da função com `safe_token_id=extractor.token_id` **cru** (sem sanitizar). Como
hashes hex começam por dígito em ~62,5% dos casos (10 de 16 símbolos hex são dígitos),
qualquer extractor cujo `token_id` caísse nesse caso definia `extract_t_<hash>` mas era
chamado como `extract_<hash>` — `NameError` dentro do subprocesso, script sai com código
1, `run_existing`/`run` retornam `None` silenciosamente (nunca uma exceção visível).
Confirmado empiricamente construindo um extractor literal com `token_id` começando por
dígito e rodando `ExtractorRunner.run(extractor)` sobre ele antes da correção.

**Correção aplicada**:
- Extraída a lógica de sanitização (antes duplicada implicitamente — `BaseAgent`
  possuía o único método `sanitize_identifier`, mas `CandidateResolver` já o chamava
  de fora como utilitário estático, um cheiro de que não era um conceito de `BaseAgent`)
  para uma classe nova e sem dependências, `IdentifierSanitizer`
  (`har_reproducer/templates/identifier_sanitizer.py`), reexportada em
  `har_reproducer/templates/__init__.py`.
- `BaseAgent.__init__` (`agents/base_agent.py`) passa a chamar
  `IdentifierSanitizer.sanitize(token_id)`; o método `BaseAgent.sanitize_identifier`
  foi removido (sem outros usos restantes).
- `CandidateResolver._build_literal_extractor` (`tracking/candidate_resolver.py`) passa
  a chamar `IdentifierSanitizer.sanitize(candidate.token_id)`.
- `ExtractorRunner._write_extractor_script` (`reproduction/extractor_runner.py`) —
  **o ponto do bug** — passa a chamar
  `safe_token_id=IdentifierSanitizer.sanitize(extractor.token_id)` em vez de
  `extractor.token_id` cru, alinhando o nome usado na chamada com o nome usado na
  definição da função em qualquer `Extractor.code` gerado (agents ou literal).
- `IdentifierSanitizer.sanitize` simplificado após revisão: em vez de prefixar `t_`
  só condicionalmente (`if sanitized[0].isdigit()`), passa a prefixar `t_`
  **incondicionalmente** (`return f"t_{sanitized}" if sanitized else "token"`). O
  único invariante que realmente importa é que definição e chamada da função usem a
  mesma transformação — como os três pontos de consumo sempre passam pelo mesmo
  `IdentifierSanitizer.sanitize`, essa consistência já estava garantida antes; a
  simplificação só remove uma ramificação desnecessária (`isdigit()`), sem mudar
  nenhum contrato observável fora desta classe (o nome final da função é um detalhe
  interno do script gerado, nunca comparado/persistido cru em nenhum outro lugar —
  os arquivos em disco continuam nomeados por `token_id` bruto via `Workspace`,
  função de `safe_token_id` não muda).

**Verificação**: `py_compile` em todos os arquivos tocados; reexecução de
`ExtractorRunner.run(extractor)`/`run_existing` sobre um extractor literal com
`token_id` começando por dígito, confirmando `"style"` retornado corretamente (antes:
`None`); reexecução dos scripts de teste manuais da T03/T04 após a simplificação,
todos os critérios de aceite continuam passando.
