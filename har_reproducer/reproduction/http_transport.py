from typing import Optional

import httpx
from httpx import Client, Response

from ..models import StepRequest, StepResponse


class HttpTransport:

    def send_request(self, final_request: StepRequest, step_index: int) -> StepResponse:
        with httpx.Client(follow_redirects=False) as client:
            try:
                resp: Response = client.request(
                    method=final_request.method,
                    url=final_request.url,
                    headers=final_request.headers,
                    cookies=final_request.cookies,
                    content=self._encode_body(final_request.body),
                )
            except httpx.RequestError as exc:
                return self._build_error_response(client, step_index, final_request, exc)

            return self._build_success_response(client, resp)

    def _encode_body(self, body: Optional[str]) -> Optional[bytes]:
        if not body:
            return None
        return body.encode("utf-8") if isinstance(body, str) else body

    def _build_error_response(
            self,
            client: Client,
            step_index: int,
            final_request: StepRequest,
            exc: httpx.RequestError,
    ) -> StepResponse:
        print(
            f"Network error while executing step {step_index} "
            f"({final_request.method} {final_request.url}): {exc}"
        )
        return StepResponse(
            status_code=0,
            headers={},
            cookies=dict(client.cookies),
            body=str(exc),
            body_mime=None,
            redirect_url=None,
        )

    def _build_success_response(self, client: Client, resp: Response) -> StepResponse:
        return StepResponse(
            status_code=self._normalize_status_code(resp.status_code),
            headers=dict(resp.headers),
            cookies=dict(client.cookies),
            body=resp.text,
            body_mime=resp.headers.get("Content-Type"),
            redirect_url=resp.headers.get("Location"),
        )

    def _normalize_status_code(self, raw_status: int) -> int:
        return raw_status
