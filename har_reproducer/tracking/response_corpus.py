import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class ResponseCorpus:

    def __init__(self, responses_dir: Path, step_index_width: int) -> None:
        self.responses_dir: Path = responses_dir
        self.step_index_width: int = step_index_width
        self._responses: Dict[int, Dict[str, Any]] = {}
        self._searchable: Dict[int, str] = {}

    def eligible_indexes(self, before_step_index: int) -> List[int]:
        indexes: List[int] = []
        for path in sorted(self.responses_dir.glob("res_*.json")):
            step_index: Optional[int] = self._extract_step_index(path.name)
            if step_index is not None and step_index < before_step_index:
                indexes.append(step_index)
        return sorted(indexes)

    def response(self, step_index: int) -> Optional[Dict[str, Any]]:
        memoized: Optional[Dict[str, Any]] = self._responses.get(step_index)
        if memoized is not None:
            return memoized

        loaded: Optional[Dict[str, Any]] = self._load_response(step_index)
        if loaded is None:
            return None

        self._responses[step_index] = loaded
        return loaded

    def searchable_text(self, step_index: int) -> Optional[str]:
        memoized: Optional[str] = self._searchable.get(step_index)
        if memoized is not None:
            return memoized

        response: Optional[Dict[str, Any]] = self.response(step_index)
        if response is None:
            return None

        text: str = self._serialize(response)
        self._searchable[step_index] = text
        return text

    def _load_response(self, step_index: int) -> Optional[Dict[str, Any]]:
        res_file: Path = self.responses_dir / f"res_{step_index:0{self.step_index_width}d}.json"
        if not res_file.exists():
            return None
        try:
            data: Dict[str, Any] = json.loads(res_file.read_text(encoding="utf-8"))
            return data
        except Exception as e:
            print(f"[AVISO] Falha ao carregar response do step {step_index}: {e}")
            return None

    @classmethod
    def _serialize(cls, response: Dict[str, Any]) -> str:
        parts: List[str] = []
        for name, value in (response.get("headers") or {}).items():
            parts.append(f"{name}: {value}")
        for name, value in (response.get("cookies") or {}).items():
            parts.append(f"{name}={value}")

        redirect_url: Optional[str] = response.get("redirect_url")
        if redirect_url:
            parts.append(str(redirect_url))

        body: Optional[Union[str, bytes]] = response.get("body")
        if body:
            parts.append(cls._decode_body(body))

        return "\n".join(parts)

    @staticmethod
    def _decode_body(body: Union[str, bytes]) -> str:
        if isinstance(body, bytes):
            return body.decode("utf-8", errors="replace")
        return str(body)

    @staticmethod
    def _extract_step_index(filename: str) -> Optional[int]:
        try:
            index_str: str = filename.split("_")[1].split(".")[0]
            return int(index_str)
        except (IndexError, ValueError) as e:
            print(f"[AVISO] Falha ao extrair step index do arquivo '{filename}': {e}")
            return None
