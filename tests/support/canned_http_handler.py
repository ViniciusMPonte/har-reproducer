from http.server import BaseHTTPRequestHandler
from typing import ClassVar, Dict, Optional, Tuple

from tests.support.auth_flow_tokens import AuthFlowTokens
from tests.support.canned_response import CannedResponse


class CannedHttpHandler(BaseHTTPRequestHandler):

    protocol_version: ClassVar[str] = "HTTP/1.1"

    ITEM_PATH_PREFIX: ClassVar[str] = "/item/"
    PROTECTED_PATH: ClassVar[str] = "/protected"

    ITEM_RESPONSE: ClassVar[CannedResponse] = CannedResponse(
        200, [("Content-Type", "application/json")], '{"id": 9999}',
    )

    PROTECTED_GRANTED_RESPONSE: ClassVar[CannedResponse] = CannedResponse(
        200, [("Content-Type", "application/json")], '{"ok": true}',
    )
    PROTECTED_DENIED_RESPONSE: ClassVar[CannedResponse] = CannedResponse(403, [], "")

    CANNED_RESPONSES: ClassVar[Dict[Tuple[str, str], CannedResponse]] = {
        ("POST", "/login"): CannedResponse(
            200, [("Content-Type", "application/json")], f'{{"token": "{AuthFlowTokens.TOKEN_VIVO}"}}',
        ),
        ("GET", "/login"): CannedResponse(
            200,
            [
                ("Content-Type", "text/html"),
                ("Set-Cookie", "SESSIONID=abc123live; Path=/"),
                ("X-Api-Header", "build-99"),
            ],
            '<html><body><div id="marker">tok_CSS_9</div><script>var nonce = "scr_NONCE_9";</script></body></html>',
        ),
        ("OPTIONS", "/api/do"): CannedResponse(204, [], ""),
        ("POST", "/api/do"): CannedResponse(
            200, [("Content-Type", "application/json")], '{"id": 9999, "ok": true}',
        ),
        ("GET", "/plain"): CannedResponse(200, [("Content-Type", "text/plain")], "PLAINVAL999"),
        ("GET", "/use-plain"): CannedResponse(
            200, [("Content-Type", "text/html")], "<html><body>ok</body></html>",
        ),
        ("GET", "/prefs"): CannedResponse(
            200,
            [("Content-Type", "text/html"), ("Set-Cookie", "PREFS=xyz999; Path=/")],
            "<html><body>prefs</body></html>",
        ),
        ("GET", "/use-prefs"): CannedResponse(
            200, [("Content-Type", "text/html")], "<html><body>ok</body></html>",
        ),
        ("POST", "/submit"): CannedResponse(
            200, [("Content-Type", "text/html")], "<html><body>done</body></html>",
        ),
    }

    def do_GET(self) -> None:
        self._serve()

    def do_POST(self) -> None:
        self._serve()

    def do_OPTIONS(self) -> None:
        self._serve()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _serve(self) -> None:
        canned: Optional[CannedResponse] = self._resolve(self.command, self.path)
        if canned is None:
            self._serve_not_found()
            return
        self._serve_canned(canned)

    def _resolve(self, method: str, path: str) -> Optional[CannedResponse]:
        if method == "GET" and path.startswith(self.ITEM_PATH_PREFIX):
            return self.ITEM_RESPONSE
        if method == "GET" and path == self.PROTECTED_PATH:
            return self._protected_response()
        return self.CANNED_RESPONSES.get((method, path))

    def _protected_response(self) -> CannedResponse:
        if self.headers.get("Authorization") == f"Bearer {AuthFlowTokens.TOKEN_VIVO}":
            return self.PROTECTED_GRANTED_RESPONSE
        return self.PROTECTED_DENIED_RESPONSE

    def _serve_not_found(self) -> None:
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_canned(self, canned: CannedResponse) -> None:
        raw_body: bytes = canned.body.encode("utf-8")
        self.send_response(canned.status)
        self._send_canned_headers(canned)
        self.send_header("Content-Length", str(len(raw_body)))
        self.end_headers()
        if raw_body:
            self.wfile.write(raw_body)

    def _send_canned_headers(self, canned: CannedResponse) -> None:
        for name, value in canned.headers:
            self.send_header(name, value)
