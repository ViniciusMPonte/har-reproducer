# Plano de Implementação — Renomeação de `real_requests/` para `original_requests/`

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

**Assunção herdada da spec (seção 6, não respondida explicitamente):** este plano
assume que não há workspace real nem captura local (`tests/real/captures/`) a
migrar manualmente. Se algum existir, a migração (`git mv real_requests
original_requests` dentro do `output/` daquele workspace, ou da pasta da captura)
fica fora deste plano — nenhuma task abaixo cobre isso.

⚠️ **Estado transiente esperado entre T01 e T03:** depois de T01 (código de
produção renomeado), a comparação de árvore golden dentro de
`test_run_dry_skip_rules_methods` (e de qualquer outro cenário golden) vai
falhar — o workspace gerado já tem `original_requests/`, mas a referência
gravada em `tests/golden/` ainda tem `real_requests/` até T03 regenerá-la. Isso
é esperado; não é uma regressão a investigar antes de T03.

## T01 — `WorkspaceDir`/`Workspace`: renomear `real_requests` para `original_requests`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/fs_io/workspace_dir.py` (`WorkspaceDir`),
`har_reproducer/fs_io/workspace.py` (`Workspace`), `tests/test_cli_run.py`
(único teste de produção com o path literal `"real_requests"`).

**Contexto:**
`WorkspaceDir.REAL_REQUESTS = "real_requests"` nomeia uma pasta que guarda a
requisição tal como veio do HAR (sem resolução de token) — o mesmo tipo de
conteúdo que `ORIGINAL_RESPONSES` guarda do lado da resposta. O nome atual
sugere "a requisição de fato enviada", que não é o que a pasta contém (spec
seção 1). `Workspace.request_file()` é o único ponto de leitura/escrita dessa
pasta usado pelo resto do código de produção — nenhum outro consumidor acessa
`workspace.real_requests`/`WorkspaceDir.REAL_REQUESTS` diretamente.

**Estado atual:**
```python
# workspace_dir.py
class WorkspaceDir(str, Enum):
    ...
    REAL_REQUESTS = "real_requests"
    ...

# workspace.py
self.real_requests: Path = self._prepare_dir(WorkspaceDir.REAL_REQUESTS)
...
def request_file(self, index: int) -> Path:
    return self.real_requests / f"req_{index:0{self.STEP_INDEX_WIDTH}d}.json"
```
```python
# tests/test_cli_run.py:113
real_request: str = (output_dir / "real_requests" / "req_0003.json").read_text(encoding="utf-8")
```

**Estado esperado depois:**
- `WorkspaceDir.REAL_REQUESTS` renomeado para `WorkspaceDir.ORIGINAL_REQUESTS = "original_requests"` (membro removido, não mantido como alias).
- `Workspace.real_requests` renomeado para `Workspace.original_requests`, construído a partir de `WorkspaceDir.ORIGINAL_REQUESTS`.
- `Workspace.request_file()` **mantém o nome** (não há segunda pasta de requisição a desambiguar, diferente de `response_file()`/`original_response_file()`) — só troca `self.real_requests` por `self.original_requests` no corpo.
- `tests/test_cli_run.py:113` passa a ler `output_dir / "original_requests" / "req_0003.json"`.
- [⚠️] Nenhum outro arquivo de `har_reproducer/` acessa o atributo/enum antigo diretamente (confirmado por busca antes desta task — só `request_file()` é usado externamente); se a implementação encontrar outro ponto, ele entra nesta mesma task, não numa task nova.

**Critérios de aceite:**
- [ ] `WorkspaceDir.ORIGINAL_REQUESTS.value == "original_requests"`; `WorkspaceDir` não tem mais nenhum membro `REAL_REQUESTS`.
- [ ] `Workspace(tmp_path).original_requests == tmp_path / "original_requests"` (pasta física criada nesse caminho).
- [ ] `Workspace(tmp_path).request_file(3) == tmp_path / "original_requests" / "req_0003.json"`.
- [ ] `uv run pytest tests/test_cli_run.py` passa 100% (inclui `test_run_dry_skip_rules_methods`, que lê o path literal).
- [ ] Garantia de não-regressão: `uv run pytest tests/unit` continua 100% verde — nenhum teste unitário referencia `real_requests`/`REAL_REQUESTS` diretamente (todos usam `request_file()`), então nenhum deveria quebrar.
- [ ] Cenários golden **não** precisam passar ainda nesta task (ver nota de estado transiente acima) — só rodar `tests/test_cli_run.py`, `tests/unit`, não a suíte golden inteira.

## T02 — `RealCapture`/`CaptureImporter`: renomear `real_requests` para `original_requests`

**Depende de:** Nenhuma (arquivos independentes de T01 — não importam `WorkspaceDir`, leem uma captura já copiada em disco).
**Arquivos envolvidos:** `tests/real/support/real_capture.py` (`RealCapture`),
`tests/real/support/capture_importer.py` (`CaptureImporter`),
`tests/real/support/test_real_capture.py`.

**Contexto:**
`tests/real/` testa os mecanismos de produção contra captura real de site,
copiada previamente por `CaptureImporter` a partir de um workspace de `run
--mode main`. Como esse código lê uma pasta já materializada em disco (não
constrói um `Workspace` em memória), ele usa a string literal `"real_requests"`
em vez do enum — precisa ser atualizado em paralelo a T01 para continuar
lendo/copiando do nome de pasta correto depois da mudança.

**Estado atual:**
```python
# real_capture.py
self.real_requests_dir: Path = base_dir / "real_requests"
...
path: Path = self.real_requests_dir / f"req_{index:0{self.STEP_INDEX_WIDTH}d}.json"

# capture_importer.py
SUBDIRECTORIES: ClassVar[Tuple[str, ...]] = ("real_requests", "real_responses", "original_responses")

# test_real_capture.py
real_requests_dir: Path = base_dir / "real_requests"
```

**Estado esperado depois:**
- `RealCapture.real_requests_dir` → `RealCapture.original_requests_dir` (mesmo padrão de nome de `real_responses_dir`/`original_responses_dir`, já existentes na classe).
- `CaptureImporter.SUBDIRECTORIES` → `("original_requests", "real_responses", "original_responses")`.
- `tests/real/support/test_real_capture.py` usa `original_requests_dir` no helper `_write_step_request` — o comportamento testado (reconstrução de `StepRequest`, propagação de `FileNotFoundError`) não muda, só o nome da pasta usada para escrever a amostra.

**Critérios de aceite:**
- [ ] `RealCapture(tmp_path).original_requests_dir == tmp_path / "original_requests"` — não existe mais `real_requests_dir` na classe.
- [ ] `CaptureImporter.SUBDIRECTORIES == ("original_requests", "real_responses", "original_responses")`.
- [ ] `uv run pytest tests/real/support/test_real_capture.py` passa 100%.
- [ ] Garantia de não-regressão: `uv run pytest -m real_capture` continua se comportando igual a antes desta task (sem captura local em `tests/real/captures/`, tudo `SKIPPED`; migração de captura já existente está fora do escopo, ver nota de assunção no topo deste plano).

## T03 — Regenerar a árvore golden com o novo nome de pasta

**Depende de:** T01 (o comportamento do `run`/`replay`/`optimize` que a árvore golden registra só muda depois do rename de produção).
**Arquivos envolvidos:** as 25 pastas afetadas em `tests/golden/<cenário>/real_requests/` → `tests/golden/<cenário>/original_requests/` (lista completa: `run_main`, `run_dry_reset_removes_litter`, `replay_ref_fallback`, `criteria_body_contains_success`, `criteria_status_code_success`, `replay_list_out_of_order`, `replay_smart_to_4`, `run_dry_skip_rules_methods`, `replay_slice_full`, `criteria_html_element_present_failure`, `run_dry_default`, `run_auth_flow`, `replay_smart_to_6`, `criteria_body_contains_failure`, `replay_list_asc`, `criteria_empty_list`, `replay_smart_noflag`, `replay_all`, `criteria_html_element_present_success`, `replay_slice_0_3`, `criteria_status_code_failure`, `replay_dry_ref_fallback`, `criteria_url_match_success`, `criteria_url_match_failure`, `replay_smart_from_3`).

**Contexto:**
`GoldenWorkspace._record` (`tests/support/golden_workspace.py`) apaga o
diretório de referência inteiro e recria a partir do snapshot do workspace
atual sempre que `HAR_REPRODUCER_UPDATE_GOLDEN=1` está setado — não é preciso
(nem desejável) editar essas 25 pastas manualmente; regenerar e conferir o
diff é a validação, no mesmo espírito da carve-out de TDD já prevista pra
"regeneração de golden" (`spec-e-plano/SKILL.md`, Passo 3 — não há red/green
aqui, a comparação de árvore já é a verificação).

**Estado atual:** as 25 pastas listadas acima têm uma subpasta `real_requests/`.

**Estado esperado depois:** a mesma subpasta passa a se chamar
`original_requests/`, com o mesmo conteúdo de arquivo — nenhuma outra
diferença em nenhum cenário.

**Passos:**
```bash
HAR_REPRODUCER_UPDATE_GOLDEN=1 uv run pytest --runslow
git diff --stat tests/golden/     # conferir ANTES de confiar no resultado
uv run pytest --runslow            # sem a env var — suíte inteira precisa passar depois
```

**Critérios de aceite:**
- [ ] `git diff --stat tests/golden/` mostra, para cada uma das 25 pastas, só a renomeação `real_requests/...` → `original_requests/...` — nenhum outro arquivo criado, removido ou com conteúdo alterado.
- [ ] `uv run pytest --runslow` (sem `HAR_REPRODUCER_UPDATE_GOLDEN`) passa 100% depois da regravação.
- [ ] Garantia de não-regressão: `uv run pytest` (suíte padrão, sem `--runslow`) também passa 100%.

## T04 — `README.md`: atualizar as menções a `real_requests`

**Depende de:** T01 (o README passa a descrever o comportamento já corrigido).
**Arquivos envolvidos:** `README.md` (3 ocorrências: descrição de `run`, seção
`tests/real/`, exemplo de uso de `CaptureImporter`).

**Contexto:**
`README.md` é a documentação viva do comportamento atual do CLI — as três
menções a `real_requests` (linhas 80, 204, 256 na versão anterior a este
plano) descrevem exatamente o que T01 e T02 mudam, e ficariam desatualizadas
sem este ajuste.

**Estado atual (trechos relevantes):**
```
Gera em `<output>/`: `real_requests/` (requests tal como no HAR), ...
...
`real_requests/`/`real_responses/`/`original_responses/` de um workspace real...
...
Isso copia `real_requests/`, `real_responses/` e `original_responses/` do workspace de...
```

**Estado esperado depois:** as três ocorrências usam `original_requests/` no
lugar de `real_requests/` — nenhuma outra palavra do texto ao redor muda (a
descrição "requests tal como no HAR" já estava correta, só o nome da pasta
estava errado).

**Critérios de aceite:**
- [ ] `grep -n "real_requests" README.md` não retorna nenhuma linha.
- [ ] As três frases (seção `run`, seção `tests/real/`, exemplo de `CaptureImporter`) usam `original_requests/` e continuam gramaticalmente corretas (conferir manualmente, não é só um replace mecânico de substring — “`real_requests/`/`real_responses/`/`original_responses/`” tem barras entre nomes, cuidado para não quebrar a lista).

## T05 — `reproducao-de-har`: atualizar `workspace-structure.md`

**Depende de:** T01 (o texto passa a refletir o nome novo).
**Arquivos envolvidos:**
`.claude/skills/reproducao-de-har/references/workspace-structure.md` (tabela
"As oito pastas que `run` materializa em `<output>/`").

**Contexto:**
Esse texto foi escrito nesta mesma sessão, antes de identificar o problema de
nomenclatura — a linha da tabela que descreve essa pasta usa o nome antigo.
Nenhum outro `SKILL.md`/`references/*.md` do projeto menciona
`real_requests`/`REAL_REQUESTS` (confirmado na spec, seção 3.4).

**Estado atual:**
```
| `real_requests/` | `req_NNNN.json` — a requisição de cada passo, tal como estava no HAR (sem tokens resolvidos) | `run` | Nunca (um `run` sempre grava todas) |
```

**Estado esperado depois:**
```
| `original_requests/` | `req_NNNN.json` — a requisição de cada passo, tal como estava no HAR (sem tokens resolvidos) | `run` | Nunca (um `run` sempre grava todas) |
```
Só o nome da pasta muda — a descrição da coluna "Conteúdo" já estava correta
(é exatamente por isso que o nome antigo era enganoso).

**Critérios de aceite:**
- [ ] `grep -rn "real_requests" .claude/skills/reproducao-de-har/` não retorna nenhuma linha.
- [ ] A tabela em `workspace-structure.md` lista `original_requests/` no lugar de `real_requests/`, com o resto da linha inalterado.
- [ ] Nenhuma outra seção do arquivo (ex.: "Como usar essa tabela nas outras etapas da skill") precisa de ajuste — conferir que nenhuma delas cita `real_requests` por fora da tabela (não deveria, mas vale conferir antes de fechar a task).
