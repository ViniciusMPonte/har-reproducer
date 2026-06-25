# Sugestões de Melhoria

---

## 1. Alterações Globais

Problemas que se repetem em múltiplos arquivos e devem ser resolvidos de forma uniforme em todo o projeto.

---

### 1.1 Tipagem incompleta

Todos os arquivos do projeto têm anotações de tipo parciais ou ausentes. Parâmetros, retornos e variáveis locais relevantes devem ser tipados de forma completa e consistente.

Casos específicos recorrentes:
- Métodos sem tipo de retorno declarado (`-> None`, `-> Optional[X]`, etc.)
- Tipos `Any` em modelos Pydantic onde tipos concretos são viáveis
- Subclasses de agentes que não retiram o tipo de retorno de `generate_code`

---

### 1.2 Imports fora do topo do arquivo

Imports dentro de métodos, blocos `if` e loops foram encontrados em vários arquivos. Todos devem ser movidos para o topo do arquivo, consolidando também imports duplicados do mesmo módulo.

Ocorrências identificadas:

**engine.py**
```python
def _run_extractor(self, ...):
    import sys
    import subprocess
    from pathlib import Path

def apply_patch(self, ...):
    from .models import Extractor

def diagnose(self, ...):
    from .agents.diagnose_agent import DiagnoseAgent
    from .models import FailureContext
```

**tracker.py**
```python
if is_dry_run:
    from .models import Extractor
```

**base.py (agentes)**
```python
def run_tdd_loop(self, ...):
    from har_reproducer.models import Extractor

def _verify_code(self, ...):
    import subprocess
    import sys
    from pathlib import Path
```

**diagnose_agent.py**
```python
def _simulate_diagnosis(self) -> Optional[Patch]:
    import glob
```

---

### 1.3 Métodos muito grandes com responsabilidades demais

Métodos como `analyze_step` (tracker.py) e `_verify_code` (base.py) fazem coisas demais em um único bloco. O padrão a seguir em todo o projeto: o método principal deve ser um **orquestrador** que delega para métodos privados menores.

**Sugestão geral:** extrair cada etapa significativa em seu próprio método privado com nome descritivo.

---

### 1.4 Ifs aninhados demais

Encontrado em vários arquivos, em especial `tracker.py`. Dificulta leitura e teste isolado de condições.

**Sugestão:** usar early return para achatar a estrutura.

```python
# Em vez de:
if origin:
    if response_sample:
        if not is_dry_run:
            ...

# Preferir:
if not origin:
    candidate.status = "Unresolved"
    return candidate

if not response_sample:
    return candidate

extractor = self._generate_extractor(candidate, response_sample)
```

---

### 1.5 Falhas silenciosas em blocos `except Exception`

Padrão recorrente de `except Exception: pass` ou `except Exception` sem log, engolindo erros e dificultando o debug.

**Sugestão:** sempre logar com contexto suficiente para identificar a causa.

```python
# Padrão a seguir em todo o projeto:
except Exception as e:
    print(f"[AVISO] <contexto do que estava sendo feito>: {e}")
```

Ocorrências identificadas: `har_parser.py` (`decode_body`) e `base.py` (timeout de subprocess) — **pendentes**. `tracker.py` (`_load_response`) e `grep_utils.py` (`try_decode`) — ✅ resolvidos.

---

### 1.6 Nenhum agente chama LLM — problema crítico global

O problema mais crítico de todos os agentes é o mesmo: **nenhum deles chama um LLM**. O sistema foi planejado para usar agentes especializados com geração de código via LLM e loop TDD, mas o que foi implementado são templates fixos que ignoram o conteúdo real da response. O resultado prático é que o loop TDD roda 5 vezes gerando exatamente o mesmo código com exatamente o mesmo resultado.

**Sugestão:** implementar a chamada ao LLM no `BaseAgent`, passando à cada tentativa:
- A response sample
- O valor esperado
- O erro da tentativa anterior
- Instruções específicas do domínio de cada agente

```python
import anthropic

client = anthropic.Anthropic()

def _call_llm(self, last_error: Optional[str] = None) -> str:
    prompt = f"""
    Gere uma função Python chamada extract_{self.safe_token_id}(response: dict) -> str
    que extraia o valor '{self.expected_value}' da seguinte response:
    
    {json.dumps(self.response_sample, indent=2)}
    
    {"Erro da tentativa anterior: " + last_error if last_error else ""}
    
    Retorne apenas o código Python, sem explicações.
    """
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text
```

O `run_tdd_loop` deve passar o erro da tentativa anterior para que o LLM possa corrigir:

```python
def run_tdd_loop(self, max_attempts: int = 5, origin_step: Optional[int] = None) -> Optional[Extractor]:
    last_error: Optional[str] = None
    for attempt in range(max_attempts):
        code = self.generate_code(last_error=last_error)
        success, error = self._verify_code(code)
        if success:
            ...
        last_error = error
```

---

## 2. Correções de Pacotes

Problemas de organização entre pacotes: classes no lugar errado, acoplamentos desnecessários e duplicações de modelo.

---

### 2.1 Mover `RecordedRequest` e `CurlGenerator` para dentro do pacote

```python
from src.models.request_record import RecordedRequest
from src.services.curl_generator import CurlGenerator
```

Essas classes estão fora do pacote `har_reproducer`, criando acoplamento desnecessário.

**Sugestão:** mover para dentro do pacote e ajustar os imports.

---

### 2.2 `request_record.py` está fora do pacote `har_reproducer`

O arquivo está em `src.models.request_record` enquanto deveria estar dentro do pacote principal junto com os outros modelos, ou unificado diretamente com o `models.py`. Se a classe `RecordedRequest` for removida conforme sugerido na seção 3.1, esse problema se resolve sozinho.

---

### 2.3 `RecordedRequest` duplica `StepRequest`

Os dois têm `url`, `method`, `headers`, `cookies` e `body`. Qualquer mudança em um precisa ser replicada no outro. Ver sugestão de remoção na seção 3.1.

---

### 2.4 `TokenTrace` duplica `TokenLocation` do `models.py`

O campo `location` de `TokenTrace` é uma string livre — `"Header"`, `"Cookie"`, `"Body"` — mas o `models.py` já tem o tipo `TokenLocation` definido exatamente para isso.

**Sugestão:** se `TokenTrace` for mantido, usar `TokenLocation`.

```python
from .models import TokenLocation

class TokenTrace(BaseModel):
    location: TokenLocation
```

---

### 2.5 Mover lógica do HAR para o `HARParser` (engine.py)

O `Engine` conhece a estrutura interna do HAR diretamente:

```python
har_data.get("log", {}).get("entries", [])
```

**Sugestão:** o `HARParser` deve expor um método que retorne os entries prontos, e o `Engine` só o chama.

```python
entries = HARParser.get_entries(self.har_path)
```

---

## 3. Remoção de Código Não Usado

Dead code e funcionalidades incompletas que devem ser removidos ou conectados ao fluxo real.

---

### 3.1 Remover `RecordedRequest` e simplificar `CurlGenerator`

`RecordedRequest` é criado no `Engine` apenas para ser passado ao `CurlGenerator`, que poderia receber um `StepRequest` diretamente com o `step_index` como parâmetro separado.

**Sugestão:** remover `RecordedRequest` e ajustar o `CurlGenerator`.

```python
# Engine
curl_cmd = CurlGenerator().generate(step.index, final_request, session_store=self.session_store)

# CurlGenerator
def generate(self, step_index: int, request: StepRequest, session_store: Optional[SessionStore] = None) -> str:
```

---

### 3.2 `token_traces` nunca é populado

O `RecordedRequest` tem `token_traces` mas o `CurlGenerator` encontra os traces internamente no `_find_token_traces` e nunca os salva de volta no objeto. O campo existe mas fica sempre vazio.

---

### 3.3 `ExtractorMetadata` é órfão (models.py)

Está definido mas não é usado em lugar nenhum relevante do código. O `Extractor` completo é sempre usado no lugar.

**Sugestão:** remover `ExtractorMetadata` ou unificar com `Extractor`.

---

### 3.4 `try_decode` não é usado em lugar nenhum (grep_utils.py) ✅

**Resolvido.** A função `try_decode` foi integrada ao fluxo de busca por uma abordagem mais ampla: em vez de só decodificar o padrão antes de buscar, a `grep_in_real_responses` agora tenta múltiplas variantes do padrão (literal, decodificado via `try_decode`, URL-encoded e Base64-encoded), parando no primeiro match. Isso cobre tanto o caso em que a response armazena o valor decodificado quanto o caso inverso.

A lógica foi distribuída em duas funções privadas:
- `_build_pattern_variants(pattern)` — gera as variantes deduplicas, reutilizando `try_decode`
- `_grep_single_pattern(responses_dir, pattern)` — executa o grep para um padrão único

---

### 3.5 `Any` importado mas não usado (validator.py)

```python
from typing import List, Any
```

O `Any` está importado mas não é usado em nenhuma anotação deste arquivo.

**Sugestão:** remover.

```python
from typing import List
```

---

### 3.6 `apply_patch` nunca é chamado

O método `apply_patch` existe no `Engine` mas nunca é chamado por ninguém. O `diagnose` retorna um `Patch` que só é impresso na CLI e nunca aplicado. Mesmo problema no `DiagnoseAgent` — retorna um `Patch` mas ninguém o aplica.

**Sugestão:** conectar o `apply_patch` ao fluxo de recuperação, ou remover até que esteja pronto para ser implementado de verdade.

---

### 3.7 Etapa 7 do pipeline não implementada (tracker.py)

O comentário no código diz:
```python
# 7. Validation (Skipped in this basic implementation, assumed by pipeline)
```

A validação dos extratores foi pulada completamente.

**Sugestão:** implementar a validação rodando o extrator gerado contra a response real e verificando se o valor extraído bate com o `expected_value`.

---

### 3.8 Métodos placeholder não implementados (diagnose_agent.py)

Os métodos `read_step`, `grep_responses` e `get_session_state` existem como placeholder mas retornam dados fictícios. São as ferramentas que o LLM usaria para investigar a falha — sem elas o diagnóstico real é impossível.

**Sugestão:** implementar de verdade usando `HARParser`, `grep_utils` e `SessionStore`.

---

### 3.9 Loop TDD nos agentes precisa ser verificado (tracker.py)

O `agent.run_tdd_loop()` é chamado mas o código dos agentes ainda não foi revisado. Pelo curl gerado com JWT hardcoded, é provável que o loop TDD com até 5 tentativas e chamada real ao LLM esteja incompleto ou ausente nos agentes.

**Sugestão:** revisar todos os agentes e confirmar se o fluxo descrito no plano está implementado.

---

## 4. Por Arquivo

Sugestões específicas de cada arquivo não cobertas nas seções anteriores.

---

### cli.py

**Usar a pasta do HAR como base para o output**

Atualmente `output_dir` está fixo como `"reproduction_results"`, relativo ao local de execução.

```python
output_dir = Path(args.har).parent / "reproduction_results"
```

---

**Expor `--output` como argumento no subcomando `run`**

O subcomando `parse` já tem `--output`. O `run` não tem, o que é inconsistente.

```python
run_parser.add_argument(
    "--output",
    default=None,
    help="Output directory (default: pasta do HAR/reproduction_results)"
)
```

E em `handle_run`:

```python
output_dir = Path(args.output) if args.output else Path(args.har).parent / "reproduction_results"
```

---

**Expor `--step` no subcomando `diagnose`**

O step diagnosticado está hardcoded como `step_index=1`.

```python
diag_parser.add_argument("--step", type=int, required=True, help="Índice do step a diagnosticar")
```

E em `handle_diagnose`:

```python
patch = engine.diagnose(step_index=args.step)
```

---

**Remover o `Engine` com HAR fictício no `diagnose`**

Criar `Engine(Path("dummy.har"), ...)` só para usar o diagnóstico é um workaround frágil.

**Sugestão:** extrair a lógica de diagnóstico para uma função independente que não dependa de um HAR.

---

### har_parser.py

**Limpar a pasta de output antes de escrever**

Se a pasta já existir com conteúdo de uma execução anterior, os arquivos velhos ficam misturados com os novos.

```python
import shutil

if output_dir.exists():
    shutil.rmtree(output_dir)
output_dir.mkdir(parents=True)
```

---

**Extrair métodos ignoráveis como constante**

O critério de `is_skippable` está hardcoded dentro de `parse_entry`.

```python
SKIPPABLE_METHODS: set[str] = {"OPTIONS"}

is_skippable = req_data["method"] in HARParser.SKIPPABLE_METHODS
```

---

### engine.py

**Separar `run()` e `dry_run()` em métodos distintos**

O fluxo de dry-run está misturado dentro do loop principal com condicionais, o que complica os dois fluxos e é a causa provável da falha atual.

```python
def run(self) -> bool:
    ...

def dry_run(self) -> None:
    ...
```

---

**Salvar extratores no output final**

Hoje o `_run_extractor` cria um arquivo temporário e o apaga após a execução. O plano prevê que os extratores sejam artefatos permanentes.

**Sugestão:** salvar em `self.output_dir / "extractors"` e nunca apagar.

---

**Salvar curls no output final**

A pasta de curls está hardcoded:

```python
os.makedirs("curls", exist_ok=True)
filename = f"curls/req_{step.index:04d}.curl.sh"
```

**Sugestão:** usar o diretório de output definido na instância.

```python
curls_dir = self.output_dir / "curls"
curls_dir.mkdir(parents=True, exist_ok=True)
filename = curls_dir / f"req_{step.index:04d}.curl.sh"
```

---

**Corrigir o `diagnose` para usar contexto real**

O contexto de falha está hardcoded com dados fictícios:

```python
request_attempted=StepRequest(url="dummy", method="GET"),
response_received=StepResponse(status_code=401, headers={}, cookies={}, body="Unauthorized"),
```

**Sugestão:** salvar o request e a response reais quando um step falha e passá-los ao `FailureContext`.

---

**Investigar geração de extratores**

O `_run_extractor` só executa extratores já existentes no registry. O plano prevê geração via agentes LLM com loop TDD de até 5 tentativas. Essa lógica precisa ser verificada e possivelmente implementada no `TokenTracker`.

---

### tracker.py

**Heurística de detecção muito limitada**

O `_detect_candidates` só considera um campo como token dinâmico se o nome contiver `token`, `jwt`, `auth`, `csrf` ou `session`. Qualquer campo dinâmico com outro nome é ignorado silenciosamente.

**Sugestão:** ampliar a lista de palavras-chave e considerar também campos ausentes no baseline como candidatos automáticos, independente do nome.

---

**Comparação de body muito simplificada**

O `_compare_to_baseline` compara o body inteiro como string. Se qualquer coisa mudar no body — mesmo um campo estático — tudo vai para `diffs`.

**Sugestão:** comparar campo a campo quando o body for JSON, usando `json.loads` para deserializar antes de comparar.

---

**`_determine_location` usa `BodyJSON` como padrão**

Não distingue HTML de JSON. Um body HTML seria classificado como `BodyJSON` e o agente errado seria acionado.

```python
if "text/html" in body_mime: return "BodyHTML"
if "application/json" in body_mime: return "BodyJSON"
```

---

**`_generate_curl_template` não substitui por placeholders**

Os valores dinâmicos vão direto para o curl como valores brutos do HAR. É a falha mais crítica do módulo — o JWT hardcoded no curl gerado é a prova disso.

**Sugestão:** após a detecção dos candidatos, substituir cada valor dinâmico pelo seu `{{token_id}}` correspondente antes de montar o curl.

---

**Dry-run não executa os extratores**

No dry-run, em vez de gerar o extrator real, registra um placeholder com `agent_type="Pending"` e `code=""`. Isso não faz sentido — o dry-run deveria gerar e verificar os extratores normalmente, só sem fazer as requisições HTTP.

**Sugestão:** remover o bloco `else` do dry-run e deixar a geração de extratores igual para os dois modos.

---

**`_extract_static_values` só verifica headers**

Ignora cookies e body completamente.

**Sugestão:** aplicar a mesma lógica para cookies e para campos do body quando for JSON.

---

### agentes — base.py

**Arquivo temporário hardcoded sem usar output_dir**

```python
temp_file = Path(f"temp_extractor_{self.token_id}.py")
```

O arquivo temporário é criado no diretório de execução, não no output do projeto.

**Sugestão:** receber o `output_dir` no construtor e salvar dentro dele.

```python
temp_file = self.output_dir / f"temp_extractor_{self.token_id}.py"
```

---

**`_verify_code` não passa contexto do erro para o loop TDD**

Quando `_verify_code` retorna `False`, o `run_tdd_loop` só imprime que falhou e tenta de novo com o mesmo código. O erro do subprocess é capturado mas descartado.

**Sugestão:** `_verify_code` deve retornar `Tuple[bool, Optional[str]]` e o stderr deve ser passado para o `generate_code` na próxima tentativa.

---

**`_verify_code` tem responsabilidades demais**

Faz muitas coisas: monta o script, salva em disco, executa, compara o resultado e apaga o arquivo. Deveria ser dividido em métodos menores.

---

### agentes — cookie_agent.py

**Busca por nome exato do cookie**

```python
cookies.get('{self.token_id}')
```

Assume que o nome do cookie é exatamente igual ao `token_id`. Na prática o cookie pode ter um nome diferente.

**Sugestão:** o LLM deve inspecionar a response sample e encontrar qual cookie contém o valor esperado, independente do nome.

---

### agentes — header_agent.py

**Busca por nome exato do header**

```python
headers.get('{self.token_id}')
```

Headers como `X-Auth-Token` ou `Authorization` têm nomes que raramente batem com o `token_id` derivado do campo da requisição.

**Sugestão:** o LLM deve inspecionar os headers da response sample e encontrar qual contém o valor esperado.

---

**Não trata o caso `Authorization: Bearer`**

Se o valor estiver em `Authorization: Bearer <token>`, o agente retorna o header inteiro incluindo o prefixo `"Bearer "`, não só o token.

**Sugestão:** detectar e remover prefixos conhecidos como `Bearer ` e `Token `.

---

### agentes — jsonpath_agent.py

**Não usa a biblioteca jsonpath-ng**

O nome do agente sugere que usa jsonpath, mas o código gerado usa `data.get()`. A biblioteca `jsonpath-ng` está listada nas dependências do projeto mas não é usada aqui.

**Sugestão:** o código gerado pelo LLM deve usar `jsonpath_ng` para expressões como `$.data.token` ou `$.access_token`.

---

### agentes — css_agent.py

**Seletor CSS gerado é sempre errado**

```python
soup.select_one('.{self.token_id}')
```

Busca por classe CSS com o nome do token. Um CSRF token típico fica em:

```html
<input name="_csrf" value="abc123">
```

O seletor correto seria `input[name="_csrf"]`, não `._csrf`.

---

**Extrai `.text` em vez do atributo `value`**

Para inputs HTML, o valor do token está no atributo `value`, não no texto do elemento. O código atual faz `element.text.strip()` que vai retornar vazio para inputs.

**Sugestão:** o LLM deve identificar se o elemento é um input e usar `element.get('value')` nesse caso.

---

### agentes — regex_agent.py

**Padrão regex muito específico e frágil**

```python
re.search(r'{self.token_id}=([\w-]+)', body)
```

Só encontra o token se ele aparecer literalmente como `token_id=valor`. JWTs, tokens em JSON dentro de scripts, ou qualquer outro formato vai falhar.

---

**Import `re` desnecessário no arquivo do agente**

O `import re` está no topo do `regex_agent.py` mas só é usado no código que o agente *gera*, não no agente em si. É desnecessário no arquivo do agente.

---

### agentes — diagnose_agent.py

**Diagnóstico sempre retorna o mesmo patch**

Se encontrar `"eyJ"` em qualquer response, retorna sempre:

```python
Patch(
    action="FIX_EXTRACTOR",
    target_token_id="auth_token",
    new_code="..."
)
```

O `target_token_id` está hardcoded como `"auth_token"` independente do token que realmente falhou.

---

### models.py

**`SuccessCriterion` tem tipagem fraca**

```python
class SuccessCriterion(BaseModel):
    type: Literal["url_match", "status_code", "body_contains", "html_element_present", "composite"]
    value: Any
    expected: Any
```

`value` e `expected` como `Any` não dizem nada. Cada tipo de critério tem expectativas diferentes.

**Sugestão:** modelar com tipos específicos por critério usando discriminated unions do Pydantic.

```python
class StatusCodeCriterion(BaseModel):
    type: Literal["status_code"]
    expected: int

class BodyContainsCriterion(BaseModel):
    type: Literal["body_contains"]
    expected: str

SuccessCriterion = Union[StatusCodeCriterion, BodyContainsCriterion, ...]
```

---

**`DynamicToken.origin_step` usa `-1` como sentinela**

No `_detect_candidates` do tracker o token é criado com `origin_step=-1` como sentinela para "ainda não encontrado". O tipo `int` não deixa isso claro e o valor `-1` é um magic number.

```python
origin_step: Optional[int] = None
```

E no tracker:

```python
DynamicToken(
    ...
    origin_step=None,
    status="Unresolved"
)
```

---

**`Extractor.agent_type` com `Literal` é frágil**

```python
agent_type: Literal["CookieAgent", "HeaderAgent", "JSONPathAgent", "CSSAgent", "RegexAgent"]
```

Se um novo agente for criado, é necessário lembrar de atualizar o `Literal` aqui também.

**Sugestão:** usar um `Enum` como fonte única da verdade.

```python
from enum import Enum

class AgentType(str, Enum):
    COOKIE = "CookieAgent"
    HEADER = "HeaderAgent"
    JSONPATH = "JSONPathAgent"
    CSS = "CSSAgent"
    REGEX = "RegexAgent"

class Extractor(BaseModel):
    agent_type: AgentType
```

---

**`Patch` não valida campos obrigatórios por ação**

```python
class Patch(BaseModel):
    action: PatchAction
    target_token_id: Optional[str] = None
    new_value: Optional[str] = None
    new_code: Optional[str] = None
    rationale: str
```

Se `action="INJECT_VALUE"`, o `new_value` é obrigatório. Se `action="FIX_EXTRACTOR"`, o `new_code` é obrigatório. Mas o modelo não valida isso.

**Sugestão:** usar discriminated unions por ação.

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

Patch = Union[InjectValuePatch, FixExtractorPatch, ReplaceExtractorPatch]
```

---

**`PatchAction` e `TokenLocation` deveriam ser Enums**

```python
PatchAction = Literal["FIX_EXTRACTOR", "INJECT_VALUE", "REPLACE_EXTRACTOR"]
TokenLocation = Literal["Header", "Cookie", "BodyJSON", "BodyHTML", "Script"]
```

Strings soltas espalhadas pelo código sem fonte única da verdade.

```python
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

---

**`StepRequest` e `StepResponse` aceitam `bytes` no body**

```python
body: Optional[Union[str, bytes]] = None
```

Aceitar `bytes` complica todo o código que usa o body — é necessário verificar o tipo antes de qualquer operação de string. No `HARParser` o body já é sempre decodificado para string antes de salvar.

**Sugestão:** restringir para `Optional[str] = None` e garantir que a decodificação acontece sempre no `HARParser` antes de criar o objeto.

---

### session.py

**`get_token` lança `KeyError` sem tratamento**

```python
def get_token(self, token_id: str) -> str:
    return self.state.tokens[token_id]
```

Se o token não existir na sessão, vai crashar em qualquer lugar que chame `get_token` sem um try/catch.

**Sugestão:** retornar `Optional[str]` ou aceitar um valor padrão.

```python
def get_token(self, token_id: str, default: Optional[str] = None) -> Optional[str]:
    return self.state.tokens.get(token_id, default)
```

---

**`render` não avisa quando um placeholder não é resolvido**

Se o template tem `{{jwt_main}}` mas o token não está na sessão, o placeholder fica no texto final sem substituição e ninguém avisa. Isso pode causar requisições com `Authorization: Bearer {{jwt_main}}` sendo enviadas para o servidor.

```python
import re

def render(self, template: str) -> str:
    result = template
    for token_id, value in self.state.tokens.items():
        result = result.replace(f"{{{{{token_id}}}}}", value)
    
    unresolved = re.findall(r'\{\{(\w+)\}\}', result)
    if unresolved:
        print(f"[AVISO] Placeholders não resolvidos: {unresolved}")
    
    return result
```

---

**`render_dict` tem tipagem incorreta**

```python
def render_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
```

O método aceita e processa dicionários, listas e strings — mas o tipo declarado só fala em dicionário.

```python
def render_dict(self, data: Any) -> Any:
```

---

**Sem método para verificar se um token existe**

Não há um `has_token` — quem precisa verificar antes de usar é obrigado a acessar `session_store.state.tokens` diretamente, quebrando o encapsulamento.

```python
def has_token(self, token_id: str) -> bool:
    return token_id in self.state.tokens
```

---

**`state` é público e acessado diretamente em vários lugares**

O `self.state` é acessado diretamente em vários arquivos (`session_store.state.tokens`, `session_store.state.registry`), expondo o estado interno e acoplando os outros módulos à estrutura do `SessionState`.

**Sugestão:** expor métodos específicos no `SessionStore` para cada operação necessária, mantendo o `state` privado.

```python
def get_registry(self) -> Dict[str, Extractor]:
    return self.state.registry

def set_extractor(self, token_id: str, extractor: Extractor) -> None:
    self.state.registry[token_id] = extractor

def get_extractor(self, token_id: str) -> Optional[Extractor]:
    return self.state.registry.get(token_id)
```

---

### grep_utils.py

**Ordem dos resultados do `grep -rl` não é garantida**

A documentação oficial do GNU grep não garante ordem na saída do `-rl`. A ordem depende do sistema de arquivos e pode não ser numérica.

**Sugestão:** ordenar os resultados antes de pegar o primeiro, garantindo sempre o arquivo com menor índice.

```python
files = sorted(result.stdout.splitlines())
first_match_file = files[0]
```

---

**`CalledProcessError` mascara erros reais**

O grep retorna código de saída diferente de zero tanto quando não encontra nada quanto quando há um erro real (pasta inexistente, permissão negada, etc.). Os dois casos são tratados como "não encontrado" silenciosamente.

**Sugestão:** distinguir os dois casos pelo `returncode`.

```python
except subprocess.CalledProcessError as e:
    if e.returncode == 1:  # grep não encontrou nada
        return None
    raise  # erro real, propagar
```

---

**Docstring incorreta em `grep_in_real_responses`**

```python
Returns the first match as (step_index, content) or None if not found.
```

Na prática retorna `(step_index, filename)` — o nome do arquivo, não o conteúdo.

```python
Returns the first match as (step_index, filename) or None if not found.
```

---

### validator.py

**`composite` não valida o tipo dos sub-critérios**

O `criterion.expected` é tratado como lista de `SuccessCriterion` mas o modelo define `expected` como `Any`. Se alguém passar uma lista de dicionários em vez de objetos `SuccessCriterion`, o `_check_criterion` vai crashar sem uma mensagem clara.

```python
elif criterion.type == "composite":
    sub_criteria = criterion.expected
    if not isinstance(sub_criteria, list):
        return False
    if not all(isinstance(c, SuccessCriterion) for c in sub_criteria):
        print("[ERRO] Critério composite contém itens inválidos")
        return False
    return all(Validator._check_criterion(response, c) for c in sub_criteria)
```

---

**`url_match` verifica só o `redirect_url`**

O próprio comentário no código reconhece a limitação. Se a última requisição não for um redirecionamento, o `redirect_url` vai ser `None` e o critério sempre vai falhar silenciosamente.

**Sugestão:** o `Engine` deveria passar a URL final da última requisição junto com a response, ou o `Validator` deveria receber o `StepRequest` também.

---

**`body_contains` trata `bytes` como vazio silenciosamente**

```python
body = response.body if isinstance(response.body, str) else ""
```

Se o body for `bytes`, descarta sem avisar e o critério sempre falha.

```python
if isinstance(response.body, bytes):
    body = response.body.decode("utf-8", errors="replace")
elif isinstance(response.body, str):
    body = response.body
else:
    body = ""
```

---

**Nenhum log de qual critério falhou**

Quando `validate` retorna `False`, ninguém sabe qual critério específico não foi satisfeito.

```python
for criterion in criteria:
    if not Validator._check_criterion(response, criterion):
        print(f"[FALHA] Critério não satisfeito: {criterion.type} — esperado: {criterion.expected}")
        return False
return True
```