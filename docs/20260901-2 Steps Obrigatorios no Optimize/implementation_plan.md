# Plano de Implementação — Steps Obrigatórios no `optimize`

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `parse_step_index_file`: criar parser compartilhado de arquivo de índices

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/fs_io/step_index_file.py` (novo),
`har_reproducer/fs_io/__init__.py` (exportar), `tests/unit/test_step_index_file.py`
(novo).

**Contexto:**
Hoje, o parsing de um `.txt` com um índice de step por linha vive só dentro de
`ReplayRunner._schedule_list` (`har_reproducer/replay/replay_runner.py:197-202`),
privado e específico do `replay --mode list`. Esta task extrai essa lógica para uma
função livre reaproveitável tanto por `replay` (T02) quanto pelo novo
`--required-steps-file` de `optimize` (T07) — spec seção 3.1.

**Estado atual:**
- Não existe `har_reproducer/fs_io/step_index_file.py`.
- A lógica de parsing (sem a validação de existência, que é uma responsabilidade
  separada de `ReplayRunner._require_all_existing`) está inline em
  `_schedule_list`:
  ```python
  lines: List[str] = steps_file.read_text(encoding="utf-8").splitlines()
  ordered_indexes: List[int] = [int(line.strip()) for line in lines if line.strip()]
  ```

**Estado esperado depois:**
- Novo módulo `har_reproducer/fs_io/step_index_file.py` com uma função livre:
  ```python
  from pathlib import Path
  from typing import List


  def parse_step_index_file(path: Path) -> List[int]:
      lines: List[str] = path.read_text(encoding="utf-8").splitlines()
      return [int(line.strip()) for line in lines if line.strip()]
  ```
- `har_reproducer/fs_io/__init__.py` passa a exportar `parse_step_index_file` junto
  de `HARParser`/`Workspace`/`WorkspaceDir`.
- ⚠️ Não faz validação de existência de índice contra o workspace — isso continua
  sendo responsabilidade de cada chamador (`ReplayRunner._require_all_existing` em
  T02, `CliHandlers._validate_required_steps` em T07). Esta função só parseia texto.
- ⚠️ Não faz `set()`/dedup nem `sorted()` — preserva ordem e duplicatas da forma como
  aparecem no arquivo, igual ao comportamento atual de `_schedule_list` antes do
  `set(ordered_indexes)` que ela mesma aplica depois.
- Erros de leitura (`FileNotFoundError`) e de conversão (`ValueError` de
  `int(...)`) propagam crus, sem wrapping — quem decide se/como traduzir isso é o
  chamador (T02 mantém o comportamento cru já existente de `replay`; T07 adiciona
  wrapping novo só para `optimize`, spec seção 3.3/5).

**Critérios de aceite:**
- [x] `parse_step_index_file(arquivo com "0\n3\n\n7\n")` retorna `[0, 3, 7]`.
- [x] `parse_step_index_file(arquivo vazio)` retorna `[]`.
- [x] `parse_step_index_file(arquivo só com linhas em branco)` retorna `[]`.
- [x] `parse_step_index_file(caminho inexistente)` levanta `FileNotFoundError`.
- [x] `parse_step_index_file(arquivo com linha "abc")` levanta `ValueError`.
- [x] `parse_step_index_file(arquivo com "3\n3\n1\n")` retorna `[3, 3, 1]` (preserva
      ordem e duplicata — não deduplica, não ordena).

---

## [T02] — `ReplayRunner._schedule_list`: delegar parsing para `parse_step_index_file`

**Depende de:** T01 (usa a função extraída).
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py`.

**Contexto:**
Refactor puramente estrutural — substitui a lógica de parsing inline por uma chamada
à função compartilhada de T01, sem alterar nenhum comportamento observável de
`replay --mode list`. Spec seção 3.1 ("Alternativa descartada").

**Estado atual** (`replay_runner.py:197-202`):
```python
def _schedule_list(self, steps_file: Path) -> Tuple[List[int], Set[int]]:
    existing_set: Set[int] = set(self.existing_step_indexes())
    lines: List[str] = steps_file.read_text(encoding="utf-8").splitlines()
    ordered_indexes: List[int] = [int(line.strip()) for line in lines if line.strip()]
    self._require_all_existing(ordered_indexes, existing_set)
    return ordered_indexes, set(ordered_indexes)
```

**Estado esperado depois:**
```python
def _schedule_list(self, steps_file: Path) -> Tuple[List[int], Set[int]]:
    existing_set: Set[int] = set(self.existing_step_indexes())
    ordered_indexes: List[int] = parse_step_index_file(steps_file)
    self._require_all_existing(ordered_indexes, existing_set)
    return ordered_indexes, set(ordered_indexes)
```
- Import novo: `from har_reproducer.fs_io import parse_step_index_file` (o módulo já
  importa `Workspace` de `har_reproducer.fs_io` — acrescentar ao mesmo import).
- `_require_all_existing` (linhas 204-209) permanece inalterado.
- ⚠️ Este é um `refactor:` puro — TDD não se aplica aqui (skill `spec-e-plano`,
  Passo 3): não há comportamento novo a reproduzir com teste antes, os testes
  existentes de `replay --mode list` já cobrem o contrato.

**Critérios de aceite:**
- [x] Toda a suíte de testes que já cobre `replay --mode list --steps-file` (ex.:
      `tests/test_cli_optimize.py`, testes de `ReplayRunner` em
      `tests/unit/`) continua passando sem alteração — garantia de não-regressão.
- [x] `_schedule_list` de um `.txt` com "0\n2\n5\n" continua retornando
      `([0, 2, 5], {0, 2, 5})`.
- [x] `_schedule_list` com um índice que não existe no workspace continua
      levantando `ValueError` via `_require_all_existing` (mensagem inalterada).

---

## [T03] — `ReplayOptimizer`: encanamento do parâmetro `required_steps`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py`.

**Contexto:**
Primeiro passo para introduzir o conceito de "step obrigatório" no
`ReplayOptimizer`: adicionar o parâmetro `required_steps` na assinatura pública
(`optimize`) e repassá-lo, ainda sem nenhuma lógica de proteção real, até
`_run_phase2` e `_reduce_anchors`. As tasks T04/T05 usam esse parâmetro para de fato
mudar o comportamento de remoção. Separado em task própria porque é puro encanamento
(mudança de assinatura), enquanto T04/T05 mudam algoritmo — spec seções 3.4 e 3.7.

**Estado atual** (`replay_optimizer.py:38-67`):
```python
def optimize(
        self,
        workspace: Workspace,
        run_id: str,
        from_index: int,
        to_index: int,
        success_criteria: List[SuccessCriterion],
        output_path: Optional[Path] = None,
) -> Optional[List[int]]:
    anchors: List[int]
    backbone: List[int]
    anchors, backbone = self._run_phase1(from_index, to_index)

    try:
        kept: List[int] = self._run_phase2(from_index, to_index, anchors, backbone, success_criteria)
    except ReplayOptimizerAborted as aborted:
        print(f"ReplayOptimizer: aborted — {aborted.reason}")
        return None

    reduced_anchors: List[int] = self._reduce_anchors(anchors, from_index, to_index, kept, success_criteria)
    ...
```
E `_run_phase2` (linhas 171-182):
```python
def _run_phase2(
        self, from_index: int, to_index: int, anchors: List[int], backbone: List[int],
        success_criteria: List[SuccessCriterion],
) -> List[int]:
    kept: List[int] = []
    for left, right in self._ranges_target_to_from(from_index, anchors):
        kept += self._resolve_range(left, right, to_index, backbone, kept, success_criteria)
    return kept
```

**Estado esperado depois:**
```python
def optimize(
        self,
        workspace: Workspace,
        run_id: str,
        from_index: int,
        to_index: int,
        success_criteria: List[SuccessCriterion],
        output_path: Optional[Path] = None,
        required_steps: Optional[Set[int]] = None,
) -> Optional[List[int]]:
    required: Set[int] = set(required_steps) if required_steps else set()
    anchors: List[int]
    backbone: List[int]
    anchors, backbone = self._run_phase1(from_index, to_index)

    try:
        kept: List[int] = self._run_phase2(from_index, to_index, anchors, backbone, success_criteria, required)
    except ReplayOptimizerAborted as aborted:
        print(f"ReplayOptimizer: aborted — {aborted.reason}")
        return None

    reduced_anchors: List[int] = self._reduce_anchors(
        anchors, from_index, to_index, kept, success_criteria, required
    )
    ...
```
```python
def _run_phase2(
        self, from_index: int, to_index: int, anchors: List[int], backbone: List[int],
        success_criteria: List[SuccessCriterion], required: Set[int] = set(),
) -> List[int]:
    kept: List[int] = []
    for left, right in self._ranges_target_to_from(from_index, anchors):
        kept += self._resolve_range(left, right, to_index, backbone, kept, success_criteria, required)
    return kept
```
- `_resolve_range` e `_reduce_anchors` ganham o parâmetro `required` na assinatura
  nesta task (posicional, último parâmetro, **com default** `= set()`), mas **ainda
  sem usá-lo** no corpo — T04/T05 implementam a lógica que de fato o consome. Isso
  mantém esta task como encanamento puro e testável isoladamente (o parâmetro chega
  até onde precisa, sem mudar nenhum resultado ainda).
- ⚠️ `required_steps: Optional[Set[int]] = None` em `optimize()` (API pública) e
  `required: Set[int] = set()` em `_run_phase2`/`_resolve_range`/`_reduce_anchors`
  (métodos privados) — os dois preservam toda chamada existente sem argumento novo,
  mas por razões diferentes: `optimize()` é só chamado de fora (CLI/testes de
  integração) e nenhuma dessas chamadas passa `output_path` sem nome depois de
  `required_steps`, então `Optional[...] = None` normalizado dentro do método basta.
  Já `_run_phase2`, `_resolve_range` e `_reduce_anchors` são **chamados diretamente
  por vários testes unitários existentes** em `tests/unit/test_replay_optimizer.py`
  sem esse argumento (ex.: linhas 130, 145, 160, 178, 203, 282 chamam
  `_run_phase2(...)`; linhas 420, 435, 493, 510 chamam `_reduce_anchors(...)`, todas
  com 5 argumentos, sem `required`) — se esses três métodos exigissem `required` sem
  default, essas ~10 chamadas quebrariam com `TypeError: missing 1 required
  positional argument`. Por isso os três usam default mutável `set()` diretamente
  (não `Optional[Set[int]] = None`): é seguro aqui porque `required` só é lido
  (`c in required`/`a in required`), nunca mutado — o padrão de evitar default
  mutável existe para prevenir mutação acidental compartilhada, que não se aplica
  neste caso (mesma justificativa da spec, seção 3.5).

**Critérios de aceite:**
- [x] `optimize(...)` chamado sem `required_steps` (como todo teste hoje chama)
      continua produzindo exatamente o mesmo resultado de antes — garantia de
      não-regressão (rodar toda a suíte `tests/unit/test_replay_optimizer.py`).
- [x] `optimize(..., required_steps={5})` não lança erro e chega até
      `_resolve_range`/`_reduce_anchors` sem quebrar (ainda sem efeito observável
      nesta task — efeito é validado em T04/T05).
- [x] `optimize(..., required_steps=None)` e `optimize(...)` (omitindo o parâmetro)
      produzem resultado idêntico entre si.
- [x] Toda chamada direta existente a `_run_phase2(...)` sem `required` em
      `tests/unit/test_replay_optimizer.py` (linhas 130, 145, 160, 178, 203, 282 no
      estado atual do arquivo) continua funcionando sem `TypeError` — garantia de
      não-regressão explícita para o default `set()` dos métodos privados.

---

## [T04] — `ReplayOptimizer._resolve_range`: separar candidatos `forced`/`optional`

**Depende de:** T03 (assinatura já recebe `required`).
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py`,
`tests/unit/test_replay_optimizer.py`.

**Contexto:**
Núcleo da feature na fase 2 da busca (remoção de candidatos entre anchors
consecutivos). Spec seção 3.5. Hoje todo candidato do range é igualmente removível;
esta task faz com que os candidatos presentes em `required` nunca sejam oferecidos
para remoção, permanecendo em toda tentativa do range.

**Estado atual** (`replay_optimizer.py:184-207`):
```python
def _resolve_range(
        self, left: int, right: int, to_index: int, backbone: List[int],
        kept_so_far: List[int], success_criteria: List[SuccessCriterion],
) -> List[int]:
    if self._attempt(left, right, [], backbone, kept_so_far, to_index, success_criteria):
        return []

    candidates: List[int] = self._candidates_between(left, right)
    if not candidates or not self._attempt(left, right, candidates, backbone, kept_so_far, to_index, success_criteria):
        raise ReplayOptimizerAborted(
            f"ReplayOptimizer: faixa ({left}, {right}) falhou mesmo com todos os candidatos incluídos."
        )

    working: List[int] = list(candidates)
    for candidate in reversed(candidates):
        trial: List[int] = [c for c in working if c != candidate]
        if self._attempt(left, right, trial, backbone, kept_so_far, to_index, success_criteria):
            working = trial
    return working
```

**Estado esperado depois:**
```python
def _resolve_range(
        self, left: int, right: int, to_index: int, backbone: List[int],
        kept_so_far: List[int], success_criteria: List[SuccessCriterion], required: Set[int] = set(),
) -> List[int]:
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
- ⚠️ Com `required` vazio: `forced == []`, `optional == candidates_all`, e o
  algoritmo produz exatamente a mesma sequência de chamadas a `_attempt` e o mesmo
  retorno do código atual — isso é a garantia de não-regressão desta task, e deve
  ser coberta por teste explícito, não só assumida.
- ⚠️ A primeira tentativa passa a testar com `forced` (não mais `[]`) quando há
  candidatos obrigatórios no range — um range com candidatos obrigatórios nunca
  retorna `[]` mesmo que o "atalho sem nenhum candidato" teria passado, porque o
  atalho agora sempre inclui `forced`.
- ⚠️ Não alterar `_candidates_between` — ela continua devolvendo todo índice
  existente entre `left` e `right`, sem saber de `required`; a distinção é feita
  aqui, em `_resolve_range`.

**Critérios de aceite:**
- [x] Com `required=set()`: mesmo resultado do algoritmo atual num cenário já
      coberto por teste existente (ex.: um cenário equivalente a
      `test_run_phase2_elimination_keeps_only_the_necessary_candidate_closest_to_left`
      ou `test_range_without_candidates_shortcut_failure_aborts`, em
      `tests/unit/test_replay_optimizer.py` — confirmar nome exato no arquivo antes
      de reutilizar, não assumir que existe literalmente) — não-regressão.
- [x] Com `required={c}` onde `c` é um candidato do range que a busca *removeria*
      normalmente (i.e., o teste sem `required` já prova que `c` não é necessário):
      `_resolve_range(...)` inclui `c` no retorno mesmo assim.
- [x] Com `required` igual a todos os candidatos do range: `_resolve_range` retorna
      exatamente esses candidatos (todos), sem levantar `ReplayOptimizerAborted`,
      desde que a tentativa com todos presentes passe.
- [x] Com um candidato obrigatório que sozinho não muda se a faixa passa ou não
      (redundante): o resultado final ainda o inclui, e nenhum outro candidato
      necessário deixa de ser detectado (o laço guloso sobre `optional` continua
      funcionando igual).
- [x] `ReplayOptimizerAborted` continua sendo levantada quando nem com todos os
      candidatos (`candidates_all`) a faixa passa — comportamento de erro
      inalterado.

---

## [T05] — `ReplayOptimizer._reduce_anchors`: separar anchors `forced`/`removable`

**Depende de:** T03 (assinatura já recebe `required`).
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py`,
`tests/unit/test_replay_optimizer.py`.

**Contexto:**
Mesma ideia de T04, aplicada à fase final de redução de anchors. Spec seção 3.6.
Sem isso, um anchor que coincida com um índice `required` (ex.: o step de login,
quando o resolver o identificou como anchor) ainda poderia ser removido nesta fase,
mesmo protegido em `_resolve_range`.

**Estado atual** (`replay_optimizer.py:69-87`):
```python
def _reduce_anchors(
        self, anchors: List[int], from_index: int, to_index: int, kept: List[int],
        success_criteria: List[SuccessCriterion],
) -> List[int]:
    removable: List[int] = [anchor for anchor in anchors if anchor not in (from_index, to_index)]
    working: List[int] = list(removable)
    for anchor in reversed(removable):
        trial: List[int] = [a for a in working if a != anchor]
        trial_final_list: List[int] = sorted({from_index, to_index, *trial, *kept})
        if self._confirm(
                trial_final_list, to_index, success_criteria,
                restrict_backbone_feed_to=set(trial_final_list),
        ):
            working = trial
    return working
```

**Estado esperado depois:**
```python
def _reduce_anchors(
        self, anchors: List[int], from_index: int, to_index: int, kept: List[int],
        success_criteria: List[SuccessCriterion], required: Set[int] = set(),
) -> List[int]:
    forced: List[int] = [a for a in anchors if a not in (from_index, to_index) and a in required]
    removable: List[int] = [a for a in anchors if a not in (from_index, to_index) and a not in required]
    working: List[int] = list(removable)
    for anchor in reversed(removable):
        trial: List[int] = [a for a in working if a != anchor]
        trial_final_list: List[int] = sorted({from_index, to_index, *forced, *trial, *kept})
        if self._confirm(
                trial_final_list, to_index, success_criteria,
                restrict_backbone_feed_to=set(trial_final_list),
        ):
            working = trial
    return forced + working
```
- ⚠️ `trial_final_list` passa a incluir `*forced` sempre — sem isso, um anchor
  obrigatório sairia do `trial_final_list` testado e do retorno final, já que
  `working` nunca o conteria (ele é excluído de `removable` desde o início). É esse
  detalhe que faz a diferença entre "nunca testar remover" (objetivo) e
  "remover sem testar" (bug).
- ⚠️ Com `required` vazio: `forced == []`, comportamento idêntico ao atual —
  garantia de não-regressão, mesma lógica de T04.

**Critérios de aceite:**
- [x] Com `required=set()`: mesmo resultado do algoritmo atual no teste existente
      `test_reduce_anchors_removes_an_unnecessary_anchor` (ou nome equivalente já
      presente em `tests/unit/test_replay_optimizer.py`) — não-regressão.
- [x] Com um anchor `a` que o teste
      `test_reduce_anchors_does_not_remove_an_anchor_whose_cookie_the_target_genuinely_needs`
      (`tests/unit/test_replay_optimizer.py`) já prova ser necessário: continua
      sendo mantido mesmo sem estar em `required` (não-regressão do mecanismo
      existente).
- [x] Com `required={a}` onde `a` é um anchor que a busca *removeria* normalmente
      (cenário construído análogo ao teste de anchor desnecessário, mas com `a`
      declarado obrigatório): `_reduce_anchors` retorna `a` no resultado mesmo
      assim.
- [x] `from_index`/`to_index` continuam nunca aparecendo em `removable`/`forced`
      (já são sempre mantidos por fora, sem mudança nesta task).

---

## [T06] — `CliParser`: nova flag `--required-steps-file` em `optimize`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/cli/cli_parser.py`.

**Contexto:**
Expõe a feature na CLI. Spec seção 3.2. Task isolada e sem lógica — só argparse.

**Estado atual** (`cli_parser.py:86-110`):
```python
def _build_optimize_subparser(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
    optimize_parser: ArgumentParser = subparsers.add_parser("optimize")
    optimize_parser.add_argument("--output", required=True, help="Path to an existing workspace directory")
    optimize_parser.add_argument("--to", dest="to_index", type=int, required=True, help="Target step index")
    optimize_parser.add_argument(
        "--from", dest="from_index", type=int, default=0, help="Floor step index (default: 0)"
    )
    optimize_parser.add_argument("--config", help="Path to project config (JSON)")
    optimize_parser.add_argument(
        "--success-criteria",
        dest="success_criteria",
        default=None,
        help="Inline JSON list of SuccessCriterion, overrides config.json for this call",
    )
    optimize_parser.add_argument(
        "--steps-out", dest="steps_out", default=None, help="Custom output path for the optimized steps .txt"
    )
    optimize_parser.add_argument(
        "--max-requests",
        dest="max_requests",
        type=int,
        default=500,
        help="Worst-case request budget before aborting",
    )
    optimize_parser.set_defaults(func=self._handlers.handle_optimize)
```

**Estado esperado depois:**
Nova chamada `add_argument` antes de `set_defaults`:
```python
    optimize_parser.add_argument(
        "--required-steps-file",
        dest="required_steps_file",
        default=None,
        help="Path to a txt file with one required step index per line — never removed by the search",
    )
    optimize_parser.set_defaults(func=self._handlers.handle_optimize)
```
- Opcional (`default=None`) — ausência de flag preserva `args.required_steps_file
  is None`, o que T07 trata como "nenhum step obrigatório declarado".

**Critérios de aceite:**
- [x] `optimize --output X --to 5 --required-steps-file path.txt` parseia com
      `args.required_steps_file == "path.txt"`.
- [x] `optimize --output X --to 5` (sem a flag nova) parseia com
      `args.required_steps_file is None` — não-regressão de toda invocação
      existente de `optimize` sem a flag nova.

---

## [T07] — `CliHandlers.handle_optimize`: carregar, validar e repassar steps obrigatórios

**Depende de:** T01 (`parse_step_index_file`), T04 e T05 (o `ReplayOptimizer` já
precisa saber respeitar `required_steps` antes de esta task passar a fornecê-lo de
verdade), T06 (a flag já precisa existir para `args.required_steps_file` existir).
**Arquivos envolvidos:** `har_reproducer/cli/cli_handlers.py`,
`tests/test_cli_optimize.py`.

**Contexto:**
Fecha o encanamento ponta a ponta: lê o `.txt` de `--required-steps-file`, valida
contra o workspace e o range `[--from, --to]`, e repassa para
`ReplayOptimizer.optimize(...)`. Spec seção 3.3.

**Estado atual** (`cli_handlers.py:140-178, 194-201`):
```python
def handle_optimize(self, args: Namespace) -> bool:
    ...
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
    ...

@staticmethod
def _validate_optimize_from_index(runner: ReplayRunner, from_index: int) -> None:
    existing: Set[int] = set(runner.existing_step_indexes())
    if from_index not in existing:
        raise ValueError(
            f"ReplayOptimizer: step(s) [{from_index}] não existem no workspace (nenhum curl file em disco) — "
            f"provavelmente foram pulados por skip_rules ou estão fora do intervalo de steps existentes."
        )
```

**Estado esperado depois:**
```python
def handle_optimize(self, args: Namespace) -> bool:
    ...
    required_steps: Set[int] = self._load_required_steps(args.required_steps_file)
    self._validate_optimize_from_index(runner, args.from_index)
    self._validate_required_steps(runner, required_steps, args.from_index, args.to_index)

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
            workspace, run_id, args.from_index, args.to_index, success_criteria, output_path,
            required_steps=required_steps,
        )
    )
    ...

@staticmethod
def _load_required_steps(required_steps_file: Optional[str]) -> Set[int]:
    if not required_steps_file:
        return set()
    path: Path = Path(required_steps_file)
    try:
        return set(parse_step_index_file(path))
    except (FileNotFoundError, ValueError) as error:
        raise ValueError(f"--required-steps-file {path}: {error}") from error

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
- Import novo: `from har_reproducer.fs_io import parse_step_index_file` (acrescentar
  ao import já existente de `har_reproducer.fs_io` em `cli_handlers.py`).
- ⚠️ Ordem de validação: `_load_required_steps` primeiro (erro de arquivo/parsing é
  mais básico que erro de existência/range), depois `_validate_optimize_from_index`
  (já existe), depois `_validate_required_steps` — todas antes de instanciar
  `ReplayOptimizer`/rodar o proxy, para falhar rápido sem tráfego de rede.
- ⚠️ `required_steps` sempre passado por keyword (`required_steps=required_steps`)
  para `optimizer.optimize(...)`, não posicional — evita ambiguidade com
  `output_path`, que também é opcional.

**Critérios de aceite:**
- [x] `optimize --required-steps-file <arquivo com "3\n">` (índice `3` existente e
      dentro de `[--from, --to]`) roda sem erro e o `.txt` final inclui `3`, mesmo
      num cenário onde `3` seria removido sem a flag (teste de integração/CLI,
      similar aos já existentes em `tests/test_cli_optimize.py`).
- [x] `optimize --required-steps-file <arquivo com índice inexistente no workspace>`
      levanta `ValueError` mencionando o índice, antes de qualquer requisição de
      rede.
- [x] `optimize --required-steps-file <arquivo com índice fora de [--from, --to]>`
      levanta `ValueError` mencionando `--from`/`--to`.
- [x] `optimize --required-steps-file <caminho inexistente>` levanta `ValueError`
      mencionando o caminho do arquivo (não deixa `FileNotFoundError` cru
      propagar).
- [x] `optimize --required-steps-file <arquivo com linha "abc">` levanta
      `ValueError` mencionando o caminho do arquivo.
- [x] `optimize` sem `--required-steps-file` continua funcionando exatamente como
      hoje — toda a suíte `tests/test_cli_optimize.py` existente passa sem
      alteração (não-regressão).

---

## [T08] — Docs: `navigation-on-medical-portals.md` referencia `--required-steps-file`

**Depende de:** T07 (a feature precisa estar implementada e funcionando ponta a
ponta antes de recomendá-la como solução).
**Arquivos envolvidos:**
`.claude/skills/reproducao-de-har/references/navigation-on-medical-portals.md`.

**Contexto:**
O falso positivo do `optimize` em fluxos de login (commit `0eca890`) documentou o
problema e um contorno manual via `--from <login>` que descarta tudo antes do login,
inclusive o step 0 (sanity check do portal). Com a feature implementada, essa seção
ganha a solução direta. Sem mudança de código, só de doc — não segue TDD (skill
`spec-e-plano`, Passo 3, exceção de "mudanças de docs").

**Estado atual** (trecho relevante, adicionado no commit `0eca890`):
```markdown
  - Se precisar garantir os dois por fora do que a busca decide: rodar `optimize --from <índice do login>` protege o login e tudo abaixo dele como piso; devolver o step 0 manualmente e revalidar com `replay --mode list --steps-file` antes de aceitar o resultado.
```

**Estado esperado depois:**
Substituir esse bullet (mantendo o restante da seção "Fluxo de login" intacto) por
algo como:
```markdown
  - **Forma recomendada de garantir os dois sem sacrificar `--from`:** declarar o
    índice do step 0 e do login num `.txt` (um índice por linha) e passar via
    `optimize --required-steps-file <arquivo>` — o `ReplayOptimizer` nunca tenta
    remover esses índices, independente do que o resolver de tokens concluir
    sozinho. Preferível a `--from <índice do login>`, que descarta tudo antes do
    login (inclusive o próprio step 0).
```
- ⚠️ Não remover a explicação de *por que* o falso positivo acontece (parágrafos
  anteriores do bullet) — só a "forma de contornar" muda; o diagnóstico continua
  válido e é o que ajuda a decidir quando usar a flag nova.
- Referenciar esta task/spec no `git log` (mensagem de commit) para quem quiser
  entender a motivação completa, já que o texto da skill deve ficar curto e
  acionável (mesmo princípio de concisão das demais referências da skill).

**Critérios de aceite:**
- [x] O bullet de contorno manual (`--from <índice do login>` como única opção)
      não existe mais como *única* recomendação — `--required-steps-file` aparece
      como forma preferencial.
- [x] O restante da seção "Fluxo de login" (diagnóstico do falso positivo,
      checagem do `.txt` de saída, papel do step 0 como sanity check) permanece
      textualmente intacto.
