# Lacunas de teste — replay sobre workspace `dry` (item 8 da `lista_de_bugs.md`)

> Levantamento em 10/08/2026, durante a reanálise do item 8 após o merge do fix do
> item 2 (`4d5869f`). O item 8 deixou de existir **como bug** — o fallback do
> README para `original_responses/` voltou a ser alcançável — mas nenhum teste cobre
> o cenário. Este arquivo inventaria essa lacuna para uma etapa futura de testes.

## 1. O cenário sem cobertura

`replay` sobre um workspace que só rodou `run --mode dry` deve resolver tokens
dinâmicos cujo `origin_step` está **fora** do schedule, lendo a resposta de
`original_responses/`. Esse é exatamente o exemplo documentado no `README.md:149`
("workspace que só rodou `dry`... o `replay` cai automaticamente para
`original_responses/`").

O bug original (item 8) era: como o item 2 impedia o `.py` do extrator de ser
gravado em `dry`, `ExtractorRunner.run_existing` (`extractor_runner.py:23-31`)
retornava `None` **antes** de usar o `response_override_dir`, e o replay emitia
`Failed to resolve token` para todos os steps (resolução zero). O fix do item 2
(`4d5869f`) fez `resolve_all()` rodar em `dry` (`engines/engine.py:73`), gravando o
`.py` — o fallback passou a ser exercido de fato.

**O que não existe hoje:** nenhum teste que pegue um workspace `dry` real, rode o
replay (ou a resolução de tokens) e afirme que os tokens com origem fora do
schedule resolvem via `original_responses/`. Se o item 2 regredir (`.py` deixar de
ser gravado em `dry`), o item 8 volta silenciosamente — nada na suíte pega.

## 2. Cobertura atual (o que existe, e por que não fecha a lacuna)

| Teste | Local | O que cobre | Lacuna que deixa |
|---|---|---|---|
| `_reference_dir_for_step` sem origem usa `res_refer_dir` | `tests/unit/test_replay_token_resolver.py:15-21` | Pure function, origem `None` | Não exercita o caminho real (arquivo em disco + `.py` existente) |
| `_reference_dir_for_step` usa `res_refer_dir` quando o arquivo existe | `tests/unit/test_replay_token_resolver.py:24-32` | Pure function, `res_refer_dir` populado | — |
| `_reference_dir_for_step` cai em `original_dir` quando falta o arquivo | `tests/unit/test_replay_token_resolver.py:35-42` | Pure function, `res_refer_dir` sem o arquivo | Não prova que o `.py` existe nem que a resolução completa funciona |
| `_resolve_one` retorna `False` sem chamar `_record_observation` quando o extrator devolve `None` | `tests/unit/test_replay_token_resolver.py:92-103` | Caminho de falha com `FakeExtractorRunner(run_existing_result=None)` | Cobre a falha, não o sucesso |
| `run_existing` retorna `None` quando o arquivo não existe | `tests/unit/test_extractor_runner.py:22-29` | Comportamento do `ExtractorRunner` isolado | É justamente o sintoma do item 8; nada garante que o `.py` **existe** no workspace `dry` |
| Golden `replay_ref_fallback` | `tests/test_cli_replay.py:245-272` + `tests/golden/replay_ref_fallback/` | `_reference_dir_for_step` sobre workspace **`main`** com cópia de `real_responses` (um arquivo removido) | Workspace `main`, não `dry` — `real_responses` populado e `.py` gravado pelo modo `main`; não prova o cenário `real_responses` vazio |
| Golden `run_dry_*` (árvore de arquivos) | `tests/golden/run_dry_default/` etc. | Pina, por comparação de árvore, que o workspace `dry` agora **tem** os `.py` (regenerados em `4d5869f`) | Pina o `run`, não o `replay` sobre ele |

## 3. Testes propostos para implementar no futuro

### 3.1 Unitário — resolução de token no workspace `dry` via `original_responses/` (sem rede)

Local sugerido: `tests/unit/test_replay_token_resolver.py` (ou
`tests/unit/test_extractor_runner.py` para a parte do runner).

Precisa de um `FakeExtractorRunner` que registre o `response_override_dir` recebido
(hoje `run_existing_calls` em `tests/support/fake_extractor_runner.py:23` já guarda
`RecordedRunCall(token_id, response_override_dir)` — dá para assertar direto).

Cenário:
1. Montar um workspace `dry` real: rodar `run --mode dry` sobre
   `tests/fixtures/synthetic_flow.har` (mesmo jeito de `tests/test_cli_run.py:16`),
   ou materializar a árvore `tests/golden/run_dry_default/` como fixture.
2. `ReplayTokenResolver.resolve(curl_text, schedule, replay_run_dir, res_refer_dir, original_responses_dir)`
   com:
   - `res_refer_dir = workspace.real_responses` (**vazio** no `dry`);
   - `original_responses_dir = workspace.original_responses` (populado);
   - `schedule` que **deixa de fora** o `origin_step` dos tokens do `curl_text`
     (ex.: `curl` do step 4 — tokens dos steps 3 e 0 — com `schedule={4}`).
3. Asserts:
   - o `curl` contém token(s) com origem fora do schedule;
   - o valor retornado não é `None` (tokens resolvem);
   - os `run_existing_calls` registram `response_override_dir == original_responses_dir`;
   - `session_store` passou a ter os tokens setados.

Isso não exige rede (só o `ReplayTokenResolver`), então fica na rodada padrão.

### 3.2 Unitário — regressão do item 2: `dry` grava o `.py` do extrator

Local sugerido: `tests/unit/test_token_resolver.py` (ou `tests/unit/test_engine.py`).

Já há cobertura parcial via golden (árvore de `run_dry_*`), mas um teste fino
explícito deixa a intenção clara: após `run --mode dry` sobre um HAR com token
dinâmico, `workspace.extractor_file(token_id).exists()` é `True` para todo token
resolvido — e, em consequência, `ExtractorRunner.run_existing(token_id, dir)`
executa o script (não retorna `None` prematuro).

### 3.3 Golden (slow) — replay de ponta a ponta sobre workspace `dry`

Local sugerido: `tests/test_cli_replay.py`, novo cenário com
`@pytest.mark.slow`, análogo a `test_replay_ref_fallback` (linhas 245-272).

Fluxo:
1. `run --mode dry` sobre `synthetic_flow.har` → workspace W.
2. `replay --mode list` com `steps_file` contendo só um step cujos tokens tenham
   origem fora do schedule (ex.: `4`).
3. Asserts no stdout: sem nenhuma linha `Failed to resolve token`; `Step 4
   completed with status 200`; veredito coerente.
4. Golden da árvore do workspace (como os demais `replay_*`).

Esse cenário é o que reproduziria o item 8 se ele voltasse — o sintoma era
exatamente `Failed to resolve token` para todos os steps.

## 4. Como verificar o cenário hoje (procedimento manual)

Foi o que confirmou que o item 8 não existe mais:

```bash
uv run pytest  # 202 passed, 11 skipped (offline)
```

Reprodução manual (materializar o HAR substituindo `__PORT__`):

```bash
# 1. dry
har-reproducer run --har <har> --mode dry --output <ws>
# 2. conferir que dry gravou os .py
ls <ws>/extractors/*.py            # existe (antes do fix: vazio)
ls <ws>/real_responses/            # vazio (dry)
ls <ws>/original_responses/        # populado
# 3. replay de um step com origem fora do schedule
printf '4\n' > steps.txt
har-reproducer replay --output <ws> --mode list --steps-file steps.txt
# antes do fix: "Failed to resolve token" para todos; agora: nenhuma ocorrência
```

## 5. Referência

- `lista_de_bugs.md` — itens 2 e 8 desta pasta.
- Fix do item 2 (causa raiz do item 8): commit `4d5869f`.
- `har_reproducer/reproduction/extractor_runner.py:23-31` (`run_existing`).
- `har_reproducer/replay/replay_token_resolver.py:41-72` (`_resolve_one` /
  `_reference_dir_for_step`).
- `har_reproducer/engines/engine.py:73` (`resolve_all()` incondicional).
- Testes de suporte: `tests/support/fake_extractor_runner.py`,
  `tests/support/replay_scenario.py`, `tests/support/cli_invoker.py`.
