---
name: guia-de-estilo
description: Padrão de código deste projeto (tipagem, estrutura de classes, decomposição de métodos, comentários, tratamento de erros, comportamento). Use SEMPRE antes de escrever, editar ou revisar arquivos Python neste projeto — inclusive ao gerar tasks do plano de refatoração.
---

# Guia de estilo — padrão de código do projeto

Extraído dos arquivos reais do projeto e do prompt de refatoração usado. Serve como referência para manter consistência ao implementar as tasks do plano.

## Tipagem
- Toda variável, parâmetro, retorno e atributo tem tipo explícito — mesmo quando óbvio pelo lado direito: `self.session_store: SessionStore = SessionStore()`, não só `self.session_store = SessionStore()`.
- Constantes de classe usam `ClassVar[...]`: `MAX_STEP_ATTEMPTS: ClassVar[int] = 2`, `RECOVERABLE_STATUS_CODES: ClassVar[Set[int]] = {400, 401}`.
- `Path` (pathlib) para qualquer caminho de arquivo — nunca `str` cru.
- Evitar `Any`. Se o tipo depende de outro arquivo do projeto que você não tem em mãos, pare e peça o arquivo em vez de chutar um tipo genérico. `object` só quando o valor é genuinamente opaco (sem tipo mais específico disponível em lugar nenhum do código).

## Estrutura e composição
- Um conceito coeso = uma classe = um arquivo. Nome do arquivo em snake_case do nome da classe (`curl_generator.py` → `CurlGenerator`).
- Dependências são instanciadas no `__init__` e guardadas como atributo tipado: `self.request_builder: RequestBuilder = RequestBuilder(...)`.
- Nada solto no módulo — sem função ou constante fora de classe. Até um arquivo só com um enum (`workspace_dir.py`) ou só com staticmethods (`extractor_template.py`) segue esse padrão.
  - Vale também em `tests/` (`conftest.py`, `test_*.py`): a isenção documentada é só para funções decoradas como fixture do `pytest` e funções `test_*`, exigidas como funções de módulo pelo framework. Constantes — paths, portas, valores fixos — continuam exigindo uma classe com `ClassVar`, mesmo dentro de `conftest.py`. Já aconteceu de constantes soltas (`FIXTURES_DIR`, `OFFLINE_PORT`) passarem batido num `conftest.py` antes de serem corrigidas.
- `Enum(str, Enum)` para qualquer conjunto fechado de valores (`TokenLocation`, `AgentType`, `EngineMode`).

## Decomposição de métodos
- Método não deve passar de ~2 níveis de indentação (loop → if, no máximo). Se passar, extrai método privado (`_algo`).
- Métodos privados pequenos, um por responsabilidade — ex.: `CurlGenerator._header_parts`/`_cookie_parts`/`_body_parts`, `RequestBuilder._render_headers`/`_render_body`.
- Guard clauses (`if x is None: return None`) em vez de aninhar — é o que mantém o limite de indentação.
- `@staticmethod` para métodos sem estado de instância; `@classmethod` para padrão singleton/factory (`Workspace`, `EngineFactory`).
- Duplicação de lógica vira constante/coleção — ex.: `LOCATION_AGENTS: ClassVar[Dict[TokenLocation, Type[BaseAgent]]]` em vez de um `if/elif` por location.

## Comentários e nomenclatura
- Zero comentários (`#`) e zero docstrings. O nome do método/variável carrega a explicação.
- Nomes descritivos e longos são preferíveis a nomes curtos com comentário ao lado.

## Tratamento de erros
- Nas bordas de I/O/subprocess (leitura de arquivo, execução de script externo), `except Exception` amplo é aceitável, mas sempre seguido de `print` de aviso e retorno degradado (`None`/lista vazia) — nunca deixa a exceção propagar silenciosamente nem crasha o processo inteiro por causa de uma falha pontual (ex.: `CandidateResolver._load_response`, `ExtractorRunner._execute_extractor_script`).
- Fora dessas bordas, não engolir exceção — deixar propagar.

## Comportamento e código morto
- Refatoração nunca muda comportamento observável, nem em casos de borda (ordem de tentativas, condições de retry, etc.).
- Se algo parecer código morto ou defensivo para um caso que o tipo real dos dados nunca produz, **avisar antes de remover** — nunca simplificar em silêncio.

## Processo ao gerar cada task do plano
1. Propor a decomposição (quais métodos/blocos viram o quê) antes de escrever o arquivo final.
2. Só gerar o(s) arquivo(s) depois de aprovado.
3. Rodar um compile-check (`py_compile` ou equivalente) antes de entregar.
4. Ao final, listar o que foi extraído/para onde, e quais tipos ficaram `Any`/`object` por falta de contexto — perguntando se há mais arquivos do projeto que permitam apertar esses tipos.
