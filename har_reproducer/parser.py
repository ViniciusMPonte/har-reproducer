import json
import base64
from pathlib import Path
from typing import List, Dict, Any, Optional
from .models import Step, StepRequest, StepResponse

class HARParser:
    """
    Handles the decomposition of HAR files into atomic step files.
    """
    
    @staticmethod
    def load_har(path: Path) -> Dict[str, Any]:
        """Loads a HAR file from disk."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def decode_body(body_content: str, encoding: Optional[str] = None) -> str:
        """
        Decodes the HAR body content based on the encoding provided.
        """
        if not body_content:
            return ""
            
        if encoding == "base64":
            try:
                return base64.b64decode(body_content).decode("utf-8", errors="replace")
            except Exception:
                return body_content
        
        return body_content

    @staticmethod
    def parse_entry(entry: Dict[str, Any], index: int) -> Step:
        """
        Parses a single HAR entry into a Step object.
        """
        req_data = entry["request"]
        res_data = entry["response"]
        
        # Parse Request
        req_headers = {v["name"]: v["value"] for v in req_data.get("headers", [])}
        req_cookies = {c["name"]: c["value"] for c in req_data.get("cookies", [])}
        
        req_body = None
        post_data = req_data.get("postData")
        if post_data:
            req_body = post_data.get("text")
            
        # Handle OPTIONS skipping
        is_skippable = req_data["method"] == "OPTIONS"
        
        request = StepRequest(
            url=req_data["url"],
            method=req_data["method"],
            headers=req_headers,
            cookies=req_cookies,
            body=req_body,
            is_skippable=is_skippable
        )
        
        # Parse Response
        res_headers = {v["name"]: v["value"] for v in res_data.get("headers", [])}
        res_cookies = {c["name"]: c["value"] for c in res_data.get("cookies", [])}
        
        res_content = res_data.get("content", {})
        text = res_content.get("text")
        encoding = res_content.get("encoding")
        
        body = HARParser.decode_body(text, encoding)
        
        response = StepResponse(
            status_code=res_data["status"],
            headers=res_headers,
            cookies=res_cookies,
            body=body,
            body_mime=res_content.get("mimeType"),
            redirect_url=res_data.get("redirectUrl")
        )
        
        return Step(index=index, request=request, response=response)

    @classmethod
    def split_har(cls, har_path: Path, output_dir: Path):
        """
        Decomposes a HAR file into indexed req_NNNN.json and res_NNNN.json files.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        har_data = cls.load_har(har_path)
        entries = har_data.get("log", {}).get("entries", [])
        
        for i, entry in enumerate(entries):
            step = cls.parse_entry(entry, i)
            
            # Save request
            req_file = output_dir / f"req_{i:04d}.json"
            req_file.write_text(step.request.model_dump_json(indent=2), encoding="utf-8")
            
            # Save response
            res_file = output_dir / f"res_{i:04d}.json"
            res_file.write_text(step.response.model_dump_json(indent=2), encoding="utf-8")
            
        return len(entries)
