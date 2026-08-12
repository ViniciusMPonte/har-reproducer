# Plano de Implementação — Correção da Anotação de Token Estático que Quebra o Parser de Dependências

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de
> uma task posterior). Cada task é autocontida — não deveria ser necessário
> reabrir a spec pra executar uma task isolada.

## [T01] — `Workspace`: nasce `STEP_INDEX_WIDTH` como constante nomeada

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/fs_io/workspace.py` (`Workspace`)

**Contexto:**
O padding de 4 dígitos usado em todo nome de arquivo do workspace
(`req_0005.curl.sh`, `res_0005.json`) hoje é o literal `4` repetido em 5
métodos deste arquivo (mais 7 ocorrências fora de escopo em outros módulos,
spec seção 2). `CurlTokenComment` (T03) precisa da mesma largura pra formatar
o número dentro do comentário novo — nasce aqui a constante que ela vai
receber por construtor.

**Estado atual:**
```python
def request_file(self, index: int) -> Path:
    return self.real_requests / f"req_{index:04d}.json"

def response_file(self, index: int) -> Path:
    return self.real_responses / f"res_{index:04d}.json"

def original_response_file(self, index: int) -> Path:
    return self.original_responses / f"res_{index:04d}.json"

def curl_file(self, index: int) -> Path:
    return self.curls / f"req_{index:04d}.curl.sh"

def replay_response_file(self, run_id: str, index: int) -> Path:
    return self.replay_run_dir(run_id) / f"res_{index:04d}.json"
```

**Estado esperado depois:**
- Nasce `STEP_INDEX_WIDTH: ClassVar[int] = 4` em `Workspace`.
- Os 5 métodos acima passam a usar `f"req_{{index:0{Workspace.STEP_INDEX_WIDTH}d}}.json"`
  (ou equivalente) em vez do literal `4`.
- ⚠️ Não tocar nos outros 7 locais fora de `workspace.py` que também usam o
  literal `4` (`har_parser.py`, `candidate_resolver.py`, `token_resolver.py`,
  `replay_token_resolver.py`, `extractor_template.py`) — fora de escopo desta
  spec (seção 1).
- Comportamento observável idêntico a hoje — mesma largura, mesmos nomes de
  arquivo gerados. Isso é puramente `refactor:`, sem TDD (não há "red" a
  escrever, guia-de-estilo, exceção de refactor estrutural).

**Critérios de aceite:**
- [x] `Workspace.STEP_INDEX_WIDTH == 4`.
- [x] `Workspace(tmp_path).curl_file(5)` continua retornando um `Path`
      terminando em `req_0005.curl.sh` (não-regressão).
- [x] Suíte completa de testes que usa `Workspace` (`tests/unit/test_replay_runner.py`,
      `tests/unit/test_replay_token_resolver.py`, golden) continua passando sem
      nenhuma mudança de asserção.

## [T02] — Novos enums de frase: `DependencyPhrase`, `OriginStatusPhrase`, `ReplayStatusPhrase`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/replay/curl_token_comment.py` (novo arquivo)

**Contexto:**
Toda frase que hoje é string solta espalhada entre `CurlGenerator` e
`ReplayRunner` vira membro de um `Enum(str, Enum)` fechado, uma categoria por
enum (spec seção 3.3). Esses enums são a base sobre a qual `CurlTokenComment`
(T03) é construída.

**Estado atual:**
Não existe — as frases são strings soltas em `curl_generator.py:63,65,67-69`
e `replay_runner.py:18-19`.

**Estado esperado depois:**
```python
class DependencyPhrase(str, Enum):
    COMES_FROM_STEP = "comes from response of step"


class OriginStatusPhrase(str, Enum):
    UNDETERMINED = "origin location undetermined — using literal captured value"
    EXTRACTION_EXHAUSTED = "origin location determined but extraction exhausted — using literal captured value"


class ReplayStatusPhrase(str, Enum):
    PROBABLY_STATIC = "probably static"
    COULD_NOT_EXTRACT = "could not extract value from response, using captured value"
```
- ⚠️ Os valores textuais devem ser **idênticos, caractere a caractere**, aos
  textos já usados hoje em `curl_generator.py`/`replay_runner.py` (incluindo o
  travessão `—`) — não é uma reescrita de copy, é a mesma frase virando
  membro de enum.
- `CurlDependencyParser`/`CurlGenerator`/`ReplayRunner` ainda não são tocados
  nesta task — os enums existem isolados, sem nenhum consumidor ainda.

**Critérios de aceite:**
- [x] `DependencyPhrase.COMES_FROM_STEP.value == "comes from response of step"`.
- [x] `OriginStatusPhrase.UNDETERMINED.value` é idêntico ao texto hoje escrito
      em `curl_generator.py:65`.
- [x] `OriginStatusPhrase.EXTRACTION_EXHAUSTED.value` é idêntico ao texto hoje
      escrito em `curl_generator.py:67-69` (concatenado).
- [x] `ReplayStatusPhrase.PROBABLY_STATIC.value == "probably static"` — mesmo
      texto de `ReplayRunner.STATIC_WARNING_SUFFIX` hoje (`" - probably static"`),
      sem o prefixo `" - "` (o prefixo/separador passa a ser responsabilidade
      de composição de `CurlTokenComment`, não do enum).
- [x] `ReplayStatusPhrase.COULD_NOT_EXTRACT.value == "could not extract value from response, using captured value"`
      — mesmo texto de `ReplayRunner.CAPTURED_FALLBACK_SUFFIX` hoje, sem o
      prefixo `" - "`.
- [x] As 3 classes são `str, Enum` (checável via `isinstance(DependencyPhrase.COMES_FROM_STEP, str)`).

## [T03] — `CurlTokenComment`: formata, compõe e faz parse do comentário — núcleo da correção

**Depende de:** T01 (`Workspace.STEP_INDEX_WIDTH`), T02 (enums de frase).
**Arquivos envolvidos:** `har_reproducer/replay/curl_token_comment.py` (`CurlTokenComment`, mesmo arquivo dos enums de T02)

**Contexto:**
Esta é a classe que passa a ser a única dona do formato do comentário de
dependência — escrita e leitura (spec seção 3.1). Substitui
`CurlDependencyParser` (ainda não removida nesta task — `CurlDependencyParser`
continua existindo e em uso até T07, para não quebrar os consumidores atuais
no meio do caminho).

**Estado atual:**
`CurlDependencyParser.DEPENDENCY_PATTERN` (`curl_dependency_parser.py:7-10`)
exige `$` no fim da linha — é exatamente o bug (spec seção 1).

**Estado esperado depois:**
```python
class CurlTokenComment:

    CATEGORY_SEPARATOR: ClassVar[str] = "; "

    DEPENDENCY_PATTERN: ClassVar[Pattern[str]] = re.compile(
        r"^# \[Token (?P<token_id>[a-z0-9]+) "
        rf"{re.escape(DependencyPhrase.COMES_FROM_STEP.value)} "
        r"(?P<origin_step>\d+)\]",
        re.MULTILINE,
    )

    def __init__(self, step_index_width: int) -> None:
        self.step_index_width: int = step_index_width

    def format_dependency_line(
        self, token_id: str, origin_step: int, origin_status: Optional[OriginStatusPhrase] = None
    ) -> str: ...

    def with_replay_status(self, line: str, phrase: ReplayStatusPhrase) -> str: ...

    def parse(self, curl_text: str) -> Dict[str, int]: ...
```
- `format_dependency_line` monta `# [Token {token_id} comes from response of
  step {origin_step:0{width}d}]`, seguido de `{origin_status.value}` se
  `origin_status` não for `None`.
- `with_replay_status` recebe uma linha já formatada (com ou sem status
  prévio), identifica quais categorias (`OriginStatusPhrase`,
  `ReplayStatusPhrase`) já estão presentes no texto após o `]` (comparando
  contra os `.value` conhecidos de cada enum), substitui/adiciona o
  `ReplayStatusPhrase` recebido, e **recompõe a linha inteira do zero** na
  ordem canônica (`OriginStatusPhrase` antes de `ReplayStatusPhrase`,
  separador `CATEGORY_SEPARATOR`).
- `parse` usa `DEPENDENCY_PATTERN.finditer` — mesmo contrato de retorno de
  `CurlDependencyParser.parse` hoje (`Dict[str, int]`), mas tolera qualquer
  texto após o `]` (spec seção 3.2) e continua ignorando linhas de comentário
  que não batem no padrão (não-regressão do comportamento de
  `test_parse_ignores_exhausted_annotation_line`, adaptado nesta task para um
  cenário de comentário genuinamente arbitrário, já que o cenário original
  — segunda linha de "extraction exhausted" — deixa de ocorrer no formato
  novo).
- ⚠️ `with_replay_status` nunca faz string-replace posicional no texto livre
  — sempre parseia as categorias presentes para estado estruturado antes de
  recompor (spec seção 3.3). Isso é o que garante ordem determinística mesmo
  se o arquivo tiver sido editado manualmente fora de ordem.

**TDD desta task:** escrever primeiro `tests/unit/test_curl_token_comment.py`
(substitui `tests/unit/test_curl_dependency_parser.py`) cobrindo, em
vermelho, cada cenário abaixo antes de implementar `CurlTokenComment`.

**Critérios de aceite:**
- [x] `format_dependency_line("abc", 5)` retorna
      `"# [Token abc comes from response of step 0005]"` (sem status, sem
      espaço sobrando no fim).
- [x] `format_dependency_line("abc", 5, OriginStatusPhrase.UNDETERMINED)` retorna
      a linha com `"] origin location undetermined — using literal captured value"`
      no final.
- [x] `with_replay_status(line_sem_status, ReplayStatusPhrase.PROBABLY_STATIC)`
      anexa `"probably static"` após o `]`.
- [x] `with_replay_status` chamado sobre uma linha que já tem
      `OriginStatusPhrase.UNDETERMINED` preserva esse status e concatena o
      `ReplayStatusPhrase` novo com `"; "`, nesta ordem: origem antes de
      replay.
- [x] `with_replay_status` chamado duas vezes seguidas com
      `ReplayStatusPhrase` diferente (`PROBABLY_STATIC` depois
      `COULD_NOT_EXTRACT`) resulta em **só o segundo** presente na linha final
      (substitui, não acumula) — cenário do relatório (spec seção 5).
- [x] `parse(texto)` com uma linha no formato novo, sem nenhum status,
      retorna `{"abc": 5}`.
- [x] `parse(texto)` com uma linha no formato novo **com qualquer status
      anexado** (`OriginStatusPhrase`, `ReplayStatusPhrase`, ou os dois
      concatenados) continua retornando `{"abc": 5}` — este é o teste que
      reproduz e fecha o bug original (equivalente adaptado de
      `test_parse_still_extracts_dependency_annotated_as_probably_static`).
- [x] `parse(texto)` ignora uma linha de comentário arbitrária que não bate
      no padrão (`"# nota qualquer sobre este step"`) sem lançar exceção e
      sem incluí-la no resultado.
- [x] `parse(texto)` com múltiplas linhas de dependência retorna todas
      (não-regressão de `test_parse_extracts_multiple_dependencies`).

## [T04] — `CurlGenerator`: passa a delegar para `CurlTokenComment`

**Depende de:** T03.
**Arquivos envolvidos:** `har_reproducer/reproduction/curl_generator.py` (`CurlGenerator`)

**Contexto:**
`CurlGenerator._token_comments` monta as linhas de comentário inline hoje
(spec seção 2). Passa a delegar a formatação para `CurlTokenComment`,
recebida por construtor.

**Estado atual:**
```python
class CurlGenerator:

    def generate(self, request: StepRequest, tokens: List[DynamicToken]) -> str:
        ...

    @staticmethod
    def _token_comments(tokens: List[DynamicToken]) -> List[str]:
        lines: List[str] = []
        for token in tokens:
            if token.origin_step is None:
                continue
            lines.append(f"# Token {token.token_id} comes from response of step {token.origin_step}")
            if token.origin_location is None:
                lines.append(f"# Token {token.token_id} origin location undetermined — using literal captured value")
            elif token.extraction_exhausted:
                lines.append(
                    f"# Token {token.token_id} origin location determined but extraction exhausted — "
                    f"using literal captured value"
                )
        return lines
```

**Estado esperado depois:**
- `CurlGenerator.__init__(self, curl_token_comment: CurlTokenComment) -> None`
  — dependência explícita, sem default (guia-de-estilo).
- `_token_comments` deixa de ser `@staticmethod` (passa a usar
  `self.curl_token_comment`) e delega a cada token para
  `self.curl_token_comment.format_dependency_line(token.token_id, token.origin_step, origin_status)`,
  onde `origin_status` é `OriginStatusPhrase.UNDETERMINED` se
  `token.origin_location is None`, `OriginStatusPhrase.EXTRACTION_EXHAUSTED`
  se `token.extraction_exhausted`, ou `None` caso contrário.
- ⚠️ Uma única linha por token agora (a lógica de "duas linhas condicionais"
  vira "um status opcional passado pra `format_dependency_line`") — não é
  mais uma lista de até 2 linhas por token, é sempre 1.

**Critérios de aceite:**
- [x] `CurlGenerator(CurlTokenComment(4))` — construtor aceita a dependência.
- [x] `generate(...)` para um token com `origin_location is None` produz uma
      única linha de comentário terminando em
      `"origin location undetermined — using literal captured value"`, no
      formato novo (`# [Token ...] ...`).
- [x] `generate(...)` para um token com `origin_location` resolvido e
      `extraction_exhausted=False` produz a linha só com a cláusula `[...]`,
      sem status.
- [x] `generate(...)` para múltiplos tokens preserva a ordem original (uma
      linha por token, na ordem em que os tokens foram passados) —
      não-regressão.
- [x] `tests/unit/test_curl_generator.py` atualizado: as 5 instanciações de
      `CurlGenerator()` sem argumento passam a receber
      `CurlTokenComment(step_index_width=4)`; as asserções que checavam o
      texto antigo (linhas 37/47 hoje) passam a checar o formato novo.

## [T05] — `ReplayRunner`: passa a delegar para `CurlTokenComment`, remove sufixos antigos

**Depende de:** T03.
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py` (`ReplayRunner`)

**Contexto:**
`ReplayRunner._mark_token`/`_annotate_static_tokens`/`_annotate_fallback_tokens`
mutam a linha de dependência inline hoje — é o ponto exato do bug (spec seção
1). Passam a delegar para `CurlTokenComment.with_replay_status`.

**Estado atual:**
```python
STATIC_WARNING_SUFFIX: ClassVar[str] = " - probably static"
CAPTURED_FALLBACK_SUFFIX: ClassVar[str] = " - could not extract value from response, using captured value"

def __init__(self, workspace, dependency_parser: CurlDependencyParser, ...) -> None:
    ...
    self.dependency_parser: CurlDependencyParser = dependency_parser
    ...

@classmethod
def _mark_token(cls, text: str, token_id: str, suffix: str) -> str:
    prefix: str = f"# Token {token_id} comes from response of step "
    lines: List[str] = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(prefix) and not line.endswith(suffix):
            lines[i] = line + suffix
            break
    return "\n".join(lines) + "\n"
```

**Estado esperado depois:**
- `STATIC_WARNING_SUFFIX`/`CAPTURED_FALLBACK_SUFFIX` **removidos**.
- Parâmetro de construtor `dependency_parser: CurlDependencyParser` renomeado
  para `curl_token_comment: CurlTokenComment` (mesma posição/uso —
  `_expand_pending` troca `self.dependency_parser.parse(...)` por
  `self.curl_token_comment.parse(...)`).
- `_mark_token` é removido; `_annotate_static_tokens`/`_annotate_fallback_tokens`
  passam a, para cada `token_id`, achar a linha correspondente (mesma busca
  por prefixo que existe hoje, mas usando a cláusula formatada por
  `CurlTokenComment` para reconhecer a linha) e chamar
  `self.curl_token_comment.with_replay_status(linha, ReplayStatusPhrase.PROBABLY_STATIC)`
  ou `...COULD_NOT_EXTRACT` respectivamente.
- ⚠️ Comportamento observável de `_run_step`/`compute_smart_schedule` para o
  usuário final não muda (mesmos steps executados, mesmo veredito) — só o
  texto do `.curl.sh` grava um formato diferente, e o schedule deixa de
  encolher entre execuções (é a correção do bug em si).

**Critérios de aceite:**
- [x] `test_compute_smart_schedule_still_expands_after_dependency_annotated_as_static`
      (já commitado, vermelho) passa a **verde**: anotar o step 5 como
      estático via `_run_step` não faz o step 2 desaparecer de
      `compute_smart_schedule(None, 5)`.
- [x] `test_mark_token_appends_suffix_once`/`test_mark_token_leaves_text_unchanged_for_absent_token`
      (hoje testam `_mark_token` diretamente) são adaptados para testar
      `with_replay_status` via `curl_token_comment` (o método `_mark_token` não
      existe mais).
- [x] `test_annotate_static_tokens_rewrites_file_only_when_text_changes`/
      `test_annotate_fallback_tokens_rewrites_file_only_when_text_changes`
      continuam passando, checando o novo texto de status em vez de
      `"probably static"`/`"could not extract value"` soltos (agora vía
      `ReplayStatusPhrase.PROBABLY_STATIC.value`/`.COULD_NOT_EXTRACT.value`).
- [x] `test_run_step_annotates_fallback_token_in_curl` atualizado: referência a
      `ReplayRunner.CAPTURED_FALLBACK_SUFFIX` troca para
      `ReplayStatusPhrase.COULD_NOT_EXTRACT.value`.
- [x] `test_execute_schedule_annotate_false_suppresses_curl_annotation`/
      `test_execute_schedule_annotate_true_default_keeps_curl_annotation`
      atualizados na mesma linha.
- [x] Helper `_runner(...)` em `tests/unit/test_replay_runner.py` passa a
      construir `CurlTokenComment(step_index_width=4)` em vez de
      `CurlDependencyParser()`.
- [x] Fixtures hardcoded como `"# Token abc comes from response of step 2\ncurl..."`
      nos testes deste arquivo passam a ser construídas chamando
      `CurlTokenComment.format_dependency_line("abc", 2)` (spec seção 5,
      convenção de teste) em vez de string solta.
- [x] `tests/test_cli_replay.py:262` (referência a `CAPTURED_FALLBACK_SUFFIX`)
      atualizado para `ReplayStatusPhrase.COULD_NOT_EXTRACT.value`.

## [T06] — `ReplayTokenResolver`: passa a receber `CurlTokenComment`

**Depende de:** T03.
**Arquivos envolvidos:** `har_reproducer/replay/replay_token_resolver.py` (`ReplayTokenResolver`)

**Contexto:**
`ReplayTokenResolver.resolve` chama `self.dependency_parser.parse(curl_text)`
(`replay_token_resolver.py:33`) para descobrir `origin_step` de cada token —
mesmo bug secundário descrito na spec (seção 1): perde a origem depois da
primeira anotação.

**Estado atual:**
```python
def __init__(self, session_store, extractor_runner, dependency_parser: CurlDependencyParser, metadata_store) -> None:
    ...
    self.dependency_parser: CurlDependencyParser = dependency_parser
```

**Estado esperado depois:**
- Parâmetro renomeado para `curl_token_comment: CurlTokenComment`, mesma
  posição/uso (`self.curl_token_comment.parse(curl_text)`).
- Nenhuma outra mudança de comportamento — `_resolve_one` continua idêntico,
  só passa a receber `origin_step` correto mesmo depois de replays
  anteriores terem anotado a linha (correção implícita do bug secundário).

**Critérios de aceite:**
- [x] Helper `_resolver(...)` em `tests/unit/test_replay_token_resolver.py`
      passa a construir `CurlTokenComment(step_index_width=4)` em vez de
      `CurlDependencyParser()`.
- [x] Teste novo: `resolve` sobre um `curl_text` já anotado (via
      `CurlTokenComment.with_replay_status`) continua retornando o
      `origin_step` correto para o token — não-regressão do bug secundário
      (spec seção 1, consequência sobre `ReplayTokenResolver`).
- [x] Suíte existente de `test_replay_token_resolver.py` passa sem outra
      mudança de asserção.

## [T07] — Remove `CurlDependencyParser`, atualiza `replay/__init__.py`

**Depende de:** T03, T04, T05, T06 (nenhum consumidor de produção ou teste
ainda referencia `CurlDependencyParser` depois destas).
**Arquivos envolvidos:** `har_reproducer/replay/curl_dependency_parser.py` (removido), `har_reproducer/replay/__init__.py`

**Contexto:**
Com `CurlGenerator`, `ReplayRunner` e `ReplayTokenResolver` já usando
`CurlTokenComment`, `CurlDependencyParser` fica sem nenhum consumidor —
remove-se para não deixar duas fontes de verdade do mesmo formato coexistindo
(o problema original que motivou toda a correção).

**Estado atual:**
`har_reproducer/replay/__init__.py` reexporta `CurlDependencyParser`,
`ReplayResultComparator`, `ReplayRunner`, `ReplayTokenResolver`.

**Estado esperado depois:**
- `har_reproducer/replay/curl_dependency_parser.py` deletado.
- `tests/unit/test_curl_dependency_parser.py` deletado (conteúdo já migrado
  para `tests/unit/test_curl_token_comment.py` em T03).
- `replay/__init__.py` reexporta `CurlTokenComment` em vez de
  `CurlDependencyParser` (mais `DependencyPhrase`, `OriginStatusPhrase`,
  `ReplayStatusPhrase` se algum consumidor externo ao pacote precisar deles
  diretamente — confirmar durante a task se `cli_handlers.py` precisa
  importar os enums ou só `CurlTokenComment`).

**Critérios de aceite:**
- [x] `grep -r "CurlDependencyParser" har_reproducer/ tests/` não retorna
      nenhuma ocorrência.
- [x] `from har_reproducer.replay import CurlTokenComment` funciona.
- [x] Suíte completa (`uv run pytest`) roda sem erro de import.

## [T08] — Composition roots: `EngineFactory` e `CliHandlers._build_replay_runner` passam a construir `CurlTokenComment`

**Depende de:** T01, T04, T05, T06.
**Arquivos envolvidos:** `har_reproducer/engines/construction/engine_factory.py` (`EngineFactory._build_tracker`), `har_reproducer/cli/cli_handlers.py` (`CliHandlers._build_replay_runner`)

**Contexto:**
São as duas raízes de composição que instanciam `CurlGenerator`/
`CurlDependencyParser` hoje sem conhecer a mudança de construtor — achado da
revisão adversarial desta spec (spec seção 2). Sem esta task, `run`/`replay`/
`optimize` quebram em produção com `TypeError` assim que T04/T05/T06 forem
aplicadas, mesmo que a suíte de testes unitários passe.

**Estado atual:**
```python
# engine_factory.py:93, dentro de _build_tracker
curl_generator: CurlGenerator = CurlGenerator()
```
```python
# cli_handlers.py:225, dentro de _build_replay_runner
dependency_parser: CurlDependencyParser = CurlDependencyParser()
# ... injetado em ReplayTokenResolver e ReplayRunner
```

**Estado esperado depois:**
```python
# engine_factory.py
curl_token_comment: CurlTokenComment = CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH)
curl_generator: CurlGenerator = CurlGenerator(curl_token_comment)
```
```python
# cli_handlers.py
curl_token_comment: CurlTokenComment = CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH)
# ... injetado em ReplayTokenResolver e ReplayRunner no lugar de dependency_parser
```
- ⚠️ Mesma instância de `CurlTokenComment` compartilhada entre
  `ReplayTokenResolver` e `ReplayRunner` em `_build_replay_runner`, igual ao
  padrão atual com `CurlDependencyParser` (`cli_handlers.py:225` já
  compartilha uma única instância entre os dois).

**Critérios de aceite:**
- [x] `uv run python -m har_reproducer.main run --har ... --config ...`
      executa sem `TypeError` (smoke test manual ou via golden existente).
- [x] `uv run python -m har_reproducer.main replay --output ... --mode all`
      executa sem `TypeError`.
- [x] Golden suite (`tests/golden/run_main`, `tests/golden/replay_all`, etc.)
      continua passando com o composition root atualizado (antes de
      regenerar em T09 — nesta task ainda deve estar vermelho/divergente
      porque o formato do fixture ainda é o antigo; ver T09).

## [T09] — Regenerar fixtures golden e validar suíte completa

**Depende de:** T01 a T08.
**Arquivos envolvidos:** `tests/golden/*/curls/*.curl.sh` (regravados)

**Contexto:**
Todo fixture golden com `# Token ... comes from response of step` foi escrito
no formato antigo. Depois de T01-T08, a produção passa a gerar o formato
novo — os fixtures precisam ser regravados para refletir a mudança
deliberada de comportamento (guia-de-estilo, exceção de TDD: "Regeneração de
golden — a comparação de árvore ou o texto já é a verificação").

**Estado atual:**
`tests/golden/*/curls/req_*.curl.sh` contêm o formato antigo (`# Token abc
comes from response of step 5`, sem colchetes).

**Estado esperado depois:**
- Rodar `HAR_REPRODUCER_UPDATE_GOLDEN=1 uv run pytest --runslow`.
- Todos os fixtures que continham uma linha de dependência passam a ter o
  formato novo (`# [Token abc comes from response of step 0005]`, com
  status concatenado quando aplicável).
- Diff revisado manualmente antes de commitar (`git diff tests/golden/`) para
  confirmar que a única mudança é o formato do comentário — nenhuma mudança
  de comportamento de request/response.

**Critérios de aceite:**
- [x] `uv run pytest` (suíte padrão) passa 100%.
- [x] `uv run pytest --runslow` (inclui golden de rede) passa 100%.
- [x] `git diff tests/golden/` mostra só mudanças nas linhas de comentário
      `# Token ...`/`# [Token ...]` — nenhum outro campo do `.curl.sh`
      (método, URL, headers, body) muda.
- [x] Os 2 testes vermelhos originais desta etapa
      (`test_parse_still_extracts_dependency_annotated_as_probably_static`,
      migrado para `test_curl_token_comment.py` em T03;
      `test_compute_smart_schedule_still_expands_after_dependency_annotated_as_static`,
      em T05) estão verdes.
