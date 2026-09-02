# Fluxo de decisão — har-reproducer

Este texto orienta um agente sobre **qual comando/modo escolher em cada etapa**
ao trabalhar com um fluxo HAR. Pressupõe que os guardrails de segurança
(texto separado) já foram lidos e são respeitados.

## 1. Chegando um HAR novo

Ponto de partida padrão: **`run --mode main`**, não `parse` sozinho e não
`run --mode dry`.

- `parse` sozinho só decompõe o HAR em `req_XXXX.json`/`res_XXXX.json`, sem
  gerar `curls/` nem `extractors/`. Só vale a pena rodar isoladamente quando
  o objetivo é apenas inspecionar a estrutura bruta do fluxo (quantos passos,
  quais URLs) antes de decidir mais nada — na prática, raramente é o
  primeiro comando a rodar, porque `run` já faz esse trabalho e mais.
- `run --mode main` é o modo padrão de verdade: já gera `real_responses/`,
  que é a referência preferida por `replay`/`optimize`, e evita um passo
  extra de "confirmar depois contra o servidor real". Na maioria dos casos
  é a melhor opção desde o início — respeitando sempre o guardrail de avisar
  sobre efeito colateral antes da primeira execução real num HAR novo.
- `run --mode dry` **não é o caminho mais seguro por padrão** — é uma opção
  específica para quando o fluxo tem muitos tokens que só o LLM fallback
  consegue resolver (os agentes determinísticos — regex/JSONPath/CSS/
  header/cookie — não dão conta). Nesse cenário, rodar `main` direto faria
  cada chamada ao LLM acontecer *no meio* da sequência de requisições reais
  contra o portal, e a latência dessas chamadas pode atrasar o fluxo o
  suficiente para afetar o resultado (sessão/token expirando, timing
  sensível do portal, etc.). `dry` deixa resolver os tokens offline primeiro
  (contra `original_responses/`, sem rede), pra só depois rodar `main` com
  os extratores já prontos e sem essa latência no meio do fluxo real.

## 2. Quando usar `dry` antes de `main`

Use `run --mode dry` como etapa preparatória — não como destino final —
quando desconfiar que o fluxo vai depender bastante do LLM fallback:

- Muitos passos com tokens que não seguem padrão óbvio (regex/JSONPath/CSS
  não bastam), ou um HAR grande onde isso pode se acumular.
- Sinal de que o portal alvo é sensível a tempo entre requisições (ex.:
  tokens de curta duração, fluxos de poucos segundos entre passos).

Depois do `dry`, o agente já tem os `extractors/` gerados e pode avaliar
quantos dependeram do LLM antes de decidir se vale ajustar algo manualmente
ou já seguir para `run --mode main` com essa base pronta — reduzindo o
número de chamadas ao LLM que aconteceriam em tempo real durante o `main`.
Se o fluxo não tiver esse risco de latência, pular direto para `main` é a
opção padrão.

## 3. Revisar extratores antes de `replay`/`optimize`

Depois de qualquer `run` (main ou dry) e **antes** de rodar `replay --mode all`
ou `optimize`: rodar `extractor list` sobre o workspace. É leitura pura, sem
rede, e pega uma classe de problema que não precisa de nenhuma requisição real
pra ser confirmado ou corrigido — ver
[extractor-crud-strategies.md](extractor-crud-strategies.md) para o sinal mais
barato (extratores com `referenced_by: []`, tipicamente sintoma de
"Attempt 1 failed... Retrying" no log do `run`) e os padrões de correção.
Vale como hábito padrão, não só quando algo já deu errado: pegar um extrator
órfão ou obviamente errado agora custa uma leitura; deixá-lo passar pra dentro
do `optimize` custa dezenas de requisições reais gastas em cima de lixo.

## 4. De `run` para `replay`

`replay` exige um workspace já existente com `curls/` populado (de um `run`
anterior). Não recria nada do zero — reaproveita o que já foi gerado.

**Primeiro passo obrigatório depois de qualquer `run`: `replay --mode all`.**
Serve para validar se o resultado do `run` é confiável — reexecutar tudo
pode revelar falso positivo (`run --mode main` "deu certo", mas ao
reexecutar falha), problemas de tempo de resposta do portal, etc. Não pular
direto para `optimize` ou para os modos de análise sem essa validação de
base primeiro.

Depois que `all` confirma (ou não) que o fluxo reexecuta corretamente, os
outros três modos — `smart`, `slice`, `list` — são **ferramentas de análise
de trechos específicos**, não etapas sequenciais entre si. Servem tanto
depois de `all` quanto depois de `optimize`, dependendo da pergunta que o
agente está tentando responder:

| Modo | Pergunta que responde |
|---|---|
| `smart` | "Esse passo (ou trecho) funciona só com as dependências óbvias?" — reexecuta o alvo (`--to`) e, recursivamente, só os passos dos quais ele depende via tokens dinâmicos. |
| `slice` | O oposto do `smart`: reexecuta um intervalo contíguo (`--from` a `--to`) sem resolver dependência nenhuma — útil para checar se um trecho funciona "como está", sem a poda de dependências que o `smart` faz. |
| `list` | Ferramenta para comprovar uma teoria específica formada durante a análise — ex: "concluí que os passos 2 e 5 precisam ser sequenciais entre si, e o resto só depende das dependências óbvias"; monta a lista exata e valida. |
| `all` | Sempre o primeiro modo depois de um `run` — valida o resultado como um todo antes de qualquer análise mais fina. |

## 5. De `replay` para `optimize`

`optimize` também exige workspace com `curls/` e referência de resposta já
populados (idealmente `real_responses/` de um `run --mode main` anterior).
Entra em cena depois que `replay --mode all` já confirmou que o fluxo
funciona de ponta a ponta, quando o objetivo muda para "qual é o
subconjunto mínimo de passos necessário para o alvo (`--to`) responder
corretamente?" — normalmente para produzir um `.txt` pronto para
`replay --mode list --steps-file`.

Depois de um `optimize`, os modos de análise (`smart`/`slice`/`list`)
continuam úteis — agora sobre o resultado minimizado. Por exemplo: `smart`
para conferir se o subconjunto encontrado ainda respeita as dependências
óbvias, ou `list` para testar uma variação da lista que o `optimize`
produziu. Ver guardrails para os riscos de rodar `optimize` (efeito
colateral repetido, `--max-requests`).

## 6. Resumo visual

```
HAR novo
  │
  ▼
risco de muita dependência de LLM fallback (timing sensível)?
  │
  ├─ não ──────────────────────────────▶ run --mode main
  │
  └─ sim ──▶ run --mode dry (resolve tokens offline) ──▶ run --mode main
  │
  ▼
extractor list   (revisão offline — sem rede — antes de qualquer replay/optimize)
  │
  ▼
replay --mode all   (sempre o primeiro — valida o run, detecta falso positivo)
  │
  ├─ confirmado, quero o subconjunto mínimo? ──▶ optimize
  │
  └─ preciso analisar algo específico (antes ou depois do optimize):
        ├─ só as dependências óbvias bastam? ──▶ smart
        ├─ um trecho fixo funciona sem poda de dependência? ──▶ slice
        └─ tenho uma teoria pontual pra comprovar? ──▶ list
```
