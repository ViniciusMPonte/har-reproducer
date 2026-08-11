# Plano de Implementação — Otimizador de Sequência Mínima de Replay

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `ReplayRunner`: `execute_schedule` (execução bruta) e parâmetro `annotate`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py`,
`tests/unit/test_replay_runner.py`

**Contexto:**
`_run_schedule` (linhas 63-84) hoje funde execução e veredito por comparador no
mesmo método, e `_run_step` (linhas 94-121) sempre anota o `.curl.sh` com
`- probably static`/`- could not extract value...` quando o resolver devolve tokens
estáticos/fallback. O `ReplayOptimizer` (tasks T06-T09) precisa de um jeito de
executar um schedule e receber as `StepResponse` de volta sem essa anotação — spec
seções 3.1 e 3.6.

**Estado atual:**
```python
def _run_step(self, index: int, schedule: Set[int]) -> StepResponse:
    ...
    if static_token_ids:
        self._annotate_static_tokens(index, static_token_ids)
    if fallback_token_ids:
        self._annotate_fallback_tokens(index, fallback_token_ids)
    ...

def _run_schedule(self, ordered_indexes: List[int], schedule: Set[int]) -> bool:
    if not ordered_indexes:
        raise ValueError("ReplayRunner: schedule vazio — nenhum step para processar.")
    results: List[Tuple[int, StepResponse, bool]] = []
    for index in ordered_indexes:
        response: StepResponse = self._run_step(index, schedule)
        results.append((index, response, self.comparator.matches_original(index, response)))
    ...
```

**Estado esperado depois:**
- `_run_step` ganha `annotate: bool = True`; só chama
  `_annotate_static_tokens`/`_annotate_fallback_tokens` quando `annotate` é `True`.
- Novo método público `execute_schedule(self, ordered_indexes: List[int], schedule: Set[int], annotate: bool = True) -> List[Tuple[int, StepResponse]]`
  — mesma guarda de `ordered_indexes` vazio (`ValueError`), devolve a lista de
  `(index, StepResponse)` na ordem de `ordered_indexes`, repassando `annotate` pra
  cada `_run_step`.
- `_run_schedule` passa a delegar: itera `self.execute_schedule(ordered_indexes, schedule)`
  (com `annotate=True` default, preservando o comportamento atual) e monta os
  `results` com `self.comparator.matches_original(...)` em cima do que
  `execute_schedule` devolveu — sem duplicar a chamada a `_run_step`.
- ⚠️ `run_all`/`run_slice`/`run_smart`/`run_list` não mudam de assinatura nem de
  comportamento observável — este é o ponto central de não-regressão da task.

**Critérios de aceite:**
- [x] `execute_schedule([], set())` levanta `ValueError` com a mesma mensagem que
  `_run_schedule([], set())` já levanta hoje.
- [x] `execute_schedule([2, 5], {2, 5})` devolve `[(2, StepResponse(...)), (5, StepResponse(...))]`
  na ordem dada, sem chamar `self.comparator`.
- [x] `execute_schedule(..., annotate=False)` com um `FakeReplayTokenResolver` que
  devolve `static_token_ids={"tok1"}` **não** altera o conteúdo do `.curl.sh` do step
  (garante que `_annotate_static_tokens` não foi chamada); com `annotate=True`
  (default), o `.curl.sh` é anotado como hoje.
- [x] Não-regressão: os testes já existentes de `test_replay_runner.py` para
  `run_all`/`run_slice`/`run_smart`/`run_list` (veredito via comparador, anotação de
  tokens estáticos/fallback, retry em 400/401) continuam passando sem alteração.

## [T02] — `ReplayRunner`: expõe `compute_smart_schedule` e `existing_step_indexes`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py`,
`tests/unit/test_replay_runner.py`

**Contexto:**
`_schedule_smart` (linhas 162-175) e `_existing_step_indexes` (linhas 203-209) são
privados. O `ReplayOptimizer` precisa pedir "qual é o schedule que o `smart` usaria"
(pra achar as âncoras) e "quais steps existem no workspace" (pra achar os candidatos
de cada faixa) sem disparar nenhuma execução — spec seção 3.2.

**Estado atual:**
```python
def _schedule_smart(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
    ...

def _existing_step_indexes(self) -> List[int]:
    ...
```

**Estado esperado depois:**
- `_schedule_smart` renomeado para público, `compute_smart_schedule`, implementação
  idêntica; `run_smart` chama `self.compute_smart_schedule(...)` no lugar de
  `self._schedule_smart(...)`.
- `_existing_step_indexes` renomeado para público, `existing_step_indexes`,
  implementação idêntica; todos os chamadores internos (`_schedule_all`,
  `_schedule_slice`, `_schedule_smart`/`compute_smart_schedule`, `_schedule_list`)
  atualizados pro novo nome.
- ⚠️ Puramente uma mudança de visibilidade — nenhuma mudança de comportamento.

**Critérios de aceite:**
- [x] `compute_smart_schedule(0, 6)` devolve exatamente o mesmo resultado que o
  `_schedule_smart(0, 6)` de antes da renomeação (teste de paridade, reaproveitando
  os casos já cobertos pelos testes existentes de `run_smart`).
- [x] `existing_step_indexes()` devolve a mesma lista ordenada que
  `_existing_step_indexes()` devolvia.
- [x] Não-regressão: `run_all`/`run_slice`/`run_smart`/`run_list` continuam
  passando sem alteração de comportamento.

## [T03] — `contracts.ScheduleExecutor`: `Protocol` para o `ReplayOptimizer` depender de

**Depende de:** T01, T02 (a assinatura exata que o `Protocol` declara vem de lá).
**Arquivos envolvidos:** `har_reproducer/contracts/schedule_executor.py` (novo),
`har_reproducer/contracts/__init__.py`, `tests/unit/test_schedule_executor_contract.py`
(novo)

**Contexto:**
O `ReplayOptimizer` (T06+) não deveria precisar montar um `ReplayRunner` completo
(com `SessionStore`, `CurlHttpTransport`, `MitmProxyOrchestrator`, etc.) pra ser
testado isoladamente — o mesmo problema que `HttpTransport`
(`har_reproducer/contracts/http_transport.py`) já resolve pra `ReplayRunner` hoje.
Não há decisão equivalente na spec (que só diz "usa uma única instância de
`ReplayRunner`", seção 3.3) — esta task formaliza isso como um `Protocol`, sem mudar
nenhum comportamento descrito na spec: `ReplayRunner` continua sendo a única
implementação real usada em produção (`handle_optimize`, T10), só que tipada pelo
`Protocol` na fronteira com `ReplayOptimizer`.

**Estado atual:**
Não existe.

**Estado esperado depois:**
```python
class ScheduleExecutor(Protocol):
    def execute_schedule(
            self, ordered_indexes: List[int], schedule: Set[int], annotate: bool = True
    ) -> List[Tuple[int, StepResponse]]: ...

    def compute_smart_schedule(
            self, from_index: Optional[int], to_index: Optional[int]
    ) -> Tuple[List[int], Set[int]]: ...

    def existing_step_indexes(self) -> List[int]: ...
```
`ReplayRunner` satisfaz este `Protocol` estruturalmente (duck typing, sem herança) —
mesmo padrão de `CurlHttpTransport` satisfazendo `HttpTransport` hoje.

**Critérios de aceite:**
- [x] Uma variável anotada como `ScheduleExecutor` recebe uma instância real de
  `ReplayRunner` sem erro de tipo (checagem estática/mypy, se o projeto rodar mypy;
  senão, um teste que chama os 3 métodos através da variável tipada e confirma que
  devolvem o que `ReplayRunner` devolveria diretamente).
- [x] Um `FakeScheduleExecutor` de teste (definido em `tests/support/`, usado a
  partir de T06) implementando só esses 3 métodos também satisfaz o `Protocol`.

## [T04] — `Workspace`: caminho do `.txt` de saída do otimizador

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/fs_io/workspace.py`,
`tests/unit/test_workspace.py` (criar se não existir)

**Contexto:**
Spec seção 3.4 — `Workspace` não tem um caminho pra "lista de steps otimizada"; o
`--steps-file` de `replay --mode list` hoje sempre aponta pra um arquivo que o
usuário escreveu à mão.

**Estado atual:**
`Workspace` tem `curl_file`, `replay_run_dir`, `replay_response_file`,
`response_file`/`original_response_file`, mas nenhum método para o `.txt` do
otimizador.

**Estado esperado depois:**
```python
def optimized_steps_file(self, run_id: str) -> Path:
    return self.replays / f"optimized_{run_id}.txt"
```
ao lado dos outros métodos de caminho.

**Critérios de aceite:**
- [x] `workspace.optimized_steps_file("run-1")` devolve
  `workspace.replays / "optimized_run-1.txt"`.
- [x] `optimized_steps_file("run-1")` e `optimized_steps_file("run-2")` devolvem
  caminhos diferentes (não sobrescreve otimização anterior).
- [x] Não-regressão: os outros métodos de caminho de `Workspace` (`curl_file`,
  `replay_run_dir`, etc.) continuam funcionando sem alteração.

## [T05] — `ExtractorMetadataStore`: variante silenciosa (sem persistir observação)

**Depende de:** Nenhuma.
**Arquivos envolvidos:**
`har_reproducer/reproduction/extractor_metadata_store.py`,
`tests/unit/test_extractor_metadata_store.py` (criar se não existir)

**Contexto:**
Spec seção 3.6, parte 1 — o `ReplayOptimizer` chama `ReplayTokenResolver.resolve`
(logo, `_record_observation`) muitas vezes numa única busca; sem isolamento, isso
infla `valid_count`/`ever_changed` persistidos em disco numa escala desproporcional
ao uso real. Esta task resolve só o **contador** — a anotação do `.curl.sh` em si é
resolvida à parte por T01 (`annotate=False`) e usada junto em T06.

**Estado atual:**
```python
class ExtractorMetadataStore:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace: Workspace = workspace

    def load(self, token_id: str) -> Optional[Extractor]:
        ...

    def save(self, extractor: Extractor) -> None:
        meta_file: Path = self.workspace.extractor_meta_file(extractor.token_id)
        meta_file.write_text(extractor.model_dump_json(indent=2), encoding="utf-8")
```

**Estado esperado depois:**
Nova subclasse no mesmo arquivo:
```python
class SilentExtractorMetadataStore(ExtractorMetadataStore):
    def save(self, extractor: Extractor) -> None:
        return None
```
`load` é reaproveitado sem alteração (herda de `ExtractorMetadataStore`).

**Critérios de aceite:**
- [x] `SilentExtractorMetadataStore(workspace).load(token_id)` devolve o mesmo
  `Extractor` que `ExtractorMetadataStore(workspace).load(token_id)` devolveria, para
  um `extract_*.meta.json` já existente no workspace.
- [x] Chamar `SilentExtractorMetadataStore(workspace).save(extractor)` não cria nem
  modifica `workspace.extractor_meta_file(extractor.token_id)` — o arquivo permanece
  exatamente como estava antes da chamada (ou continua inexistente, se nunca existiu).
- [x] Não-regressão: `ExtractorMetadataStore.save` (a classe base, usada por
  `replay`/`run` normalmente) continua persistindo em disco como hoje.

## [T06] — `ReplayOptimizer`: scaffolding + Fase 1 (backbone) + estimativa/teto de requisições

**Depende de:** T01, T02, T03, T04, T05.
**Arquivos envolvidos:** `har_reproducer/optimization/__init__.py` (novo),
`har_reproducer/optimization/replay_optimizer.py` (novo),
`tests/support/fake_schedule_executor.py` (novo),
`tests/unit/test_replay_optimizer.py` (novo)

**Contexto:**
Spec seção 3.3 (Fase 1) e 3.7 — primeira parte do componente novo. Antes de testar
qualquer faixa, o `ReplayOptimizer` precisa calcular as âncoras (`compute_smart_schedule`),
o `backbone` (`[from_index..B]`, com o caso degenerado `B = from_index` quando só há
uma âncora), rodar esse backbone ao vivo uma única vez (`execute_schedule` com
`annotate=False`), e calcular/imprimir a estimativa de custo antes de qualquer
requisição.

**Estado atual:**
Não existe.

**Estado esperado depois:**
```python
class ReplayOptimizer:
    def __init__(
            self,
            schedule_executor: ScheduleExecutor,
            metadata_store: SilentExtractorMetadataStore,
            max_requests: int = 500,
    ) -> None:
        self.schedule_executor = schedule_executor
        self.metadata_store = metadata_store
        self.max_requests = max_requests
        self.requests_made: int = 0

    def _compute_backbone(self, from_index: int, anchors: List[int]) -> List[int]:
        boundary = anchors[-2] if len(anchors) >= 2 else from_index
        return [i for i in self.schedule_executor.existing_step_indexes() if from_index <= i <= boundary]
```
(assinatura final do método público `optimize(...)` só fecha em T09, quando a Fase 2
e a confirmação final também existem — esta task só entrega a Fase 1 e a
infraestrutura de contagem/estimativa, testadas isoladamente.)

Cálculo de estimativa (seção 3.7): dado `anchors` e `existing_step_indexes()`, calcula
`k_i` por faixa (candidatos entre âncoras consecutivas, do alvo pro `from_index`) e
imprime `custo(faixa_i) ≈ (k_i + 2) × (k_i + kept_acumulado_i + 2)` somado ao tamanho
do backbone, com o aviso de que refreshes reativos não entram na conta.

**Critérios de aceite:**
- [x] `anchors = [0, 3, 6, 9]`, `from_index=0` → backbone calculado é
  `[0, 1, 2, 3, 4, 5, 6]` (todos os índices existentes entre `from_index` e `a_{n-1}=6`,
  inclusive) — usando um `FakeScheduleExecutor` com `existing_step_indexes` fixo.
- [x] `anchors = [9]` (âncora única), `from_index=0` → backbone calculado é `[0]`
  (caso degenerado, spec seção 3.3).
- [x] A Fase 1 chama `schedule_executor.execute_schedule(backbone, set(backbone), annotate=False)`
  exatamente uma vez — verificável inspecionando as chamadas registradas pelo
  `FakeScheduleExecutor`.
- [x] `requests_made` é incrementado pelo tamanho do backbone depois da Fase 1.
- [x] A estimativa impressa antes da Fase 1 contém o texto de aviso sobre refreshes
  reativos não entrarem na conta (verificável via `capsys`).
- [x] `FakeScheduleExecutor` (novo test double, em `tests/support/`) implementa
  `ScheduleExecutor` (T03) registrando cada chamada de `execute_schedule`
  (`ordered_indexes`, `schedule`, `annotate`) e devolvendo respostas configuráveis
  por chamada — é o que todas as tasks seguintes do otimizador reusam.

## [T07] — `ReplayOptimizer`: Fase 2 — atalho, faixa inteira, eliminação regressiva

**Depende de:** T06.
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py`,
`tests/unit/test_replay_optimizer.py`

**Contexto:**
Spec seção 3.3 (Fase 2) — o núcleo da busca. Processa as faixas do alvo pro
`from_index` (a mais próxima do alvo primeiro), testando pra cada uma o atalho de
duas pontas, depois a faixa inteira, depois eliminação regressiva candidato por
candidato (do mais próximo de `R` pro mais próximo de `L`). Ainda sem a recuperação
reativa (T08) — um `400`/`401`/`0` aqui, por ora, é tratado como falha de critério
normal (T08 refina isso).

**Estado atual:**
Só a Fase 1 (T06) existe.

**Estado esperado depois:**
Para cada faixa `(L, R)`, na ordem descrita na spec: monta `ordered_indexes`/`schedule`
conforme a fórmula da seção 3.3 (nunca inclui `L` nem nada à esquerda — só backbone
via `schedule`), chama `execute_schedule(..., annotate=False)`, aplica
`Validator.validate` na `StepResponse` do `to_index`. Devolve, ao final, `kept: List[int]`
— todos os candidatos sobreviventes de todas as faixas, e o conjunto de âncoras.

**Critérios de aceite:**
- [x] Faixa cujo atalho de duas pontas (`C=∅`) já sucede → `kept` da faixa é `[]`,
  só 1 chamada de `execute_schedule` pra essa faixa.
- [x] Faixa cujo atalho falha mas a faixa inteira sucede, e a eliminação encontra
  exatamente 1 candidato necessário (o mais próximo de `L`, testado por último) →
  `kept` da faixa contém só esse candidato, na ordem certa de tentativas (atalho →
  faixa inteira → remove o mais próximo de `R` primeiro, sucesso → remove o próximo,
  falha, restaura).
- [x] `ordered_indexes` de cada chamada dentro de uma faixa nunca contém `L` nem
  qualquer índice menor que `L` (verificável inspecionando as chamadas do
  `FakeScheduleExecutor`).
- [x] Faixas processadas em sequência incluem corretamente o `kept` da(s) faixa(s)
  já processada(s) em `ordered_indexes`/`schedule` das faixas seguintes (a faixa mais
  próxima do `from_index` "arrasta" os sobreviventes das faixas mais próximas do
  alvo).
- [x] Faixa sem candidatos (`R == L + 1`) é resolvida só com o atalho, sem chamada
  extra.

## [T08] — `ReplayOptimizer`: recuperação reativa (400/401/falha de transporte)

**Depende de:** T07.
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py`,
`tests/unit/test_replay_optimizer.py`

**Contexto:**
Spec seção 3.3 — quando um step do schedule volta com `status_code` em
`StepRetryPolicy.RECOVERABLE_STATUS_CODES ∪ {0}`, a tentativa atual é refeita depois
de reexecutar o backbone (Fase 1) de novo, até 2 vezes, antes de aceitar o resultado
como um veredito normal (sucesso/falha de critério) — nunca um caminho de abort
dedicado (⚠️ decisão já corrigida numa rodada de revisão da spec: ver seção 3.3,
"não distingue... por isso... não é tratado como um erro especial").

**Estado atual:**
Fase 2 (T07) aceita qualquer resultado do `Validator.validate` como definitivo, sem
checar `status_code` de nenhum step intermediário do schedule.

**Estado esperado depois:**
Ao redor de cada chamada de `execute_schedule` dentro da Fase 2 (e da Fase 1,
seção 3.3): se algum `(index, StepResponse)` do resultado tiver `status_code` em
`{400, 401, 0}`, reexecuta o backbone (`execute_schedule(backbone, ..., annotate=False)`,
incrementando `requests_made`) e repete a mesma tentativa (mesmo `ordered_indexes`/
`schedule` de antes) — até 2 vezes. Na 3ª ocorrência consecutiva, para de tentar
refresh e usa o resultado que saiu (que vai, naturalmente, contar como falha de
critério na lógica já existente da Fase 2 — T07).

**Critérios de aceite:**
- [x] Um `FakeScheduleExecutor` configurado para devolver `status_code=401` na 1ª
  chamada de uma tentativa e `status_code=200` (com body/status que satisfaz o
  `Validator`) na 2ª → a tentativa é refeita automaticamente (backbone reexecutado
  uma vez) e o resultado final é sucesso, sem consumir a lógica de "candidato
  necessário".
- [x] Um `FakeScheduleExecutor` configurado para devolver `401` em todas as
  tentativas (mesmo depois de 2 refreshes) → a 3ª falha consecutiva cai de volta no
  fluxo normal da Fase 2 — se for um teste de eliminação, o candidato é restaurado
  como necessário (mesmo caminho que uma falha de critério comum, T07); se for
  "faixa inteira", dispara o abort padrão da seção 5 da spec.
  cada refresh reexecuta exatamente o backbone (nem mais, nem menos índices).
- [x] `requests_made` conta os refreshes reativos (cada um soma `len(backbone)`).

## [T09] — `ReplayOptimizer`: montagem final, confirmação, escrita do `.txt`

**Depende de:** T04, T07, T08.
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py`,
`tests/unit/test_replay_optimizer.py`

**Contexto:**
Spec seção 3.3 (final) e 3.4 — depois de todas as faixas processadas, monta a lista
final (âncoras + `kept`), roda uma confirmação end-to-end do zero, e só escreve o
`.txt` (via `Workspace.optimized_steps_file`) se essa confirmação passar. Fecha a
assinatura pública do componente:
```python
def optimize(
        self, workspace: Workspace, run_id: str, from_index: int, to_index: int,
        success_criteria: List[SuccessCriterion],
) -> Optional[List[int]]:
    ...  # None se abortou; a lista final (já escrita em disco) se teve sucesso
```

**Estado atual:**
Fase 1 (T06) + Fase 2 com recuperação reativa (T07+T08) existem, mas nada monta a
lista final nem escreve o `.txt`.

**Estado esperado depois:**
- Lista final = `sorted({from_index} ∪ set(anchors) ∪ set(kept))`.
- Confirmação: `execute_schedule(lista_final, set(lista_final), annotate=False)`,
  aplica `Validator.validate` na resposta do `to_index` — sujeita à mesma
  recuperação reativa de T08.
- Sucesso → escreve `workspace.optimized_steps_file(run_id)` com um índice por
  linha (mesmo formato que `--mode list --steps-file` já consome,
  `CurlDependencyParser`/`ReplayRunner._schedule_list`), devolve a lista.
- Falha (mesmo depois dos refreshes) → não escreve arquivo, devolve `None`, loga a
  última faixa concluída com sucesso (seção 5 da spec).

**Critérios de aceite:**
- [x] Cenário de sucesso ponta a ponta (Fase 1 + Fase 2 + confirmação, usando
  `FakeScheduleExecutor`) → `.txt` escrito em `workspace.optimized_steps_file(run_id)`
  contém exatamente os índices esperados, um por linha, em ordem ascendente.
- [x] Confirmação final que falha (mesmo depois de faixas passarem individualmente)
  → nenhum arquivo é escrito, `optimize` devolve `None`.
- [x] Lista final nunca contém índice duplicado, mesmo quando âncoras/`kept`
  coincidem numericamente com o `to_index` (`to_index == from_index`, spec seção 5).

## [T10] — CLI: novo comando `optimize`

**Depende de:** T02, T05, T06, T09.
**Arquivos envolvidos:** `har_reproducer/cli/cli_parser.py`,
`har_reproducer/cli/cli_handlers.py`, `tests/test_cli_optimize.py` (novo)

**Contexto:**
Spec seção 3.5 — quarto subcomando, seguindo o padrão de `handle_replay`/
`_build_replay_subparser`. Monta o `ReplayOptimizer` com os mesmos componentes que
`_build_replay_runner` já monta pro `ReplayRunner` (agora incluindo
`SilentExtractorMetadataStore` de T05 no lugar de `ExtractorMetadataStore`), dentro
do mesmo `orchestrator.run(...)`.

**Estado atual:**
`CliParser.build` monta 3 subcomandos (`parse`/`run`/`replay`); não há `optimize`.

**Estado esperado depois:**
- `_build_optimize_subparser`: `--output` (obrigatório), `--to` (obrigatório),
  `--from` (opcional, default `0`), `--config` (opcional), `--success-criteria`
  (opcional, JSON de lista), `--steps-out` (opcional), `--max-requests` (opcional,
  default `500`).
- `handle_optimize`:
  - valida workspace (mesmo padrão de `_prepare_replay_workspace`);
  - valida `from_index` existente no workspace (⚠️ checagem que `compute_smart_schedule`
    não faz hoje — spec seção 5);
  - resolve `success_criteria`: `--success-criteria` (parseado como lista de
    `SuccessCriterion`) se informado, senão `project_config.success_criteria`; recusa
    rodar (`ValueError`) se a lista final estiver vazia;
  - monta `ReplayOptimizer` com `SilentExtractorMetadataStore(workspace)` e o
    `--max-requests` informado;
  - roda dentro de `orchestrator.run(...)`, imprime o resultado
    (`optimize.py`-style: caminho do `.txt` em caso de sucesso, motivo do abort em
    caso de falha).

**Critérios de aceite:**
- [x] `optimize --output <ws> --to 9` (sem `--config` nem `--success-criteria`, e
  `config.json` do workspace com `success_criteria` vazio ou ausente) → levanta
  `ValueError` antes de qualquer requisição de rede.
- [x] `optimize --output <ws> --to 9 --from 999` (`999` não existe no workspace) →
  erro explícito, mesmo padrão de mensagem que `ReplayRunner._require_all_existing`.
- [x] `optimize --output <ws> --to 9 --success-criteria '[{"type":"status_code","expected":200}]'`
  sobrescreve o `success_criteria` do `config.json` só para essa chamada.
- [x] `--steps-out <path>` customizado é respeitado; sem a flag, cai no default de
  `Workspace.optimized_steps_file(run_id)`.
- [x] Teste de integração (mesmo padrão de `test_cli_replay.py`, usando
  `CannedHttpServer`/`GoldenWorkspaceFactory`) cobrindo o caminho feliz de ponta a
  ponta contra um workspace golden simples (todas as âncoras bastam, nenhum
  candidato necessário) — cobertura de fiação (workspace → `ReplayOptimizer` →
  `.txt`), não do algoritmo de busca em si (já coberto por unitários em T06-T09). ⚠️
  Um golden cobrindo o caso "candidato de efeito colateral realmente necessário"
  exigiria um servidor de teste com estado (o `CannedHttpServer` atual é stateless,
  keyed só por `(method, path)`) — está fora do escopo desta task; a spec não pede
  esse nível de golden, e a lógica correspondente já tem cobertura unitária
  suficiente via `FakeScheduleExecutor` (T07/T08).
