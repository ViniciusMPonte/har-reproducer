# Spec — Correções Triviais Catalogadas

## 0. Sumário

Três correções pequenas e independentes entre si (arquivos diferentes, sem dependência de
código compartilhado), catalogadas desde 17/08/2026 em
`docs/20260817 Reteste do Otimizador contra Servidor Real/correcoes.md` como itens 1, 3 e
7 — reunidas numa etapa só porque nenhuma, isolada, justificaria o ciclo completo de
spec+plano. **1.** O README promete que o resultado do `optimize` é "um mínimo local
(nenhum passo isolado pode ser removido)", o que é falso — âncoras nunca são testadas para
remoção. **3.** `Optimization FAILED` e `Reproduction FAILED` saem com exit code `0`,
indistinguíveis de sucesso para qualquer script que encadeie comandos. **7.**
`optimize --steps-out` sobrescreve um arquivo existente sem aviso.

### Glossário

| termo | significado nesta spec |
|---|---|
| **âncora** | Step de origem citado numa linha de dependência recalculável de um `.curl.sh`. Entra no schedule do `optimize` por construção e nunca é testado para remoção (item 4 do backlog, fase 2, fora de escopo aqui). |
| **`ValueError` de validação** | Erro de argumento inválido (ex.: `--to` para um step inexistente), levantado antes de qualquer requisição de rede. Já sai com exit code `1` hoje — não muda. |
| **`FAILED`** | O comando rodou até o fim sem erro de validação, mas não alcançou o estado esperado (`Reproduction FAILED`, `Optimization FAILED`). Hoje sai com exit code `0`; esta spec muda isso. |

---

## 1. Objetivo

### 1.1 — README: a promessa de minimalidade do `optimize`

Medido contra o servidor real (`docs/20260817 .../relatorio.md`, §3.5): `[233]` sozinho
passa com `200`, `[227]` sozinho passa, `[83]` sozinho devolve `304` — e o `optimize`
devolve 7, 7 e 4 steps respectivamente para esses mesmos alvos. **Qualquer** passo isolado
do resultado pode ser removido nos três alvos testados, contradizendo a frase do README.

### 1.2 — Exit code `0` em falha

| Cenário | Exit code hoje |
|---|---|
| `Reproduction SUCCESSFUL` | `0` |
| `Reproduction FAILED` (`run`/`replay`) | **`0`** |
| `Optimization SUCCESSFUL` | `0` |
| `Optimization FAILED` | **`0`** |
| `ValueError` de validação | `1` |

Um script que encadeie `run && replay` ou cheque `$?` não distingue sucesso de falha —
só lendo o stdout, ou verificando se o `.txt` de saída existe. As falhas de *validação*
já saem com `1`, tornando o comportamento inconsistente dentro do mesmo comando.

### 1.3 — `--steps-out` sobrescreve sem aviso

`ReplayOptimizer.optimize` (`optimization/replay_optimizer.py:59`) escreve o resultado com
`destination.write_text(...)`, sem checar se `destination` já existe. Rodar `optimize`
duas vezes apontando para o mesmo `--steps-out` descarta o resultado anterior sem aviso
nem backup.

### 1.4 Fora de escopo

- **Item 4 (fase 2 do `optimize`, testar âncora para remoção)** — é o que tornaria a
  promessa do README verdadeira "de verdade"; esta etapa só corrige o **texto**. Etapa
  própria, maior, ainda não especificada.
- **Item 2** (`origin_location` no cache hit) e **redescoberta reativa** — sem relação de
  código com esta etapa; ficam para depois, na ordem já combinada.

---

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `README.md` — parágrafo do `optimize`

```
O `optimize` parte do schedule que `replay --mode smart --from --to` calcularia (as
âncoras — passos de onde algum token consumido pelo alvo tem origem confirmada) e testa,
faixa a faixa entre âncoras consecutivas, se os passos que ficam fora desse schedule
ainda são necessários — removendo-os um a um até achar um subconjunto mínimo local que
ainda faz o alvo responder de acordo com `success_criteria`. Ao final, escreve um `.txt`
no formato que `replay --mode list --steps-file` já consome.

⚠️ Cada requisição vai contra o servidor real (...). O resultado é um mínimo local (nenhum
passo isolado pode ser removido), não necessariamente o menor subconjunto teoricamente
possível.
```

O corpo do parágrafo já está correto ("faixa a faixa **entre** âncoras"); é só a frase do
`⚠️` que generaliza demais, dizendo "nenhum passo isolado" sem qualificar que isso vale só
para os candidatos testados, não para as âncoras.

### `har_reproducer/main.py` (21 linhas, arquivo inteiro)

```python
def main() -> None:
    load_dotenv()
    handlers: CliHandlers = CliHandlers(engine_factory=EngineFactory, har_parser=HARParser)
    cli_parser: CliParser = CliParser(handlers)
    parser: ArgumentParser = cli_parser.build()
    args: Namespace = parser.parse_args()
    args.func(args)
```

`args.func` é um dos quatro `handle_*` de `CliHandlers`, ligado via `set_defaults(func=...)`
em `CliParser` (`cli_parser.py:37,57,81,107`) — chamada direta, sem tradução de retorno em
código de saída.

### `CliHandlers.handle_run` / `handle_replay` / `handle_optimize` / `handle_parse` — `har_reproducer/cli/cli_handlers.py`

```python
def handle_run(self, args: Namespace) -> None:
    ...
    result: bool = self._run(...)
    self._print_result(result)

def handle_replay(self, args: Namespace) -> None:
    ...
    result: bool = orchestrator.run(lambda: self._dispatch_replay_mode(runner, args))
    self._print_result(result)

def handle_optimize(self, args: Namespace) -> None:
    ...
    result: Optional[List[int]] = orchestrator.run(lambda: optimizer.optimize(...))
    self._print_optimize_result(result, ...)

def handle_parse(self, args: Namespace) -> None:
    ...
    count: int = self._har_parser.split_har(har_path, output_dir)
    print(f"Parsed HAR into {count} steps.")
```

Os quatro devolvem `None` hoje. `handle_run`/`handle_replay` já têm um `bool` de sucesso em
mãos (`result`); `handle_optimize` tem `Optional[List[int]]`, onde sucesso é
`result is not None`; `handle_parse` não tem noção de falha (uma `.har` malformada já
levanta exceção antes de chegar aqui, tratada pelo caminho de `ValueError`/traceback que
já existe).

⚠️ **`CliInvoker._call_main`** (`tests/support/cli_invoker.py:28-33`) já captura
`SystemExit` e o guarda em `CliInvocationResult.exception`:
```python
def _call_main(self) -> Optional[BaseException]:
    try:
        main()
    except SystemExit as system_exit:
        return system_exit
    ...
```
Isso importa porque **`sys.exit(0)` levanta `SystemExit(0)` igual a `sys.exit(1)` levanta
`SystemExit(1)`** — não existe "sair com 0 sem lançar `SystemExit`" chamando `sys.exit`
explicitamente. Dezenas de testes hoje fazem `assert result.exception is None` para
cenários de **sucesso** (`test_cli_run.py`, `test_cli_replay.py`, dois casos de
`test_cli_optimize.py`). Se `main()` chamar `sys.exit(0)` no caminho de sucesso, todos eles
passam a ver `SystemExit(0)` em vez de `None` — quebra em massa. É por isso que 3.2 (abaixo)
só chama `sys.exit` no caminho de falha, nunca no de sucesso.

### `test_cli_config.py` — os quatro testes que já demonstram o defeito

```python
def test_criteria_status_code_failure(...) -> None:
    ...
    result: CliInvocationResult = scenario.run('{"success_criteria": [{"type": "status_code", "expected": 500}]}')
    assert result.exception is None                              # <- é o defeito, capturado em teste
    assert "Reproduction FAILED: Target state not reached." in result.stdout
    ...
```

Os quatro (`test_criteria_status_code_failure`, `test_criteria_body_contains_failure`,
`test_criteria_url_match_failure`, `test_criteria_html_element_present_failure`) afirmam
`result.exception is None` num cenário de `Reproduction FAILED` — são a prova em teste do
item 1.2, e são os únicos testes existentes que a mudança de 3.2 toca.

### `ReplayOptimizer.optimize` — `har_reproducer/optimization/replay_optimizer.py:34-58`

```python
destination: Path = output_path if output_path is not None else workspace.optimized_steps_file(run_id)
destination.write_text("\n".join(str(index) for index in final_list) + "\n", encoding="utf-8")
return final_list
```

`destination` nunca é checada antes da escrita.

---

## 3. Decisões de arquitetura

### 3.1 — README: reescrever a promessa de minimalidade

**Estado esperado:**
```
⚠️ Cada requisição vai contra o servidor real (o mesmo risco de efeito colateral que já
existe em `run`/`replay`) e a busca pode reexecutar o mesmo passo várias vezes — não é
recomendado num fluxo com efeitos colaterais não-idempotentes (ex.: criar um recurso novo
a cada chamada). O resultado é um mínimo local **dentro de cada faixa entre âncoras
consecutivas** (nenhum candidato testado pode ser removido sem quebrar o alvo) — as
âncoras em si nunca são testadas para remoção, então não é o menor subconjunto
teoricamente possível do fluxo inteiro.
```

Só o parágrafo do `⚠️` muda; o corpo descritivo acima dele já está correto.

### 3.2 — Exit code por resultado, não por exceção de validação

**Estado esperado:** os quatro `handle_*` passam a devolver `bool` (sucesso); `main()`
traduz em código de saída, **só chamando `sys.exit` no caminho de falha**:

```python
def main() -> None:
    load_dotenv()
    ...
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

def handle_replay(self, args: Namespace) -> bool:
    ...
    result: bool = orchestrator.run(lambda: self._dispatch_replay_mode(runner, args))
    self._print_result(result)
    return result

def handle_optimize(self, args: Namespace) -> bool:
    ...
    result: Optional[List[int]] = orchestrator.run(lambda: optimizer.optimize(...))
    self._print_optimize_result(result, ...)
    return result is not None

def handle_parse(self, args: Namespace) -> bool:
    ...
    print(f"Parsed HAR into {count} steps.")
    return True
```

⚠️ **`sys.exit` só no `if not success`, nunca no caminho de sucesso** — é a decisão de
2 (§2), sem ela dezenas de testes de sucesso quebrariam por verem `SystemExit(0)` em vez
de `None`.
⚠️ `ValueError` de validação continua propagando sem ser capturada aqui — já sai com `1`
hoje (o traceback do Python faz isso), e essa etapa não muda esse caminho.
⚠️ `handle_parse` sempre devolve `True` — não tem noção de falha parcial hoje (HAR
malformado já levanta exceção antes de chegar ao `print` final).

**Decisão sobre `replay` com divergência (ponto que o backlog deixava explicitamente
aberto):** `Reproduction FAILED` do `replay` sai com exit `1`, igual ao de `run` — os dois
são a mesma classe de resultado ("o comando rodou, mas o alvo não bateu"), e o backlog já
os tratava como o mesmo item. Ver §6 para confirmação.

### 3.3 — `--steps-out`: avisar antes de sobrescrever

**Estado esperado:**
```python
destination: Path = output_path if output_path is not None else workspace.optimized_steps_file(run_id)
if destination.exists():
    print(f"[AVISO] {destination} já existe e será sobrescrito.")
destination.write_text("\n".join(str(index) for index in final_list) + "\n", encoding="utf-8")
```

**Escolhido: avisar, não recusar.** O backlog oferecia as duas opções ("decisão de produto,
não de arquitetura"). Recusar exigiria uma flag nova (`--force` ou similar) só para o caso
comum de rodar `optimize` de novo sobre o mesmo workspace — atrito desproporcional ao
risco (o arquivo é só uma lista de índices, facilmente regerada). Aviso no stdout já torna
a sobrescrita visível sem impor fricção. Ver §6 para confirmação.

---

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `README.md` | reescreve o parágrafo `⚠️` do `optimize` (3.1) |
| `har_reproducer/main.py` → `main` | traduz o retorno de `args.func` em `sys.exit(1)`, só na falha (3.2) |
| `cli/cli_handlers.py` → `handle_run`/`handle_replay`/`handle_optimize`/`handle_parse` | passam a devolver `bool` (3.2) |
| `optimization/replay_optimizer.py` → `ReplayOptimizer.optimize` | avisa antes de sobrescrever `destination` (3.3) |
| `tests/test_cli_config.py` | os 4 testes `*_failure` passam a esperar `SystemExit(1)` em vez de `exception is None` (3.2) |

Nenhum outro componente muda — `CliParser`, `ReplayOptimizer` (fora do trecho de 3.3),
`Engine`/`ReplayRunner` continuam iguais.

---

## 5. Casos de borda e comportamento de erro

**5.1 `run --mode dry`.** `DryEngine` também retorna `bool` de `_reproduce()` — o caminho
já existe e não muda; só a tradução final em `main()` é nova.

**5.2 `optimize` abortado por `ReplayOptimizerAborted`** (faixa que falha mesmo com todos
os candidatos). `optimizer.optimize` já devolve `None` nesse caso (`except
ReplayOptimizerAborted: ... return None`) — cai no mesmo `result is not None` de 3.2, sem
mudança de lógica.

**5.3 `--max-requests` excedido.** Levanta `ValueError` — já sai com `1` hoje, sem mudança.

**5.4 `--steps-out` apontando para um diretório inexistente.** Comportamento inalterado —
`write_text` já levantaria `FileNotFoundError` hoje; esta etapa não adiciona tratamento
para esse caso, só para o de sobrescrita.

---

## 6. Suposições e pontos a confirmar

- **`replay` com divergência sai com exit `1`, igual a `run`** (3.2) — o backlog original
  deixava isso como decisão aberta explicitamente. Proposta: sim, é a mesma classe de
  resultado. Confirmar.
- **`--steps-out`: avisar, não recusar** (3.3) — proposta escolhida; a alternativa mais
  rígida (recusar sem flag) fica descartada, mas registrada aqui para confirmação.
- **Texto exato do `[AVISO]`** e do parágrafo novo do README — ajustável.

---

## 7. Referência

Toda alteração de código desta spec segue [[guia-de-estilo]]. Nenhuma decisão aqui
envolve o princípio de genericidade de [[arquitetura-e-fundamentos]] — são três correções
de comportamento observável (documentação, código de saída, aviso de sobrescrita), sem
suposição nova sobre formato de protocolo ou de site.
