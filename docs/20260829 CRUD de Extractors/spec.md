# Spec — CRUD de Extractors

## 0. Sumário e glossário

**Sumário.** Hoje um extractor (o par de arquivos `extract_<token_id>.py` +
`extract_<token_id>.meta.json` em `<workspace>/extractors/`, e a referência
`{{extractor:<token_id>}}` que ele deixa num `.curl.sh`) só nasce, muda ou morre como
efeito colateral do comando `run` — a única forma de corrigir um extractor errado, criar
um que faltou, ou remover um inútil é rodar `run` de novo (potencialmente contra o
servidor real) e torcer para a descoberta automática acertar dessa vez. Esta etapa
adiciona um comando novo, `extractor`, que opera diretamente sobre um workspace já
existente (criado por um `run` anterior) para listar, inspecionar, criar, editar,
apagar, testar e (des)vincular extractors a curls — sem rodar `run` de novo e sem
subir o proxy/mitm. O público-alvo declarado é um agente de IA fazendo correção de
fluxo, o que muda o desenho: toda operação de escrita é validada executando o código
contra pelo menos uma resposta real antes de persistir (nunca "parece certo"), a saída
é sempre JSON em stdout (uma API de máquina, não de humano), e cada mutação expõe um
preview do que mudaria antes de exigir confirmação implícita — pontos detalhados nas
seções 3 e 5.

**Glossário:**

- **CRUD de extractors** — o comando `extractor` e suas 8 ações (`list`, `get`,
  `create`, `update`, `delete`, `bind`, `unbind`, `test`), tema desta spec.
- **Amostra (sample)** — um arquivo JSON de resposta HTTP real usado para validar um
  extractor: tanto `real_responses/res_NNNN.json`/`original_responses/res_NNNN.json` já
  existentes no workspace quanto um arquivo JSON arbitrário apontado pelo chamador.
- **Vínculo (bind)** — a referência de um `token_id` a um `.curl.sh` específico: a
  linha de comentário `# [Token <id> comes from response of step <n>]` mais a
  ocorrência do placeholder `{{extractor:<id>}}` no corpo do curl.
- **Extractor órfão** — um `.meta.json`/`.py` persistido cujo `token_id` não aparece
  como placeholder em nenhum `.curl.sh` do workspace.
- **Curl órfão de token** — um `.curl.sh` que referencia (via placeholder ou comentário
  de dependência) um `token_id` sem `.meta.json`/`.py` correspondente em `extractors/`.

## 1. Objetivo

O pipeline de descoberta automática (`run`/`dry`, ver [[arquitetura-e-fundamentos]])
tenta generalizar da melhor forma possível, mas por design nunca vai acertar 100% dos
casos — o próprio princípio de genericidade do projeto admite isso (extractor literal
como fallback consciente, não como erro). Na prática isso se manifesta em três
problemas que hoje só têm um remédio (rodar `run` de novo, contra o servidor real,
sem controle fino sobre o que muda):

1. **Extractor incorreto em alguns casos** — o código gerado bate com a amostra usada
   na descoberta mas falha (ou extrai o valor errado) contra outras respostas do mesmo
   formato — típico de regex/CSS ajustado a uma única ocorrência (overfitting), não a
   uma estrutura recorrente.
2. **Extractor inútil** — foi gerado, mas nunca deveria ter sido (ex.: um valor que na
   verdade é estático e o `admission_gate`/`BaselineDiff` classificou errado como
   dinâmico) ou está vinculado a um curl que não precisa mais dele.
3. **Extractor fundamental ausente** — um valor dinâmico real não foi descoberto (a
   origem não foi encontrada, `TokenLocationDetector` não reconheceu o local, ou o
   `Agent` esgotou tentativas e caiu para `LiteralAgent`/`LiteralFallbackAgent`) e o
   curl ficou com um literal capturado que só funciona para aquela reprodução
   específica.

O objetivo desta etapa é permitir corrigir os três casos diretamente sobre os
artefatos já materializados em `<workspace>/extractors/` e `<workspace>/curls/`, com
validação obrigatória antes de qualquer escrita, para uso por um agente de IA operando
sem supervisão linha a linha.

**Fora de escopo** (explicitamente, não implementar nesta etapa):

- Rodar `Agent`s/LLM para *descobrir* novos candidatos — o CRUD assume que o
  `code`/`token_id` já vêm prontos do chamador (humano ou agente de IA); ele valida e
  persiste, não gera heurística de extração nova.
- Reprocessar `TokenLocation`/`AgentType` de um extractor a partir da resposta (ex.:
  "detectar automaticamente se isso é regex ou CSS") — o chamador informa
  `agent_type` explicitamente na criação/edição.
- Qualquer alteração ao comportamento de `run`/`replay`/`optimize` existentes — esta
  etapa só adiciona um comando novo e read/write isolado sobre arquivos que esses
  comandos já produzem e consomem, sem tocar a lógica deles.
- UI ou API HTTP — a interface é CLI, mesmo padrão dos comandos já existentes.
- Resolver a colisão de `token_id` do jeito que `CandidateResolver._fork_token_id` faz
  hoje (fork automático) — o CRUD detecta a colisão e recusa a operação, deixando a
  decisão (sobrescrever ou usar outro id) para o chamador. Ver seção 5.

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

- **`Extractor`** (`har_reproducer/models/session.py:38-48`) — modelo Pydantic
  persistido em `.meta.json`. Campos: `token_id: str`, `code: str`,
  `verified: bool = False`, `agent_type: AgentType`, `origin_step: Optional[int]`,
  `temp_file_path: Optional[str]`, `valid_count: int = 0`,
  `last_value: Optional[str]`, `ever_changed: bool = False`,
  `captured_value: Optional[str]`. Nenhum campo é adicionado ou removido nesta etapa.
- **`ExtractorMetadataStore`** (`har_reproducer/reproduction/extractor_metadata_store.py:8-24`)
  — `load(token_id) -> Optional[Extractor]` lê `workspace.extractor_meta_file(token_id)`
  e desserializa via `Extractor.model_validate_json`; `save(extractor)` escreve
  `extractor.model_dump_json(indent=2)`. Não existe hoje nenhum método de listagem —
  ver decisão 3.1.
- **`ExtractorRunner`** (`har_reproducer/reproduction/extractor_runner.py:11-76`) —
  `run(extractor, response_override_dir=None)` **escreve o `.py` (`_write_extractor_script`,
  linhas 18-21 e 33-44) antes de executar e comparar** — a ordem real é grava → limpa
  `temp_file_path` → só então roda. Isso significa que `run()` **não serve como
  validação pré-escrita**: se for usado para "testar antes de aceitar", o `.py`
  (potencialmente quebrado) já foi sobrescrito no disco antes de qualquer decisão do
  chamador — ponto central que descarta reaproveitar `run()` no fluxo de validação do
  CRUD (ver decisão 3.4, que usa `ExtractorValidator`/`render_temp_script` em vez
  disso, e só chama a escrita final depois de aprovada). `run_existing(token_id,
  response_override_dir=None)` executa um `.py` já persistido sem reescrevê-lo,
  devolvendo `None` se o arquivo não existir — esse sim é seguro para reaproveitar
  tal como está (ex.: na ação `test` quando o chamador não fornece `--code-file`).
- **`ExtractorTemplate`** (`har_reproducer/templates/extractor_template.py:6-66`) —
  `render_script(safe_token_id, code, step_index)` é a variante final persistida (lê
  a resposta de `real_responses/res_{step_index:04d}.json` em runtime, respeitando
  `HAR_REPRODUCER_RESPONSE_OVERRIDE_DIR`); `render_temp_script(safe_token_id, code,
  response_sample)` embute a resposta inline como `repr()` de dict Python e é a
  variante usada para testar contra uma amostra arbitrária sem depender de arquivo em
  `real_responses/` — é o que a ação `test` (seção 3.5) reaproveita diretamente, do
  mesmo jeito que `BaseAgent._write_temp_script`
  (`har_reproducer/agents/base_agent.py:179-187`) já faz.
- **`IdentifierSanitizer.sanitize(raw)`** (`har_reproducer/templates/identifier_sanitizer.py`)
  — `re.sub(r"\W", "_", str(raw))` prefixado com `t_` (ou `"token"` se vazio). O `code`
  de um `Extractor` **precisa** definir `def extract_{IdentifierSanitizer.sanitize(token_id)}(response):
  ...` — é o nome que `render_script`/`render_temp_script` chamam depois de colar o
  `code` no template (`extractor_template.py:29,62`). Um `code` com nome de função
  divergente falha em runtime com `NameError`, silenciosamente convertido em
  `return_code != 0` → `None` por `ExtractorRunner._execute_extractor_script` — ou
  seja, hoje esse erro de contrato não tem mensagem clara nenhuma. Ver decisão 3.2.
- **`CurlTokenComment`** (`har_reproducer/replay/curl_token_comment.py:21-126`) — já é
  uma classe autocontida (não amarrada a `CurlGenerator`), reaproveitável tal como
  está: `format_dependency_line(token_id, origin_step, origin_status=None) -> str`
  gera exatamente a linha `# [Token <id> comes from response of step <n>]`, e
  `parse(curl_text) -> Dict[str, int]`/`parse_anchors(curl_text) -> Dict[str, int]` já
  sabem ler essas linhas de volta. Nenhuma mudança necessária nesta classe.
- **`CookieJarCurlOverride`** (`har_reproducer/reproduction/cookie_jar_curl_override.py:1-59`)
  — não é reaproveitado por chamada direta (resolve cookies, não tokens de extractor),
  mas é o precedente de estilo a seguir para reescrever um `.curl.sh` já persistido: tokeniza
  com `shlex.split(..., comments=True)`, localiza/substitui o argumento certo, e
  remonta com `shlex.join(...)` — nunca regex de texto livre sobre o curl inteiro. A
  decisão 3.3 usa o mesmo padrão.
- **`Workspace`** (`har_reproducer/fs_io/workspace.py:7-73`) — `extractor_file(token_id)`,
  `extractor_meta_file(token_id)` (usam o `token_id` cru como nome de arquivo, apesar
  do parâmetro se chamar `safe_token_id`), `curl_file(index)` e o diretório público
  `self.curls: Path` (usado para glob, ver `ReplayRunner.existing_step_indexes`,
  `har_reproducer/replay/replay_runner.py:216-222`, precedente para achar todos os
  `.curl.sh` de um workspace).
- **`CandidateResolver._derive_token_id`/`_fork_token_id`**
  (`har_reproducer/tracking/candidate_resolver.py:159-165`) — `token_id` é hoje sempre
  um hash MD5 hex (`md5(f"{path}:{origin_step}")`, ou `md5(f"{base}:{attempt}")` em
  caso de colisão). Nada no runtime (nem `Workspace`, nem `ExtractorMetadataStore`,
  nem `SessionStore.TOKEN_PLACEHOLDER_PATTERN = re.compile(r"\{\{extractor:([a-f0-9]+)\}\}")`,
  `har_reproducer/session/session_store.py:9`) impõe que seja MD5 — mas o regex do
  placeholder exige que o `token_id` case com `[a-f0-9]+`, ou seja, **só aceita
  caracteres hexadecimais minúsculos**. Isso restringe qualquer `token_id` fornecido ao
  CRUD (seção 3.2).
- **`CandidateResolver._register_extractor`** (`har_reproducer/tracking/candidate_resolver.py:173-186`)
  — grava em disco só a linha `self.metadata_store.save(new_extractor)` (183); as
  outras duas linhas do corpo (`self.session_store.state.registry[...] = new_extractor`,
  `candidate.status = "Resolved"`) são estado em memória do processo de `run`, não
  persistência — citado aqui só como precedente de "quem hoje chama `save()`", não
  como algo que o CRUD reaproveita diretamente.
- **`TokenResolver._refresh_token`** (`har_reproducer/tracking/token_resolver.py:25-39`)
  — confirma que `extractor.captured_value` é usado como fallback (linhas 37-39)
  sempre que `ExtractorRunner.run()` devolve `None` ou lança exceção — mesmo padrão de
  fallback citado na seção 5 para `bind`/`unbind`.
- **`StepResponse`** (`har_reproducer/models/http.py:22-31`) — modelo Pydantic que
  todo `real_responses/res_NNNN.json` de fato é (`status_code`, `headers`,
  `cookies`, `cookie_attributes`, `body`, `body_mime`, `redirect_url`, `skipped`,
  `skip_reason`). Os agentes concretos (`HeaderAgent`, `JSONPathAgent`, etc.) lêem o
  dict de resposta esperando exatamente essas chaves (`response.get("headers", {})`,
  `response.get("body", "")`) — uma amostra fornecida ao CRUD que não tiver essa
  forma produz um extractor que "roda" mas nunca acha o valor, indistinguível de
  código errado se não for validado à parte (seção 3.4, seção 5).
- **`Workspace.response_file(index)`** (`har_reproducer/fs_io/workspace.py:49-50`) —
  devolve o `Path` de `real_responses/res_{index:04d}.json` **sem checar se existe**;
  é o método que o CRUD usa para checar a existência da amostra **antes** de tentar
  validar (seção 3.4), em vez de depender de uma exceção que o próprio `ExtractorRunner`
  não levanta para esse caso (ver nota abaixo).
- ⚠️ **`ExtractorRunner._write_extractor_script` só levanta `ValueError` quando
  `extractor.origin_step is None`** (`extractor_runner.py:34-35`) — nunca quando
  `origin_step` tem um valor válido mas o arquivo de resposta correspondente não
  existe. Nesse segundo caso, a falha só aparece dentro do subprocesso gerado por
  `ExtractorTemplate.render_script`/`_load_response` (linhas 51-57, 64-65 do template)
  e vira silenciosamente `return_code != 0` → `None` em
  `ExtractorRunner._execute_extractor_script` (linhas 64-69) — sem exceção nenhuma
  para o chamador distinguir "resposta ausente" de "código errado". O CRUD não pode
  depender de capturar `ValueError` para esse cenário (ver seção 5).

## 3. Decisões de arquitetura

### 3.1 — `ExtractorMetadataStore.list_all()`

**Estado atual:** só existe `load(token_id)` pontual — nenhuma forma de enumerar todos
os extractors de um workspace.

**Estado esperado:**

```python
def list_all(self) -> List[Extractor]:
    extractors: List[Extractor] = []
    for meta_file in sorted(self.workspace.extractors.glob("extract_*.meta.json")):
        token_id: str = meta_file.stem.removeprefix("extract_").removesuffix(".meta")
        extractor: Optional[Extractor] = self.load(token_id)
        if extractor is not None:
            extractors.append(extractor)
    return extractors
```

Reaproveita o `load()` existente (mesmo tratamento de erro, mesmo `print` de aviso em
`.meta.json` corrompido — nenhum `.meta.json` inválido derruba a listagem inteira).
Aditivo: nenhuma assinatura existente muda.

### 3.2 — Validação de `code` antes de qualquer escrita: `ExtractorValidator`

**Estado atual:** o único lugar que verifica "esse `code` roda e devolve o valor certo"
é `BaseAgent._verify_code`/`_write_temp_script`/`_execute_script`
(`har_reproducer/agents/base_agent.py:174-177, 179-187, 189-202`), amarrado a uma
instância de agente (`self.workspace`, `self.script_executor`, `self.safe_token_id`,
`self.expected_value` como atributos de instância) — não é chamável isoladamente para
um `code` fornecido por fora do fluxo de agente/LLM. Nota: `_write_temp_script`
sempre grava no mesmo caminho determinístico `workspace.temp_extractor_file(self.safe_token_id)`
— um arquivo por `token_id`, não por amostra; isso importa para o design de
`run_against_samples` abaixo, que precisa rodar várias amostras por chamada sem que
uma sobrescreva o arquivo temporário da anterior nem deixe resíduo (seção 5).

**Estado esperado:** uma classe nova, `ExtractorValidator`
(`har_reproducer/reproduction/extractor_validator.py`), que replica a mesma verificação
sem depender de um `Agent`:

```python
class ExtractorSampleResult(BaseModel):
    sample_label: str
    output: Optional[str]
    error: Optional[str]
    matches_expected: Optional[bool]


class ExtractorValidator:
    def __init__(self, script_executor: ScriptExecutor) -> None:
        self.script_executor: ScriptExecutor = script_executor

    def defines_expected_function(self, token_id: str, code: str) -> bool:
        expected_name: str = f"extract_{IdentifierSanitizer.sanitize(token_id)}"
        return re.search(rf"^def {re.escape(expected_name)}\(", code, re.MULTILINE) is not None

    def run_against_samples(
            self, token_id: str, code: str, samples: Dict[str, Dict[str, Any]],
            expected_values: Optional[Dict[str, str]] = None,
    ) -> List[ExtractorSampleResult]:
        ...  # para cada (label, response_json) em samples: escreve um temp script via
             # ExtractorTemplate.render_temp_script num caminho único por (token_id, label)
             # — nunca o caminho fixo workspace.temp_extractor_file(safe_token_id) que
             # BaseAgent usa (colidiria entre amostras da mesma chamada, ou entre chamadas
             # concorrentes para o mesmo token_id) —, executa, monta ExtractorSampleResult,
             # e remove o temp script em seguida, sempre (sucesso, falha ou exceção)
```

`defines_expected_function` é checado **antes** de qualquer tentativa de execução, em
todo `create`/`update` — hoje um `code` com nome de função errado falha em runtime como
`NameError`, convertido silenciosamente em `None` por
`ExtractorRunner._execute_extractor_script` (linhas 64-69); o CRUD recusa a operação
com uma mensagem explícita em vez de deixar isso acontecer.

`run_against_samples` reaproveita `ExtractorTemplate.render_temp_script` (já existe,
seção 2) e um `ScriptExecutor` recebido por construtor (mesmo padrão de dependência
injetada de `ExtractorRunner`/`BaseAgent`) — nenhuma classe existente precisa mudar
para isso funcionar; `ExtractorValidator` só monta o script, delega a execução e limpa
o próprio temp file (ao contrário de `BaseAgent`, cujo cleanup só acontece no caminho
de falha do TDD loop — `run_against_samples` limpa incondicionalmente, já que não há
um "loop" externo que vá reaproveitar o arquivo depois).

⚠️ Isso é o que endereça diretamente o problema #1 da seção 1 (extractor que funciona
numa amostra e falha em outras): tanto `create`/`update` quanto a ação `test` (3.5)
aceitam **múltiplas amostras**, não uma só — ao contrário do TDD loop atual
(`BaseAgent.run_tdd_loop`), que só verifica contra a `response_sample` única capturada
na descoberta.

### 3.3 — Vínculo com um `.curl.sh` persistido: `ExtractorCurlBinder`

**Estado atual:** a única forma de um curl ganhar `{{extractor:<id>}}` e a linha
`# [Token <id> comes from response of step <n>]` é via `CurlGenerator.generate()`
(`har_reproducer/reproduction/curl_generator.py:15-21`), que **sempre reconstrói o
curl inteiro a partir de um `StepRequest` em memória** — nunca edita um `.curl.sh` já
escrito em disco. Não existe hoje nenhuma operação de "editar o curl persistido para
apontar (ou parar de apontar) para este token".

**Estado esperado:** uma classe nova,
`har_reproducer/reproduction/extractor_curl_binder.py`, no mesmo estilo de
`CookieJarCurlOverride` (shlex, nunca regex de texto livre sobre o curl inteiro):

```python
class ExtractorCurlBinder:
    def __init__(self, curl_token_comment: CurlTokenComment) -> None:
        self.curl_token_comment: CurlTokenComment = curl_token_comment

    def bind(self, curl_text: str, token_id: str, origin_step: int, literal_value: str) -> Tuple[str, int]:
        ...  # separa as linhas "# [...]" do corpo do curl ANTES de tokenizar (ver ⚠️
             # abaixo — ao contrário de CookieJarCurlOverride, aqui a saída é persistida,
             # então nenhuma linha de comentário pode ser perdida); tokeniza só o corpo
             # via shlex, substitui toda ocorrência exata de `literal_value` num token
             # por "{{extractor:<token_id>}}" (contando quantas substituições fez),
             # remonta o corpo com shlex.join, e insere/substitui a linha de dependência
             # deste token_id (format_dependency_line(token_id, origin_step,
             # origin_status=None) — sempre reseta qualquer status de origem/replay que
             # a linha já carregasse, ver ⚠️ abaixo) entre as demais linhas de comentário
             # preservadas; devolve (novo_texto, contagem_de_substituicoes)

    def unbind(self, curl_text: str, token_id: str, replacement_value: str) -> Tuple[str, int]:
        ...  # mesma separação comentários/corpo; troca TODAS as ocorrências exatas de
             # "{{extractor:<token_id>}}" por replacement_value no corpo (espelhando
             # bind, que pode ter criado mais de uma ocorrência — ver ⚠️ abaixo),
             # contando quantas trocou, e remove só a linha
             # "# [Token <token_id> comes from response of step ...]" correspondente,
             # preservando as demais; devolve (novo_texto, contagem_de_substituicoes)
```

`bind`/`unbind` recebem e devolvem **texto** do curl (não leem/escrevem arquivo
diretamente) — quem lê/escreve `workspace.curl_file(index)` é o handler CLI (seção
3.6), o que mantém a classe testável sem I/O, mesmo padrão de `CurlGenerator.generate`.

⚠️ **O paralelo com `CookieJarCurlOverride` vale só para a técnica de tokenização
(shlex em vez de regex de texto livre), não para a forma como ela trata comentários.**
`CookieJarCurlOverride.apply` (`cookie_jar_curl_override.py:14-23`) chama
`shlex.split(curl_resolved, comments=True)` sobre o **texto inteiro** do curl
(inclusive as linhas `# [Token ...]`), e `comments=True` descarta qualquer token que
comece com `#` — seguro ali só porque `curl_with_jar` é usado uma vez, na hora de
disparar a requisição (`ReplayRunner._run_step`, `replay_runner.py:116-117`), e
**nunca é escrito de volta no `.curl.sh`** — o arquivo original com os comentários
permanece intacto em disco. `ExtractorCurlBinder.bind`/`unbind`, ao contrário,
**reescreve o `.curl.sh` persistido** — se tokenizasse o texto inteiro com
`comments=True` do mesmo jeito, apagaria do arquivo, silenciosamente, as linhas de
dependência de **outros tokens** vinculados ao mesmo curl (quebrando
`CurlTokenComment.parse`/`parse_anchors` para esses outros tokens em replays
futuros). Por isso `bind`/`unbind` separam as linhas `# [...]` do corpo do curl antes
de tokenizar — só o corpo passa por shlex; as linhas de comentário são
manipuladas por texto puro (achar/substituir a linha específica deste `token_id`),
não fazem parte da tokenização.

⚠️ **`ExtractorCurlBinder.bind` não é chamada com um `token_id` arbitrário — o handler
`handle_bind` é quem garante as duas invariantes abaixo antes de sequer montar o
texto novo do curl:**

1. **O `token_id` precisa existir e estar persistido** — `handle_bind` chama
   `ExtractorMetadataStore.load(token_id)`; se vier `None`, recusa
   (`{"ok": false, "error": "token_id does not exist, use create first"}`). Sem essa
   checagem, `bind` criaria exatamente o "curl órfão de token" que o glossário (§0)
   define como estado ruim — um placeholder no curl sem `.meta.json`/`.py`
   correspondente.
2. **`origin_step` não é uma flag de `bind`** — é sempre lido do
   `Extractor.origin_step` já persistido (o mesmo objeto carregado no passo 1), nunca
   informado pelo chamador. Existem duas fontes de "origin_step" no sistema que não
   podem divergir: o valor gravado dentro do `.py` (decide qual arquivo
   `res_{step}.json` o extractor lê em runtime, `extractor_template.py:51-57`) e o
   valor do comentário de dependência no curl (decide, em `ReplayTokenResolver._resolve_one`,
   `har_reproducer/replay/replay_token_resolver.py:47-60`, qual diretório de override
   passar). Se `bind` aceitasse um `origin_step` independente do chamador, um valor
   divergente faria `ReplayTokenResolver` escolher o diretório errado (achando que o
   step está "in schedule" quando não está, ou vice-versa) e cair silenciosamente no
   fallback `captured_value` sem pista da causa raiz. Derivar sempre do `Extractor`
   persistido elimina essa divergência por construção.

Se `literal_value` aparecer em mais de um token do curl (ex.: o mesmo valor
literal por coincidência em dois headers), `bind` substitui **todas** as ocorrências
exatas — é o comportamento mais seguro por padrão (evita reprodução carregar o valor
antigo em algum lugar esquecido), e a contagem de substituições feitas (segundo
elemento da tupla devolvida por `bind`) é repassada tal como está na saída JSON da
ação `bind` para o chamador perceber se não era o esperado (0 substituições é,
inclusive, o caso de recusa "literal_value not found in curl" da seção 5).

⚠️ **`unbind` espelha essa mesma regra, por simetria**: se `bind` criou N ocorrências
do placeholder (porque `literal_value` apareceu N vezes), `unbind` precisa trocar as
N ocorrências de volta — uma implementação que só troca a primeira deixaria N-1
placeholders "presos" depois de um `unbind` aparentemente bem-sucedido. Por isso
`unbind` também devolve `Tuple[str, int]` (mesma forma de `bind`), não só `str`.

### 3.4 — Persistir só depois de validado (nunca via `ExtractorRunner.run`)

**Estado atual:** `CandidateResolver._register_extractor`
(`har_reproducer/tracking/candidate_resolver.py:173-186`) chama só
`self.metadata_store.save(new_extractor)` — o `.py` só é escrito depois, de forma
adiada, na primeira vez que `TokenResolver._refresh_token`
(`har_reproducer/tracking/token_resolver.py:25-39`) chama
`self.extractor_runner.run(extractor, ...)` durante a resolução de tokens do `run`.
Ou seja, hoje `.meta.json` e `.py` **nunca são garantidos sincronizados no mesmo
instante** — é uma janela aceita porque o pipeline de `run` sempre acaba chamando
`run()` antes do curl ser de fato usado.

**Estado esperado:** o CRUD **não pode reaproveitar `ExtractorRunner.run()` como
"validar antes de aceitar"**, porque `run()` já escreve o `.py` em disco antes de
executar e comparar (seção 2) — usá-lo aqui deixaria exatamente um `.py` quebrado no
disco quando a validação reprovasse. O fluxo de `create`/`update` é, nesta ordem
exata:

0. **`update` apenas:** carregar o `Extractor` existente
   (`ExtractorMetadataStore.load(token_id)`; recusar com `"token_id does not exist,
   use create"` se vier `None`) e construir o objeto final mesclando os campos
   informados por flag sobre os valores já persistidos (campo omitido → mantém o
   valor carregado). **Todos os passos seguintes (1-6) operam sobre esse objeto já
   mesclado** — em particular, o `origin_step` usado no passo 4 é sempre o
   `origin_step` final (informado ou herdado), nunca `None` só porque `--origin-step`
   foi omitido nesta chamada. `create` não tem esse passo — os campos vêm só das
   flags, todas exigidas na tabela 3.6 (`--code-file --agent-type --origin-step`
   obrigatórios).
1. Validar que `token_id` **inteiro** casa com o charset hex minúsculo —
   `re.fullmatch(r"[a-f0-9]+", token_id)` — recusar antes de qualquer outro passo,
   inclusive antes do `load()` do passo seguinte. ⚠️ Isso **não** é a mesma coisa que
   chamar `SessionStore.TOKEN_PLACEHOLDER_PATTERN` diretamente sobre o `token_id`:
   esse padrão é `re.compile(r"\{\{extractor:([a-f0-9]+)\}\}")`
   (`session_store.py:9`) — exige literalmente o prefixo `{{extractor:` e o sufixo
   `}}` ao redor do grupo hex, então rodá-lo com `.fullmatch()`/`.match()` contra um
   `token_id` cru (sem chaves) **nunca casa**, mesmo para um `token_id` válido como
   `"deadbeef"` — recusaria `create`/`update` sempre. E `.search()` sem âncoras
   (`^...$`) aceitaria uma string como `"aa/../../etc"` (acha a substring válida
   `"aa"` e ignora o resto), o próprio vetor de escape de diretório que esta
   checagem existe para prevenir, já que `Workspace.extractor_file`/
   `extractor_meta_file` (seção 2) usam o `token_id` cru como nome de arquivo.
   `TOKEN_PLACEHOLDER_PATTERN` é reaproveitado só como *referência* do charset
   esperado (o grupo `[a-f0-9]+` dentro dele), nunca como o objeto regex a ser
   chamado sobre o `token_id` isolado — a validação usa um `re.fullmatch` próprio,
   anchorado, sobre a string inteira.
2. **`create` apenas:** checar que `token_id` ainda não existe
   (`ExtractorMetadataStore.load(token_id) is None`) — se já existir, recusar
   (`"token_id already exists, use update"`) antes de qualquer outro passo.
3. Validar que `code` define `extract_{IdentifierSanitizer.sanitize(token_id)}`
   (`ExtractorValidator.defines_expected_function`, 3.2).
4. Checar `workspace.response_file(origin_step).exists()` explicitamente (seção 2,
   `Workspace.response_file`) — se não existir, recusar com uma mensagem específica
   ("response for step N not found"), sem tentar rodar nada.
5. Carregar essa resposta como **dict cru** (`json.loads(...)`) e validar que ela tem
   a forma de `StepResponse` (`StepResponse.model_validate(response_dict)`, seção 2 e
   seção 5 — "amostra que é JSON válido mas não tem a forma de `StepResponse`") — a
   instância de `StepResponse` devolvida por `model_validate` serve só para essa
   checagem de forma e é descartada em seguida; é o **dict cru**, não a instância
   Pydantic, que é passado adiante, porque `render_temp_script`/`render_script`
   embutem a resposta como um dict Python literal e o `code` gerado a acessa via
   `.get(...)` (uma instância de `StepResponse` não tem esse método). Chamar
   `ExtractorValidator.run_against_samples(token_id, code, {"origin_step":
   response_dict, **amostras extras de `--sample`})` — **nunca toca `extractors/`**,
   só escreve/lê arquivos temporários em `temp_extractors/` (3.2). Se a amostra
   rotulada `"origin_step"` não bater com `captured_value` (quando fornecido) ou com
   o valor de `--expect` correspondente (quando fornecido), recusar — nada foi
   escrito em `extractors/` até aqui.
6. Só agora, com a validação aprovada: escrever `extract_<token_id>.py` chamando
   `ExtractorTemplate.render_script(...)` diretamente (reaproveitando o template, não
   `ExtractorRunner.run()` — evita reexecutar o script mais uma vez à toa, já que o
   passo 5 já confirmou que o `code` funciona) e, imediatamente em seguida, sem
   nenhum I/O entre os dois, `ExtractorMetadataStore.save(extractor)`.

⚠️ Isso reduz a janela de dessincronização a duas escritas consecutivas sem lógica
entre elas, mas não é uma garantia de transação real (uma queda de processo exatamente
entre o passo 6a e o 6b ainda deixaria os dois arquivos fora de sincronia) — aceito
como risco residual da mesma categoria da dívida já existente no pipeline (seção 2),
não uma garantia nova que a spec esteja prometendo. Uma transação de verdade (escrever
em arquivo temporário + `os.replace` atômico dos dois) fica fora de escopo desta etapa;
se um caso real de corrupção aparecer, é assunto de spec futura.

Nenhuma classe existente muda aqui — é orquestração nova no handler CLI (seção 3.6)
sobre os componentes que já existem (`ExtractorValidator`, `ExtractorTemplate`,
`ExtractorMetadataStore`).

### 3.5 — Ação `test`: candidato solto, sem persistir

**Estado esperado (novo):** `extractor test` roda um `code` (do próprio extractor já
persistido, ou de um `--code-file` fornecido pelo chamador — útil pra testar uma
correção *antes* de decidir se vira `update`) contra uma ou mais amostras, sem
escrever nada em disco. Reaproveita só `ExtractorValidator.run_against_samples` (3.2).
É a ferramenta que endereça diretamente o pedido original: um agente de IA pode testar
uma correção contra várias respostas reais do workspace (`real_responses/res_0003.json
res_0007.json ...`) antes de comprometer a mudança com `update`.

### 3.6 — Superfície CLI: subcomando `extractor`

**Estado esperado:** um subcomando novo `extractor`, com uma sub-ação obrigatória
(`argparse` sub-subparser, mesmo padrão de `--mode` em `replay`, mas aqui como
subcomando aninhado por exigir flags distintas por ação):

```bash
uv run python -m har_reproducer.main extractor <ação> --output DIR [flags da ação]
```

| Ação | Flags | Efeito |
|---|---|---|
| `list` | `--output` | Lista todos os extractors do workspace (via `ExtractorMetadataStore.list_all`), cada um anotado com os `.curl.sh` que o referenciam (glob dos curls + `SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text)` sobre o **corpo** de cada um — ver ⚠️ abaixo). |
| `get` | `--output --token-id` | Mostra um extractor (via `load`) + a mesma anotação de curls vinculados. `404`-like (`ok: false`) se não existir. |
| `create` | `--output --token-id --code-file --agent-type --origin-step [--captured-value] [--verified]` | Valida (3.2) e persiste (3.4) um extractor novo. Recusa se `token_id` já existir (usar `update`). |
| `update` | `--output --token-id [--code-file] [--agent-type] [--origin-step] [--captured-value] [--verified]` | Mesma validação/persistência de `create`, mas exige que o `token_id` já exista; campos omitidos mantêm o valor atual. |
| `delete` | `--output --token-id [--force]` | Remove `.py` + `.meta.json`. Recusa se algum `.curl.sh` ainda referencia o token (mesma checagem de "referenciado por" de `list`/`get` acima), a menos que `--force` (ver seção 5). |
| `bind` | `--output --token-id --curl req_NNNN.curl.sh --value` | Carrega o `Extractor` (recusa se não existir — ver 3.3), deriva `origin_step` dele (nunca é uma flag) e aplica `ExtractorCurlBinder.bind` no `.curl.sh` indicado, reescrevendo o arquivo. |
| `unbind` | `--output --token-id --curl req_NNNN.curl.sh --value` | Aplica `ExtractorCurlBinder.unbind` (troca o placeholder pelo literal informado em `--value`) e reescreve o arquivo. |
| `test` | `--output [--token-id \| --code-file] --sample res_0003.json [--sample ...] [--expect res_0003.json=valor ...]` | Roda contra as amostras indicadas (paths dentro de `real_responses/`/`original_responses/` ou absolutos), sem persistir nada. |

`--output` é sempre obrigatório (o workspace já existente, mesmo significado que em
`replay`/`optimize`) e o comando **nunca** sobe o proxy/mitm nem toca a rede — é
leitura/escrita pura de arquivos, do mesmo jeito que o `replay` já demonstra ser
possível sem re-descoberta.

⚠️ **A checagem de "referenciado por" (`list`/`get`/`delete`) usa o placeholder no
corpo do curl, não a linha de comentário.** `CurlTokenComment.parse(curl_text)`
(`har_reproducer/replay/curl_token_comment.py:71-75`) só lê as linhas
`# [Token <id> comes from response of step <n>]` — nunca olha o corpo do curl em
busca de `{{extractor:<id>}}`. Se um `.curl.sh` tiver o placeholder no corpo mas, por
edição manual (plausível dado que o público-alvo edita curls diretamente às vezes),
tiver perdido a linha de comentário correspondente, uma checagem baseada só em
`CurlTokenComment.parse` deixaria `delete` (sem `--force`) apagar um extractor ainda
referenciado — exatamente o "curl órfão de token" que essa checagem existe para
evitar. Por isso a checagem usa
`SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text)` (o mesmo padrão citado no
passo 1 de 3.4, mas aqui usado como foi desenhado — sobre um texto maior, buscando
ocorrências do placeholder completo `{{extractor:<id>}}`, não validando uma string
isolada) diretamente sobre o corpo de cada curl, em vez de (ou além de) parsear só o
comentário.

⚠️ **O workspace precisa já existir** — `Workspace.__init__`
(`har_reproducer/fs_io/workspace.py:11-22`) cria o diretório e as 8 subpastas
eagerly (`mkdir(parents=True, exist_ok=True)`) se não existirem, o que mascararia um
`--output` digitado errado como "workspace vazio" em vez de erro claro. Todo handler
de `extractor` replica o guard que `CliHandlers._prepare_replay_workspace`
(`har_reproducer/cli/cli_handlers.py:210-218`) já usa em `replay`/`optimize`: checar
`output_dir.exists()` (e, para ações que dependem de curls, que `curls/` não esteja
vazio) **antes** de instanciar `Workspace`, recusando com
`{"ok": false, "error": "workspace not found: <path>"}` em vez de criar um workspace
novo silenciosamente.

**Saída sempre em JSON em stdout** (decisão nova, não segue o padrão de `print` em
texto solto dos outros comandos): como o público-alvo declarado é um agente de IA,
cada ação imprime um objeto JSON único (`{"ok": bool, ...}` com o payload específico
da ação, e `{"ok": false, "error": "..."}` em qualquer recusa) em vez de mensagens de
texto livre — evita o agente ter que fazer parsing frágil de string. O código de saída
do processo continua seguindo a mesma convenção do resto da CLI (`sys.exit(1)` quando
`ok` é `false`, via `args.func` retornando `bool`, `har_reproducer/main.py:19-21`).

⚠️ **Essa promessa não é automática — dois pontos do caminho hoje escapariam dela se
nada for feito:**

1. **Erro de parsing do `argparse` em si** (ex.: `extractor get` sem `--token-id`,
   flag obrigatória faltando). `CliParser.build()` usa `argparse.ArgumentParser`/
   `add_subparsers`/`add_parser` sem nenhuma customização
   (`har_reproducer/cli/cli_parser.py:15-24`) — por padrão, isso imprime uso/erro em
   **texto puro no stderr** e sai com `sys.exit(2)` **antes** de qualquer handler
   rodar, quebrando "sempre JSON" logo no erro de uso mais comum. `main.py` precisa
   interceptar isso especificamente para o subcomando `extractor` — ex.: capturar
   `SystemExit`/erro de parsing ao redor de `parser.parse_args()` quando
   `sys.argv[1] == "extractor"` e emitir `{"ok": false, "error": "..."}` em vez de
   deixar o comportamento padrão do `argparse` vazar.
2. **Exceção não prevista dentro de um `handle_*`** (ex.: `AgentType(args.agent_type)`
   com um valor fora do enum levanta `ValueError` cru — `AgentType(str, Enum)`,
   `models/session.py:7-14`; ou uma `pydantic.ValidationError` ao montar `Extractor`
   com um campo inválido). Cada `handle_*` de `ExtractorCliHandlers` precisa de um
   `try/except Exception` de topo (ou um wrapper comum compartilhado por todas as
   ações) que converte qualquer exceção não antecipada em
   `{"ok": false, "error": str(exc)}` antes de imprimir — nunca deixar um traceback
   cru vazar para stderr.

Composição: `ExtractorCliHandlers` (`har_reproducer/cli/extractor_cli_handlers.py`),
nova classe paralela a `CliHandlers`, construída e despachada em `main.py` do mesmo
jeito que `CliHandlers` já é; `CliParser._build_extractor_subparser` adiciona o
subcomando aninhado. Nenhuma classe existente (`CliHandlers`, `CliParser`) tem método
removido ou alterado — só ganham, respectivamente, um método novo de composição e uma
chamada a mais em `build()`.

As dependências de cada `handle_*` (`Workspace`, `ScriptExecutor`,
`CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH)`,
`ExtractorMetadataStore(workspace)`, `ExtractorRunner(workspace, script_executor)`,
`ExtractorValidator(script_executor)`, `ExtractorCurlBinder(curl_token_comment)`) são
construídas dentro do próprio handler, a partir do `Workspace` já validado (guard
acima) — mesmo padrão que `CliHandlers.handle_replay`/`_build_replay_runner`
(`cli_handlers.py:115-138`) já usa hoje: essas dependências só existem depois que
`--output` é conhecido em tempo de execução, então não há como recebê-las por
construtor de `ExtractorCliHandlers` (que é montado uma vez em `main.py`, antes de
qualquer `--output` ser parseado).

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `ExtractorMetadataStore` | Método novo `list_all() -> List[Extractor]` (aditivo). |
| `ExtractorSampleResult` (novo, `har_reproducer/models/extractor_sample_result.py`) | Modelo Pydantic do resultado de rodar um extractor contra uma amostra — arquivo próprio, não em `session.py` (que só concentra os modelos consumidos pelo pipeline principal `run`/`replay`/`optimize`; `ExtractorSampleResult` é exclusivo do comando `extractor`). |
| `ExtractorValidator` (novo, `har_reproducer/reproduction/extractor_validator.py`) | `defines_expected_function`, `run_against_samples`. |
| `ExtractorCurlBinder` (novo, `har_reproducer/reproduction/extractor_curl_binder.py`) | `bind`, `unbind` sobre texto de curl já persistido. |
| `ExtractorCliHandlers` (novo, `har_reproducer/cli/extractor_cli_handlers.py`) | Um método por ação (`handle_list`, `handle_get`, `handle_create`, `handle_update`, `handle_delete`, `handle_bind`, `handle_unbind`, `handle_test`), orquestrando os componentes acima + `ExtractorRunner`/`ExtractorMetadataStore` já existentes. |
| `CliParser` | Método novo `_build_extractor_subparser`, chamado em `build()`. |
| `main.py` | Passa a construir/injetar `ExtractorCliHandlers` junto com `CliHandlers`. |
| `README.md` | Nova seção `### \`extractor\` — CRUD de extratores de um workspace`, mesmo padrão de tabela de flags das seções existentes (ver seção 6). |
| `ExtractorRunner`, `ExtractorTemplate`, `CurlTokenComment`, `Workspace`, `CandidateResolver` | Nenhuma mudança — reaproveitados como estão (seção 2). |

## 5. Casos de borda e comportamento de erro

- **`code` com nome de função divergente do esperado** (`extract_{IdentifierSanitizer.sanitize(token_id)}`)
  — `create`/`update` recusam antes de qualquer execução (`ExtractorValidator.defines_expected_function`),
  com `{"ok": false, "error": "..."}` citando o nome exato esperado. Comportamento
  **novo** (hoje isso falha silenciosamente como `NameError` → `None`).
- **`token_id` fornecido não é hex minúsculo** — `create`/`update` recusam via
  `re.fullmatch(r"[a-f0-9]+", token_id)` (passo 1 de 3.4; **não** via
  `SessionStore.TOKEN_PLACEHOLDER_PATTERN` diretamente, que exige o wrapper
  `{{extractor:...}}` e nunca casaria contra um `token_id` isolado — ver ⚠️ em 3.4).
  O CRUD não relaxa essa regra porque o charset já é assumido por todo o resto do
  pipeline de resolução de placeholder.
- **`create` com `token_id` já existente** — recusa (`{"ok": false, "error": "token_id already exists, use update"}`);
  não há fork automático como em `CandidateResolver._fork_token_id` — o CRUD é uma
  operação explícita, decidir sobrescrever é do chamador via `update`.
- **`origin_step` sem `real_responses/res_{step:04d}.json` correspondente** —
  **não** é detectado por um `ValueError` de `ExtractorRunner` (ele só levanta essa
  exceção quando `origin_step is None`, nunca quando o arquivo simplesmente não
  existe — seção 2). `create`/`update` checam `workspace.response_file(origin_step).exists()`
  explicitamente no passo 4 de 3.4, **antes** do passo de validação (passo 5), e recusam com
  `{"ok": false, "error": "response for step N not found"}` — distinto de "o código
  está errado" (que só aparece depois, no resultado de `run_against_samples`).
  Se `--origin-step` aponta para um step que só existe em `original_responses/` (nunca
  chegou a rodar de fato, ex. workspace criado via `dry`), essa mesma checagem já
  recusa a operação (não é tratado como caso especial — `create`/`update` só
  verificam `real_responses/`, nunca fazem fallback para `original_responses/`, ao
  contrário de `replay`, que tem essa distinção explícita via
  `_resolve_response_reference_dir`).
- **`delete` de um `token_id` ainda referenciado em algum `.curl.sh`** — recusa por
  padrão (`{"ok": false, "error": "still referenced by req_0006.curl.sh, ...", "referenced_by": [...]}`),
  evitando criar um "curl órfão de token" sem querer; `--force` ignora essa checagem e
  apaga mesmo assim (o curl fica com um placeholder que nunca mais resolve — o
  chamador assume o risco).
- **`bind` de um `token_id` inexistente** — recusa
  (`{"ok": false, "error": "token_id does not exist, use create first"}`) — ver 3.3;
  é a checagem que evita `bind` produzir um "curl órfão de token" no sentido inverso
  (placeholder sem extractor por trás).
- **`bind` cujo `literal_value` não aparece em nenhum token do curl** — recusa
  (`{"ok": false, "error": "literal_value not found in curl"}`); nenhuma escrita
  parcial.
- **`bind` de um `token_id` que já está vinculado a outro curl** — permitido (o
  mesmo token pode ser referenciado por múltiplos steps, é o comportamento já visto
  em curls reais do pipeline atual quando o mesmo valor aparece em mais de um
  request) — não é um erro, é o caso normal de reuso de extractor.
- **`bind` sobre uma linha de dependência que já carregava um sufixo de status**
  (`OriginStatusPhrase`/`ReplayStatusPhrase`, ex. um curl que já passou por `replay` e
  ganhou "probably static" ou "using literal captured value") — decisão consciente:
  `bind` sempre reescreve a linha do zero com `origin_status=None`, descartando
  qualquer sufixo anterior. Justificativa: o chamador está fornecendo uma correção
  ativa (presumivelmente um extractor validado agora), então o status antigo deixa de
  ser válido; se o operador quiser preservar um status observado por `replay`, não
  deve chamar `bind` nesse curl.
- **`unbind` de um `token_id` que não está de fato vinculado ao curl indicado** —
  recusa (`{"ok": false, "error": "token not bound to this curl"}`), sem tocar o
  arquivo.
- **`update` que muda `origin_step` de um token já vinculado a um ou mais curls** —
  os curls já vinculados continuam com o comentário de dependência apontando para o
  `origin_step` antigo até serem explicitamente revinculados (`bind` de novo); `update`
  não varre nem reescreve curls automaticamente (fora de escopo desta etapa — seria
  o mesmo tipo de "ação em massa sobre curls" que `bind`/`unbind` deliberadamente
  tratam um de cada vez). O chamador (agente de IA) precisa saber disso: mudar
  `origin_step` via `update` e não rebindar deixa a divergência descrita em 3.3
  reaparecer. `list`/`get` reportam `origin_step` atual do extractor junto com
  `referenced_by`, o que permite ao chamador perceber a divergência antes dela causar
  falha silenciosa num `replay`.
- **`--output` apontando para um diretório que não existe** — recusa em toda ação
  (`{"ok": false, "error": "workspace not found: <path>"}`) **antes** de instanciar
  `Workspace` (que criaria o diretório e as 8 subpastas silenciosamente — seção 3.6,
  ⚠️), mesmo guard que `replay`/`optimize` já aplicam via `_prepare_replay_workspace`.
- **Extractor órfão (`.meta.json` sem nenhum curl referenciando)** — `list`/`get`
  reportam isso na anotação (`"referenced_by": []`), mas não é um erro nem impede
  nenhuma ação — é informação para o chamador decidir se limpa (`delete`) ou não.
- **`test` sem persistir** — nunca escreve em `extractors/`; se `--token-id` for
  passado sem `--code-file`, usa o `code` já persistido (equivalente a "reverificar o
  que já existe contra amostras novas", útil pra confirmar que um extractor "correto
  mas que não funciona em todos os casos" realmente tem esse problema antes de mexer
  nele).
- **Amostra (`--sample`) que não é um JSON válido de resposta** — cada amostra falha
  isoladamente (`ExtractorSampleResult(error=...)`), sem abortar as demais amostras da
  mesma chamada — mesma filosofia de `ExtractorMetadataStore.list_all` (um item ruim
  não derruba a operação inteira).
- **Amostra que é JSON válido, mas não tem a forma de `StepResponse`** (ex.: o
  chamador aponta um arquivo com só o corpo puro da resposta, sem `headers`/`body`/
  `status_code` — confirmado em `har_reproducer/models/http.py` que é essa a forma
  que `real_responses/res_NNNN.json` sempre tem, e que os agentes concretos
  (`HeaderAgent`, `JSONPathAgent`, etc.) leem via `response.get("headers", {})`/
  `response.get("body", "")`) — sem validar isso, o extractor roda contra um dict
  que não tem as chaves esperadas e falha com um erro genérico de "valor não
  encontrado", indistinguível de "o `code` está errado". `run_against_samples`
  tenta `StepResponse.model_validate(...)` antes de rodar essa amostra e, se falhar,
  devolve `ExtractorSampleResult(error="sample is not a valid response structure
  (missing headers/body/status_code/...)")` — separado do erro de execução do
  extractor em si.
- **`.py` sem `.meta.json` correspondente, ou vice-versa** (o estado que o risco
  residual admitido em 3.4 pode produzir numa queda de processo entre os passos 6a/6b)
  — `list`/`get` só enxergam o que tem `.meta.json` (`list_all` faz glob em
  `extract_*.meta.json`, seção 3.1); um `.py` órfão sem `.meta.json` **não aparece**
  em nenhuma das duas ações — limitação conhecida, não resolvida nesta etapa (o
  chamador não tem hoje um jeito de descobrir esse `.py` solto via CRUD; só acharia
  olhando o diretório `extractors/` diretamente). `delete` de um `token_id` cujo
  `.meta.json` já não existe (mas o `.py` sim, ou nenhum dos dois) é idempotente —
  remove o que existir e não trata a ausência de qualquer um dos dois como erro.
  Por outro lado, `create` sobre um `token_id` cujo `.py` está órfão (sem
  `.meta.json`) é **seguro e intencional**: o passo 2 de 3.4 (`ExtractorMetadataStore.load(token_id)
  is None`) retorna `None` nesse estado — a mesma condição de "token_id livre" —, então
  `create` passa e sobrescreve o `.py` órfão como parte da escrita normal do passo 6;
  não é um caso não coberto, é o próprio `create` funcionando como o jeito de
  consertar esse estado.
- **Duas chamadas concorrentes de `create` para o mesmo `token_id`** — o fluxo da
  3.4 não usa lock de arquivo; há uma janela entre o passo 2 (checar que o
  `token_id` ainda não existe) e o passo 6 (escrita) em que duas chamadas
  concorrentes podem ambas passar pela checagem de inexistência antes de qualquer
  uma escrever, e a segunda escrita simplesmente sobrescreve a primeira sem erro —
  equivalente a um `update` silencioso em vez do "recusa" que `create` promete.
  Aceito como risco residual desta etapa (mesma categoria do risco já admitido em
  3.4 para o par de escritas `.py`/`.meta.json`) — um lock de arquivo real fica fora
  de escopo; se aparecer um caso real de uso concorrente do CRUD por múltiplos
  agentes, é assunto de spec futura.
- **`--expect` fornecido para `test`/`create`/`update`** — quando presente, cada
  amostra ganha `matches_expected: bool`; quando ausente, `matches_expected: null` (o
  chamador só recebe o valor extraído, sem veredito automático) — relevante quando o
  chamador (agente de IA) ainda não sabe qual é o valor certo e está usando `test`
  para explorar, não para confirmar.

## 6. Atualização do README

A seção `## Como executar` ganha uma subseção nova, no mesmo padrão de `### replay`/
`### optimize` (comando, tabela de flags, parágrafo de efeito e comportamento),
descrevendo o subcomando `extractor` e suas 8 ações — tabela da seção 3.6 desta spec
adaptada para o README, com o mesmo aviso de pré-requisito ("Requer um workspace já
criado por um `run` anterior") já usado em `replay`/`optimize`, e uma nota explícita
de que a saída é sempre um JSON em stdout (diferente do texto solto de `run`/`replay`/
`optimize`), já que o comando é desenhado para consumo por agente, não leitura humana
direta.

## Referência

Implementação segue `guia_de_estilo.md`/[[guia-de-estilo]] como padrão obrigatório —
tipagem explícita em toda variável/parâmetro/retorno, um conceito coeso por classe/
arquivo, dependências recebidas por construtor, guard clauses em vez de aninhamento,
zero comentários/docstrings (o código desta spec é ilustrativo, não literal — a
implementação segue o guia à risca, inclusive na nomenclatura final dos métodos
privados de cada classe nova).
