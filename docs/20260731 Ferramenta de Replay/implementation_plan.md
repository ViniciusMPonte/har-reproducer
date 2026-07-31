# Plano de Implementação — Ferramenta de Replay a partir de Curls Salvos

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma task
> posterior). Cada task é autocontida — não deveria ser necessário reabrir o `spec.md`
> pra executar uma task isolada.

---

## T01 — `Workspace`: novo diretório de replay + métodos de path
**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/fs_io/workspace_dir.py` (`WorkspaceDir`), `har_reproducer/fs_io/workspace.py` (`Workspace`)

**Contexto:**
`Workspace` centraliza a criação/resolução de todos os caminhos do diretório de saída
(`curls`, `real_requests`, `real_responses`, `extractors`, `temp_extractors`,
`mitm_capture`), todos criados de uma vez em `Workspace.init(output_dir)`. A ferramenta
de replay (em desenvolvimento nas próximas tasks) precisa de um diretório novo pra
persistir os resultados de cada execução de replay, sem sobrescrever o histórico
original — e, diferente dos demais, esse diretório tem subpastas dinâmicas (uma por
execução, por `run_id`), criadas sob demanda, não todas de uma vez no `init()`.

**Estado atual:**
- `WorkspaceDir` (enum `str, Enum`) tem: `CURLS`, `REAL_RESPONSES`, `REAL_REQUESTS`,
  `EXTRACTORS`, `TEMP_EXTRACTORS`, `MITM_CAPTURE`.
- `Workspace.init(output_dir)` cria um diretório físico pra cada valor do enum e seta
  como atributo de classe (`setattr(cls, workspace_dir.value, path)`).
- Não existe nenhum método pra resolver caminhos dentro de subdiretórios dinâmicos.

**Estado esperado depois:**
- Novo membro no enum: `REPLAYS = "replays"`. Sujeito ao mesmo mkdir automático do
  `Workspace.init` (diretório pai `replays/` vazio, criado junto com os demais).
- Dois métodos novos em `Workspace`, `classmethod`, com `cls._ensure_initialized()` no
  início (mesmo padrão dos demais):
  - `replay_run_dir(cls, run_id: str) -> Path` — retorna `cls.replays / run_id`, e cria
    esse subdiretório na hora (`mkdir(parents=True, exist_ok=True)`) — diferente dos
    métodos de path fixo existentes, que não criam nada porque o diretório pai já foi
    criado no `init()`.
  - `replay_response_file(cls, run_id: str, index: int) -> Path` — retorna
    `cls.replay_run_dir(run_id) / f"res_{index:04d}.json"` (reaproveita o método
    acima).
- ⚠️ Seguir exatamente o padrão de zero-padding usado em `response_file`/`request_file`/
  `curl_file` (`f"{index:04d}"`).

**Critérios de aceite:**
- [X] `WorkspaceDir.REPLAYS.value == "replays"`.
- [X] Após `Workspace.init(tmp_path)`, `<tmp_path>/replays` existe e está vazio.
- [X] `Workspace.replay_run_dir("20260730_143210")` retorna
      `<tmp_path>/replays/20260730_143210` e cria esse diretório no disco.
- [X] `Workspace.replay_response_file("20260730_143210", 3)` retorna
      `<tmp_path>/replays/20260730_143210/res_0003.json`, com o diretório pai já criado.
- [X] Chamar `replay_run_dir`/`replay_response_file` duas vezes com o mesmo `run_id` não
      lança erro.
- [X] `curl_file`, `response_file`, `request_file`, `extractor_file`,
      `mitm_capture_file`, `get_root_path`, `get_mitmproxy_ca_path` continuam
      funcionando exatamente como antes — nenhuma regressão.

---

## T02 — `ProjectConfig`: novo campo `response_reference_dir`
**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/config.py` (`ProjectConfig`)

**Contexto:**
`ProjectConfig` é o model pydantic carregado por `ProjectConfigLoader` a partir de um
JSON opcional (`--config`). O replay precisa de um diretório de referência
configurável, usado como fonte de resposta para tokens cujo step de origem não faz
parte do schedule de uma execução de replay (implementado em tasks futuras). O campo
precisa existir no model antes de qualquer componente do replay poder usá-lo.

**Estado atual:**
```python
class ProjectConfig(BaseModel):
    llm: Optional[LLMSettings] = None
    success_criteria: List[SuccessCriterion] = Field(default_factory=list)
    proxy_port: Optional[int] = None
    ca_cert_path: Optional[Path] = None
```

**Estado esperado depois:**
- Novo campo, mesmo padrão dos demais:
  ```python
  response_reference_dir: Optional[Path] = None
  ```
- Nenhuma outra mudança em `ProjectConfig`, `ProjectConfigLoader` ou nos usos
  existentes de `ca_cert_path`/`proxy_port`/`success_criteria`/`llm`.
- ⚠️ A resolução do default (quando `None`, usar `Workspace.real_responses`) NÃO é
  feita aqui, nem em `ProjectConfigLoader._apply_defaults` — fica pra T14
  (`handle_replay`), porque `_apply_defaults` é compartilhado com `run`/`parse` e não
  deve depender de `Workspace` já estar inicializado.

**Critérios de aceite:**
- [X] `ProjectConfig()` continua funcionando, com `response_reference_dir is None`.
- [X] `ProjectConfig(response_reference_dir="/algum/caminho")` aceita e converte pra
      `Path`.
- [X] JSON de config sem o campo continua parseando normalmente via
      `ProjectConfigLoader.load` (retrocompatibilidade).
- [X] JSON de config com `"response_reference_dir": "/algum/caminho"` é parseado
      corretamente.
- [X] Nenhuma regressão nos campos existentes (`llm`, `success_criteria`, `proxy_port`,
      `ca_cert_path`).

---

## T03 — `CurlDependencyParser`: extrai origem dos tokens a partir dos comentários do curl
**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/replay/__init__.py` (novo, vazio),
`har_reproducer/replay/curl_dependency_parser.py` (novo)

**Contexto:**
Todo `req_XXXX.curl.sh` gerado por `CurlGenerator` tem, opcionalmente, linhas de
comentário no topo declarando de qual step cada token referenciado se origina, no
formato exato `# Token {token_id} comes from response of step {origin_step}` (uma linha
por token com `origin_step` não-nulo). É a única fonte de dependência token→step
disponível sem reexecutar análise — essencial pro modo `smart` do replay (calcular quais
steps precisam ser reexecutados) e pra decidir, por token, de qual diretório ler a
resposta de origem.

**Estado atual:**
Esse componente não existe. Não há forma programática de extrair `token_id →
origin_step` a partir de um texto de curl salvo — hoje essa relação só existe em
memória durante a análise (`TokenTracker`), que o replay não executa.

**Estado esperado depois:**
```python
import re
from re import Pattern
from typing import ClassVar, Dict


class CurlDependencyParser:
    DEPENDENCY_PATTERN: ClassVar[Pattern[str]] = re.compile(
        r"^# Token (?P<token_id>[a-f0-9]+) comes from response of step (?P<origin_step>\d+)$",
        re.MULTILINE,
    )

    def parse(self, curl_text: str) -> Dict[str, int]:
        return {
            match.group("token_id"): int(match.group("origin_step"))
            for match in self.DEPENDENCY_PATTERN.finditer(curl_text)
        }
```
- Token sem linha de comentário correspondente: simplesmente não aparece no dict — não
  é erro.
- Criar `har_reproducer/replay/__init__.py` vazio (só pra tornar o pacote importável;
  re-exportar ou não os componentes fica a critério de quem implementar).

**Critérios de aceite:**
- [X] `parse("# Token abc123 comes from response of step 0\ncurl ...")` retorna
      `{"abc123": 0}`.
- [X] `parse(texto_sem_comentario)` retorna `{}`.
- [X] Curl com múltiplas linhas de comentário (múltiplos tokens) retorna todas as
      entradas.
- [X] Linha mal formada (ex. sem "comes from response of step") não gera entrada
      espúria.
- [X] `token_id` aparecendo só dentro de um `{{extractor:...}}` no corpo do curl (fora
      de uma linha de comentário) não interfere no resultado.

---

## T04 — `ReplayResultComparator`: compara status code do replay com o original
**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/replay/replay_result_comparator.py` (novo)

**Contexto:**
Ao final de qualquer execução de replay, é preciso saber se o resultado "bate" com a
execução original — por ora, uma comparação simples de `status_code` do último step
processado contra o `res_XXXX.json` original daquele índice, **sempre** vindo de
`real_responses/` (nunca de um diretório de referência configurável — este pode não
conter o response do último step). A leitura do original usa regex simples sobre o
texto bruto do arquivo, sem parsear o JSON inteiro — decisão deliberada pra manter
simples agora.

**Estado atual:**
Esse componente não existe. `Engine._validate_final` usa `Validator` +
`success_criteria` do `ProjectConfig`, mas essa lógica não se aplica ao replay
(decisão tomada: não reaproveitar `Validator`/`success_criteria` aqui).

**Estado esperado depois:**
```python
import re
from re import Match, Pattern
from typing import ClassVar, Optional

from har_reproducer.fs_io import Workspace
from har_reproducer.models import StepResponse


class ReplayResultComparator:
    STATUS_CODE_PATTERN: ClassVar[Pattern[str]] = re.compile(r'"status_code"\s*:\s*(\d+)')

    def matches_original(self, index: int, response: StepResponse) -> bool:
        try:
            original_text: str = Workspace.response_file(index).read_text(encoding="utf-8")
        except Exception as e:
            print(f"Could not read original response for step {index} to compare: {e}")
            return False

        match: Optional[Match[str]] = self.STATUS_CODE_PATTERN.search(original_text)
        if match is None:
            print(f"Could not find status_code in original response for step {index} to compare.")
            return False
        return int(match.group(1)) == response.status_code
```
- `Workspace.response_file(index)` é o método já existente (hardcoded pra
  `real_responses/`) — não confundir com `replay_response_file` (T01), que é do
  diretório de replay. É intencional usar sempre o original aqui.
- ⚠️ Leitura envolvida em `try/except Exception` (padrão de borda de I/O do guia de
  estilo) — arquivo original ausente não deve propagar exceção, só degradar pra `False`
  com aviso.

**Critérios de aceite:**
- [X] `matches_original(3, StepResponse(status_code=200, ...))` retorna `True` quando o
      `res_0003.json` original tem `"status_code": 200`.
- [X] Retorna `False` quando os status codes divergem.
- [X] Retorna `False` (com print, sem exceção) quando o arquivo original não existe.
- [X] Retorna `False` (com print, sem exceção) quando o arquivo existe mas não tem
      `status_code` reconhecível pela regex.
- [X] Não é afetado por diferenças em headers/body/cookies — só `status_code` importa.

---

## T05 — `StepRetryPolicy`: extrai o loop de tentativas/recuperação do `Engine`
**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/reproduction/step_retry_policy.py` (novo)

**Contexto:**
Hoje a lógica de "tentar até N vezes, com recuperação determinística entre tentativas"
está inline em `Engine.execute_step`/`handle_recovery`, amarrada a atributos de
instância do `Engine`. O replay precisa da mesma política (mesmos
`MAX_STEP_ATTEMPTS`/`RECOVERABLE_STATUS_CODES`), mas com uma noção de "tentativa"
diferente — por isso a lógica precisa ser extraída pra um componente parametrizado por
funções, compartilhado entre `Engine` (T09) e `ReplayRunner` (T12).

**Estado atual** (em `har_reproducer/engines/engine.py`, só leitura de referência nesta
task — não mexer nele aqui):
```python
RECOVERABLE_STATUS_CODES: ClassVar[Set[int]] = {400, 401}
MAX_STEP_ATTEMPTS: ClassVar[int] = 2
...
def execute_step(self, step: Step) -> StepResponse:
    for attempt in range(self.MAX_STEP_ATTEMPTS):
        response: StepResponse = self._attempt_step(step)
        is_last_attempt = attempt == self.MAX_STEP_ATTEMPTS - 1
        if not is_last_attempt and self.handle_recovery(response):
            print(f"Deterministic recovery successful for step {step.index}. Retrying request...")
            continue
        return response
    raise RuntimeError(f"execute_step exhausted {self.MAX_STEP_ATTEMPTS} attempts for step {step.index}")
```

**Estado esperado depois:**
```python
from typing import Callable, ClassVar, Set

from har_reproducer.models import StepResponse


class StepRetryPolicy:
    MAX_STEP_ATTEMPTS: ClassVar[int] = 2
    RECOVERABLE_STATUS_CODES: ClassVar[Set[int]] = {400, 401}

    def execute(
        self,
        step_index: int,
        attempt_fn: Callable[[], StepResponse],
        recovery_fn: Callable[[StepResponse], bool],
    ) -> StepResponse:
        for attempt in range(self.MAX_STEP_ATTEMPTS):
            response: StepResponse = attempt_fn()
            is_last_attempt: bool = attempt == self.MAX_STEP_ATTEMPTS - 1
            if not is_last_attempt and recovery_fn(response):
                print(f"Recovery successful for step {step_index}. Retrying request...")
                continue
            return response
        raise RuntimeError(f"execute exhausted {self.MAX_STEP_ATTEMPTS} attempts for step {step_index}")
```
- `recovery_fn` encapsula, como hoje, tanto a checagem de `status_code in
  RECOVERABLE_STATUS_CODES` quanto a ação de recuperação — `execute()` não faz essa
  checagem sozinho.
- ⚠️ Mudanças de texto já confirmadas como aceitáveis: exceção final vira
  `"execute exhausted {N} attempts for step {step_index}"`; print de recuperação vira
  `"Recovery successful for step {step_index}. Retrying request..."`.
- Esta task NÃO altera `engine.py` — só cria o componente novo (integração é T09).

**Critérios de aceite:**
- [X] `execute(0, attempt_fn, recovery_fn)` chama `attempt_fn()` uma vez e retorna a
      resposta se o status não for recuperável.
- [X] Status 400 na primeira tentativa + `recovery_fn` retornando `True`: `attempt_fn()`
      é chamado uma segunda vez; o retorno de `execute` é o da segunda chamada.
- [X] Todas as `MAX_STEP_ATTEMPTS` tentativas com status recuperável e `recovery_fn`
      sempre `True`: `execute` lança `RuntimeError("execute exhausted 2 attempts for step {step_index}")`.
- [X] `recovery_fn` nunca é chamado na última tentativa, mesmo com status recuperável.
- [X] `MAX_STEP_ATTEMPTS`/`RECOVERABLE_STATUS_CODES` acessíveis via instância e via
      classe (`StepRetryPolicy.RECOVERABLE_STATUS_CODES`).

---

## T06 — `ExtractorTemplate`: script gerado suporta override de diretório de resposta
**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/templates/extractor_template.py`
(`render_script`)

**Contexto:**
Todo `extract_{token_id}.py` gerado por `render_script` tem uma `_load_response()`
interna que hoje sempre lê de `real_responses/`, de forma fixa. O replay precisa, em
alguns casos (modo `smart` reexecutando um step de origem via HTTP), que esse script
leia de um diretório diferente (o diretório desta execução de replay), sem afetar em
nada o uso atual do `Engine`.

**Estado atual:**
```python
@staticmethod
def render_script(safe_token_id: str, code: str, step_index: int) -> str:
    return f"""
import sys
import json
from pathlib import Path
from typing import Dict

{code}

def _load_response() -> Dict:
    response_file: Path = Path(__file__).resolve().parent.parent / "{WorkspaceDir.REAL_RESPONSES.value}" / "res_{step_index:04d}.json"
    return json.loads(response_file.read_text(encoding="utf-8"))

if __name__ == "__main__":
    try:
        response = _load_response()
        result = extract_{safe_token_id}(response)
        print(result)
    except Exception:
        sys.exit(1)
"""
```

**Estado esperado depois:**
```python
@staticmethod
def render_script(safe_token_id: str, code: str, step_index: int) -> str:
    return f"""
import os
import sys
import json
from pathlib import Path
from typing import Dict

{code}

def _load_response() -> Dict:
    override_dir = os.environ.get("HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR")
    if override_dir:
        response_file: Path = Path(override_dir) / "res_{step_index:04d}.json"
    else:
        response_file: Path = Path(__file__).resolve().parent.parent / "{WorkspaceDir.REAL_RESPONSES.value}" / "res_{step_index:04d}.json"
    return json.loads(response_file.read_text(encoding="utf-8"))

if __name__ == "__main__":
    try:
        response = _load_response()
        result = extract_{safe_token_id}(response)
        print(result)
    except Exception:
        sys.exit(1)
"""
```
- Nome exato da env var: `HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR` — referenciado por T07,
  precisa bater exatamente.
- `render_bash_script` e `render_temp_script` não são tocados nesta task.
- ⚠️ Garantia de não regressão: sem a env var setada (todo o fluxo atual do `Engine`),
  comportamento idêntico ao de hoje.

**Critérios de aceite:**
- [ ] Sem `HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR` setada no ambiente do script gerado:
      lê de `real_responses/res_{step_index:04d}.json` relativo ao arquivo — igual hoje.
- [ ] Script escrito em disco e rodado com a env var apontando pra um diretório
      alternativo (com `res_{step_index:04d}.json` diferente): lê desse diretório.
- [ ] Script escrito e rodado sem a env var, com o arquivo em `real_responses/`: ainda
      funciona (regressão do comportamento atual).
- [ ] `render_bash_script`/`render_temp_script` não mudam (fora de escopo).

---

## T07 — `ExtractorRunner`: `run_existing` aceita diretório de override de resposta
**Depende de:** T06 (a env var só faz efeito se o script gerado já souber lê-la — os
dois lados dessa feature precisam existir juntos pra ser testável de ponta a ponta).
**Arquivos envolvidos:** `har_reproducer/reproduction/extractor_runner.py`
(`run_existing`, `_execute_extractor_script`)

**Contexto:**
`ExtractorRunner.run_existing(token_id)` hoje só localiza e executa o script já
existente em disco, sem nenhuma forma de influenciar de onde ele lê a resposta (isso é
resolvido dentro do próprio script — mudança feita em T06). Falta o lado que passa esse
override quando quem chama precisa — exatamente o caso do replay.

**Estado atual:**
```python
def run_existing(self, token_id: str) -> Optional[str]:
    extractor_file: Path = Workspace.extractor_file(token_id)
    if not extractor_file.exists():
        return None
    return self._execute_extractor_script(extractor_file)

def _execute_extractor_script(self, extractor_file: Path) -> Optional[str]:
    try:
        result: CompletedProcess[str] = subprocess.run(
            [sys.executable, str(extractor_file)],
            capture_output=True,
            text=True,
            timeout=self.EXTRACTOR_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()
```

**Estado esperado depois:**
```python
def run_existing(self, token_id: str, response_override_dir: Optional[Path] = None) -> Optional[str]:
    extractor_file: Path = Workspace.extractor_file(token_id)
    if not extractor_file.exists():
        return None
    return self._execute_extractor_script(extractor_file, response_override_dir)

def _execute_extractor_script(
    self, extractor_file: Path, response_override_dir: Optional[Path] = None
) -> Optional[str]:
    env: Dict[str, str] = self._build_env(response_override_dir)
    try:
        result: CompletedProcess[str] = subprocess.run(
            [sys.executable, str(extractor_file)],
            capture_output=True,
            text=True,
            timeout=self.EXTRACTOR_TIMEOUT_SECONDS,
            env=env,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()

@staticmethod
def _build_env(response_override_dir: Optional[Path]) -> Dict[str, str]:
    env: Dict[str, str] = dict(os.environ)
    if response_override_dir is not None:
        env["HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR"] = str(response_override_dir)
    return env
```
- Imports novos: `os`, `Dict` do `typing` (checar se já não estão importados no
  arquivo).
- `run` (usado por `_write_extractor_script`, chamado a partir de um `Extractor` em
  memória) não é tocado.
- ⚠️ Garantia de não regressão: `TokenResolver` (usado pelo `Engine`) chama `run`, não
  `run_existing` — não é afetado. Chamadas existentes de `run_existing(token_id)` sem o
  segundo argumento continuam funcionando (default `None` → comportamento idêntico).

**Critérios de aceite:**
- [ ] `run_existing("abc123")` (sem segundo argumento) funciona exatamente como hoje —
      nenhuma env var extra é setada além do `os.environ` herdado.
- [ ] `run_existing("abc123", Path("/tmp/algum_dir"))` seta
      `HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR=/tmp/algum_dir` no ambiente do subprocess.
- [ ] Combinado com T06: `response_override_dir` apontando pra um diretório com
      `res_XXXX.json` diferente do original faz o extractor retornar o valor extraído
      da resposta alternativa.
- [ ] `extractor_file` inexistente continua retornando `None`, com ou sem
      `response_override_dir`.
- [ ] Timeout/exit code != 0 continuam retornando `None`.

---

## T08 — `ReplayTokenResolver`: resolve tokens de um curl sob demanda
**Depende de:** T03 (`CurlDependencyParser`), T07 (`ExtractorRunner` com
`response_override_dir`)
**Arquivos envolvidos:** `har_reproducer/replay/replay_token_resolver.py` (novo)

**Contexto:**
`TokenResolver.resolve_all()` (usado pelo `Engine`) itera
`session_store.state.registry`, populado durante a análise de cada step — o replay não
roda análise, então esse registry nunca é populado e `TokenResolver` não pode ser
reaproveitado. O replay precisa resolver, sob demanda, só os tokens referenciados no
texto de um curl específico, decidindo por token se a resposta de origem vem do
diretório desta execução de replay (quando o step de origem também está sendo
reexecutado nesta run) ou de um diretório de referência (quando não está).

**Estado atual:**
Esse componente não existe.

**Estado esperado depois:**
```python
from pathlib import Path
from typing import Dict, Optional, Set

from har_reproducer.reproduction import ExtractorRunner
from har_reproducer.replay.curl_dependency_parser import CurlDependencyParser
from har_reproducer.session import SessionStore


class ReplayTokenResolver:
    def __init__(
        self,
        session_store: SessionStore,
        extractor_runner: ExtractorRunner,
        dependency_parser: CurlDependencyParser,
    ) -> None:
        self.session_store: SessionStore = session_store
        self.extractor_runner: ExtractorRunner = extractor_runner
        self.dependency_parser: CurlDependencyParser = dependency_parser

    def resolve(
        self,
        curl_text: str,
        schedule: Set[int],
        replay_run_dir: Path,
        res_refer_dir: Path,
    ) -> None:
        dependencies: Dict[str, int] = self.dependency_parser.parse(curl_text)
        token_ids: Set[str] = set(SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text))
        for token_id in token_ids:
            self._resolve_one(token_id, dependencies, schedule, replay_run_dir, res_refer_dir)

    def _resolve_one(
        self,
        token_id: str,
        dependencies: Dict[str, int],
        schedule: Set[int],
        replay_run_dir: Path,
        res_refer_dir: Path,
    ) -> None:
        origin_step: Optional[int] = dependencies.get(token_id)
        override_dir: Path = replay_run_dir if origin_step in schedule else res_refer_dir
        value: Optional[str] = self.extractor_runner.run_existing(token_id, override_dir)
        if value is None:
            print(f"Failed to resolve token '{token_id}' during replay: extractor returned no value.")
            return
        self.session_store.set_token(token_id, value)
```
- ⚠️ `origin_step in schedule` com `origin_step is None` sempre é `False` — não precisa
  checagem explícita antes, cai naturalmente no `res_refer_dir`.
- ⚠️ `override_dir` nunca é `None` aqui — sempre um dos dois diretórios explícitos
  (diferente de como `run_existing` é usado hoje pelo `Engine`/`TokenResolver`, que
  nunca passa override).
- Confirmar que `SessionStore.TOKEN_PLACEHOLDER_PATTERN` é acessível como `ClassVar`
  público sem instanciar `SessionStore`.

**Critérios de aceite:**
- [ ] Token cujo `origin_step` está em `schedule`: `run_existing` é chamado com
      `replay_run_dir`.
- [ ] Token cujo `origin_step` NÃO está em `schedule`: `run_existing` é chamado com
      `res_refer_dir`.
- [ ] Token sem linha de comentário correspondente (origin desconhecido): tratado como
      "fora do schedule", usa `res_refer_dir`.
- [ ] Mesmo `token_id` aparecendo mais de uma vez no curl: `run_existing` é chamado uma
      única vez pra esse `token_id`.
- [ ] Dois tokens diferentes, origens diferentes (um dentro do schedule, outro fora):
      cada um usa o diretório correto, independentemente.
- [ ] `run_existing` retornando `None` pra um token: `set_token` não é chamado pra esse
      `token_id`, mas a resolução dos demais tokens do mesmo curl continua.
- [ ] Nenhuma exceção propaga de `resolve()` mesmo se algum extractor falhar.

---

## T09 — `Engine`: passa a compor `StepRetryPolicy`
**Depende de:** T05 (`StepRetryPolicy`)
**Arquivos envolvidos:** `har_reproducer/engines/engine.py`

**Contexto:**
Pedido explícito de extrair a lógica de retry/recuperação (T05), reaproveitável entre
`Engine` e o replay. O `Engine` precisa passar a usar esse componente em vez de manter a
lógica (e as constantes) inline/duplicada.

**Estado atual:**
```python
class Engine:
    USES_NETWORK: ClassVar[bool] = True
    RECOVERABLE_STATUS_CODES: ClassVar[Set[int]] = {400, 401}
    MAX_STEP_ATTEMPTS: ClassVar[int] = 2
    ...
    def handle_recovery(self, response: StepResponse) -> bool:
        if response.status_code not in self.RECOVERABLE_STATUS_CODES:
            return False
        print(f"Detected {response.status_code}. Attempting deterministic recovery (token refresh)...")
        self.token_resolver.resolve_all()
        return True

    def execute_step(self, step: Step) -> StepResponse:
        for attempt in range(self.MAX_STEP_ATTEMPTS):
            response: StepResponse = self._attempt_step(step)
            is_last_attempt = attempt == self.MAX_STEP_ATTEMPTS - 1
            if not is_last_attempt and self.handle_recovery(response):
                print(f"Deterministic recovery successful for step {step.index}. Retrying request...")
                continue
            return response
        raise RuntimeError(f"execute_step exhausted {self.MAX_STEP_ATTEMPTS} attempts for step {step.index}")
```

**Estado esperado depois:**
- `Engine.__init__` ganha `self.retry_policy: StepRetryPolicy = StepRetryPolicy()`
  (import novo, do módulo criado em T05).
- `RECOVERABLE_STATUS_CODES`/`MAX_STEP_ATTEMPTS` deixam de existir como `ClassVar` do
  `Engine` — removidos.
- `handle_recovery` passa a checar `self.retry_policy.RECOVERABLE_STATUS_CODES` em vez
  de `self.RECOVERABLE_STATUS_CODES`; resto do método inalterado.
- `execute_step` vira:
  ```python
  def execute_step(self, step: Step) -> StepResponse:
      return self.retry_policy.execute(step.index, lambda: self._attempt_step(step), self.handle_recovery)
  ```
- `_attempt_step` não muda.
- ⚠️ Mudanças de texto já confirmadas: exceção de esgotamento e print de recuperação
  bem-sucedida mudam de wording (definidos em `StepRetryPolicy`, T05).
- ⚠️ `DryEngine` (subclasse) sobrescreve `execute_step` inteiramente e não usa
  `retry_policy` — não precisa ser tocado.

**Critérios de aceite:**
- [ ] `Engine.RECOVERABLE_STATUS_CODES`/`Engine.MAX_STEP_ATTEMPTS` não existem mais
      como atributos da classe.
- [ ] `execute_step(step)` com status 200 na primeira tentativa retorna a resposta sem
      chamar `handle_recovery`.
- [ ] `execute_step(step)` com status 401 na primeira tentativa e sucesso na segunda:
      `token_resolver.resolve_all()` chamado uma vez, `_attempt_step` chamado duas
      vezes.
- [ ] `execute_step(step)` esgotando as duas tentativas com status sempre recuperável
      lança `RuntimeError("execute exhausted 2 attempts for step {step.index}")`.
- [ ] `DryEngine.execute_step` continua funcionando sem mudança.
- [ ] Nenhuma outra parte do `Engine` (`_reproduce`, `_process_entry`, `_persist_*`,
      `_validate_final`, `_build_llm`, `_build_http_transport`) muda de comportamento.

---

## T10 — CLI: flag `--no-reset` para `run`/`parse`
**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/cli/cli_parser.py`,
`har_reproducer/cli/cli_handlers.py`

**Contexto:**
Hoje `handle_run`/`handle_parse` sempre apagam e recriam o diretório de saída antes de
rodar, sem opção de manter o conteúdo existente. Precisa de uma flag opcional pra pular
esse reset, mantendo o comportamento atual como default (mudança estritamente aditiva).

**Estado atual (`cli_parser.py`):**
```python
def _build_run_subparser(self, subparsers) -> None:
    run_parser: ArgumentParser = subparsers.add_parser("run")
    run_parser.add_argument("--har", required=True, ...)
    run_parser.add_argument("--output", default=None, ...)
    run_parser.add_argument("--mode", choices=[...], default=EngineMode.MAIN.value, ...)
    run_parser.add_argument("--config", ...)
    run_parser.set_defaults(func=self._handlers.handle_run)

def _build_parse_subparser(self, subparsers) -> None:
    parse_parser: ArgumentParser = subparsers.add_parser("parse")
    parse_parser.add_argument("--har", required=True, ...)
    parse_parser.add_argument("--output", default=None, ...)
    parse_parser.set_defaults(func=self._handlers.handle_parse)
```

**Estado atual (`cli_handlers.py`):**
```python
def handle_run(self, args: Namespace) -> None:
    har_path: Path = Path(args.har)
    output_dir: Path = self._resolve_output_dir(args, har_path)
    self._reset_output_dir(output_dir)
    ...

def handle_parse(self, args: Namespace) -> None:
    har_path: Path = Path(args.har)
    output_dir: Path = self._resolve_output_dir(args, har_path)
    self._reset_output_dir(output_dir)
    ...
```

**Estado esperado depois:**
- Em `cli_parser.py`, em `_build_run_subparser` e `_build_parse_subparser`:
  ```python
  run_parser.add_argument(
      "--no-reset",
      dest="reset_output_dir",
      action="store_false",
      default=True,
      help="Não apagar/recriar o diretório de saída antes de rodar (default: apaga e recria)",
  )
  ```
  (idem em `parse_parser`).
- Em `cli_handlers.py`:
  ```python
  def handle_run(self, args: Namespace) -> None:
      har_path: Path = Path(args.har)
      output_dir: Path = self._resolve_output_dir(args, har_path)
      if args.reset_output_dir:
          self._reset_output_dir(output_dir)
      ...

  def handle_parse(self, args: Namespace) -> None:
      har_path: Path = Path(args.har)
      output_dir: Path = self._resolve_output_dir(args, har_path)
      if args.reset_output_dir:
          self._reset_output_dir(output_dir)
      ...
  ```
- ⚠️ Esta task não mexe no subcomando `replay` (nunca terá essa flag nem chamará
  `_reset_output_dir` — tratado em T13/T14).

**Critérios de aceite:**
- [ ] `run --har x.har` (sem `--no-reset`) continua apagando/recriando `output_dir`,
      igual hoje.
- [ ] `run --har x.har --no-reset` NÃO apaga `output_dir` existente.
- [ ] Mesmo comportamento pra `parse`.
- [ ] `args.reset_output_dir` é `True` por default quando a flag não é passada.
- [ ] Nenhuma outra parte de `handle_run`/`handle_parse` muda.

---

## T11 — `ReplayRunner`: cálculo do schedule para os 4 modos
**Depende de:** T01 (`Workspace.replay_run_dir`/`replay_response_file`,
`Workspace.curls`), T03 (`CurlDependencyParser`, usado direto pelo modo `smart`)
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py` (novo — só cálculo de
schedule nesta task; execução propriamente dita é T12)

**Contexto:**
Os quatro modos de replay (`all`, `slice`, `smart`, `list`) diferem só em como calculam
o conjunto de steps a processar (`schedule`) e a ordem de iteração
(`ordered_indexes`) — a execução por step (T12) é idêntica pros quatro. Esta task cobre
só o cálculo do schedule, isolado e testável sem subir proxy nem executar HTTP.

**Estado atual:**
Esse componente não existe.

**Estado esperado depois:**
```python
import re
from pathlib import Path
from re import Pattern
from typing import ClassVar, List, Optional, Set, Tuple

from har_reproducer.fs_io import Workspace
from har_reproducer.replay.curl_dependency_parser import CurlDependencyParser


class ReplayRunner:
    STEP_FILENAME_PATTERN: ClassVar[Pattern[str]] = re.compile(r"req_(\d+)\.curl\.sh")

    def __init__(self, dependency_parser: CurlDependencyParser) -> None:
        self.dependency_parser: CurlDependencyParser = dependency_parser

    def _schedule_all(self) -> Tuple[List[int], Set[int]]:
        ordered_indexes: List[int] = self._existing_step_indexes()
        return ordered_indexes, set(ordered_indexes)

    def _schedule_slice(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
        existing: List[int] = self._existing_step_indexes()
        effective_from: int = from_index if from_index is not None else 0
        effective_to: int = to_index if to_index is not None else max(existing)
        ordered_indexes: List[int] = list(range(effective_from, effective_to + 1))
        return ordered_indexes, set(ordered_indexes)

    def _schedule_smart(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]:
        existing: List[int] = self._existing_step_indexes()
        floor: int = from_index if from_index is not None else 0
        target: int = to_index if to_index is not None else max(existing)

        schedule: Set[int] = {target}
        pending: Set[int] = {target}
        while pending:
            current: int = pending.pop()
            curl_text: str = Workspace.curl_file(current).read_text(encoding="utf-8")
            dependencies = self.dependency_parser.parse(curl_text)
            for origin_step in dependencies.values():
                if origin_step >= floor and origin_step not in schedule:
                    schedule.add(origin_step)
                    pending.add(origin_step)

        return sorted(schedule), schedule

    def _schedule_list(self, steps_file: Path) -> Tuple[List[int], Set[int]]:
        lines: List[str] = steps_file.read_text(encoding="utf-8").splitlines()
        ordered_indexes: List[int] = [int(line.strip()) for line in lines if line.strip()]
        return ordered_indexes, set(ordered_indexes)

    def _existing_step_indexes(self) -> List[int]:
        indexes: List[int] = []
        for path in Workspace.curls.glob("req_*.curl.sh"):
            match = self.STEP_FILENAME_PATTERN.match(path.name)
            if match is not None:
                indexes.append(int(match.group(1)))
        return sorted(indexes)
```
- ⚠️ `_existing_step_indexes` usa regex sobre `path.name` (não `path.stem` — o nome do
  arquivo tem dois sufixos, `.curl.sh`, e `Path.stem` só remove o último, então
  `path.stem` de `req_0003.curl.sh` seria `req_0003.curl`, o que quebraria um parsing
  ingênuo por `split("_")`; o regex sobre `path.name` evita esse problema).
- `_schedule_smart` usa `dependencies.values()` (todos os `origin_step` retornados pelo
  parser pra aquele curl) — como `CurlDependencyParser.parse` já só retorna entradas
  cujas linhas de comentário existem nesse `curl_text` específico, isso já está
  implicitamente filtrado; não precisa cruzar com o padrão de placeholder aqui.
- Se `Workspace.curl_file(current)` não existir durante o cálculo do `smart`: deixar
  `FileNotFoundError` propagar — comportamento esperado (erro, não pular
  silenciosamente).

**Critérios de aceite:**
- [ ] `_schedule_all()` com steps 0,1,2 existentes retorna `([0,1,2], {0,1,2})`.
- [ ] `_schedule_slice(None, None)` com steps 0..4 retorna `([0,1,2,3,4], {0,1,2,3,4})`.
- [ ] `_schedule_slice(2, None)` com steps 0..4 retorna `([2,3,4], {2,3,4})`.
- [ ] `_schedule_slice(None, 2)` com steps 0..4 retorna `([0,1,2], {0,1,2})`.
- [ ] `_schedule_smart(2, 5)` com step 5 dependendo de step 3 (via comentário no curl de
      step 5) e nenhuma outra dependência: retorna `([3, 5], {3, 5})` — steps 2 e 4 NÃO
      aparecem.
- [ ] `_schedule_smart` com cadeia de dependência de dois níveis (5 depende de 3, que
      depende de 1, floor=0): inclui 1, 3 e 5.
- [ ] `_schedule_smart` com floor maior que uma dependência necessária (floor=4, step 5
      depende de step 3): step 3 NÃO entra no schedule.
- [ ] `_schedule_list` de um arquivo com `"2\n5\n2\n"` retorna `([2, 5, 2], {2, 5})` —
      ordem do arquivo preservada na lista, duplicata não repetida no set.
- [ ] `_schedule_list` com linhas em branco entre números ignora as linhas em branco.

---

## T12 — `ReplayRunner`: execução por step + orquestração dos 4 modos + comparação final
**Depende de:** T11 (schedule), T04 (`ReplayResultComparator`), T05
(`StepRetryPolicy`), T08 (`ReplayTokenResolver`)
**Arquivos envolvidos:** `har_reproducer/replay/replay_runner.py` (extensão da classe
criada em T11)

**Contexto:**
Com o schedule calculado (T11), falta processar cada step (resolver tokens, montar
curl final, executar via HTTP, persistir resposta, imprimir progresso) e, ao final,
comparar o último resultado com o original. Essa sequência é idêntica pros 4 modos — só
muda o `schedule`/`ordered_indexes` de entrada.

**Estado atual:**
Ver T11 — só o cálculo de schedule existe até aqui.

**Estado esperado depois:**
- `ReplayRunner.__init__` ganha as dependências que faltam:
  ```python
  def __init__(
      self,
      dependency_parser: CurlDependencyParser,
      session_store: SessionStore,
      http_transport: CurlHttpTransport,
      replay_token_resolver: ReplayTokenResolver,
      retry_policy: StepRetryPolicy,
      comparator: ReplayResultComparator,
      run_id: str,
      replay_run_dir: Path,
      res_refer_dir: Path,
  ) -> None:
      self.dependency_parser = dependency_parser
      self.session_store = session_store
      self.http_transport = http_transport
      self.replay_token_resolver = replay_token_resolver
      self.retry_policy = retry_policy
      self.comparator = comparator
      self.run_id = run_id
      self.replay_run_dir = replay_run_dir
      self.res_refer_dir = res_refer_dir
  ```
- Quatro métodos públicos, um por modo, mesma estrutura:
  ```python
  def run_all(self) -> bool:
      ordered_indexes, schedule = self._schedule_all()
      return self._run_schedule(ordered_indexes, schedule)

  def run_slice(self, from_index: Optional[int], to_index: Optional[int]) -> bool:
      ordered_indexes, schedule = self._schedule_slice(from_index, to_index)
      return self._run_schedule(ordered_indexes, schedule)

  def run_smart(self, from_index: Optional[int], to_index: Optional[int]) -> bool:
      ordered_indexes, schedule = self._schedule_smart(from_index, to_index)
      return self._run_schedule(ordered_indexes, schedule)

  def run_list(self, steps_file: Path) -> bool:
      ordered_indexes, schedule = self._schedule_list(steps_file)
      return self._run_schedule(ordered_indexes, schedule)
  ```
- Método privado comum:
  ```python
  def _run_schedule(self, ordered_indexes: List[int], schedule: Set[int]) -> bool:
      last_index: Optional[int] = None
      last_response: Optional[StepResponse] = None
      for index in ordered_indexes:
          last_response = self._run_step(index, schedule)
          last_index = index

      is_match: bool = self.comparator.matches_original(last_index, last_response)
      print(
          f"\nReplay Validation Result: {'✓ SUCCESS' if is_match else '✗ MISMATCH'} "
          f"(step {last_index} status code vs. original)"
      )
      return is_match

  def _run_step(self, index: int, schedule: Set[int]) -> StepResponse:
      curl_text: str = Workspace.curl_file(index).read_text(encoding="utf-8")

      def attempt() -> StepResponse:
          self.replay_token_resolver.resolve(curl_text, schedule, self.replay_run_dir, self.res_refer_dir)
          curl_resolved: str = self.session_store.render(curl_text)
          return self.http_transport.send_request(curl_resolved, index)

      def recover(response: StepResponse) -> bool:
          if response.status_code not in StepRetryPolicy.RECOVERABLE_STATUS_CODES:
              return False
          print(f"Detected {response.status_code}. Attempting deterministic recovery (token refresh)...")
          return True

      response: StepResponse = self.retry_policy.execute(index, attempt, recover)
      Workspace.replay_response_file(self.run_id, index).write_text(
          response.model_dump_json(indent=2), encoding="utf-8"
      )
      print(f"Step {index} completed with status {response.status_code}")
      return response
  ```
- ⚠️ `recover()` só faz a checagem de status e imprime o aviso — a "ação de
  recuperação" em si é implícita: a próxima chamada de `attempt()` já re-resolve os
  tokens do zero (chama `replay_token_resolver.resolve` de novo). Não precisa chamar
  `resolve` explicitamente dentro de `recover()`.
- ⚠️ Se `ordered_indexes` estiver vazio, `last_index`/`last_response` ficam `None` — não
  deveria acontecer (validação de arquivo vazio pro modo `list` acontece na CLI, T14),
  mas decidir na implementação se um erro explícito é melhor que deixar `None` seguir
  pro `comparator` (que espera `int`/`StepResponse` não-opcionais).
- Se algum `Workspace.curl_file(index)` do schedule não existir: `read_text()` lança
  `FileNotFoundError`, que deve propagar.

**Critérios de aceite:**
- [ ] `run_all()` processa todos os steps existentes em ordem ascendente, persiste um
      `res_XXXX.json` em `replays/<run_id>/` pra cada um, retorna o resultado de
      `matches_original` do último.
- [ ] `run_slice(2, 4)` processa exatamente os steps 2, 3 e 4, nessa ordem.
- [ ] `run_smart(2, 5)`, com step 5 dependendo de step 3: processa só 3 e 5 (nessa
      ordem); nenhum arquivo é persistido pra 2 ou 4; nenhum print acontece pra 2 ou 4.
- [ ] `run_list(caminho)` processa os steps na ordem exata do arquivo, mesmo fora de
      ordem crescente.
- [ ] Step cujo token depende de outro step DENTRO do schedule: `resolve` é chamado com
      `self.replay_run_dir` pra esse token (verificável via spy/mock).
- [ ] Step cujo token depende de um step FORA do schedule: `resolve` é chamado com
      `self.res_refer_dir`.
- [ ] Resposta com status 401 na primeira tentativa e 200 na segunda: só a resposta
      final (200) é persistida em `replay_response_file(run_id, index)`.
- [ ] Nenhum `req_XXXX.json` é persistido em nenhum momento pelo `ReplayRunner`.
- [ ] O print final de validação aparece uma única vez por chamada de
      `run_all`/`run_slice`/`run_smart`/`run_list`, referenciando o índice do último
      step processado (não necessariamente o maior índice, no caso do modo `list`).

---

## T13 — CLI: subparser `replay`
**Depende de:** T10 (mesmo arquivo `cli_parser.py` — evita edições fora de ordem).
**Arquivos envolvidos:** `har_reproducer/cli/cli_parser.py`

**Contexto:**
Falta o subcomando `replay` na CLI — só a definição dos argumentos via `argparse`, sem
validação de regras entre flags (isso fica em `CliHandlers.handle_replay`, T14).

**Estado atual:**
`CliParser.build()` só registra `parse` e `run` (via `_build_parse_subparser`/
`_build_run_subparser`).

**Estado esperado depois:**
```python
def _build_replay_subparser(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
    replay_parser: ArgumentParser = subparsers.add_parser("replay")
    replay_parser.add_argument("--output", required=True, help="Path to an existing workspace directory")
    replay_parser.add_argument("--mode", choices=["all", "slice", "smart", "list"], required=True, help="Replay execution mode")
    replay_parser.add_argument("--from", dest="from_index", type=int, default=None, help="Starting step index (slice/smart only)")
    replay_parser.add_argument("--to", dest="to_index", type=int, default=None, help="Ending step index (slice/smart only)")
    replay_parser.add_argument("--steps-file", dest="steps_file", default=None, help="Path to a txt file with one step index per line (list mode only)")
    replay_parser.add_argument("--config", help="Path to project config (JSON)")
    replay_parser.set_defaults(func=self._handlers.handle_replay)
```
- Chamar `self._build_replay_subparser(subparsers)` dentro de `build()`, junto das
  outras duas chamadas.
- Nenhuma validação de regra entre flags nesta task — `argparse` só define os
  argumentos, aceita qualquer combinação sintaticamente válida.
- `self._handlers.handle_replay` ainda não existe até T14 — a referência só resolve de
  fato depois, mas isso não impede o parser de ser definido/testado isoladamente
  (`argparse` só guarda a referência à função, não a chama nesta task).

**Critérios de aceite:**
- [ ] `replay --output x --mode all` é aceito pelo parser sem erro de `argparse`.
- [ ] `replay --mode all` (sem `--output`) falha com erro de `argparse`.
- [ ] `replay --output x` (sem `--mode`) falha com erro de `argparse`.
- [ ] `"smart"` e `"list"` estão entre os `choices` de `--mode` (checar que não foram
      esquecidos).
- [ ] `args.from_index`/`args.to_index` são `None` quando não passados, `int` quando
      passados.
- [ ] `args.steps_file` é `None` quando `--steps-file` não é passado.
- [ ] `run` e `parse` continuam funcionando exatamente como antes.

---

## T14 — `CliHandlers`: `handle_replay`
**Depende de:** T02 (`ProjectConfig.response_reference_dir`), T12 (`ReplayRunner`
completo), T13 (subparser `replay` definido)
**Arquivos envolvidos:** `har_reproducer/cli/cli_handlers.py`

**Contexto:**
Última peça de integração — o handler que valida os argumentos do comando `replay`,
monta todas as dependências e executa o modo pedido dentro do proxy.

**Estado atual:**
`CliHandlers` não tem `handle_replay`. `_run_with_proxy` (usado por `handle_run`) é a
referência mais próxima de como orquestrar proxy + execução, mas constrói um `Engine`,
não um `ReplayRunner` — não serve pra reaproveitar diretamente.

**Estado esperado depois:**
```python
def handle_replay(self, args: Namespace) -> None:
    output_dir: Path = Path(args.output)
    self._validate_replay_mode_flags(args)

    if not output_dir.exists():
        raise ValueError(f"Workspace directory does not exist: {output_dir}")

    Workspace.init(output_dir)
    if not any(Workspace.curls.glob("req_*.curl.sh")):
        raise ValueError(f"Workspace has no curl files: {output_dir}")

    project_config: ProjectConfig = ProjectConfigLoader.load(Path(args.config) if args.config else None)
    res_refer_dir: Path = project_config.response_reference_dir or Workspace.real_responses
    if not res_refer_dir.exists():
        raise ValueError(f"response_reference_dir does not exist: {res_refer_dir}")

    run_id: str = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_store: SessionStore = SessionStore()
    extractor_runner: ExtractorRunner = ExtractorRunner()
    dependency_parser: CurlDependencyParser = CurlDependencyParser()
    replay_token_resolver: ReplayTokenResolver = ReplayTokenResolver(session_store, extractor_runner, dependency_parser)
    retry_policy: StepRetryPolicy = StepRetryPolicy()
    comparator: ReplayResultComparator = ReplayResultComparator()

    orchestrator: MitmProxyOrchestrator = MitmProxyOrchestrator(project_config.proxy_port, project_config.ca_cert_path)
    http_transport: CurlHttpTransport = CurlHttpTransport(orchestrator.port, project_config.ca_cert_path)

    runner: ReplayRunner = ReplayRunner(
        dependency_parser=dependency_parser,
        session_store=session_store,
        http_transport=http_transport,
        replay_token_resolver=replay_token_resolver,
        retry_policy=retry_policy,
        comparator=comparator,
        run_id=run_id,
        replay_run_dir=Workspace.replay_run_dir(run_id),
        res_refer_dir=res_refer_dir,
    )

    result: bool = orchestrator.run(lambda: self._dispatch_replay_mode(runner, args))
    self._print_result(result)

def _dispatch_replay_mode(self, runner: ReplayRunner, args: Namespace) -> bool:
    if args.mode == "all":
        return runner.run_all()
    if args.mode == "slice":
        return runner.run_slice(args.from_index, args.to_index)
    if args.mode == "smart":
        return runner.run_smart(args.from_index, args.to_index)
    return runner.run_list(Path(args.steps_file))

def _validate_replay_mode_flags(self, args: Namespace) -> None:
    if args.mode == "all" and (args.from_index is not None or args.to_index is not None or args.steps_file is not None):
        raise ValueError("--from/--to/--steps-file não se aplicam a --mode all")
    if args.mode in ("slice", "smart"):
        if args.steps_file is not None:
            raise ValueError(f"--steps-file não se aplica a --mode {args.mode}")
        if args.from_index is not None and args.to_index is not None and args.from_index > args.to_index:
            raise ValueError("--from não pode ser maior que --to")
    if args.mode == "list":
        if args.steps_file is None:
            raise ValueError("--mode list exige --steps-file")
        if args.from_index is not None or args.to_index is not None:
            raise ValueError("--from/--to não se aplicam a --mode list")
```
- ⚠️ **Ordem de inicialização crítica:** `Workspace.init(output_dir)` PRECISA vir antes
  de `ProjectConfigLoader.load`, porque `res_refer_dir` depende de
  `Workspace.real_responses` já estar setado — diferente da ordem usada em
  `_run_with_proxy` (config antes do `Workspace.init`, que só acontece dentro do
  `Engine.__init__`). NÃO copiar essa ordem aqui.
- `_reset_output_dir` NUNCA é chamado neste handler.
- `_validate_replay_mode_flags` roda antes de qualquer acesso a filesystem/`Workspace`
  — falha rápido em erro de combinação de flags, sem custo de I/O.
- Reaproveitar `_print_result` (já existe, genérico, recebe `bool`) — não duplicar.
- `CliParser.build()` (T13) já aponta `func=self._handlers.handle_replay` — depois
  desta task, essa referência passa a resolver de verdade.

**Critérios de aceite:**
- [ ] `replay --output <workspace_válido> --mode all` roda sem erro e imprime o
      resultado final via `_print_result`.
- [ ] `replay --output <dir_sem_curls> --mode all` falha com erro claro, sem subir o
      `mitmdump`.
- [ ] `replay --output <dir_inexistente> --mode all` falha com erro claro, sem chamar
      `Workspace.init`.
- [ ] `replay --output <workspace_válido> --mode all --from 2` falha com erro claro.
- [ ] `replay --output <workspace_válido> --mode list` (sem `--steps-file`) falha com
      erro claro.
- [ ] `replay --output <workspace_válido> --mode slice --from 5 --to 2` falha com erro
      claro.
- [ ] Config com `response_reference_dir` apontando pra diretório existente: esse
      diretório chega como `res_refer_dir` no `ReplayRunner` construído.
- [ ] Config com `response_reference_dir` apontando pra diretório inexistente: falha
      com erro claro, antes de subir o proxy.
- [ ] Config sem `response_reference_dir`: `res_refer_dir` cai pra
      `Workspace.real_responses`.
- [ ] `_reset_output_dir` nunca é chamado em nenhum caminho de `handle_replay`
      (verificável via spy/mock).
- [ ] `handle_run`/`handle_parse` continuam funcionando exatamente como antes.
