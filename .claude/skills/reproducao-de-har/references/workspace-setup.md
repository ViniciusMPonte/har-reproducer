# Configuração do workspace — har-reproducer

Este texto define como o agente organiza os arquivos ao começar a trabalhar
com um HAR novo, antes de rodar qualquer comando do `har-reproducer`.

## 1. Raiz do workspace

O agente **pergunta ao usuário** onde deve ficar a raiz onde os workspaces
vão morar — não escolhe um lugar por conta própria na primeira vez. Depois
de definida (nesta conversa ou numa anterior), reaproveita a mesma raiz
para os próximos HARs, a menos que o usuário indique outra.

## 2. Estrutura por HAR

Para cada HAR novo, o agente cria uma pasta própria dentro da raiz:

```
<raiz>/<domínio>__<AAAAMMDD>_<HHMM>_<tipo>/
  ├── <arquivo>.har        # cópia do HAR original
  └── output/              # workspace de saída (--output aponta aqui)
```

- **Nome da pasta**: `<domínio>__<AAAAMMDD>_<HHMM>_<tipo>` — extensão da
  convenção usada em `tests/real/captures/` (que só tinha `<domínio>__<AAAAMMDD>`
  porque nunca teve duas capturas do mesmo domínio no mesmo dia). `<domínio>`
  é o domínio do portal alvo; `<AAAAMMDD>`/`<HHMM>` são data e hora da
  **captura** do HAR (quando o fluxo foi gravado, extraídos do nome do
  arquivo `captura_AAAAMMDD_HHMMSS.har`), não do momento em que o agente
  está trabalhando nele; `<tipo>` é `login`/`valores_pagos`/`analitico`
  (Passo 0 de `gravacao-de-har`). **O horário, não o tipo, é o que garante
  unicidade** — duas capturas do mesmo domínio, mesmo dia e mesmo tipo (ex.:
  uma regravação horas depois) também não colidem, porque o `HHMM` já
  diferencia sozinho; o tipo entra só para tornar o nome legível sem abrir
  a pasta.
- **Cópia do HAR**: o agente copia o `.har` original para dentro dessa
  pasta — não referencia o arquivo de onde ele estiver espalhado no
  sistema. Isso mantém o HAR de origem junto do que foi gerado a partir
  dele, mesmo que o arquivo original seja movido ou apagado depois.
- **`output/`**: é o valor passado em `--output` para `parse`/`run`/
  `replay`/`optimize` sobre esse HAR — onde tudo que o `har-reproducer`
  gera (`curls/`, `extractors/`, respostas, etc.) fica. Ver seção 3 sobre
  como esse diretório é versionado.

## 3. `output/` como repositório git

Ao criar a pasta `output/` de um HAR novo (ou ao encontrar uma já
existente sem repositório), o agente inicializa um repositório git ali
dentro e **commita a cada alteração** feita nesse diretório — extratores
editados, o `config.json` do workspace, respostas geradas, o registro de
estratégias, qualquer arquivo tocado depois.

É só `output/` que é versionado — a cópia do `.har` ao lado fica fora do
controle de versão (seção 2). O motivo de commitar a cada mudança está
detalhado no texto de diagnóstico: é esse histórico que permite editar os
arquivos ali (inclusive os mais sensíveis, como `extractors/`) com
liberdade durante testes, com rollback e branches disponíveis.

## 4. Um HAR novo, um workspace novo

Cada HAR novo recebe sua própria pasta `<domínio>__<AAAAMMDD>_<HHMM>_<tipo>/` —
o agente não reaproveita nem combina o workspace de um HAR dentro do de
outro, mesmo que sejam do mesmo domínio. Se dois HARs do mesmo domínio forem
capturados em datas diferentes, ou na mesma data em horários/tipos
diferentes, ambos coexistem lado a lado (`exemplo.com.br__20260824_0915_login/`,
`exemplo.com.br__20260824_1440_valores_pagos/`), do mesmo jeito que já
acontece em (uma versão anterior mais simples de) `tests/real/captures/`.
