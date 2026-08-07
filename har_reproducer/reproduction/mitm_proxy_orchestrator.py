import http.client
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, ClassVar, Dict, IO, List, Optional

from har_reproducer.fs_io import Workspace
from har_reproducer.reproduction.mitm_env import MitmEnv
from har_reproducer.reproduction.proxy_readiness import ProxyReadiness


class MitmProxyOrchestrator:
    CA_CERT_FILENAME: ClassVar[str] = "mitmproxy-ca-cert.pem"
    ADDON_PATH: ClassVar[Path] = Path(__file__).resolve().parent / "mitm_addon.py"
    PACKAGE_ROOT: ClassVar[Path] = Path(__file__).resolve().parent.parent.parent
    HEALTH_CHECK_TIMEOUT_SECONDS: ClassVar[float] = 10.0
    HEALTH_CHECK_INTERVAL_SECONDS: ClassVar[float] = 0.2
    PROXY_PROBE_TIMEOUT_SECONDS: ClassVar[float] = 1.0
    MITMPROXY_SERVER_HEADER_MARKER: ClassVar[str] = "mitmproxy"
    TERMINATE_TIMEOUT_SECONDS: ClassVar[float] = 5.0
    MITMDUMP_EXECUTABLE_NAME: ClassVar[str] = "mitmdump.exe" if sys.platform == "win32" else "mitmdump"

    def __init__(self, workspace: Workspace, proxy_port: Optional[int], project_root: Path) -> None:
        self.workspace: Workspace = workspace
        self.project_root: Path = project_root
        self.port: int = self._resolve_port(proxy_port)
        self.ca_cert_path: Path = self.project_root / self.CA_CERT_FILENAME
        self._process: Optional[subprocess.Popen] = None
        self._log_file: Optional[IO[str]] = None

    @staticmethod
    def _resolve_port(proxy_port: Optional[int]) -> int:
        if proxy_port is not None:
            return proxy_port
        return MitmProxyOrchestrator._find_free_port()

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
            probe_socket.bind(("127.0.0.1", 0))
            return probe_socket.getsockname()[1]

    @staticmethod
    def _resolve_mitmdump_path() -> Path:
        executable_dir: Path = Path(sys.executable).parent
        return executable_dir / MitmProxyOrchestrator.MITMDUMP_EXECUTABLE_NAME

    def run(self, callback: Callable[[], bool]) -> bool:
        self._process = self._start_process()
        try:
            self._wait_until_ready()
            return callback()
        finally:
            self._terminate()

    def _start_process(self) -> subprocess.Popen:
        self._log_file = open(self.workspace.mitm_log_file(), "w", encoding="utf-8")
        return subprocess.Popen(
            self._build_command(),
            env=self._build_env(),
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
        )

    def _build_command(self) -> List[str]:
        return [
            str(self._resolve_mitmdump_path()),
            "-s", str(self.ADDON_PATH),
            "--listen-port", str(self.port),
            "--set", f"confdir={self.project_root}",
        ]

    def _build_env(self) -> Dict[str, str]:
        env: Dict[str, str] = dict(os.environ)
        env[MitmEnv.CAPTURE_PATH_ENV_VAR] = str(self.workspace.mitm_capture_file())
        env["PYTHONPATH"] = self._prepend_package_root(env.get("PYTHONPATH"))
        return env

    @classmethod
    def _prepend_package_root(cls, existing: Optional[str]) -> str:
        if not existing:
            return str(cls.PACKAGE_ROOT)
        return f"{cls.PACKAGE_ROOT}{os.pathsep}{existing}"

    def _wait_until_ready(self) -> None:
        deadline: float = time.monotonic() + self.HEALTH_CHECK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._process_died_early():
                raise RuntimeError(self._build_early_exit_message())

            readiness: ProxyReadiness = self._probe_proxy()
            if readiness == ProxyReadiness.READY:
                return
            if readiness == ProxyReadiness.OCCUPIED_BY_OTHER_PROCESS:
                message: str = self._build_port_conflict_message()
                print(f"[AVISO] {message}")
                raise RuntimeError(message)

            time.sleep(self.HEALTH_CHECK_INTERVAL_SECONDS)

        raise RuntimeError(
            f"mitmdump não ficou pronto na porta {self.port} após {self.HEALTH_CHECK_TIMEOUT_SECONDS}s."
        )

    def _process_died_early(self) -> bool:
        assert self._process is not None
        return self._process.poll() is not None

    def _build_early_exit_message(self) -> str:
        assert self._process is not None
        log_path: Path = self.workspace.mitm_log_file()
        output: str = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        return f"mitmdump encerrou antes de ficar pronto (exit code {self._process.returncode}):\n{output}"

    def _probe_proxy(self) -> ProxyReadiness:
        if not self._can_connect():
            return ProxyReadiness.NOT_READY_YET
        return self._classify_response()

    def _can_connect(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=self.HEALTH_CHECK_INTERVAL_SECONDS):
                return True
        except OSError:
            return False

    def _classify_response(self) -> ProxyReadiness:
        try:
            server_header: str = self._fetch_server_header()
        except (OSError, http.client.HTTPException):
            return ProxyReadiness.OCCUPIED_BY_OTHER_PROCESS

        if self.MITMPROXY_SERVER_HEADER_MARKER in server_header.lower():
            return ProxyReadiness.READY
        return ProxyReadiness.OCCUPIED_BY_OTHER_PROCESS

    def _fetch_server_header(self) -> str:
        connection: http.client.HTTPConnection = http.client.HTTPConnection(
            "127.0.0.1", self.port, timeout=self.PROXY_PROBE_TIMEOUT_SECONDS
        )
        try:
            connection.request("GET", "/")
            response: http.client.HTTPResponse = connection.getresponse()
            return response.getheader("Server", "")
        finally:
            connection.close()

    def _build_port_conflict_message(self) -> str:
        return (
            f"A porta {self.port} já está sendo usada por outro processo — "
            f"a resposta recebida não veio do mitmdump que acabamos de iniciar "
            f"(header 'Server' não indica mitmproxy). "
            f"Escolha outra porta ou libere a porta {self.port} antes de tentar novamente."
        )

    def _terminate(self) -> None:
        if self._process is None:
            return

        self._process.terminate()
        try:
            self._process.wait(timeout=self.TERMINATE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        self._process = None

        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
