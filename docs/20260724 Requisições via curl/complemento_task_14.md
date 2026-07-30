## O que a T14 precisa saber e não está no plano original

**1. Variável de ambiente é obrigatória, não opcional**
O plano de T14 nunca menciona env var. Mas o addon (T13) só funciona se `HAR_REPRODUCER_MITM_CAPTURE_PATH` estiver setada **antes** do `mitmdump` subir — porque `MitmAddon.__init__` é executado na carga do script (`addons = [MitmAddon()]` roda assim que o `mitmdump -s` importa o arquivo), e se a env var não existir, o addon levanta `RuntimeError` imediatamente, o que derruba o processo do `mitmdump` inteiro no boot.

Ou seja: no `subprocess.Popen(...)` que a T14 vai montar, é preciso passar `env=` com essa variável setada como `str(Workspace.mitm_capture_file())` — não é algo que "roda e depois configura", tem que estar presente desde o `Popen`.

**2. Importar a constante, não repetir a string**
```python
from har_reproducer.reproduction.mitm_addon import MitmAddon
...
env[MitmAddon.CAPTURE_PATH_ENV_VAR] = str(Workspace.mitm_capture_file())
```
Evita a string `"HAR_REPRODUCER_MITM_CAPTURE_PATH"` duplicada e dessincronizável entre os dois arquivos.

**3. Flags de CLI confirmadas por teste real**
O plano fala em termos vagos ("subir `mitmdump -s {addon}` com `--set confdir=...`"). Testei e a invocação que funciona é:
```
mitmdump -s <caminho_do_addon> --listen-port <porta> --set confdir=<raiz_do_projeto>
```
`--listen-port`, não `--port`.

**4. Onde o CA aparece, confirmado**
Com `--set confdir=X`, o certificado sai em `X/mitmproxy-ca-cert.pem` — bate com o que o plano assumia, mas agora está validado empiricamente, não só suposto.

**5. Health check precisa checar mais que a porta**
Como o addon pode derrubar o processo no boot (ponto 1), um health check que só tenta conectar na porta em loop pode ficar esperando o timeout inteiro num cenário de env var esquecida, sem nunca detectar que o processo já morreu. Vale o loop de health check também chamar `process.poll()` a cada tentativa e falhar cedo se o processo já encerrou — em vez de só esperar a porta abrir.

Também vale considerar checar a existência do `mitmproxy-ca-cert.pem` como parte do "pronto", já que quem consome a porta/CA logo em seguida (`CurlHttpTransport`, T12) precisa do caminho do CA imediatamente.

**6. Copiar o `--ssl-insecure` em testes**
Só precisei dessa flag porque *este sandbox* intercepta TLS de saída com certificado próprio, e o `mitmdump` corretamente rejeitava esse cert como não confiável. Isso é uma particularidade do ambiente de teste, não do seu ambiente real.