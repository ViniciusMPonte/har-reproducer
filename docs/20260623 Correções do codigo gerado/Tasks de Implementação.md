# Tasks de Implementação — har_reproducer

Ordem recomendada: Seção 2 (pacotes) → Seção 3 (dead code) → Seção 1 (globais) → Seção 4 (por arquivo) → Seção 5 (agentes).

---

## Seção 2 — Correções de Pacotes

---

### TASK-01 — Remover `RecordedRequest` e simplificar `CurlGenerator`

**Arquivos:** `src/models/request_record.py`, `src/services/curl_generator.py`, `har_reproducer/engine.py`
**Depende de:** nenhuma

**Contexto:**
`RecordedRequest` é um modelo intermediário criado no `Engine` apenas para ser repassado ao `CurlGenerator`. Ele duplica os campos de `StepRequest` (`url`, `method`, `headers`, `cookies`, `body`), forçando manutenção dupla. O `CurlGenerator` pode receber `StepRequest` diretamente com `step_index` como parâmetro separado.

**O que fazer:**
1. Alterar a assinatura do `CurlGenerator.generate` para receber `StepRequest` diretamente
2. Remover a criação de `RecordedRequest` no `Engine` e passar `StepRequest` direto
3. Remover o arquivo `src/models/request_record.py`
4. Ajustar todos os imports que referenciam `RecordedRequest`

```python
# Assinatura nova do CurlGenerator
def generate(self, step_index: int, request: StepRequest, session_store: Optional[SessionStore] = None) -> str:

# Chamada no Engine
curl_cmd = CurlGenerator().generate(step.index, final_request, session_store=self.session_store)
```

**Critério de conclusão:**
- [X] `RecordedRequest` não existe mais em nenhum arquivo
- [X] `CurlGenerator.generate` recebe `StepRequest` diretamente
- [X] Nenhum import quebrado no projeto

---

### TASK-02 — Mover `CurlGenerator` para dentro do pacote `har_reproducer`

**Arquivos:** `src/services/curl_generator.py`, `har_reproducer/engine.py`, demais importadores
**Depende de:** TASK-01

**Contexto:**
`CurlGenerator` está em `src.services`, fora do pacote `har_reproducer`, criando acoplamento desnecessário entre os dois namespaces.

**O que fazer:**
1. Mover `curl_generator.py` para `har_reproducer/curl_generator.py`
2. Atualizar todos os imports do projeto para o novo caminho

**Critério de conclusão:**
- [X] `CurlGenerator` está em `har_reproducer/curl_generator.py`
- [X] Nenhum import aponta para `src.services.curl_generator`

---

### TASK-03 — Converter `TokenLocation`, `PatchAction` e `AgentType` para Enum (models.py)

**Arquivo:** `har_reproducer/models.py`
**Depende de:** nenhuma

**Contexto:**
`TokenLocation`, `PatchAction` e `agent_type` são `Literal` com strings soltas. Ao adicionar um novo agente ou ação, é necessário lembrar de atualizar cada `Literal` manualmente — fácil de esquecer e silencioso em runtime.

**O que fazer:**
1. Criar `class AgentType(str, Enum)` com os valores atuais do `Literal`
2. Criar `class PatchAction(str, Enum)` com os valores atuais do `Literal`
3. Criar `class TokenLocation(str, Enum)` com os valores atuais do `Literal`
4. Substituir os usos de string literal nos demais arquivos pelos Enums

```python
from enum import Enum

class AgentType(str, Enum):
    COOKIE = "CookieAgent"
    HEADER = "HeaderAgent"
    JSONPATH = "JSONPathAgent"
    CSS = "CSSAgent"
    REGEX = "RegexAgent"

class PatchAction(str, Enum):
    FIX_EXTRACTOR = "FIX_EXTRACTOR"
    INJECT_VALUE = "INJECT_VALUE"
    REPLACE_EXTRACTOR = "REPLACE_EXTRACTOR"

class TokenLocation(str, Enum):
    HEADER = "Header"
    COOKIE = "Cookie"
    BODY_JSON = "BodyJSON"
    BODY_HTML = "BodyHTML"
    SCRIPT = "Script"
```

**Critério de conclusão:**
- [X] Os três Enums existem em `models.py`
- [X] Nenhum arquivo usa strings soltas para esses valores
- [X] `TokenTrace.location` (se mantido) usa `TokenLocation`

---

### TASK-04 — Substituir `Patch` por discriminated unions (models.py)

**Arquivo:** `har_reproducer/models.py`, `har_reproducer/engine.py`, `har_reproducer/agents/diagnose_agent.py`
**Depende de:** TASK-03

**Contexto:**
O modelo `Patch` atual tem todos os campos como `Optional`, mas cada ação tem campos obrigatórios diferentes. É possível criar um `Patch` inválido (ex: `action="INJECT_VALUE"` sem `new_value`) sem nenhum erro em runtime.

**O que fazer:**
1. Criar modelos específicos por ação com discriminated unions do Pydantic
2. Substituir o `Patch` genérico pelo `Union` tipado
3. Atualizar os lugares que criam ou consomem `Patch`

```python
class InjectValuePatch(BaseModel):
    action: Literal["INJECT_VALUE"]
    target_token_id: str
    new_value: str
    rationale: str

class FixExtractorPatch(BaseModel):
    action: Literal["FIX_EXTRACTOR"]
    target_token_id: str
    new_code: str
    rationale: str

class ReplaceExtractorPatch(BaseModel):
    action: Literal["REPLACE_EXTRACTOR"]
    target_token_id: str
    new_code: str
    rationale: str

Patch = Annotated[Union[InjectValuePatch, FixExtractorPatch, ReplaceExtractorPatch], Field(discriminator="action")]
```

**Critério de conclusão:**
- [X] `Patch` genérico removido de `models.py`
- [X] Criação de `Patch` inválido levanta erro do Pydantic
- [X] `diagnose_agent.py` e `engine.py` criam os subtipos corretos

---

### TASK-05 — Substituir `SuccessCriterion` por discriminated unions (models.py)

**Arquivo:** `har_reproducer/models.py`, `har_reproducer/validator.py`
**Depende de:** nenhuma

**Contexto:**
`SuccessCriterion` tem `value` e `expected` como `Any`. Cada tipo de critério tem expectativas diferentes (`status_code` espera `int`, `body_contains` espera `str`). A falta de tipagem faz o `validator.py` precisar de validação manual de tipo em runtime.

**O que fazer:**
1. Criar modelos específicos por critério
2. Definir `SuccessCriterion` como `Union` com discriminator em `type`
3. Atualizar `validator.py` para usar os tipos concretos

```python
class StatusCodeCriterion(BaseModel):
    type: Literal["status_code"]
    expected: int

class BodyContainsCriterion(BaseModel):
    type: Literal["body_contains"]
    expected: str

class UrlMatchCriterion(BaseModel):
    type: Literal["url_match"]
    expected: str

class HtmlElementPresentCriterion(BaseModel):
    type: Literal["html_element_present"]
    expected: str

class CompositeCriterion(BaseModel):
    type: Literal["composite"]
    expected: List["SuccessCriterion"]

SuccessCriterion = Annotated[
    Union[StatusCodeCriterion, BodyContainsCriterion, UrlMatchCriterion, HtmlElementPresentCriterion, CompositeCriterion],
    Field(discriminator="type")
]
```

**Critério de conclusão:**
- [X] `SuccessCriterion` genérico removido
- [X] `validator.py` não faz mais checagem manual de tipo no critério `composite`
- [X] Todos os lugares que criam `SuccessCriterion` usam o subtipo correto

---

### TASK-06 — Mover lógica de entries do HAR para `HARParser` (engine.py)

**Arquivos:** `har_reproducer/engine.py`, `har_reproducer/parser.py`
**Depende de:** nenhuma

**Contexto:**
O `Engine` acessa a estrutura interna do HAR diretamente (`har_data.get("log", {}).get("entries", [])`), quebrando o encapsulamento do `HARParser`. O parser deve ser o único lugar que conhece o formato interno do HAR.

**O que fazer:**
1. Adicionar método `get_entries(har_path: Path) -> list[dict]` ao `HARParser`
2. Substituir o acesso direto no `Engine` pela chamada ao método

```python
# HARParser
@classmethod
def get_entries(cls, har_path: Path) -> list[dict]:
    with open(har_path) as f:
        har_data = json.load(f)
    return har_data.get("log", {}).get("entries", [])

# Engine
entries = HARParser.get_entries(self.har_path)
```

**Critério de conclusão:**
- [X] `Engine` não faz mais `json.load` do HAR nem acessa `.get("log")`
- [X] `HARParser.get_entries` existe e está tipado

---

## Seção 3 — Remoção de Código Não Usado

---

### TASK-07 — Remover `ExtractorMetadata` (models.py)

**Arquivo:** `har_reproducer/models.py`
**Depende de:** nenhuma

**Contexto:**
`ExtractorMetadata` está definido em `models.py` mas não é usado em lugar nenhum relevante do código. O `Extractor` completo é sempre usado no lugar.

**O que fazer:**
1. Confirmar com `grep -r "ExtractorMetadata"` que não há uso real
2. Remover a classe de `models.py`

**Critério de conclusão:**
- [X] `ExtractorMetadata` não existe mais em nenhum arquivo

---

### TASK-08 — Ativar `try_decode` e buscar todas as variantes encode/decode (grep_utils.py) ✅

**Arquivos:** `har_reproducer/grep_utils.py`, `har_reproducer/tracker.py`
**Depende de:** nenhuma

**Contexto:**
`try_decode` estava definido em `grep_utils.py` mas nunca chamado. Além disso, a busca original só tentava o padrão literal — tokens podem estar armazenados nas responses em encoding diferente do usado na requisição (ex: requisição envia Base64, response armazena o valor bruto, ou vice-versa).

**O que fazer:**
1. `grep_in_real_responses` refatorar para tentar todas as variantes do padrão antes de desistir, via nova função privada `_build_pattern_variants`
2. `_build_pattern_variants` gera variantes deduplicas na ordem: literal → decodificado (via `try_decode`) → URL-encoded → Base64-encoded
3. Extrair lógica de execução do grep para `_grep_single_pattern` (responsabilidade única)
4. Reaproveitar `try_decode` por `_build_pattern_variants` sem duplicação de lógica
5. Adicionado log no `except` do `try_decode` conforme padrão global (TASK-13)

**Critério de conclusão:**
- [X] `try_decode` é chamado em pelo menos um lugar (`_build_pattern_variants`)
- [X] Nenhum import de `try_decode` sem uso
- [X] Busca tenta literal, decodificado, URL-encoded e Base64-encoded antes de retornar `None`
- [X] `except Exception` no `try_decode` tem `print` de aviso com contexto

---

### TASK-09 — Remover import `Any` sem uso (validator.py)

**Arquivo:** `har_reproducer/validator.py`
**Depende de:** nenhuma (pode ser feito junto com TASK-05 se `SuccessCriterion` for refatorado antes)

**Contexto:**
`Any` é importado de `typing` mas não é usado em nenhuma anotação do arquivo.

**O que fazer:**
```python
# Antes
from typing import List, Any

# Depois
from typing import List
```

**Critério de conclusão:**
- [X] `Any` não aparece em `from typing import` no `validator.py`

---

### TASK-10 — Conectar `apply_patch` ao fluxo ou remover

**Arquivos:** `har_reproducer/engine.py`, `har_reproducer/agents/diagnose_agent.py`, `har_reproducer/cli.py`
**Depende de:** TASK-04 (discriminated unions de Patch)

**Contexto:**
O método `apply_patch` existe no `Engine` mas nunca é chamado. O `diagnose` do `Engine` retorna um `Patch` que a CLI apenas imprime. O `DiagnoseAgent` também retorna um `Patch` que nunca é aplicado. O fluxo diagnose → apply está pela metade.

**O que fazer:**
- Se o fluxo de diagnóstico não está pronto para produção: remover `apply_patch` do `Engine` e adicionar um `# TODO` claro no `diagnose` da CLI indicando que a aplicação do patch não está implementada
- Se o fluxo deve ser conectado agora: após o `diagnose` retornar um `Patch`, chamar `engine.apply_patch(patch)` dentro do `handle_diagnose` da CLI

**Critério de conclusão:**
- [X] Ou `apply_patch` é chamado no fluxo real, ou está removido com TODO documentado
- [X] Nenhum método público "fantasma" sem chamador e sem aviso

---

### TASK-11 — Implementar etapa 7 do pipeline do tracker (validação de extratores)

**Arquivo:** `har_reproducer/tracker.py`
**Depende de:** TASK-16 (loop TDD com erro propagado), TASK-22 (LLM nos agentes)

**Contexto:**
O comentário no código diz:
```python
# 7. Validation (Skipped in this basic implementation, assumed by pipeline)
```
A validação dos extratores foi pulada. O plano prevê rodar o extrator gerado contra a response real e verificar se o valor extraído bate com o `expected_value`.

**O que fazer:**
1. Após o `run_tdd_loop` retornar um extrator, executar o extrator contra a response real do step de origem
2. Comparar o valor extraído com `candidate.expected_value`
3. Setar `extractor.verified = True` se bater, ou registrar como `Unresolved` com log de falha

**Critério de conclusão:**
- [ ] Nenhum extrator chega ao curl com `verified = False` sem aviso explícito
- [ ] O campo `verified` do `Extractor` reflete o resultado real da validação

---

### TASK-12 — Implementar ferramentas reais do `DiagnoseAgent`

**Arquivo:** `har_reproducer/agents/diagnose_agent.py`
**Depende de:** TASK-06 (HARParser.get_entries), TASK-23 (LLM no DiagnoseAgent)

**Contexto:**
Os métodos `read_step`, `grep_responses` e `get_session_state` existem como placeholder mas retornam dados fictícios. Sem eles o diagnóstico real é impossível — o LLM não tem como investigar a falha.

**O que fazer:**
1. `read_step(step_index)` → usar `HARParser` para carregar o step real
2. `grep_responses(pattern)` → usar `grep_utils.grep_in_real_responses`
3. `get_session_state()` → receber `SessionStore` no construtor e retornar o estado atual

**Critério de conclusão:**
- [ ] Os três métodos retornam dados reais, não fictícios
- [ ] `DiagnoseAgent` recebe `SessionStore` no construtor

---

## Seção 1 — Alterações Globais

---

### TASK-13 — Corrigir falhas silenciosas em `except Exception` (todos os arquivos)

**Arquivos:** `har_reproducer/parser.py`, `har_reproducer/tracker.py`, `har_reproducer/grep_utils.py`, `har_reproducer/agents/base.py`
**Depende de:** nenhuma

**Contexto:**
Padrão recorrente de `except Exception: pass` sem log, engolindo erros e impossibilitando o debug.

**O que fazer — por arquivo:**

`parser.py` — método `decode_body`:
```python
except Exception as e:
    print(f"[AVISO] Falha ao decodificar body base64: {e}. Retornando conteúdo original.")
    return body_content
```

`tracker.py` — método `_load_response`:
```python
except Exception as e:
    print(f"[AVISO] Falha ao carregar response do step {step_index}: {e}")
    return None
```
✅ Implementado.

`grep_utils.py` — método `try_decode`:
```python
except Exception as e:
    print(f"[AVISO] Falha ao decodificar base64: {e}")
```
✅ Implementado (junto com TASK-08).

`base.py` — timeout de subprocess:
```python
except subprocess.TimeoutExpired:
    print(f"[AVISO] Timeout ao verificar extrator para {self.token_id}")
```

**Critério de conclusão:**
- [X] Nenhum `except Exception: pass` no projeto
- [X] Nenhum `except Exception` sem `print` de aviso com contexto

---

### TASK-14 — Mover todos os imports para o topo dos arquivos

**Arquivos:** `har_reproducer/engine.py`, `har_reproducer/tracker.py`, `har_reproducer/agents/base.py`, `har_reproducer/agents/diagnose_agent.py`
**Depende de:** nenhuma

**Contexto:**
Imports dentro de métodos, blocos `if` e loops foram encontrados em vários arquivos. Python permite isso mas é antipadrão — dificulta entender dependências e pode esconder ImportError até o momento de execução.

**O que fazer — por arquivo:**

`engine.py`:
```python
# Mover do _run_extractor para o topo:
import sys
import subprocess
from pathlib import Path
# Mover do apply_patch e diagnose, unificando os imports duplicados de .models:
from .agents.diagnose_agent import DiagnoseAgent
from .models import Extractor, FailureContext
```

`tracker.py`:
```python
# Mover do bloco if is_dry_run para o topo:
from .models import Extractor
```

`agents/base.py`:
```python
# Mover do run_tdd_loop e _verify_code para o topo:
import subprocess
import sys
from pathlib import Path
from har_reproducer.models import Extractor
```

`agents/diagnose_agent.py`:
```python
# Mover do _simulate_diagnosis para o topo:
import glob
```

**Critério de conclusão:**
- [X] Nenhum `import` dentro de método, `if` ou loop em nenhum arquivo do projeto

---

### TASK-15 — Tipar completamente todos os arquivos do projeto

**Arquivos:** todos
**Depende de:** TASK-03 (Enums), TASK-04, TASK-05 (discriminated unions)

**Contexto:**
Anotações de tipo parciais ou ausentes em todo o projeto. Casos recorrentes: métodos sem tipo de retorno, `Any` onde tipos concretos são viáveis, subclasses de agentes sem tipo de retorno em `generate_code`.

**O que fazer — prioridade por arquivo:**

`parser.py`:
```python
@classmethod
def split_har(cls, har_path: Path, output_dir: Path) -> int: ...
```

`agents/base.py`:
```python
def run_tdd_loop(self, max_attempts: int = 5, origin_step: Optional[int] = None) -> Optional[Extractor]: ...
def _verify_code(self, code: str) -> Tuple[bool, Optional[str]]: ...
```

`agents/cookie_agent.py`, `header_agent.py`, `jsonpath_agent.py`, `css_agent.py`, `regex_agent.py`:
```python
def generate_code(self, last_error: Optional[str] = None) -> str: ...
```

`session.py`:
```python
def set_token(self, token_id: str, value: str) -> None: ...
def render_dict(self, data: Any) -> Any: ...
```

`grep_utils.py`:
- Verificar e completar tipos de retorno de `try_decode` (cada branch)

`models.py`:
- Substituir `Any` em `SessionState` por tipos concretos onde possível
- `DynamicToken.origin_step: Optional[int] = None` (remover magic number `-1`)

`validator.py`:
- Após TASK-05, `_check_criterion` já terá tipos concretos por critério

**Critério de conclusão:**
- [X] `mypy --strict` (ou equivalente) sem erros nos arquivos alterados
- [X] Nenhum método público sem tipo de retorno declarado
- [X] Nenhum `origin_step = -1` no código

---

### TASK-16 — Decompor métodos grandes em métodos privados menores

**Arquivos:** `har_reproducer/tracker.py`, `har_reproducer/agents/base.py`
**Depende de:** TASK-17 (early returns)

**Contexto:**
`analyze_step` (tracker.py) e `_verify_code` (base.py) fazem coisas demais em um único bloco, dificultando teste e leitura.

**O que fazer:**

`tracker.py` — `analyze_step`:
Extrair cada etapa numerada do pipeline em seu próprio método privado:
```python
def analyze_step(self, step_index: int) -> StepAnalysis:
    baseline = self._load_baseline()
    step = self._load_step(step_index)
    candidates = self._detect_candidates(step, baseline)
    curl_template = self._generate_curl_template(step, candidates)
    origins = self._find_origins(candidates, step_index)
    extractors = self._generate_extractors(candidates, origins)
    return self._build_analysis(step_index, curl_template, extractors, candidates)
```

`agents/base.py` — `_verify_code`:
Dividir em:
- `_write_temp_script(code: str) -> Path`
- `_execute_script(script_path: Path) -> Tuple[bool, Optional[str]]`
- `_cleanup_script(script_path: Path) -> None`

**Critério de conclusão:**
- [X] `analyze_step` é um orquestrador com no máximo 15 linhas de corpo
- [X] `_verify_code` delegado para submétodos com responsabilidade única

---

### TASK-17 — Achatar ifs aninhados com early return (tracker.py)

**Arquivo:** `har_reproducer/tracker.py`
**Depende de:** nenhuma

**Contexto:**
O `analyze_step` tem `if` dentro de `if` dentro de `for`, dificultando a leitura e o teste isolado de cada condição.

**O que fazer:**
Substituir ifs aninhados por early returns nos métodos internos:

```python
# Em vez de:
if origin:
    if response_sample:
        if not is_dry_run:
            ...

# Usar:
if not origin:
    candidate.status = "Unresolved"
    return candidate

if not response_sample:
    return candidate

extractor = self._generate_extractor(candidate, response_sample)
```

**Critério de conclusão:**
- [X] Nenhum bloco com mais de 2 níveis de `if` aninhado em `tracker.py`

---

## Seção 4 — Por Arquivo

---

### TASK-18 — Corrigir CLI: output_dir, `--output`, `--step` e Engine fictício

**Arquivo:** `har_reproducer/cli.py`
**Depende de:** nenhuma

**Contexto:**
Quatro problemas independentes na CLI que podem ser resolvidos juntos:
1. `output_dir` está hardcoded como `"reproduction_results"` relativo ao diretório de execução
2. O subcomando `run` não tem `--output` (inconsistente com `parse`)
3. O step do `diagnose` está hardcoded como `step_index=1`
4. `diagnose` cria um `Engine(Path("dummy.har"), ...)` como workaround frágil

**O que fazer:**

```python
# 1 e 2: output_dir baseado no HAR + argumento --output no run
run_parser.add_argument("--output", default=None, help="Output directory")

output_dir = Path(args.output) if args.output else Path(args.har).parent / "reproduction_results"

# 3: --step no diagnose
diag_parser.add_argument("--step", type=int, required=True, help="Índice do step a diagnosticar")
patch = engine.diagnose(step_index=args.step)

# 4: extrair diagnose para função independente que não dependa de Engine com HAR fictício
```

**Critério de conclusão:**
- [X] `output_dir` usa pasta do HAR como base por padrão
- [X] `run` aceita `--output`
- [X] `diagnose` aceita `--step` obrigatório
- [X] Nenhum `Engine(Path("dummy.har"), ...)` no código

---

### TASK-19 — Corrigir `parser.py`: limpar output e extrair constante `SKIPPABLE_METHODS`

**Arquivo:** `har_reproducer/parser.py`
**Depende de:** nenhuma

**Contexto:**
Dois problemas independentes:
1. Se a pasta de output já existir de uma execução anterior, os arquivos velhos ficam misturados com os novos
2. O critério de `is_skippable` está hardcoded dentro de `parse_entry` em vez de ser uma constante configurável

**O que fazer:**

```python
# 1: limpar pasta antes de escrever
import shutil

if output_dir.exists():
    shutil.rmtree(output_dir)
output_dir.mkdir(parents=True)

# 2: constante de classe
SKIPPABLE_METHODS: set[str] = {"OPTIONS"}

is_skippable = req_data["method"] in HARParser.SKIPPABLE_METHODS
```

**Critério de conclusão:**
- [X] Re-execução do parser sobre o mesmo output não deixa arquivos órfãos
- [X] `SKIPPABLE_METHODS` é uma constante de classe em `HARParser`

---

### TASK-20 — Corrigir `engine.py`: separar run/dry_run, curls e extratores no output

**Arquivo:** `har_reproducer/engine.py`
**Depende de:** TASK-14 (imports no topo)

**Contexto:**
Três problemas relacionados ao fluxo de execução do Engine:
1. O dry-run está misturado no loop principal com condicionais, complicando os dois fluxos
2. Curls salvos em pasta hardcoded `"curls/"` em vez do `output_dir`
3. Extratores criados como temporários e apagados — o plano prevê que sejam artefatos permanentes

**O que fazer:**

```python
# 1: separar em dois métodos
def run(self) -> bool: ...
def dry_run(self) -> None: ...

# 2: curls no output_dir
curls_dir = self.output_dir / "curls"
curls_dir.mkdir(parents=True, exist_ok=True)
filename = curls_dir / f"req_{step.index:04d}.curl.sh"

# 3: extratores permanentes
extractors_dir = self.output_dir / "extractors"
extractors_dir.mkdir(parents=True, exist_ok=True)
# nunca apagar após execução
```

**Critério de conclusão:**
- [ ] `run()` e `dry_run()` são métodos distintos sem condicionais cruzados
- [ ] Curls salvos em `output_dir/curls/`
- [ ] Extratores salvos em `output_dir/extractors/` e nunca apagados

---

### TASK-21 — Corrigir `engine.py`: diagnose com contexto real e investigar geração de extratores

**Arquivo:** `har_reproducer/engine.py`
**Depende de:** TASK-20

**Contexto:**
Dois problemas relacionados à completude do fluxo do Engine:
1. O `diagnose` usa request e response fictícios hardcoded no `FailureContext`
2. O `_run_extractor` só executa extratores já existentes no registry; o plano prevê geração via LLM com loop TDD

**O que fazer:**

```python
# 1: salvar request e response reais quando um step falha
# Em algum ponto do loop de execução onde a falha é detectada:
self._last_failed_request = actual_request
self._last_failed_response = actual_response

# E no diagnose:
context = FailureContext(
    request_attempted=self._last_failed_request,
    response_received=self._last_failed_response,
)
```

Para o item 2: verificar se `TokenTracker` gera extratores via agentes LLM antes de chamá-los. Se não gera, conectar a chamada ao `run_tdd_loop` dos agentes.

**Critério de conclusão:**
- [ ] `diagnose` usa request/response reais capturados durante a execução
- [ ] Nenhum valor hardcoded (`"dummy"`, `"Unauthorized"`) no `FailureContext`
- [ ] Fluxo de geração de extratores via agente está documentado ou implementado

---

### TASK-22 — Corrigir `tracker.py`: heurística, body, location, placeholders e dry-run

**Arquivo:** `har_reproducer/tracker.py`
**Depende de:** TASK-03 (TokenLocation Enum), TASK-17 (early returns)

**Contexto:**
Cinco problemas de lógica no tracker que juntos explicam o curl com JWT hardcoded:
1. Heurística de detecção limitada a nomes específicos (`token`, `jwt`, etc.)
2. Comparação de body como string inteira em vez de campo a campo
3. `_determine_location` usa `BodyJSON` como padrão sem verificar `body_mime`
4. `_generate_curl_template` não substitui valores dinâmicos por `{{placeholders}}`
5. Dry-run registra placeholders `Pending` em vez de gerar extratores reais

**O que fazer:**

```python
# 1: ampliar heurística — campos ausentes no baseline também são candidatos
DYNAMIC_NAME_PATTERNS = {"token", "jwt", "auth", "csrf", "session", "key", "secret", "bearer", "nonce"}

# Se o campo não existe no baseline → candidato independente do nome
if field_name not in baseline_fields:
    candidates.append(candidate)

# 2: comparar body JSON campo a campo
if body_mime and "application/json" in body_mime:
    baseline_body = json.loads(baseline.body or "{}")
    step_body = json.loads(step.body or "{}")
    for key, value in step_body.items():
        if baseline_body.get(key) != value:
            diffs[key] = value
else:
    # fallback: comparação de string
    ...

# 3: usar body_mime para determinar location
if "text/html" in body_mime:
    return TokenLocation.BODY_HTML
if "application/json" in body_mime:
    return TokenLocation.BODY_JSON

# 4: substituir por placeholder no curl
for candidate in candidates:
    curl_template = curl_template.replace(candidate.value, f"{{{{{candidate.token_id}}}}}")

# 5: remover bloco else do dry-run — extratores gerados igualmente nos dois modos
```

**Critério de conclusão:**
- [ ] Campos ausentes no baseline são detectados como candidatos
- [ ] Comparação de body JSON é campo a campo
- [ ] `_determine_location` usa `body_mime` para distinguir HTML de JSON
- [ ] Curl gerado contém `{{token_id}}` em vez do valor bruto do HAR
- [ ] Dry-run gera extratores reais (sem bloco `Pending`)

---

### TASK-23 — Corrigir `session.py`: get_token seguro, render com aviso, has_token e encapsulamento de state

**Arquivo:** `har_reproducer/session.py`
**Depende de:** nenhuma

**Contexto:**
Quatro problemas no `SessionStore` que expõem estado interno e causam crashes silenciosos:
1. `get_token` lança `KeyError` se o token não existe
2. `render` não avisa quando um `{{placeholder}}` não é resolvido
3. Não há `has_token` — callers acessam `session_store.state.tokens` diretamente
4. `state` é público e acessado diretamente em vários arquivos

**O que fazer:**

```python
# 1: get_token seguro
def get_token(self, token_id: str, default: Optional[str] = None) -> Optional[str]:
    return self.state.tokens.get(token_id, default)

# 2: render com aviso de placeholder não resolvido
import re

def render(self, template: str) -> str:
    result = template
    for token_id, value in self.state.tokens.items():
        result = result.replace(f"{{{{{token_id}}}}}", value)
    unresolved = re.findall(r'\{\{(\w+)\}\}', result)
    if unresolved:
        print(f"[AVISO] Placeholders não resolvidos: {unresolved}")
    return result

# 3: has_token
def has_token(self, token_id: str) -> bool:
    return token_id in self.state.tokens

# 4: métodos de acesso ao registry
def get_registry(self) -> Dict[str, Extractor]:
    return self.state.registry

def set_extractor(self, token_id: str, extractor: Extractor) -> None:
    self.state.registry[token_id] = extractor

def get_extractor(self, token_id: str) -> Optional[Extractor]:
    return self.state.registry.get(token_id)
```

Após adicionar os métodos, substituir todos os acessos diretos a `session_store.state.tokens` e `session_store.state.registry` nos outros arquivos.

**Critério de conclusão:**
- [ ] `get_token` nunca lança `KeyError`
- [ ] `render` imprime aviso com placeholders não resolvidos
- [ ] `has_token` existe e é usado onde aplicável
- [ ] Nenhum acesso direto a `session_store.state` fora de `session.py`

---

### TASK-24 — Corrigir `grep_utils.py`: ordem garantida, erro real vs not-found, docstring

**Arquivo:** `har_reproducer/grep_utils.py`
**Depende de:** nenhuma

**Contexto:**
Três problemas no utilitário de grep:
1. A ordem dos arquivos retornados por `grep -rl` não é garantida pelo GNU grep
2. `CalledProcessError` trata "não encontrado" e "erro real" da mesma forma
3. Docstring de `grep_in_real_responses` diz `content` mas retorna `filename`

**O que fazer:**

```python
# 1: ordenar antes de pegar o primeiro
files = sorted(result.stdout.splitlines())
first_match_file = files[0]

# 2: distinguir não-encontrado de erro real
except subprocess.CalledProcessError as e:
    if e.returncode == 1:  # grep: nenhum match
        return None
    raise  # erro real (permissão, pasta inexistente, etc.)

# 3: corrigir docstring
"""Returns the first match as (step_index, filename) or None if not found."""
```

**Critério de conclusão:**
- [ ] O arquivo com menor índice numérico é sempre retornado (independente da ordem do filesystem)
- [ ] Erros reais do grep são propagados em vez de engolidos
- [ ] Docstring corrigida

---

### TASK-25 — Corrigir `validator.py`: composite, url_match, body bytes e log de falha

**Arquivo:** `har_reproducer/validator.py`
**Depende de:** TASK-05 (SuccessCriterion discriminated unions)

**Contexto:**
Quatro problemas no validador:
1. `composite` não valida o tipo dos sub-critérios antes de iterar
2. `url_match` só verifica `redirect_url`, que pode ser `None` para requisições normais
3. `body_contains` descarta body em bytes silenciosamente
4. Quando `validate` retorna `False`, não loga qual critério falhou

**O que fazer:**

```python
# 1: validar tipo dos sub-critérios (resolvido em grande parte pela TASK-05)
elif criterion.type == "composite":
    sub_criteria = criterion.expected
    if not isinstance(sub_criteria, list):
        return False
    if not all(isinstance(c, SuccessCriterion) for c in sub_criteria):
        print("[ERRO] Critério composite contém itens inválidos")
        return False
    return all(Validator._check_criterion(response, c) for c in sub_criteria)

# 2: url_match — receber StepRequest também, ou usar URL da response
# (decisão de arquitetura: Engine deve passar a URL final junto com a response)

# 3: body em bytes — tentar decodificar antes de descartar
if isinstance(response.body, bytes):
    body = response.body.decode("utf-8", errors="replace")
elif isinstance(response.body, str):
    body = response.body
else:
    body = ""

# 4: logar qual critério falhou
for criterion in criteria:
    if not Validator._check_criterion(response, criterion):
        print(f"[FALHA] Critério não satisfeito: {criterion.type} — esperado: {criterion.expected}")
        return False
return True
```

**Critério de conclusão:**
- [ ] Critério `composite` com itens inválidos loga erro descritivo
- [ ] Body em bytes é decodificado antes da checagem
- [ ] Log identifica qual critério falhou quando `validate` retorna `False`
- [ ] `url_match` tem comportamento documentado para o caso `redirect_url = None`

---

## Seção 5 — Agentes

---

### TASK-26 — Implementar chamada LLM no `BaseAgent` com propagação de erro

**Arquivo:** `har_reproducer/agents/base.py`
**Depende de:** TASK-14 (imports no topo), TASK-16 (decomposição de _verify_code)

**Contexto:**
Nenhum agente chama LLM. O `generate_code` é um template fixo — se falhar na primeira tentativa, vai falhar nas outras 4 com o mesmo código. O loop TDD é inútil sem LLM e sem propagação do erro para a tentativa seguinte.

**O que fazer:**
1. Adicionar `_call_llm(last_error: Optional[str]) -> str` no `BaseAgent`
2. Alterar `run_tdd_loop` para passar `last_error` para `generate_code` a cada tentativa
3. Alterar `_verify_code` para retornar `Tuple[bool, Optional[str]]` (sucesso + stderr)

```python
import anthropic
import json

client = anthropic.Anthropic()

def _call_llm(self, last_error: Optional[str] = None) -> str:
    prompt = f"""
Gere uma função Python chamada extract_{self.safe_token_id}(response: dict) -> str
que extraia o valor '{self.expected_value}' da seguinte response:

{json.dumps(self.response_sample, indent=2)}

{"Erro da tentativa anterior:\\n" + last_error if last_error else ""}

Retorne apenas o código Python, sem explicações.
"""
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

def run_tdd_loop(self, max_attempts: int = 5, origin_step: Optional[int] = None) -> Optional[Extractor]:
    last_error: Optional[str] = None
    for attempt in range(max_attempts):
        code = self.generate_code(last_error=last_error)
        success, error = self._verify_code(code)
        if success:
            return self._build_extractor(code)
        last_error = error
        print(f"[TDD] Tentativa {attempt + 1}/{max_attempts} falhou para {self.token_id}: {error}")
    print(f"[ERRO] Extrator para {self.token_id} não verificado após {max_attempts} tentativas")
    return None

def _verify_code(self, code: str) -> Tuple[bool, Optional[str]]:
    # retorna (True, None) se passou, (False, stderr) se falhou
    ...
```

**Critério de conclusão:**
- [ ] `_call_llm` existe no `BaseAgent` e chama a API da Anthropic
- [ ] `run_tdd_loop` passa `last_error` para `generate_code` a cada iteração
- [ ] `_verify_code` retorna `Tuple[bool, Optional[str]]`
- [ ] O loop realmente gera código diferente entre tentativas quando há erro

---

### TASK-27 — Implementar `generate_code` com LLM no `CookieAgent`

**Arquivo:** `har_reproducer/agents/cookie_agent.py`
**Depende de:** TASK-26

**Contexto:**
Template fixo que busca o cookie pelo nome exato do `token_id`. Na prática o cookie pode ter qualquer nome — só o valor importa para a extração.

**O que fazer:**
Substituir o template fixo por chamada ao LLM com prompt específico de cookie:

```python
def generate_code(self, last_error: Optional[str] = None) -> str:
    return self._call_llm(last_error=last_error)
```

O prompt do `_call_llm` herdado deve instruir o LLM a inspecionar os cookies da response sample e encontrar qual deles contém o `expected_value`, independente do nome do cookie.

**Critério de conclusão:**
- [ ] `CookieAgent.generate_code` chama LLM
- [ ] Código gerado não assume que o nome do cookie é igual ao `token_id`
- [ ] Passa no teste TDD da fixture `tracker_set_cookie`

---

### TASK-28 — Implementar `generate_code` com LLM no `HeaderAgent`

**Arquivo:** `har_reproducer/agents/header_agent.py`
**Depende de:** TASK-26

**Contexto:**
Template fixo com busca por nome exato do header. Além disso, não trata o prefixo `Bearer` — retorna o header inteiro em vez de só o token.

**O que fazer:**
1. Substituir template por chamada ao LLM
2. Instruir o LLM a remover prefixos conhecidos (`Bearer `, `Token `)

```python
def generate_code(self, last_error: Optional[str] = None) -> str:
    return self._call_llm(last_error=last_error)
```

**Critério de conclusão:**
- [ ] `HeaderAgent.generate_code` chama LLM
- [ ] Código gerado trata o caso `Authorization: Bearer <token>` extraindo só o token
- [ ] Passa no teste TDD da fixture `tracker_jwt_body`

---

### TASK-29 — Implementar `generate_code` com LLM no `JSONPathAgent`

**Arquivo:** `har_reproducer/agents/jsonpath_agent.py`
**Depende de:** TASK-26

**Contexto:**
Template fixo usando `data.get(token_id)` em vez de jsonpath real. A biblioteca `jsonpath-ng` está no projeto mas não é usada.

**O que fazer:**
1. Substituir template por chamada ao LLM
2. Instruir o LLM a usar `jsonpath_ng` para navegar estruturas JSON aninhadas

```python
def generate_code(self, last_error: Optional[str] = None) -> str:
    return self._call_llm(last_error=last_error)
```

O prompt deve especificar que o código gerado deve usar `jsonpath_ng.ext.parser.parse` e pode gerar expressões como `$.data.token` ou `$.access_token`.

**Critério de conclusão:**
- [ ] `JSONPathAgent.generate_code` chama LLM
- [ ] Código gerado usa `jsonpath_ng`
- [ ] Passa no teste TDD da fixture `tracker_jwt_body`

---

### TASK-30 — Implementar `generate_code` com LLM no `CSSAgent`

**Arquivo:** `har_reproducer/agents/css_agent.py`
**Depende de:** TASK-26

**Contexto:**
Template fixo com seletor `.token_id` (classe CSS) que nunca funciona. Além disso, usa `.text` em vez de `.get('value')` para inputs HTML.

**O que fazer:**
1. Substituir template por chamada ao LLM
2. Instruir o LLM a usar `BeautifulSoup` e gerar seletores CSS reais baseados na response sample
3. Instruir o LLM a usar `.get('value')` para elementos `<input>`

```python
def generate_code(self, last_error: Optional[str] = None) -> str:
    return self._call_llm(last_error=last_error)
```

**Critério de conclusão:**
- [ ] `CSSAgent.generate_code` chama LLM
- [ ] Código gerado usa seletor real (ex: `input[name="_csrf"]`) em vez de `.token_id`
- [ ] Passa no teste TDD da fixture `tracker_csrf_html`

---

### TASK-31 — Implementar `generate_code` com LLM no `RegexAgent`

**Arquivo:** `har_reproducer/agents/regex_agent.py`
**Depende de:** TASK-26

**Contexto:**
Template fixo com padrão `token_id=([\w-]+)` que só funciona para formato `nome=valor`. Import de `re` desnecessário no arquivo do agente (só é usado no código gerado).

**O que fazer:**
1. Substituir template por chamada ao LLM
2. Remover o `import re` do arquivo do agente (fica só no código gerado)
3. Instruir o LLM a gerar regex que capture o valor exato no contexto real da response

```python
def generate_code(self, last_error: Optional[str] = None) -> str:
    return self._call_llm(last_error=last_error)
```

**Critério de conclusão:**
- [ ] `RegexAgent.generate_code` chama LLM
- [ ] `import re` removido do arquivo do agente
- [ ] Passa no teste TDD da fixture `tracker_script_token`

---

### TASK-32 — Implementar `DiagnoseAgent` com LLM real

**Arquivo:** `har_reproducer/agents/diagnose_agent.py`
**Depende de:** TASK-12 (ferramentas reais), TASK-26 (LLM no BaseAgent)

**Contexto:**
O `diagnose` simula uma busca por `"eyJ"` e sempre retorna o mesmo patch com `target_token_id="auth_token"` hardcoded. Não chama LLM.

**O que fazer:**
1. Substituir `_simulate_diagnosis` por chamada real ao LLM com tool use
2. O LLM deve receber o `FailureContext` e usar as ferramentas `read_step`, `grep_responses` e `get_session_state` para investigar
3. O `target_token_id` do patch deve vir da análise real, não hardcoded

```python
def diagnose(self, failure_context: FailureContext) -> Optional[Patch]:
    # Chamar LLM com tool use, passando failure_context
    # Ferramentas disponíveis: read_step, grep_responses, get_session_state
    ...
```

**Critério de conclusão:**
- [ ] `diagnose` chama LLM com o contexto real de falha
- [ ] `target_token_id` do patch reflete o token que realmente falhou
- [ ] As ferramentas `read_step`, `grep_responses` e `get_session_state` retornam dados reais

---

### TASK-33 — Corrigir `base.py`: output_dir no construtor e decomposição de `_verify_code`

**Arquivo:** `har_reproducer/agents/base.py`
**Depende de:** TASK-14 (imports no topo), TASK-16 (decomposição de métodos)

**Contexto:**
O arquivo temporário do extrator é criado no diretório de execução (`Path(f"temp_extractor_{self.token_id}.py")`), não no output do projeto. Além disso, `_verify_code` acumula muitas responsabilidades.

**O que fazer:**

```python
# Construtor: receber output_dir
def __init__(self, ..., output_dir: Path):
    self.output_dir = output_dir

# Usar output_dir para o arquivo temporário
temp_file = self.output_dir / f"temp_extractor_{self.token_id}.py"
```

Decompor `_verify_code` em:
- `_write_temp_script(code: str) -> Path`
- `_execute_script(script_path: Path) -> Tuple[bool, Optional[str]]`
- `_cleanup_script(script_path: Path) -> None`

**Critério de conclusão:**
- [ ] `BaseAgent` recebe `output_dir` no construtor
- [ ] Arquivo temporário criado dentro de `output_dir`
- [ ] `_verify_code` delegado para submétodos com responsabilidade única