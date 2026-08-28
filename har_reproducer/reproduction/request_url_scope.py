from typing import ClassVar, Dict, Tuple
from urllib.parse import urlparse, ParseResult

from har_reproducer.fs_io import Workspace
from har_reproducer.models import StepRequest


class RequestUrlScope:

    DEFAULT_PORT_BY_SCHEME: ClassVar[Dict[str, int]] = {"http": 80, "https": 443}

    @staticmethod
    def parts(url: str) -> Tuple[str, int, str]:
        parsed: ParseResult = urlparse(url)
        host: str = parsed.hostname or ""
        port: int = parsed.port or RequestUrlScope.DEFAULT_PORT_BY_SCHEME.get(parsed.scheme, 443)
        path: str = parsed.path or "/"
        return host, port, path

    @staticmethod
    def parts_for_step(workspace: Workspace, index: int) -> Tuple[str, int, str]:
        request: StepRequest = StepRequest.model_validate_json(
            workspace.request_file(index).read_text(encoding="utf-8")
        )
        return RequestUrlScope.parts(request.url)
