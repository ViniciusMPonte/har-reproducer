from pathlib import Path
from typing import Dict, Optional, Union

from har_reproducer.models import Step, StepRequest
from har_reproducer.reproduction import CurlGenerator
from har_reproducer.session import SessionStore


class RequestBuilder:

    def __init__(self, session_store: SessionStore, curls_dir: Path) -> None:
        self.session_store: SessionStore = session_store
        self.curls_dir: Path = curls_dir

    def build_final_request(self, step: Step) -> StepRequest:
        req: StepRequest = step.request

        return StepRequest(
            url=req.url,
            method=req.method,
            headers=self._render_headers(req.headers),
            cookies=self.session_store.render_dict(req.cookies),
            body=self._render_body(req.body),
            is_skippable=req.is_skippable,
        )

    def _render_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        raw_headers: Dict[str, str] = self.session_store.render_dict(headers)
        return {k: v for k, v in raw_headers.items() if not k.startswith(":")}

    def _render_body(self, body: Optional[Union[str, bytes]]) -> Optional[str]:
        if body is None:
            return None
        if isinstance(body, bytes):
            return body.decode("utf-8", errors="replace")
        return self.session_store.render(body)

    def write_curl(self, step: Step, final_request: StepRequest) -> None:
        curl_cmd: str = CurlGenerator().generate(
            step.index, final_request, session_store=self.session_store
        )

        curl_file: Path = self.curls_dir / f"req_{step.index:04d}.curl.sh"
        curl_file.write_text(f"#!/bin/bash\n{curl_cmd}\n", encoding="utf-8")
