# Investigação da Porta de Admissão — base de evidência

**Esta pasta não é uma etapa.** Não tem `spec.md` nem `implementation_plan.md`, e nada aqui
deve ser implementado. É o registro de uma investigação de 20/08/2026 que projetou a
correção do `Authorization` congelado, submeteu o desenho a duas revisões adversariais de
contexto limpo, mediu tudo sobre **duas** gravações do mesmo site, e concluiu que o assunto
se divide em três etapas.

## Para onde isso foi

As três etapas resultantes estão registradas como itens **9**, **10** e **11** do adendo de
20/08 em `docs/20260817 Reteste do Otimizador contra Servidor Real/correcoes.md`:

| item | etapa | estado |
|---|---|---|
| 9 | Extrator literal congelado não deveria virar âncora | `docs/20260820 Extrator Literal Não Vira Âncora/` |
| 10 | `real_responses/` guarda corpo comprimido como mojibake | a fazer — pré-requisito do item 11 |
| 11 | Porta de admissão + casamento por fragmento | a fazer — depende de 9 e 10 |

Esta pasta existe para que os itens 10 e 11 não comecem do zero.

## O que tem aqui

| arquivo | conteúdo |
|---|---|
| `medições.md` | Todos os números da investigação, com procedência e o meio de reproduzir. Já **corrigido** — a versão original tinha erros que as revisões acharam, e cada correção está marcada. |
| `revisões-adversariais.md` | O consolidado dos achados das duas revisões, incluindo os que derrubaram decisões e os que corrigiram números. É o documento mais útil dos três. |
| `spec-descartada.md` | A spec que foi escrita e descartada, com um cabeçalho listando o que nela caiu e por quê. Preservada pelo mapa de componentes e pela análise das duas épocas. |
| `medições/` | Scripts. Rodam da raiz do projeto e recebem os caminhos por argumento — não há caminho de scratchpad embutido. |

## Os dados de referência

Os números foram medidos sobre workspaces gerados com `run --mode main` contra o servidor
real da aplicação. **Os workspaces não estão no repositório** (10 MB e 16 MB, e são dados
derivados). Para regerar:

```bash
# gravação atual — 324 entries
uv run python -m har_reproducer.main run \
    --har ../arquivos-har/progressofit.har \
    --output ../arquivos-har/ws_atual --mode main --config config.json

# gravação anterior — 238 entries, é a que expõe os falsos positivos
uv run python -m har_reproducer.main run \
    --har "../progressofit(antigo).har" \
    --output ../arquivos-har/ws_anterior --mode main --config config.json
```

⚠️ Depende do servidor da aplicação estar no ar (`http://localhost:8090` e
`http://127.0.0.1:8080`) e leva ~2m24s na gravação atual. E o resultado **não é
determinístico**: o laço TDD dos agentes usa LLM quando `config.json` a configura, então
duas execuções do mesmo HAR produzem conjuntos diferentes de extrator (medido: uma deu
`{HeaderAgent 4, CSSAgent 3, RegexAgent 4, LiteralAgent 4, LiteralFallbackAgent 2}` e outra
`{HeaderAgent 4, RegexAgent 4, LiteralAgent 4, LiteralFallbackAgent 5}` — três valores que
uma execução aprendeu a extrair, a outra congelou). Espere variação de alguns pontos
percentuais nos números que dependem de quantos extratores são literais.

`arquivos-har/ws_20260817_main` é o workspace de referência que sobreviveu à investigação e
serve para a maioria das medições sem regerar nada.

## As três conclusões que importam

1. **O ganho grande não era da porta.** 89% a 96% das linhas de dependência dos workspaces
   vêm de extrator literal congelado, que devolve o mesmo valor com ou sem o step de origem
   no schedule — e ainda assim o arrasta para lá. Isso é o item 9, e é independente de tudo
   o mais.
2. **A porta não é confiável enquanto o item 10 existir.** Os falsos positivos que o desenho
   produziu na gravação anterior vêm de respostas cujo corpo foi persistido ainda
   comprimido: a comparação entre épocas lê "a substring desapareceu" e conclui "o valor é
   dinâmico".
3. **Uma gravação não valida um critério de admissão.** Todo critério que zerava os falsos
   positivos na gravação atual falhou na anterior, e a classe de risco que a gravação atual
   declara vazia (requisição condicional: 0 `If-None-Match`) é 53,6% da anterior (126 de
   235 curls).
