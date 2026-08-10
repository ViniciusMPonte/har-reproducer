# Spec — Item 6: Nomes que mentem / efeitos colaterais fora de lugar

> Fonte: `lista_de_bugs.md` item 6 (três casos, todos "ainda existem"). Origem
> primária: `docs/20260806 Rede de Caracterização Golden/spec.md` §6.6.
> Os itens 1–5 da lista já foram corrigidos nesta branch; esta spec cobre só o item 6.

## 1. Objetivo

O item 6 cataloga três defeitos de qualidade de código (nenhum bug de comportamento
na rede golden, mas custos reais de manutenção e de execução):

1. **6a — `MitmProxyOrchestrator.project_root` é um nome que mente.**
   `har_reproducer/reproduction/mitm_proxy_orchestrator.py:26-30` recebe um
   parâmetro chamado `project_root` que na prática é o `confdir` do mitmproxy: os
   chamadores (`har_reproducer/cli/cli_handlers.py:81-85` e `:116-118`) passam
   `project_config.ca_cert_path`, que é o **diretório** de config do mitmproxy
   (default `<repo>/.mitmproxy`), e o próprio `_build_command`
   (`mitm_proxy_orchestrator.py:73`) usa `f"confdir={self.project_root}"`. O nome
   sugere a raiz do projeto e esconde o papel real do valor.
2. **6b — carregar config cria `.mitmproxy/` em disco como efeito colateral.**
   `ProjectConfigLoader._apply_defaults`
   (`har_reproducer/config/project_config_loader.py:35-38`) chama
   `Workspace.get_mitmproxy_ca_path()` (`har_reproducer/fs_io/workspace.py:31-34`),
   que faz `mkdir(parents=True, exist_ok=True)` de `<repo>/.mitmproxy`. Como
   `ProjectConfigLoader.load` é chamado incondicionalmente em `handle_run`
   (`cli_handlers.py:45`) e `handle_replay` (`cli_handlers.py:112`), até `run
   --mode dry` — que nunca sobe proxy — grava um diretório na raiz do repositório.
3. **6c — `BaseAgent.run_tdd_loop` dorme 5s após o último attempt que já vai
   falhar.** `har_reproducer/agents/base_agent.py:164` executa
   `self.sleeper.sleep(self.RETRY_DELAY_SECONDS)` em **todo** caminho de falha do
   loop, inclusive depois da última tentativa, quando não existe próximo attempt.

Custo de não corrigir: 6a engana quem lê o código (atributo que parece guardar a
raiz do projeto é um diretório do mitmproxy); 6b escreve no repositório do usuário
sem necessidade (efeito colateral fora de lugar, quebra o princípio de "carregar
config não deve ter efeitos de I/O"); 6c paga 5s de `time.sleep` real por
resolução fracassada, exatamente o caminho mais comum (fallback literal).

Escopo: os **três** casos de 6a/6b/6c. Fica **fora**:
- Renomear `ProjectConfig.ca_cert_path` (campo do `config.json` — quebra de
  formato; ver §3.1).
- O padrão análogo de "sleep no último attempt" em
  `CurlHttpTransport._read_captured_response`
  (`har_reproducer/reproduction/curl_http_transport.py:64-70`) — não catalogado no
  item 6 e congelado por teste existente
  (`tests/unit/test_curl_http_transport.py:67-76`, que espera 5 sleeps para 5
  attempts).
- Qualquer coisa dos demais itens da lista (7, 8, 9, 10).

## 2. Componentes existentes reaproveitados (estado atual)

### 2.1 `MitmProxyOrchestrator` — `har_reproducer/reproduction/mitm_proxy_orchestrator.py`

```python
def __init__(self, workspace: Workspace, proxy_port: Optional[int], project_root: Path) -> None:
    self.workspace: Workspace = workspace
    self.project_root: Path = project_root
    self.port: int = self._resolve_port(proxy_port)
    self.ca_cert_path: Path = self.project_root / self.CA_CERT_FILENAME
```

- `:30` deriva o caminho do certificado como `confdir / mitmproxy-ca-cert.pem`
  (`CA_CERT_FILENAME`, `:16`).
- `:73` monta o flag do mitmdump: `"--set", f"confdir={self.project_root}"`.
- `_start_process` (`:59-66`) abre o log e faz `subprocess.Popen` do mitmdump — é o
  ponto onde a rede passa a ser usada de fato.
- `_build_command`/`_build_env`/`_wait_until_ready`/`_terminate` são os demais
  colaboradores, testados em `tests/unit/test_mitm_proxy_orchestrator.py` (que
  constrói o orchestrator com `project_root=tmp_path` em `:13`).

Os dois chamadores em produção passam **posicionalmente**: `_run_with_proxy`
(`cli_handlers.py:81-85`) e `handle_replay` (`cli_handlers.py:116-118`) fazem
`MitmProxyOrchestrator(workspace, project_config.proxy_port, project_config.ca_cert_path)`.
Rename de parâmetro, portanto, não muda nenhuma chamada em produção.

### 2.2 `ProjectConfigLoader` — `har_reproducer/config/project_config_loader.py`

```python
@staticmethod
def load(config_path: Optional[Path]) -> ProjectConfig:
    config: ProjectConfig = ProjectConfigLoader._load_raw(config_path)
    return ProjectConfigLoader._apply_defaults(config)

@staticmethod
def _apply_defaults(config: ProjectConfig) -> ProjectConfig:
    if config.ca_cert_path is None:
        config.ca_cert_path = Workspace.get_mitmproxy_ca_path()
    return config
```

- `ProjectConfig.ca_cert_path` (`har_reproducer/models/config.py:24`) é
  `Optional[Path]`; o README (`:148`) o documenta como "diretório de configuração
  do mitmproxy (`confdir`), de onde é lido o certificado `mitmproxy-ca-cert.pem`".
- O único consumidor do campo em produção é o próprio `MitmProxyOrchestrator` via
  `cli_handlers` (§2.1).

### 2.3 `Workspace.get_mitmproxy_ca_path` — `har_reproducer/fs_io/workspace.py:30-34`

```python
@staticmethod
def get_mitmproxy_ca_path() -> Path:
    path: Path = Workspace.get_root_path().parent / ".mitmproxy"
    path.mkdir(parents=True, exist_ok=True)
    return path
```

- É um `@staticmethod` puro de resolução de caminho **exceto** pelo `mkdir` na
  linha 33, que é o efeito colateral denunciado em 6b.
- Só tem um chamador: `ProjectConfigLoader._apply_defaults` (§2.2).

### 2.4 `BaseAgent.run_tdd_loop` — `har_reproducer/agents/base_agent.py:131-167`

```python
for attempt in range(total):
    code: Optional[str] = self.generate_code(last_error=last_error)
    if code is None:
        break
    success, error = self._verify_code(code)
    if success:
        ... return Extractor(...)
    last_error = error
    print(f"Attempt {attempt + 1} failed for {self.token_id}. Retrying...")
    self.sleeper.sleep(self.RETRY_DELAY_SECONDS)
```

- `total` é `len(strategies)` ou o `max_attempts` recebido (`:139`).
- O `sleep` (`:164`, `RETRY_DELAY_SECONDS = 5` em `:18`) roda após **toda**
  verificação que falha — inclusive quando `attempt == total - 1`, onde o loop
  termina logo em seguida.
- Teste existente que o fix não pode quebrar:
  `test_run_tdd_loop_succeeds_on_second_attempt_and_sleeps_once_between_attempts`
  (`tests/unit/test_base_agent.py:122-138`) espera exatamente 1 sleep para uma
  falha seguida de sucesso.

## 3. Decisões de arquitetura

### 3.1 Renomear `project_root` → `confdir` em `MitmProxyOrchestrator`

O valor recebido e armazenado é o diretório de config do mitmproxy (o mesmo
`confdir` do flag `--set confdir=...`). O nome do atributo deve dizer isso.

Estado atual:

```python
def __init__(self, workspace: Workspace, proxy_port: Optional[int], project_root: Path) -> None:
    self.workspace: Workspace = workspace
    self.project_root: Path = project_root
    self.port: int = self._resolve_port(proxy_port)
    self.ca_cert_path: Path = self.project_root / self.CA_CERT_FILENAME
```

Estado esperado:

```python
def __init__(self, workspace: Workspace, proxy_port: Optional[int], confdir: Path) -> None:
    self.workspace: Workspace = workspace
    self.confdir: Path = confdir
    self.port: int = self._resolve_port(proxy_port)
    self.ca_cert_path: Path = self.confdir / self.CA_CERT_FILENAME
```

- `_build_command` (`:73`) passa a `f"confdir={self.confdir}"`.
- `self.ca_cert_path` mantém o nome — esse sim é o caminho do arquivo de
  certificado, nome honesto.
- Os chamadores em `cli_handlers` não mudam (passagem posicional).
- `tests/unit/test_mitm_proxy_orchestrator.py:13` atualiza o keyword:
  `project_root=tmp_path` → `confdir=tmp_path`.
- `ProjectConfig.ca_cert_path` **não** muda de nome: é chave do formato de
  `config.json`, renomeá-la quebra configs de usuário sem ganho proporcional. Fica
  documentado no README como o confdir (já está, `README.md:148`).

Alternativa descartada: manter `project_root` e só adicionar um comentário — viola
o guia de estilo (zero comentários) e não resolve a mentira do nome.

### 3.2 Tirar o `mkdir` de `.mitmproxy/` do caminho de carregamento de config

O defeito é duplo: o `mkdir` está num método que deveria só resolver caminho
(`Workspace.get_mitmproxy_ca_path`) **e** é alcançado pelo carregamento de config,
que roda em `dry`. A correção move a criação do diretório para o único lugar onde
ele é necessário: o momento em que o proxy vai subir.

Estado atual — `fs_io/workspace.py:30-34`:

```python
@staticmethod
def get_mitmproxy_ca_path() -> Path:
    path: Path = Workspace.get_root_path().parent / ".mitmproxy"
    path.mkdir(parents=True, exist_ok=True)
    return path
```

Estado esperado — `get_mitmproxy_ca_path` volta a ser puramente resolução de
caminho:

```python
@staticmethod
def get_mitmproxy_ca_path() -> Path:
    return Workspace.get_root_path().parent / ".mitmproxy"
```

O `mkdir` migra para `MitmProxyOrchestrator` (`reproduction/mitm_proxy_orchestrator.py`),
como método novo chamado no início de `_start_process`:

```python
def _start_process(self) -> subprocess.Popen:
    self._ensure_confdir()
    self._log_file = open(self.workspace.mitm_log_file(), "w", encoding="utf-8")
    return subprocess.Popen(...)

def _ensure_confdir(self) -> None:
    self.confdir.mkdir(parents=True, exist_ok=True)
```

Consequências observáveis (todas intencionais):
- `run --mode dry` deixa de criar `<repo>/.mitmproxy/`.
- `run --mode main` e `replay` continuam criando o diretório — agora no
  `_start_process`, imediatamente antes do `mitmdump`, preservando a garantia de
  que o confdir existe quando o mitmdump sobe (o `mitmproxy` grava
  `mitmproxy-ca-cert.pem` ali; a primeira rodada de rede gera o certificado).
- `handle_replay` (`cli_handlers.py:112`) chama `ProjectConfigLoader.load` sem
  efeitos colaterais; o diretório nasce quando `orchestrator.run` → `_start_process`.

Escolha de onde criar o diretório: `_start_process`, não `__init__`, para manter o
construtor livre de I/O (testável: `__init__` não cria nada, `_ensure_confdir`
cria) e alinhado ao princípio do guia de estilo de bordas de I/O no ponto de uso.

### 3.3 Não dormir após o último attempt de `run_tdd_loop`

Estado atual (`agents/base_agent.py:162-164`):

```python
last_error = error
print(f"Attempt {attempt + 1} failed for {self.token_id}. Retrying...")
self.sleeper.sleep(self.RETRY_DELAY_SECONDS)
```

Estado esperado — dorme só se ainda existe um próximo attempt:

```python
last_error = error
print(f"Attempt {attempt + 1} failed for {self.token_id}. Retrying...")
if attempt < total - 1:
    self.sleeper.sleep(self.RETRY_DELAY_SECONDS)
```

- O `print` **não muda**: faz parte do contrato de stdout dos golden tests
  (`run_dry_*` comparam o texto do `stdout.txt`).
- Quando `generate_code` retorna `None` (estratégias esgotadas), o loop faz
  `break` sem dormir — comportamento inalterado.
- Com `total == 1`, não há sleep algum (antes: 1 sleep desperdiçado).

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `MitmProxyOrchestrator` (`reproduction/mitm_proxy_orchestrator.py`) | `project_root` → `confdir` (param + atributo, `:26-30`, `:73`); novo `_ensure_confdir()` chamado no início de `_start_process` |
| `Workspace.get_mitmproxy_ca_path` (`fs_io/workspace.py:30-34`) | Remove o `mkdir`; volta a ser só resolução de caminho |
| `ProjectConfigLoader._apply_defaults` (`config/project_config_loader.py:35-38`) | Sem mudança de código — passa a ser puro porque o `mkdir` saiu de `get_mitmproxy_ca_path` |
| `BaseAgent.run_tdd_loop` (`agents/base_agent.py:162-164`) | Guarda o `sleep` com `if attempt < total - 1` |
| `cli_handlers.py` (`:81-85`, `:116-118`) | Sem mudança (passagem posicional) |
| `tests/unit/test_mitm_proxy_orchestrator.py` | Keyword `project_root=` → `confdir=`; novos testes de 6a e 6b |
| `tests/unit/test_workspace.py` | Novo teste de pureza de `get_mitmproxy_ca_path` |
| `tests/unit/test_base_agent.py` | Novo teste: sleep só entre attempts |

## 5. Casos de borda e comportamento de erro

| # | Caso | Comportamento esperado |
|---|---|---|
| 1 | 6a: chamadores passam `config.ca_cert_path` explícito ou default | Ambos são caminhos de diretório; `confdir` os aceita sem validação nova (o mitmdump que valida o conteúdo) |
| 2 | 6b: confdir já existe | `_ensure_confdir` com `exist_ok=True` é no-op |
| 3 | 6b: confdir aninhado não existente | `parents=True` cria a cadeia inteira |
| 4 | 6b: `dry` | Nunca toca `.mitmproxy/` — é o objetivo do fix |
| 5 | 6b: `replay` e `main` | `.mitmproxy/` criado em `_start_process`, antes do `mitmdump` — comportamento preservado |
| 6 | 6c: `total == 1` | Zero sleeps (antes: 1 desperdiçado) |
| 7 | 6c: `generate_code` retorna `None` antes do fim | `break` sem sleep — inalterado |
| 8 | 6c: último attempt falha e estrategias esgotadas | `total - 1` sleeps ao todo; o `print` "Retrying..." permanece mesmo no último attempt (contrato golden) |

## 6. Suposições e pontos a confirmar

1. **`ProjectConfig.ca_cert_path` mantém o nome.** Também é um "nome que mente"
   (guarda o confdir, não o arquivo), mas é chave pública do `config.json` e está
   documentada no README (`:148`). Recomenda-se não renomear nesta etapa; se a
   intenção for renomear, é uma mudança de formato de config que precisa de spec
   própria.
2. **`_read_captured_response` fica de fora.** Mesmo padrão de sleep-no-último-
   attempt, mas não está no item 6 e o comportamento está congelado pelo teste
   `test_read_captured_response_gives_up_after_max_attempts` (5 sleeps/5 attempts).
3. **O print "Attempt N failed … Retrying..." permanece mesmo no último attempt.**
   Alternativa seria suprimi-lo, mas isso altera o stdout golden dos `run_dry_*` —
   fora do escopo do item 6c, que só denuncia o sleep.

## 7. Referência

Todo código desta etapa, inclusive em `tests/`, segue
`.claude/skills/guia-de-estilo/SKILL.md`: tipagem explícita, `ClassVar` para
constantes, `Path` para caminhos, zero comentários/docstrings, guard clauses,
dependências por construtor. Fórmula de tarefa e formato de commit seguem
`.claude/skills/spec-e-plano/SKILL.md`.
