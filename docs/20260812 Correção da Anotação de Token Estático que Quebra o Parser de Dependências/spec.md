# Spec — Correção da Anotação de Token Estático que Quebra o Parser de Dependências

## 1. Objetivo

`ReplayRunner` anota, no próprio `.curl.sh`, quando um token acabou de ser
classificado como estático (`_annotate_static_tokens`) ou como fallback
(`_annotate_fallback_tokens`) durante um `replay`. Essa anotação é feita
**mutando a mesma linha** que `CurlDependencyParser` depende para descobrir de
qual step um token se origina — e o regex que faz essa leitura exige que a
linha termine exatamente em `\d+$`. Assim que a anotação é aplicada, a linha
para de bater no regex, e o step de origem desaparece **permanentemente**
(persistido em disco) do grafo de dependências.

Dois consumidores reais dependem desse grafo e são afetados:

- `ReplayRunner.compute_smart_schedule` (usado por `replay --mode smart` e
  pela fase 1 do `optimize`, `replay_runner.py:166-189`) — perde a âncora,
  produzindo um schedule mínimo menor do que deveria, sem nenhum aviso.
- `ReplayTokenResolver.resolve` (`replay_token_resolver.py:33,56`) — perde o
  `origin_step` do próprio token sendo resolvido, caindo em
  `_reference_dir_for_step(None, ...)` (`replay_token_resolver.py:90-91`), que
  ignora o step de origem real e usa sempre o diretório de referência
  default. Esta segunda consequência não estava registrada no relatório que
  motivou esta spec — foi descoberta durante a investigação desta etapa.

Reproduzido de forma determinística em teste (branch
`20260812-correcao-da-anotacao-de-token-estatico-que-quebra-o-parser-de-dependencias`,
commit `test:`): três chamadas seguidas de `replay --mode smart` sobre o mesmo
workspace encolhem o schedule de `[0, 1, 14, 23, 34, 75, 233]` para
`[233]` (ver `docs/20260811-3 Teste do Otimizador contra Servidor Real/relatorio.md`,
seção 3.3). Não depende de nenhuma peculiaridade do HAR usado naquele teste —
reproduz em qualquer workspace onde `replay` já rodou com `annotate=True`
(comportamento padrão).

**Causa raiz de arquitetura, não só de regex:** o formato dessa linha de
comentário é um contrato implícito entre três classes que não têm nenhum dono
comum — `CurlGenerator` escreve a linha original (`curl_generator.py:63`),
`ReplayRunner._mark_token` a muta depois (`replay_runner.py:145-153`), e
`CurlDependencyParser` a lê (`curl_dependency_parser.py:7-10`). Nenhuma delas
sabe da existência das outras duas além da convenção de string. Corrigir só o
regex (tolerar o sufixo atual) resolveria o sintoma de hoje e deixaria a
mesma classe de bug pronta para voltar no próximo sufixo que alguém
adicionar.

**Fora de escopo desta spec:**
- Unificar a largura de zero-padding (`:04d`) usada em nomes de arquivo em
  todo o projeto (`workspace.py`, `har_parser.py`, `candidate_resolver.py`,
  `token_resolver.py`, `replay_token_resolver.py`, `extractor_template.py`) —
  avaliado e descartado nesta rodada de conversa por ter um raio de explosão
  muito maior que o bug sendo corrigido, e por não haver nenhum bug de
  overflow real hoje (`:04d` em Python é largura *mínima*, nunca trunca). Só
  nasce, nesta spec, uma constante nomeada para a largura já usada por
  `Workspace`, reaproveitada pelo comentário novo (ver seção 3.4) — os outros
  7 locais fora de `workspace.py` continuam com o literal `4` como estão.
- Achado do relatório sobre `ResponseGrep` não reconhecer o prefixo `"Bearer
  "` (seção 3.1 do relatório) — bug distinto, não relacionado ao parser de
  dependências.
- Achado do relatório sobre `--from` alto mascarar dependência real como
  fallback literal sem avisar (seção 3.4 do relatório) — também distinto.
- Suporte a ler o formato antigo de comentário (sem `[...]`) em workspaces já
  existentes — decidido: **não há suporte**. Um workspace criado por uma
  versão anterior do código precisa ser regenerado (`run` de novo) para se
  beneficiar da correção. Ver seção 5.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `CurlGenerator._token_comments` — `reproduction/curl_generator.py:58-71`

Escreve, para cada `DynamicToken` com `origin_step` conhecido, a linha de
dependência e, condicionalmente, uma segunda linha de status:

```python
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

Roda uma única vez, no `run` (via `TokenTracker.analyze_step` →
`CurlGenerator.generate`, `tracking/token_tracker.py:29`). `origin_location` e
`extraction_exhausted` são campos de `DynamicToken`
(`models/session.py`: `origin_location: Optional[TokenLocation] = None`,
`extraction_exhausted: bool = False`) — decididos uma vez nesse momento e
nunca revisitados depois pelo próprio `run`.

### `ReplayRunner._mark_token`/`_annotate_static_tokens`/`_annotate_fallback_tokens` — `replay/replay_runner.py:18-19,127-153`

```python
STATIC_WARNING_SUFFIX: ClassVar[str] = " - probably static"
CAPTURED_FALLBACK_SUFFIX: ClassVar[str] = " - could not extract value from response, using captured value"
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

Chamado a cada `_run_step` (`replay_runner.py:107-110`), toda vez que
`ReplayTokenResolver.resolve` classifica o token como estático ou fallback
**e** `annotate=True` (padrão de `execute_schedule`, `replay_runner.py:64`;
`ReplayOptimizer._execute_raw` usa `annotate=False` internamente,
`replay_optimizer.py:93`, mas `optimize` herda o estrago se `replay` já
rodou antes sobre o mesmo `--output`, já que o `.curl.sh` já estaria mutado
em disco). Reescreve o `.curl.sh` no disco (`curl_file.write_text(...)`,
linhas 134/143) — o efeito é permanente, não just-in-memory.

### `CurlDependencyParser.DEPENDENCY_PATTERN` — `replay/curl_dependency_parser.py:6-16`

```python
class CurlDependencyParser:
    DEPENDENCY_PATTERN: ClassVar[Pattern[str]] = re.compile(
        r"^# Token (?P<token_id>[a-z0-9]+) comes from response of step (?P<origin_step>\d+)$",
        re.MULTILINE,
    )

    def parse(self, curl_text: str) -> Dict[str, int]:
        return {
            match.group("token_id"): int(match.group("origin_step"))
            for match in self.DEPENDENCY_PATTERN.finditer(curl_text)
        }
```

Único ponto de leitura do grafo de dependências. Consumido por:
- `ReplayRunner._expand_pending` (`replay_runner.py:181-189`), dentro de
  `compute_smart_schedule`.
- `ReplayTokenResolver.resolve` (`replay_token_resolver.py:33`), para decidir
  de onde ler a resposta de origem de cada token (`_resolve_one`, linhas
  56-91).

Já tolera hoje comentários extras que **não batem** no padrão (ex.: a segunda
linha de status escrita por `CurlGenerator`, seção acima) — simplesmente os
ignora, sem erro. O bug não é intolerância a comentário extra; é que
`_mark_token` reescreve a própria linha que o padrão depende, em vez de
adicionar uma linha nova.

### Raízes de composição que instanciam as classes afetadas (não citadas antes — achado da revisão adversarial desta spec)

- `EngineFactory._build_tracker` (`engines/construction/engine_factory.py:93`)
  instancia `CurlGenerator()` **sem nenhum argumento**, dentro do composition
  root do comando `run`/`dry`.
- `CliHandlers._build_replay_runner` (`cli/cli_handlers.py:225`) instancia
  `CurlDependencyParser()` uma única vez e **compartilha essa instância**
  entre `ReplayTokenResolver` (linhas 227-229) e `ReplayRunner` (linhas
  236-248, parâmetro `dependency_parser=dependency_parser`) — é o composition
  root do `replay`/`optimize`.

Qualquer mudança de construtor em `CurlGenerator`/`CurlDependencyParser`
precisa necessariamente tocar estes dois pontos, ou `run`/`replay`/`optimize`
quebram em produção com `TypeError`, não só em teste.

### `Workspace` — `fs_io/workspace.py:43-67`

Centraliza os nomes de arquivo do workspace, todos com padding fixo de 4
dígitos hardcoded em cada método (`f"req_{index:04d}.curl.sh"`, etc. — 5
ocorrências neste arquivo, mais 7 em outros módulos fora de escopo: 2 em
`har_parser.py`, 2 em `extractor_template.py`, 1 em `candidate_resolver.py`, 1
em `token_resolver.py`, 1 em `replay_token_resolver.py`). Não existe hoje
nenhuma constante nomeada para esse `4`. Confirmado: nenhum golden fixture do
projeto passa de 2 dígitos de índice hoje — não há caso de overflow em uso.

### `ReplayOptimizer` — `optimization/replay_optimizer.py`

Confirmado por leitura completa do arquivo e de `contracts/schedule_executor.py`:
não usa `CurlDependencyParser` diretamente — depende de
`compute_smart_schedule`/`existing_step_indexes` via `schedule_executor`
injetado (contrato `ScheduleExecutor`), cuja implementação concreta é o
próprio `ReplayRunner`. Corrigir `CurlDependencyParser`/`CurlTokenComment`
corrige `optimize` automaticamente, sem tocar em `replay_optimizer.py`.

## 3. Decisões de arquitetura

### 3.1 Uma classe única passa a ser dona do formato do comentário — escrita e leitura

Hoje três classes (`CurlGenerator`, `ReplayRunner`, `CurlDependencyParser`)
concordam por convenção implícita de string, sem nenhuma delas conhecer as
outras. Nasce uma classe nova (nome proposto: `CurlTokenComment`, arquivo
`replay/curl_token_comment.py` — substitui `CurlDependencyParser`, mesmo
diretório, contrato de leitura compatível) que passa a ser a única fonte de
verdade do formato:

- Formata a linha de dependência de um token (usada por `CurlGenerator` na
  criação).
- Compõe/atualiza o(s) status legíveis por humano na mesma linha (usada por
  `ReplayRunner` nas anotações).
- Faz o parse de volta para `Dict[str, int]` (mesmo contrato público de
  `CurlDependencyParser.parse` hoje — os dois consumidores atuais,
  `ReplayRunner._expand_pending` e `ReplayTokenResolver.resolve`, trocam de
  dependência por construtor sem mudar de assinatura de uso).

`CurlGenerator` e `ReplayRunner` passam a receber essa classe por construtor
(dependência explícita, sem default — `guia-de-estilo`), em vez de montar
strings inline. Isso exige atualizar as duas raízes de composição citadas na
seção 2 (`EngineFactory._build_tracker`, `CliHandlers._build_replay_runner`)
— ver seção 4 para a lista completa de arquivos afetados, incluindo testes.

### 3.2 Formato da linha: cláusula de máquina delimitada por `[...]`, status humano livre depois

Formato atual (frágil, âncora é o fim da linha):
```
# Token {token_id} comes from response of step {origin_step}
```

Formato novo:
```
# [Token {token_id} comes from response of step {origin_step:04d}] {status legível}
```

O regex de leitura para de exigir `$` no fim — passa a exigir só o `]` de
fechamento, e é **montado a partir do enum da seção 3.3**, nunca duplicado
como string solta (é isso que faz `CurlTokenComment` ser a fonte única de
verdade — o parser e o escritor compartilham o literal, não só a convenção):

```python
DEPENDENCY_PATTERN: ClassVar[Pattern[str]] = re.compile(
    r"^# \[Token (?P<token_id>[a-z0-9]+) "
    rf"{re.escape(DependencyPhrase.COMES_FROM_STEP.value)} "
    r"(?P<origin_step>\d+)\]",
    re.MULTILINE,
)
```

Qualquer texto depois do `]` — um status, dois, três, o que for adicionado no
futuro — nunca mais quebra o parser, porque o parser não olha pra depois do
`]`. Isso elimina a classe de bug inteira, não só a instância atual.

Motivo de manter **uma linha por token** (em vez de uma linha nova por status,
alternativa considerada e descartada): um `.curl.sh` de um `POST` pode ter
vários tokens, cada um potencialmente com status de origem (`CurlGenerator`)
**e** status de replay (`ReplayRunner`) — uma linha por status seria até 3
linhas por token, repetindo `# Token <hash>` várias vezes. Uma linha por
token, com o `[...]` isolando a parte que a máquina lê, mantém o bloco de
comentários do tamanho de hoje.

### 3.3 Frases fechadas em enum, uma categoria por enum, ordem fixa de composição

Toda frase que hoje é string solta (incluindo "comes from response of step")
vira membro de um `Enum(str, Enum)` (`guia-de-estilo`: conjunto fechado de
valores sempre em enum), agrupada por categoria — uma categoria por enum:

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

- `DependencyPhrase` é a cláusula dentro do `[...]` — hoje só tem 1 membro,
  modelado como enum mesmo assim, por simetria com as outras categorias (não
  por necessidade funcional imediata). O `token_id`/`origin_step` não entram
  no texto do enum — são dados concatenados por fora, exatamente como
  `curl_generator.py:63` já faz hoje.
- `OriginStatusPhrase` — escrita uma única vez por `CurlGenerator`, na
  criação (substitui as duas condições de `_token_comments`, seção 2).
- `ReplayStatusPhrase` — escrita/**atualizada** por `ReplayRunner` a cada
  replay. Pode mudar entre execuções (um token pode ser `PROBABLY_STATIC` num
  replay e `COULD_NOT_EXTRACT` no próximo, se o servidor mudar de
  comportamento). Os `ClassVar` antigos `ReplayRunner.STATIC_WARNING_SUFFIX`/
  `CAPTURED_FALLBACK_SUFFIX` são **removidos** — todo consumidor passa a
  referenciar `ReplayStatusPhrase.PROBABLY_STATIC.value`/
  `ReplayStatusPhrase.COULD_NOT_EXTRACT.value` diretamente. Consumidores hoje
  afetados por essa remoção: `tests/unit/test_replay_runner.py` (múltiplas
  ocorrências) e `tests/test_cli_replay.py:262`.

**API mínima de `CurlTokenComment`** (decisão explícita — os métodos operam
sobre uma **linha isolada**, não sobre o texto multi-linha do `.curl.sh`
inteiro; achar a linha certa dentro do arquivo continua responsabilidade de
`ReplayRunner`, igual ao `_mark_token` de hoje):

```python
class CurlTokenComment:

    def __init__(self, step_index_width: int) -> None:
        self.step_index_width: int = step_index_width

    def format_dependency_line(
        self, token_id: str, origin_step: int, origin_status: Optional[OriginStatusPhrase] = None
    ) -> str: ...

    def with_replay_status(self, line: str, phrase: ReplayStatusPhrase) -> str: ...

    def parse(self, curl_text: str) -> Dict[str, int]: ...
```

`format_dependency_line` é usado por `CurlGenerator` na criação (já recebe o
`origin_status`, se houver, decidido uma única vez). `with_replay_status` é
usado por `ReplayRunner`, sempre sobre uma linha já existente.

**Algoritmo de composição — sempre recompõe a partir de estado estruturado,
nunca faz string-replace posicional no texto livre.** Tanto
`format_dependency_line` quanto `with_replay_status` seguem o mesmo
princípio: ao processar uma linha, `CurlTokenComment` primeiro identifica
quais categorias (`OriginStatusPhrase`, `ReplayStatusPhrase`) já estão
presentes na linha recebida — comparando o texto livre após o `]` contra os
`.value` conhecidos de cada enum, categoria por categoria — guarda isso como
estado estruturado (não como texto), aplica a mudança pedida (adiciona
`ReplayStatusPhrase` novo, ou substitui o que já havia dessa mesma categoria)
e **sempre re-serializa a linha inteira do zero**, na ordem canônica fixa
(`OriginStatusPhrase` antes de `ReplayStatusPhrase`, separador `"; "`). Isso
garante que a ordem final nunca depende da ordem física de escrita no
arquivo nem da ordem em que as categorias foram atualizadas ao longo do
tempo — mesmo que o arquivo tenha sido editado manualmente fora de ordem, o
resultado depois de qualquer chamada de `with_replay_status` volta pra ordem
canônica.

Regra de composição:
- **Categorias diferentes concatenam**, sempre na mesma ordem:
  `OriginStatusPhrase` (se houver) antes de `ReplayStatusPhrase` (se houver).
  Separador: `"; "`.
- **Mesma categoria substitui**, nunca acumula — uma nova
  `ReplayStatusPhrase` escrita num replay sobrescreve a anterior daquela
  mesma categoria, em vez de concatenar um histórico.

Exemplo composto (token com `origin_location is None` desde a criação, e que
neste replay caiu em fallback):
```
# [Token 19ca0711b31b0813fdab80694bdc28b1 comes from response of step 0005] origin location undetermined — using literal captured value; could not extract value from response, using captured value
```

### 3.4 Largura do número dentro do `[...]` — constante nomeada, injetada por construtor, sem inferência dinâmica

Decisão (Escopo A, ver seção 1): nasce `Workspace.STEP_INDEX_WIDTH:
ClassVar[int] = 4`, e os 5 métodos de `workspace.py` que hoje usam o literal
`4` (`request_file`, `response_file`, `original_response_file`, `curl_file`,
`replay_response_file`) passam a referenciar essa constante em vez do
literal. `CurlTokenComment` recebe a largura por construtor
(`step_index_width: int`, seção 3.3) — as raízes de composição
(`EngineFactory`, `CliHandlers._build_replay_runner`) constroem
`CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH)`. Essa escolha
(construtor explícito, em vez de `CurlTokenComment` importar `Workspace`
diretamente) evita acoplamento cruzado `replay/` → `fs_io/` e permite testar
`CurlTokenComment` com qualquer largura sem tocar em `Workspace`. Os outros 7
locais fora de `workspace.py` que também usam o literal `4` (seção 2) não são
tocados nesta spec.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `DependencyPhrase`, `OriginStatusPhrase`, `ReplayStatusPhrase` (novos enums) | Frases fechadas por categoria, `Enum(str, Enum)`. |
| `CurlTokenComment` (nova classe, substitui `CurlDependencyParser`) | `__init__(step_index_width: int)`. Formata a linha de dependência (`format_dependency_line`), atualiza status por categoria (`with_replay_status`) e faz o parse de volta (`parse`, mesmo contrato público de hoje). |
| `Workspace.STEP_INDEX_WIDTH` (nova constante) | `ClassVar[int] = 4`, substitui o literal nos 5 métodos de `workspace.py`. |
| `CurlGenerator` | Construtor passa a exigir `CurlTokenComment` (sem default); `_token_comments` delega pra `format_dependency_line` em vez de montar `f"# Token..."` inline. |
| `ReplayRunner` | Construtor troca o parâmetro `dependency_parser: CurlDependencyParser` por `curl_token_comment: CurlTokenComment`; `_mark_token`/`_annotate_static_tokens`/`_annotate_fallback_tokens` delegam pra `with_replay_status`. `STATIC_WARNING_SUFFIX`/`CAPTURED_FALLBACK_SUFFIX` removidos. |
| `ReplayTokenResolver` | Construtor troca `CurlDependencyParser` por `CurlTokenComment` (mesmo uso de `.parse`). |
| `CurlDependencyParser` | Removida — `CurlTokenComment` absorve o método `parse`. |
| `EngineFactory._build_tracker` (`engine_factory.py:93`) | Passa a construir `CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH)` e injetar em `CurlGenerator`. |
| `CliHandlers._build_replay_runner` (`cli_handlers.py:225`) | Troca `CurlDependencyParser()` por `CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH)`, compartilhada entre `ReplayTokenResolver` e `ReplayRunner`. |
| `replay/__init__.py` | Atualiza export: remove `CurlDependencyParser`, adiciona `CurlTokenComment`. |
| `tests/unit/test_curl_generator.py` | 5 instanciações de `CurlGenerator()` sem argumento passam a receber `CurlTokenComment`; asserções que hoje checam string literal do formato antigo (linhas 37/47) são reescritas para o formato novo. |
| `tests/unit/test_curl_dependency_parser.py` | Vira `tests/unit/test_curl_token_comment.py`, contra a nova classe/API. |
| `tests/unit/test_replay_runner.py` | Helper `_runner(...)` troca `CurlDependencyParser()` por `CurlTokenComment(...)`; fixtures que hoje hardcodam `"# Token abc comes from response of step 2\n..."` como string literal passam a ser construídas chamando `CurlTokenComment.format_dependency_line(...)` (evita reintroduzir na suíte de teste o mesmo problema de string solta que esta spec corrige na produção). Referências a `ReplayRunner.CAPTURED_FALLBACK_SUFFIX`/`STATIC_WARNING_SUFFIX` trocam para `ReplayStatusPhrase.*.value`. |
| `tests/unit/test_replay_token_resolver.py` | Helper `_resolver(...)` troca `CurlDependencyParser()` por `CurlTokenComment(...)`. |
| `tests/test_cli_replay.py:262` | Referência a `ReplayRunner.CAPTURED_FALLBACK_SUFFIX` troca para `ReplayStatusPhrase.COULD_NOT_EXTRACT.value`. |
| `tests/golden/*/curls/*.curl.sh` | Regenerar via `HAR_REPRODUCER_UPDATE_GOLDEN=1 uv run pytest --runslow` — o formato do comentário muda para todo fixture que tenha algum `# Token ... comes from response of step` gravado. |

## 5. Casos de borda e comportamento de erro

- **Workspace já existente, criado por uma versão anterior do código (formato
  antigo, sem `[...]`)** — o novo regex não bate no formato antigo (não tem
  `[`/`]`). Decidido: assim como qualquer mudança estrutural nos arquivos
  gerados pelo `run`, um workspace pré-existente precisa ser regenerado
  (`run` de novo) para se beneficiar da correção; não há migração automática
  nem suporte a ler os dois formatos simultaneamente.
- **Token que nunca teve `OriginStatusPhrase` nem `ReplayStatusPhrase`** — a
  linha fica só com a cláusula `[...]`, sem nada depois — igual ao caso
  "tudo certo" de hoje (token resolvido deterministicamente, sem fallback em
  nenhuma etapa).
- **`ReplayStatusPhrase` mudando de valor entre replays** — sempre substitui,
  nunca acumula, e sempre reordena pra forma canônica (seção 3.3). Precisa de
  teste explícito (replay 1 marca `PROBABLY_STATIC`, replay 2 sobre o mesmo
  arquivo marca `COULD_NOT_EXTRACT` → linha final tem só o segundo, não os
  dois).
- **`ReplayTokenResolver.resolve`** — ao trocar de `CurlDependencyParser` para
  `CurlTokenComment.parse`, a assinatura e o retorno (`Dict[str, int]`) não
  mudam — nenhuma alteração de comportamento esperada além de o `origin_step`
  deixar de se perder após a primeira anotação (correção implícita do bug
  secundário da seção 1).
- **Não regressão do teste de tolerância a comentário extra** — o
  `CurlDependencyParser` de hoje já ignora uma linha de comentário adicional
  que não bate no padrão (`test_parse_ignores_exhausted_annotation_line`).
  Esse cenário específico (uma segunda linha solta de "extraction exhausted")
  deixa de ocorrer na prática no formato novo, já que `OriginStatusPhrase`
  passa a viver na mesma linha da cláusula `[...]`, nunca numa linha própria.
  O teste deve ser adaptado para representar um comentário genuinamente
  arbitrário/não relacionado (ex.: `# nota qualquer sobre este step`), para
  continuar cobrindo a robustez geral do parser contra comentários
  desconhecidos, sem depender de um cenário que a produção não gera mais.
- **Convenção de teste**: testes que precisam de um `.curl.sh` com comentário
  de dependência como fixture devem construir esse texto chamando
  `CurlTokenComment` (a própria classe sob teste, ou uma instância dela),
  não hardcodando o formato novo como string solta — do contrário a suíte
  reintroduz o mesmo contrato implícito de string que esta spec elimina da
  produção. A exceção natural é o próprio teste de `CurlTokenComment`, que
  precisa fixar o formato esperado em algum lugar.

## 6. Decisões finais (sem pendências)

Todos os pontos que estavam em aberto nesta spec foram decididos:

1. **Nome da classe nova**: `CurlTokenComment`, em `replay/curl_token_comment.py`
   (substitui `CurlDependencyParser`).
2. **Migração de workspace antigo**: sem suporte ao formato antigo — workspace
   pré-existente precisa de novo `run` (seção 1/5).
3. **Separador entre categorias concatenadas**: `"; "` (seção 3.3).
4. **`step_index_width` em `CurlTokenComment`**: por construtor, explícito
   (seção 3.4).
5. **`ReplayRunner.STATIC_WARNING_SUFFIX`/`CAPTURED_FALLBACK_SUFFIX`**:
   removidos, substituídos por `ReplayStatusPhrase.*.value` (seção 3.3).

Nenhuma suposição pendente de confirmação nesta spec.

## 7. Referência

Implementação segue `guia-de-estilo` (tipagem explícita, dependências por
construtor, `Enum(str, Enum)` para conjuntos fechados, zero comentários no
código Python, decomposição em métodos privados pequenos).
