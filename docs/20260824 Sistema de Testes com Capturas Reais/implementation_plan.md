# Plano de Implementação — Sistema de Testes com Capturas Reais

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

⚠️ **T04 é uma exceção à regra "uma task, um commit"** (Passo 3 da skill `spec-e-plano`):
ela popula `tests/real/captures/`, que é gitignored por T03 — não há nada para `git add`.
T04 não gera commit nenhum; seu critério de aceite é verificado rodando T05 e confirmando
que o teste **não** pula.

⚠️ **T01 e T02 não seguem TDD com par red→green.** Nenhuma classe de apoio deste projeto
(`tests/support/golden_workspace.py`, `har_materializer.py`, `fake_extractor_runner.py`,
etc.) tem teste unitário próprio isolado — todas são exercitadas indiretamente pelos testes
que as consomem (`grep -rl` confirma: nenhum `test_golden_workspace*`/`test_har_materializer*`
existe no repo). T01 abre uma exceção pontual e justificada (ver a própria T01), mas T02
segue o padrão estabelecido — sem teste próprio, exercitada por T04/T05.

## [T01] — `RealCapture`: carrega `Step`/`StepRequest` real a partir de disco

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/real/support/real_capture.py` (novo, classe `RealCapture`),
`tests/real/support/test_real_capture.py` (novo, teste unitário).

**Contexto:**
Hoje não existe nenhuma classe que reconstrua um `Step`/`StepRequest` real a partir de um
`req_XXXX.json` gravado em disco — `ResponseCorpus` (`tracking/response_corpus.py`) já faz
o equivalente para respostas (dict cru), mas não há simétrico para requests. `RealCapture` é
essa peça, e é o componente central desta etapa: toda captura real passa por ela.

**Estado atual:**
- `har_reproducer.models.http.StepRequest` (`models/http.py:7-13`) é o mesmo tipo que
  `Engine._persist_request_step` (`engines/engine.py:107-108`) grava via
  `request.model_dump_json(indent=2)` em `real_requests/req_XXXX.json`.
- `har_reproducer.fs_io.workspace.Workspace.STEP_INDEX_WIDTH: ClassVar[int] = 4`
  (`fs_io/workspace.py:9`) já é a convenção de largura do índice — `RealCapture` reusa essa
  constante, não duplica o número mágico.
- Nenhuma classe expõe `real_requests_dir`/`real_responses_dir`/`original_responses_dir` de
  uma pasta arbitrária prontos para consumo por `ResponseCorpus` (que já aceita qualquer
  diretório, sem exigir workspace de produção).

**Estado esperado depois:**

```python
from pathlib import Path
from typing import ClassVar

from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import Step, StepRequest


class RealCapture:

    STEP_INDEX_WIDTH: ClassVar[int] = Workspace.STEP_INDEX_WIDTH

    def __init__(self, base_dir: Path) -> None:
        self.base_dir: Path = base_dir
        self.real_requests_dir: Path = base_dir / "real_requests"
        self.real_responses_dir: Path = base_dir / "real_responses"
        self.original_responses_dir: Path = base_dir / "original_responses"

    def step_request(self, index: int) -> StepRequest:
        path: Path = self.real_requests_dir / f"req_{index:0{self.STEP_INDEX_WIDTH}d}.json"
        return StepRequest.model_validate_json(path.read_text(encoding="utf-8"))

    def step(self, index: int) -> Step:
        return Step(index=index, request=self.step_request(index))
```

⚠️ `step_request`/`step` propagam qualquer exceção de leitura/parsing sem capturar — não é
borda de I/O de produção coberta pela regra de `except Exception` amplo do guia de estilo
(`spec.md` §3.2). Um teste real que não encontra o arquivo esperado deve falhar alto, não
degradar para `None`.

⚠️ Exceção pontual ao padrão "sem teste próprio para classe de apoio" (ver nota no topo do
plano): `RealCapture` ganha um teste unitário com dado **sintético e fabricado** (não uma
captura real) porque é o único componente novo desta etapa cuja lógica (parsing de
`StepRequest` a partir de JSON) é genuinamente testável isoladamente sem precisar de
nenhuma captura real — ao contrário de `CaptureImporter` (T02), que só faz sentido operando
sobre uma árvore de diretórios real. `tests/real/support/test_real_capture.py` grava um
`StepRequest` fabricado num `tmp_path`, via `model_dump_json`, e confirma que
`RealCapture.step_request`/`step` o reconstrói de volta — mesmo padrão de `tmp_path` já
usado em `tests/unit/test_candidate_resolver.py`.

**Critérios de aceite:**
- [x] `RealCapture(base_dir).step_request(12)` lê `base_dir/real_requests/req_0012.json` e
  devolve um `StepRequest` com os mesmos campos gravados.
- [x] `RealCapture(base_dir).step(12)` devolve um `Step` com `index == 12` e `.request`
  igual ao de `step_request(12)`.
- [x] `RealCapture(base_dir).real_responses_dir == base_dir / "real_responses"` (idem para
  `original_responses_dir`) — sem exigir que os diretórios existam no disco (só formata o
  `Path`, não valida presença).
- [x] Ler um índice cujo arquivo não existe propaga `FileNotFoundError` (não retorna `None`
  nem imprime aviso).
- [x] `py_compile` limpo em `real_capture.py` e `test_real_capture.py`.

## [T02] — `CaptureImporter`: copia uma captura real para `tests/real/captures/`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `tests/real/support/capture_importer.py` (novo, classe
`CaptureImporter`).

**Contexto:**
Sem isso, povoar `tests/real/captures/<domínio>__<data>/` exigiria copiar
`real_requests/`/`real_responses/`/`original_responses/` arquivo por arquivo à mão a cada
nova captura — `CaptureImporter` mecaniza essa cópia (spec §3.5).

**Estado atual:** Não existe. Nenhum componente do projeto copia subárvores de um workspace
de `--output` para outro lugar — o mais próximo é `shutil.rmtree`/`mkdir` dentro de
`GoldenWorkspace._record` (`tests/support/golden_workspace.py`), que grava uma referência
golden, não uma captura real.

**Estado esperado depois:**

```python
import shutil
from datetime import date
from pathlib import Path
from typing import ClassVar, Tuple


class CaptureImporter:

    SUBDIRECTORIES: ClassVar[Tuple[str, ...]] = ("real_requests", "real_responses", "original_responses")

    def __init__(self, captures_root: Path) -> None:
        self.captures_root: Path = captures_root

    def import_capture(self, workspace_output_dir: Path, domain: str, captured_on: date) -> Path:
        destination: Path = self.captures_root / f"{domain}__{captured_on:%Y%m%d}"
        for subdirectory in self.SUBDIRECTORIES:
            shutil.copytree(
                workspace_output_dir / subdirectory, destination / subdirectory, dirs_exist_ok=True
            )
        return destination
```

⚠️ Não valida que `domain` bate com o conteúdo copiado, nem que `workspace_output_dir`
tem as três subpastas — deixa `shutil.copytree` propagar `FileNotFoundError` se uma faltar
(spec §5, "casos de borda"). Não é um subcomando de `har_reproducer.main`: é utilitário de
teste, invocado manualmente por quem estiver importando uma captura nova, fora do fluxo de
`pytest` (spec §3.5).

**Critérios de aceite:**
- [x] `CaptureImporter(tmp_path / "captures").import_capture(origin_dir, "example.com", date(2026, 8, 24))`
  cria `tmp_path/captures/example.com__20260824/` com as três subpastas copiadas.
- [x] Rodar `import_capture` duas vezes com o mesmo domínio/data funde por cima
  (`dirs_exist_ok=True`) — arquivos de mesmo nome são sobrescritos, arquivos que só existem
  numa das duas cópias sobrevivem (spec §5).
- [x] `workspace_output_dir` sem uma das três subpastas propaga `FileNotFoundError` — não
  cai num estado parcial silencioso.
- [x] `py_compile` limpo.

## [T03] — `tests/real/conftest.py`: diretório de capturas, marcador e fixture de skip gracioso

**Depende de:** T01 (usa `RealCapture` como tipo de retorno da fixture).
**Arquivos envolvidos:** `tests/real/conftest.py` (novo), `.gitignore` (+1 linha).

**Contexto:**
É aqui que a captura vira, de fato, opt-in por presença de arquivo: um teste que precisa de
uma captura real pede a fixture correspondente, que pula (`pytest.skip`) se a pasta não
existir localmente — sem precisar de uma flag de CLI nova, ao contrário de `--runslow`
(spec §3.4, que já justifica a diferença: lá é escolha do usuário, aqui é disponibilidade de
dado).

**Estado atual:**
- `.gitignore` (raiz do projeto) não tem entrada para `tests/real/captures/` — a pasta, uma
  vez criada por T04, seria rastreada pelo git.
- `tests/conftest.py` define o padrão de referência a replicar: `OfflineFixtureConfig` como
  classe de `ClassVar` (`FIXTURES_DIR`, `GOLDEN_DIR`), `pytest_addoption`/
  `pytest_collection_modifyitems` para o marcador `slow` (`tests/conftest.py:17-36`).
- Não existe `tests/real/` nem `tests/real/conftest.py`.

**Estado esperado depois:**

`.gitignore`, nova linha:
```
tests/real/captures/
```

`tests/real/conftest.py`:

```python
from pathlib import Path
from typing import ClassVar

import pytest

from tests.real.support.real_capture import RealCapture


class RealFixtureConfig:
    CAPTURES_DIR: ClassVar[Path] = Path(__file__).parent / "captures"


class UnimedriopretoCaptureConfig:
    FOLDER_NAME: ClassVar[str] = "autorizador.unimedriopreto.com.br__20260824"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "real_capture: usa dados reais de tests/real/captures/")


@pytest.fixture
def real_captures_dir() -> Path:
    return RealFixtureConfig.CAPTURES_DIR


@pytest.fixture
def unimedriopreto_20260824_capture(real_captures_dir: Path) -> RealCapture:
    base_dir: Path = real_captures_dir / UnimedriopretoCaptureConfig.FOLDER_NAME
    if not base_dir.exists():
        pytest.skip(f"captura real ausente em {base_dir} — rode CaptureImporter para importá-la")
    return RealCapture(base_dir)
```

⚠️ O marcador `real_capture` é só para filtragem/relatório (`pytest -m real_capture`) — quem
decide pular é a fixture, pela presença do diretório, não o marcador (spec §3.4). Isso é
diferente do padrão `slow`, onde `pytest_collection_modifyitems` decide o skip a partir da
flag `--runslow`; aqui não há `pytest_collection_modifyitems` correspondente, de propósito.

**Critérios de aceite:**
- [x] `git check-ignore -v tests/real/captures/qualquer_coisa` confirma que a nova linha do
  `.gitignore` cobre a pasta.
- [x] Um teste que pede `unimedriopreto_20260824_capture` sem a pasta existir no disco é
  reportado como `SKIPPED`, com a mensagem citando o caminho ausente — não `FAILED`, não
  `ERROR`.
- [x] `pytest --collect-only -m real_capture` não lança (marcador registrado, sem
  `PytestUnknownMarkWarning`).
- [x] `pytest tests/` inteiro continua com o mesmo `438 passed, 19 skipped` de antes desta
  task, mais os novos testes de T01 — nada existente regride.

## [T04] — Importar a captura real de `autorizador.unimedriopreto.com.br` de 24/08/2026

**Depende de:** T02 (`CaptureImporter`), T03 (`.gitignore` já cobre o destino antes de
qualquer arquivo real tocar o disco rastreado pelo git).
**Arquivos envolvidos:** Nenhum arquivo versionado — só `tests/real/captures/autorizador.unimedriopreto.com.br__20260824/` (gitignored, local).

**Contexto:**
Task puramente operacional, não gera commit (ver ⚠️ no topo do plano). Popula o disco local
com a captura real que T05 vai consumir — usando o workspace de `--output` que o usuário já
gerou (`run --mode main` sobre `progressofit.har`, 233 entries,
`autorizador.unimedriopreto.com.br`).

**Estado atual:** `tests/real/captures/` não existe (nem rastreado, nem no disco).

**Estado esperado depois:** rodar, a partir da raiz do projeto:

```python
from datetime import date
from pathlib import Path

from tests.real.support.capture_importer import CaptureImporter

CaptureImporter(Path("tests/real/captures")).import_capture(
    workspace_output_dir=Path("<caminho do --output real do usuário>"),
    domain="autorizador.unimedriopreto.com.br",
    captured_on=date(2026, 8, 24),
)
```

`tests/real/captures/autorizador.unimedriopreto.com.br__20260824/` passa a existir, com
`real_requests/`, `real_responses/` e `original_responses/` — 233 arquivos cada, espelhando
o workspace de origem.

**Critérios de aceite:**
- [x] A pasta existe no disco local com as três subpastas e 233 arquivos em cada.
- [x] `git status` não lista nada em `tests/real/captures/` (confirma que o `.gitignore` de
  T03 realmente cobre) — nenhum `git add`/commit associado a esta task.
- [x] T05 (próxima task), depois desta, roda sem pular.

## [T05] — Primeiro teste real: cookie de sessão do login (step 124), captura de 24/08

**Depende de:** T01, T03, T04.
**Arquivos envolvidos:** `tests/real/test_candidate_resolver_unimedriopreto.py` (novo).

**Contexto:**
Prova de que o sistema funciona ponta a ponta: usa `RealCapture` para carregar o request
real do login (step `124`) e o baseline real (step `0`) da captura de
`autorizador.unimedriopreto.com.br__20260824`, produz o candidato via `BaselineDiff` real
(mesma classe de produção, não dublê), e resolve esse candidato via `CandidateResolver` real
contra o `original_responses/` real da mesma captura. É um **teste de caracterização**
(glossário da spec) — documenta o comportamento atual (`"Static"`, sem extrator), não a
regra de negócio corrigida (fora de escopo desta etapa, spec §0).

**Estado atual:** Não existe nenhum teste que exercite este mecanismo com dado real — a
única tentativa (hardcoded, sem uso de captura real) foi descartada nesta mesma etapa antes
da spec.

**Estado esperado depois:**

```python
from typing import List

import pytest

from har_reproducer.models import DynamicToken
from har_reproducer.session import SessionStore
from har_reproducer.tracking.baseline_diff import BaselineDiff
from har_reproducer.tracking.candidate_resolver import CandidateResolver
from har_reproducer.tracking.flow_vocabulary import FlowVocabulary
from har_reproducer.tracking.response_corpus import ResponseCorpus
from tests.real.support.real_capture import RealCapture
from tests.support.fake_extractor_runner import FakeExtractorRunner
from tests.support.fake_metadata_store import FakeMetadataStore


LOGIN_STEP_INDEX: int = 124
SESSION_COOKIE_ORIGIN_STEP_INDEX: int = 12


@pytest.mark.real_capture
def test_login_session_cookie_is_marked_static_against_the_real_capture(
        unimedriopreto_20260824_capture: RealCapture,
) -> None:
    diff: BaselineDiff = BaselineDiff()
    diffs = diff.compare(
        unimedriopreto_20260824_capture.step(LOGIN_STEP_INDEX),
        unimedriopreto_20260824_capture.step(0),
    )
    candidates: List[DynamicToken] = diff.detect_candidates(diffs)
    candidate: DynamicToken = next(c for c in candidates if c.path == "cookie:JSESSIONID")

    discovery_corpus = ResponseCorpus(unimedriopreto_20260824_capture.original_responses_dir, RealCapture.STEP_INDEX_WIDTH)
    execution_corpus = ResponseCorpus(unimedriopreto_20260824_capture.real_responses_dir, RealCapture.STEP_INDEX_WIDTH)
    resolver = CandidateResolver(
        discovery_corpus, ..., SessionStore(), FakeExtractorRunner(), FakeMetadataStore(), ..., execution_corpus,
    )

    resolved = resolver.resolve([candidate], LOGIN_STEP_INDEX)

    assert resolved[0].status == "Static"
    assert resolved[0].origin_step == SESSION_COOKIE_ORIGIN_STEP_INDEX
```

⚠️ O esboço acima omite `OriginFinder`/`AgentFactory` reais por brevidade — a task implementa
com os colaboradores de produção de verdade (`OriginFinder(discovery_corpus, FlowVocabulary())`,
`AgentFactory` real), não dublês, exceto `FakeExtractorRunner`/`FakeMetadataStore` (que não
têm papel neste caminho — o candidato nunca chega a `_generate_new_extractor`) — mesmo padrão
de dublê mínimo já usado em `tests/unit/test_candidate_resolver.py`.

⚠️ Este teste usa `execution_corpus` apontando para `real_responses/` **da captura real**,
não para um diretório vazio — diferente da tentativa hardcoded descartada, que usava um
`execution_corpus` vazio para forçar o caminho `if not execution_text: return True`. Rodar
contra a captura real de verdade é o que decide, sem suposição, qual dos dois caminhos do
código realmente dispara (`candidate_resolver.py:75-81`) — e é exatamente essa ambiguidade,
não resolvida na investigação anterior a esta etapa, que esta task finalmente fecha com
dado real, não com hipótese.

**Critérios de aceite:**
- [x] Com a captura de T04 presente, o teste roda (não pula) e passa, reportando o `status`
  real observado (`"Static"` ou `"Resolved"` — qualquer que seja, documentado como
  comportamento atual, não assumido de antemão).
- [x] Sem a captura no disco (`tests/real/captures/` renomeado/ausente), o teste é
  `SKIPPED`, não `FAILED`.
- [x] `resolved[0].origin_step == 12` — a origem do cookie de sessão bate com a mesma
  captura, independente do `status` observado.
- [x] Nenhum teste de `tests/unit/`/`tests/golden/` regride (`pytest tests/unit tests/golden -q`
  continua verde).

## Achado observado durante a implementação de T05

O esboço de T05 previa `assert resolved[0].status == "Static"`. A implementação real usa
`assert resolved[0].status in ("Static", "Resolved")` — divergência deliberada, porque o
critério de aceite pede reportar o observado, não travar numa hipótese. **O status
observado, contra a captura real de `autorizador.unimedriopreto.com.br__20260824`, foi
`"Resolved"`.**

Isso não é a mesma coisa que "a regra de negócio funciona". Investigação imediata (fora do
escopo de T05, registrada aqui por rastreabilidade):

- A porta de admissão não rejeitou porque `real_responses/res_0012.json`, na captura
  importada, contém o valor de uma execução **posterior** ao `run` original (a sobrescrita
  do `optimize` que rodou depois, sobre o mesmo workspace) — artefato de qual arquivo restou
  em disco no momento da importação, não uma propriedade estável do fluxo.
- Como não rejeitou, o `RegexAgent` construiu um extrator a partir de
  `original_responses/res_0012.json` (HAR imutável) — que contém o cookie de sessão
  literalmente no trecho `setCookie('JSESSIONID', '68ECB342...')` — e a verificação passou
  (`verified=True`, `agent_type=RegexAgent`, `origin_location=SCRIPT`).
- **Esse trecho é o mesmo decoy que gira a cada requisição real**, comprovado três vezes
  contra o servidor nesta mesma sessão de trabalho (`.curl.sh` real do step `12` rodado 3×,
  três valores diferentes, nenhum igual ao cookie enviado). O regex construído, aplicado a
  qualquer resposta real diferente da de origem, extrai um valor aleatório — não a sessão.
  Confirmado rodando o regex real contra um corpo fabricado com outro valor: retorna esse
  outro valor, sem erro.

Ou seja: dependendo de qual arquivo de execução sobrou em disco no momento do check, o mesmo
candidato pode virar (a) um literal congelado sem extrator (a história documentada antes
desta etapa), ou (b) um extrator **verificado e aparentemente correto**, mas que sempre
esteve errado — porque a origem escolhida (o corpo do script) nunca foi a sessão de verdade,
só parecia ser, na única amostra em que foi comparado. (b) é mais grave que (a): falha
silenciosamente, sem nenhum sinal (`verified=True`) de que algo está errado.

Isso muda o que uma etapa de correção futura precisa endereçar: não é só "criar extrator
quando falta" — é a porta de admissão (e a origem via corpo de script) não distinguirem eco
fiel de decoy. Registrado aqui, fora de escopo de implementação nesta etapa (decisão do
usuário ao fechar T05): decidir e implementar a correção fica para uma etapa própria.

## Fechamento

Depois de T05, marcar os checkboxes deste plano e commitar `doc: marcando tasks concluídas`
— exceto o item de T04 (sem commit, por natureza da task). Seguir Passo 4/5 da skill
`spec-e-plano` (merge `--no-ff` de volta em `master`, depois retro de convenção).
