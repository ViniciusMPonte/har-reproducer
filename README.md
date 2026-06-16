# HAR Flow Reproducer

Ferramenta para reprodução de fluxos de requisições a partir de arquivos HAR, com detecção automática de tokens dinâmicos e agentes de extração verificados.

## 🚀 Como Executar

### 1. Instalação
Este projeto utiliza o [uv](https://github.com/astral-sh/uv) para gerenciamento de dependências.

```bash
# Instala as dependências e sincroniza o ambiente
uv sync
```

### 2. Comandos do CLI

Use `uv run` para executar a ferramenta:

#### Passo 1: Parse do HAR
Decompõe o arquivo HAR em passos individuais (arquivos JSON).
```bash
uv run python -m har_reproducer.cli parse --har caminho/para/arquivo.har --output steps_dir
```

#### Passo 2: Executar Reprodução
Tenta reproduzir o fluxo. Você pode usar o modo `dry-run` para analisar os tokens sem fazer chamadas de rede.
```bash
# Reprodução real
uv run python -m har_reproducer.cli run --har caminho/para/arquivo.har --config criteria.json

# Análise Dry-Run (Simulação)
uv run python -m har_reproducer.cli run --har caminho/para/arquivo.har --dry-run
```

#### Passo 3: Diagnosticar Falhas
Se um passo falhar, utilize o comando de diagnóstico para sugerir correções nos extratores.
```bash
uv run python -m har_reproducer.cli diagnose --steps steps_dir --real-responses reproduction_results/real_responses
```

---

## 🧪 Como Rodar os Testes

Para executar a suíte de testes com `uv`:

```bash
uv run pytest
```

Para rodar testes de um módulo específico:
```bash
uv run pytest tests/engine
uv run pytest tests/agents
uv run pytest tests/parser
```
