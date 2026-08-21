# Plano de Implementação — Correções Triviais Catalogadas

> Baseado em `spec.md`. Ordem das tasks é topológica (nenhuma task depende de uma
> task posterior). Cada task é autocontida — não deveria ser necessário reabrir a
> spec pra executar uma task isolada.

## [T01] — `README.md`: corrige a promessa de minimalidade do `optimize`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `README.md` (parágrafo `⚠️` da seção do comando `optimize`, linhas ~130-134)

**Contexto:**
O README descreve o comportamento do `optimize` e, no parágrafo de aviso, afirma que o
resultado é minimal no sentido absoluto ("nenhum passo isolado pode ser removido"). Isso é
falso: `optimize` nunca testa uma âncora para remoção — só os candidatos dentro de cada
faixa entre âncoras consecutivas. Medido contra o servidor real
(`docs/20260817 Reteste do Otimizador contra Servidor Real/relatorio.md`, §3.5): `[233]`
sozinho já passa com `200`, `[227]` sozinho passa, `[83]` sozinho devolve `304` — e
`optimize` devolve 7, 7 e 4 steps respectivamente para os mesmos alvos, porque cada um
desses conjuntos contém pelo menos uma âncora que nunca foi testada para remoção.

**Estado atual:**
```
⚠️ Cada requisição vai contra o servidor real (o mesmo risco de efeito colateral que já
existe em `run`/`replay`) e a busca pode reexecutar o mesmo passo várias vezes — não é
recomendado num fluxo com efeitos colaterais não-idempotentes (ex.: criar um recurso novo
a cada chamada). O resultado é um mínimo local (nenhum passo isolado pode ser removido),
não necessariamente o menor subconjunto teoricamente possível.
```

**Estado esperado depois:**
```
⚠️ Cada requisição vai contra o servidor real (o mesmo risco de efeito colateral que já
existe em `run`/`replay`) e a busca pode reexecutar o mesmo passo várias vezes — não é
recomendado num fluxo com efeitos colaterais não-idempotentes (ex.: criar um recurso novo
a cada chamada). O resultado é um mínimo local **dentro de cada faixa entre âncoras
consecutivas** (nenhum candidato testado pode ser removido sem quebrar o alvo) — as
âncoras em si nunca são testadas para remoção, então não é o menor subconjunto
teoricamente possível do fluxo inteiro.
```

⚠️ Só este parágrafo muda. O corpo descritivo acima dele (spec §2) já descreve
corretamente "faixa a faixa entre âncoras" — não reescrever.

**Critérios de aceite:**
- [x] O parágrafo `⚠️` do `optimize` no README passa a citar explicitamente "dentro de
  cada faixa entre âncoras consecutivas" em vez de "nenhum passo isolado".
- [x] Nenhum outro trecho do README é alterado.

---

## [T02] — `CliHandlers`/`main`: exit code 1 em `FAILED`, nunca `sys.exit(0)` em sucesso

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/main.py` (`main`), `har_reproducer/cli/cli_handlers.py`
(`handle_run`, `handle_parse`, `handle_replay`, `handle_optimize`), `tests/test_cli_config.py`
(4 testes `*_failure`), `tests/test_cli_replay.py`, `tests/test_cli_optimize.py`

**Contexto:**
Hoje `Reproduction FAILED` e `Optimization FAILED` saem com exit code `0` — indistinguível
de sucesso para qualquer script que encadeie comandos e cheque `$?`. Os quatro
`handle_*` de `CliHandlers` devolvem `None`; `main()` chama `args.func(args)` e ignora
qualquer retorno. `ValueError` de validação (ex.: `--to` para um step inexistente) já sai
com `1` hoje, por propagação natural do traceback — esse caminho não muda.

⚠️ `CliInvoker._call_main` (`tests/support/cli_invoker.py:28-33`) já captura **qualquer**
`SystemExit` (inclusive `SystemExit(0)`) como `result.exception`:
```python
def _call_main(self) -> Optional[BaseException]:
    try:
        main()
    except SystemExit as system_exit:
        return system_exit
    except Exception as exception:
        return exception
    return None
```
Dezenas de testes de sucesso hoje afirmam `assert result.exception is None`
(`test_cli_run.py`, `test_cli_replay.py`, `test_cli_optimize.py`, os `*_success` de
`test_cli_config.py`). Por isso `main()` **nunca chama `sys.exit` no caminho de
sucesso** — só no de falha.

**Estado atual:**
```python
# har_reproducer/main.py
def main() -> None:
    load_dotenv()
    handlers: CliHandlers = CliHandlers(engine_factory=EngineFactory, har_parser=HARParser)
    cli_parser: CliParser = CliParser(handlers)
    parser: ArgumentParser = cli_parser.build()
    args: Namespace = parser.parse_args()
    args.func(args)
```
```python
# har_reproducer/cli/cli_handlers.py
def handle_run(self, args: Namespace) -> None:
    ...
    result: bool = self._run(engine_factory, mode, har_path, workspace, project_config, sleeper)
    self._print_result(result)

def handle_parse(self, args: Namespace) -> None:
    ...
    count: int = self._har_parser.split_har(har_path, output_dir)
    print(f"Parsed HAR into {count} steps.")

def handle_replay(self, args: Namespace) -> None:
    ...
    result: bool = orchestrator.run(lambda: self._dispatch_replay_mode(runner, args))
    self._print_result(result)

def handle_optimize(self, args: Namespace) -> None:
    ...
    result: Optional[List[int]] = orchestrator.run(lambda: optimizer.optimize(...))
    self._print_optimize_result(result, output_path or workspace.optimized_steps_file(run_id))
```

**Estado esperado depois:**
```python
# har_reproducer/main.py
import sys

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
```python
def handle_run(self, args: Namespace) -> bool:
    ...
    result: bool = self._run(...)
    self._print_result(result)
    return result

def handle_parse(self, args: Namespace) -> bool:
    ...
    print(f"Parsed HAR into {count} steps.")
    return True

def handle_replay(self, args: Namespace) -> bool:
    ...
    result: bool = orchestrator.run(lambda: self._dispatch_replay_mode(runner, args))
    self._print_result(result)
    return result

def handle_optimize(self, args: Namespace) -> bool:
    ...
    result: Optional[List[int]] = orchestrator.run(lambda: optimizer.optimize(...))
    self._print_optimize_result(result, output_path or workspace.optimized_steps_file(run_id))
    return result is not None
```

⚠️ `handle_parse` sempre devolve `True` — um HAR malformado já levanta exceção antes do
`print` final (caminho de `ValueError`, inalterado); não há hoje uma noção de "parse
falhou sem exceção".
⚠️ `replay` com divergência (sem exceção) passa a sair com exit `1`, igual a `run` — spec
§3.2/§6: são a mesma classe de resultado ("comando rodou, alvo não bateu").

**Critérios de aceite (TDD — escrever/migrar os testes abaixo antes de tocar no código
de produção; confirmar que falham pelo motivo certo antes de implementar):**
- [x] `tests/test_cli_config.py`: os 4 testes `test_criteria_status_code_failure`,
  `test_criteria_body_contains_failure`, `test_criteria_url_match_failure`,
  `test_criteria_html_element_present_failure` trocam `assert result.exception is None`
  por `assert isinstance(result.exception, SystemExit)` e
  `assert result.exception.code == 1` — o resto de cada teste (asserções de stdout,
  golden) não muda.
- [x] Novo teste em `tests/test_cli_replay.py`, reaproveitando o padrão de
  `dry_workspace_network`/`ReplayScenario` já usados no arquivo: roda `replay` com um
  `--config` cujo `success_criteria` não bate com a resposta real (ex.:
  `{"success_criteria": [{"type": "status_code", "expected": 599}]}`), e afirma
  `"Reproduction FAILED: Target state not reached." in result.stdout`,
  `isinstance(result.exception, SystemExit)` e `result.exception.code == 1`.
- [x] Novo teste em `tests/test_cli_optimize.py`, reaproveitando `main_workspace`/
  `ReplayScenario`: roda `optimize --to 9 --success-criteria
  '[{"type":"status_code","expected":599}]'` (nunca satisfeito pelo servidor real,
  força `ReplayOptimizerAborted` em `_resolve_range` já na primeira faixa) e afirma
  `"Optimization FAILED: unable to find a passing subset" in result.stdout`,
  `isinstance(result.exception, SystemExit)` e `result.exception.code == 1`.
- [x] Não-regressão: todo teste de sucesso existente que afirma `result.exception is
  None` (`test_cli_run.py`, `test_cli_replay.py`, `test_cli_optimize.py`, os
  `*_success` de `test_cli_config.py`) continua passando sem alteração — `main()` não
  chama `sys.exit` nenhuma vez no caminho de sucesso.
- [x] Não-regressão: `test_optimize_requires_success_criteria`,
  `test_optimize_rejects_missing_from_index`,
  `test_optimize_success_criteria_flag_overrides_empty_config` e
  `test_replay_missing_step` continuam afirmando `isinstance(result.exception,
  ValueError)` sem mudança — `ValueError` de validação não passa por `sys.exit`.

---

## [T03] — `ReplayOptimizer.optimize`: avisa antes de sobrescrever `--steps-out`

**Depende de:** Nenhuma.
**Arquivos envolvidos:** `har_reproducer/optimization/replay_optimizer.py` (`optimize`),
`tests/test_cli_optimize.py` (novo teste) ou `tests/unit/test_replay_optimizer.py`

**Contexto:**
`ReplayOptimizer.optimize` escreve o resultado em `destination` sem checar se o arquivo
já existe — rodar `optimize` duas vezes para o mesmo `--steps-out` (ou para o
`workspace.optimized_steps_file(run_id)` default, se colidir) descarta o conteúdo
anterior sem aviso. O restante do projeto já usa o prefixo `[AVISO]` para mensagens
desse tipo (`tracking/token_location_detector.py:29`,
`reproduction/mitm_proxy_orchestrator.py:105`,
`reproduction/extractor_metadata_store.py:19`, entre outros) — a nova mensagem segue o
mesmo prefixo.

**Estado atual:**
```python
# har_reproducer/optimization/replay_optimizer.py:59-61
destination: Path = output_path if output_path is not None else workspace.optimized_steps_file(run_id)
destination.write_text("\n".join(str(index) for index in final_list) + "\n", encoding="utf-8")
return final_list
```

**Estado esperado depois:**
```python
destination: Path = output_path if output_path is not None else workspace.optimized_steps_file(run_id)
if destination.exists():
    print(f"[AVISO] {destination} já existe e será sobrescrito.")
destination.write_text("\n".join(str(index) for index in final_list) + "\n", encoding="utf-8")
return final_list
```

⚠️ Continua sobrescrevendo (spec §3.3 — decisão escolhida foi avisar, não recusar); a
mudança é só imprimir o aviso antes de escrever quando o arquivo já existe.

**Critérios de aceite (TDD):**
- [x] Teste unitário (`tests/unit/test_replay_optimizer.py`, seguindo o padrão de stub
  já usado nesse arquivo): chamando `optimize` com `output_path` apontando para um
  arquivo já existente, o stdout contém
  `f"[AVISO] {output_path} já existe e será sobrescrito."` e o arquivo é sobrescrito
  com o novo conteúdo (não faz merge nem preserva o antigo).
- [x] Teste unitário: chamando `optimize` com `output_path` apontando para um caminho
  que **não** existe ainda, nenhum `[AVISO]` é impresso, e o arquivo é criado
  normalmente.
- [x] Não-regressão: `test_optimize_happy_path_writes_default_steps_file` e
  `test_optimize_respects_custom_steps_out` (`tests/test_cli_optimize.py`) continuam
  passando sem alteração — nenhum dos dois roda `optimize` duas vezes sobre o mesmo
  destino, então nenhum `[AVISO]` deveria aparecer no stdout deles.
