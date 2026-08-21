# Spec — Extrator Literal Não Vira Âncora

## 0. Sumário

Quando o projeto não consegue aprender a recalcular um valor, ele guarda o valor literal
dentro de um extrator e anota no `.curl.sh` uma linha dizendo de qual step o valor veio e
que ele está congelado. Quem calcula o schedule do `replay --mode smart` lê a primeira
metade dessa linha e ignora a segunda: trata o step de origem como **âncora** e o arrasta
para dentro do replay, embora o extrator vá devolver o mesmo literal com ou sem aquele
step. Medido, **89% a 96% das linhas de dependência dos workspaces são desse tipo**, e
eliminá-las como âncora derruba o replay de um alvo típico de 2,38 para 1,03 requisições
(gravação atual) e de 6,48 para 1,32 (gravação anterior). A correção não descarta extrator
nenhum, não muda o formato do `.curl.sh`, não exige regerar workspace, e vale para os
workspaces que já estão em disco.

### Glossário

| termo | significado nesta spec |
|---|---|
| **extrator recalculável** | Extrator cujo código lê a resposta do step de origem e deriva o valor dela (`CookieAgent`, `HeaderAgent`, `JSONPathAgent`, `CSSAgent`, `RegexAgent`). Executá-lo com a resposta fresca dá um valor diferente de executá-lo com a resposta congelada. |
| **extrator literal congelado** | Extrator cujo código é `return '<valor gravado no HAR>'` (`AgentType.LITERAL`, quando a localização do valor na resposta não foi determinada, e `AgentType.LITERAL_FALLBACK`, quando o agente esgotou as tentativas). Devolve o mesmo valor independentemente de qual resposta esteja em disco. |
| **linha de dependência** | Comentário `# [Token <id> comes from response of step <N>]` no topo do `.curl.sh`, opcionalmente seguido de frases de status. É a única fonte de âncora do projeto. |
| **âncora** | Step de origem que o `replay --mode smart` puxa para o schedule por causa de uma linha de dependência, transitivamente. Cada âncora é uma requisição extra em todo replay que passe por aquele curl. |
| **frase de status de origem** | Sufixo da linha de dependência que declara que o valor ficou literal: `origin location undetermined — using literal captured value` ou `origin location determined but extraction exhausted — using literal captured value` (`OriginStatusPhrase`). |
| **frase de status de replay** | Sufixo distinto, escrito pelo `replay` depois de executar (`probably static`, `could not extract value from response, using captured value` — `ReplayStatusPhrase`). **Não** indica extrator literal e não pode ser confundido com o anterior. |

Os números deste documento são reproduzíveis com `medir_ancoras.py`, nesta mesma pasta.

---

## 1. Objetivo

### 1.1 O problema

`ReplayRunner._expand_pending` (`har_reproducer/replay/replay_runner.py:175-183`) monta o
schedule do `--mode smart` assim:

```python
curl_text: str = self.workspace.curl_file(current).read_text(encoding="utf-8")
dependencies: Dict[str, int] = self.curl_token_comment.parse(curl_text)
for origin_step in dependencies.values():
    if origin_step >= floor and origin_step not in schedule and origin_step in existing_set:
        schedule.add(origin_step)
        pending.add(origin_step)
```

`CurlTokenComment.parse` (`replay/curl_token_comment.py:66-70`) casa apenas a cláusula
`# [Token <id> comes from response of step <N>]` e devolve `{token_id: origin_step}`,
**descartando o sufixo da linha**. Só que o sufixo é justamente onde está escrito que o
valor não é recalculável. Um `.curl.sh` real do workspace de referência:

```
# [Token 19ca0711b31b0813fdab80694bdc28b1 comes from response of step 0005] origin location undetermined — using literal captured value
```

O extrator desse token é `AgentType.LITERAL`: seu código é `return 'PLAINVAL777'`. Ele
devolve `PLAINVAL777` esteja o step 5 no schedule ou não. Mesmo assim o step 5 entra no
schedule, é executado contra a rede, e o replay do step 6 custa 2 requisições em vez de 1.

### 1.2 O tamanho do problema, medido

Três workspaces, todos com as duas metades da conta:

| workspace | linhas de dependência | → recalculáveis | âncoras | curls com âncora | `smart` médio |
|---|---|---|---|---|---|
| `arquivos-har/ws_20260817_main` (HAR de 324 entries) | 254 | **11** (96% congelados) | 8 → 5 | 219/320 → 7/320 | 2,38 → **1,03** |
| outra execução do mesmo HAR | 254 | **8** (97% congelados) | 8 → 4 | 219/320 → 4/320 | 2,38 → **1,02** |
| HAR anterior (238 entries) | 865 | **93** (89% congelados) | 69 → 65 | 232/235 → 68/235 | 6,48 → **1,32** |

"`smart` médio" é a média do tamanho do schedule sobre **todos** os alvos possíveis do
workspace, calculada com a mesma expansão transitiva de `_expand_pending`. No workspace de
referência, **213 dos 320 alvos** têm o schedule reduzido; na gravação anterior, 232 de 235.

Exemplos do workspace de referência:

```
alvo 82: [0, 23, 75, 82] -> [82]
alvo 87: [23, 75, 87]    -> [87]
alvo 14: [1, 14]         -> [14]
```

⚠️ **A proporção de literais congelados não é estável entre execuções do mesmo HAR**, e
isso é um argumento a favor desta etapa, não contra. As duas execuções da tabela diferem
porque o laço TDD dos agentes é não-determinístico (há LLM no caminho quando
`config.json` o configura): uma produziu `{HeaderAgent 4, CSSAgent 3, RegexAgent 4,
LiteralAgent 4, LiteralFallbackAgent 2}` e a outra `{HeaderAgent 4, RegexAgent 4,
LiteralAgent 4, LiteralFallbackAgent 5}` — três valores que uma execução aprendeu a
extrair, a outra congelou. Hoje isso significa que **o custo do replay de um alvo depende
de quanto o agente conseguiu naquele dia**, o que não deveria ser verdade para um valor
que ficou literal nos dois casos.

### 1.3 Por que isso é o problema certo para atacar primeiro

A linha de dependência de um extrator literal congelado é a única coisa que faz um step
entrar no schedule sem nenhum efeito sobre o resultado. Não há trade-off: o valor entregue
ao request é bit a bit o mesmo com e sem a âncora, porque o código do extrator não olha a
resposta. É corrigir uma incoerência interna, não escolher entre dois comportamentos.

### 1.4 Fora de escopo

- **Deixar de criar o extrator literal.** Ele continua sendo criado, registrado e
  executado, e a linha de dependência continua no `.curl.sh`. O que muda é só quem a lê
  como âncora. Decidir se um valor comprovadamente obsoleto deveria virar extrator é
  assunto da etapa de porta de admissão, registrada em
  `docs/20260817 Reteste do Otimizador contra Servidor Real/correcoes.md`.
- **Mudar o formato do `.curl.sh`.** Ver 3.3: a informação necessária já está na linha, e
  não mudar o formato é o que faz esta etapa valer para os workspaces já em disco.
- **`replay --mode all/slice/list`.** Não usam âncora; nada muda.
- **Ajustar `--max-requests` do `optimize`.** A estimativa de pior caso muda de valor
  (3.5); calibrar o limite não faz parte daqui.
- **Requisição condicional.** Na gravação anterior, 63 âncoras de `If-None-Match` e 21 de
  `If-Modified-Since` são extratores **recalculáveis** e continuam sendo âncora, como
  devem. Esta etapa não os toca.

---

## 2. Componentes existentes reaproveitados (estado atual, não redesenhar)

### `CurlTokenComment` — `har_reproducer/replay/curl_token_comment.py` (109 linhas)

Dono do formato dos comentários. Três enums de frase (`DependencyPhrase` `:7-8`,
`OriginStatusPhrase` `:11-13`, `ReplayStatusPhrase` `:16-18`), dois padrões
(`DEPENDENCY_PATTERN` `:26-31`, `UNRESOLVED_PATTERN` `:33-36`) e a composição
clause + frases separadas por `CATEGORY_SEPARATOR = "; "`.

```python
DEPENDENCY_PATTERN: ClassVar[Pattern[str]] = re.compile(
    r"^# \[Token (?P<token_id>[a-z0-9]+) "
    rf"{re.escape(DependencyPhrase.COMES_FROM_STEP.value)} "
    r"(?P<origin_step>\d+)\]",
    re.MULTILINE,
)

def parse(self, curl_text: str) -> Dict[str, int]:
    return {
        match.group("token_id"): int(match.group("origin_step"))
        for match in self.DEPENDENCY_PATTERN.finditer(curl_text)
    }
```

`_split_clause_and_status` (`:72-76`) e `_categorize` (`:78-88`) **já sabem** separar a
cláusula das frases e classificar cada frase em `OriginStatusPhrase` ou
`ReplayStatusPhrase`. É esse maquinário que a decisão 3.1 reaproveita — não há parser novo
a escrever.

### `CurlGenerator._token_comments` / `_origin_status` — `har_reproducer/reproduction/curl_generator.py:61-79`

```python
@staticmethod
def _origin_status(token: DynamicToken) -> Optional[OriginStatusPhrase]:
    if token.origin_location is None:
        return OriginStatusPhrase.UNDETERMINED
    if token.extraction_exhausted:
        return OriginStatusPhrase.EXTRACTION_EXHAUSTED
    return None
```

Importa porque estabelece a **equivalência exata** que esta etapa usa: a frase de status de
origem está presente na linha se e somente se o extrator é literal congelado. Do outro
lado, `CandidateResolver._generate_extractor`
(`har_reproducer/tracking/candidate_resolver.py:172-190`) só produz literal por esses dois
caminhos — `origin_location is None` → `AgentType.LITERAL`; agente esgotado →
`extraction_exhausted = True` e `AgentType.LITERAL_FALLBACK`. Não existe terceiro caminho
para literal, nem caminho para um extrator recalculável carregar a frase.

### `ReplayRunner.compute_smart_schedule` / `_expand_pending` — `har_reproducer/replay/replay_runner.py:160-183`

Ponto único de expansão de âncora. `compute_smart_schedule` parte do alvo e expande
transitivamente pelas dependências de cada curl já no schedule, respeitando o piso
`--from` e a existência do step. É o único chamador de `parse` no ramo de schedule.

### `ReplayRunner._apply_replay_status` — `har_reproducer/replay/replay_runner.py:140-147`

Acrescenta `ReplayStatusPhrase` a uma linha já existente, casando por
`f"# [Token {token_id} "`. Importa como armadilha: depois de um replay, uma mesma linha
pode carregar **duas** frases (`origin_status; replay_status`), e a distinção entre elas é
o que a decisão 3.1 não pode errar.

### `ReplayTokenResolver.resolve` / `_resolve_one` — `har_reproducer/replay/replay_token_resolver.py:25-67`

```python
dependencies: Dict[str, int] = self.curl_token_comment.parse(curl_text)
token_ids: Set[str] = set(SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text))
```

⚠️ Load-bearing para o escopo desta etapa: a lista de tokens a resolver vem dos
**placeholders do curl**, não das dependências. `dependencies` serve só para escolher o
diretório de resposta em `_resolve_one` (`:47-67`). Por isso 3.4 pode deixar `parse`
intacto — e deve.

### `ReplayOptimizer` — `har_reproducer/optimization/replay_optimizer.py:67-76, 161-180`

`_run_phase1` chama `compute_smart_schedule` e chama o resultado de `anchors`;
`_compute_backbone` (`:74-76`) usa `anchors[-2]` como fronteira; `_ranges_target_to_from`
(`:161-170`) particiona a busca entre âncoras consecutivas;
`_estimate_worst_case_requests` (`:172-180`) soma backbone e faixas. Importa porque menos
âncoras muda a **forma** da busca do `optimize`, não só o conteúdo (3.5).

---

## 3. Decisões de arquitetura

### 3.1 — `CurlTokenComment.parse_anchors`: dependência que exige o step de origem

**Estado atual:** só existe `parse`, que devolve toda linha de dependência, congelada ou
não.

**Estado esperado:** um método novo ao lado de `parse`, que devolve **apenas** as
dependências cujo extrator é recalculável — isto é, cuja linha **não** carrega nenhuma
`OriginStatusPhrase`:

- percorre as linhas que casam `DEPENDENCY_PATTERN`;
- para cada uma, separa cláusula e sufixo com o `_split_clause_and_status` que já existe;
- classifica o sufixo com o `_categorize` que já existe;
- inclui a dependência no resultado somente quando a parte `OriginStatusPhrase` da
  classificação é `None`.

⚠️ **A `ReplayStatusPhrase` não exclui a dependência.** `probably static` e
`could not extract value from response, using captured value` são observações do replay
sobre um extrator que pode ser perfeitamente recalculável; e depois de um replay a linha
pode carregar as duas frases ao mesmo tempo. Usar `_categorize`, que devolve as duas
categorias separadamente, é o que evita esse erro — testar "o sufixo está vazio" seria
errado.

⚠️ `DEPENDENCY_PATTERN` é `re.MULTILINE` e casa no começo da linha; `parse` usa
`finditer` sobre o texto inteiro. O método novo precisa iterar **linha a linha** para
poder olhar o sufixo de cada uma, e não pode assumir que o sufixo termina na linha
seguinte.

**Por que um método novo em vez de mudar `parse`.** `parse` tem dois consumidores com
necessidades opostas: o schedule quer só o que ancora, e o `ReplayTokenResolver` quer o
step de origem de **todo** token, inclusive dos literais (3.4). Mudar `parse` serviria um e
prejudicaria o outro.

### 3.2 — `_expand_pending` passa a expandir só pelo que ancora

**Estado atual:** `dependencies: Dict[str, int] = self.curl_token_comment.parse(curl_text)`.

**Estado esperado:** a mesma linha chamando o método de 3.1. Nada mais em
`compute_smart_schedule` muda: o piso `--from`, o teste de existência do step e a expansão
transitiva continuam idênticos.

Efeito medido (1.2): 254 → 11 dependências no workspace de referência, 8 → 5 âncoras, 213
dos 320 alvos com schedule menor, 2,38 → 1,03 requisições em média.

### 3.3 — O formato do `.curl.sh` não muda

**Alternativa considerada e descartada:** fazer `CurlGenerator._token_comments` emitir os
extratores literais numa categoria informativa nova (`# [Frozen N] …`) em vez de linha de
dependência.

**Por que não:** a informação já está na linha, escrita pelo próprio projeto e legível por
`grep`. Não mudar o formato compra três coisas concretas:

1. **Os workspaces já em disco passam a se beneficiar sem rodar `run` de novo** — e rodar
   `run` custa 2m24s no HAR de referência e depende do servidor da aplicação estar no ar.
2. **Nenhum dos 27 cenários golden muda de conteúdo** (5.1), o que mantém esta etapa
   pequena e auditável.
3. **A proveniência é preservada.** "Este valor veio do step 5 e nós não aprendemos a
   recalculá-lo" é exatamente o insumo de que a etapa futura de redescoberta precisa;
   trocar por uma categoria sem step de origem jogaria fora informação.

O custo é que a linha continua se chamando "dependência" sendo que não é uma. Aceito: o
sufixo declara o que ela é, e o nome do método de 3.1 declara qual leitura ancora.

### 3.4 — `ReplayTokenResolver` continua usando `parse`

**Estado atual e esperado:** iguais. Fica registrado por que, para ninguém "consertar"
depois: os tokens a resolver vêm dos placeholders do curl, e `dependencies` só escolhe o
diretório de resposta. Se um token literal deixasse de constar em `dependencies`,
`_resolve_one` receberia `origin_step=None`, `_reference_dir_for_step` (`:84-94`) cairia em
`res_refer_dir` e, caso `res_<origem>.json` não existisse lá, o script do extrator
(`templates/extractor_template.py`, `render_script`) falharia ao carregar a resposta, sairia
com código 1 e o token cairia em `_fallback_to_captured` (`:69-82`). O valor final seria o
mesmo — `captured_value` de um extrator literal **é** o literal — mas com aviso no stdout e
o token contado como `CAPTURED_FALLBACK`. Barulho sem ganho.

### 3.5 — Consequência declarada no `optimize`

`ReplayOptimizer` não muda de código, mas muda de regime, porque recebe menos âncoras:

- `_compute_backbone` usa `anchors[-2]` quando há duas ou mais âncoras e `from_index` caso
  contrário. Com menos âncoras, o backbone encolhe.
- `_ranges_target_to_from` particiona a busca entre âncoras consecutivas. Com menos
  âncoras, sobram menos faixas e mais largas.
- `_estimate_worst_case_requests` soma os dois; o número impresso muda.

Direção do efeito, sobre o workspace de referência: menos âncoras significa backbone menor
e faixas maiores. O resultado final do comando continua sendo validado por
`_confirm`, então isto não é risco de correção — é mudança de custo e de número impresso, e
o plano tem que declarar quais asserções de teste do `optimize` a acompanham.

### 3.6 — A cobertura nova é o coração desta etapa

**Estado atual:** medido, **nenhum dos 27 cenários golden exercita o defeito**. O fixture
`tests/fixtures/synthetic_flow.har` produz exatamente **uma** linha de dependência
congelada, em `req_0006.curl.sh` (token literal com origem no step 5), e os três cenários
de smart têm alvo 9, 4 e 9 — nenhum passa pelo step 6. Por isso os 27 cenários passam
byte-idênticos depois da mudança (5.1) e por isso a mudança precisa de teste novo.

**Estado esperado:** um cenário que ancore no alvo 6, cujo schedule é hoje `[5, 6]` e passa
a ser `[6]`. É o teste vermelho da etapa: ele falha antes da mudança e passa depois. Junto
dele, testes de unidade do método de 3.1 cobrindo as quatro formas que uma linha pode ter:
sem sufixo; com `OriginStatusPhrase` só; com `ReplayStatusPhrase` só; com as duas
(`origin_status; replay_status`), que é a forma que aparece depois de um replay.

---

## 4. Novos componentes e alterações — resumo

| Componente | Mudança |
|---|---|
| `replay/curl_token_comment.py` → `CurlTokenComment` | **método novo** que devolve só as dependências de extrator recalculável, reaproveitando `_split_clause_and_status` e `_categorize` (3.1) |
| `replay/replay_runner.py` → `ReplayRunner._expand_pending` | passa a chamar o método novo em vez de `parse` (3.2) |
| `replay/replay_token_resolver.py`, `reproduction/curl_generator.py`, `optimization/replay_optimizer.py` | **não mudam** (3.3, 3.4, 3.5) |
| `tests/unit/test_curl_token_comment.py` | testes do método novo, com as quatro formas de sufixo (3.6) |
| `tests/unit/test_replay_runner.py` | schedule do smart não ancora em linha de literal congelado |
| cenário golden novo de `replay --mode smart` com alvo 6 | o teste vermelho da etapa (3.6) |
| asserções de schedule do `optimize`, se mudarem | acompanham 3.5 |

---

## 5. Casos de borda e comportamento de erro

**5.1 Os 27 cenários golden.** Medido, todos passam byte-idênticos: o único alvo cujo
schedule muda no fixture é o 6, e nenhum cenário existente usa 6 como alvo
(`replay_smart_noflag` → 9, `replay_smart_to_4` → 4, `replay_smart_from_3` → 9 com piso 3).
Os cenários `run_*` não mudam porque o formato do `.curl.sh` não muda (3.3). Os dois testes
do `optimize` têm alvo 9 e também não mudam. Isso é bom para o risco desta etapa e ruim
para a confiança nela: ver 3.6.

**5.2 Linha com as duas frases.** Depois de um replay, `_apply_replay_status` pode produzir
`# [Token … step 0005] origin location undetermined — using literal captured value; probably static`.
A linha continua sendo de literal congelado e continua fora das âncoras. O caso inverso —
`# [Token … step 0003] probably static` sozinho — é extrator **recalculável** que o replay
observou estável, e continua ancorando.

**5.3 Curl sem nenhuma dependência recalculável.** `_expand_pending` simplesmente não
adiciona nada, e `compute_smart_schedule` devolve `[target]`. É o caso mais comum depois da
mudança: 313 dos 320 curls do workspace de referência.

**5.4 Workspace gerado por versão anterior.** Funciona sem regerar, porque a frase de
status já era escrita. Um workspace anterior a 04/08/2026 que não tenha a frase é
interpretado como recalculável — comportamento de hoje, sem regressão.

**5.5 Frase futura em `OriginStatusPhrase`.** A regra é "qualquer `OriginStatusPhrase`
exclui a dependência das âncoras", derivada do enum e não de uma lista literal. Uma frase
nova de origem passa a excluir automaticamente — o que é o comportamento certo, porque toda
`OriginStatusPhrase` existente significa "caiu para literal". ⚠️ Se algum dia existir uma
frase de origem que **não** signifique literal, essa invariante quebra em silêncio; ela
fica escrita junto do enum.

**5.6 `--mode smart` com `--from` acima da âncora.** Inalterado: o piso é aplicado depois,
no mesmo `if` de hoje.

**5.7 Custo.** O método novo faz uma varredura por linha em vez de um `finditer` no texto
inteiro, sobre arquivos de dezenas de linhas, uma vez por step do schedule. Irrelevante.

---

## 6. Suposições e pontos a confirmar

- **Nome do método** (`parse_anchors`, `parse_recalculable`, `parse_dependencies_for_schedule`)
  — ajustável. O que não é ajustável é ele viver em `CurlTokenComment`, que é o dono do
  formato.
- **Alvo do cenário golden novo** — proposto o alvo 6 do `synthetic_flow.har`, que é o único
  que exercita o defeito hoje. Se a preferência for um fixture com cadeia mais longa (para
  cobrir também a expansão transitiva atravessando um literal congelado), o plano cresce em
  uma task de fixture.
- **Asserções do `optimize`** — os dois testes atuais têm alvo 9 e não mudam (5.1). Se o
  plano quiser um teste que exercite 3.5 de propósito, é uma task a mais.

---

## 7. Referência

Toda alteração de código desta spec segue o padrão descrito em [[guia-de-estilo]]
(`.claude/skills/guia-de-estilo`). A decisão respeita o princípio de genericidade de
[[arquitetura-e-fundamentos]]: nada aqui assume formato de token, header ou convenção de
site — a regra é derivada de uma propriedade que o próprio projeto já registra no artefato
(o extrator é ou não recalculável) e do enum que a declara.
