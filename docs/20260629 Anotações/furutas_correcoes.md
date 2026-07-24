# anotações do estudo

- pegar o arquivo har e cria lista de dicionarios
- separa primeiro step do har

- LOOP
    - compara a request atual do har com a primeira request do har
    - o que tiver igual mantem na proxima request em execução
    - o que tiver diferente, pesquisa nos responses do har e cria extratores
    - usa extratores nos responses da execução
    - passa o valor para a resquest em execução
    - executa
    - valida se deu certo
    - grava request e response em execução no output
    - acrescenta mais 1 no index

__________

# Modelos

    "provider": "google",
    "model": "gemini-3.1-flash-lite"
	"model": "gemma-4-26b-a4b-it"

    "provider": "ollama",
    "model": "gemma4:e2b"
