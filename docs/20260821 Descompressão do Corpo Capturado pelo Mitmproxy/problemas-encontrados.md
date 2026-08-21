# Problemas encontrados — fora do escopo desta etapa

Registrado durante a investigação do defeito de `MitmAddon._build_content` (`spec.md`).
Cada item aqui tem evidência medida, mas não caso medido suficiente para justificar uma
etapa própria agora — fica documentado para não ser redescoberto do zero, e para que
apareça se algum dia o sintoma for observado num HAR real.

---

## 1. `_build_post_data` corrompe corpo de request binário, sem fallback

**Onde:** `har_reproducer/reproduction/mitm_addon.py:82-86`

```python
@staticmethod
def _build_post_data(request: Request) -> Optional[Dict[str, Any]]:
    if not request.raw_content:
        return None

    text: str = request.raw_content.decode("utf-8", errors="replace")
    return {"text": text}
```

Duas diferenças em relação ao `_build_content` da resposta (`:90-101`, o método que esta
etapa corrige):

1. **Não descomprime.** Se o request declarar `Content-Encoding` (raro, mas legal em HTTP),
   `request.raw_content` traz o corpo comprimido — a mesma classe de defeito que motivou
   esta etapa do lado da resposta.
2. **Não tem fallback para base64.** `_build_content` tenta `.decode("utf-8")` estrito e só
   cai para base64 se falhar; `_build_post_data` já nasce com `errors="replace"`, então
   **todo** corpo de request que não seja texto UTF-8 — comprimido ou não, upload binário,
   multipart com arquivo — vira mojibake sem alternativa. Não há como recuperar o corpo
   original a partir do que fica gravado.

**Por que não foi corrigido aqui:** medido nos dois HARs usados nesta investigação (a
gravação atual de 324 entries e a anterior de 238), **0 entries têm `Content-Encoding` no
request**. Não há evidência de que isso produza corrupção nestes dados — o raciocínio é por
analogia de código, não por sintoma observado. Corrigir sem caso medido correria o risco de
uma mudança sem teste que a justifique (o mesmo motivo que levou este projeto a preferir
"registrado, não corrigido" antes, no item 8 do backlog de
`docs/20260817 Reteste do Otimizador contra Servidor Real/correcoes.md`).

**O que motivaria abrir etapa:** um HAR real com upload binário (multipart com arquivo,
corpo comprimido em POST) onde o `real_requests/req_*.json` correspondente aparecer com
proporção alta de `�` — o mesmo sintoma que abriu esta etapa, do outro lado do request. Se
isso aparecer, a correção provavelmente espelha a desta etapa para o lado do request:
descomprimir via `request.get_content(strict=False)` antes de decidir texto ou base64, e
trocar o `.decode("utf-8", errors="replace")` incondicional por tentativa estrita com
fallback para base64 — hoje um upload de imagem em POST, por exemplo, viraria `�` em vez de
base64 recuperável.

**Severidade se ocorrer:** mais silenciosa que o defeito de resposta corrigido nesta etapa,
porque não há segunda época para comparar e revelar a divergência — um request corrompido
simplesmente nunca bate com o valor esperado por nenhum agente que dependa do corpo do
request como origem (não é um caso hoje coberto por nenhum `TokenLocation`, que só olha
resposta — mas description central: agentes de origem procuram em respostas, não em
requests, então o impacto direto conhecido é sobre `real_requests/`, que hoje só é
consumido para diagnóstico e para o replay recriar o request original a partir do template,
não para descoberta de origem).
