# Tarefas

- o arquivo curl gerado não deve ter o token, e sim o id. A ideia é que seja um modelo, não para ser usado (pode ser
  usado atraves de algum "resolver.py" para essa tarefa)
- estou na duvida se essa linha esta funcionando: deterministic: List[Strategy] = self.deterministic_strategies ()
- validar o que acontece quando
    - grep encontra nos resposes, mas não consegue criar extrator (Acho que é valido criar extrator que passar extrator
      que simplesmente passa a string, mas isso precisa ser avisado no curl)
    - não encontra nos responses
- Outra coisa, acho que preciso implementar logo a validação se o token candidato é realmente algo que precise ser
  pesquisado ou é só uma palavra estatica obvia
    - deterministico (tipo lista)
    - llm

# Futuro

- o prompt precisa ser melhor trabalho explicando como é a resposta esperada (talvez até uma skill)
    - criar "modelo do teste" exigindo da llm que ela só edite aonde ela é permitida. Dessa forma o teste fica
      padronizada e previsivel. Tipo uma interface.