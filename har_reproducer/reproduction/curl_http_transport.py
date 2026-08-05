import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

from har_reproducer.fs_io import HARParser, Workspace
from har_reproducer.models import Step, StepResponse


class CurlHttpTransport:
    DEFAULT_TIMEOUT_SECONDS: ClassVar[float] = 30.0
    CAPTURE_READ_ATTEMPTS: ClassVar[int] = 5
    CAPTURE_READ_RETRY_INTERVAL_SECONDS: ClassVar[float] = 0.1

    def __init__(self, port: int, ca_cert_path: Optional[Path]) -> None:
        self.port: int = port
        self.ca_cert_path: Optional[Path] = ca_cert_path

    def send_request(self, curl_literal: str, step_index: int) -> StepResponse:
        curl_command: str = self._build_curl_command(curl_literal)

        try:
            completed: subprocess.CompletedProcess = subprocess.run(
                ["bash", "-c", curl_command],
                capture_output=True,
                timeout=self.DEFAULT_TIMEOUT_SECONDS,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return self._build_error_response(step_index, str(exc))

        if completed.returncode != 0:
            return self._build_error_response(step_index, self._decode_stderr(completed))

        response: Optional[StepResponse] = self._read_captured_response(step_index)
        if response is not None:
            return response

        return self._build_error_response(
            step_index, "Falha ao ler a captura do mitmproxy após o curl ter sucesso."
        )

    def _build_curl_command(self, curl_literal: str) -> str:
        proxy_flags: List[str] = [
            f"--proxy http://127.0.0.1:{self.port}",
            self._tls_flag(),
            "-o /dev/null",
            "-sS",
        ]
        return " \\\n     ".join([curl_literal.strip()] + proxy_flags)

    def _tls_flag(self) -> str:
        if self.ca_cert_path is None:
            return "--insecure"

        return f"--cacert {shlex.quote(str(self.ca_cert_path))}"

    @staticmethod
    def _decode_stderr(completed: subprocess.CompletedProcess) -> str:
        return completed.stderr.decode("utf-8", errors="replace").strip()

    def _read_captured_response(self, step_index: int) -> Optional[StepResponse]:
        for _ in range(self.CAPTURE_READ_ATTEMPTS):
            response: Optional[StepResponse] = self._try_read_capture(step_index)
            if response is not None:
                return response
            time.sleep(self.CAPTURE_READ_RETRY_INTERVAL_SECONDS)
        return None

    @staticmethod
    def _try_read_capture(step_index: int) -> Optional[StepResponse]:
        try:
            entries: List[Dict[str, Any]] = HARParser.get_entries(Workspace.mitm_capture_file())
            if not entries:
                return None
            step: Step = HARParser.parse_entry(entries[0], step_index)
            return step.response
        except Exception:
            return None

    @staticmethod
    def _build_error_response(step_index: int, error_message: str) -> StepResponse:
        print(
            f"Network error while executing step {step_index} "
            f"message: {error_message}"
        )
        return StepResponse(
            status_code=0,
            headers={},
            cookies={},
            body=error_message,
            body_mime=None,
            redirect_url=None,
        )
