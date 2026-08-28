import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mitmproxy.http import HTTPFlow, Request, Response
from mitmproxy.net.http import cookies as mitm_cookies

from har_reproducer.reproduction.mitm_env import MitmEnv


class MitmAddon:

    def __init__(self) -> None:
        self.capture_path: Path = self._resolve_capture_path()

    def _resolve_capture_path(self) -> Path:
        raw_path: Optional[str] = os.environ.get(MitmEnv.CAPTURE_PATH_ENV_VAR)
        if raw_path is None:
            raise RuntimeError(
                f"{MitmEnv.CAPTURE_PATH_ENV_VAR} não está definida no ambiente do mitmdump."
            )
        return Path(raw_path)

    def response(self, flow: HTTPFlow) -> None:
        if flow.response is None:
            return

        entry: Dict[str, Any] = self._build_entry(flow.request, flow.response)
        envelope: Dict[str, Any] = self._build_envelope(entry)
        self._write_envelope(envelope)

    def _build_envelope(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        return {"log": {"entries": [entry]}}

    def _build_entry(self, request: Request, response: Response) -> Dict[str, Any]:
        return {
            "request": self._build_request(request),
            "response": self._build_response(response),
        }

    def _build_request(self, request: Request) -> Dict[str, Any]:
        req_data: Dict[str, Any] = {
            "method": request.method,
            "url": request.url,
            "headers": self._headers_list(request.headers.items(multi=True)),
            "cookies": self._request_cookies_list(request),
        }
        post_data: Optional[Dict[str, Any]] = self._build_post_data(request)
        if post_data is not None:
            req_data["postData"] = post_data
        return req_data

    def _build_response(self, response: Response) -> Dict[str, Any]:
        res_data: Dict[str, Any] = {
            "status": response.status_code,
            "headers": self._headers_list(response.headers.items(multi=True)),
            "cookies": self._response_cookies_list(response),
            "content": self._build_content(response),
        }
        redirect_url: Optional[str] = response.headers.get("location")
        if redirect_url is not None:
            res_data["redirectUrl"] = redirect_url
        return res_data

    @staticmethod
    def _headers_list(items: List[Tuple[str, str]]) -> List[Dict[str, str]]:
        return [{"name": name, "value": value} for name, value in items]

    @staticmethod
    def _request_cookies_list(request: Request) -> List[Dict[str, str]]:
        return [{"name": name, "value": value} for name, value in request.cookies.items(multi=True)]

    @staticmethod
    def _response_cookies_list(response: Response) -> List[Dict[str, Any]]:
        cookies_list: List[Dict[str, Any]] = []
        for name, (value, attrs) in response.cookies.items(multi=True):
            cookies_list.append({
                "name": name,
                "value": value,
                "domain": attrs.get("domain"),
                "path": attrs.get("path", "/"),
                "expired": mitm_cookies.is_expired(attrs),
            })
        return cookies_list

    @staticmethod
    def _build_post_data(request: Request) -> Optional[Dict[str, Any]]:
        if not request.raw_content:
            return None

        text: str = request.raw_content.decode("utf-8", errors="replace")
        return {"text": text}

    @staticmethod
    def _build_content(response: Response) -> Dict[str, Any]:
        mime_type: str = response.headers.get("content-type", "")
        content: Optional[bytes] = response.get_content(strict=False)

        if not content:
            return {"text": "", "mimeType": mime_type}

        try:
            text: str = content.decode("utf-8")
            return {"text": text, "mimeType": mime_type}
        except UnicodeDecodeError:
            encoded_text: str = base64.b64encode(content).decode("ascii")
            return {"text": encoded_text, "mimeType": mime_type, "encoding": "base64"}

    def _write_envelope(self, envelope: Dict[str, Any]) -> None:
        try:
            self.capture_path.write_text(json.dumps(envelope), encoding="utf-8")
        except Exception as e:
            print(f"[AVISO] Falha ao escrever captura do mitmproxy em {self.capture_path}: {e}")


addons = [MitmAddon()]
