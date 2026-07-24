import base64
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from har_reproducer.models import Step, StepRequest, StepResponse


class HARParser:

    SKIPPABLE_METHODS: set[str] = {"OPTIONS"}

    @staticmethod
    def load_har(path: Path) -> Dict[str, Any]:

        with open(path, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)
            return data

    @classmethod
    def get_entries(cls, har_path: Path) -> List[Dict[str, Any]]:

        with open(har_path, "r", encoding="utf-8") as f:
            har_data: Dict[str, Any] = json.load(f)
        entries: List[Dict[str, Any]] = har_data.get("log", {}).get("entries", [])
        return entries

    @staticmethod
    def decode_body(body_content: str, encoding: Optional[str] = None) -> str:

        if not body_content:
            return ""

        if encoding == "base64":
            try:
                return base64.b64decode(body_content).decode("utf-8", errors="replace")
            except Exception as e:
                print(f"[AVISO] Falha ao decodificar body base64: {e}. Retornando conteúdo original.")
                return body_content

        return body_content

    @staticmethod
    def parse_entry(entry: Dict[str, Any], index: int) -> Step:

        req_data: Dict[str, Any] = entry["request"]
        res_data: Dict[str, Any] = entry["response"]

        req_headers: Dict[str, str] = {v["name"]: v["value"] for v in req_data.get("headers", [])}
        req_cookies: Dict[str, str] = {c["name"]: c["value"] for c in req_data.get("cookies", [])}

        req_body: Optional[str] = None
        post_data: Optional[Dict[str, Any]] = req_data.get("postData")
        if post_data:
            req_body = post_data.get("text")

        is_skippable: bool = req_data["method"] in HARParser.SKIPPABLE_METHODS

        request: StepRequest = StepRequest(
            url=req_data["url"],
            method=req_data["method"],
            headers=req_headers,
            cookies=req_cookies,
            body=req_body,
            is_skippable=is_skippable
        )

        res_headers: Dict[str, str] = {v["name"]: v["value"] for v in res_data.get("headers", [])}
        res_cookies: Dict[str, str] = {c["name"]: c["value"] for c in res_data.get("cookies", [])}

        res_content: Dict[str, Any] = res_data.get("content", {})
        text: Optional[str] = res_content.get("text")
        encoding: Optional[str] = res_content.get("encoding")

        body: str = HARParser.decode_body(text or "", encoding)

        response: StepResponse = StepResponse(
            status_code=res_data["status"],
            headers=res_headers,
            cookies=res_cookies,
            body=body,
            body_mime=res_content.get("mimeType"),
            redirect_url=res_data.get("redirectUrl")
        )

        return Step(index=index, request=request, response=response)

    @classmethod
    def split_har(cls, har_path: Path, output_dir: Path) -> int:

        output_dir = output_dir / "parse"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        har_data: Dict[str, Any] = cls.load_har(har_path)
        entries: List[Dict[str, Any]] = har_data.get("log", {}).get("entries", [])

        for i, entry in enumerate(entries):
            step: Step = cls.parse_entry(entry, i)

            req_file: Path = output_dir / f"req_{i:04d}.json"
            req_file.write_text(step.request.model_dump_json(indent=2), encoding="utf-8")

            res_file: Path = output_dir / f"res_{i:04d}.json"
            assert step.response is not None
            res_file.write_text(step.response.model_dump_json(indent=2), encoding="utf-8")

        return len(entries)
