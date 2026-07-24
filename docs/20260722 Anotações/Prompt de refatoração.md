# Prompt de refatoração

Refatore a(s) classe(s) abaixo seguindo estritamente estas regras:

## 1. Métodos pequenos e de responsabilidade única
- Quebre métodos longos em métodos privados menores, cada um fazendo uma coisa só.
- Nenhum método deve passar de ~2 níveis de indentação (loop → if, no máximo). Se passar, extraia um método.
- Elimine duplicação de lógica (ex.: dois `if` fazendo a mesma checagem viram uma constante/coleção).

## 2. Separação em classes/arquivos por responsabilidade
- Identifique blocos de métodos que formam um conceito coeso (ex.: construção de request, transporte HTTP, execução de script) e extraia cada bloco para sua própria classe, em seu próprio arquivo.
- A classe original deve orquestrar, delegando para essas classes via composição (instanciadas no `__init__`), não por herança.
- Nada fica solto no módulo: nada de função ou constante fora de classe.

## 3. Tudo tipado, evitando `Any`
- Toda variável, parâmetro, retorno e atributo de classe deve ter tipo explícito.
- Constantes de classe (ex.: limites, timeouts, status codes) devem ser anotadas com `ClassVar[...]` e não apenas atribuídas sem tipo.
- Evite `Any`: use o tipo mais específico possível.
  - Se o tipo real depender de outro arquivo do projeto (models, contracts, etc.), pergunte por esses arquivos antes de "chutar" um tipo genérico.
  - Se a própria API/dependência que está sendo chamada já é contratualmente tipada como `Any` (ex.: JSON sem schema, biblioteca de terceiros), replique esse `Any` em vez de fingir precisão com `object` — isso seria menos correto, não mais.
  - `object` só deve ser usado quando o valor é genuinamente opaco e não há um tipo mais específico disponível em lugar nenhum do código.

## 4. Zero comentários
- Não inclua comentários (`#`) nem docstrings.
- O código deve se explicar por nomes de métodos/variáveis claros, não por explicações ao lado.

## 5. Comportamento preservado 1:1
- A refatoração não pode mudar comportamento observável, incluindo casos de borda (ordem de tentativas, condições de retry, etc.).
- Se algum trecho parecer código morto/defensivo incompatível com o tipo real dos dados (ex.: checagem para um tipo que nunca ocorre), avise explicitamente antes de simplificar, em vez de simplificar em silêncio.

## 6. Processo
1. Primeiro proponha a decomposição (quais métodos viram quais classes/arquivos) e pergunte se pode prosseguir.
2. Depois de aprovado, gere os arquivos.
3. Rode um compile-check (`py_compile` ou equivalente) antes de entregar.
4. Ao final, liste rapidamente o que foi extraído para onde, e quais tipos ficaram como `Any`/`object` por falta de contexto — perguntando se há mais arquivos do projeto que permitam apertar esses tipos.

## Classe(s) a refatorar
```
<colar aqui o código da classe>
```