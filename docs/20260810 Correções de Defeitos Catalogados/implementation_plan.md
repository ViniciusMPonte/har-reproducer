# Plano de Implementação — Item 6: Nomes que mentem / efeitos colaterais fora de lugar

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `MitmProxyOrchestrator`: renomear `project_root` → `confdir`

**Depende de:** Nenhuma (Contexto de pré-requisito).
**Arquivos envolvidos:** `har_reproducer/reproduction/mitm_proxy_orchestrator.py` (MitmProxyOrchestrator), `tests/unit/test_mitm_proxy_orchestrator.py`

**Contexto:**
O parâmetro/atributo `project_root` de `MitmProxyOrchestrator` é um nome que mente:
os chamadores passam `project_config.ca_cert_path` (o `confdir` do mitmproxy, um
diretório de config) e o próprio `_build_command` o usa como `confdir`. O nome
sugere a raiz do projeto e esconde o papel real. A correção é só de nomenclatura —
nenhum comportamento muda (spec seção 3.1).

**Estado atual:**
- `mitm_proxy_orchestrator.py:26-30`:
  ```python
  def __init__(self, workspace: Workspace, proxy_port: Optional[int], project_root: Path) -> None:
      self.workspace: Workspace = workspace
      self.project_root: Path = project_root
      self.port: int = self._resolve_port(proxy_port)
      self.ca_cert_path: Path = self.project_root / self.CA_CERT_FILENAME
  ```
- `mitm_proxy_orchestrator.py:73`: `"--set", f"confdir={self.project_root}"`.
- `tests/unit/test_mitm_proxy_orchestrator.py:13` usa o keyword `project_root=tmp_path`.
- Os chamadores em produção (`cli_handlers.py:81-85,116-118`) passam posicionalmente — não mudam.

**Estado esperado depois:**
- Parâmetro e atributo viram `confdir`: `self.confdir: Path = confdir`, `self.ca_cert_path: Path = self.confdir / self.CA_CERT_FILENAME`.
- `_build_command` emite `f"confdir={self.confdir}"`.
- `self.ca_cert_path` mantém o nome (é o arquivo do certificado, nome honesto).
- `tests/unit/test_mitm_proxy_orchestrator.py:13` atualiza para `confdir=tmp_path`.
- Novos testes: (a) `_build_command()` contém o flag `confdir` com o valor passado; (b) `ca_cert_path` é `confdir / CA_CERT_FILENAME`.
- ⚠️ Não renomear `ProjectConfig.ca_cert_path` (chave do `config.json`, breaking change — spec §3.1).

**Critérios de aceite:**
- [x] `test_build_command_sets_confdir_to_confdir_argument`: `orchestrator._build_command()` contém `f"confdir={tmp_path}"`.
- [x] `test_ca_cert_path_is_derived_from_confdir`: `orchestrator.ca_cert_path == tmp_path / MitmProxyOrchestrator.CA_CERT_FILENAME`.
- [x] `grep -r "project_root" har_reproducer/` não retorna nada (a menos do README/docs, que não estão no escopo do grep de código).
- [x] Não-regressão: todos os testes de `tests/unit/test_mitm_proxy_orchestrator.py` passam.

## [T02] — `Workspace`/`MitmProxyOrchestrator`: mover criação de `.mitmproxy/` do load de config para o start do proxy

**Depende de:** Nenhuma (Contexto de pré-requisito).
**Arquivos envolvidos:** `har_reproducer/fs_io/workspace.py` (Workspace), `har_reproducer/reproduction/mitm_proxy_orchestrator.py` (MitmProxyOrchestrator), `tests/unit/test_workspace.py`, `tests/unit/test_mitm_proxy_orchestrator.py`

**Contexto:**
Carregar config cria `<repo>/.mitmproxy/` em disco como efeito colateral
(`ProjectConfigLoader._apply_defaults` → `Workspace.get_mitmproxy_ca_path()`, que
faz `mkdir`), mesmo em `dry` — que nunca sobe proxy. O `mkdir` sai do resolvedor de
caminho e vai para o `MitmProxyOrchestrator`, no momento em que o proxy realmente
sobe (spec seção 3.2).

**Estado atual:**
- `fs_io/workspace.py:30-34`:
  ```python
  @staticmethod
  def get_mitmproxy_ca_path() -> Path:
      path: Path = Workspace.get_root_path().parent / ".mitmproxy"
      path.mkdir(parents=True, exist_ok=True)
      return path
  ```
- `mitm_proxy_orchestrator.py:59-66`: `_start_process` abre o log e faz `Popen` do mitmdump sem garantir o confdir (a garantia hoje vem do load de config).
- `ProjectConfigLoader._apply_defaults` (`project_config_loader.py:35-38`) não muda de código — só deixa de ter efeito colateral.

**Estado esperado depois:**
- `get_mitmproxy_ca_path` vira só resolução de caminho (sem `mkdir`).
- `MitmProxyOrchestrator` ganha:
  ```python
  def _ensure_confdir(self) -> None:
      self.confdir.mkdir(parents=True, exist_ok=True)
  ```
  chamado na primeira linha de `_start_process`, antes de abrir o log/`Popen`.
- ⚠️ Criar em `_start_process`, não em `__init__`: o construtor deve continuar sem I/O (testável — spec §3.2).
- ⚠️ `mkdir(parents=True, exist_ok=True)` para confdir aninhado e já existente.

**Critérios de aceite:**
- [x] `test_get_mitmproxy_ca_path_does_not_create_directory` (`test_workspace.py`): gravar `exists()` antes de chamar; chamar `Workspace.get_mitmproxy_ca_path()`; `exists()` continua igual ao valor antes.
- [x] `test_init_does_not_create_confdir`: `MitmProxyOrchestrator(Workspace(tmp_path), proxy_port=8080, confdir=tmp_path / "nested" / "confdir")`; após o `__init__`, o diretório **não** existe.
- [x] `test_ensure_confdir_creates_directory`: mesmo orchestrator; após `_ensure_confdir()`, o diretório existe (`is_dir()`).
- [x] Não-regressão: `uv run pytest tests/ -q` passa — em particular os golden `run_dry_*` (que deixam de escrever no repo) e `run_main`/`replay` (que continuam criando `.mitmproxy/` via `_start_process`).

## [T03] — `BaseAgent.run_tdd_loop`: não dormir após o último attempt

**Depende de:** Nenhuma (Contexto de pré-requisito).
**Arquivos envolvidos:** `har_reproducer/agents/base_agent.py` (BaseAgent), `tests/unit/test_base_agent.py`

**Contexto:**
`run_tdd_loop` dorme 5s (`RETRY_DELAY_SECONDS`) após **toda** verificação que
falha, inclusive depois da última tentativa — quando não existe próximo attempt e o
loop termina falhando de qualquer forma. O sleep só faz sentido **entre** attempts
(spec seção 3.3).

**Estado atual:**
- `agents/base_agent.py:162-164`:
  ```python
  last_error = error
  print(f"Attempt {attempt + 1} failed for {self.token_id}. Retrying...")
  self.sleeper.sleep(self.RETRY_DELAY_SECONDS)
  ```
- `total` é `len(strategies)` ou `max_attempts` (`:139`); o `print` "Retrying..." permanece inalterado (contrato golden).

**Estado esperado depois:**
- `self.sleeper.sleep(...)` guardado por `if attempt < total - 1:` — dorme só se há próximo attempt.
- ⚠️ Não tocar no `print` (stdout golden dos `run_dry_*`) nem no `break` quando `generate_code` retorna `None`.

**Critérios de aceite:**
- [x] `test_run_tdd_loop_sleeps_only_between_failed_attempts`: agent com 3 estratégias que sempre falham (FakeScriptExecutor com 3 resultados de erro); `run_tdd_loop(origin_step=0)` retorna `None` e `len(sleeper.calls) == 2`. (Antes do fix: 3 calls.)
- [x] `test_run_tdd_loop_single_attempt_does_not_sleep`: agent com 1 estratégia que falha; `len(sleeper.calls) == 0`.
- [x] Não-regressão: `test_run_tdd_loop_succeeds_on_second_attempt_and_sleeps_once_between_attempts` (`test_base_agent.py:122-138`) continua com `len(sleeper.calls) == 1`; suíte completa passa.
