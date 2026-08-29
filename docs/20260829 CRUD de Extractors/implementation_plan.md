# Plano de Implementação — CRUD de Extractors

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `ExtractorSampleResult`: modelo do resultado de rodar um extractor contra uma amostra

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/models/extractor_sample_result.py` (novo), `har_reproducer/models/__init__.py` (exportar).

**Contexto:**
A ação `test` e o fluxo de validação de `create`/`update` (spec seção 3.2, 3.4) precisam
reportar, por amostra testada, se o extractor rodou, o que devolveu, e se bateu com um
valor esperado. Hoje não existe nenhum modelo para isso — é conteúdo novo, exclusivo do
comando `extractor`, por isso vive em arquivo próprio (spec seção 4), não em
`models/session.py` (que só concentra os modelos consumidos pelo pipeline principal
`run`/`replay`/`optimize`).

**Estado atual:**
- `har_reproducer/models/__init__.py` exporta todos os modelos do pacote a partir de
  `analysis.py`, `config.py`, `criteria.py`, `execution.py`, `http.py`, `session.py`.
- Não existe nenhum modelo de "resultado de execução de amostra".

**Estado esperado depois:**
- Novo arquivo `har_reproducer/models/extractor_sample_result.py`:
  ```python
  class ExtractorSampleResult(BaseModel):
      sample_label: str
      output: Optional[str] = None
      error: Optional[str] = None
      matches_expected: Optional[bool] = None
  ```
  - `sample_label` identifica a amostra dentro de uma chamada de `run_against_samples`
    (ex.: `"origin_step"` para a resposta do `origin_step`, ou o nome do arquivo/label
    de um `--sample` extra).
  - `output` é o valor extraído (stdout do script), `None` se a execução falhou.
  - `error` é a mensagem de erro (JSON inválido, forma inesperada, timeout, mismatch de
    execução), `None` em caso de sucesso.
  - `matches_expected` é `True`/`False` quando um valor esperado foi fornecido para
    aquela amostra (via `captured_value` ou `--expect`), `None` quando não havia valor
    esperado para comparar (spec seção 5, "`--expect` fornecido para `test`/`create`/`update`").
- `har_reproducer/models/__init__.py` passa a importar e reexportar `ExtractorSampleResult`
  (mesmo padrão dos demais modelos), mantendo `__all__` em ordem alfabética.

**Critérios de aceite:**
- [ ] `ExtractorSampleResult(sample_label="origin_step", output="abc", error=None, matches_expected=True)` serializa via `model_dump_json()` e desserializa de volta via `model_validate_json()` preservando todos os campos.
- [ ] `ExtractorSampleResult(sample_label="x")` (só o campo obrigatório) tem `output`, `error`, `matches_expected` todos `None` por padrão.
- [ ] `from har_reproducer.models import ExtractorSampleResult` funciona sem importar o submódulo diretamente.
- [ ] Nenhum modelo existente (`Extractor`, `DynamicToken`, etc.) muda de comportamento — `__all__` só ganha uma entrada nova.

## [T02] — `ExtractorMetadataStore`: `list_all()` enumera todos os extractors de um workspace

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/reproduction/extractor_metadata_store.py` (`ExtractorMetadataStore`).

**Contexto:**
`ExtractorMetadataStore` hoje só sabe carregar/salvar um extractor por vez, dado seu
`token_id` (spec seção 2). As ações `list`/`get`/`delete`/`bind` do CRUD (spec seção
3.6) precisam enumerar todos os extractors de um workspace para anotar curls
referenciados, então é preciso um método de listagem que não existe hoje.

**Estado atual (`extractor_metadata_store.py:8-24`):**
```python
class ExtractorMetadataStore:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace: Workspace = workspace

    def load(self, token_id: str) -> Optional[Extractor]:
        meta_file: Path = self.workspace.extractor_meta_file(token_id)
        if not meta_file.exists():
            return None
        try:
            return Extractor.model_validate_json(meta_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[AVISO] Falha ao carregar metadado do extractor '{token_id}': {e}")
            return None

    def save(self, extractor: Extractor) -> None:
        meta_file: Path = self.workspace.extractor_meta_file(extractor.token_id)
        meta_file.write_text(extractor.model_dump_json(indent=2), encoding="utf-8")
```

**Estado esperado depois:**
- Novo método público `list_all(self) -> List[Extractor]`, aditivo — nenhuma
  assinatura existente muda:
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
  ⚠️ Reaproveita `self.load()` — herda o mesmo tratamento de erro (`print` de aviso e
  `None` em caso de `.meta.json` corrompido), então um arquivo inválido é pulado, não
  derruba a listagem inteira (spec seção 3.1). `sorted(...)` garante ordem
  determinística (por nome de arquivo) — relevante para a saída JSON de `list` ser
  estável entre chamadas.
- `SilentExtractorMetadataStore` (mesma classe, `save` sobrescrito para não persistir)
  **não precisa** sobrescrever `list_all` — é uma operação de leitura, não afetada pelo
  comportamento "silencioso" de escrita usado em `optimize`.

**Critérios de aceite:**
- [ ] Workspace sem nenhum `.meta.json` em `extractors/` → `list_all()` retorna `[]`.
- [ ] Workspace com 2 `.meta.json` válidos → `list_all()` retorna os 2 `Extractor`, em ordem determinística (por nome de arquivo).
- [ ] Workspace com 1 `.meta.json` válido + 1 corrompido (JSON inválido) → `list_all()` retorna só o válido, sem levantar exceção (o `[AVISO]` de `load()` é impresso, mas a chamada não falha).
- [ ] `load(token_id)` e `save(extractor)` continuam se comportando exatamente como antes (não regride nenhum teste existente de `test_extractor_metadata_store.py`).

## [T03] — `ExtractorValidator`: valida nome de função e roda `code` contra múltiplas amostras sem persistir

**Depende de:** [T01] (usa `ExtractorSampleResult`).
**Arquivos envolvidos:** `har_reproducer/reproduction/extractor_validator.py` (novo), `har_reproducer/reproduction/__init__.py` (exportar).

**Contexto:**
Hoje a única verificação de "esse `code` roda e devolve o valor certo" é
`BaseAgent._verify_code`/`_write_temp_script`/`_execute_script`
(`har_reproducer/agents/base_agent.py:174-177, 179-187, 189-202`), amarrada a uma
instância de agente e a uma única amostra por chamada (spec seção 3.2). O CRUD precisa
da mesma verificação, isolada de qualquer `Agent`, capaz de rodar contra **múltiplas**
amostras numa só chamada (spec seção 3.2, ⚠️ — é o que endereça o problema #1 da spec,
seção 1: extractor que funciona numa amostra e falha em outras).

**Estado atual:**
- `BaseAgent._write_temp_script` (`base_agent.py:179-187`) sempre grava no caminho
  determinístico `workspace.temp_extractor_file(self.safe_token_id)` — um arquivo por
  `token_id`, não por amostra.
- `ExtractorTemplate.render_temp_script(safe_token_id, code, response_sample)`
  (`extractor_template.py:12-34`) já embute a amostra inline como `repr()` de dict
  Python — é a variante reaproveitada aqui, sem mudança.
- `StepResponse` (`har_reproducer/models/http.py:22-31`) é a forma real de
  `real_responses/res_NNNN.json` (`status_code`, `headers`, `cookies`,
  `cookie_attributes`, `body`, `body_mime`, `redirect_url`, `skipped`, `skip_reason`).

**Estado esperado depois:**
- Nova classe `ExtractorValidator`, construída com `workspace: Workspace` e
  `script_executor: ScriptExecutor` recebidos por construtor:
  - `defines_expected_function(self, token_id: str, code: str) -> bool` — usa
    `IdentifierSanitizer.sanitize(token_id)` para montar o nome esperado
    (`extract_<safe_token_id>`) e confere, via regex ancorada em início de linha
    (`re.MULTILINE`), que `code` define uma função com esse nome exato. Endereça a
    seção 5 da spec ("`code` com nome de função divergente do esperado").
  - `run_against_samples(self, token_id: str, code: str, samples: Dict[str, Dict[str, Any]], expected_values: Optional[Dict[str, str]] = None) -> List[ExtractorSampleResult]`
    — para cada `(label, response_dict)` em `samples`, nesta ordem:
    1. Valida a forma da amostra via `StepResponse.model_validate(response_dict)`; se
       levantar `ValidationError`, produz
       `ExtractorSampleResult(sample_label=label, error="sample is not a valid response structure (missing headers/body/status_code/...)")`
       e **não tenta rodar** essa amostra (spec seção 5 — "amostra que é JSON válido
       mas não tem a forma de `StepResponse`"). A instância validada é descartada em
       seguida — é o `response_dict` original (não a instância Pydantic) que segue
       para `render_temp_script`, porque o `code` gerado acessa a resposta via
       `.get(...)` (spec seção 3.4, passo 5).
    2. Se a forma bater, escreve um script temporário via
       `ExtractorTemplate.render_temp_script(safe_token_id, code, response_dict)` num
       caminho **único por `(token_id, label)`** — nunca o caminho fixo de
       `workspace.temp_extractor_file(safe_token_id)` que `BaseAgent` usa, que
       colidiria entre amostras da mesma chamada ou entre chamadas concorrentes para
       o mesmo `token_id` (spec seção 3.2, ⚠️). Sugestão de caminho:
       `workspace.temp_extractor_file(f"{safe_token_id}__{index}")`, onde `index` é a
       posição da amostra na iteração (garante unicidade sem depender do conteúdo de
       `label`, que pode ter caracteres não seguros para nome de arquivo).
    3. Executa via `self.script_executor.run(script_path, 5)` (mesmo timeout de 5s
       usado em `BaseAgent`/`ExtractorRunner`); monta o `ExtractorSampleResult`
       (`output` = stdout limpo em caso de sucesso; `error` = stderr/"timeout"/mensagem
       de mismatch em caso de falha; `matches_expected` = comparação com
       `expected_values.get(label)` quando fornecido, `None` caso contrário).
    4. Remove o script temporário **incondicionalmente** (sucesso, falha ou exceção) —
       ao contrário de `BaseAgent`, cujo cleanup só acontece no caminho de falha do
       TDD loop; aqui não há um "loop" externo que reaproveite o arquivo depois (spec
       seção 3.2).
- `har_reproducer/reproduction/__init__.py` passa a exportar `ExtractorValidator`.

**Critérios de aceite:**
- [ ] `defines_expected_function("deadbeef", "def extract_t_deadbeef(response):\n    return 'x'\n")` → `True`.
- [ ] `defines_expected_function("deadbeef", "def extract_wrong_name(response):\n    return 'x'\n")` → `False`.
- [ ] `run_against_samples` com uma amostra cuja forma não bate com `StepResponse` (ex.: `{"foo": "bar"}`) devolve `ExtractorSampleResult(error=...)` sem tentar executar nada (nenhum script temporário é gravado para essa amostra).
- [ ] `run_against_samples` com 2 amostras válidas (uma onde o `code` acerta o valor, outra onde erra) devolve 2 `ExtractorSampleResult` distintos, cada um com seu próprio `output`/`error`, sem uma amostra sobrescrever o arquivo temporário da outra (verificável rodando ambas e checando que os dois resultados batem com o `code` fornecido, não com um resultado cruzado).
- [ ] Depois de qualquer chamada a `run_against_samples` (sucesso ou falha), nenhum arquivo temporário residual sobra em `temp_extractors/`.
- [ ] `expected_values={"origin_step": "certo"}` com uma amostra rotulada `"origin_step"` que extrai `"certo"` → `matches_expected=True` nesse resultado; se extrair outro valor → `matches_expected=False`; amostra sem entrada em `expected_values` → `matches_expected=None`.

## [T04] — `ExtractorCurlBinder`: vincula/desvincula um `token_id` a um `.curl.sh` já persistido

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/reproduction/extractor_curl_binder.py` (novo), `har_reproducer/reproduction/__init__.py` (exportar).

**Contexto:**
Hoje a única forma de um curl ganhar `{{extractor:<id>}}` e a linha de dependência é
`CurlGenerator.generate()` (`har_reproducer/reproduction/curl_generator.py:15-21`),
que sempre reconstrói o curl inteiro a partir de um `StepRequest` em memória — nunca
edita um `.curl.sh` já escrito em disco (spec seção 3.3). O CRUD precisa editar um
curl persistido diretamente, preservando tudo que não muda.

**Estado atual:**
- `CurlTokenComment.format_dependency_line(token_id, origin_step, origin_status=None) -> str`
  (`har_reproducer/replay/curl_token_comment.py:41-48`) já gera a linha
  `# [Token <id> comes from response of step <n>]`, reaproveitada tal como está.
- `CurlTokenComment.DEPENDENCY_PATTERN` (`curl_token_comment.py:26-31`) já sabe casar
  essa linha por `token_id` — reaproveitado para achar/substituir a linha certa.
- Todo `.curl.sh` persistido começa com `#!/bin/bash\n` (`ExtractorTemplate.render_bash_script`,
  `har_reproducer/engines/engine.py:124-125`), seguido das linhas de comentário
  (`# [Token ...]`/`# [Static ...]`/`# [Unresolved ...]`) e só então o bloco `curl -X ... \`.
- `CookieJarCurlOverride.apply` (`cookie_jar_curl_override.py:14-23`) é o precedente de
  estilo (shlex, nunca regex de texto livre), mas tokeniza o **texto inteiro**
  (`shlex.split(curl_resolved, comments=True)`) — seguro lá só porque o resultado é
  efêmero (nunca escrito de volta no `.curl.sh`, spec seção 3.3, ⚠️). Aqui o resultado
  é persistido, então as linhas `#`-prefixadas precisam ser preservadas à parte,
  nunca passadas pelo tokenizador.

**Estado esperado depois:**
- Nova classe `ExtractorCurlBinder`, construída com `curl_token_comment: CurlTokenComment`
  recebido por construtor:
  - `_split_header_and_body(self, curl_text: str) -> Tuple[List[str], str]` (privado)
    — separa as linhas iniciais que começam com `#` (shebang + comentários de
    dependência) do restante (o bloco `curl -X ...`), por posição (todas as linhas
    `#`-prefixadas até a primeira linha que não começa com `#`), sem usar shlex nessa
    etapa.
  - `bind(self, curl_text: str, token_id: str, origin_step: int, literal_value: str) -> Tuple[str, int]`
    — tokeniza **só o corpo** via `shlex.split`, substitui toda ocorrência exata de
    `literal_value` como substring dentro de cada token por
    `"{{extractor:<token_id>}}"` (contando as substituições feitas em cada token via
    `token.count(literal_value)` antes de substituir), remonta o corpo (`shlex.join`
    dos tokens resultantes — aceito como reformatação em linha única do curl,
    trade-off deliberado: `shlex.join` não preserva a formatação multi-linha
    `\`-continuada original, mas o curl resultante continua funcionalmente idêntico e
    mais fácil de diffar/grepar programaticamente por um agente de IA). Insere ou
    substitui, entre as linhas de comentário preservadas, a linha de dependência deste
    `token_id` (`format_dependency_line(token_id, origin_step, origin_status=None)` —
    sempre com `origin_status=None`, resetando qualquer sufixo de status que a linha já
    carregasse, spec seção 5). Devolve `(novo_texto_completo, contagem_de_substituicoes)`.
  - `unbind(self, curl_text: str, token_id: str, replacement_value: str) -> Tuple[str, int]`
    — mesma separação header/corpo; troca **todas** as ocorrências exatas de
    `"{{extractor:<token_id>}}"` no corpo por `replacement_value` (espelhando `bind`,
    que pode ter criado mais de uma ocorrência — spec seção 3.3, ⚠️), contando as
    trocas; remove só a linha de dependência deste `token_id` das linhas de
    comentário preservadas, mantendo as demais (`# [Static ...]`, `# [Unresolved ...]`,
    linhas de dependência de outros tokens, o shebang) intactas. Devolve
    `(novo_texto_completo, contagem_de_substituicoes)`.
- `har_reproducer/reproduction/__init__.py` passa a exportar `ExtractorCurlBinder`.

**Critérios de aceite:**
- [ ] `bind` num curl com `-H 'X-Plain: SEGREDO123'` e `literal_value="SEGREDO123"` produz um curl cujo corpo contém `-H 'X-Plain: {{extractor:<id>}}'` e devolve contagem `1`.
- [ ] `bind` num curl onde `literal_value` aparece em 2 tokens diferentes (ex.: um header e um valor de cookie iguais por coincidência) substitui as 2 ocorrências e devolve contagem `2`.
- [ ] `bind` num curl onde `literal_value` não aparece em nenhum token devolve contagem `0` e o texto do curl inalterado (exceto talvez a linha de dependência, que a spec deixa a cargo do handler decidir se ainda insere com 0 substituições — ver T08, que trata isso como recusa).
- [ ] Depois de `bind`, o texto resultante ainda contém o shebang `#!/bin/bash` e todas as linhas de comentário que não são a deste `token_id` (ex.: `# [Static ...]`, linha de dependência de outro `token_id`), inalteradas.
- [ ] `bind` sobre uma linha de dependência já existente para este `token_id` com sufixo de status (`OriginStatusPhrase`/`ReplayStatusPhrase`) reescreve a linha sem o sufixo (reset deliberado).
- [ ] `unbind` depois de um `bind` que criou N ocorrências do placeholder restaura as N ocorrências para `replacement_value` e devolve contagem `N`; a linha de dependência deste `token_id` desaparece do texto resultante; outras linhas de comentário permanecem.
- [ ] `CurlTokenComment.parse(novo_texto)` depois de `bind` inclui `{token_id: origin_step}`; depois do `unbind` correspondente, não inclui mais esse `token_id`.

## [T05] — `ExtractorCliHandlers`: esqueleto, guard de workspace, envelope JSON, `list`/`get`, e roteamento de erros do `argparse` para JSON

**Depende de:** [T02] (usa `ExtractorMetadataStore.list_all`).
**Arquivos envolvidos:** `har_reproducer/cli/extractor_cli_handlers.py` (novo), `har_reproducer/cli/cli_parser.py` (`CliParser`), `har_reproducer/main.py`, `har_reproducer/cli/__init__.py` (exportar).

**Contexto:**
Esta é a task que estabelece toda a infraestrutura compartilhada pelas 8 ações do
comando `extractor` (spec seção 3.6): o guard que recusa um `--output` inexistente
antes de instanciar `Workspace`, o envelope de saída sempre-JSON (inclusive quando o
`argparse` falha o parsing ou quando uma exceção não prevista escapa de um handler), e
as duas ações mais simples (`list`/`get`) para provar essa infraestrutura de ponta a
ponta antes das ações que escrevem (T06-T09).

**Estado atual:**
- `Workspace.__init__` (`har_reproducer/fs_io/workspace.py:11-22`) cria o diretório e
  as 8 subpastas eagerly (`mkdir(parents=True, exist_ok=True)`) se não existirem — sem
  guard, um `--output` digitado errado vira um workspace vazio silencioso.
- `CliHandlers._prepare_replay_workspace` (`har_reproducer/cli/cli_handlers.py:210-218`)
  já resolve esse mesmo problema para `replay`/`optimize`:
  ```python
  @staticmethod
  def _prepare_replay_workspace(output_dir: Path) -> Workspace:
      if not output_dir.exists():
          raise ValueError(f"Workspace directory does not exist: {output_dir}")
      workspace: Workspace = Workspace(output_dir)
      if not any(workspace.curls.glob("req_*.curl.sh")):
          raise ValueError(f"Workspace has no curl files: {output_dir}")
      return workspace
  ```
- `CliParser.build()` (`har_reproducer/cli/cli_parser.py:15-24`) usa
  `argparse.ArgumentParser`/`add_subparsers`/`add_parser` sem nenhuma customização —
  um erro de parsing (flag obrigatória faltando) imprime uso/erro em texto puro no
  stderr e sai com `sys.exit(2)` antes de qualquer handler rodar.
- `main.py` (`har_reproducer/main.py:11-21`):
  ```python
  def main() -> None:
      load_dotenv()
      handlers: CliHandlers = CliHandlers(engine_factory=EngineFactory, har_parser=HARParser)
      cli_parser: CliParser = CliParser(handlers)
      parser: ArgumentParser = cli_parser.build()
      args: Namespace = parser.parse_args()
      success: bool = args.func(args)
      if not success:
          sys.exit(1)
  ```
- `tests/support/cli_invoker.py` já existe e roda `main()` de ponta a ponta capturando
  stdout/stderr/exceção (via `sys.argv` trocado) — é o jeito que os testes de CLI deste
  projeto já verificam handlers (`tests/unit/test_cli_handlers.py`), reaproveitado aqui
  sem mudança.

**Estado esperado depois:**
- Nova classe `ExtractorCliHandlers`, sem dependências no construtor (mesmo padrão de
  `CliHandlers` — ver `cli_handlers.py:33-41`, que também não recebe workspace-specific
  deps no construtor, só monta por chamada):
  - Método privado `_prepare_workspace(output_dir: Path, require_curls: bool) -> Workspace`
    — mesmo guard de `_prepare_replay_workspace`, mas com `require_curls` opcional
    (ações que não dependem de curls existentes, como `list` sobre um workspace recém-
    criado por `run --mode dry`, não precisam exigir `.curl.sh`; por default `True`
    para as ações que envolvem curl).
  - Método privado `_emit(payload: Dict[str, Any]) -> bool` — `print(json.dumps(payload))`
    e devolve `bool(payload.get("ok", False))`, único ponto de saída para stdout de
    toda ação.
  - Método privado `_run_safely(self, action: Callable[[], Dict[str, Any]]) -> bool` —
    chama `action()`; se levantar qualquer `Exception` (inclusive `ValueError` do guard
    de workspace), captura e `return self._emit({"ok": False, "error": str(exc)})`; se
    `action()` devolver normalmente, `return self._emit(payload)` (o payload já inclui
    `"ok": True/False` conforme o resultado de negócio, ex.: recusa explícita como
    "token_id already exists" não é uma exceção Python, é um retorno normal com
    `ok=False` — reserva exceção só para falha genuinamente inesperada, guia de estilo).
  - `handle_list(self, args: Namespace) -> bool` — `_run_safely` de uma função que
    prepara o workspace, chama `ExtractorMetadataStore(workspace).list_all()`, anota
    cada extractor com os `.curl.sh` que o referenciam (glob de `workspace.curls` +
    `SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text)` sobre o corpo de cada
    um — não só `CurlTokenComment.parse`, spec seção 3.6 ⚠️, já que um curl editado à
    mão pode ter o placeholder sem a linha de comentário), e devolve
    `{"ok": True, "extractors": [...]}`.
  - `handle_get(self, args: Namespace) -> bool` — mesma lógica de anotação, mas para um
    único `token_id`; `{"ok": False, "error": "extractor not found: <id>"}` se
    `load(token_id)` devolver `None`.
- `CliParser` ganha `_build_extractor_subparser(self, subparsers)`, chamado em
  `build()` junto dos outros quatro `_build_*_subparser`. Cria o subcomando
  `extractor` com um `add_subparsers(dest="action", required=True)` aninhado; nesta
  task, registra só as ações `list` (`--output`) e `get` (`--output --token-id`),
  apontando para `extractor_handlers.handle_list`/`handle_get`.
- `main.py` ganha o roteamento de erro do `argparse` para JSON, **só quando o primeiro
  argumento é `"extractor"`**:
  ```python
  def main() -> None:
      load_dotenv()
      handlers: CliHandlers = CliHandlers(engine_factory=EngineFactory, har_parser=HARParser)
      extractor_handlers: ExtractorCliHandlers = ExtractorCliHandlers()
      cli_parser: CliParser = CliParser(handlers, extractor_handlers)
      parser: ArgumentParser = cli_parser.build()
      if len(sys.argv) > 1 and sys.argv[1] == "extractor":
          success: bool = _dispatch_extractor(parser, sys.argv[1:])
      else:
          args: Namespace = parser.parse_args()
          success = args.func(args)
      if not success:
          sys.exit(1)
  ```
  ⚠️ `main.py` é um arquivo sem classe (isenção documentada do guia de estilo só para
  o ponto de entrada do módulo) — a função auxiliar `_dispatch_extractor` segue o
  mesmo padrão que já existe ali (função de módulo, não método de classe):
  ```python
  def _dispatch_extractor(parser: ArgumentParser, argv: List[str]) -> bool:
      with contextlib.redirect_stderr(io.StringIO()):
          try:
              args: Namespace = parser.parse_args(argv)
          except SystemExit:
              print(json.dumps({"ok": False, "error": "invalid arguments for extractor command"}))
              return False
      return args.func(args)
  ```
  `redirect_stderr` suprime o texto de uso/erro que o `argparse` imprimiria por
  padrão (spec seção 3.6, ⚠️ — "sem deixar o comportamento padrão do argparse
  vazar"); a exceção não prevista dentro de `args.func(args)` já é tratada por
  `ExtractorCliHandlers._run_safely`, não precisa de outro `try/except` aqui.
- `CliParser.__init__` passa a receber `extractor_handlers: ExtractorCliHandlers` além
  de `handlers: CliHandlers` (dependência por construtor, guia de estilo).

**Critérios de aceite:**
- [ ] `extractor list --output <dir-inexistente>` devolve `{"ok": false, "error": "Workspace directory does not exist: <dir>"}` em stdout, sem criar o diretório.
- [ ] `extractor list --output <workspace-vazio-sem-curls>` (se `require_curls=True` for o default de `list`) devolve `{"ok": false, "error": "..."}`; se a task decidir que `list` não exige curls, documentar essa escolha nos critérios e testar o caminho de sucesso com 0 extractors (`{"ok": true, "extractors": []}`).
- [ ] `extractor list --output <workspace com 2 extractors, 1 referenciado por um curl>` devolve `{"ok": true, "extractors": [...]}` com o campo de referência (`referenced_by`) correto para os dois.
- [ ] `extractor get --output <dir> --token-id <inexistente>` devolve `{"ok": false, "error": "extractor not found: <id>"}`.
- [ ] `extractor get --output <dir>` (sem `--token-id`, flag obrigatória ausente) devolve, via stdout, `{"ok": false, "error": "invalid arguments for extractor command"}` e **nenhum** texto de uso do `argparse` aparece em stdout nem quebra o teste por escrever em stderr sem tratamento (usar `CliInvoker`, que já captura ambos).
- [ ] `parse`/`run`/`replay`/`optimize` continuam funcionando exatamente como antes (não regride `test_cli_handlers.py` nem os testes de `parse`/`run`) — o roteamento especial em `main.py` só se aplica quando `sys.argv[1] == "extractor"`.

## [T06] — `ExtractorCliHandlers`: `handle_create`/`handle_update` (validação completa antes de persistir)

**Depende de:** [T03] (`ExtractorValidator`), [T05] (esqueleto/guard/envelope).
**Arquivos envolvidos:** `har_reproducer/cli/extractor_cli_handlers.py`, `har_reproducer/cli/cli_parser.py`.

**Contexto:**
Esta task implementa o fluxo central da spec (seção 3.4): validar um extractor
fornecido (por humano ou agente de IA) contra pelo menos uma resposta real antes de
persistir, sem nunca deixar um `.py` quebrado no disco quando a validação reprova.

**Estado atual:**
- Nenhum handler de escrita existe ainda (só `list`/`get`, de T05).
- `ExtractorRunner.run()` (`extractor_runner.py:18-21`) escreve o `.py` antes de
  comparar — **não** é reaproveitado aqui como validação (spec seção 2, 3.4).
- `Workspace.response_file(index)` (`workspace.py:49-50`) devolve o `Path` sem checar
  existência.
- `ExtractorTemplate.render_script(safe_token_id, code, step_index)`
  (`extractor_template.py:37-57`) é a variante final persistida, reaproveitada
  diretamente (não via `ExtractorRunner.run()`) para escrever o `.py` só depois da
  validação aprovada.

**Estado esperado depois (spec seção 3.4, os 7 passos — 0 a 6):**
- `handle_create(self, args: Namespace) -> bool` e `handle_update(self, args: Namespace) -> bool`
  compartilham um método privado `_create_or_update(self, args: Namespace, is_update: bool) -> Dict[str, Any]`
  que executa, nesta ordem exata:
  - **0 (só `update`):** `ExtractorMetadataStore.load(args.token_id)`; `None` →
    recusa `"token_id does not exist, use create"`. Constrói o `Extractor` final
    mesclando os campos informados por flag (`--code-file`, `--agent-type`,
    `--origin-step`, `--captured-value`, `--verified`) sobre os valores já
    persistidos — campo omitido mantém o valor carregado. Todos os passos seguintes
    operam sobre esse objeto mesclado, nunca sobre `args` cru.
  - **1:** `re.fullmatch(r"[a-f0-9]+", token_id)` — recusa se não casar. ⚠️ **Não**
    reaproveitar `SessionStore.TOKEN_PLACEHOLDER_PATTERN` diretamente aqui — esse
    padrão exige o wrapper `{{extractor:...}}` e nunca casaria contra um `token_id`
    isolado (spec seção 3.4, ⚠️ detalhado).
  - **2 (só `create`):** `ExtractorMetadataStore.load(token_id) is None` — recusa
    `"token_id already exists, use update"` se já existir.
  - **3:** `ExtractorValidator.defines_expected_function(token_id, code)` — recusa
    citando o nome exato esperado se `False`.
  - **4:** `workspace.response_file(origin_step).exists()` — recusa
    `"response for step N not found"` se `False`, sem tentar rodar nada.
  - **5:** carrega o JSON de `response_file` como dict cru; monta o dict de amostras
    (`{"origin_step": response_dict}` + uma entrada por `--sample` extra, se a CLI
    escolher expor isso também em `create`/`update` — opcional, a spec só exige a
    amostra do `origin_step`); chama `ExtractorValidator.run_against_samples(...)`
    com `expected_values={"origin_step": captured_value}` quando `captured_value`
    estiver definido, mesclado com `--expect` se fornecido. Se o resultado da amostra
    `"origin_step"` tiver `error` ou `matches_expected is False`, recusa — nada foi
    escrito em `extractors/` até aqui.
  - **6:** escreve `extract_<token_id>.py` via `ExtractorTemplate.render_script(...)`
    diretamente (não `ExtractorRunner.run()`) e, imediatamente em seguida,
    `ExtractorMetadataStore.save(extractor)`.
- Payload de sucesso: `{"ok": True, "token_id": ..., "verified": ..., "samples": [...]}`
  (os `ExtractorSampleResult` do passo 5, para o chamador ver o que foi validado).
- `CliParser._build_extractor_subparser` ganha as ações `create`
  (`--output --token-id --code-file --agent-type --origin-step [--captured-value] [--verified]`)
  e `update` (mesmas flags, todas opcionais exceto `--output --token-id`).

**Critérios de aceite:**
- [ ] `create` com `code` cuja função tem nome errado → recusa antes de tocar `real_responses/` ou `extractors/` (nenhum arquivo novo é criado).
- [ ] `create` com `origin_step` cujo `real_responses/res_NNNN.json` não existe → recusa `"response for step N not found"`, nenhum arquivo escrito.
- [ ] `create` com `code` que extrai um valor diferente de `--captured-value` → recusa; **nenhum** `.py` novo aparece em `extractors/` (prova de que a ordem evita o `.py` quebrado da versão ingênua via `ExtractorRunner.run()`).
- [ ] `create` bem-sucedido escreve `.py` **e** `.meta.json` na mesma chamada; `ExtractorMetadataStore.load(token_id)` depois devolve o extractor persistido; `ExtractorRunner.run_existing(token_id, ...)` roda e bate com o valor esperado.
- [ ] `create` com `token_id` já existente → recusa `"token_id already exists, use update"`, sem sobrescrever o extractor anterior.
- [ ] `update` só com `--code-file` (sem `--origin-step`) sobre um extractor existente usa o `origin_step` já persistido no passo 4, não falha por `origin_step` ausente.
- [ ] `update` com `token_id` inexistente → recusa `"token_id does not exist, use create"`.
- [ ] `update` que muda só `captured_value` (mantendo o `code` antigo) preserva o `code`/`agent_type`/`origin_step` anteriores no `.meta.json` resultante.

## [T07] — `ExtractorCliHandlers`: `handle_delete` (checagem de referência via placeholder no corpo do curl)

**Depende de:** [T05].
**Arquivos envolvidos:** `har_reproducer/cli/extractor_cli_handlers.py`, `har_reproducer/cli/cli_parser.py`.

**Contexto:**
`delete` remove `.py` + `.meta.json`, mas só se nenhum `.curl.sh` do workspace ainda
referenciar o `token_id` — a menos que `--force` (spec seção 3.6, seção 5).

**Estado atual:**
- Nenhum handler de remoção existe ainda.
- `CurlTokenComment.parse(curl_text)` (`curl_token_comment.py:71-75`) só lê as linhas
  de comentário — **não** detecta um placeholder que sobreviveu no corpo do curl sem
  a linha de comentário correspondente (spec seção 3.6, ⚠️ detalhado).

**Estado esperado depois:**
- `handle_delete(self, args: Namespace) -> bool` — prepara o workspace, glob de
  `workspace.curls.glob("req_*.curl.sh")`, para cada curl roda
  `SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text)` sobre o texto inteiro
  (não só `CurlTokenComment.parse`) e coleta os que contêm `token_id`. Se a lista não
  estiver vazia e `args.force` for `False`, recusa
  `{"ok": False, "error": "still referenced by ...", "referenced_by": [...]}`. Caso
  contrário (lista vazia, ou `--force`), remove `workspace.extractor_file(token_id)`
  e `workspace.extractor_meta_file(token_id)` se existirem — `unlink(missing_ok=True)`
  em cada um, idempotente mesmo se só um dos dois existir (spec seção 5, "`.py` sem
  `.meta.json` correspondente").
- `CliParser._build_extractor_subparser` ganha a ação `delete`
  (`--output --token-id [--force]`, `--force` como `action="store_true"`).

**Critérios de aceite:**
- [ ] `delete` de um `token_id` referenciado por um curl (via placeholder no corpo) sem `--force` → recusa, `.py`/`.meta.json` continuam existindo.
- [ ] `delete` de um `token_id` cujo placeholder está no corpo do curl mas a linha de comentário foi removida manualmente → ainda assim recusa (prova de que a checagem usa o placeholder, não só `CurlTokenComment.parse`).
- [ ] `delete --force` de um `token_id` referenciado remove `.py`/`.meta.json` mesmo assim.
- [ ] `delete` de um `token_id` não referenciado por nenhum curl remove ambos os arquivos sem precisar de `--force`.
- [ ] `delete` de um `token_id` cujo `.meta.json` já não existe (mas o `.py` sim) remove o `.py` sem erro (idempotente).
- [ ] `delete` de um `token_id` totalmente inexistente (nem `.py` nem `.meta.json`) não levanta exceção — devolve sucesso (nada a remover) ou uma mensagem clara, a task escolhe qual, desde que não seja um traceback cru.

## [T08] — `ExtractorCliHandlers`: `handle_bind`/`handle_unbind`

**Depende de:** [T04] (`ExtractorCurlBinder`), [T05].
**Arquivos envolvidos:** `har_reproducer/cli/extractor_cli_handlers.py`, `har_reproducer/cli/cli_parser.py`.

**Contexto:**
`bind` vincula um `token_id` já existente a um `.curl.sh`, derivando `origin_step` do
`Extractor` persistido (nunca uma flag do usuário — spec seção 3.3, ⚠️, para evitar a
divergência entre o `origin_step` gravado no `.py` e o do comentário do curl,
detalhada na spec). `unbind` desfaz.

**Estado atual:**
- Nenhum handler de vínculo existe ainda; `ExtractorCurlBinder` (T04) já implementa a
  lógica pura de texto.

**Estado esperado depois:**
- `handle_bind(self, args: Namespace) -> bool` — prepara o workspace; carrega
  `ExtractorMetadataStore.load(args.token_id)`; `None` → recusa
  `"token_id does not exist, use create first"`. Lê `workspace.curl_file` pelo índice
  extraído de `args.curl` (nome do arquivo, ex. `req_0006.curl.sh`); chama
  `ExtractorCurlBinder.bind(curl_text, token_id, extractor.origin_step, args.value)`;
  se a contagem devolvida for `0`, recusa `"literal_value not found in curl"` sem
  escrever o arquivo; caso contrário, escreve o novo texto de volta em
  `workspace.curl_file(index)` e devolve
  `{"ok": True, "replacements": count}`.
- `handle_unbind(self, args: Namespace) -> bool` — mesma preparação; **não** exige que
  o extractor ainda exista (permite desvincular mesmo que o `.meta.json` já tenha sido
  removido); chama `ExtractorCurlBinder.unbind(curl_text, token_id, args.value)`; se a
  contagem for `0` (placeholder não estava de fato no curl), recusa
  `"token not bound to this curl"` sem escrever; caso contrário, escreve de volta e
  devolve `{"ok": True, "replacements": count}`.
- `CliParser._build_extractor_subparser` ganha as ações `bind`
  (`--output --token-id --curl req_NNNN.curl.sh --value`) e `unbind` (mesmas flags).

**Critérios de aceite:**
- [ ] `bind` de um `token_id` inexistente → recusa, arquivo do curl não é tocado (comparar mtime/conteúdo antes e depois).
- [ ] `bind` bem-sucedido: o `.curl.sh` no disco passa a conter `{{extractor:<id>}}` no lugar do literal, e a linha `# [Token <id> comes from response of step <origin_step-do-Extractor>]` — o `origin_step` usado é o do `Extractor` carregado, **não** uma flag (a ação `bind` na tabela do parser não expõe `--origin-step`).
- [ ] `bind` cujo `--value` não aparece no curl → recusa, arquivo inalterado.
- [ ] `unbind` depois de um `bind` bem-sucedido restaura o literal e remove a linha de dependência; `CurlTokenComment.parse` no texto resultante não inclui mais esse `token_id`.
- [ ] `unbind` de um `token_id` não vinculado ao curl indicado → recusa, arquivo inalterado.
- [ ] Ciclo completo `bind` → `unbind` → `delete` (sem `--force`) num mesmo `token_id`/curl: `delete` sucede porque `unbind` já removeu a referência — nenhum estado inconsistente fica para trás.

## [T09] — `ExtractorCliHandlers`: `handle_test`

**Depende de:** [T03] (`ExtractorValidator`), [T05].
**Arquivos envolvidos:** `har_reproducer/cli/extractor_cli_handlers.py`, `har_reproducer/cli/cli_parser.py`.

**Contexto:**
`test` roda um `code` (do extractor já persistido, ou de um `--code-file` fornecido)
contra uma ou mais amostras arbitrárias, sem persistir nada — a ferramenta que
endereça diretamente o problema #1 da spec (seção 1): testar uma correção contra
várias respostas reais antes de comprometer a mudança com `update` (spec seção 3.5).

**Estado atual:**
- Nenhum handler de teste solto existe ainda; `ExtractorValidator.run_against_samples`
  (T03) já implementa a execução pura.

**Estado esperado depois:**
- `handle_test(self, args: Namespace) -> bool` — prepara o workspace (sem exigir
  curls, já que `test` pode rodar sobre um extractor que ainda nem foi vinculado);
  resolve o `code`: se `args.code_file` for fornecido, lê o arquivo; senão, carrega
  `ExtractorMetadataStore.load(args.token_id)` e usa `extractor.code` (recusa se
  nenhum dos dois for fornecido, ou se `--token-id` apontar para um extractor
  inexistente). Resolve as amostras: cada `--sample` é um path — se relativo, resolvido
  contra `workspace.real_responses`/`workspace.original_responses` (nessa ordem de
  preferência) antes de tentar como path absoluto; carrega o JSON de cada um (amostra
  que falha ao parsear vira um `ExtractorSampleResult(error=...)` isolado, sem abortar
  as demais). Monta `expected_values` a partir de `--expect res_NNNN.json=valor`
  (parse de `"="`, uma entrada por ocorrência da flag). Chama
  `ExtractorValidator.run_against_samples(token_id, code, samples, expected_values)` e
  devolve `{"ok": True, "results": [...]}` (nunca `ok: False` só por causa de uma
  amostra ter `matches_expected=False` — isso é informação para o chamador, não uma
  falha da própria ação `test`, que só devolve `ok: False` se nem `code` nem amostras
  puderam ser resolvidos).
- `CliParser._build_extractor_subparser` ganha a ação `test`
  (`--output [--token-id | --code-file] --sample ARQ [--sample ARQ ...] [--expect ARQ=valor ...]`).

**Critérios de aceite:**
- [ ] `test --token-id <id> --sample res_0003.json` roda o `code` já persistido contra a amostra indicada, sem escrever nada em `extractors/` (mtime dos arquivos existentes inalterado).
- [ ] `test --code-file correcao.py --sample res_0003.json --sample res_0007.json` roda o código do arquivo contra as duas amostras, devolvendo 2 resultados — nenhuma persistência.
- [ ] `test` sem `--token-id` nem `--code-file` → recusa clara, sem traceback.
- [ ] `test --token-id <id> --sample arquivo_invalido.json` (JSON malformado) devolve `results` com um `ExtractorSampleResult(error=...)` para essa amostra; se houver mais `--sample` válidos na mesma chamada, eles ainda aparecem no resultado.
- [ ] `test ... --expect res_0003.json=VALOR_ESPERADO` marca `matches_expected` corretamente no resultado daquela amostra; amostra sem `--expect` correspondente tem `matches_expected: null`.

## [T10] — `README.md`: nova seção `extractor` — CRUD de extratores de um workspace

**Depende de:** [T06], [T07], [T08], [T09] (documenta o comando já totalmente funcional).
**Arquivos envolvidos:** `README.md`.

**Contexto:**
A spec (seção 6) pede a atualização do README com os novos comandos, no mesmo padrão
das seções `### replay`/`### optimize` já existentes (comando, tabela de flags,
parágrafo de efeito/comportamento).

**Estado atual (`README.md`, seção `## Como executar`):**
- Contém `### parse`, `### run`, `### replay`, `### optimize`, cada uma com bloco de
  comando, tabela `| Flag | Descrição |`, e parágrafo de efeito — sem nenhuma menção a
  `extractor`.

**Estado esperado depois:**
- Nova subseção `### \`extractor\` — CRUD de extratores de um workspace`, inserida
  depois de `### optimize` (mesma ordem do restante do documento, dos comandos "mais
  básicos" aos "mais avançados" sobre um workspace já existente):
  - Aviso de pré-requisito, igual ao de `replay`/`optimize`: "Requer um workspace já
    criado por um `run` anterior."
  - Bloco de comando:
    ```bash
    uv run python -m har_reproducer.main extractor <ação> --output DIR [flags da ação]
    ```
  - Tabela com as 8 ações (`list`, `get`, `create`, `update`, `delete`, `bind`,
    `unbind`, `test`), flags e efeito — adaptada da tabela da spec seção 3.6.
  - Nota explícita, destacada (não misturada com o parágrafo de efeito): a saída de
    todo `extractor <ação>` é sempre um único objeto JSON em stdout
    (`{"ok": bool, ...}`), diferente do texto solto de `run`/`replay`/`optimize` —
    porque o comando é desenhado para consumo por agente de IA, não leitura humana
    direta.
  - Um parágrafo curto explicando o propósito (correção pontual de extractors gerados
    incorretamente, ausentes, ou inúteis pela descoberta automática — sem precisar
    rodar `run` de novo), espelhando a seção 1 da spec.

**Critérios de aceite:**
- [ ] `README.md` tem uma subseção `### \`extractor\`` entre `### optimize` e `## Configuração`, seguindo o mesmo formato markdown das subseções vizinhas (mesmo nível de cabeçalho, mesmo estilo de tabela).
- [ ] A tabela documenta as 8 ações e bate exatamente com as flags implementadas em T05-T09 (nenhuma flag documentada que não existe no `CliParser`, nenhuma flag implementada que ficou de fora do README).
- [ ] A nota sobre saída-sempre-JSON está presente e destacada.
- [ ] Nenhuma seção existente do README (`parse`, `run`, `replay`, `optimize`, `Configuração`, `Testes`) é reordenada ou alterada além da inserção da nova subseção.
