# Spec — Reaproveitamento de Extractors entre Execuções e Detecção de Tokens Estáticos

> Fonte única de verdade para gerar o `implementation_plan.md` desta etapa. Assume que
> quem escreve o plano não participou da conversa que chegou a estas decisões — tudo
> que é necessário para entender o "porquê" e o "o quê" está aqui, sem depender de nada
> além do código-fonte atual do projeto (`har_reproducer/`), do `guia_de_estilo.md` e do
> `spec.md` (ferramenta de replay, já implementada) desta mesma pasta.

## 1. Objetivo

Hoje, cada invocação do CLI (`run --mode main`/`dry`) começa com um
`SessionStore.state.registry` vazio e regenera, do zero, **todo** extractor para
**todo** token dinâmico detectado — mesmo que um extractor idêntico e funcional já
tenha sido gerado e persistido em disco por uma execução anterior contra o mesmo
`output_dir`. Isso tem dois custos: (a) chamadas de LLM redundantes a cada nova
execução, e (b) nenhum mecanismo para corrigir um extractor que passou a falhar sem
regenerá-lo do zero.

Esta spec cobre duas mudanças relacionadas, ambas apoiadas no mesmo mecanismo de
persistência (metadados em JSON ao lado do `.py` do extractor):

1. **Reaproveitamento entre execuções**: antes de gerar um extractor novo,
   `CandidateResolver` verifica se já existe um extractor persistido em disco para
   aquele `token_id` e se ele ainda é válido contra o response atual. Se for válido,
   reaproveita sem chamar o agente/LLM. Se existir mas falhar, tenta **corrigir**
   (chama o agente de novo, passando o erro observado como contexto) em vez de gerar do
   zero.
2. **Detecção de token "falso dinâmico"**: um contador nos metadados registra, ao
   longo de execuções repetidas de `replay`, se o valor resolvido por um extractor
   **nunca mudou**. Depois de 5 resoluções válidas seguidas com o mesmo valor, o token é
   provavelmente estático (foi classificado como dinâmico por engano, ver seção 2 sobre
   `BaselineDiff`) — isso vira um **aviso em comentário** no `req_XXXX.curl.sh`
   correspondente, não uma ação automática.

Fora de escopo (feature futura, não implementar agora): descartar o extractor
automaticamente e substituir o placeholder por um valor literal no curl quando o token
for confirmado como estático.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

- **`CandidateResolver._process_candidate`** (`tracking/candidate_resolver.py:37-62`) —
  fluxo atual, por candidato:
  1. `origin = ResponseGrep.find(responses_dir, candidate.current_value)`; se `None`,
     `status = "NotFound"`, retorna.
  2. `origin_step = origin[0]`; `candidate.token_id = md5(f"{path}:{origin_step}")`
     (`_derive_token_id`) — **determinístico**: mesmo `path` + mesmo `origin_step` em
     execuções diferentes geram o mesmo `token_id`.
  3. `existing = session_store.state.registry.get(token_id)`; se existir e
     `existing.verified`, `status = "Resolved"`, retorna — **isto já é um cache, mas só
     dentro do processo atual** (dedupe entre steps da mesma run; ver seção 6 da
     conversa anterior/registry). `session_store` é criado do zero em todo
     `Engine.__init__` (`engines/engine.py:42`), então esse cache nunca sobrevive entre
     invocações do CLI.
  4. Senão: `status = "UnderReview"`; carrega `response_sample` de
     `responses_dir/res_{origin_step:04d}.json`; se não existir, retorna sem gerar
     nada; detecta `origin_location`; chama `_register_extractor`.
  5. `_register_extractor` → `_generate_extractor` → escolhe `Agent` por
     `TokenLocation` (`LOCATION_AGENTS`) → `agent.run_tdd_loop(origin_step=...)`. Se
     retornar `Extractor`, grava em `registry[token_id]`, `status = "Resolved"`; senão
     `status = "Unresolved"`.

- **`BaseAgent.run_tdd_loop(max_attempts=None, origin_step=None)`**
  (`agents/base_agent.py:124-156`) — itera estratégias (`deterministic_strategies()` +
  `MAX_LLM_ATTEMPTS = 5` tentativas de LLM). A cada tentativa: `generate_code(last_error)`
  → `_verify_code(code)` (escreve script temporário via
  `ExtractorTemplate.render_temp_script`, executa em subprocess, compara `stdout` com
  `expected_value`). `last_error` começa em `None` **sempre**, é reatribuído
  internamente a cada tentativa fracassada (`last_error = error`) — **não existe hoje
  parâmetro para semear esse loop com um erro conhecido de antemão**. Em sucesso,
  retorna `Extractor(token_id=, code=, verified=True, agent_type=AgentType(nome da
  classe), origin_step=, temp_file_path=)`. Em esgotamento de tentativas, limpa o
  arquivo temporário e retorna `None`.

- **`ExtractorRunner`** (`reproduction/extractor_runner.py`) —
  - `run(extractor: Extractor) -> Optional[str]`: **reescreve** `extractors/extract_
    {token_id}.py` a partir de `extractor.code` (`_write_extractor_script`, via
    `ExtractorTemplate.render_script`), executa, retorna `stdout` ou `None` em qualquer
    falha (subprocess, timeout, `returncode != 0`).
  - `run_existing(token_id, response_override_dir=None) -> Optional[str]`: **não
    reescreve nada** — só executa o `.py` já existente em
    `Workspace.extractor_file(token_id)` (retorna `None` se o arquivo não existir).
  - `_build_env`: se `response_override_dir` for passado, seta
    `HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR` no subprocess; o script gerado
    (`ExtractorTemplate.render_script`) lê dali; senão cai no fallback fixo
    (`real_responses/res_{step:04d}.json`).

- **`Workspace`** (`fs_io/workspace.py`) — `extractor_file(token_id) ->
  extractors/extract_{token_id}.py` é o **único artefato persistido hoje** para um
  extractor. Não existe nenhum arquivo de metadados ao lado (sem `verified`,
  `agent_type`, `origin_step`, nem qualquer histórico de execução persistido em disco).

- **`TokenResolver.resolve_all()`** (`tracking/token_resolver.py`) — itera **todo**
  `session_store.state.registry`, e para cada extractor `verified` com `origin_step`
  não nulo, chama `extractor_runner.run(extractor)` — ou seja, **reescreve o `.py` a
  cada step do fluxo principal** (`Engine._process_entry`, uma vez por step, e de novo
  em `handle_recovery`), mesmo para extractors que não mudaram. Isso é redundante mas
  inofensivo (mesmo conteúdo) — relevante porque qualquer metadado novo gravado ao lado
  do `.py` não pode ser apagado/resetado por essa reescrita.

- **`PlaceholderApplier._verified_extractor`** (`tracking/placeholder_applier.py:34-38`)
  — também depende de `session_store.state.registry` para decidir se substitui um
  valor literal por `{{extractor:token_id}}` no curl template do step. Confirma que o
  registry em memória continua necessário — não está sendo substituído, só ganha uma
  segunda fonte de preenchimento (ver seção 3.3).

- **`ReplayTokenResolver.resolve`/`_resolve_one`** (`replay/replay_token_resolver.py`)
  — para cada `token_id` encontrado via regex no `curl_text`
  (`SessionStore.TOKEN_PLACEHOLDER_PATTERN`), decide `override_dir` (`replay_run_dir` se
  o `origin_step` estiver no `schedule` desta execução de replay, senão
  `res_refer_dir`), chama `extractor_runner.run_existing(token_id, override_dir)`. É
  aqui que aparece, a cada execução de `replay`, uma amostra **nova e ao vivo** da
  resposta de origem — o único lugar do sistema onde "rodar de novo" produz informação
  empírica nova sobre o valor do token (dentro de uma mesma run de `run`/`dry`, o
  response de origem é fixo em disco, reler não muda nada).

- **`ReplayRunner._run_step`** (`replay/replay_runner.py:73-92`) — lê
  `curl_text = Workspace.curl_file(index).read_text(...)`, chama
  `replay_token_resolver.resolve(curl_text, schedule, ...)`, renderiza e envia. É o
  único ponto que já lê o arquivo de curl por completo antes de cada tentativa — ponto
  natural para também escrever de volta um aviso (seção 3.6).

- **`BaselineDiff.compare`/`detect_candidates`** (`tracking/baseline_diff.py`) — um
  valor (`url`, header, cookie ou body) vira candidato a token dinâmico **só por ser
  diferente do request do primeiro step do fluxo** (`baseline`/`first_entry`). Não há
  nenhuma validação cruzada entre execuções — é a raiz do problema de falso-positivo
  que a seção 3.6 (contador de estabilidade) mitiga. `extract_static_values`
  (`baseline_diff.py:79-84`) já existe como conceito separado, mas cobre só headers
  iguais ao baseline — não tem relação com o mecanismo empírico proposto aqui.

- **Models** (`models/session.py`):
  ```python
  class Extractor(BaseModel):
      token_id: str
      code: str
      verified: bool = False
      agent_type: AgentType
      origin_step: Optional[int] = None
      temp_file_path: Optional[str] = None

  class SessionState(BaseModel):
      tokens: Dict[str, str] = Field(default_factory=dict)
      registry: Dict[str, Extractor] = Field(default_factory=dict)
  ```

- **`CliParser` — `--no-reset` (`cli/cli_parser.py:29-35`, `:49-55`)** — estado
  **atual** (antes desta spec): tanto `run` quanto `parse` têm `reset_output_dir` com
  `default=True` (ou seja, por padrão o comando **apaga e recria** `output_dir` inteiro
  antes de rodar — `CliHandlers._reset_output_dir`, `shutil.rmtree` +
  `mkdir`). `--no-reset` é a flag que desliga isso. Com esse default, **nenhum
  reaproveitamento entre execuções seria possível** sem passar `--no-reset` em toda
  invocação a partir da segunda — o diretório `extractors/` (e os metadados novos desta
  spec) seriam apagados antes mesmo do `CandidateResolver` rodar. Este é exatamente o
  comportamento invertido pela seção 3.9 desta spec (a flag deixa de existir, vira
  `--reset` com `default=False`).

## 3. Decisões de arquitetura

### 3.1 Extensão do model `Extractor` com campos de persistência/estabilidade

```python
class Extractor(BaseModel):
    token_id: str
    code: str
    verified: bool = False
    agent_type: AgentType
    origin_step: Optional[int] = None
    temp_file_path: Optional[str] = None
    valid_count: int = 0
    last_value: Optional[str] = None
    ever_changed: bool = False
```

`valid_count`, `last_value` e `ever_changed` só têm significado quando o extractor é
resolvido repetidamente ao vivo (replay, seção 3.6) — em `run`/`dry` ficam nos valores
default e não são lidos. Reaproveitar o mesmo model (em vez de criar um model paralelo
de metadados) porque é exatamente o mesmo dado que já vive no `registry` em memória;
persistir é só serializar/desserializar essa mesma estrutura.

### 3.2 Novo arquivo de metadados por extractor + `ExtractorMetadataStore`

Novo método em `Workspace`:
```python
@classmethod
def extractor_meta_file(cls, token_id: str) -> Path:
    cls._ensure_initialized()
    return cls.extractors / f"extract_{token_id}.meta.json"
```
Arquivo irmão de `extract_{token_id}.py`, no mesmo diretório.

Novo componente, único responsável por ler/escrever esse arquivo (um conceito por
arquivo, `guia_de_estilo.md`):
```python
class ExtractorMetadataStore:
    def load(self, token_id: str) -> Optional[Extractor]:
        meta_file: Path = Workspace.extractor_meta_file(token_id)
        if not meta_file.exists():
            return None
        return Extractor.model_validate_json(meta_file.read_text(encoding="utf-8"))

    def save(self, extractor: Extractor) -> None:
        meta_file: Path = Workspace.extractor_meta_file(extractor.token_id)
        meta_file.write_text(extractor.model_dump_json(indent=2), encoding="utf-8")
```
Sem cache interno — é só I/O de um JSON pequeno, chamado no máximo uma vez por token
por step/replay.

### 3.3 Reaproveitamento em `CandidateResolver._process_candidate`

Ponto de inserção: exatamente onde hoje `existing is None` decide gerar do zero. Novo
fluxo:

```python
existing: Optional[Extractor] = self.session_store.state.registry.get(candidate.token_id)
if existing is not None and existing.verified:
    candidate.status = "Resolved"
    return candidate

persisted: Optional[Extractor] = self.metadata_store.load(candidate.token_id)
if persisted is not None:
    result: Optional[str] = self.extractor_runner.run_existing(candidate.token_id)
    if result == candidate.current_value:
        self.session_store.state.registry[candidate.token_id] = persisted
        candidate.status = "Resolved"
        return candidate
    initial_error = self._mismatch_error(result, candidate.current_value)
else:
    initial_error = None

candidate.status = "UnderReview"
response_sample = self._load_response(origin_step)
if response_sample is None:
    return candidate
candidate.origin_location = TokenLocationDetector.find(candidate.current_value, response_sample)
self._register_extractor(candidate, response_sample, initial_error)
return candidate
```

Pontos a notar:
- `run_existing(candidate.token_id)` sem `response_override_dir` — mesmo fallback fixo
  que `run`/`dry` já usam hoje (`real_responses/`), nenhuma mudança de comportamento de
  leitura de response.
- `response_sample` só é carregado (I/O + parse de JSON) quando realmente necessário
  (extractor persistido não existe, ou existe mas falhou) — hoje é sempre carregado
  para todo candidato `UnderReview`; isso é uma melhoria incidental, não o objetivo
  principal.
- Se `persisted` existir e validar (`result == candidate.current_value`), o extractor é
  colocado no `registry` **sem chamar o agente** — este é o ganho central da spec.
- Se `persisted` existir mas **não** validar, o erro vira `initial_error` e o fluxo
  segue para `_register_extractor`/`_generate_extractor`, agora como **correção**, não
  geração do zero (seção 3.4).
- `_register_extractor`/`ExtractorMetadataStore.save` gravam o metadado novo em disco
  ao final (sucesso ou falha da correção) — sem isso, a run seguinte não teria como
  saber que já foi tentado.

### 3.4 Correção de extractor existente que falhou — `initial_error` em `run_tdd_loop`

Mudança de assinatura:
```python
def run_tdd_loop(
    self,
    max_attempts: Optional[int] = None,
    origin_step: Optional[int] = None,
    initial_error: Optional[str] = None,
) -> Optional[Extractor]:
    strategies = self._get_strategies()
    total = len(strategies) if max_attempts is None else max_attempts
    last_error: Optional[str] = initial_error
    ...
```
Única mudança: `last_error` deixa de começar sempre em `None` e passa a começar em
`initial_error` (default `None`, comportamento idêntico ao atual quando não passado).
A primeira chamada de `generate_code(last_error=initial_error)` já inclui o motivo da
falha observada no prompt do LLM (`ExtractorPrompt.build(..., last_error=...)`, sem
mudança nenhuma necessária ali). `_generate_extractor` passa a aceitar e repassar
`initial_error` para `agent.run_tdd_loop`.

Não é necessário persistir o `code` antigo que falhou — a correção não depende de ver
o código anterior, só do erro observado (mesma informação que já orienta o loop de TDD
hoje quando uma tentativa falha dentro da mesma run).

### 3.5 Reset do contador ao corrigir um extractor existente

Consequência intencional do fluxo acima, deixada explícita aqui: quando `persisted`
existe mas falha a verificação (seção 3.3), o caminho de correção monta um `Extractor`
**novo** via `_generate_extractor`/`run_tdd_loop` — `code` novo, gerado pelo agente. Os
campos `valid_count`/`last_value`/`ever_changed` desse objeto novo vêm nos defaults do
model (`0`/`None`/`False`, seção 3.1) — **não são herdados** do `persisted` antigo que
falhou.

Isso é desejado, não um bug a corrigir depois: o contador atesta a estabilidade de uma
implementação **específica** do extractor (seção 3.7). Se o código mudou, a evidência
acumulada era sobre o comportamento do código antigo — não pode ser reaproveitada como
prova de que o código novo também produz sempre o mesmo valor. A contagem tem que
recomeçar do zero para a nova implementação.

### 3.6 Escrita do metadado durante `run`/`dry` — preservar contadores

`TokenResolver`/`ExtractorRunner.run()` continuam reescrevendo `extract_{token_id}.py`
a cada step (comportamento atual, não muda). O `ExtractorMetadataStore.save` chamado
por `CandidateResolver` (seção 3.3) só grava os campos "de identidade"
(`code`, `verified`, `agent_type`, `origin_step`) — nunca reseta `valid_count`/
`last_value`/`ever_changed` se o registro já existir em disco, porque esses três campos
só são escritos pelo fluxo de replay (seção 3.6). Concretamente: ao gravar, `save`
sempre recebe o `Extractor` vindo do `registry`/agente (que carrega `valid_count=0`
default se foi recém-gerado, ou os valores já existentes se veio de `persisted`
hidratado em 3.3) — não há merge manual necessário porque o objeto que chega em
`save()` já é o mesmo objeto lido ou o mesmo objeto recém-criado, nunca os dois
misturados incorretamente.

### 3.7 Contador de estabilidade / detecção de token estático — no fluxo de `replay`

`STATIC_CONFIRMATION_THRESHOLD: ClassVar[int] = 5`, definido em `ReplayTokenResolver`
(decisão fechada).

Mudança em `ReplayTokenResolver._resolve_one`: depois de obter `value` com sucesso
(hoje: `session_store.set_token(token_id, value)` e retorna), passa a também:

```python
persisted: Optional[Extractor] = self.metadata_store.load(token_id)
if persisted is not None:
    if persisted.last_value is None or persisted.last_value == value:
        persisted.valid_count += 1
    else:
        persisted.ever_changed = True
    persisted.last_value = value
    self.metadata_store.save(persisted)
```

`resolve()` passa a retornar `Set[str]` com os `token_id`s (dentre os resolvidos nesta
chamada) cujo metadado, após a atualização acima, satisfaz `not ever_changed and
valid_count >= STATIC_CONFIRMATION_THRESHOLD` — hoje `resolve()` não retorna nada
(`-> None`); essa é uma mudança de assinatura observável.

Por que só em `replay` e não em `run`/`dry`: dentro de uma run de `run`/`dry`, o
response de origem do token é lido do mesmo arquivo estático o tempo todo — reexecutar
o extractor nunca produz um valor novo, então o contador nunca teria informação real
para acumular ali (seção 2, `ReplayTokenResolver`).

### 3.8 Aviso de token estático como comentário no curl

`ReplayRunner._run_step` já lê `curl_text` inteiro antes de cada tentativa
(`replay_runner.py:74`). Depois de `replay_token_resolver.resolve(...)` retornar o
`Set[str]` de tokens prováveis estáticos (seção 3.7), `ReplayRunner` edita, **para cada
um**, a linha de comentário de origem já existente no arquivo (gerada por
`CurlGenerator._token_comments`, `curl_generator.py:58-61`:
`# Token {token_id} comes from response of step {origin_step}`) — não insere uma linha
nova. Localiza a linha por prefixo (`f"# Token {token_id} comes from response of step"`)
e, se ela ainda não terminar com o sufixo de aviso, acrescenta:

```
# Token b774bbe7479e9c91042c3f09a2aea7b7 comes from response of step 0 - probably static
```

Idempotente por construção: se a linha já termina com `- probably static`, nada é
escrito de novo — sem necessidade de rastrear separadamente "já avisei sobre esse
token" em outro lugar. Não há mais uma decisão de "onde inserir" (a linha alvo já
existe e é única por `token_id`, ver exemplo em `spec.md` seção 2 desta pasta) —
substitui o que antes era tratado como ponto em aberto.

### 3.9 Inversão do padrão de reset do `output_dir` — `--reset`

Mudança em `cli/cli_parser.py`, nos dois subparsers que hoje têm `--no-reset`
(`_build_parse_subparser`, `_build_run_subparser`):

```python
run_parser.add_argument(
    "--reset",
    dest="reset_output_dir",
    action="store_true",
    default=False,
    help="Apagar/recriar o diretório de saída antes de rodar (default: preservar)",
)
```
(idêntico para `parse_parser`, mesmo texto de ajuda). `CliHandlers.handle_run`/
`handle_parse` não mudam — já leem `args.reset_output_dir` e chamam
`_reset_output_dir` condicionalmente; só o default e o nome/sentido da flag invertem.

Efeito prático: a partir desta mudança, **o reaproveitamento entre execuções (seção
3.3) passa a ser o comportamento padrão**, sem exigir nenhuma flag extra — o usuário só
precisa passar `--reset` quando quiser explicitamente descartar tudo e começar do
zero.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `Extractor` (model) | + `valid_count: int = 0`, `last_value: Optional[str] = None`, `ever_changed: bool = False` |
| `Workspace` | + `extractor_meta_file(token_id) -> Path` |
| `ExtractorMetadataStore` (novo) | `load(token_id)` / `save(extractor)` — único ponto de I/O do `.meta.json` |
| `CandidateResolver._process_candidate` | novo passo: checar `.meta.json` em disco antes de gerar; validar via `run_existing`; se inválido, seguir para correção com `initial_error` |
| `BaseAgent.run_tdd_loop` / `generate_code` | novo parâmetro `initial_error: Optional[str] = None`, semeia `last_error` em vez de sempre `None` |
| `ReplayTokenResolver._resolve_one` | atualiza `valid_count`/`last_value`/`ever_changed` a cada resolução válida; `resolve()` passa a retornar `Set[str]` de tokens prováveis estáticos |
| `ReplayRunner._run_step` | edita idempotentemente a linha de comentário de origem no `req_XXXX.curl.sh`, adicionando `- probably static` para tokens prováveis estáticos |
| `CliParser` (`parse` e `run`) | `--no-reset` (default `True`) vira `--reset` (default `False`) |

## 5. Casos de borda e comportamento de erro

- **`--reset` passado explicitamente em `run`/`parse`**: apaga `extractors/` inteiro,
  inclusive os `.meta.json` — reaproveitamento não acontece nessa invocação
  (comportamento correto e esperado de `--reset`, não um bug a tratar). Sem `--reset`
  (novo default, seção 3.9), o diretório é preservado e o reaproveitamento acontece
  normalmente, sem flag nenhuma.
- **Extractor persistido existe mas falha a verificação, agente corrige com
  sucesso**: o `Extractor` novo zera `valid_count`/`last_value`/`ever_changed`
  (seção 3.5) — intencional, evidência de estabilidade do código antigo não vale para
  o código novo.
- **`.meta.json` existe mas `extract_{token_id}.py` não** (ou vice-versa, inconsistência
  manual do usuário no diretório): `run_existing` retorna `None` se o `.py` não existir
  → cai no caminho de correção/geração normal, sobrescrevendo os dois arquivos. Não
  precisa de validação extra.
- **Extractor confirmado estático (`ever_changed=False`, `valid_count>=5`) muda de valor
  depois do aviso já ter sido inserido no curl**: `ever_changed` vira `True` no
  metadado (o contador continua sendo atualizado normalmente após o threshold, não
  para em 5), mas o comentário de aviso já escrito no curl **não é removido**
  automaticamente — fica desatualizado até uma limpeza manual. Aceito como limitação
  conhecida (aviso é só consultivo, não altera comportamento de execução).
- **`ExtractorMetadataStore.load` encontra um JSON corrompido/schema antigo**: erro de
  parse do pydantic (`model_validate_json`) deve ser tratado como "não existe metadado"
  (log de aviso + `None`), nunca crash — mesma filosofia de degradação já usada em
  `CandidateResolver._load_response` (`except Exception` com print).
- **Correção de extractor esgota as tentativas** (`run_tdd_loop` retorna `None` mesmo
  com `initial_error`): mesmo comportamento de hoje para geração do zero —
  `status = "Unresolved"`, nenhum metadado novo sobrescreve o antigo (o antigo
  continua em disco, ainda inválido, será tentado de novo na próxima run).

## 6. Referência

Implementação deve seguir `guia_de_estilo.md`: tipagem explícita em tudo, `ClassVar`
para constantes de classe, um conceito por arquivo, guard clauses, zero
comentários/docstrings, `except Exception` amplo só em bordas de I/O/subprocess (sempre
com print de aviso + degradação, nunca crash silencioso), e o processo de "propor
decomposição → aprovação → gerar arquivo → compile-check" para cada task do plano.
