# HAR Flow Reproducer

Ferramenta de linha de comando que reproduz um fluxo de requisições HTTP capturado em um arquivo **HAR**, detectando automaticamente quais valores (tokens, IDs, cookies, headers) mudam de uma execução para outra e gerando extratores para resolvê-los dinamicamente a cada passo.

## Como funciona

1. **`parse`** decompõe o HAR em um passo (`step`) por requisição, sem executar nada.
2. **`run`** percorre o HAR passo a passo: para cada requisição, compara a resposta com a primeira requisição do fluxo (baseline) para identificar valores dinâmicos (via agentes de regex, JSONPath, CSS, header e cookie), gera um `curl` parametrizado para o passo e — no modo `main` — executa esse `curl` de fato contra o servidor real (através de um proxy `mitmproxy` local, usado para capturar a resposta real). No modo `dry`, os mesmos passos são analisados usando as respostas já gravadas no HAR, sem tráfego de rede.
3. **`replay`** reexecuta os `curl`s já gerados por um `run` anterior (a partir do workspace de saída), resolvendo os tokens dinâmicos com base nas respostas reais capturadas, e permite repetir só um trecho do fluxo (um passo específico, uma faixa, ou apenas os passos dos quais aquele trecho depende).

Ao final de um `run` ou `replay`, o resultado é validado contra os `success_criteria` definidos no `config.json` (ex.: status code esperado, texto esperado no corpo, etc.).

Um LLM (opcional, configurado em `config.json`) é usado como fallback para resolver tokens que os agentes determinísticos não conseguem identificar sozinhos.

## Tecnologias

- **Python 3.12+** / **uv** (gerenciamento de dependências e execução)
- **mitmproxy** — proxy local usado para capturar as respostas reais das requisições reproduzidas
- **LangChain** (+ `langchain-google-genai`, `langchain-openai`, `langchain-anthropic`, `langchain-ollama`) — integração com LLMs como fallback na resolução de tokens
- **Pydantic** — validação de modelos e do `config.json`
- **curl** e **bash** — usados via subprocess para executar as requisições reproduzidas (necessários no sistema)

## Instalação

Pré-requisitos: Python 3.12+, [uv](https://github.com/astral-sh/uv), e `curl`/`bash` disponíveis no sistema.

```bash
# Instala as dependências e sincroniza o ambiente
uv sync
```

Se for usar um LLM como fallback (opcional, ver seção de configuração abaixo), crie um arquivo `.env` na raiz do projeto com a chave do provedor escolhido:

```bash
GOOGLE_API_KEY=...      # provider: google / gemini / gemma / google_genai
OPENAI_API_KEY=...      # provider: openai
ANTHROPIC_API_KEY=...   # provider: anthropic / claude
# provider: ollama roda localmente e não precisa de chave
```

O certificado do `mitmproxy` é gerado automaticamente (em `.mitmproxy/` na raiz do projeto) na primeira execução que usar a rede.

## Como executar

O ponto de entrada é `har_reproducer.main`:

```bash
uv run python -m har_reproducer.main <comando> [opções]
```

### `parse` — decompor o HAR em passos

```bash
uv run python -m har_reproducer.main parse --har caminho/para/arquivo.har [--output DIR] [--reset]
```

| Flag | Descrição |
|---|---|
| `--har` (obrigatório) | Caminho do arquivo HAR |
| `--output` | Diretório de saída (padrão: `<pasta-do-har>/output`) |
| `--reset` | Apaga e recria o diretório de saída antes de rodar (padrão: preserva o que já existe) |

Gera `req_XXXX.json` / `res_XXXX.json` de cada passo em `<output>/parse/`.

### `run` — reproduzir o fluxo

```bash
uv run python -m har_reproducer.main run --har caminho/para/arquivo.har [--mode main|dry] [--config config.json] [--output DIR] [--reset]
```

| Flag | Descrição |
|---|---|
| `--har` (obrigatório) | Caminho do arquivo HAR |
| `--mode` | `main` (padrão) executa as requisições de verdade via proxy; `dry` só analisa os tokens usando as respostas já gravadas no HAR, sem rede |
| `--config` | Caminho do `config.json` do projeto (ver seção abaixo). Se omitido, usa valores padrão (sem LLM, sem critério de sucesso) |
| `--output` | Diretório de saída (padrão: `<pasta-do-har>/output`) |
| `--reset` | Apaga e recria o diretório de saída antes de rodar (padrão: preserva) |

Gera em `<output>/`: `real_requests/` (requests tal como no HAR), `original_responses/` (respostas originais do HAR — sempre gravadas, em qualquer modo), `real_responses/` (respostas reais obtidas via HTTP — só populado em modo `main`; em modo `dry` fica vazio), `curls/` (um `.curl.sh` por passo) e `extractors/` (extratores gerados para os tokens dinâmicos). Esse workspace é o que o `replay` reutiliza depois.

### `replay` — reexecutar passos de um workspace já gerado

Requer um workspace já criado por um `run` anterior (com `curls/` populado).

```bash
uv run python -m har_reproducer.main replay --output DIR --mode all|slice|smart|list [--from N] [--to N] [--steps-file arquivo.txt] [--config config.json]
```

| Flag | Descrição |
|---|---|
| `--output` (obrigatório) | Caminho do workspace existente (o mesmo `--output` usado no `run`) |
| `--mode` (obrigatório) | `all`, `slice`, `smart` ou `list` (ver abaixo) |
| `--from` / `--to` | Índices inicial/final do passo (só para `slice`/`smart`) |
| `--steps-file` | Caminho de um `.txt` com um índice de passo por linha (só para `mode list`) |
| `--config` | Caminho do `config.json` do projeto |

Modos de replay:

- **`all`** — reexecuta todos os passos existentes no workspace, na ordem.
- **`slice`** — reexecuta os passos de `--from` até `--to` (padrão: do primeiro ao último passo existente, se omitidos).
- **`smart`** — reexecuta apenas o passo alvo (`--to`, padrão: o último existente) e, recursivamente, os passos anteriores dos quais ele depende (via tokens dinâmicos), sem descer abaixo de `--from` (padrão: 0). Útil para não reexecutar o fluxo inteiro quando só um passo específico precisa ser testado.
- **`list`** — reexecuta exatamente os passos listados em `--steps-file`, na ordem em que aparecem no arquivo. Formato do arquivo: um índice de passo por linha, por exemplo:
  ```
  0
  3
  7
  ```

Ao final, o `replay` compara a resposta do último passo executado com a resposta de referência daquele passo (status code, lida de `real_responses/` ou, na ausência dela, de `original_responses/`) e reporta sucesso ou divergência.

## Configuração (`config.json`)

Arquivo JSON passado via `--config`, com todos os campos opcionais:

```json
{
  "llm": {
    "provider": "google",
    "model": "gemini-3.1-flash-lite",
    "temperature": 0.0,
    "extra": {}
  },
  "success_criteria": [
    { "type": "status_code", "expected": 200 }
  ],
  "proxy_port": null,
  "ca_cert_path": null,
  "response_reference_dir": null
}
```

- **`llm`** — provedor de LLM usado como fallback para resolver tokens dinâmicos que os agentes determinísticos não identificam. Se omitido, nenhum fallback de LLM é usado.
  - `provider`: `ollama` (padrão, não precisa de chave), `google`/`gemini`/`gemma`/`google_genai`, `openai`, ou `anthropic`/`claude`. A chave correspondente (`GOOGLE_API_KEY`, `OPENAI_API_KEY` ou `ANTHROPIC_API_KEY`) deve estar no `.env`.
  - `model` (obrigatório dentro de `llm`): nome do modelo a ser usado.
  - `temperature`: padrão `0.0`.
  - `extra`: kwargs adicionais repassados direto ao construtor do modelo (LangChain).
- **`success_criteria`** — lista de critérios usados para validar o último passo do fluxo. Cada item tem um `type` e um `expected`:
  - `status_code` (int)
  - `body_contains` (string)
  - `url_match` (string)
  - `html_element_present` (seletor CSS, string)

  Se a lista estiver vazia (padrão), o fluxo é considerado bem-sucedido sem validação adicional.
- **`proxy_port`** — porta fixa para o `mitmproxy`. Se omitido, uma porta livre é escolhida automaticamente.
- **`ca_cert_path`** — diretório de configuração do `mitmproxy` (`confdir`), de onde é lido o certificado `mitmproxy-ca-cert.pem` usado nas requisições (`--cacert`). Se omitido, usa `.mitmproxy/` na raiz do projeto.
- **`response_reference_dir`** — diretório de respostas reais usado como referência pelo `replay` ao resolver tokens de passos fora do schedule atual. Se omitido, usa `<output>/real_responses/` do próprio workspace; quando a resposta de um passo específico não existir ali (ex.: workspace que só rodou `dry`), o `replay` cai automaticamente para `<output>/original_responses/`.
