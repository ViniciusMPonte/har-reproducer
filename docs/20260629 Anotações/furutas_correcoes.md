- O grep_utils.py são funções soltas. COlocar tudo em um método.
- os comentários realmente estão sendo uteis?

# anotações do estudo

- entender o que esta chegando para ser extraido nos extratores e qual é a estrutura



- pegar o arquivo har e cria lista de dicionarios
- separa primeiro step do har

LOOP
	- compara a request atual do har com a primeira request do har
	- o que tiver igual mantem na proxima request em execução
	- o que tiver diferente, pesquisa nos responses do har e cria extratores
	- usa extratores nos responses da execução
	- passa o valor para a resquest em execução
	- executa
	- valida se deu certo
	- grava request e response em execução no output
	- acrescenta mais 1 no index