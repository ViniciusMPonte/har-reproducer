# Lista de bugs encontrados durante a caracterização golden e a refatoração/criação de testes unitários

Levantamento em 10/08/2026. Fonte primária: `docs/20260806 Rede de Caracterização
Golden/spec.md` §6 ("Dívida catalogada — defeitos congelados"), nove defeitos
descobertos durante a Etapa A (caracterização) por execução (§6.1-6.4, §6.8, §6.9) ou
por grep/leitura (§6.5-§6.7). Nenhum deles foi corrigido nas Etapas A, B ou C — as
três etapas trataram apenas de testes e refatoração estrutural, por decisão de
escopo (ver `[[refatoracao-para-testabilidade]]`). Um décimo item foi acrescentado: um
achado arquitetural da retro de 09/08/2026, que não é um bug de comportamento, mas um
acoplamento frágil descoberto ao escrever os dublês de teste da Etapa C.

Todos os 10 itens abaixo foram **reverificados em 10/08/2026 lendo o código atual**
(pós-merge das três etapas) — os números de linha do spec original ficaram
desatualizados pela refatoração, então cada item aqui cita a localização **atual**.

**Nenhum item foi corrigido.** Nove ainda existem tal como descoberto; um deles
(código morto) teve parte removida incidentalmente pela refatoração da Etapa B, mas o
restante persiste. Esta lista não propõe correção — é o inventário para a próxima
etapa decidir o que vale corrigir e escrever a spec correspondente.

---

## 1. `CookieAgent` inalcançável em HAR realista — `Set-Cookie` é classificado como header genérico, não como cookie

**Ainda existe.**

Não é um problema de ordem temporal (uma requisição nunca poderia depender da sua
própria resposta, e o código já trata isso corretamente em
`ResponseGrep`/`CandidateResolver._find_origin`, que só busca origem em respostas de
steps **anteriores**). O bug real é de **precedência de classificação** dentro de
um mesmo response sample: `TokenLocationDetector.find`
(`har_reproducer/tracking/token_location_detector.py:12-19`) testa
`_find_in_headers` **antes** de `_find_in_cookies`. Uma captura de HAR realista (de
browser ou do `mitm_addon`) inclui o header cru `Set-Cookie: SESSIONID=…` junto com o
dict `cookies` já parseado — o mesmo valor aparece nos dois lugares. Como
`_find_in_headers` roda primeiro, o valor é achado ali e classificado
`TokenLocation.HEADER`, nunca chegando a `_find_in_cookies`. Isso direciona o fluxo
para `HeaderAgent`, que procura um header chamado literalmente `SESSIONID` (nome
derivado do path `cookie:SESSIONID`) — mas o header real se chama `Set-Cookie`, a
busca por nome falha, as estratégias determinísticas se esgotam, e o resultado é
`LiteralFallbackAgent` (`har_reproducer/tracking/candidate_resolver.py:187`): valor
hardcoded em vez de extrator.

**Impacto observado (Etapa A, medido):** com `Set-Cookie` na entry 0, tanto `dry`
quanto `main` produzem `LiteralFallbackAgent` para o cookie de sessão — o caso mais
comum de token dinâmico. `Attempt 1 failed` e 5s de `time.sleep` por ocorrência
(retry determinístico que sempre falha, seguido do delay fixo do item 6). Alcançar
`CookieAgent` de fato exige uma entry artificial sem `Set-Cookie` no header (só
`cookies[]`) — o que não ocorre em captura real, já que o protocolo HTTP sempre emite
o header.

## 2. `run --mode dry` não é idempotente — infla extratores a cada rodada

**Ainda existe.**

`Engine.execute_step` (`har_reproducer/engines/engine.py:72-74`) só chama
`self.token_resolver.resolve_all()` sob `if self.USES_NETWORK`.
`DryEngine.USES_NETWORK = False` (`har_reproducer/engines/dry_engine.py:8`), então em
modo dry o `.py` do extrator nunca é escrito — só o `.meta.json` é gravado
incondicionalmente por `CandidateResolver` via `analyze_step`. Na rodada seguinte,
`CandidateResolver._check_persisted_slot` (`har_reproducer/tracking/candidate_resolver.py:103-113`)
chama `ExtractorRunner.run_existing`, que retorna `None` porque o `.py` não existe
(`har_reproducer/reproduction/extractor_runner.py:28-30`); isso é lido como
`MISMATCH`, e `_find_slot` (`candidate_resolver.py:72-85`) forka um `token_id` novo —
todo `dry` subsequente sobre o mesmo `--output` cria mais extratores, nunca reutiliza.

**Impacto observado (Etapa A, medido):** com dois steps reenviando o mesmo cookie,
`dry` gera dois `LiteralFallbackAgent` (deveria ser um reaproveitado) e paga 10,7s;
numa segunda rodada no mesmo `--output`, os extratores dobram.

## 3. `temp_extractors/` nunca é limpo em modo dry

**Ainda existe.** Mesma causa raiz do item 2: `ExtractorRunner._cleanup_temp_file`
(`har_reproducer/reproduction/extractor_runner.py:46-52`) só é alcançado dentro de
`ExtractorRunner.run()`, gated pelo mesmo `USES_NETWORK` do item 2.
`BaseAgent.run_tdd_loop` cria o arquivo temporário no caminho de sucesso
(`har_reproducer/agents/base_agent.py`) e não o remove ali — só no caminho de falha
total. Em `dry`, o diretório `temp_extractors/` acumula arquivo por candidato
resolvido, para sempre.

## 4. Token de corpo de requisição é irresolvível por construção

**Ainda existe.** `BaselineDiff._diff_body` (`har_reproducer/tracking/baseline_diff.py:39-50`)
emite o path `"body"` com o **corpo inteiro da requisição** como valor candidato.
`CandidateResolver._find_origin` faz grep desse texto inteiro (via `ResponseGrep`)
contra as respostas anteriores — só casaria se o corpo inteiro de uma requisição
aparecesse literalmente, byte a byte, numa resposta prévia. Na prática, nunca
resolve; sempre cai em fallback.

## 5. Código morto

**Parcialmente corrigido pela refatoração (efeito colateral, não intencional); resto ainda existe.**

- `Engine.curls_dir` / `.extractors_dir` / `.temp_extractors_dir` — **corrigido**:
  removidos da refatoração da Etapa B (T07, `Workspace` centralizou os caminhos).
  Confirmado por grep: nenhuma ocorrência em `har_reproducer/`.
- `contracts.StepExecutor` (TypeAlias, `har_reproducer/contracts/types.py:9`) — ainda
  existe, ainda não usado como anotação em nenhum lugar, e a assinatura ainda não
  corresponde a `Engine.execute_step` atual.
- `SessionStore.get_token` / `.render_dict` (`har_reproducer/session/session_store.py:18-20,26-34`)
  — ainda existem, sem nenhum chamador de produção.
- `raise RuntimeError` final de `StepRetryPolicy.execute`
  (`har_reproducer/reproduction/step_retry_policy.py:16-23`) — ainda inalcançável: no
  último `attempt`, o `return response` dentro do loop sempre executa antes.
- `entries[0]` sem guarda contra HAR vazio — ainda existe em dois lugares:
  `har_reproducer/engines/engine.py:46` e
  `har_reproducer/reproduction/curl_http_transport.py:77`.
- `StepRequest.is_skippable` (`har_reproducer/models/http.py:13`) — ainda morto como
  leitura em produção (só escrito em `engine.py:64`); é lido apenas em teste.

## 6. Nomes que mentem / efeitos colaterais fora de lugar

**Ainda existe (os três).**

- `MitmProxyOrchestrator.project_root` (`har_reproducer/reproduction/mitm_proxy_orchestrator.py:26-30`)
  armazena, na prática, o `ca_cert_path`/`confdir` do mitmproxy — os chamadores
  (`har_reproducer/cli/cli_handlers.py:81-85,116-118`) passam
  `project_config.ca_cert_path` nesse parâmetro. O nome do atributo sugere a raiz do
  projeto; é um diretório de config do mitmproxy.
- `ProjectConfigLoader._apply_defaults` cria `.mitmproxy/` em disco como efeito
  colateral de carregar config (`har_reproducer/config/project_config_loader.py:34-38`
  → `Workspace.get_mitmproxy_ca_path()`, que faz `mkdir`), mesmo em modo `dry` — que
  nunca usa proxy. `ProjectConfigLoader.load` é chamado incondicionalmente em
  `handle_run` (`har_reproducer/cli/cli_handlers.py:45`), antes de qualquer checagem
  de modo.
- `BaseAgent.run_tdd_loop` (`har_reproducer/agents/base_agent.py:142-166`) dorme
  (`Sleeper`, 5s) em todo caminho de falha dentro do loop de tentativas, sem checar
  se é a última tentativa — sleep desnecessário mesmo depois do último attempt, que
  já vai falhar de qualquer forma.

## 7. `pytest` e `pytest-httpx` em `dependencies`, não num grupo dev

**Ainda existe.** `pyproject.toml` só tem `[project.dependencies]`, com
`pytest>=9.1.0` e `pytest-httpx>=0.36.2` misturados às dependências de produção; não
há `[project.optional-dependencies]`/grupo dev. `pytest-httpx` está declarado e,
confirmado por grep, não é usado por nenhum código do repo (nem produção, nem
`tests/`). Débito já adiado duas vezes: §6.7 da Etapa A, D.8 da spec da Etapa C.

## 8. Exemplo do README para `response_reference_dir` (fallback em workspace `dry`) é inalcançável

**Ainda existe**, e depende do item 2 continuar existindo. `ExtractorRunner.run_existing`
(`har_reproducer/reproduction/extractor_runner.py:23-31`) retorna `None` assim que
`extractor_file.exists()` é falso — **antes** de qualquer uso do
`response_override_dir`. Como o item 2 garante que o `.py` do extrator nunca existe
num workspace que só rodou `dry`, o fallback documentado no README (linha ~149:
"quando a resposta de um passo específico não existir ali, ex.: workspace que só
rodou `dry`, o `replay` cai automaticamente para `original_responses/`") nunca é
exercido por esse caminho — o `replay` sobre workspace `dry` emite `Failed to resolve
token` para todos os steps, resolve zero.

## 9. Token não resolvido interpola placeholder cru no `curl`, mas `replay` reporta sucesso mesmo assim

**Ainda existe.** `ReplayRunner._run_schedule` (`har_reproducer/replay/replay_runner.py:62-77`)
roda todos os steps do schedule, mas só passa o **último** índice/response para
`ReplayResultComparator.matches_original` (`har_reproducer/replay/replay_result_comparator.py:15-24`)
— nenhum status intermediário é checado. Um step no meio do schedule com token
irresolvível (placeholder `{{extractor:...}}` interpolado literalmente pelo
`SessionStore.render`, causando `curl: (3) nested brace in URL` e `status_code: 0`)
não impede o último step de ser avaliado isoladamente como sucesso — o `replay`
imprime `✓ SUCCESS` e `Reproduction SUCCESSFUL` com um step quebrado no meio do
caminho.

Dois problemas independentes agravam isso: (a) um token irresolvível degrada
silenciosamente para texto literal em vez de abortar o step com erro claro; (b) o
veredito final ignora o status dos steps intermediários. Ambos ainda presentes.

## 10. Achado arquitetural — `BaseAgent.run_tdd_loop` acopla nome de classe ao enum `AgentType`

**Não é um bug de comportamento em produção hoje — é um acoplamento frágil, ainda presente.**

`har_reproducer/agents/base_agent.py:157` faz `AgentType(self.__class__.__name__)`.
`AgentType` (`har_reproducer/models/session.py:7-14`) é um `Enum` cujos valores são
literalmente nomes de classe (`COOKIE = "CookieAgent"`, etc.). As 5 subclasses reais
hoje (`CookieAgent`, `HeaderAgent`, `JSONPathAgent`, `CSSAgent`, `RegexAgent`)
coincidem exatamente, então nada quebra no código atual. Mas qualquer subclasse nova
de `BaseAgent` — de produção ou um dublê de teste — cujo `__class__.__name__` não
bata byte a byte com um valor do enum faz `run_tdd_loop` lançar `ValueError`.
Descoberto durante a Etapa C (unitários finos) ao escrever dublês de teste para
`BaseAgent`. Documentado na retro de 09/08/2026 e no skill
`arquitetura-e-fundamentos`.

---

## Resumo

| # | Defeito | Status em 10/08/2026 |
|---|---|---|
| 1 | `Set-Cookie` classificado como header genérico antes de cookie, `CookieAgent` inalcançável | Ainda existe |
| 2 | `dry` não idempotente, infla extratores | Ainda existe |
| 3 | `temp_extractors/` não limpo em `dry` | Ainda existe |
| 4 | Token de corpo irresolvível por construção | Ainda existe |
| 5 | Código morto (6 símbolos) | 1 removido incidentalmente, 5 ainda existem |
| 6 | Nomes que mentem / efeitos colaterais fora de lugar (3 casos) | Ainda existe (os 3) |
| 7 | `pytest`/`pytest-httpx` em `dependencies` | Ainda existe |
| 8 | Exemplo do README inalcançável | Ainda existe |
| 9 | Token irresolvível + veredito de `replay` ignora steps intermediários | Ainda existe |
| 10 | Acoplamento nome-de-classe ↔ `AgentType` | Ainda existe (risco latente) |

Nenhuma spec de correção foi escrita ainda — esta é só a lista, por pedido explícito.
