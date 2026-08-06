import socket
import threading
from http.server import ThreadingHTTPServer
from typing import ClassVar, Optional

from tests.support.canned_http_handler import CannedHttpHandler


class CannedHttpServer:

    MINIMUM_PORT: ClassVar[int] = 10000

    def __init__(self, port: int) -> None:
        if port < self.MINIMUM_PORT:
            raise ValueError(f"CannedHttpServer requires a 5-digit port, got {port}")
        self.port: int = port
        self._server: ThreadingHTTPServer = ThreadingHTTPServer(("127.0.0.1", port), CannedHttpHandler)
        self._thread: Optional[threading.Thread] = None

    @staticmethod
    def free_port() -> int:
        with socket.socket() as temp_socket:
            temp_socket.bind(("127.0.0.1", 0))
            return int(temp_socket.getsockname()[1])

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
