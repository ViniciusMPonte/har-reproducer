# Spec — Renomeação de `real_requests/` para `original_requests/`

## 0. Sumário e glossário

**Sumário:** o diretório de workspace hoje chamado `real_requests/` não guarda a
requisição "real" (a que foi de fato enviada, com tokens resolvidos) — guarda a
requisição **tal como estava gravada no HAR original**, sem nenhuma resolução.
Isso é inconsistente com o par `original_responses/`/`real_responses/`, onde
"original" e "real" têm significado preciso e opostos. Esta etapa renomeia o
diretório (e o enum/atributo de código correspondente) para `original_requests/`,
e atualiza todo texto vivo (README, skill operacional) que descreve essa
estrutura — sem alterar nenhum documento histórico de `docs/`, que descreve o
estado do projeto em cada momento passado e não deve ser reescrito.

**Glossário:**
- **Documento vivo**: texto que descreve o comportamento **atual** do projeto e
  deve acompanhar mudanças de código (`README.md`, `.claude/skills/*/SKILL.md`
  e seus `references/`). Contrasta com:
- **Documento histórico**: `spec.md`/`implementation_plan.md`/relatórios dentro
  de uma pasta `docs/AAAAMMDD .../` de uma etapa já fechada — registra a decisão
  tomada **naquele momento**, com o vocabulário e os nomes de então. Não é
  corrigido quando um nome muda depois, pelo mesmo motivo que uma ata de reunião
  não é reescrita quando a decisão nela registrada muda mais tarde.
- **Árvore golden**: a referência gravada em `tests/golden/<cenário>/` contra a
  qual `GoldenWorkspace.assert_matches` compara a saída de uma execução real do
  `har_reproducer` durante os testes — inclui a lista de arquivos/diretórios
  gerados e o conteúdo normalizado de cada um.
- **Captura real**: os arquivos crus (`real_requests/`/`real_responses/`/
  `original_responses/` de um workspace de verdade) usados por `tests/real/`
  para testar os mecanismos de produção contra dado de produção genuíno — nunca
  commitados (`tests/real/captures/` está no `.gitignore`).

## 1. Objetivo

Hoje, `har_reproducer/fs_io/workspace_dir.py` define
`WorkspaceDir.REAL_REQUESTS = "real_requests"`, e
`har_reproducer/engines/engine.py:87-88` grava ali a requisição de cada passo
**no mesmo momento e da mesma forma** que grava `original_responses/` — direto
do HAR, antes de qualquer análise de token ou resolução (`Engine._reproduce`,
`_persist_request_step` chamado antes de `TokenTracker.analyze_step`). Não
existe hoje nenhuma requisição "real" (resolvida, de fato enviada) persistida
como JSON — a requisição de fato enviada só existe como `.curl.sh` em `curls/`,
em formato diferente.

O nome `real_requests` sugere o oposto do conteúdo real do diretório, e quebra
a simetria que o restante do workspace estabelece:

| Prefixo | Significado em `*_responses/` | Significado em `*_requests/` (hoje) |
|---|---|---|
| `original_` | O que o HAR tinha gravado | **Não existe — deveria ser este** |
| `real_` | O que o servidor respondeu de fato, ao vivo | O que o HAR tinha gravado (**errado**) |

Um agente ou desenvolvedor que nunca leu o código conclui, pelo nome, que
`real_requests/` contém a requisição de fato enviada — e é justamente esse
mal-entendido que motivou esta etapa (identificado ao escrever
`.claude/skills/reproducao-de-har/references/workspace-structure.md`, que
precisou de uma ressalva textual para não repetir o engano).

**Fora de escopo:**
- Renomear o método `Workspace.request_file()`. Diferente de
  `response_file()`/`original_response_file()` (que precisam de dois nomes
  porque **duas** pastas de resposta coexistem), só existe uma pasta de
  requisição — não há ambiguidade a resolver, e `request_file()` continua
  correto e sem confusão depois da mudança.
- Editar qualquer documento histórico de `docs/` (ver glossário) — a lista
  completa dos textos que citam `real_requests`/`REAL_REQUESTS` e ficam
  intocados está na seção 5.
- Migrar capturas reais já existentes no disco de algum desenvolvedor
  (`tests/real/captures/`, não versionado) — ver seção 6.
- Qualquer mudança de comportamento do `har_reproducer` além do nome do
  diretório/enum — o conteúdo gravado, o formato do arquivo, e o momento em
  que é escrito continuam idênticos.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

- **`har_reproducer/fs_io/workspace_dir.py`** — `WorkspaceDir` é um `Enum` de
  string; cada membro é o nome literal de uma subpasta de `output/`:
  ```python
  class WorkspaceDir(str, Enum):
      CURLS = "curls"
      REAL_RESPONSES = "real_responses"
      ORIGINAL_RESPONSES = "original_responses"
      REAL_REQUESTS = "real_requests"
      EXTRACTORS = "extractors"
      TEMP_EXTRACTORS = "temp_extractors"
      MITM_CAPTURE = "mitm_capture"
      REPLAYS = "replays"
  ```
- **`har_reproducer/fs_io/workspace.py`** — `Workspace.__init__` materializa as
  oito subpastas eagerly, uma por membro do enum, cada uma num atributo público
  homônimo:
  ```python
  self.real_requests: Path = self._prepare_dir(WorkspaceDir.REAL_REQUESTS)
  ```
  e `request_file(index)` monta o caminho de um arquivo dentro dela:
  ```python
  def request_file(self, index: int) -> Path:
      return self.real_requests / f"req_{index:0{self.STEP_INDEX_WIDTH}d}.json"
  ```
- **`har_reproducer/engines/engine.py:108-110`** — `_persist_request_step`
  grava `step.request` (o `StepRequest` recém-parseado do HAR, sem nenhuma
  resolução de token) via `self.workspace.request_file(index)`, chamado antes
  de `self.tracker.analyze_step(step, first_entry)` — confirma que o conteúdo
  é sempre a versão original do HAR, nunca a requisição de fato enviada.
- **`har_reproducer/reproduction/request_url_scope.py:23`** e todo o restante
  do código de produção só acessam o arquivo via `workspace.request_file(index)`
  — nenhum outro ponto do pacote lê `workspace.real_requests`/
  `WorkspaceDir.REAL_REQUESTS` diretamente (confirmado por busca em todo
  `har_reproducer/`).
- **`tests/support/golden_workspace.py` (`GoldenWorkspace._record`)** — ao
  regravar uma referência golden (`HAR_REPRODUCER_UPDATE_GOLDEN=1`), primeiro
  apaga o diretório de referência inteiro (`shutil.rmtree`) e depois recria a
  partir do snapshot atual do workspace — ou seja, regenerar a suíte golden
  depois da mudança de código já renomeia a pasta em toda árvore de referência
  automaticamente, sem exigir `git mv` manual em cada uma das 25 pastas
  (listadas na seção 5).
- **`tests/real/support/capture_importer.py` (`CaptureImporter`)** — copia
  `real_requests/`/`real_responses/`/`original_responses/` de um workspace de
  origem (`run --mode main` de verdade) para `tests/real/captures/<domínio>__
  <data>/`, usando os nomes literais em `SUBDIRECTORIES`.
- **`tests/real/support/real_capture.py` (`RealCapture`)** — lê de volta essas
  capturas para os testes de `tests/real/`, com `self.real_requests_dir = 
  base_dir / "real_requests"` montado por string literal (não usa
  `WorkspaceDir`, porque lê uma captura já copiada em disco, não um
  `Workspace` construído em memória).

## 3. Decisões de arquitetura

### 3.1 Renomear o enum e o atributo de `Workspace`, manter o método

`WorkspaceDir.REAL_REQUESTS = "real_requests"` vira
`WorkspaceDir.ORIGINAL_REQUESTS = "original_requests"`; o atributo
`Workspace.real_requests` vira `Workspace.original_requests`. O método
`request_file()` mantém o nome (ver "Fora de escopo", seção 1) e só troca a
pasta que referencia internamente:

```python
def request_file(self, index: int) -> Path:
    return self.original_requests / f"req_{index:0{self.STEP_INDEX_WIDTH}d}.json"
```

Nenhum chamador de `request_file()` (produção ou teste) muda — a mudança é
inteiramente interna ao `Workspace`.

### 3.2 Regenerar a árvore golden em vez de editar manualmente

As 25 pastas de referência golden (`tests/golden/<cenário>/real_requests/`,
lista completa na seção 5) não são editadas à mão — depois da mudança de
código (3.1), rodar
`HAR_REPRODUCER_UPDATE_GOLDEN=1 uv run pytest --runslow` (comando já
documentado no `README.md`) regrava a árvore inteira a partir do
comportamento real do código já corrigido, incluindo o novo nome de pasta.
⚠️ Conferir o diff resultante antes de commitar: a única mudança esperada em
cada cenário é o nome do diretório (`real_requests/` → `original_requests/`)
com o mesmo conteúdo de arquivo — qualquer outra diferença no diff indica uma
regressão não relacionada a esta etapa introduzida sem querer.

### 3.3 Atualizar os dois consumidores de teste com path literal

`tests/test_cli_run.py:113` e o trio `tests/real/support/{capture_importer,
real_capture,test_real_capture}.py` (seção 2) usam a string literal
`"real_requests"` em vez de `WorkspaceDir`/`Workspace.request_file()`, porque
`tests/real/support/` lê uma captura já copiada em disco, não um `Workspace`
construído em memória — não há como reaproveitar o enum ali. Cada ocorrência
literal vira `"original_requests"` (e o atributo `RealCapture.real_requests_dir`
vira `RealCapture.original_requests_dir`, mesmo padrão de
`real_responses_dir`/`original_responses_dir` já existentes na mesma classe).

### 3.4 Documentos vivos: só os que descrevem o comportamento atual

Só três arquivos vivos citam `real_requests` (busca em `.md` de todo o
repositório, excluindo `docs/`): `README.md` (3 ocorrências: descrição do
`run`, descrição de `tests/real/`, e o exemplo de
`CaptureImporter.import_capture`) e
`.claude/skills/reproducao-de-har/references/workspace-structure.md` (a linha
da tabela que descreve essa pasta, escrita nesta mesma sessão). Nenhum outro
`SKILL.md`/`references/*.md` do projeto menciona `real_requests`/
`REAL_REQUESTS` (confirmado por busca) — `arquitetura-e-fundamentos/SKILL.md`
nunca chegou a listar essa pasta na sua enumeração de subdiretórios do
`Workspace`, então não precisa de correção por causa desta etapa (é uma lacuna
pré-existente e não relacionada — não faz parte desta spec corrigi-la).

### 3.5 Documentos históricos ficam intocados

22 arquivos dentro de `docs/AAAAMMDD .../` (fora desta própria pasta) citam
`real_requests`/
`REAL_REQUESTS` (specs, planos de implementação, relatórios de investigação de
etapas já fechadas). Nenhum é editado — são o registro do que existia e foi
decidido em cada momento passado, com o vocabulário de então; reescrevê-los
retroativamente para usar o nome novo falsificaria esse registro. A lista
completa está na seção 5, só para conferência de que a busca não deixou nada
de fora — não como lista de tasks.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `har_reproducer/fs_io/workspace_dir.py` | `REAL_REQUESTS = "real_requests"` → `ORIGINAL_REQUESTS = "original_requests"` |
| `har_reproducer/fs_io/workspace.py` | Atributo `self.real_requests` → `self.original_requests`; `request_file()` referencia o atributo novo (nome do método inalterado) |
| `tests/test_cli_run.py:113` | Literal `"real_requests"` → `"original_requests"` |
| `tests/real/support/capture_importer.py` | `SUBDIRECTORIES` troca `"real_requests"` por `"original_requests"` |
| `tests/real/support/real_capture.py` | `real_requests_dir` → `original_requests_dir` (atributo e uso em `step_request`) |
| `tests/real/support/test_real_capture.py` | Variável local `real_requests_dir` → `original_requests_dir` (mesmo comportamento testado) |
| `tests/golden/<25 cenários>/real_requests/` | Regeneradas via `HAR_REPRODUCER_UPDATE_GOLDEN=1 uv run pytest --runslow` (não editadas à mão) |
| `README.md` | 3 ocorrências de `real_requests` → `original_requests` (linhas 80, 204, 256 na versão atual) |
| `.claude/skills/reproducao-de-har/references/workspace-structure.md` | Linha da tabela (`real_requests/`) → `original_requests/`, texto da coluna "Conteúdo" ajustado se necessário |
| `docs/**` (22 arquivos históricos) | **Nenhuma mudança** — ver seção 3.5 |
| `tests/real/captures/**` (local, não versionado) | **Nenhuma mudança automática** — ver seção 6 |

## 5. Casos de borda e comportamento de erro

- **Regeneração golden traz mudança além do nome da pasta.** Se o diff do
  passo 3.2 mostrar qualquer coisa além da renomeação (conteúdo de arquivo
  diferente, arquivo novo/faltando em outro lugar), a implementação para e
  investiga antes de aceitar a regravação — não é esperado que a mudança desta
  etapa afete conteúdo, só o nome do diretório.
- **`tests/real/` sem captura local.** Os testes de `tests/real/` que
  dependem de uma captura em `tests/real/captures/` já são pulados
  automaticamente (`SKIPPED`) quando a pasta não existe (mecanismo já
  documentado no `README.md`) — não é um caso de erro novo introduzido por
  esta etapa, mas garante que a suíte de testes deste repositório passa mesmo
  sem nenhuma captura real local disponível pra validar 3.3 fim a fim.
- **`WorkspaceDir` é `str, Enum`.** Qualquer serialização que dependa do
  `.value` do enum (não encontrada em código de produção nesta investigação,
  mas vale a checagem durante a implementação) continuaria funcionando, pois o
  valor de string muda junto com o nome do membro — não há um caso de
  compatibilidade retroativa a preservar (workspaces antigos em disco com a
  pasta `real_requests/` física não são migrados automaticamente; ver seção 6).

## 6. Suposições e pontos a confirmar

- **Workspaces de HAR já existentes em disco** (fora de `tests/`, ex.: um
  workspace real criado por um agente seguindo `reproducao-de-har` antes desta
  mudança) continuam com a pasta física `real_requests/` no disco — o código
  novo, ao rodar `replay`/`optimize`/`extractor` sobre esse workspace antigo,
  vai procurar em `original_requests/` (vazia) em vez de `real_requests/`
  (com os arquivos). **Não há migração automática nesta etapa.** Se você já
  tiver workspaces reais em uso, confirme se quer um passo de migração
  (`git mv real_requests original_requests` dentro de cada `output/`
  existente) antes de considerar esta etapa fechada, ou se nenhum workspace
  real está em uso ainda e isso não se aplica.
- **`tests/real/captures/` local** (não versionado): se você tiver capturas
  já importadas no seu disco, elas continuam com `real_requests/` — o
  `CaptureImporter` novo vai procurar `original_requests/` na próxima
  importação a partir de um workspace de origem, mas não renomeia capturas já
  importadas. Mesma pergunta: vale um passo manual de `git mv` local (fora do
  repositório, então fora do plano de implementação) ou não há captura
  importada ainda?

## 7. Referência

Toda implementação desta spec segue `.claude/skills/guia-de-estilo/SKILL.md`.
