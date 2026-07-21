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

__________

//
//- o conteudo do rep_.json precisa estar no teste enviado para llm ler, mas não no teste. Porem precisa ter a leitura do arquivo la. (remover o Any, ou fazer o cast dentro do try
//
//- o prompt precisa ser melhor trabalho explicando como é a resposta esperada
//	- criar um arquivo separado para o prompt do teste
//	- criar "modelo do teste" exigindo da llm que ela só edite aonde ela é permitida. Dessa forma o teste fica padronizada e previsivel. Tipo uma interface.
//
//- remover todos os comentários desnecessários.


//  "llm": {
//    "provider": "ollama",
//    "model": "gemma4:e2b"
  "model": "gemma-4-26b-a4b-it"
//  },

- outro problema, nos extratores, a criação de código esta em dois lugares diferentes, um é na geração, que hoje esta no _write_temp_script do base.py, e o outro no _run_extractor, que esta no engine.py
- creio que o fluxo não esteja correto, o código esta criando todos os extratores antes de testar em uma requisição real