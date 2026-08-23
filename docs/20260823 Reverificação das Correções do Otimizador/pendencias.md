# Pendências ainda abertas — levantamento consolidado em toda a `docs/`

> Complementa `relatorio.md` (mesma pasta). Aquele documento reverifica os 11 itens do
> catálogo `docs/20260817 Reteste do Otimizador contra Servidor Real/correcoes.md` — todos
> ✅. Este aqui varre o **restante** da árvore de `docs/` (16/06 a 21/08) atrás de
> pendências registradas em qualquer momento do projeto e ainda sem solução hoje
> (23/08/2026). Cada item foi conferido contra o código atual antes de entrar na lista;
> a seção final registra o que parecia pendência mas já está fechado.

## Resumo

| # | Pendência | Severidade | Origem | Onde no código |
|---|---|---|---|---|
| 1 | Redescoberta reativa: criar extrator **novo** quando o refresh não basta (candidato marcado `"Static"`, nenhum extrator jamais existiu) | Média-Alta | `correcoes.md` item 6 / item 11 (17–21/08) | `tracking/candidate_resolver.py` (`_admission_gate_rejects`), caminho de recuperação em `replay_optimizer.py`/`replay_runner.py`/`engine.py` |
| 2 | Requisição condicional (`If-None-Match`/`If-Modified-Since`) sem tratamento especial — regressão aceita, destino é o item 1 | Média | `correcoes.md` item 11 (21/08) | `tracking/candidate_resolver.py` |
| 3 | `ReplayTokenResolver._resolve_one` decide o diretório de leitura só com `origin_step in schedule` — em `--mode all` isso é sempre verdadeiro mesmo que o step de origem ainda não tenha rodado nesta execução | Média | `docs/20260805 Origem Futura de Token Dinâmico/spec.md` (05/08), "fora de escopo... fica para uma spec separada" | `replay/replay_token_resolver.py:56-61` |
| 4 | `BaselineDiff._diff_headers` usa um baseline único e fixo (step 0) sem filtrar variação normal por tipo de request — gera candidatos como `Accept` só por diferença de contexto de navegação | Baixa (impacto prático reduzido pela porta de admissão) | `docs/20260803 Origem de Token Não Determinada/spec.md` (03/08), "fica para uma spec separada" | `tracking/baseline_diff.py:25-29` |
| 5 | Extrator confirmado estático após 5 replays (`STATIC_CONFIRMATION_THRESHOLD`) só ganha um **aviso em comentário** — não é descartado nem substituído por literal automaticamente | Baixa | `docs/20260803 Reaproveitamento de Extractores/spec.md`, "fora de escopo (feature futura)" | `replay/replay_token_resolver.py` (`_record_observation`), `replay/curl_token_comment.py` (`PROBABLY_STATIC`) |
| 6 | `entries[0]` acessado sem guarda contra HAR vazio, em dois lugares | Baixa | `docs/20260810 Correções de Defeitos Catalogados/lista_de_bugs.md` item 5 | `engines/engine.py:49`, `reproduction/curl_http_transport.py:77` |
| 7 | `StepRequest.is_skippable` morto em produção — só é escrito, nunca lido fora de teste | Baixa | idem, item 5 | `models/http.py:13`, escrito em `engines/engine.py:81` |
| 8 | `ProjectConfigLoader._apply_defaults` cria `.mitmproxy/` em disco (via `Workspace.get_mitmproxy_ca_path()`) mesmo em modo `dry`, que nunca usa proxy — efeito colateral incondicional antes de checar o modo | Baixa | idem, item 6 | `config/project_config_loader.py:34-38`, chamado em `cli/cli_handlers.py:49` antes do `mode` ser lido (linha 53) |
| 9 | `ReplayRunner._run_schedule`: o veredito final só detecta divergência intermediária no caso específico `status_code == 0` — um step intermediário com status divergente porém diferente de zero não derruba `is_match` | Média — **parcialmente fechado** (o sintoma catalogado, token irresolvível → curl quebrado, foi coberto) | idem, item 9 | `replay/replay_runner.py:68-80` (`intermediate_broken`) |
| 10 | `BaseAgent.run_tdd_loop`: `AgentType(self.__class__.__name__)` acopla o nome da classe Python ao valor do enum — qualquer subclasse nova (produção ou dublê de teste) cujo nome não bata byte a byte quebra com `ValueError` | Baixa (risco latente, sem bug ativo) | idem, item 10 (achado arquitetural) | `agents/base_agent.py:161`, enum em `models/session.py` |
| 11 | README (`response_reference_dir`) descreve um fallback para `original_responses/` em workspace só-`dry` — dependia do item 2 do catálogo de 10/08 (agora fechado); **não confirmado por reprodução direta** se o exemplo é alcançável hoje | Baixa, verificação pendente | idem, item 8 — premissa mudou, status não reconfirmado | `README.md:172`, `reproduction/extractor_runner.py:23-31` |
| 12 | "Retenção genuína de candidato na fase 2 do `optimize`" nunca observada — o motivo estrutural original (login não é consumido por ninguém) não vale mais, mas a medição de hoje ainda dá `kept=[]` | Baixa, dívida de cobertura | `correcoes.md`/`relatorio.md` 17/08 §3.10 — premissa desatualizada, ver nota abaixo | `optimization/replay_optimizer.py:138-143` |
| 13 | Abort na confirmação final do `optimize` (`replay_optimizer.py:54-55`) nunca observado contra servidor real | Baixa, dívida de cobertura | idem | `optimization/replay_optimizer.py:54-55` |
| 14 | `skip_rules.methods` nunca exercitado — só a variante por scheme (`ws://`) foi coberta; nenhum HAR disponível tem `OPTIONS` | Baixa, dívida de cobertura | idem | `config` / `StepSkipEvaluator` |

---

## Detalhe por item

### 1–2. Redescoberta reativa e requisição condicional

Já registrados em `correcoes.md` (itens 6 e 11) como deliberadamente fora de escopo das
etapas de 21/08: a recuperação por divergência (item 6, ✅) só troca o **gatilho** de
quando reexecutar um extrator **existente**; criar um extrator **novo** quando isso não
resolve — porque a porta de admissão marcou o candidato como `"Static"` e nenhum
extrator jamais existiu — segue sem spec própria. O item 11 aponta o mesmo destino para
o tratamento de `If-None-Match`/`If-Modified-Since` (regressão aceita: ~84 extratores
`HeaderAgent` da gravação anterior deixaram de existir na gravação atual). Nada no
código de hoje endereça isso — confirmado por ausência de qualquer spec/etapa posterior
a 21/08-6 sobre o assunto.

### 3. `ReplayTokenResolver._resolve_one` — segunda camada de defesa da causalidade

```python
def _resolve_one(self, token_id, dependencies, schedule, ...):
    origin_step = dependencies.get(token_id)
    if origin_step in schedule:
        override_dir = replay_run_dir
    else:
        override_dir = self._reference_dir_for_step(...)
```
(`replay/replay_token_resolver.py:56-61`, texto idêntico ao citado na spec de 05/08).
Em `--mode all`, `schedule` é o conjunto de índices da run inteira — sempre contém
`origin_step` mesmo que esse step **ainda não tenha executado** no momento em que o
token é resolvido (ex.: se o step de origem falhar por um motivo alheio ao token). A
spec de 05/08 registrou isso como "fora de escopo... fica para uma spec separada"; não
apareceu nenhuma spec sobre o assunto desde então. É diretamente relevante para o
mecanismo que sustenta o item 4 do backlog de 17/08 (âncoras testadas para remoção,
reverificado em `relatorio.md` desta pasta) — vale considerar junto se algum dia for
retomado.

### 4. `BaselineDiff._diff_headers` — baseline único, sem filtro por tipo de request

```python
@staticmethod
def _diff_headers(step, baseline):
    return {f"header:{key}": value for key, value in step.request.headers.items()
            if baseline.request.headers.get(key) != value}
```
(`tracking/baseline_diff.py:25-29`, inalterado desde a citação na spec de 03/08). Gera
candidato para qualquer header que difira do step `0`, incluindo variação normal por
tipo de request (ex.: `Accept: */*` de um `fetch` vs. `Accept: text/html,...` da
navegação inicial). A spec de 03/08 já media isso como causa raiz de o `Accept` virar
candidato antes de qualquer código tocado por aquela etapa, e explicitamente adiou a
correção. **Nota de impacto:** a porta de admissão (item 11 do backlog de 17/08) reduziu
bastante o custo prático — um candidato assim, se não mudar entre épocas, cai em
`"Static"` sem nunca virar extrator nem custar uma chamada de LLM verificada; mas o
ruído na fase de descoberta (mais candidatos processados) continua existindo.

### 5. Extrator "estático após replay" só ganha aviso, não é descartado

`docs/20260803 Reaproveitamento de Extractores/spec.md` implementou o mecanismo de
observar 5 resoluções seguidas com o mesmo valor e anotar um aviso no `.curl.sh`
(`ReplayStatusPhrase.PROBABLY_STATIC`, hoje em `curl_token_comment.py:17`), mas
registrou explicitamente como fora de escopo "descartar o extractor automaticamente e
substituir o placeholder por um valor literal". Isso nunca foi retomado — o mecanismo
de hoje continua sendo só o comentário informativo.

### 6–8. Três itens residuais do catálogo de bugs de 10/08

`docs/20260810 Correções de Defeitos Catalogados/lista_de_bugs.md` catalogou 10
defeitos; 7 foram fechados por refatorações posteriores mesmo sem spec dedicada (ver
seção "Descartado" abaixo) — mas 3 continuam idênticos ao texto original:

- **`entries[0]` sem guarda contra HAR vazio**, em `engines/engine.py:49` e
  `reproduction/curl_http_transport.py:77` — um `.har` com `"entries": []` ainda
  derruba com `IndexError` cru em vez de uma mensagem clara.
- **`StepRequest.is_skippable` morto em produção** — `engines/engine.py:81` escreve o
  campo, mas nenhum código de produção o lê (só um `assert` em
  `tests/test_cli_run.py:114`).
- **`ProjectConfigLoader._apply_defaults` cria `.mitmproxy/` incondicionalmente** —
  chamado em `cli/cli_handlers.py:49`, antes de `mode` ser lido em `cli_handlers.py:53`
  — então `run --mode dry`, que nunca usa proxy, ainda cria o diretório em disco.

### 9. Veredito de `replay` — cobertura parcial de divergência intermediária

```python
intermediate_broken = any(response.status_code == 0 for _, response, _ in results[:-1])
is_match = target_matched and not intermediate_broken
```
(`replay/replay_runner.py:74-76`). Isso fecha exatamente o sintoma catalogado em 10/08
(token irresolvível → `curl: (3) nested brace in URL` → `status_code: 0` → antes
ignorado) — hoje um `status_code == 0` em qualquer step intermediário derruba
`is_match`. Mas a garantia mais ampla que o item pedia ("o veredito ignora o status dos
steps intermediários") não está totalmente fechada: um step intermediário que responda
com um status real, porém divergente do original (ex.: `500` em vez de `200`, sem cair
para `0`), ainda não derruba `is_match` — só o `status_code == 0` é checado, não
`matches_original` para cada step. Classificado como **parcialmente fechado**.

### 10. Acoplamento nome-de-classe ↔ `AgentType`

```python
agent_type=AgentType(self.__class__.__name__)
```
(`agents/base_agent.py:161`, idêntico ao citado em 10/08). As 5 subclasses de produção
continuam batendo com os valores do enum (`CookieAgent`, `HeaderAgent`, `JSONPathAgent`,
`CSSAgent`, `RegexAgent`), então não há bug ativo — mas é risco latente documentado
também em `arquitetura-e-fundamentos`.

### 11. README `response_reference_dir` — status não reconfirmado

O item 8 do catálogo de 10/08 dizia que o exemplo do README (fallback para
`original_responses/` quando um workspace só rodou `dry`) era inalcançável **porque**
dependia do item 2 (dry não escreve o `.py` do extrator) continuar quebrado. O item 2
está fechado hoje (ver "Descartado"), o que muda a premissa — mas tentar reproduzir o
cenário nesta sessão esbarrou num erro de transporte de rede anterior à resolução de
token (fixture `auth_flow.har` aponta para um host que não responde), não confirmando
nem refutando o comportamento do fallback em si. Fica como pendência de verificação, não
como defeito confirmado.

### 12–14. Dívida de cobertura do `optimize` (repetida de `correcoes.md`/`relatorio.md` 17/08 §3.10)

Três lacunas de teste nunca exercitadas contra servidor real, ainda sem mudança desde
17/08:

- **Retenção genuína de candidato na fase 2** — a justificativa original ("o único
  candidato plausível a efeito colateral necessário é o login, que ninguém consome")
  **não vale mais**: o relatório de 23/08 desta mesma pasta mede que o login (step
  `153`) hoje é consumido por um `JSONPathAgent` genuíno. Ainda assim, a medição de
  hoje contra o alvo `233` também deu `kept=[]` nas duas faixas testadas — então a
  lacuna de cobertura continua de fato aberta, só que sem uma explicação estrutural tão
  limpa quanto a de 17/08. Vale reavaliar com um alvo diferente antes de assumir que é
  estrutural de novo.
- **Abort na confirmação final** (`replay_optimizer.py:54-55`) — exige que todas as
  faixas passem individualmente e o conjunto final falhe; não ocorreu em nenhuma
  bateria até hoje.
- **`skip_rules.methods`** — nenhum HAR disponível no projeto tem `OPTIONS`; só a
  variante por scheme (`ws://`) foi coberta.

---

## Descartado — parecia pendência, já está fechado

- **Bug 1 (10/08, `CookieAgent` inalcançável)** — fechado. `TokenLocationDetector.find`
  hoje testa `_find_in_cookies` **antes** de `_find_in_headers`
  (`tracking/token_location_detector.py:12-19`), ordem invertida em relação ao texto
  catalogado.
- **Bug 2 (10/08, `dry` não idempotente)** — fechado, confirmado empiricamente nesta
  sessão: 3 rodadas de `run --mode dry` sobre o mesmo `--output` (`tests/fixtures/auth_flow.har`)
  produziram exatamente 2 extratores em todas as três, sem crescer.
- **Bug 3 (10/08, `temp_extractors/` não limpo em `dry`)** — fechado, confirmado no
  mesmo teste: 0 arquivos em `temp_extractors/` depois de 3 rodadas.
- **Bug 4 (10/08, token de corpo irresolvível por construção)** — fechado por commit
  explícito `9a28fd6 fix: bug 4 — _diff_body emite só os segmentos alterados do corpo,
  não o corpo inteiro`, no próprio dia do catálogo.
- **Bug 5, subitens `contracts.StepExecutor`, `SessionStore.get_token`/`.render_dict`,
  `raise RuntimeError` inalcançável de `StepRetryPolicy`** — todos removidos do código;
  `StepRetryPolicy` foi reescrita inteira pela etapa de recuperação por divergência
  (21/08-3), sem sobrar o trecho morto original.
- **Bug 6, subitem `MitmProxyOrchestrator.project_root`** — renomeado para `confdir`,
  nome agora condizente com o conteúdo.
- **Bug 6, subitem sleep desnecessário no último attempt** — fechado:
  `agents/base_agent.py:168-169` hoje só dorme `if attempt < total - 1`.
- **Dívida técnica do acoplamento `_mark_token_static`/regex ancorado (05/08)** —
  obsoleta: o mecanismo inteiro (`CurlDependencyParser`) foi substituído por
  `CurlTokenComment`, com cláusula delimitada por `[...]` e status humano fora dela
  (etapa de 12/08, já coberta no catálogo de 17/08 item 3.1/1 de `correcoes.md`).
- **"Separar respostas originais das reais" (adiado em 03/08)** — resolvido pela
  própria spec que registrou o adiamento (`docs/20260804 Separação de Respostas
  Originais e Reais/`).
- **"Trocar o corpus de `real_responses` para `original_responses` em `--mode main`"
  (adiado em 13/08)** — hoje `discovery_corpus` é sempre construído sobre
  `original_responses` (`engines/construction/engine_factory.py:79`), em qualquer modo,
  consistente com a decisão que a spec de 13/08 tinha adiado.
- **Item 4 do backlog de 17/08 (âncoras nunca testadas para remoção)** — fechado por
  `docs/20260821-6 Âncoras Também Testadas para Remoção/`, já coberto em detalhe no
  `relatorio.md` desta mesma pasta; não repetido aqui.
- **Docs de 16/06 a 24/07** (`Criação com agente de IA`, `Correções do codigo gerado`,
  `Anotações`, `replay_handoff.md` de `Requisições via curl`) — checados por amostragem:
  são a criação inicial do projeto e o handoff que deu origem à
  `docs/20260731 Ferramenta de Replay/`. O próprio `tracker.py` (peça central da época)
  foi "refatorado por completo" depois (`git log`, commit `e15c753`), e o projeto
  inteiro passou por reorganização de pacotes e imports absolutos na sequência. Nenhum
  item específico desses documentos foi encontrado sobrevivendo tal como escrito —
  tratados como substituídos, não como fonte de pendência viva.
