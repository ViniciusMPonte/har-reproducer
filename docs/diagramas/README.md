# Diagramas do projeto

Diagramas em formato **draw.io** (`.drawio`, XML editável). Para abrir:

- Web: [app.diagrams.net](https://app.diagrams.net) → *File → Open from → Device*.
- VS Code: extensão *Draw.io Integration* — abre e edita `.drawio` direto no editor.

## Diagramas disponíveis

- [`fluxo-run.drawio`](fluxo-run.drawio) — visão de regra de negócio do comando
  `run`: da chamada do usuário até o resultado final (sucesso/falha), passando
  pela decisão proxy real vs. modo simulado e pelo loop de reprodução de cada
  requisição do fluxo capturado. Cada caixa nomeia a classe responsável e uma
  frase curta do que ela decide/faz — não é um trace de chamadas de método.
  Fontes: [main.py](../../har_reproducer/main.py),
  [cli_handlers.py](../../har_reproducer/cli/cli_handlers.py),
  [engine.py](../../har_reproducer/engines/engine.py).
