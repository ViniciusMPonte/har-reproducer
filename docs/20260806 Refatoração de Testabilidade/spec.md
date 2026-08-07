# Spec — Refatoração de Testabilidade

## 1. Objetivo

### O problema

O projeto acabou de ganhar uma rede de caracterização golden — 39 testes em
`tests/` que comparam a árvore do workspace e o `stdout` dos três comandos
contra referências gravadas (`docs/20260806 Rede de Caracterização Golden/`,
mergeada em `e701ed6`). Essa rede prova que o comportamento não mudou, mas
**não testa nenhuma unidade**: ela invoca `main()` e olha o resultado no disco.

A lógica que mais produziu bug no histórico — arbitragem de slot de token,
schedule de replay, loop TDD dos agents — continua sem cobertura fina, e vai
continuar enquanto o grafo de objetos não for construível sem estado global,
disco, subprocesso e rede. Hoje não é:

- `Workspace` é singleton materializado por `setattr` de atributo de classe
  (`fs_io/workspace.py:19-26`). Dez arquivos dependem dele. Não há `reset`, e o
  estado vaza de um teste para o seguinte.
- O ramo `run` constrói os colaboradores dentro do `__init__`
  (`engines/engine.py:26-57`, `tracking/token_tracker.py:16-28`,
  `tracking/candidate_resolver.py:33-45`, `tracking/token_resolver.py:10-13`) —
  sem parâmetro que permita substituí-los. O ramo `replay` faz o oposto:
  `ReplayRunner.__init__` (`replay/replay_runner.py:19-41`) é atribuição pura,
  montada em `CliHandlers._build_replay_runner` (`cli/cli_handlers.py:119-147`).
- `CurlHttpTransport` sempre chama `curl` de verdade por subprocess; os
  `time.sleep` de `agents/base_agent.py:161` e
  `reproduction/curl_http_transport.py:67` custam tempo de parede real; e
  `subprocess.run([sys.executable, ...])` aparece cru em dois lugares.

### O arco: três etapas

| Etapa | Entrega | Toca `har_reproducer/`? |
|---|---|---|
| **A** | Rede de caracterização golden sobre os 3 comandos — **feita**, `e701ed6` | Não |
| **B — esta** | Refatoração de testabilidade, corte "nível 2": só as costuras que desbloqueiam teste | **Sim** |
| **C** | Unitários finos, usando as costuras de B | Não |

### Escopo desta etapa

As cinco costuras descritas no esboço §3.8 da spec da Etapa A, e nada além:

1. `Workspace` deixa de ser singleton e vira instância injetada, com atributos
   explícitos.
2. Seam de transporte HTTP.
3. Seam de espera, para os dois `time.sleep` em escopo.
4. `ScriptExecutor` encapsulando o `subprocess.run([sys.executable, ...])`
   duplicado.
5. Injeção de colaboradores no ramo `run`, mais um `AgentFactory`.

### Fora de escopo

- Os cinco itens que a §3.8 da Etapa A pôs fora do corte nível 2: `DryEngine`
  como estratégia injetada; **factories como raízes de composição**;
  `ProjectPaths`; um `Reporter` no lugar dos 31 `print`; quebra dos arquivos
  multi-classe. ⚠️ O segundo é contrariado de propósito por esta spec — ver §3.7
  e §6.7.
- Corrigir qualquer um dos nove defeitos catalogados na §6 da spec da Etapa A.
  Eles continuam congelados pelo golden.
- Escrever os unitários (Etapa C).
- `pytest.ini`, o grupo de dependências dev, e mover `pytest`/`pytest-httpx`
  de `dependencies` (defeito §6.7 da Etapa A).
- **O acesso a disco do `CandidateResolver` continua sem costura — em dois
  pontos independentes.** Nenhuma das cinco costuras alcança:
  1. `_find_origin` (`tracking/candidate_resolver.py:70-77`) → `ResponseGrep.find`
     → o `subprocess.run` de `tracking/response_grep.py:65`, sobre o comando
     `["grep", "-lF", ...]` montado em `:64`;
  2. `_load_response` (`tracking/candidate_resolver.py:166-175`) →
     `json.loads((self.responses_dir / f"res_{i:04d}.json").read_text())` —
     leitura direta, **sem passar por `ResponseGrep`**.

  Consequência prática para a Etapa C, que vale registrar antes que alguém
  descubra ao escrever o teste: `CandidateResolver._find_slot`/`_check_slot` — o
  segundo alvo prioritário da §3.9 da Etapa A — **ficam testáveis**; percorrida a
  cadeia inteira (`_find_slot` → `_check_slot` → `_check_cached_slot` /
  `_check_persisted_slot` → `metadata_store.load` e
  `extractor_runner.run_existing`), ela só toca colaboradores injetados e
  `self.responses_dir` trafega como `Path` opaco. Já `_find_origin`,
  `_load_response` e portanto `_process_candidate` **não** ficam: exigem
  diretório real, `grep` de verdade e arquivos de resposta em disco. Injetar só
  um `ResponseGrep` falso não resolve — o segundo ponto continua lá. Uma costura
  para os dois é assunto de outra spec.

⚠️ **`StepRequest.is_skippable` (`models/http.py:13`) não pode ser removido.** É
código morto como leitura, mas está **serializado** em `real_requests/*.json` —
`false` no step 0, `true` no step pulado. Faz parte do contrato golden.

### Prior art: a spec nível 3 arquivada

Existe uma spec anterior **não usada** para o mesmo problema, num branch não
mergeado:
`docs/20260805 Injeção de Workspace e Dependências/spec.md`, commit `ee0cd08`
em `20260805-9-injecao-de-workspace-e-dependencias`, com a mensagem
"doc: adição de spec (não usado)". Ela é o **corte nível 3**: inclui
`ProjectPaths`, `DryEngine` como estratégia injetada, `ReplayRunnerFactory`, e
`CliHandlers` reduzido a casca fina.

Esta spec reaproveita dela o desenho do `ScriptExecutor` (§3.5), o mapa de
consumidores do `Workspace` (§2.2) e vários casos de borda já verificados por
grep. O resto continua fora de escopo, e quem quiser retomá-lo depois tem o
documento pronto no histórico.

### Restrição transversal

**Nenhuma mudança de comportamento observável** — nem no resultado, nem nos
arquivos escritos, nem na ordem de operações, nem nas mensagens impressas, nem
nos casos de borda. Toda task é `refactor:`. Onde o comportamento atual parece
errado, esta etapa **preserva** e registra; corrigir é assunto de outra spec.

**O portão de aceite é `uv run pytest --runslow`** — os 39 testes, verdes, sem
regravar nada. `HAR_REPRODUCER_UPDATE_GOLDEN=1` **nunca** é setado nesta etapa:
se uma task faz o golden divergir, a task está errada, não o golden (regra
explícita da §3.4 da Etapa A).

⚠️ **O portão nunca é o `pytest` default.** Medido: nenhum dos 28 testes
offline chega em `CliHandlers._build_replay_runner` — os três cenários de erro
de `replay` com workspace real levantam `ValueError` em `cli_handlers.py:106`,
`:110` e `:116`, todos **antes** da linha 98 que monta o runner. Uma quebra de
assinatura no ramo `replay` deixa a rodada default **inteiramente verde**. E o
projeto não tem mypy, ruff nem pyright (verificado: nada em `pyproject.toml`
nem em `pytest.ini`), então quebra de assinatura só aparece em runtime.

---

## 2. Componentes existentes (estado atual, não redesenhar)

### 2.1 `Workspace` — `fs_io/workspace.py`

```python
class Workspace:
    _output_dir: Optional[Path] = None

    curls: Path
    real_responses: Path
    ...

    @classmethod
    def init(cls, output_dir: Path) -> None:
        cls._output_dir = Path(output_dir)
        cls._output_dir.mkdir(parents=True, exist_ok=True)
        for workspace_dir in WorkspaceDir:
            path: Path = cls._output_dir / workspace_dir.value
            path.mkdir(parents=True, exist_ok=True)
            setattr(cls, workspace_dir.value, path)
```

Os oito nomes de atributo (`:10-17`) são **só anotações** — passam a existir
quando `init()` roda o `setattr`. Os onze métodos de caminho são `@classmethod`
precedidos de `cls._ensure_initialized()` (`:28-33`): `temp_extractor_file`,
`extractor_file`, `extractor_meta_file`, `request_file`, `response_file`,
`original_response_file`, `mitm_capture_file`, `mitm_log_file`, `curl_file`,
`replay_run_dir`, `replay_response_file`.

⚠️ Há **dois** modos de falha, não um: os acessos a *atributo* — `Workspace.curls`
em `cli_handlers.py:109` e `replay_runner.py:174`, `Workspace.real_responses` em
`cli_handlers.py:114`, `Workspace.original_responses` em `cli_handlers.py:146`, e
os seis de `engine.py:38-42` (a linha `:40` lê **dois**) — não passam por
`_ensure_initialized()` e produzem `AttributeError` cru, não o `RuntimeError`
com mensagem.

Dois `@staticmethod` **não dependem de `output_dir`** (`:35-43`):
`get_root_path()` devolve o diretório do pacote `har_reproducer/`;
`get_mitmproxy_ca_path()` devolve `<repo>/.mitmproxy`, criando-o. Único
consumidor externo: `config/project_config_loader.py:37`.

### 2.2 Os dez consumidores

| Classe | Arquivo | O que usa |
|---|---|---|
| `CliHandlers` | `cli/cli_handlers.py:108,109,114,144,146` | `init`, `curls`, `real_responses`, `replay_run_dir`, `original_responses` |
| `Engine` | `engines/engine.py:37-42,129,133,136,139` | `init`, 5 atributos de diretório, `request_file`, `original_response_file`, `response_file`, `curl_file` |
| `ReplayRunner` | `replay/replay_runner.py:77,95,102,149,174` | `curl_file`, `replay_response_file`, `curls` |
| `ReplayResultComparator` | `replay/replay_result_comparator.py:25` | `response_file`, `original_response_file` |
| `ExtractorRunner` | `reproduction/extractor_runner.py:26,35` | `extractor_file` |
| `ExtractorMetadataStore` | `reproduction/extractor_metadata_store.py:10,20` | `extractor_meta_file` |
| `CurlHttpTransport` | `reproduction/curl_http_transport.py:73` | `mitm_capture_file` |
| `MitmProxyOrchestrator` | `reproduction/mitm_proxy_orchestrator.py:59,77,113` | `mitm_log_file`, `mitm_capture_file` |
| `BaseAgent` | `agents/base_agent.py:149,163,172` | `temp_extractor_file` |
| `ProjectConfigLoader` | `config/project_config_loader.py:37` | **só o `@staticmethod`** `get_mitmproxy_ca_path` |

`templates/extractor_template.py` importa apenas o enum `WorkspaceDir`
(`WorkspaceDir.REAL_RESPONSES.value` na linha 56) — **não muda**.

⚠️ **Dependência temporal implícita hoje:** em `_run_with_proxy`
(`cli_handlers.py:56-70`) o `MitmProxyOrchestrator` é construído **antes** do
`Engine`, e é `Engine.__init__` que chama `Workspace.init` (`engine.py:37`).
Só não quebra porque o orquestrador só toca `Workspace` dentro de `run()`.

⚠️ O script gerado por `ExtractorTemplate.render_script`
(`templates/extractor_template.py:56`) resolve a resposta por
`Path(__file__).resolve().parent.parent / "real_responses"` — ele **assume que
mora em `<output>/extractors/`**. O layout de diretórios é contrato do arquivo
gerado, não só do `Workspace`.

### 2.3 Ramo `run` — construção de dependências

`engines/engine.py:26-57` faz, num `__init__` só: inicializar estado global,
ler config do disco, construir um cliente de LLM (que valida variável de
ambiente e pode lançar), e montar oito colaboradores.

```python
        Workspace.init(output_dir)
        self.curls_dir: Path = Workspace.curls
        self.original_responses_dir: Path = Workspace.original_responses
        self.tracking_responses_dir: Path = Workspace.real_responses if self.USES_NETWORK else Workspace.original_responses
        self.extractors_dir: Path = Workspace.extractors
        self.temp_extractors_dir: Path = Workspace.temp_extractors
        ...
        project_config: ProjectConfig = ProjectConfigLoader.load(config_path)
        ...
        self.token_resolver: TokenResolver = TokenResolver(self.tracking_responses_dir, self.session_store)
        llm: Optional[BaseChatModel] = self._build_llm(project_config)
        self.tracker: TokenTracker = TokenTracker(self.tracking_responses_dir, self.session_store, llm=llm)
```

⚠️ **Atributos mortos, reconfirmados por grep no código atual desta etapa:**
`curls_dir`, `extractors_dir` e `temp_extractors_dir` têm **zero** leituras;
`original_responses_dir` só casa com o atributo homônimo de `ReplayRunner`
(`replay_runner.py:81`, outra classe); `output_dir` (`:35`) só casa com
`SuccessCriterionScenario.output_dir`, atributo de teste. Apenas
`tracking_responses_dir` é lido — nas linhas `:53` e `:57`.

`TokenResolver` (`tracking/token_resolver.py:13`) constrói um `ExtractorRunner()`;
`CandidateResolver` (`tracking/candidate_resolver.py:42-43`) constrói **outro**,
mais um `ExtractorMetadataStore()`. `TokenTracker`
(`tracking/token_tracker.py:26-28`) constrói `BaselineDiff`,
`CandidateResolver` e `PlaceholderApplier`.

⚠️ `token_tracker.py:35` instancia um colaborador **dentro do método**, a cada
chamada: `template: str = CurlGenerator().generate(step.request, tokens)`.
`CurlGenerator` é sem estado (`reproduction/curl_generator.py` — todos os
métodos operam só sobre os parâmetros), então hoistar para o `__init__` é
seguro.

⚠️ O `ProjectConfig` é carregado **duas vezes** no modo `main`
(`cli_handlers.py:57` e `engine.py:48`) e **uma** no modo `dry`.

### 2.4 Seleção de agent — `tracking/candidate_resolver.py`

`LOCATION_AGENTS` (`:25-31`) mapeia cinco `TokenLocation` para cinco agents, e
`_generate_extractor` (`:186-195`) instancia:

```python
        agent_cls: Type[BaseAgent] = self.LOCATION_AGENTS.get(candidate.origin_location, RegexAgent)

        agent: BaseAgent = agent_cls(
            token_id=candidate.token_id,
            response_sample=response_sample,
            expected_value=candidate.current_value,
            path=candidate.path,
            location=candidate.origin_location.value if candidate.origin_location else None,
            llm=self.llm,
        )
```

⚠️ `TokenLocation.URL_PARAM` (`models/session.py:23`) **não está no mapa** —
cai no default `RegexAgent`. Comportamento a preservar.

Nenhuma subclasse de agent define `__init__` (verificado): as cinco herdam o de
`BaseAgent` (`agents/base_agent.py:23-40`).

### 2.5 Transporte HTTP

`engines/engine.py:59-65`:

```python
    def _build_http_transport(
            self, proxy_port: Optional[int], ca_cert_path: Optional[Path]
    ) -> Optional[CurlHttpTransport]:
        if not self.USES_NETWORK:
            return None
        assert proxy_port is not None
        return CurlHttpTransport(proxy_port, ca_cert_path)
```

⚠️ O `return None` é **incondicional nos argumentos** quando `USES_NETWORK` é
falso: `DryEngine` nunca recebe transporte, mesmo se um `proxy_port` for
passado. É essa invariante — não a convenção do chamador — que precisa
sobreviver.

O ramo `replay` já recebe o transporte pronto: `CurlHttpTransport` é construído
em `_build_replay_runner` (`cli_handlers.py:134`) e injetado no `ReplayRunner`.

### 2.6 Os dois `subprocess.run`

`agents/base_agent.py:181-200` e `reproduction/extractor_runner.py:52-71`.
Divergem em **quatro** eixos, não um:

| | `BaseAgent._execute_script` | `ExtractorRunner._execute_extractor_script` |
|---|---|---|
| exceção capturada | só `subprocess.TimeoutExpired` (`:189`) | `Exception` (`:66`) |
| retorno | `Tuple[bool, Optional[str]]` | `Optional[str]` |
| `env` | não passa (herda do pai) | passa `env=` (`:64`), montado em `_build_env` |
| timeout | literal `5` (`:187`) | `EXTRACTOR_TIMEOUT_SECONDS: ClassVar[int]` (`:14`) |

⚠️ **O trecho genuinamente comum são ~6 linhas.** O ganho desta costura é o
seam, não o reuso — e a divergência de tratamento de exceção precisa ser
**preservada**, não unificada: em `BaseAgent` um `OSError` propaga; em
`ExtractorRunner` vira `None`.

### 2.7 Os `time.sleep`

| Local | Linha | Em escopo? |
|---|---|---|
| `BaseAgent.run_tdd_loop` | `agents/base_agent.py:161` — `RETRY_DELAY_SECONDS = 5` | **Sim** |
| `CurlHttpTransport._read_captured_response` | `reproduction/curl_http_transport.py:67` — 5 × 0,1 s | **Sim** |
| `MitmProxyOrchestrator._wait_until_ready` | `reproduction/mitm_proxy_orchestrator.py:101` — 0,2 s | **Não** — supervisão de processo externo, fora das cinco costuras |

⚠️ A costura **não acelera a suíte**: os testes golden invocam `main()`, que
monta o `Sleeper` de produção — ele continua dormindo, e a suíte continua
custando ~32 s. Ela só permite que os unitários da Etapa C não paguem a espera.

⚠️ **Isto corrige uma expectativa da spec da Etapa A.** A §3.7 dela afirma "A
Etapa B derruba isso com o seam de espera — não otimizando a suíte, mas
removendo a espera real", sugerindo que os ~20 s de `time.sleep` sumiriam ao
fim desta etapa. Não somem: nenhum teste golden tem como injetar um dublê, já
que entra pelo `main()`. Quem voltar à Etapa A esperando ~12 s depois desta
etapa vai achar que algo quebrou.

### 2.8 O formato-alvo, que já existe

`ReplayRunner.__init__` (`replay/replay_runner.py:19-41`): dez parâmetros, dez
atributos tipados, nenhuma construção. Montado em
`CliHandlers._build_replay_runner` (`cli/cli_handlers.py:119-147`), que recebe
`(orchestrator, run_id, res_refer_dir)` — tudo ambiente — e monta o grafo.

⚠️ `MitmProxyOrchestrator.__init__` (`mitm_proxy_orchestrator.py:26`) recebe o
`ca_cert_path` do `ProjectConfig` num parâmetro chamado **`project_root`**, e o
valor é o *confdir* `<repo>/.mitmproxy` (posto por `_apply_defaults`,
`project_config_loader.py:37`); o `.pem` é derivado dele em `:29`. O nome mente
(defeito §6.6 da Etapa A) e **não é corrigido aqui** — a raiz de composição
apenas repassa o valor como hoje.

### 2.9 A rede golden como oráculo

39 testes, 28 offline + 11 marcados `slow`. `CliInvoker` (`tests/support/`)
substitui `sys.argv`, chama `har_reproducer.main.main()`, captura `stdout`,
`stderr` e a exceção. `GoldenWorkspace` compara a árvore inteira por caminho e
conteúdo — **incluindo diretórios vazios**, gravados como `<EMPTY_DIR>`.

⚠️ `<EMPTY_DIR>` marca **todo** diretório, vazio ou não
(`golden_workspace.py:76-78`: `if path.is_dir()`), e é o `.gitkeep` que sinaliza
o diretório-folha na referência gravada. O conteúdo de `mitm_capture/` é
excluído à parte, por `_is_under_mitm_capture` (`:85-86`) — logo `run_main`
grava `mitm_capture/` como diretório mesmo tendo arquivos dentro.

Consequência que dita duas decisões desta spec:

- Nos goldens de `run`, `replay` e `criteria` os oito diretórios do `Workspace`
  existem e são comparados (com `.gitkeep` nos folha: em `run_dry_default`,
  `mitm_capture/`, `real_responses/` e `replays/`; em `run_main`,
  `mitm_capture/`, `replays/` e `temp_extractors/`). Um `Workspace` que criasse
  os diretórios preguiçosamente **quebraria a suíte** — a materialização *eager*
  é contrato.
- Nos **4 goldens de `parse`** nenhum dos oito existe: `tests/golden/parse_default/`
  contém só `parse/` e `stdout.txt`. É esse fato que congela o caso §5.1 —
  `handle_parse` não pode construir um `Workspace`.

---

## 3. Decisões de arquitetura

### 3.1 `Workspace` vira instância com atributos explícitos

**Estado esperado:**

```python
class Workspace:

    def __init__(self, output_dir: Path) -> None:
        self.output_dir: Path = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.curls: Path = self._prepare_dir(WorkspaceDir.CURLS)
        self.real_responses: Path = self._prepare_dir(WorkspaceDir.REAL_RESPONSES)
        self.original_responses: Path = self._prepare_dir(WorkspaceDir.ORIGINAL_RESPONSES)
        self.real_requests: Path = self._prepare_dir(WorkspaceDir.REAL_REQUESTS)
        self.extractors: Path = self._prepare_dir(WorkspaceDir.EXTRACTORS)
        self.temp_extractors: Path = self._prepare_dir(WorkspaceDir.TEMP_EXTRACTORS)
        self.mitm_capture: Path = self._prepare_dir(WorkspaceDir.MITM_CAPTURE)
        self.replays: Path = self._prepare_dir(WorkspaceDir.REPLAYS)

    def _prepare_dir(self, workspace_dir: WorkspaceDir) -> Path:
        path: Path = self.output_dir / workspace_dir.value
        path.mkdir(parents=True, exist_ok=True)
        return path
```

Os onze métodos de caminho viram métodos de instância. `_output_dir`, `init()`
e `_ensure_initialized()` deixam de existir.

⚠️ A ordem das oito atribuições é a **ordem de declaração do enum**
`WorkspaceDir` (`fs_io/workspace_dir.py:5-12`), que é a ordem em que o `for` de
hoje cria os diretórios. Manter.

⚠️ **Remoção de `init`/`_ensure_initialized` não é uma escolha independente:**
`init()` é o `@classmethod` que muta atributo de classe — ele *é* o singleton. E
o `RuntimeError` "Workspace não inicializado" guarda um estado
(`_output_dir is None`) que uma instância não alcança.

**Os dois `@staticmethod` ficam onde estão.** `get_root_path` e
`get_mitmproxy_ca_path` continuam em `Workspace`, chamados na classe;
`config/project_config_loader.py` **não muda**. Extraí-los para um
`ProjectPaths` (o que a spec nível 3 propunha, §3.2 dela) está fora de escopo.
Custo aceito: uma classe de instância que ainda expõe dois helpers estáticos de
caminho de repositório.

**Alternativa descartada:** manter o singleton e adicionar `Workspace.reset()`
para os testes. Não elimina o compartilhamento de estado — só dá uma ferramenta
para limpá-lo — e toda falha de ordem reaparece quando alguém esquece de chamar.

### 3.2 A migração do `Workspace` é atômica, e vem por último; a ordem das cinco costuras

**Alternativa descartada:** a fachada temporária da spec nível 3 (§3.1.1 dela) —
manter os `@classmethod` delegando para uma instância default guardada em
`_default`, migrar os consumidores em grupos, e remover o andaime na última
task. Rejeitada por dois motivos: os nomes de classmethod e de método de
instância colidem (`temp_extractor_file` não pode ser os dois), então a fachada
exigiria nomes provisórios; e a própria spec nível 3 registra o risco do andaime
sobreviver à etapa.

Em vez disso, **a ordem do plano faz o trabalho da fachada**: a costura 1 é a
última task. Quando ela chega, `CandidateResolver`, `TokenResolver` e
`TokenTracker` já recebem `ExtractorRunner`/`ExtractorMetadataStore` prontos
(costura 5) e **não precisam ser tocados** — verificado: nenhuma das três tem
qualquer referência a `Workspace` hoje. A mudança vira mecânica —
`Workspace.x` → `self.workspace.x` — nas classes-folha e nas duas raízes.

**A ordem completa, e por quê.** A dependência não é só "1 por último":

| Ordem | Costura | Depende de |
|---|---|---|
| 1ª | 5a — `AgentFactory` extraída de `CandidateResolver`, carregando só `llm` | — |
| 2ª | 5b — as três classes de tracking recebem colaboradores; ainda montadas em `Engine.__init__` | 5a |
| 3ª | **2 — seam de transporte**: `Engine` deixa de construir o `CurlHttpTransport` | — (autocontida) |
| 4ª | 5c — `EngineFactory` vira raiz; `Engine.__init__` vira atribuição pura; carga única de config; código morto | 5b **e 2** |
| 5ª | 4 — `ScriptExecutor` | 5a e 5c (a `AgentFactory` é o funil até o `BaseAgent`; a raiz é quem o constrói) |
| 6ª | 3 — `Sleeper` | 5a, 5c **e 2** — antes da costura 2 quem constrói o `CurlHttpTransport` no ramo `run` é `Engine._build_http_transport` (`:59-65`), e o `sleeper` teria de descer pelo `Engine` |
| 7ª | 1 — `Workspace` instância | todas |

⚠️ **A costura 2 precede a 5c, e não o contrário.** `Engine.__init__` não pode
ser "atribuição pura" enquanto `engine.py:52` chamar `_build_http_transport`
(`:59-65`): ou o transporte chega pronto, ou o `__init__` ainda constrói. Logo a
task da raiz de composição *já executaria* a costura de transporte se ela viesse
antes — e a task 2 chegaria vazia, sobrando só criar `contracts/http_transport.py`.
Invertida, a costura 2 é autocontida e deixa os 39 verdes sozinha: `Engine`
recebe `http_transport` pronto, `EngineFactory.create` troca
`(proxy_port, ca_cert_path)` por ele, e `CliHandlers._run_with_proxy` passa
`CurlHttpTransport(orchestrator.port, orchestrator.ca_cert_path)` — exatamente
os dois valores que `engine.py:65` recebe hoje, e exatamente o que
`_build_replay_runner` (`:134`) já faz.

⚠️ **A costura 5c também move `Workspace.init(output_dir)` para
`CliHandlers.handle_run`** (depois do `--reset`, ainda como `@classmethod`), por
dois motivos: `Workspace.init` não cabe num `__init__` de atribuição pura, e a
`EngineFactory` precisa ler `Workspace.real_responses`/`.original_responses`
para calcular `tracking_responses_dir` — atributos que só existem depois do
`setattr` do `init` (`workspace.py:23-26`). A costura 1 depois troca essa linha
única por `workspace = Workspace(output_dir)`. Consequência honesta: **metade do
reposicionamento do `Workspace` acontece em 5c**, não na task final.

A razão de 4 e 3 virem depois de 5: `BaseAgent` passa a exigir
`script_executor`/`sleeper` como parâmetro obrigatório — sem default temporário
— e quem instancia o agent antes da `AgentFactory` é
`CandidateResolver._generate_extractor` (`candidate_resolver.py:188-195`), que
teria de recebê-los só para repassar, e depois perdê-los.

⚠️ **Na costura 5a, quem constrói a `AgentFactory` é o `TokenTracker`**, a
partir do `llm` que ele já recebe e repassa hoje (`token_tracker.py:27`).
`CandidateResolver` já sai dessa task na forma final — recebendo
`agent_factory` por construtor. A alternativa (deixar `CandidateResolver`
construir a `AgentFactory` internamente) fecharia a task num arquivo só, mas
poria o andaime **dentro da classe que a etapa está justamente esvaziando**,
enquanto o `TokenTracker` é o objeto que a 5b desmonta em seguida — lá o
andaime dura uma task, aqui duraria e depois teria de ser desfeito no arquivo
errado. As duas opções são construção dentro de um `__init__`; o critério é
onde o andaime morre mais cedo.

⚠️ **Churn de assinatura previsto, para não parecer retrabalho na revisão:**
`AgentFactory` muda de construtor em quatro das sete tasks (5a `llm`, 4
`+script_executor`, 3 `+sleeper`, 1 `+workspace`), `EngineFactory` em cinco
(2, 5c, 4, 3, 1), e **`CliHandlers._build_replay_runner` em três (4, 3, 1)** —
porque é ele que monta o `ExtractorRunner` e o `CurlHttpTransport` do ramo
`replay`. É a consequência direta de as costuras serem transversais e de o
`Workspace` vir por último. As assinaturas intermediárias, por extenso:

| Task | Assinatura intermediária |
|---|---|
| 5a | `AgentFactory(llm)`; `create(candidate, response_sample) -> BaseAgent` |
| 2 | `EngineFactory.create` **continua `@classmethod`**, trocando `(proxy_port, ca_cert_path)` por `http_transport: Optional[HttpTransport] = None`; a invariante `USES_NETWORK` mora no corpo desse `@classmethod` e só migra para método de instância em 5c |
| 5c | `EngineFactory(project_config)` — **um** parâmetro: `script_executor` e `sleeper` só existem nas tasks seguintes, e `workspace` na última |

⚠️ **Regra de import obrigatória em `agents/construction/agent_factory.py`: as
cinco subclasses são importadas por submódulo direto**
(`from har_reproducer.agents.cookie_agent import CookieAgent`, …), **nunca**
`from har_reproducer.agents import CookieAgent`. A §4 acrescenta `AgentFactory`
a `agents/__init__.py`, e em ordem alfabética `construction` precede
`cookie_agent` — o `__init__` importaria `agent_factory` com o pacote
meio-inicializado. Reproduzido em sandbox:
`ImportError: cannot import name 'CookieAgent' from partially initialized module`.
É a razão pela qual `engines/construction/engine_factory.py:4-6` já importa
`dry_engine` e `engine` por submódulo — o layout que esta etapa copia traz a
regra junto.

⚠️ **Na task 5b, `ExtractorRunner` tem de ser construído antes da linha que hoje
é `engine.py:53`.** `TokenResolver` passa a exigi-lo ali, e a montagem do resto
do grafo de tracking fica naturalmente perto de `:57` — construir na ordem
errada estoura em `engine.py:53`. É também na 5b, e não na 5c, que
`ExtractorRunner`/`ExtractorMetadataStore` viram **instância compartilhada**
entre `TokenResolver` e `CandidateResolver`; a 5c só muda quem monta.

⚠️ **`CandidateResolver` continua importando `BaseAgent`** depois da 5a — ele
anota o tipo da variável do agent. Os cinco imports que saem são os das
subclasses.

⚠️ **As assinaturas mostradas em §3.6 e §3.7 são o estado final.** As tasks
intermediárias carregam versões **sem `workspace`** — não existe instância dele
antes da última task — e a costura 1 reabre `EngineFactory`, `AgentFactory` e
`CliHandlers._build_replay_runner` para acrescentá-lo. Isso é churn conhecido e
aceito: o caminho alternativo (`Workspace` primeiro) obrigaria a enfiar
`workspace` nas três classes de tracking só para elas construírem
`ExtractorRunner`, e a costura 5 desfaria isso em seguida.

⚠️ Como não há checador estático no projeto, a task da costura 1 tem que
**verificar por grep** que nenhuma referência a `Workspace.` sobrou. **Duas**
referências não são exercitadas por nenhum dos 39 testes, e só o grep as pega:

1. `MitmProxyOrchestrator._build_early_exit_message` (`:113`) — só roda quando o
   `mitmdump` morre antes de ficar pronto.
2. `ReplayRunner._annotate_static_tokens` (`:102`, `Workspace.curl_file`) — só
   roda quando `ReplayTokenResolver._record_observation` devolve `True`, o que
   exige `valid_count >= STATIC_CONFIRMATION_THRESHOLD = 5`
   (`replay_token_resolver.py:11,84`). Medido: cada cenário de `replay` parte de
   uma **cópia fresca** do workspace de `main`, então `valid_count` é **1** nos
   sete `.meta.json` de `tests/golden/replay_all/`, e a string
   `probably static` não aparece em nenhum golden. `_mark_token_static`
   (`:110-118`) é morto na suíte junto com ele. ⚠️ Este é o pior dos dois: está
   no ramo `replay`, e é o **único** caminho que reescreve `curls/` durante um
   replay.

E `ProjectConfigLoader._apply_defaults` (`:37`) é a única referência que
**sobrevive** à migração, por ser o `@staticmethod`. Os demais caminhos de erro
citados como suspeitos numa versão anterior desta seção — o timeout de
`_wait_until_ready` (`:103-105`) e o parse-error de `ProjectConfigLoader`
(`:28-32`) — **não tocam `Workspace`** e não precisam de conferência.

### 3.3 Seam de transporte HTTP

**Novo:** `contracts/http_transport.py`

```python
class HttpTransport(Protocol):
    def send_request(self, curl_literal: str, step_index: int) -> StepResponse: ...
```

`Engine` deixa de receber `(proxy_port, ca_cert_path)` e passa a receber
`http_transport: Optional[HttpTransport]`; `_build_http_transport` (`:59-65`) e
o `assert proxy_port is not None` saem de `Engine`. `ReplayRunner.http_transport`
passa a ser tipado como `HttpTransport`.

⚠️ A invariante da §2.5 migra para dentro de `EngineFactory.create`, **não** para
a convenção do chamador: `create` zera o transporte quando
`engine_cls.USES_NETWORK` é falso, e assere `http_transport is not None` quando
é verdadeiro. Sem isso, nada impediria uma `DryEngine` de receber um transporte.

`Protocol` — e não classe base abstrata — porque é o padrão que o projeto já usa
para costura de implementação trocável (`LLMProviderProtocol`,
`contracts/types.py:11-12`), e porque não há comportamento comum a herdar.

⚠️ **Arquivo próprio, e não dentro de `types.py` junto do precedente citado.**
`contracts/types.py` agrupa `LLMProviderProtocol` com três `TypeAlias`, o que
contraria "um conceito coeso = uma classe = um arquivo". É desvio pré-existente:
esta etapa nem o corrige nem o imita. Herdamos o *padrão* (`Protocol`), não o
*layout*.

⚠️ **Honestidade sobre o que o `Protocol` entrega hoje: nada executável.** Sem
mypy, ruff ou pyright no projeto (§6.6), ele não é verificado em import nem em
runtime — uma ABC pelo menos falharia ao instanciar implementação incompleta. O
valor do `Protocol` aqui é documentar a fronteira para quem lê e para o dublê da
Etapa C, não impedir erro agora. O que de fato destrava o teste offline é a
**construção sair do `Engine`**, não a anotação de tipo.

### 3.4 Seam de espera

**Novo:** `reproduction/sleeper.py`

```python
class Sleeper:

    @staticmethod
    def sleep(seconds: float) -> None:
        time.sleep(seconds)
```

Injetado em `BaseAgent` (via `AgentFactory`) e em `CurlHttpTransport`. Classe
concreta, não `Protocol`: é um wrapper de uma linha sobre um efeito colateral, e
o dublê da Etapa C herda dela sobrescrevendo `sleep`. O `Protocol` fica
reservado para `HttpTransport`, onde a superfície é maior e há duas
implementações plausíveis em produção.

⚠️ `@staticmethod` porque o método não usa estado de instância, como o guia
exige. Isso não atrapalha o dublê: uma subclasse pode sobrescrever `sleep` com
método de instância e contar chamadas.

⚠️ `ScriptExecutor.run`, em contraste, é método de **instância** — e a
justificativa honesta é só uma: é o idioma que `ExtractorRunner._execute_extractor_script`
(`:52-71`) já usa ao ler `self.EXTRACTOR_TIMEOUT_SECONDS`. Ler um `ClassVar` via
`self` não é estado de instância, então a regra do guia sozinha empurraria `run`
para `@staticmethod`/`@classmethod` também; o que decide é o precedente do
projeto.

### 3.5 `ScriptExecutor`

**Novos:** `models/execution.py` e `reproduction/script_executor.py` — o desenho
é o da spec nível 3 (§3.3 dela), com uma alteração: o `-1` de timeout, que lá era
literal, vira `TIMEOUT_RETURN_CODE: ClassVar[int]`.

```python
class ScriptExecutionResult(BaseModel):
    timed_out: bool
    return_code: int
    stdout: str
    stderr: str
```

```python
class ScriptExecutor:
    TIMEOUT_RETURN_CODE: ClassVar[int] = -1

    def run(
            self,
            script_path: Path,
            timeout_seconds: float,
            env: Optional[Dict[str, str]] = None,
    ) -> ScriptExecutionResult:
        try:
            completed: CompletedProcess[str] = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ScriptExecutionResult(
                timed_out=True, return_code=self.TIMEOUT_RETURN_CODE, stdout="", stderr=""
            )

        return ScriptExecutionResult(
            timed_out=False,
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
```

Como as duas divergências são preservadas:

- **`BaseAgent._execute_script`** chama `run(path, 5)` — mantendo o literal `5`
  de `base_agent.py:187`, **sem** promovê-lo a `ClassVar`, porque a divergência
  literal-vs-`ClassVar` entre os dois call sites (§2.6) é parte do que está
  congelado — sem `env`, e testa
  `result.timed_out` como guard clause, imprimindo `[AVISO] Timeout ao verificar
  extrator para {token_id}` e devolvendo `(False, "Timeout during verification")`.
  `ScriptExecutor` captura **só** `TimeoutExpired`, logo um `OSError` continua
  propagando de `BaseAgent` como hoje.
- **`ExtractorRunner._execute_extractor_script`** mantém o seu próprio
  `try/except Exception` **em volta da chamada** a `ScriptExecutor.run`,
  preservando o engolir-tudo. Num timeout, `return_code = -1` e o
  `if result.return_code != 0: return None` já existente produz o mesmo `None`
  de hoje.

⚠️ `env=None` em `subprocess.run` herda o ambiente do processo pai — exatamente
o comportamento atual de `BaseAgent`, que não passa `env`. Passar `None`
explicitamente preserva isso.

⚠️ **Esta costura quase não reduz duplicação** (~6 linhas comuns). Quem for
implementá-la não deve tentar unificar retorno, `env` ou tratamento de exceção
"já que está mexendo" — a divergência é o comportamento congelado.

### 3.6 `AgentFactory`

**Novo:** `agents/construction/agent_factory.py`, espelhando o layout de
`engines/construction/`.

```python
class AgentFactory:
    LOCATION_AGENTS: ClassVar[Dict[TokenLocation, Type[BaseAgent]]] = {...}
    DEFAULT_AGENT: ClassVar[Type[BaseAgent]] = RegexAgent

    def __init__(
            self,
            workspace: Workspace,
            script_executor: ScriptExecutor,
            sleeper: Sleeper,
            llm: Optional[BaseChatModel],
    ) -> None: ...

    def create(self, candidate: DynamicToken, response_sample: Dict[str, Any]) -> BaseAgent: ...
```

`CandidateResolver` perde `LOCATION_AGENTS`, os cinco imports de agent e o
atributo `llm`; recebe uma `AgentFactory` por construtor e substitui as linhas
`:186-195` por uma chamada a `create`.

⚠️ `create` reproduz **exatamente** os argumentos atuais, incluindo
`location=candidate.origin_location.value if candidate.origin_location else None`
e o default `RegexAgent` para `URL_PARAM`.

⚠️ `BaseAgent.__init__` ganha `workspace`, `script_executor` e `sleeper`. As
cinco subclasses não definem `__init__` e não mudam.

### 3.7 Injeção no ramo `run`, e `EngineFactory` como raiz de composição

**`Engine.__init__` vira atribuição pura**, no formato de `ReplayRunner`:

```python
    def __init__(
            self,
            har_path: Path,
            workspace: Workspace,
            session_store: SessionStore,
            tracker: TokenTracker,
            token_resolver: TokenResolver,
            skip_evaluator: StepSkipEvaluator,
            retry_policy: StepRetryPolicy,
            validator: Validator,
            success_criteria: List[SuccessCriterion],
            http_transport: Optional[HttpTransport],
    ) -> None:
```

`_build_http_transport` sai de `Engine` (§3.3). `_build_llm` **migra inteiro para
`EngineFactory.__init__`** — ver abaixo. `DryEngine` continua herdando `__init__`
sem override.

**As três classes de tracking recebem o que hoje constroem:**

| Classe | Passa a receber |
|---|---|
| `TokenTracker` | `baseline_diff`, `candidate_resolver`, `placeholder_applier`, `curl_generator` — perde `responses_dir`, `llm` **e `session_store`**, os três só repassados |
| `CandidateResolver` | `responses_dir`, `session_store`, `extractor_runner`, `metadata_store`, `agent_factory` — perde `llm` |
| `TokenResolver` | `responses_dir`, `session_store`, `extractor_runner` |

⚠️ `TokenTracker.session_store` (`token_tracker.py:23`) existe só para construir
`CandidateResolver` (`:27`) e `PlaceholderApplier` (`:28`) dentro do próprio
`__init__`; `analyze_step` (`:30-43`) nunca o lê. Com os dois recebidos prontos,
o atributo fica morto — vai para a §3.9.

**A raiz de composição do ramo `run` é `EngineFactory`**, na forma de instância:

```python
factory = EngineFactory(workspace, project_config, script_executor, sleeper)
uses_network = factory.resolve_class(mode).USES_NETWORK
engine = factory.create(mode, har_path, http_transport)
```

Os quatro colaboradores do `__init__` **não dependem do modo** — derivam de argv
ou são puros — então a factory se constrói antes de qualquer decisão sobre rede.
`resolve_class` vira método de instância lendo o `ClassVar _STRATEGIES`; **não
sobra nenhum `@classmethod` na classe**. `http_transport` é parâmetro de
`create` porque é o único colaborador cuja existência depende do modo.

**O LLM é construído no `__init__` da factory**, a partir do `project_config`
que ela já recebe: `_build_llm` sai de `Engine` (`engine.py:67-76`) e vira
`self.llm: Optional[BaseChatModel]`, **com o `print("LLM fallback enabled from
config: …")` intacto**. O `__init__` é o lugar, e não `create`, porque o guia
manda instanciar dependência no `__init__` e guardá-la como atributo tipado; e a
factory é construída uma vez por invocação, então o `print` continua saindo uma
vez só. A `AgentFactory` (§3.6) é o único consumidor do LLM depois desta etapa.

⚠️ Sem isso, o LLM ficaria **órfão**: `AgentFactory` o exige e nenhuma outra
peça da cadeia o produziria. A ordem resultante — `Workspace` → config →
`EngineFactory.__init__` (LLM, `print`) → orquestrador → transporte → `create` —
mantém a §5 caso 14 (workspace materializado antes de o LLM poder lançar) e
mantém o `print` na mesma posição relativa do `stdout`: verificado que
`MitmProxyOrchestrator.__init__` (`:26-31`) só faz cinco atribuições, e que o
único código que ele alcança é `_find_free_port` (`:39-43`), um bind-and-close de
socket efêmero — sem disco, sem processo, sem `print`.

⚠️ **A factory é construída exatamente uma vez, em `handle_run`, e repassada aos
dois ramos — e essa unicidade é load-bearing**, porque o `__init__` imprime.
`_run` (`cli_handlers.py:46-50`) precisa de uma instância antes do branch de
modo, para chamar `resolve_class`; se a implementação construir uma factory ali
e outra dentro de `_run_with_proxy`/`_run_without_proxy`, o LLM é construído duas
vezes e a linha `LLM fallback enabled…` **sai duplicada**. Nenhum dos 39 testes
pegaria: nenhum cenário golden configura `llm`. Em `create` esse risco não
existiria; no `__init__` ele depende de disciplina, e por isso está escrito aqui.

`CliHandlers` continua **guardando** o `Type[EngineFactory]` que recebe de
`main.py:13`; a **instanciação acontece dentro de `handle_run`**, depois de
resolver o `output_dir`, aplicar o `--reset`, construir o `Workspace` e carregar
o `ProjectConfig`. `handle_parse` nunca instancia a factory nem o `Workspace`
(§5 caso 1). `main.py` **não muda**.

O corte de responsabilidade: **a CLI possui o que vem de argv e do processo**
(paths, `--reset`, config, porta e processo do mitmdump, transporte, `Sleeper`,
`ScriptExecutor`); **a factory possui o que vem do domínio** (quais
colaboradores uma `Engine` precisa e como se ligam).

⚠️ **Isto contraria, ao pé da letra, a linha "factories como raízes de
composição" da lista de fora-de-escopo, e é deliberado.** A defesa: nenhuma
factory nova nasce; `EngineFactory` já existe e já instancia `Engine`
(`engine_factory.py:29-36`); o pacote `engines/construction/` já existe com
`__init__.py` vazio; e o ramo `replay` continua montado em
`CliHandlers._build_replay_runner`, preservando a assimetria atual em vez de
introduzir um `ReplayRunnerFactory`.

**Alternativa descartada: montar o grafo em `CliHandlers._build_engine`**,
espelhando `_build_replay_runner`. Três razões:
1. A fiação condicional de `engine.py:40` (`real_responses` vs
   `original_responses`) e `:59-65` (transporte `None` em dry) é a única lógica
   real da montagem. Como método público de uma factory ela é asserível numa
   linha; como método privado de `CliHandlers` a única porta é `handle_run`, que
   recebe `Namespace`, pode fazer `rmtree` (`:182`) e sobe mitmdump (`:70`).
2. Inverte a direção de dependência: `cli` ganharia aresta direta para
   `tracking`, `validation`, `llm` e `agents`, e `cli_handlers.py` — já o
   arquivo com mais imports do projeto — iria de 183 para ~250 linhas com duas
   responsabilidades.
3. O pacote `engines/construction/` passaria a hospedar só um registro de 15
   linhas enquanto a construção acontece dois níveis acima.

Contra-argumento considerado e pesado: a regra canônica de "uma raiz de
composição por aplicação, o mais perto possível do entry point". Não se aplica
aqui porque `main.py` (22 linhas) não pode ser a raiz — o grafo depende de paths
derivados de argv e de uma porta de mitmdump viva —, `CliHandlers` já recebe
`EngineFactory` injetado, e os dois ramos compartilham **zero instâncias**
(`SessionStore`, `ExtractorRunner`, `StepRetryPolicy` são os mesmos *tipos*,
nunca os mesmos objetos). Não há grafo comum para centralizar.

⚠️ Custo aceito e registrado: `ExtractorRunner` e `ExtractorMetadataStore`
passam a ser construídos em **dois** call sites — `EngineFactory` e
`cli_handlers.py:126,128` — e o do ramo `replay` é o esquecível. Medido:
esquecê-lo produz `TypeError` que quebra os 10 testes de `replay`, mas **os 28
offline passam**. É a razão de o portão ser sempre `--runslow`.

Números exatos, para a task não herdar exagero: hoje `ExtractorRunner()` tem
**três** call sites (`cli_handlers.py:126`, `token_resolver.py:13`,
`candidate_resolver.py:42`) e `ExtractorMetadataStore()` tem **dois**
(`cli_handlers.py:128`, `candidate_resolver.py:43`); depois desta etapa os de
`tracking/` somem e sobram dois e dois. `SessionStore` e `StepRetryPolicy` **já**
são construídos em dois lugares hoje (`engine.py:44,46` e
`cli_handlers.py:125,132`) — para eles nada muda.

⚠️ **Uma instância por ramo**, não uma por consumidor: hoje `TokenResolver` e
`CandidateResolver` criam cada um o seu `ExtractorRunner`. O que torna o
compartilhamento seguro é que **`ExtractorRunner` e `ExtractorMetadataStore`**
são sem estado — nenhuma das duas tem `__init__`, e nenhum método escreve em
atributo de instância; os efeitos colaterais são no filesystem, não no objeto.
(Os *consumidores* não são: `CandidateResolver.__init__` existe em `:33-45` e
mantém `_validated_values` e `_origin_cache`. É por isso que a afirmação vale
para o que é compartilhado, não para quem compartilha.) É o que
`_build_replay_runner` já faz no ramo `replay`.

⚠️ **Risco futuro registrado como custo aceito:** se algum dia `ExtractorRunner`
ganhar cache — a forma natural de atacar o overhead de resolução repetida de
token, tema de `docs/20260805 Overhead Redundante de Resolução de Tokens no
Modo Main` e `docs/20260805 Redução de Overhead em Resolução Redundante de
Tokens` — a instância compartilhada passa a mudar comportamento, e o golden não
distingue uma instância de duas. Quem mexer nisso precisa reabrir esta decisão.

### 3.8 O `ProjectConfig` passa a ser carregado uma vez só

`CliHandlers` carrega o `ProjectConfig` — precisa dele para
`proxy_port`/`ca_cert_path` — e passa o objeto pronto à factory. No modo `main`
isso reduz de duas cargas para uma; no modo `dry` continua uma.

⚠️ **Isto vale para `handle_run`, não para `handle_replay`.** Em `handle_replay`
a sequência atual é preservada literalmente: validação de flags (`:89`) →
checagem de existência do diretório (`:105-106`) → construção do `Workspace` →
**checagem de que existem `req_*.curl.sh` (`:109-110`)** → carga de config
(`:92`) → orquestrador. A checagem de curls fica **entre** o workspace e a
config, como hoje; intercalar a carga antes dela não quebraria nenhum golden e
ainda assim violaria a ordem de operações. Antecipar a carga para antes da
checagem de existência tornaria falsa
a garantia "erro antes de qualquer `mkdir`" do §5 caso 2, porque
`_apply_defaults` faz `mkdir` de `<repo>/.mitmproxy`. Invisível ao golden, e
proibido mesmo assim.

Consequências, ambas fora do alcance do golden:

- Com `--config` malformado, `ProjectConfigLoader._parse` (`:28-32`) imprime
  traceback em `stderr` **e** `Error loading config: ...` em `stdout`. Em `main`
  isso saía **duas vezes**; passa a sair uma. Nenhum dos 9 cenários de config da
  suíte usa JSON malformado (verificado em `tests/test_cli_config.py`).
- `_apply_defaults` chama `Workspace.get_mitmproxy_ca_path()`, que faz `mkdir`
  de `<repo>/.mitmproxy` — **fora** de `--output`, portanto invisível ao
  `GoldenWorkspace`. O `mkdir` é idempotente, mas a raiz nova **não pode**
  "otimizar" pulando `_apply_defaults` em modo `dry`: o diretório deixaria de
  ser criado e nada falharia.
- O orquestrador e a `Engine` passam a compartilhar **a mesma instância** de
  `ProjectConfig` (hoje são duas). `_apply_defaults` muta `ca_cert_path` uma vez
  na carga, e nada mais muta o objeto — aceito.

### 3.9 Código morto removido de carona

| Símbolo | Evidência |
|---|---|
| `Engine.curls_dir`, `.extractors_dir`, `.temp_extractors_dir` (`:38,41,42`) | zero leituras (grep) |
| `Engine.original_responses_dir` (`:39`) | zero leituras como atributo de `Engine`; o nome é vivo em `ReplayRunner` |
| `Engine.output_dir` (`:35`) | zero leituras; o valor passa a estar em `workspace.output_dir` |
| `Workspace.init`, `._output_dir`, `._ensure_initialized` | consequência da §3.1 |
| `TokenTracker.session_store` (`token_tracker.py:23`) | usado só dentro do próprio `__init__` (`:27-28`); fica morto quando `CandidateResolver` e `PlaceholderApplier` chegam prontos |
| `TokenTracker.responses_dir` (`:22`) e `.llm` (`:24`) | **já mortos hoje**: `:27` repassa os *parâmetros* `responses_dir` e `llm`, nunca os atributos. Zero leituras (grep) |

⚠️ Só as **duas primeiras linhas** vêm da §6.5 da spec da Etapa A.
`Engine.output_dir` não está catalogado lá; `Workspace.init`/`._output_dir`/
`._ensure_initialized` também não, e nem poderiam — hoje são código **vivo**, e
sua remoção é consequência da §3.1, não de morte prévia. Dos três de
`TokenTracker`, dois (`responses_dir` e `llm`) já eram mortos e escaparam
daquele levantamento; o terceiro (`session_store`) morre nesta etapa. Todos
sinalizados conforme o guia de estilo ("avisar antes de remover"), e nenhum
altera comportamento observável.

⚠️ **Não removidos**, apesar de catalogados na mesma §6.5: o `TypeAlias`
`contracts.StepExecutor` (`contracts/types.py:9`), `SessionStore.get_token` e
`render_dict`, o `raise RuntimeError` final de `StepRetryPolicy.execute`, o
`entries[0]` sem guarda de `engine.py:83`, e `StepRequest.is_skippable`. Nenhum
deles é tocado pelas cinco costuras — removê-los seria escopo novo.

---

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `fs_io/workspace.py` → `Workspace` | Instância; 8 atributos explícitos; 11 métodos de caminho viram de instância; perde `init`/`_output_dir`/`_ensure_initialized`; mantém os 2 `@staticmethod` |
| `contracts/http_transport.py` → `HttpTransport` | **Novo.** `Protocol` com `send_request` |
| `reproduction/sleeper.py` → `Sleeper` | **Novo.** Wrapper de `time.sleep` |
| `reproduction/script_executor.py` → `ScriptExecutor` | **Novo.** Encapsula `subprocess.run([sys.executable, ...])` |
| `models/execution.py` → `ScriptExecutionResult` | **Novo.** Resultado da execução de script |
| `agents/construction/agent_factory.py` → `AgentFactory` | **Novo.** Recebe `LOCATION_AGENTS` e a construção de agent vindas de `CandidateResolver` |
| `engines/construction/engine_factory.py` → `EngineFactory` | Vira raiz de composição do ramo `run`, em forma de instância; **absorve `_build_llm` no `__init__`**; `resolve_class` vira método de instância; sem `@classmethod` |
| `engines/engine.py` → `Engine` | `__init__` vira atribuição pura; recebe `workspace` e `http_transport`; perde `_build_http_transport`, `_build_llm`, os 4 dirs mortos e `output_dir`. Perde também **`tracking_responses_dir`** — que é vivo hoje (`:40`, lido em `:53` e `:57`) e passa a ser calculado na factory, não removido |
| `cli/cli_handlers.py` → `CliHandlers` | Constrói `Workspace`, `ProjectConfig`, `ScriptExecutor`, `Sleeper`, transporte e a `EngineFactory` — dentro de `handle_run`, nunca em `__init__`; carga única de config. **`handle_replay` constrói o seu próprio `ScriptExecutor` e `Sleeper`**, porque é ele que monta o `ExtractorRunner` e o `CurlHttpTransport` do ramo replay. `_prepare_replay_workspace` passa a **devolver** o `Workspace`; ele, `_resolve_response_reference_dir` e `_build_replay_runner` **continuam `@staticmethod`**, recebendo o `workspace` por parâmetro — `CliHandlers` não guarda workspace (é por invocação), então torná-los de instância contrariaria o guia |
| `replay/replay_result_comparator.py` → `_read_reference_text` (`:23`) e `reproduction/curl_http_transport.py` → `_try_read_capture` (`:70`) | **Deixam de ser `@staticmethod`**: os dois leem `Workspace` e passam a precisar de `self.workspace`. São os únicos dois casos assim fora do `CliHandlers` |
| `tracking/token_tracker.py` → `TokenTracker` | Recebe `baseline_diff`, `candidate_resolver`, `placeholder_applier`, `curl_generator`; perde `responses_dir`, `llm` e `session_store` |
| `tracking/candidate_resolver.py` → `CandidateResolver` | Recebe `extractor_runner`, `metadata_store`, `agent_factory`; perde `LOCATION_AGENTS`, os 5 imports de agent e `llm` |
| `tracking/token_resolver.py` → `TokenResolver` | Recebe `extractor_runner` |
| `agents/base_agent.py` → `BaseAgent` | Recebe `workspace`, `script_executor`, `sleeper`; `_execute_script` passa pelo `ScriptExecutor` |
| `reproduction/extractor_runner.py` → `ExtractorRunner` | Recebe `workspace` e `script_executor`; mantém o `except Exception` próprio |
| `reproduction/extractor_metadata_store.py` → `ExtractorMetadataStore` | Recebe `workspace` |
| `reproduction/curl_http_transport.py` → `CurlHttpTransport` | Recebe `workspace` e `sleeper` |
| `reproduction/mitm_proxy_orchestrator.py` → `MitmProxyOrchestrator` | Recebe `workspace` |
| `replay/replay_runner.py` → `ReplayRunner` | Recebe `workspace`; `http_transport` tipado como `HttpTransport` |
| `replay/replay_result_comparator.py` → `ReplayResultComparator` | Recebe `workspace` |
| `config/project_config_loader.py` | **Não muda** — só usa o `@staticmethod` |
| `models/__init__.py`, `contracts/__init__.py`, `reproduction/__init__.py`, `agents/__init__.py` | Uma linha de import e uma entrada em `__all__` para cada classe nova (`ScriptExecutionResult`, `HttpTransport`, `ScriptExecutor`, `Sleeper`, `AgentFactory`) |
| `agents/construction/__init__.py` | **Novo**, vazio — como `engines/construction/__init__.py` |
| `main.py`, `cli/cli_parser.py`, `templates/`, `models/http.py` | **Não mudam** |
| `tests/**` | **Não mudam.** Se um teste precisar mudar, a task está errada |

---

## 5. Casos de borda e comportamento de erro

| # | Caso | Comportamento a preservar |
|---|---|---|
| 1 | `handle_parse` | **Não** constrói `Workspace`. Hoje não chama `init()`; `HARParser.split_har` cria só `<output>/parse/`. Construir um `Workspace` ali criaria os 8 subdiretórios e quebraria os 4 goldens de `parse` |
| 2 | `replay` sobre diretório inexistente | `ValueError("Workspace directory does not exist: …")` **antes** de qualquer `mkdir` — o construtor do `Workspace` criaria o diretório e o erro nunca dispararia |
| 3 | `replay` sobre workspace sem curls | `ValueError("Workspace has no curl files: …")`, mensagem literal, depois da construção do `Workspace` (que cria subdiretórios faltantes, como `init()` faz hoje) |
| 4 | `--reset` | O `rmtree` (`cli_handlers.py:180-183`) roda **antes** de construir o `Workspace`, senão apaga o que acabou de criar |
| 5 | `replays/<run_id>/` em cenário de erro | Criado **eagerly** em `_build_replay_runner` (`:144`), antes de `orchestrator.run`. Continua existindo, vazio, quando `_require_all_existing` levanta. `replay_run_dir` permanece parâmetro de construtor do `ReplayRunner` — derivá-lo preguiçosamente do `workspace` faria o diretório sumir nesse caminho, e `test_replay_missing_step` não assere árvore |
| 6 | Modo `dry` | `real_responses/` intocado (`DryEngine._persist_response_step` no-op), `original_responses/` escrito nos dois modos, inclusive para steps pulados |
| 7 | `DryEngine` e transporte | `create` entrega `None` quando `USES_NETWORK` é falso, **independente** do que recebeu — a invariante de `_build_http_transport` |
| 8 | Modo `main` sem transporte | `assert http_transport is not None` dentro de `create`, no lugar do `assert proxy_port is not None` de `engine.py:64`. Inalcançável pela CLI, preservado mesmo assim |
| 9 | `TokenLocation.URL_PARAM` | `AgentFactory.DEFAULT_AGENT = RegexAgent`, como o `.get(..., RegexAgent)` de hoje |
| 10 | Timeout na verificação de extrator | `BaseAgent` imprime `[AVISO] Timeout ao verificar extrator para {token_id}` e devolve `(False, "Timeout during verification")` |
| 11 | `OSError` ao executar script | Em `BaseAgent`: **propaga**. Em `ExtractorRunner`: vira `None`. Divergência preservada de propósito |
| 12 | `ExtractorRunner.run_existing` sem o `.py` | `None` sem executar nada — guard clause de `:27-28` preservada |
| 13 | `config.json` inválido | `ProjectConfig()` vazio + traceback + `print`, fail-soft preservado. Sai **uma** vez em `main`, contra duas hoje (§3.8) |
| 14 | LLM com provider desconhecido | `ValueError` de `LLMFactory`, levantado **depois** de o `Workspace` estar materializado — como hoje, em que `Workspace.init` (`engine.py:37`) precede `_build_llm` (`:56`) dentro do mesmo `__init__`. A ordem "workspace primeiro, LLM depois" é obrigatória, e é o que garante que o comando deixe a árvore em disco antes de falhar. Sem cobertura: nenhum cenário golden configura `llm` |
| 14b | Sequência de `handle_replay` | Preservada inteira: flags → `exists()` → `Workspace` → checagem de `req_*.curl.sh` → config → orquestrador → runner. As duas checagens de erro precedem a carga de config, e a de curls fica **entre** o workspace e a config (§3.8) |
| 15 | `Workspace` sobre diretório já populado | Nada é apagado (`exist_ok=True` em tudo). O projeto nunca limpa entre execuções |
| 16 | `tracking_responses_dir` | Um único valor calculado na raiz e entregue a **dois** consumidores: `TokenResolver` e `CandidateResolver`. O `TokenTracker` deixa de recebê-lo já na costura 5b. ⚠️ Errar **um** dos dois em modo `main` pode passar verde — mas não porque os dois diretórios sejam iguais: medido, `run_main/real_responses/res_0000.json` e `original_responses/res_0000.json` divergem em `Server`, `Date` e `Content-Length`. O que salva é que o `HeaderAgent` da fixture tem origem em `Content-Type`, presente nos dois, e que os stubs `status_code: 0` dos steps 1 e 2 nunca são origem de token. Um `HeaderAgent` cuja origem fosse `Date`, `Server` ou `Content-Length` divergiria na hora. A task deve conferir os dois consumidores explicitamente |
| 17 | `StepRequest.is_skippable` | Continua existindo e sendo serializado em `real_requests/*.json` |
| 18 | Instância única de `SessionStore` | O grafo do ramo `run` tem **uma** `SessionStore`, atravessando `Engine`, `TokenResolver`, `CandidateResolver` e `PlaceholderApplier`. Hoje a unicidade é garantida pela cadeia de repasse (`engine.py:44` → `:53`,`:57` → `token_tracker.py:27-28`); quando a montagem vira plana, duplicá-la por engano deixa os tokens resolvidos invisíveis para quem renderiza o curl. ⚠️ Não é hipótese de estilo: `SessionStore` é o único colaborador **com estado mutável** de todo o grafo |

---

## 6. Suposições e pontos a confirmar

1. **Onde moram as classes novas de runtime.** `ScriptExecutor` e `Sleeper` em
   `reproduction/`, seguindo a spec nível 3, que já pôs `ScriptExecutor` lá — o
   pacote já hospeda colaboradores de processo (`mitm_env`, `proxy_readiness`,
   `step_retry_policy`). Alternativa não adotada: um pacote novo
   `har_reproducer/execution/`.
2. **Ciclos de import: verificados nas arestas certas.** Esta etapa adiciona
   **quatro** arestas entre pacotes — `agents → reproduction` (o `BaseAgent`
   tipando `Sleeper`/`ScriptExecutor`), `engines → agents` (a `EngineFactory`
   construindo a `AgentFactory`), `engines → contracts` e `replay → contracts`
   (`HttpTransport`). Nenhuma fecha ciclo: `reproduction` só alcança `fs_io`,
   `models` e `templates`; `agents` só alcança `contracts`, `fs_io`, `models`,
   `prompts` e `templates`; `contracts` só alcança `models`.
   ⚠️ **E uma aresta *intra*-pacote, que é a perigosa:**
   `agents/__init__ → agents.construction.agent_factory`. Essa **fecha** ciclo se
   a `AgentFactory` importar os agents pelo pacote — reproduzido, ver §3.2. É a
   única armadilha de import real desta etapa, e a análise entre pacotes não a
   pegaria.
3. **`AgentFactory` em `agents/construction/`**, espelhando
   `engines/construction/`. Alternativa não adotada: `agents/agent_factory.py`
   direto, como a spec nível 3 propunha.
4. **Os dois `@staticmethod` continuam em `Workspace`** e
   `project_config_loader.py` não muda (§3.1). `ProjectPaths` fica para depois.
5. **O portão de aceite de toda task é `uv run pytest --runslow`**, nunca o
   `pytest` default. A cegueira da rodada default é específica, não total:
   dos 12 testes offline de `replay`, três entram fundo em `handle_replay` —
   `test_replay_workspace_does_not_exist` (para em `:106`),
   `test_replay_workspace_has_no_curl_files` (passa por `Workspace.init` em
   `:108` e `Workspace.curls` em `:109`) e
   `test_replay_response_reference_dir_does_not_exist` (passa também pela carga
   de config e por `Workspace.real_responses` em `:114`). O que **nenhum** deles
   alcança é `_build_replay_runner` (`:98`), onde moram `ExtractorRunner`,
   `ExtractorMetadataStore`, `ReplayResultComparator`, `CurlHttpTransport` e o
   `ReplayRunner`. É essa metade que só o `--runslow` cobre.

6. **Onde cada colaborador do ramo `replay` nasce.** `handle_replay` constrói o
   seu próprio `ScriptExecutor` e `Sleeper` — eles não vêm de `handle_run`, e
   `CliHandlers` não os guarda no `__init__`. `ReplayRunner` mantém os três
   parâmetros `Path` que já recebe hoje (`replay_run_dir`, `res_refer_dir`,
   `original_responses_dir`), em vez de derivá-los do `workspace`: o primeiro
   pelo motivo do §5 caso 5, e os outros dois porque `res_refer_dir` pode vir do
   `config.json` e não do workspace.
6. **Não há checador estático no projeto** (nada em `pyproject.toml` nem em
   `pytest.ini`). Quebra de assinatura só aparece em runtime; a conferência por
   grep da §3.2 é a única rede para a única referência a `Workspace` que nenhum
   dos 39 testes exercita.
7. **`EngineFactory` como raiz de composição contraria a letra do
   fora-de-escopo** (§3.7). Decisão consciente, com a defesa registrada — é o
   ponto desta spec mais sujeito a veto.

8. **O guia de estilo fica desatualizado por esta etapa, e isso é assunto do
   Passo 5.** `.claude/skills/guia-de-estilo/SKILL.md` diz "`@classmethod` para
   padrão singleton/factory (**`Workspace`, `EngineFactory`**)" — e esta etapa
   remove *todos* os `@classmethod` das duas classes que o guia usa como exemplo
   canônico. A §7 ("todo código desta etapa segue o guia") vale para tudo menos
   essa linha. Nenhuma task altera `.claude/skills/`: a correção é um diff a
   propor na retro de convenção, com aprovação explícita, como a skill
   [[spec-e-plano]] exige.

9. **Dois pontos cegos que esta etapa não fecha e a Etapa C herda:**
   `MitmProxyOrchestrator._build_early_exit_message` e
   `ReplayRunner._annotate_static_tokens`/`_mark_token_static` (§3.2) não são
   exercitados por nenhum dos 39 testes. O segundo é o único caminho que
   reescreve `curls/` durante um replay. Cobri-los é trabalho da Etapa C, não
   desta.

---

## 7. Referência

Todo código desta etapa segue `.claude/skills/guia-de-estilo/SKILL.md`: tipagem
explícita em toda variável, parâmetro, retorno e atributo; `ClassVar` para
constantes de classe; `Path` para caminhos; uma classe por arquivo, nada solto
no módulo; nenhum comentário e nenhuma docstring; guard clauses e no máximo dois
níveis de indentação por método.
