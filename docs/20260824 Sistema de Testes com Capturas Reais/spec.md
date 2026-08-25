# Spec — Sistema de Testes com Capturas Reais

## 0. Sumário e glossário

Hoje, quando um teste precisa de dado real de um site capturado (requests/responses de um
`run --mode main` de verdade), a única opção é hardcodar valores relevantes numa classe de
constantes Python — o que falha em dois pontos: o dado para de ser "real" no sentido de
rastreável (ninguém confere se ainda bate com o disco) e, se algum dia alguém copiar o
`req`/`res` bruto para dentro do teste, dado sensível (senha, cookie de sessão válido) entra
no histórico do git.

Esta etapa cria um terceiro andar de teste — ao lado de `tests/unit/` (isolado, com dublês)
e `tests/golden/` (ponta a ponta, contra um servidor sintético local) — que roda contra
**cópias reais de capturas de produção**, mantidas fora do controle de versão. O código dos
testes é versionado normalmente; o dado (as capturas) não.

**Fora de escopo desta etapa — mas não por ser secundário.** A regra de negócio central do
projeto é: um token dinâmico nascido de uma resposta real (uma sessão de login, por exemplo)
deve ser capturado, virar um extrator, e ser resolvido corretamente nos curls futuros. O
caso do login (step `124` da captura de 24/08) mostrou essa regra sendo violada — o
`CandidateResolver` marcou o cookie de sessão como `"Static"` sem nunca ter existido
extrator, e nenhum caminho do código de hoje corrige isso. **Decidir e implementar essa
correção não é o objetivo desta etapa** — o objetivo daqui é só entregar a infraestrutura
(captura real + carregamento + skip gracioso) que uma etapa **seguinte** vai usar para
escrever o teste vermelho dessa regra e a correção que o faz passar. O primeiro teste
migrado sob esta convenção (T07 do plano) continua sendo um teste de caracterização
(documenta o comportamento atual, incluindo a violação), não o teste da regra corrigida.

Glossário:

| termo | significado |
|---|---|
| **captura real** | Uma cópia de `real_requests/`, `real_responses/` e `original_responses/` de um workspace real, gerado por um `run --mode main` de verdade contra um site de produção. |
| **pasta de captura** | Diretório nomeado `<domínio>__<AAAAMMDD>/` dentro de `tests/real/captures/`, contendo uma captura real. A data é a da **captura** (quando o `run` rodou), não a de quando o teste foi escrito. |
| **teste de caracterização** | Teste que afirma "isso é o que o código faz hoje", não "isso é o que o código deveria fazer". Passa confirmando o comportamento atual; não é um par red→green. |
| **teste real** | Um `test_*.py` sob `tests/real/` que consome uma pasta de captura via `RealCapture`. |

## 1. Objetivo

**Problema:** testes que precisam de dado real e sensível (sessões, credenciais, tokens de
um site de produção real) não têm hoje um lugar apropriado no repositório. As opções atuais
são: (a) hardcodar os valores relevantes numa classe de constantes Python — perde
rastreabilidade com o disco e ainda assim expõe o que foi copiado; ou (b) usar `tests/golden/`
— que serve a um propósito diferente (ver §1.1) — ou `tests/unit/` — que constrói dado
sintético mínimo via dublês, nunca lê uma captura real.

**O que esta etapa entrega:**

1. Um diretório `tests/real/` para os módulos de teste que consomem capturas reais —
   versionado normalmente, igual a `tests/unit/`.
2. Um diretório `tests/real/captures/` para as capturas em si — **listado no
   `.gitignore`**, nunca commitado. Convenção de nome `<domínio>__<AAAAMMDD>/`.
3. Uma classe de apoio (`tests/real/support/real_capture.py`, `RealCapture`) que carrega um
   `Step`/`StepRequest` real a partir de `real_requests/req_XXXX.json`, e expõe os
   diretórios de resposta prontos para `ResponseCorpus` — sem duplicar o formato de nome de
   arquivo que `Workspace` já define.
4. Um mecanismo de *skip* gracioso: um teste real ausente de captura no disco local **pula**
   (não falha), com o motivo explícito — assim `pytest` continua verde num clone novo, sem
   a pasta de captura.
5. Um importador (`tests/real/support/capture_importer.py`, `CaptureImporter`) que copia
   `real_requests/`, `real_responses/`, `original_responses/` de um workspace de `--output`
   qualquer para dentro de `tests/real/captures/<domínio>__<data>/` — para não depender de
   copiar arquivo por arquivo à mão a cada nova captura.
6. Um primeiro teste real de prova de conceito, sobre a captura de
   `autorizador.unimedriopreto.com.br` de 24/08/2026: o cookie de sessão que o login (step
   `124`) reusa é resolvido pela mesma cadeia de produção (`BaselineDiff` real +
   `CandidateResolver` real) usando o `req`/`res` reais dessa captura — caracterizando o
   comportamento atual (`"Static"`, sem extrator), como prova de que o sistema de
   carregamento funciona ponta a ponta.

**Fora de escopo:** qualquer coisa que exija decidir comportamento correto do
`CandidateResolver`/`ReplayOptimizer` (ver Sumário). Redação/mascaramento de campos
sensíveis dentro da captura — decisão do usuário: o único requisito é isolamento por
`.gitignore`, sem redação de conteúdo.

### 1.1 Por que não reaproveitar `tests/golden/`

`GoldenWorkspace`/`GoldenWorkspaceFactory` (`tests/support/golden_workspace.py`) comparam a
**árvore de arquivos inteira** gerada por um `run`/`replay`/`parse` contra uma referência
gravada, rodando a ferramenta de ponta a ponta contra um alvo **sintético e local**
(`tests/fixtures/*.har`, com `__PORT__` materializado por `HarMaterializer` contra um
`CannedHttpServer`). Nos cenários marcados `slow` que cobrem `run --mode main` (ex.:
`tests/test_auth_flow.py`) o `CliInvoker` chama o comando de produção de verdade, que
sempre abre um `mitmproxy` real como proxy (`cli_handlers.py:86`, `subprocess.Popen` de
`mitmdump` em `MitmProxyOrchestrator.run`) — o alvo por trás do proxy é sintético, o proxy
não é. Serve para caracterizar o pipeline completo contra
um cenário controlado e determinístico — não para testar um mecanismo isolado (uma classe,
um método) contra o comportamento real de um site de produção específico, com data e
domínio próprios. São eixos diferentes: golden = "o pipeline inteiro continua consistente";
capturas reais = "este mecanismo, com este dado real, faz isso". Nenhuma reaproveita a outra
diretamente, mas as duas cabem de conviver — `tests/real/` fica ao lado de `tests/golden/`
e `tests/unit/`, mesmo nível.

## 2. Componentes existentes reaproveitados

- **`har_reproducer.models.http.StepRequest`/`StepResponse`/`Step`** (`models/http.py:7-31`)
  — os arquivos `real_requests/req_XXXX.json` são gravados por
  `Engine._persist_request_step` (`engines/engine.py:107-108`) via
  `request.model_dump_json(indent=2)`. Isso significa que `StepRequest.model_validate_json`
  reconstrói o objeto exato, sem parsing customizado — é o mesmo tipo, ida e volta (validado
  por round-trip real nesta etapa). O campo `body` é tipado como `Optional[Union[str, bytes]]`,
  mas `HARParser.parse_entry` (`fs_io/har_parser.py:63-73`) só produz `str` a partir de
  `postData.text` do HAR — o round-trip vale para o dado que o `Engine` de fato grava, não
  como garantia genérica do tipo `Union`.
- **`har_reproducer.fs_io.workspace.Workspace`** (`fs_io/workspace.py`) — já define a
  convenção de nome de arquivo por step (`req_{index:04d}.json`, `res_{index:04d}.json`) via
  `STEP_INDEX_WIDTH: ClassVar[int] = 4`. `RealCapture` reusa essa constante em vez de
  duplicar o número mágico; não reusa a classe `Workspace` em si porque seu `__init__`
  cria (`mkdir`) todos os subdiretórios de um workspace de produção
  (`curls/`, `extractors/`, `temp_extractors/`, `mitm_capture/`, `replays/`) como efeito
  colateral — mutaria a pasta de captura, que deve ficar só-leitura.
- **`har_reproducer.tracking.response_corpus.ResponseCorpus`** (`tracking/response_corpus.py`)
  — já lê `res_XXXX.json` de **qualquer** diretório passado ao construtor, sem exigir que
  seja um workspace de produção. Uma pasta de captura real aponta direto para ele: nenhuma
  classe nova precisa reimplementar a leitura de resposta.
- **`tests/conftest.py`** (`OfflineFixtureConfig`, fixtures de módulo) — convenção de
  fixture (`FIXTURES_DIR`/`GOLDEN_DIR` como `ClassVar`, funções decoradas com
  `@pytest.fixture`) que `tests/real/conftest.py` replica no seu próprio nível, em vez de
  inventar um padrão novo.
- **`tests/conftest.py:pytest_addoption`/`pytest_collection_modifyitems`** — o padrão
  `--runslow` (marcador `slow`, skip condicional em `pytest_collection_modifyitems`) é a
  referência de estilo para o marcador `real_capture` desta etapa — mas o gatilho de skip é
  diferente (ver 3.4).

## 3. Decisões de arquitetura

### 3.1 Dois diretórios, dois destinos de controle de versão

```
tests/real/
    captures/                                    # gitignored, só localmente
        autorizador.unimedriopreto.com.br__20260824/
            real_requests/
                req_0000.json ... req_0232.json
            real_responses/
                res_0000.json ... res_0232.json
            original_responses/
                res_0000.json ... res_0232.json
    support/
        real_capture.py                           # RealCapture
        capture_importer.py                       # CaptureImporter
    conftest.py                                    # fixtures + skip
    test_candidate_resolver_unimedriopreto.py        # primeiro teste migrado
```

`tests/real/captures/` entra no `.gitignore` (linha nova: `tests/real/captures/`). Todo o
resto de `tests/real/` é versionado como qualquer outro teste.

**Por que copiar a captura inteira (as três pastas), não um subconjunto por cenário:** como
a pasta nunca é commitada, o custo de espaço não é um problema de repositório. Copiar tudo
de uma vez (via `CaptureImporter`, §3.5) elimina a curadoria manual de "quais steps este
teste precisa" a cada novo caso — qualquer teste futuro sobre a mesma captura já tem os 233
steps disponíveis, sem reimportar.

Não são copiados `curls/`, `extractors/`, `replays/`, `mitm_capture/`, `temp_extractors/` —
são artefatos derivados de uma execução específica (dependem de `run_id`, de qual LLM
resolveu qual token naquele dia), não o dado de entrada que os testes desta etapa consomem
(requests/responses reais). Se uma etapa futura precisar deles, é decisão daquela etapa.

### 3.2 `RealCapture` — carregamento sem duplicar o formato de arquivo

Estado atual: nenhuma classe de teste carrega um `Step`/`StepRequest` real a partir de
disco — `ResponseCorpus` lê resposta (dict cru), sem equivalente para request. Construir um
`Step`/`StepRequest` real hoje exige montar os campos à mão, um por um, como literais
Python — o cookie, a URL, o método — copiados de uma leitura manual do `req_XXXX.json`.

Estado esperado:

```python
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

⚠️ `step_request`/`step` propagam qualquer exceção de leitura/parsing (`FileNotFoundError`,
erro de validação do pydantic) sem capturar — não é uma borda de I/O de produção coberta
pela regra de `except Exception` amplo do guia de estilo; um teste real que não encontra o
arquivo esperado deve falhar alto (ou ser pulado antes, via `RealCapture.available`, §3.4),
nunca degradar silenciosamente para `None`.

### 3.3 Convenção de nome: domínio + data da captura

Estado esperado: `tests/real/captures/<domínio>__<AAAAMMDD>/`, onde:

- `<domínio>` é o host literal das requisições daquela captura (ex.:
  `autorizador.unimedriopreto.com.br`), sem esquema nem porta.
- `<AAAAMMDD>` é a data em que o `run --mode main` que gerou a captura rodou — **não** a
  data em que o teste foi escrito nem em que a pasta foi importada. Permite duas capturas do
  mesmo site em datas diferentes convivendo (`autorizador.unimedriopreto.com.br__20260824/`
  e, se o mesmo fluxo for recapturado depois, `autorizador.unimedriopreto.com.br__20261102/`)
  para comparar o mesmo cenário em momentos diferentes, como o usuário descreveu.
- Um site com múltiplos domínios relevantes na mesma captura (como o HAR de 24/08, que tem
  231 de 233 requisições em `autorizador.unimedriopreto.com.br` e mais duas em domínios de
  terceiro, `google.com`/`gstatic.com`) usa o domínio **predominante** — não se cria uma
  pasta por domínio dentro da mesma captura.

### 3.4 Skip gracioso quando a captura não existe localmente

Estado atual: nenhum teste hoje depende de um diretório que pode não existir no disco de
quem roda `pytest` — `--runslow` gate por **escolha explícita** do usuário (flag), não por
disponibilidade de arquivo.

Estado esperado: uma fixture por captura, em `tests/real/conftest.py`, que verifica a
existência da pasta e pula com `pytest.skip(...)` se ausente — sem precisar de uma flag
nova (diferente de `--runslow`: aqui não há "escolha" de rodar, só disponibilidade de dado):

```python
class UnimedriopretoCaptureConfig:
    FOLDER_NAME: ClassVar[str] = "autorizador.unimedriopreto.com.br__20260824"


@pytest.fixture
def unimedriopreto_20260824_capture(real_captures_dir: Path) -> RealCapture:
    base_dir: Path = real_captures_dir / UnimedriopretoCaptureConfig.FOLDER_NAME
    if not base_dir.exists():
        pytest.skip(f"captura real ausente em {base_dir} — rode CaptureImporter para importá-la")
    return RealCapture(base_dir)
```

⚠️ O literal do nome da pasta vira `ClassVar` mesmo aparecendo uma única vez — o guia de
estilo é explícito que constante solta dentro de `conftest.py` já escapou antes despercebida
(`FIXTURES_DIR`/`OFFLINE_PORT` em `tests/conftest.py`, hoje corrigidas).

Um marcador `real_capture` (registrado em `pytest_configure`, mesmo padrão de `slow` em
`tests/conftest.py:26-27`) marca esses testes para filtragem/relatório (`pytest -m real_capture`),
mas **não** controla o skip — a fixture acima é quem decide, pela presença do arquivo, não
pela marcação.

### 3.5 `CaptureImporter` — trazer uma captura real para dentro de `tests/real/captures/`

Estado atual: a única forma de povoar uma pasta de captura seria copiar manualmente
`real_requests/`, `real_responses/`, `original_responses/` do workspace do `--output` para
dentro de `tests/real/captures/<nome>/` via `cp`/`shutil` ad hoc, decidindo o nome da pasta
à mão a cada vez.

Estado esperado: `tests/real/support/capture_importer.py`, `CaptureImporter`, com um método
que recebe o workspace de origem e a data da captura (não deduzida automaticamente — ver
§5) e devolve o `Path` da pasta criada:

```python
class CaptureImporter:
    SUBDIRECTORIES: ClassVar[Tuple[str, ...]] = ("real_requests", "real_responses", "original_responses")

    def __init__(self, captures_root: Path) -> None:
        self.captures_root: Path = captures_root

    def import_capture(self, workspace_output_dir: Path, domain: str, captured_on: date) -> Path:
        destination: Path = self.captures_root / f"{domain}__{captured_on:%Y%m%d}"
        for subdirectory in self.SUBDIRECTORIES:
            shutil.copytree(workspace_output_dir / subdirectory, destination / subdirectory, dirs_exist_ok=True)
        return destination
```

Não é um comando de CLI novo do projeto (`har_reproducer.main` não ganha um subcomando) —
é um utilitário de teste, invocado manualmente (script one-off ou REPL) por quem estiver
importando uma captura nova, fora do fluxo de `pytest`. `domain` é passado pelo chamador, não
inferido do conteúdo (evita abrir/parsear 233 arquivos só para achar o host predominante,
quando quem está importando já sabe de qual site se trata).

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `tests/real/support/real_capture.py` (`RealCapture`) | Novo. Carrega `Step`/`StepRequest` real por índice; expõe diretórios de resposta para `ResponseCorpus`. |
| `tests/real/support/capture_importer.py` (`CaptureImporter`) | Novo. Copia as três subpastas de um workspace real para `tests/real/captures/<domínio>__<data>/`. |
| `tests/real/conftest.py` | Novo. `real_captures_dir` (`ClassVar` de config, igual a `OfflineFixtureConfig`), fixture(s) por captura com skip gracioso, `pytest_configure` registrando o marcador `real_capture`. |
| `tests/real/test_candidate_resolver_unimedriopreto.py` | Novo. Migra o teste de caracterização do cookie de sessão do login (step `124`) para a convenção desta etapa. |
| `.gitignore` | +1 linha: `tests/real/captures/`. |
| `tests/real/captures/autorizador.unimedriopreto.com.br__20260824/` | Nova pasta local (gitignored), povoada via `CaptureImporter` a partir do workspace real do usuário. |

## 5. Casos de borda e comportamento de erro

- **Captura ausente:** teste pula (`pytest.skip`), não falha — comportamento aceito e
  central da §3.4, não uma limitação a corrigir depois.
- **Captura corrompida/incompleta** (ex.: `req_0124.json` existe mas não é JSON válido, ou o
  domínio informado ao `CaptureImporter` não bate com nenhuma URL real da captura): não é
  responsabilidade desta etapa validar/normalizar — `RealCapture.step_request` deixa a
  exceção de parsing propagar (§3.2); `CaptureImporter` não valida o domínio contra o
  conteúdo copiado. Aceito como limitação: quem importa a captura é responsável por
  descrever corretamente o que está importando.
- **Duas capturas do mesmo domínio na mesma data** (ex.: dois `run --mode main` no mesmo
  dia contra o mesmo site, capturas diferentes): `CaptureImporter.import_capture` usa
  `dirs_exist_ok=True`, então uma segunda importação no mesmo dia **funde** por cima da
  primeira (arquivo a arquivo, por nome — sobrescreve os índices em comum, mantém os que só
  existem numa das duas). Aceito como limitação: se isso importar, quem estiver importando
  decide um nome de pasta manual diferente (a assinatura aceita passar qualquer `captured_on`,
  não só a data corrente).
- **`tests/real/captures/` não existe (clone novo, ninguém importou nada ainda):** a
  fixture de `real_captures_dir` não cria o diretório — `real_captures_dir / "<nome>"` não
  existirá, cai no caminho de skip do §3.4 normalmente (`Path.exists()` em caminho cujo pai
  não existe retorna `False`, não lança).
- **`CaptureImporter` sobre uma subpasta que não existe na origem** (ex.: workspace só rodou
  `dry`, sem `real_responses/` populado): `shutil.copytree` lança `FileNotFoundError` — deixa
  propagar, não há fallback degradado aqui (é uma operação manual, de quem já está olhando o
  erro na hora).

## 6. Suposições e pontos a confirmar

Nenhuma pendente — as duas decisões que precisavam de confirmação do usuário (redação de
dado sensível → não, isolamento por `.gitignore` basta; escopo da correção da pendência 1 →
fora desta etapa) já vieram resolvidas na mensagem que abriu esta etapa.

## 7. Referência

Implementação segue `.claude/skills/guia-de-estilo/SKILL.md` — tipagem explícita em toda
função/atributo novo, `ClassVar` para constantes, um conceito por arquivo, sem comentários
nem docstrings (nomes carregam a explicação).
