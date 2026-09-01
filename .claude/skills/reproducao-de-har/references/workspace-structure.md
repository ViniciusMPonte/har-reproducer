# Estrutura de um workspace (`output/`) — o que tem em cada pasta

Este texto documenta o que existe **dentro** de `output/` depois de rodar
`parse`/`run`/`replay`/`optimize`/`extractor` — o mapa que falta antes de usar
qualquer um dos outros textos desta skill, já que todos citam essas pastas
como se o agente já soubesse o que cada uma guarda. Ver `workspace-setup.md`
para onde `output/` fica (por fora, dentro de `<domínio>__<AAAAMMDD>/`) e por
que é um repositório git.

## `parse` sozinho: uma estrutura à parte

`parse` **não** gera nenhuma das pastas abaixo — escreve só em
`<output>/parse/`, um `req_XXXX.json`/`res_XXXX.json` por passo do HAR, sem
tocar rede nem gerar `curls/`/`extractors/`. É a decomposição bruta do HAR,
nada mais. Todo o resto deste texto descreve o que `run` (e o que `replay`/
`optimize`/`extractor` reaproveitam depois) gera direto em `<output>/`.

## As oito pastas que `run` materializa em `<output>/`

Cada uma nasce vazia (ou populada só parcialmente) no momento em que o
`Workspace` é construído — todas existem desde o primeiro `run`, mesmo que
algumas fiquem sem arquivo nenhum dependendo do modo.

| Pasta | Conteúdo | Quem escreve | Quando fica vazia |
|---|---|---|---|
| `real_requests/` | `req_NNNN.json` — a requisição de cada passo, tal como estava no HAR (sem tokens resolvidos) | `run` | Nunca (um `run` sempre grava todas) |
| `original_responses/` | `res_NNNN.json` — a resposta que **já estava gravada no HAR original**, sem nenhuma requisição nova | `run` | Nunca — grava em qualquer modo, mesmo `dry` |
| `real_responses/` | `res_NNNN.json` — a resposta **real**, obtida de fato contra o servidor (via proxy `mitmproxy`) | `run --mode main` | Sempre vazia em `run --mode dry` (não há tráfego de rede) |
| `curls/` | `req_NNNN.curl.sh` — um `curl` parametrizado por passo, com `{{extractor:<token_id>}}` no lugar de cada valor dinâmico e comentários `# Token <id> comes from response of step <n>` documentando a dependência | `run` | Nunca |
| `extractors/` | `extract_<token_id>.py` (código da extração) + `extract_<token_id>.meta.json` (metadados: `agent_type`, `origin_step`, `captured_value`, `verified`, `last_value`) — um par por token dinâmico descoberto | `run`, e `extractor create`/`update`/`delete` depois | Fica vazia só se o fluxo não tiver nenhum valor dinâmico (raro) |
| `temp_extractors/` | Rascunho de extractor durante validação (`ExtractorValidator`) — nunca é a versão final | `extractor create`/`update` (etapa de validação, antes de decidir persistir) | Normalmente vazia entre execuções — é território de trabalho, não arquivo definitivo |
| `mitm_capture/` | `capture.har` (tudo que o proxy interceptou) + `mitmdump.log` | `run`/`replay`/`optimize` em qualquer chamada que toque rede | Vazia se nenhum comando com tráfego real já rodou |
| `replays/` | Uma subpasta por execução de `replay` (`replays/<run_id>/res_NNNN.json`, as respostas daquela reexecução) + os `.txt` gerados por `optimize` (`replays/optimized_<run_id>.txt`) | `replay`, `optimize` | Vazia até o primeiro `replay`/`optimize` |

## Como usar essa tabela nas outras etapas da skill

- **Diagnóstico** (`diagnostics.md`): a diferença entre `original_responses/`
  (o que o HAR capturou) e `real_responses/` (o que o servidor responde hoje)
  é o primeiro lugar a olhar pra saber se o portal mudou algo desde a
  captura — sem essa tabela, as duas pastas parecem sinônimas.
- **Extractor CRUD** (`extractor-crud-strategies.md`): `extractor test` roda
  contra amostras de `real_responses/`/`original_responses/`; `extractor
  create`/`update` só persiste em `extractors/` depois de validar via
  `temp_extractors/` — nunca escreve direto lá (ver ⚠️ em
  `arquitetura-e-fundamentos`, seção do pipeline `extractor`).
- **Otimização** (Passo 4/5 do `SKILL.md`): o `.txt` que `optimize` produz
  fica em `replays/optimized_<run_id>.txt` por padrão (a menos que
  `--steps-out` aponte outro caminho) — é o mesmo formato que `replay --mode
  list --steps-file` consome.

## `config.json` do workspace (convenção, não automático)

`diagnostics.md`/`workspace-setup.md` estabelecem a convenção de manter um
`<output>/config.json` próprio de cada workspace (separado de qualquer config
compartilhado do projeto), usado principalmente para afinar
`success_criteria` conforme o diagnóstico avança. **O `har_reproducer` não
carrega esse arquivo sozinho** — nenhum comando tem um caminho padrão de
config; é sempre preciso passar `--config <output>/config.json`
explicitamente em toda chamada (`run`/`replay`/`optimize`) sobre aquele
workspace. Esquecer a flag faz o comando rodar com os valores padrão (sem
critério de sucesso configurado), não com o `config.json` do workspace.
