# Spec — Otimizador de Sequência Mínima de Replay

## 1. Objetivo

Depois que um fluxo já foi capturado (`run --mode main`) e reproduzido repetidamente em
modo rede (`replay --mode all`, o suficiente para o `ReplayTokenResolver` marcar os
tokens realmente estáticos via `STATIC_CONFIRMATION_THRESHOLD`,
`har_reproducer/replay/replay_token_resolver.py:11`), o `replay --mode smart`
(`har_reproducer/replay/replay_runner.py:162-175`) já reduz a lista de steps a rodar
para o subconjunto que o `CurlDependencyParser` consegue provar necessário — os steps
de onde algum token consumido pelo alvo (ou por uma dependência transitiva dele) foi
extraído.

Isso cobre só **dependências de token conhecidas**. Um step que não produz nenhum
token consumido depois (ex.: uma requisição que só teve o efeito colateral de renovar
algo no servidor) nunca aparece no grafo de dependências do `CurlDependencyParser` —
então o modo `smart` nunca o inclui, mesmo quando ele é necessário para o alvo
responder como esperado. Hoje, descobrir se esses steps "invisíveis ao grafo" são
realmente necessários é um processo manual: gerar um `steps.txt` à mão, rodar
`replay --mode list`, ver se bateu, ajustar a lista, repetir.

Esta feature adiciona um comando `optimize` que automatiza essa busca: parte do
schedule do `smart`, e para cada trecho do fluxo que o `smart` pulou, testa
empiricamente (rodando contra o servidor real) se aquele trecho pode ficar vazio, e se
não puder, remove os candidatos um a um até achar um subconjunto que ainda faz o alvo
responder como esperado. O resultado é escrito num `.txt` no formato que
`replay --mode list --steps-file` já consome (`har_reproducer/replay/replay_runner.py:187-192`).

⚠️ **O resultado é um mínimo local, não o menor subconjunto possível.** O algoritmo
(seção 3.3) só prova que nenhum candidato *isolado* pode ser removido do resultado
final — ele não testa remover combinações de dois ou mais candidatos ao mesmo tempo.
Isso é suficiente pra achar o caso comum (um step de efeito colateral que o `smart`
não via), mas não garante o menor `.txt` teoricamente possível quando dois candidatos
são redundantes *entre si* (qualquer um dos dois, sozinho, bastaria — só nenhum dos
dois sozinho é seguro remover, e testar essa combinação está fora do escopo aqui).

**Fora de escopo:**
- Provar que uma âncora do `smart` (um step de onde algum token teve origem
  confirmada) é removível. O algoritmo confia no grafo de dependências para essas —
  só busca steps *fora* dele. Ver seção 3.2 para a razão.
- Resolver o risco de efeitos colaterais não-idempotentes no servidor real durante a
  busca (ex.: um fluxo que cria um recurso novo a cada vez que uma requisição de
  escrita é repetida). O otimizador reexecuta trechos do fluxo múltiplas vezes contra
  o servidor real — é um risco assumido do usuário escolher usar o comando num fluxo
  onde isso importa, documentado na seção 5, não resolvido pela spec.
- Paralelizar tentativas (a busca é sequencial, uma tentativa por vez, na mesma sessão).

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

- **`ReplayRunner`** (`har_reproducer/replay/replay_runner.py`) — hoje só expõe 4
  métodos públicos de alto nível (`run_all`/`run_slice`/`run_smart`/`run_list`), cada
  um delegando para `_run_schedule(ordered_indexes, schedule) -> bool`
  (linhas 63-84), que:
  - executa cada índice via `_run_step` (linhas 94-121), que lê o `.curl.sh`, resolve
    tokens via `ReplayTokenResolver.resolve`, renderiza com `SessionStore.render`, e
    envia via `HttpTransport.send_request`;
  - aplica `StepRetryPolicy.execute` para recovery em `401`/`400`
    (`RECOVERABLE_STATUS_CODES`);
  - persiste cada resposta em `workspace.replay_response_file(run_id, index)`;
  - só **depois** de rodar todo o schedule, decide sucesso via
    `self.comparator.matches_original(index, response)` (linha 70) — comparação de
    `status_code` contra uma resposta de referência (`real_responses/`/
    `original_responses/`), não contra os `success_criteria` do `config.json`.
  - `_schedule_smart` (linhas 162-175) faz a expansão por dependência (BFS reverso via
    `CurlDependencyParser.parse` sobre os comentários `# Token ... comes from response
    of step N` de cada `.curl.sh`) que dá o schedule mínimo *conhecido* por token.
  - ⚠️ Nenhum desses métodos devolve as `StepResponse` intermediárias pro chamador —
    só o veredito booleano final. O otimizador precisa da `StepResponse` do alvo pra
    aplicar `Validator.validate` nela, então essa é a principal lacuna de API a
    preencher (seção 3.1).
- **`ReplayTokenResolver.resolve`** (`har_reproducer/replay/replay_token_resolver.py:25-45`)
  — já resolve um token tanto por um step "dentro do schedule atual" (lê de
  `replay_run_dir`, a resposta que acabou de ser gravada nesta mesma execução) quanto
  por um step fora do schedule (cai pro `res_refer_dir`/`original_responses_dir` via
  `_reference_dir_for_step`, linhas 84-94). Isso já é exatamente o mecanismo de
  "token fresco quando o step foi executado agora, valor de referência quando não
  foi" que o otimizador precisa — nenhuma mudança necessária aqui.
- **`CurlDependencyParser.parse`** (`har_reproducer/replay/curl_dependency_parser.py`)
  — dado o texto de um `.curl.sh`, devolve `{token_id: origin_step}`. Usado tanto pelo
  `_schedule_smart` quanto pelo `ReplayTokenResolver`; o otimizador reusa exatamente
  como está, sem mudança.
- **`Validator.validate(response: StepResponse, criteria: List[SuccessCriterion]) -> bool`**
  (`har_reproducer/validation/validator.py:19-24`) — método estático, sem estado,
  já usado hoje pelo `Engine` do comando `run` pra decidir sucesso a partir do
  `config.json` (`success_criteria`: `status_code`/`body_contains`/`url_match`/
  `html_element_present`). É a definição de sucesso que o otimizador usa pra decidir
  se um trecho pode ficar vazio — não o `ReplayResultComparator`.
- **`Workspace`** (`har_reproducer/fs_io/workspace.py`) — `curl_file`, `replay_run_dir`,
  `replay_response_file`, `response_file`/`original_response_file` já cobrem todos os
  caminhos que o otimizador precisa ler/escrever, exceto o `.txt` de saída (novo
  caminho, seção 3.4).
- **`StepRetryPolicy`**, **`SessionStore`**, **`ExtractorRunner`**,
  **`ExtractorMetadataStore`**, **`MitmProxyOrchestrator`**, **`CurlHttpTransport`** —
  reusados sem mudança, exatamente como `CliHandlers._build_replay_runner`
  (`har_reproducer/cli/cli_handlers.py:145-179`) já os monta hoje pro comando
  `replay`.
- **`CliHandlers`/`CliParser`** (`har_reproducer/cli/`) — o padrão de
  `handle_replay`/`_build_replay_subparser` (preparar workspace, resolver
  `res_refer_dir`, montar `run_id`, rodar dentro do `orchestrator.run(...)`) é o
  mesmo que `handle_optimize`/`_build_optimize_subparser` seguem (seção 3.5).

## 3. Decisões de arquitetura

### 3.1 — `ReplayRunner`: separar execução bruta do veredito por comparador

**Estado atual:** `_run_schedule` (linhas 63-84) executa o schedule inteiro e só
devolve `bool` — a decisão de sucesso (via `comparator`) e a execução (via
`_run_step`) estão fundidas no mesmo método, e as `StepResponse` intermediárias somem
depois do `_print_step_report`.

**Estado esperado depois:** extrair a parte de execução para um método público que
devolve os resultados brutos, e reescrever `_run_schedule` como uma casca fina em
cima dele:

```python
def execute_schedule(
        self, ordered_indexes: List[int], schedule: Set[int], annotate: bool = True
) -> List[Tuple[int, StepResponse]]:
    if not ordered_indexes:
        raise ValueError("ReplayRunner: schedule vazio — nenhum step para processar.")
    return [(index, self._run_step(index, schedule, annotate)) for index in ordered_indexes]

def _run_schedule(self, ordered_indexes: List[int], schedule: Set[int]) -> bool:
    results = [
        (index, response, self.comparator.matches_original(index, response))
        for index, response in self.execute_schedule(ordered_indexes, schedule)
    ]
    ...  # resto igual a hoje (_print_step_report, cálculo de is_match, etc.)
```

`_run_step` (linhas 94-121) ganha o mesmo parâmetro `annotate: bool = True`, só
repassado pra decidir se chama `_annotate_static_tokens`/`_annotate_fallback_tokens`
(linhas 104/106) — o resto do método não muda. `run_all`/`run_slice`/`run_smart`/
`run_list` continuam exatamente como hoje (chamam `_run_schedule`, que chama
`execute_schedule` com o default `annotate=True`, preservando o comportamento atual
do `replay`). `execute_schedule` é o que o `ReplayOptimizer` (seção 3.3) chama
diretamente, sempre com `annotate=False` (motivo na seção 3.6) — ele quer a
`StepResponse` do alvo pra aplicar `Validator`, não o veredito do comparador, e não
quer que a busca reescreva o `.curl.sh` do usuário como efeito colateral do volume de
tentativas.

⚠️ Cada chamada a `execute_schedule` reenvia via rede **todo** índice presente em
`ordered_indexes` — não existe hoje (nem esta decisão adiciona) um jeito de marcar um
índice como "disponível pra resolução de token mas não reexecutar". É por isso que a
estratégia de reaproveitar sessão entre tentativas (seção 3.3) depende do chamador
nunca incluir, em `ordered_indexes`, um índice cuja resposta already on disk ele quer
preservar — só em `schedule` (que é usado apenas pra decidir de qual diretório
`ReplayTokenResolver` lê o token, não pra decidir o que (re)executar).

### 3.2 — `ReplayRunner`: expor o schedule do `smart` sem executá-lo

**Estado atual:** `_schedule_smart(from_index, to_index)` (linhas 162-175) é privado
e só é chamado de dentro de `run_smart`, que já dispara a execução.

**Estado esperado depois:** renomear para público,
`compute_smart_schedule(self, from_index: Optional[int], to_index: Optional[int]) -> Tuple[List[int], Set[int]]`,
mantendo a implementação idêntica; `run_smart` passa a chamar
`self.compute_smart_schedule(...)` em vez de `self._schedule_smart(...)`. Sem mudança
de comportamento — só visibilidade, pra o `ReplayOptimizer` conseguir pedir "qual é o
schedule que o smart usaria" sem rodar nada ainda.

**Por que as âncoras do `smart` nunca são candidatas a remoção (decisão de escopo,
seção 1):** o `CurlDependencyParser` já prova, por evidência real no `.curl.sh`
(`# Token ... comes from response of step N`), que aquele step produz um valor que
outro step consome. Remover uma âncora garantidamente quebra a resolução daquele
token — não é uma hipótese a testar, é uma certeza estrutural. O que o otimizador
busca são os steps que o grafo de dependência *não* enxerga (efeito colateral no
servidor, não token), então só faz sentido testar remoção nos steps que ficam **entre**
duas âncoras consecutivas (ou entre o floor e a primeira âncora — decisão do usuário
na clarificação, ver seção 2 das respostas).

### 3.3 — Novo componente: `ReplayOptimizer`

**Contexto:** este é o componente novo que implementa a busca. Vive em
`har_reproducer/optimization/replay_optimizer.py` (pacote novo, ao lado de
`replay/`, pelo mesmo motivo de `replay/` estar ao lado de `reproduction/`: um
pipeline com responsabilidade própria, reaproveitando peças dos outros dois).

**Modelo de execução — uma sessão contínua, um `run_id`, um `replay_run_dir`:**
todo o processo de otimização usa **uma única instância** de `ReplayRunner` (logo, um
único `run_id`/`replay_run_dir`/`SessionStore`) do início ao fim. Uma vez que um
índice foi executado (sua resposta está em `replay_run_dir/res_NNNN.json`), ele
continua disponível como origem de token/valor sem precisar ser reexecutado — basta
continuar incluindo seu índice em `schedule` nas chamadas seguintes a
`execute_schedule`, sem incluí-lo em `ordered_indexes`.

**Terminologia:**
- **âncoras** (`A = [a_0, ..., a_n]`, `a_n = to_index`) — o schedule ordenado
  devolvido por `compute_smart_schedule(from_index, to_index)` (seção 3.2), sempre
  mantidas, nunca candidatas a remoção.
- **faixa** — o intervalo `(L, R)` entre duas âncoras consecutivas (`L = a_i`,
  `R = a_{i+1}`), ou entre `from_index` e `a_0` (a "faixa inicial", se
  `from_index < a_0`).
- **candidatos de uma faixa** — os índices de step que existem no workspace
  (`ReplayRunner._existing_step_indexes()`) estritamente entre `L` e `R`.
- **backbone** — o conjunto `[from_index .. B]`, onde `B = a_{n-1}` se existir mais de
  uma âncora (`n >= 1`), ou `B = from_index` se `A = [to_index]` for a única âncora
  (`n = 0` — ver ⚠️ abaixo). Estabelecido **uma única vez**, na Fase 1, e nunca
  reexecutado depois (exceto pela recuperação reativa) — é o que sustenta o resto da
  busca.
- **`kept`** — conjunto global, que só cresce, dos candidatos já confirmados
  necessários por alguma faixa já processada.

**Ordem de processamento — do alvo para o `from_index` (a ordem original proposta
pelo usuário; ver justificativa no final desta seção):**
faixa `(a_{n-1}, a_n)` primeiro, depois `(a_{n-2}, a_{n-1})`, ..., até
`(a_0, a_1)`, e por fim `(from_index, a_0)` se existir.

**Fase 1 — validação inicial + backbone fresco (uma única vez, antes de testar
qualquer faixa):**
Chamar `execute_schedule` (com `annotate=False`, seção 3.6) com
`ordered_indexes = [from_index .. B]` (todos os índices existentes nesse range —
âncoras e candidatos de todas as faixas exceto a última). Isso faz os efeitos
colaterais reais de toda essa região acontecerem de verdade no servidor **uma única
vez**, e persiste essas respostas no `replay_run_dir` desta mesma execução —
disponíveis via `schedule` (nunca mais reexecutados) para o resto da busca. O alvo
(`to_index`) está fora desse range, então a primeira checagem de sucesso de fato só
acontece já na Fase 2, ao testar a faixa mais próxima dele.

⚠️ Isto significa que os candidatos da faixa mais próxima do alvo (`(a_{n-1}, a_n)`,
ou `(from_index, to_index)` no caso degenerado de âncora única) — que é a **primeira**
faixa processada na ordem da Fase 2, não a última — são os únicos que **nunca**
rodam antes de serem testados: a Fase 1 deliberadamente para antes deles. Para todas
as outras faixas (processadas depois dela, mais próximas do `from_index`), seus
candidatos já rodaram uma vez, de verdade, na Fase 1, antes de a busca começar a
testar se são necessários.

⚠️ **Caso degenerado — `A = [to_index]` (n = 0), `from_index < to_index`:**
`compute_smart_schedule` pode devolver uma única âncora quando nenhuma dependência de
token do alvo aponta para um `origin_step >= from_index` — plausível, e já
reconhecido na seção 5 sob outro ângulo ("token cuja origem está fora do range"). Sem
`a_{n-1}`, `B = from_index` (não vazio) — ou seja, a Fase 1 ainda roda pelo menos o
próprio `from_index` ao vivo antes de testar a única faixa existente,
`(from_index, to_index)`. Isso preserva a garantia central da seção 5 ("tudo à
esquerda de `L` já rodou de verdade") mesmo neste caso — a alternativa (backbone
vazio) reabriria exatamente o falso-aborto que a Fase 1 existe para eliminar.

**Fase 2 — por faixa, na ordem acima:**

1. **Atalho de duas pontas:** `C = ∅`. Monta
   `ordered_indexes = sorted(dedup({R} ∪ kept_de_faixas_já_processadas ∪ {to_index}))`
   — nunca inclui `L` nem nada à esquerda dele (já coberto pelo backbone da Fase 1 ou
   por uma faixa já decidida). `schedule = backbone ∪ kept_de_faixas_já_processadas ∪
   ordered_indexes`. Chama `execute_schedule`, pega a `StepResponse` de `to_index`,
   aplica `Validator.validate(response, project_config.success_criteria)`.
   - Sucesso → faixa resolvida com 0 candidatos extras. Próxima faixa.
2. **Sem atalho, roda a faixa inteira:** `C = candidatos(L, R)` inteiro. Mesmo teste.
   - Falhou de novo → **aborta** (seção 5). Neste ponto isso é um sinal real de
     problema, não um falso positivo: a Fase 1 já garantiu que tudo à esquerda de `L`
     rodou de verdade contra o servidor antes deste teste.
3. **Eliminação regressiva, um candidato por vez, do mais próximo de `R` para o mais
   próximo de `L`:** para cada candidato `c` de `C`, nessa ordem, tenta remover
   (`C' = C - {c}`, monta `ordered_indexes`/`schedule` do mesmo jeito do passo 1 com
   `C'` no lugar de `∅`), roda de novo.
   - Sucesso → `c` sai de `C` permanentemente.
   - Falha → `c` volta pra `C` (é necessário) e segue pro próximo candidato.
4. Faixa concluída: `kept += C` (sobreviventes). Próxima faixa.

**Recuperação reativa — dá ao "token/sessão ficou stale" uma chance de se corrigir
antes de aceitar a falha como resultado do teste:** se, em qualquer chamada de
`execute_schedule` (Fase 1 ou Fase 2), algum step do schedule vier com `status_code`
em `StepRetryPolicy.RECOVERABLE_STATUS_CODES ∪ {0}` (`400`/`401`/falha de transporte)
mesmo depois do retry padrão que `_run_step` já tenta, o `ReplayOptimizer` reexecuta a
Fase 1 (o backbone inteiro, de novo) e repete a tentativa atual do zero. Limite de 2
refreshes desse tipo por tentativa.

⚠️ **Isto não distingue "sessão desatualizada" de "candidato removido era mesmo
necessário e o servidor reagiu com 400/401/erro de transporte"** — as duas causas se
manifestam de forma idêntica, e a spec não tem como diferenciá-las a priori. Por isso,
depois de esgotar os 2 refreshes, o resultado da tentativa **não é tratado como um
erro especial** — cai de volta no fluxo normal da Fase 2: se a falha persiste no
atalho/faixa-inteira, é o abort padrão da seção 5 ("faixa inteira falha"); se persiste
numa eliminação individual, o candidato `c` é restaurado como necessário (passo 3,
"Falha → `c` volta pra `C`"), exatamente como qualquer outra falha de critério. O
refresh só existe pra dar uma chance de correção quando a causa *é* staleness — quando
não é, o pior caso é gastar 2 tentativas extras antes de chegar à conclusão correta de
qualquer forma, não um diagnóstico errado permanente.

**Depois de todas as faixas processadas:** montar a lista final ordenada
(`from_index` ∪ todas as âncoras ∪ `kept`) e rodar **uma última confirmação** —
`execute_schedule` sobre a lista final inteira, do zero, `Validator.validate` no
alvo. Só escreve o `.txt` de saída (seção 3.4) se essa confirmação passar; se falhar,
aborta sem escrever o arquivo (seção 5).

**Por que a ordem é do alvo para o `from_index`, e não o contrário:** a alternativa
óbvia (processar do `from_index` pro alvo) evitaria a Fase 1 rodar candidatos ainda
não testados — mas troca esse ganho por um problema pior: cada faixa testada
precisaria, pra checar o alvo, arrastar consigo o restante do fluxo **ainda não
decidido** à direita (sem cortes, porque nada ali foi testado ainda), repetindo esse
sufixo completo em cada tentativa de cada faixa. Do alvo pro `from_index`, com a Fase
1 cobrindo o backbone de uma vez, cada faixa só arrasta consigo `kept` das faixas *já
decididas*.

⚠️ Isso é **nunca pior, e tipicamente melhor** — não uma garantia incondicional de
"estritamente mais barato". No cenário em que quase todo candidato acaba sendo
necessário, `kept` cresce e se aproxima do tamanho total já processado, convergindo
para o mesmo custo que a alternativa rejeitada teria no ponto simétrico — ver seção
3.7 para como isso afeta a estimativa de custo.

### 3.4 — `Workspace`: caminho do `.txt` de saída do otimizador

**Estado atual:** `Workspace` não tem nenhum método para um caminho de "lista de
steps otimizada" — o `--steps-file` de `replay --mode list` hoje sempre aponta pra um
arquivo que o usuário escreveu à mão em outro lugar.

**Estado esperado depois:** novo método,

```python
def optimized_steps_file(self, run_id: str) -> Path:
    return self.replays / f"optimized_{run_id}.txt"
```

ao lado dos outros métodos de caminho de `Workspace`. Um arquivo por `run_id` (mesmo
padrão de `replay_run_dir`/`replay_response_file`) — não sobrescreve uma otimização
anterior. `handle_optimize` (seção 3.5) aceita um `--steps-out <path>` opcional que,
se informado, escreve nesse caminho em vez do default.

### 3.5 — CLI: novo comando `optimize`

**Estado atual:** `CliParser.build` (`har_reproducer/cli/cli_parser.py:15-23`) monta 3
subcomandos (`parse`/`run`/`replay`); `CliHandlers` tem um `handle_*` por subcomando.

**Estado esperado depois:** quarto subcomando, seguindo o mesmo padrão de preparação
de workspace/config de `handle_replay` (`har_reproducer/cli/cli_handlers.py:107-126`):

```
har-reproducer optimize --output <dir> --to <int> [--from <int>] [--config <path>]
                         [--steps-out <path>] [--success-criteria <json>] [--max-requests <int>]
```

- `--output` (obrigatório) — mesmo workspace já usado por `run`/`replay` (precisa ter
  `curls/` e a `response_reference_dir` já populados).
- `--to` (obrigatório) — índice do step alvo (equivalente ao `--to` do
  `replay --mode smart`).
- `--from` (opcional, default `0`) — mesmo papel do `--from` do `smart`: piso que
  nenhuma âncora nem faixa cruza. Validado contra os índices existentes no workspace
  (mesma checagem que hoje falta em `_schedule_smart` pro `from_index` — ver seção 5).
- `--config` (opcional) — mesmo `config.json`; é de onde vem `success_criteria` por
  padrão (o `Validator` da seção 2) — **obrigatório ter `success_criteria` não vazio**
  a menos que `--success-criteria` seja informado, ver seção 5.
- `--success-criteria` (opcional) — uma lista JSON inline de `SuccessCriterion`
  (mesmo formato de `success_criteria` do `config.json`, ex.:
  `'[{"type":"status_code","expected":200},{"type":"body_contains","expected":"ok"}]'`),
  que **sobrescreve** os `success_criteria` do `config.json` só para esta chamada —
  lista, não item único, pelo mesmo motivo de `ProjectConfig.success_criteria` já ser
  `List[SuccessCriterion]` e `Validator.validate` já iterar essa lista com semântica
  AND (`har_reproducer/validation/validator.py:19-24`): restringir a CLI a um único
  critério não pouparia implementação e obrigaria o usuário a escolher só uma
  dimensão de verificação exatamente no caso em que mais precisa de precisão. Existe
  porque os critérios do `config.json` normalmente descrevem o destino *final* do
  fluxo — se `--to` apontar pra um step intermediário, aqueles critérios podem nunca
  bater com aquele step mesmo com a faixa "certa", e essa flag evita ter que editar o
  `config.json` a cada `--to` diferente que o usuário queira investigar.
- `--steps-out` (opcional) — caminho do `.txt` de saída; default
  `workspace.optimized_steps_file(run_id)` (seção 3.4).
- `--max-requests` (opcional, default `500`) — teto de requisições de rede reais
  (contando Fase 1 + toda a Fase 2 + refreshes reativos + confirmação final) que a
  busca pode disparar antes de abortar. Ver seção 3.7.

`handle_optimize` monta o `ReplayOptimizer` com os mesmos componentes que
`_build_replay_runner` já monta pro `ReplayRunner` (`SessionStore`, `ExtractorRunner`,
`CurlDependencyParser`, `StepRetryPolicy`, `CurlHttpTransport`), dentro do mesmo
`orchestrator.run(...)` (mitmproxy) que `handle_replay` já usa — nenhum transporte
novo, nenhum modo dry novo. `ExtractorMetadataStore` é montado de forma diferente —
ver seção 3.6.

### 3.6 — Isolar a busca de dois efeitos colaterais de disco: metadata store e anotação do `.curl.sh`

**Estado atual — dois mecanismos distintos gravam no workspace do usuário como
efeito colateral de rodar um step, e os dois são acionados por qualquer chamada a
`_run_step`:**
1. `ReplayTokenResolver._record_observation`
   (`har_reproducer/replay/replay_token_resolver.py:96-106`) incrementa `valid_count`
   (ou marca `ever_changed`) em `ExtractorMetadataStore` a cada token resolvido, e
   persiste isso em disco.
2. Depois de `STATIC_CONFIRMATION_THRESHOLD = 5` observações estáveis,
   `ReplayRunner._annotate_static_tokens`/`_annotate_fallback_tokens` (linhas
   123-139), chamadas de dentro de `_run_step` (linhas 104/106) **sempre que o
   resolver devolve `STATIC`/`CAPTURED_FALLBACK`**, escrevem diretamente no
   `.curl.sh` do usuário (`- probably static`/`- could not extract value...`).

**Problema:** o `ReplayOptimizer` chama `ReplayTokenResolver.resolve` — logo,
`_record_observation` — dezenas ou centenas de vezes numa única busca (uma vez por
token, por tentativa, em cada faixa). Isso infla o contador de observações numa
escala que não tem relação com uso real repetido do usuário. ⚠️ Neutralizar só o
mecanismo 1 (ex.: um `ExtractorMetadataStore` cujo `save` é *no-op*) **não é
suficiente**: `_record_observation` decide `STATIC` a partir do `valid_count` já
persistido em disco **antes** da busca começar (lido via `load`, que continua
funcionando normalmente) mais 1 — se um token já estiver a uma observação do
threshold (bem plausível depois do uso normal de `replay --mode all` que a seção 1
já exige como pré-requisito), a **primeira** chamada de `resolve` dentro do
`ReplayOptimizer` já dispara a anotação no `.curl.sh` real, via `ReplayRunner`, não
via `ExtractorMetadataStore` — independente do `save` ser no-op ou não.

**Estado esperado depois — os dois mecanismos precisam ser neutralizados:**
1. `handle_optimize` monta o `ReplayTokenResolver` do `ReplayOptimizer` com uma
   variante de `ExtractorMetadataStore` cujo `save` é *no-op* (lê normalmente via
   `load`, nunca persiste incremento de `valid_count`/`ever_changed` em disco) — evita
   que o *contador* infle além do que o uso real do usuário já produziu.
2. `ReplayOptimizer` chama `execute_schedule` sempre com `annotate=False` (seção
   3.1) — o novo parâmetro que suprime as chamadas a `_annotate_static_tokens`/
   `_annotate_fallback_tokens` dentro de `_run_step`, independente do que o resolver
   decidir. Isso evita a reescrita do `.curl.sh` em si, não só do contador que a
   alimenta.

Com os dois em vigor, o `.curl.sh` do usuário e o `extract_*.meta.json` de cada
extractor saem da busca exatamente como entraram — a busca só *lê* metadados já
existentes, nunca os altera.

### 3.7 — Salvaguarda de custo: estimativa prévia e teto de requisições

**Contexto:** o custo de rede da busca não é fixo — cada faixa reexecuta `R` +
`kept` das faixas já processadas + candidatos sendo testados, uma vez por tentativa
(atalho + faixa inteira + até `N` eliminações), e `kept` cresce a cada faixa
concluída (seção 3.3). Como cada requisição pode ter efeito colateral real num
servidor de produção (seção 1, fora de escopo), rodar isso sem noção do tamanho é um
risco desnecessário.

**Estado esperado depois:** antes da Fase 1, `ReplayOptimizer` calcula e imprime uma
estimativa de **pior caso** (nada é removido em nenhuma faixa) que contabiliza o
crescimento de `kept`, não só o tamanho isolado de cada faixa:

```
custo(faixa_i) ≈ (k_i + 2) × (k_i + kept_acumulado_i + 2)
estimativa_total ≈ |backbone| + Σ custo(faixa_i), onde kept_acumulado_i = Σ_{j<i} k_j
```

(`k_i` = nº de candidatos da faixa `i`, faixas contadas do alvo pro `from_index`,
mesma ordem da Fase 2). `(k_i + 2)` é o número de tentativas no pior caso (atalho +
faixa inteira + até `k_i` eliminações, nenhuma removida); `(k_i + kept_acumulado_i +
2)` é o tamanho de cada uma dessas tentativas no pior caso — não só o tamanho do
atalho (`kept_acumulado_i + 2`), já que a faixa inteira e cada eliminação também
incluem os próprios candidatos da faixa (`C`/`C'`) em `ordered_indexes`/`schedule`
(seção 3.3, passos 2-3). O termo `kept_acumulado_i` é o que faz a estimativa crescer
mais que linearmente quando há muitas faixas com muitos candidatos — reflete
diretamente o cenário descrito na seção 3.3 em que quase todo candidato acaba sendo
necessário.

⚠️ Esta estimativa **não** inclui o custo de refreshes reativos (seção 3.3) —
imprevisíveis por natureza (dependem de quantas vezes a sessão realmente expira
durante a busca) **e desproporcionalmente caros**: cada refresh reexecuta o backbone
inteiro (`|backbone|` requisições), não um número fixo pequeno — então num servidor
instável, cada tentativa que bate um `400`/`401`/erro de transporte pode custar até
`2 × |backbone|` requisições extras antes de cair de volta no resultado normal. A
estimativa impressa deixa essa omissão explícita (em vez de fingir precisão que não
tem) e recomenda calibrar `--max-requests` com folga acima do pior caso "sem
refresh" quando o backbone for grande.

Se o já executado (contando refreshes reativos, que **contam** para
`--max-requests` mesmo não entrando na estimativa impressa) ultrapassar
`--max-requests` (seção 3.5) em qualquer ponto da busca, aborta imediatamente com uma
mensagem indicando quantas requisições já foram feitas e o teto configurado — nunca
silenciosa, sempre com o número real na tela.

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `ReplayRunner` | novo método público `execute_schedule(ordered_indexes, schedule, annotate=True)` (execução bruta, sem veredito; `annotate=False` suprime a anotação do `.curl.sh`); `_run_step` ganha o mesmo parâmetro `annotate`; `_schedule_smart` → `compute_smart_schedule` (público); `_run_schedule` passa a delegar pra `execute_schedule` |
| `Workspace` | novo método `optimized_steps_file(run_id)` |
| `ReplayOptimizer` (novo) | `har_reproducer/optimization/replay_optimizer.py` — orquestra a busca faixa a faixa, Fase 1 + Fase 2 (seção 3.3), sempre com `annotate=False`, com estimativa/teto de requisições (seção 3.7) |
| `ExtractorMetadataStore` | variante "silenciosa" (sem persistir observação) usada só pelo `ReplayOptimizer` — só resolve o contador; a anotação do `.curl.sh` é suprimida separadamente via `annotate=False` (seção 3.6) |
| `CliParser` | novo subcomando `optimize` (`--output`/`--to`/`--from`/`--config`/`--success-criteria`/`--steps-out`/`--max-requests`) |
| `CliHandlers` | novo `handle_optimize`, seguindo o padrão de `handle_replay` |

## 5. Casos de borda e comportamento de erro

- **Faixa inteira falha mesmo com todos os candidatos incluídos (depois de esgotar os
  2 refreshes reativos, seção 3.3)** — aborta a otimização, reporta a faixa (`L`,
  `R`) e a `StepResponse` do alvo obtida, e não escreve `.txt`. Com a Fase 1 já tendo
  executado o backbone inteiro antes de qualquer faixa ser testada (seção 3.3, exceto
  no caso degenerado abaixo), isto **não** é um falso positivo causado por uma faixa
  vizinha ainda não decidida — é um sinal real de que a causa está dentro desta
  faixa, na âncora `R`, numa incompatibilidade entre `--to` e `success_criteria` (ver
  item abaixo), ou no servidor genuinamente indisponível.
- **`A = [to_index]` — âncora única, `from_index < to_index` (caso degenerado, seção
  3.3)** — sem `a_{n-1}`, o backbone da Fase 1 usa `B = from_index`, garantindo que
  `from_index` ainda rode ao vivo antes da única faixa existente ser testada. Sem
  essa regra, o backbone ficaria vazio e reabriria o falso-positivo que a Fase 1
  existe para eliminar.
- **Confirmação final falha depois de todas as faixas passarem individualmente** —
  mesmo tratamento: aborta, não escreve `.txt`, reporta a última faixa concluída com
  sucesso. Cenário possível: expiração de sessão entre o fim da última faixa
  processada e a confirmação — coberto pela mesma recuperação reativa da seção 3.3
  (tenta reestabelecer o backbone e confirmar de novo, até o limite de 2 refreshes).
- **`success_criteria` vazio no `config.json` e nenhum `--success-criteria`
  informado** — `Validator.validate` com lista vazia devolve `True` trivialmente
  (nenhum critério pra falhar), o que faria o otimizador aceitar qualquer resposta do
  alvo como "sucesso", inclusive um `500`. `handle_optimize` valida isso antes de
  começar e recusa rodar (`ValueError`) nesse caso, em vez de silenciosamente devolver
  a lista mínima "vazia" (só o alvo).
- **`success_criteria` do `config.json` não faz sentido pro `--to` escolhido** (ex.:
  critério pensado pro destino final do fluxo, `--to` aponta pra um step
  intermediário) — não detectável automaticamente; é exatamente o caso de uso do
  `--success-criteria` inline (seção 3.5). Sem ele, o comportamento observado é
  "toda faixa falha, incluindo com todos os candidatos" — mesmo sintoma do item
  anterior, causa diferente; a mensagem de abort deveria sugerir checar
  `--success-criteria` quando isso acontecer já na primeira faixa testada.
- **Faixa sem candidatos** (`R == L + 1`, âncoras adjacentes no HAR original) — não há
  nada a testar; a faixa é resolvida com `C = ∅` sem nenhuma chamada de rede
  extra além do atalho de duas pontas (passo 1 da Fase 2, seção 3.3), que nesse caso é
  literalmente a única tentativa possível.
- **`to_index == from_index`** (nenhuma faixa chega a existir, backbone da Fase 1 é
  vazio) — a lista final é só `[to_index]`; se a resposta desse único step já não
  bate com `success_criteria`, falha imediatamente (não há o que otimizar num alvo
  que já falha isolado).
- **Steps faltando no workspace** (`to_index` fora do range existente, ou pulado por
  `skip_rules`) — mesma validação que `ReplayRunner._require_all_existing` já faz
  hoje pros outros modos: erro explícito. **`from_index` inexistente no workspace**
  não é validado hoje por `_schedule_smart`/`compute_smart_schedule` (ele só age como
  corte numérico no BFS) — `handle_optimize` adiciona essa validação explicitamente
  antes de montar a Fase 1, já que aqui `from_index` também delimita o backbone que
  será executado ao vivo, não só um corte de busca.
- **Teto de `--max-requests` atingido** — aborta imediatamente, sem escrever `.txt`,
  reportando quantas requisições já foram feitas e o teto configurado (seção 3.7).
  Não é tratado como falha de busca — é uma parada por orçamento, distinta das
  outras categorias de abort desta seção.
- **Efeitos colaterais não-idempotentes no servidor real durante a busca** — cada
  faixa pode reexecutar o mesmo trecho do fluxo várias vezes (uma por candidato
  testado); se algum desses steps tiver efeito colateral não-idempotente (criar um
  registro novo a cada chamada, por exemplo), o otimizador vai gerar esse efeito
  colateral várias vezes durante a busca. Limitação aceita e documentada, não
  resolvida por esta spec — mesma categoria de risco que já existe hoje em
  `run`/`replay` contra um servidor real, só que com mais repetições.
- **Token cuja origem está fora do range `[from_index, to_index]` inteiro** (origem
  antes do próprio `from_index`) — mesmo comportamento que `ReplayTokenResolver` já
  tem hoje pra qualquer step fora do schedule: cai pro `res_refer_dir`/
  `original_responses_dir` (valor de referência, não fresco). Sem mudança — é o
  mesmo trade-off que `smart`/`slice` já aceitam quando o `--from` corta uma
  dependência real.

## 6. Referência

Implementação segue `guia_de_estilo.md`/[[guia-de-estilo]] como padrão obrigatório.
