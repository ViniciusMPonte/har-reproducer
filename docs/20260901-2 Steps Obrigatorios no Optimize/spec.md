# Spec — Steps Obrigatórios no `optimize`

## 0. Sumário e glossário

**Sumário:** o comando `optimize` minimiza um schedule de steps por busca (remove
candidatos e reconfirma o `success_criteria` do alvo a cada remoção). Hoje ele só
protege automaticamente o piso (`--from`) e o alvo (`--to`) — qualquer outro step,
inclusive um step de login cujo token de sessão pareceu "fixo" na amostra capturada,
pode ser removido por engano quando o resolver de tokens não reconhece a dependência
real. Esta etapa adiciona uma flag `--required-steps-file <arquivo.txt>` ao `optimize`: um
`.txt` com um índice de step por linha (mesmo formato de `replay --steps-file`) cujos
índices o `ReplayOptimizer` nunca tenta remover, independente do que a busca
concluiria sozinha. É uma garantia declarada pelo usuário, não uma inferência nova do
pipeline — continua sem hardcode de "step de login é sempre obrigatório": quem decide
o que é obrigatório é quem já sabe operar aquele portal, o comando só respeita a
decisão.

**Glossário:**
- **Step obrigatório**: índice de step que o usuário informa via `--required-steps-file`
  e que o `ReplayOptimizer` nunca tenta remover durante a busca, em nenhuma das suas
  fases (`_resolve_range`, `_reduce_anchors`).
- **Backbone**: faixa contígua de steps entre `--from` e o penúltimo anchor,
  executada por completo em toda tentativa para alimentar o cache/`CookieJar`
  (`ReplayOptimizer._compute_backbone`, `replay_optimizer.py:104-106`). ⚠️ Isso
  garante que a *resposta* de todo índice do backbone é sempre buscada, mas **não**
  garante que o índice sobreviva no `.txt` final — os ranges de `_resolve_range`
  (`_ranges_target_to_from`) cobrem o mesmo espaço de índices que o backbone quando
  há 3+ anchors (ex.: `anchors=[0,3,6,9]` → backbone `[0..6]`, e os ranges `(3,6)` e
  `(0,3)` ficam inteiramente dentro dele), então um índice do backbone pode ser
  testado e removido da fase 2 como qualquer outro candidato. Ver seção 5.
- **Anchor**: índice devolvido por `schedule_executor.compute_smart_schedule` — ponto
  de "parada" da estratégia smart de replay, candidato a remoção só na fase
  `_reduce_anchors`.
- **Candidato** (num range `(left, right)`): índice existente estritamente entre dois
  anchors consecutivos, testado para remoção por `_resolve_range`
  (`_candidates_between`, `replay_optimizer.py:233-234`).

## 1. Objetivo

Hoje, um step só sobrevive à busca do `optimize` se: (a) for o piso (`--from`) ou o
alvo (`--to`), ou (b) o resolver de tokens identificar que o alvo depende dele via
algum valor dinâmico rastreável. Quando o valor que aquele step estabelece (ex.: um
token de acesso de login) parece estático na captura — porque não mudou entre as
respostas que o pipeline viu, ou porque a resolução caiu no fallback do
`captured_value` (`Extractor.captured_value`, ver [[arquitetura-e-fundamentos]]) — o
`ReplayOptimizer` não tem como saber que aquele step é necessário na realidade, e o
remove. Isso já foi documentado como falso positivo conhecido do fluxo de login em
`docs/../.claude/skills/reproducao-de-har/references/navigation-on-medical-portals.md`
(commit `0eca890`), cujo único contorno hoje é usar `--from <índice do login>` — o que
também descarta tudo *antes* do login (inclusive o step 0, que funciona como sanity
check de "o portal está no ar").

O custo de não resolver isso: quem já sabe, por conhecimento de domínio, que um step
é indispensável (login, um step que popula um cookie de sessão usado por vários
outros steps além do alvo, um step de "keep-alive") não tem hoje uma forma de
declarar essa certeza ao `optimize` sem sacrificar tudo que vem antes dele via
`--from`. Esta etapa fecha essa lacuna: uma lista de steps que o usuário afirma serem
obrigatórios, e que a busca deve respeitar sem tentar refutar.

**Fora de escopo:**
- Qualquer heurística nova para *inferir* automaticamente que um step é obrigatório
  (ex.: "todo step de login é sempre obrigatório") — violaria o princípio de
  genericidade do projeto (ver [[arquitetura-e-fundamentos]]); a lista continua sendo
  100% declarada pelo usuário.
  Nunca é gerada automaticamente pelo próprio `optimize` — é sempre entrada.
- Validar que os steps obrigatórios *de fato* são necessários (o comando confia na
  declaração do usuário; se um step obrigatório não fizer diferença nenhuma, ele só
  aumenta o schedule final sem quebrar nada).
- Estender `--required-steps-file` para `replay` — `replay` já reexecuta uma lista fixa de
  steps (não faz busca/remoção), então o conceito de "step que não pode ser removido"
  não se aplica lá.
- Mudar o formato do `.txt` de saída do `optimize` (`workspace.optimized_steps_file`)
  para marcar quais índices vieram de `--required-steps-file` — o arquivo de saída
  continua sendo consumível diretamente por `replay --mode list --steps-file`, sem
  comentários (mesma razão de `ReplayRunner._schedule_list`, que faz
  `int(line.strip())` linha a linha sem tolerar comentário).

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `CliParser._build_optimize_subparser` — `har_reproducer/cli/cli_parser.py:86-110`

Define as flags atuais de `optimize`: `--output`, `--to`/`--from` (índices),
`--config`, `--success-criteria`, `--steps-out`, `--max-requests`. Não existe hoje
nenhuma flag para restringir remoção.

O comando `replay` já tem uma flag de arquivo `.txt` com um índice por linha,
reaproveitável como referência de formato (`cli_parser.py:77-82`):

```python
replay_parser.add_argument(
    "--steps-file",
    dest="steps_file",
    default=None,
    help="Path to a txt file with one step index per line (list mode only)",
)
```

### `ReplayRunner._schedule_list` — `har_reproducer/replay/replay_runner.py:197-202`

Parser atual desse formato de `.txt` (usado por `replay --mode list`):

```python
def _schedule_list(self, steps_file: Path) -> Tuple[List[int], Set[int]]:
    existing_set: Set[int] = set(self.existing_step_indexes())
    lines: List[str] = steps_file.read_text(encoding="utf-8").splitlines()
    ordered_indexes: List[int] = [int(line.strip()) for line in lines if line.strip()]
    self._require_all_existing(ordered_indexes, existing_set)
    return ordered_indexes, set(ordered_indexes)
```

Um índice por linha, linhas em branco ignoradas, `int(line.strip())` sem
tolerância a comentário. `_require_all_existing` (`replay_runner.py:204-209`) valida
que todo índice lido existe no workspace, levantando `ValueError` com a lista dos que
faltam. Esta etapa introduz um parser análogo (ver seção 3.1) em vez de reaproveitar
este método diretamente, porque ele é privado de `ReplayRunner` e teria que ser
promovido a método compartilhado — decisão de extração feita na seção 3.1.

### `CliHandlers.handle_optimize` — `har_reproducer/cli/cli_handlers.py:140-178`

Monta `Workspace`, `ProjectConfig`, `ReplayRunner` (usado como
`ScheduleExecutor`), valida `--from` (`_validate_optimize_from_index`,
`cli_handlers.py:194-201`) e instancia `ReplayOptimizer`:

```python
self._validate_optimize_from_index(runner, args.from_index)

optimizer: ReplayOptimizer = ReplayOptimizer(
    schedule_executor=runner,
    metadata_store=SilentExtractorMetadataStore(workspace),
    max_requests=args.max_requests,
    workspace=workspace,
    cookie_jar=cookie_jar,
)
output_path: Optional[Path] = Path(args.steps_out) if args.steps_out else None

result: Optional[List[int]] = orchestrator.run(
    lambda: optimizer.optimize(
        workspace, run_id, args.from_index, args.to_index, success_criteria, output_path
    )
)
```

`_validate_optimize_from_index` é o padrão de validação a replicar para os steps
obrigatórios (mesma mensagem de erro, mesmo `existing: Set[int] =
set(runner.existing_step_indexes())`).

### `ReplayOptimizer` — `har_reproducer/optimization/replay_optimizer.py`

Núcleo da busca. `optimize()` (linhas 38-67) orquestra 3 fases e escreve o `.txt`
final:

```python
def optimize(self, workspace, run_id, from_index, to_index, success_criteria, output_path=None):
    anchors, backbone = self._run_phase1(from_index, to_index)
    try:
        kept = self._run_phase2(from_index, to_index, anchors, backbone, success_criteria)
    except ReplayOptimizerAborted as aborted:
        print(f"ReplayOptimizer: aborted — {aborted.reason}")
        return None
    reduced_anchors = self._reduce_anchors(anchors, from_index, to_index, kept, success_criteria)
    final_list = sorted({from_index, to_index, *reduced_anchors, *kept})
    if not self._confirm(final_list, to_index, success_criteria):
        ...
    destination.write_text("\n".join(str(index) for index in final_list) + "\n", encoding="utf-8")
    return final_list
```

Nenhum parâmetro hoje representa "índices que não podem ser removidos" — `required`
não existe em lugar nenhum da assinatura (grep por `required`/`mandatory`/
`protected`/`must_keep`/`pin` no módulo não encontra ocorrência).

Duas fases decidem remoção, e são exatamente os dois pontos que esta etapa altera:

**`_reduce_anchors`** (linhas 69-87) — remove anchors um a um (exceto `from_index`/
`to_index`), testando se o resultado ainda passa:

```python
def _reduce_anchors(self, anchors, from_index, to_index, kept, success_criteria):
    removable = [anchor for anchor in anchors if anchor not in (from_index, to_index)]
    working = list(removable)
    for anchor in reversed(removable):
        trial = [a for a in working if a != anchor]
        trial_final_list = sorted({from_index, to_index, *trial, *kept})
        if self._confirm(trial_final_list, to_index, success_criteria,
                          restrict_backbone_feed_to=set(trial_final_list)):
            working = trial
    return working
```

**`_resolve_range`** (linhas 184-207) — para um range `(left, right)` entre dois
anchors consecutivos, primeiro tenta remover todos os candidatos de uma vez
(`_attempt(left, right, [], ...)`), senão faz remoção gulosa um a um:

```python
def _resolve_range(self, left, right, to_index, backbone, kept_so_far, success_criteria):
    if self._attempt(left, right, [], backbone, kept_so_far, to_index, success_criteria):
        return []
    candidates = self._candidates_between(left, right)
    if not candidates or not self._attempt(left, right, candidates, backbone, kept_so_far, to_index, success_criteria):
        raise ReplayOptimizerAborted(...)
    working = list(candidates)
    for candidate in reversed(candidates):
        trial = [c for c in working if c != candidate]
        if self._attempt(left, right, trial, backbone, kept_so_far, to_index, success_criteria):
            working = trial
    return working
```

`_run_phase2` (linhas 171-182) chama `_resolve_range` para cada range devolvido por
`_ranges_target_to_from` (linhas 225-231), acumulando o resultado em `kept`.

## 3. Decisões de arquitetura

### 3.1. Parser de `.txt` de índices — extrair um utilitário compartilhado

**Estado atual:** `ReplayRunner._schedule_list` (linhas 197-209) parseia e valida um
`.txt` de índices, mas é privado e específico do `replay --mode list`.

**Estado esperado:** criar `har_reproducer/fs_io/step_index_file.py` com uma função
livre:

```python
def parse_step_index_file(path: Path) -> List[int]:
    lines: List[str] = path.read_text(encoding="utf-8").splitlines()
    return [int(line.strip()) for line in lines if line.strip()]
```

`ReplayRunner._schedule_list` passa a delegar a leitura para
`parse_step_index_file` (mantendo `_require_all_existing` como está, chamado
depois). `CliHandlers` usa a mesma função para `--required-steps-file`. Evita duplicar a
lógica de parsing (mesmo formato, mesma tolerância a linha em branco) em dois
lugares que já nascem parecidos — e centraliza o único ponto que decidiria mudar o
formato do `.txt` no futuro (ex.: aceitar comentários), se algum dia for preciso.

**Alternativa descartada:** duplicar um parser idêntico dentro de `CliHandlers`. Mais
isolado, mas perpetua a duplicação que `guia-de-estilo` desencoraja para lógica sem
razão de divergir.

### 3.2. Nova flag `--required-steps-file` em `optimize`

**Estado atual:** `_build_optimize_subparser` (`cli_parser.py:86-110`) não tem
nenhuma flag equivalente.

**Estado esperado:**

```python
optimize_parser.add_argument(
    "--required-steps-file",
    dest="required_steps_file",
    default=None,
    help="Path to a txt file with one required step index per line — these are never removed by the search",
)
```

Nome escolhido como `--required-steps-file` (não `--required-steps`) para seguir o
mesmo padrão de `replay --steps-file`: sufixo `-file` sinaliza "isto é um caminho",
consistente em todo o CLI. Opcional (`default=None`); ausência de flag preserva 100%
o comportamento atual (sem steps obrigatórios declarados). Formato idêntico ao de
`replay --steps-file`: um índice por linha, reaproveitando `parse_step_index_file`
(seção 3.1).

### 3.3. Validação em `CliHandlers.handle_optimize`

**Estado atual:** `_validate_optimize_from_index` (`cli_handlers.py:194-201`) valida
só `--from` contra `runner.existing_step_indexes()`, antes de instanciar o
`ReplayOptimizer`.

**Estado esperado:** novo método estático `_validate_required_steps`, chamado no
mesmo ponto, mesmo padrão de mensagem:

```python
@staticmethod
def _validate_required_steps(
        runner: ReplayRunner, required_steps: Set[int], from_index: int, to_index: int,
) -> None:
    existing: Set[int] = set(runner.existing_step_indexes())
    missing: List[int] = sorted(required_steps - existing)
    if missing:
        raise ValueError(
            f"ReplayOptimizer: step(s) obrigatório(s) {missing} não existem no workspace "
            f"(nenhum curl file em disco) — provavelmente foram pulados por skip_rules ou "
            f"estão fora do intervalo de steps existentes."
        )
    out_of_range: List[int] = sorted(
        index for index in required_steps if index < from_index or index > to_index
    )
    if out_of_range:
        raise ValueError(
            f"ReplayOptimizer: step(s) obrigatório(s) {out_of_range} estão fora do intervalo "
            f"[--from {from_index}, --to {to_index}] — remova-os de --required-steps-file ou ajuste "
            f"--from/--to."
        )
```

`handle_optimize` (`cli_handlers.py:140-178`) passa a carregar o arquivo (se
informado), validar, e repassar ao `ReplayOptimizer.optimize(...)`. A leitura é
envolvida num `try/except` que traduz erro de arquivo ausente ou linha não numérica
em `ValueError` com o caminho do arquivo — ver seção 5 para o porquê de não alterar
`parse_step_index_file`/`ReplayRunner._schedule_list` para isso:

```python
required_steps: Set[int] = self._load_required_steps(args.required_steps_file)
self._validate_optimize_from_index(runner, args.from_index)
self._validate_required_steps(runner, required_steps, args.from_index, args.to_index)
...
result: Optional[List[int]] = orchestrator.run(
    lambda: optimizer.optimize(
        workspace, run_id, args.from_index, args.to_index, success_criteria, output_path,
        required_steps=required_steps,
    )
)
```

⚠️ `--from`/`--to` já são sempre mantidos independentemente de `--required-steps-file` —
declarar `--from`/`--to` na lista de obrigatórios não é erro, é redundante (a
validação de faixa acima permite, já que `index <= to_index` e `index >= from_index`
incluem os próprios extremos).

Novo método estático `_load_required_steps`, que envolve `parse_step_index_file`
com o tratamento de erro descrito acima:

```python
@staticmethod
def _load_required_steps(required_steps_file: Optional[str]) -> Set[int]:
    if not required_steps_file:
        return set()
    path: Path = Path(required_steps_file)
    try:
        return set(parse_step_index_file(path))
    except (FileNotFoundError, ValueError) as error:
        raise ValueError(f"--required-steps-file {path}: {error}") from error
```

### 3.4. `ReplayOptimizer.optimize` — novo parâmetro `required_steps`

**Estado atual:** assinatura de `optimize` (`replay_optimizer.py:38-45`) não recebe
nenhum conjunto de índices protegidos; `_run_phase2`, `_resolve_range` e
`_reduce_anchors` não têm noção de "não remover".

**Estado esperado:** novo parâmetro opcional `required_steps: Optional[Set[int]] =
None`, normalizado para `Set[int]` vazio quando omitido, propagado por toda a cadeia
de chamadas:

```python
def optimize(
        self, workspace, run_id, from_index, to_index, success_criteria,
        output_path: Optional[Path] = None,
        required_steps: Optional[Set[int]] = None,
) -> Optional[List[int]]:
    required: Set[int] = set(required_steps) if required_steps else set()
    anchors, backbone = self._run_phase1(from_index, to_index)
    try:
        kept = self._run_phase2(from_index, to_index, anchors, backbone, success_criteria, required)
    except ReplayOptimizerAborted as aborted:
        ...
    reduced_anchors = self._reduce_anchors(anchors, from_index, to_index, kept, success_criteria, required)
    final_list = sorted({from_index, to_index, *reduced_anchors, *kept})
    ...
```

`required` default `None`→`set()` preserva 100% o comportamento atual quando a flag
não é usada — nenhum teste existente que chama `optimize(...)` sem esse argumento
quebra (parâmetro é opcional e a lógica nova é sempre um no-op para conjunto vazio).

### 3.5. `_resolve_range` — separar candidatos obrigatórios dos removíveis

**Estado atual:** ver seção 2 (trecho completo) — todo candidato entre dois anchors
é igualmente removível, incluindo na primeira tentativa "remove tudo de uma vez"
(`_attempt(left, right, [], ...)`).

**Estado esperado:** dividir `_candidates_between(left, right)` em `forced` (os que
estão em `required`) e `optional` (o resto). A tentativa "remove tudo" passa a testar
com `forced` sempre presente (nunca `[]` quando há forçados no range) e, se passar,
devolve `forced` (não mais `[]`) — porque os obrigatórios têm que permanecer no
schedule mesmo quando toda a parte opcional é removível. O laço guloso de remoção
passa a iterar só sobre `optional`, nunca oferecendo um `forced` como candidato a
teste de remoção:

```python
def _resolve_range(self, left, right, to_index, backbone, kept_so_far, success_criteria, required: Set[int] = set()):
    candidates_all: List[int] = self._candidates_between(left, right)
    forced: List[int] = [c for c in candidates_all if c in required]
    if self._attempt(left, right, forced, backbone, kept_so_far, to_index, success_criteria):
        return forced
    optional: List[int] = [c for c in candidates_all if c not in required]
    if not optional or not self._attempt(
            left, right, candidates_all, backbone, kept_so_far, to_index, success_criteria):
        raise ReplayOptimizerAborted(
            f"ReplayOptimizer: faixa ({left}, {right}) falhou mesmo com todos os candidatos incluídos."
        )
    working: List[int] = list(optional)
    for candidate in reversed(optional):
        trial: List[int] = forced + [c for c in working if c != candidate]
        if self._attempt(left, right, trial, backbone, kept_so_far, to_index, success_criteria):
            working = [c for c in working if c != candidate]
    return forced + working
```

⚠️ Quando `required` é vazio (`forced == []`), este código é **idêntico em
comportamento** ao atual: `_attempt(left, right, [], ...)` na primeira tentativa,
`working = list(candidates_all)` no laço guloso — só os nomes de variável mudam
(`candidates`→`candidates_all`/`optional`). Isso é a garantia de não-regressão desta
task.

⚠️ **`required` com default `set()` (não `Optional[Set[int]] = None`), e é seguro
como default mutável**: diferente de `optimize()` (seção 3.4), este é um método
*privado*, chamado hoje diretamente por vários testes unitários
(`tests/unit/test_replay_optimizer.py`) sem esse argumento — se `required` fosse
obrigatório e sem default, toda chamada existente a `_resolve_range(...)` nesses
testes quebraria com `TypeError`. O padrão usual de evitar default mutável existe
para prevenir mutação acidental compartilhada entre chamadas; aqui `required` só é
lido (`c in required`), nunca mutado, então o mesmo objeto `set()` default
reaproveitado entre chamadas é inofensivo. Mesma decisão em 3.6/3.7.

### 3.6. `_reduce_anchors` — excluir anchors obrigatórios do pool removível

**Estado atual:** ver seção 2 — `removable` inclui todo anchor exceto `from_index`/
`to_index`; `working` começa igual a `removable` e só encolhe.

**Estado esperado:** anchors que estejam em `required` saem do pool `removable` (não
são testados para remoção), mas precisam continuar presentes em toda
`trial_final_list` testada e no retorno final — senão desapareceriam do resultado em
vez de serem preservados:

```python
def _reduce_anchors(self, anchors, from_index, to_index, kept, success_criteria, required: Set[int] = set()):
    forced: List[int] = [a for a in anchors if a not in (from_index, to_index) and a in required]
    removable: List[int] = [a for a in anchors if a not in (from_index, to_index) and a not in required]
    working: List[int] = list(removable)
    for anchor in reversed(removable):
        trial: List[int] = [a for a in working if a != anchor]
        trial_final_list: List[int] = sorted({from_index, to_index, *forced, *trial, *kept})
        if self._confirm(trial_final_list, to_index, success_criteria,
                          restrict_backbone_feed_to=set(trial_final_list)):
            working = trial
    return forced + working
```

⚠️ Mesma garantia de não-regressão da seção 3.5: com `required` vazio, `forced == []`
e o comportamento é idêntico ao atual.

### 3.7. `_run_phase2` — repassar `required`

**Estado atual:** `_run_phase2` (`replay_optimizer.py:171-182`) chama
`_resolve_range` sem nenhum conceito de obrigatório.

**Estado esperado:** `_run_phase2` recebe `required` como parâmetro extra e repassa
para cada chamada de `_resolve_range` — mudança puramente de encanamento, sem lógica
nova nesta função:

```python
def _run_phase2(self, from_index, to_index, anchors, backbone, success_criteria, required: Set[int] = set()):
    kept: List[int] = []
    for left, right in self._ranges_target_to_from(from_index, anchors):
        kept += self._resolve_range(left, right, to_index, backbone, kept, success_criteria, required)
    return kept
```

⚠️ Mesmo motivo de default `set()` (não `Optional[...] = None`) da seção 3.5 —
`_run_phase2` também é privado e chamado diretamente por testes unitários existentes
sem esse argumento.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `har_reproducer/fs_io/step_index_file.py` (novo) | `parse_step_index_file(path) -> List[int]`, parser do `.txt` de um índice por linha, reaproveitado por `replay` e `optimize`. |
| `ReplayRunner._schedule_list` | Passa a delegar o parsing para `parse_step_index_file` (refactor, sem mudança de comportamento). |
| `CliParser._build_optimize_subparser` | Nova flag `--required-steps-file` (dest `required_steps_file`), opcional. |
| `CliHandlers.handle_optimize` | Carrega e valida o `.txt` de steps obrigatórios; repassa como `required_steps` para `ReplayOptimizer.optimize`. |
| `CliHandlers._load_required_steps` (novo) | Lê `--required-steps-file` via `parse_step_index_file`, traduzindo `FileNotFoundError`/`ValueError` de parsing em `ValueError` com o caminho do arquivo. |
| `CliHandlers._validate_required_steps` (novo) | Valida que todo índice obrigatório existe no workspace e está dentro de `[--from, --to]`. |
| `ReplayOptimizer.optimize` | Novo parâmetro opcional `required_steps: Optional[Set[int]]`, default preserva comportamento atual. |
| `ReplayOptimizer._run_phase2` | Repassa `required` para `_resolve_range` (encanamento). |
| `ReplayOptimizer._resolve_range` | Separa candidatos `forced`/`optional`; `forced` nunca é oferecido para remoção, sempre presente nas tentativas. |
| `ReplayOptimizer._reduce_anchors` | Mesma separação `forced`/`removable` para anchors. |
| `.claude/skills/reproducao-de-har/references/navigation-on-medical-portals.md` | Seção "Fluxo de login" ganha `--required-steps-file` como forma recomendada de proteger o login/step 0 sem descartar tudo antes via `--from`. |

## 5. Casos de borda e comportamento de erro

- **Índice obrigatório fora do workspace** (nenhum curl file em disco): erro
  explícito antes de rodar qualquer request (`_validate_required_steps`), mesmo
  padrão de mensagem de `_validate_optimize_from_index` — comportamento a
  implementar, não uma limitação aceita.
- **Índice obrigatório fora de `[--from, --to]`**: erro explícito
  (`_validate_required_steps`), porque um índice fora do range nunca seria
  considerado pela busca de qualquer forma — sinal de uso incorreto da flag, não algo
  a ignorar silenciosamente.
- **Índice obrigatório dentro do backbone** (entre `--from` e o penúltimo anchor):
  ⚠️ **não é no-op** — corrigido em relação a uma suposição inicial descartada
  durante a revisão desta spec. O backbone só garante que a *resposta* daquele
  índice é sempre buscada (para cache/`CookieJar`); a *presença* do índice no
  `.txt` final continua decidida por `_resolve_range`, cujos ranges podem cobrir o
  mesmo espaço de índices do backbone (ver glossário). Declarar um índice do
  backbone como obrigatório muda sim o resultado: ele deixa de ser candidato a
  remoção nesse range, exatamente como qualquer outro índice obrigatório.
- **Índice obrigatório igual a `--from` ou `--to`**: no-op, já são sempre mantidos
  (seção 3.3, nota).
- **`required_steps` inclui um índice que a busca já manteria de qualquer forma**
  (porque o resolver detectou a dependência real): no-op — o schedule final não
  muda, só a lista deixa de depender de o resolver ter acertado.
- **Todos os candidatos de um range são obrigatórios**: `_resolve_range` retorna
  `forced` direto na primeira tentativa (linha "if attempt(forced) return forced"),
  sem nenhuma tentativa de remoção — comportamento correto, não é um caso de erro.
- **`--required-steps-file` aponta para arquivo vazio ou só com linhas em branco**:
  `parse_step_index_file` devolve lista vazia — equivalente a não informar a flag,
  não é erro.
- **Arquivo com índice repetido**: tolerado (vira `Set[int]`, duplicata é
  no-op) — mesma tolerância implícita que `replay --mode list` já tem via
  `set(ordered_indexes)`.
- **`--required-steps-file` aponta para um caminho inexistente**: hoje
  `ReplayRunner._schedule_list` deixaria propagar o `FileNotFoundError` cru de
  `Path.read_text()` para esse mesmo caso em `replay --mode list` — mesmo
  comportamento indesejável que esta etapa não corrige por completo, mas não deve
  repetir sem necessidade. `CliHandlers.handle_optimize` envolve a leitura do
  `--required-steps-file` (não `parse_step_index_file` em si, para não alterar o
  contrato já usado por `replay`) num `try/except FileNotFoundError` que relança
  como `ValueError` com o caminho informado, seguindo o mesmo padrão de mensagem
  das demais validações desta etapa.
- **Arquivo com linha não numérica** (`abc`, `1.5`, etc.): `int(line.strip())`
  propaga `ValueError` nativo do Python (`invalid literal for int() with base 10:
  'abc'`) — sem o contexto de qual arquivo/linha originou o erro. Mesma limitação
  que `replay --mode list --steps-file` já tem hoje (não é regressão introduzida
  por esta etapa), mas como `--required-steps-file` é uma flag nova, vale o mesmo
  tratamento acima: `handle_optimize` deve envolver a chamada a
  `parse_step_index_file(Path(args.required_steps_file))` também nesse ponto,
  relançando como `ValueError` com o caminho do arquivo antes do texto original do
  erro. Não estender esse tratamento a `replay` (fora de escopo desta etapa, ver
  seção 1).

## 6. Referência

Implementação segue `guia_de_estilo.md`/[[guia-de-estilo]] como padrão obrigatório.
