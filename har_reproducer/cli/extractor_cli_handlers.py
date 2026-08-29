import json
from argparse import Namespace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from har_reproducer.fs_io import Workspace
from har_reproducer.models import Extractor
from har_reproducer.reproduction import ExtractorMetadataStore
from har_reproducer.session.session_store import SessionStore


class ExtractorCliHandlers:

    def handle_list(self, args: Namespace) -> bool:
        return self._run_safely(lambda: self._list(args))

    def handle_get(self, args: Namespace) -> bool:
        return self._run_safely(lambda: self._get(args))

    def _list(self, args: Namespace) -> Dict[str, Any]:
        workspace: Workspace = self._prepare_workspace(Path(args.output), require_curls=False)
        extractors: List[Extractor] = ExtractorMetadataStore(workspace).list_all()
        return {
            "ok": True,
            "extractors": [self._annotate(workspace, extractor) for extractor in extractors],
        }

    def _get(self, args: Namespace) -> Dict[str, Any]:
        workspace: Workspace = self._prepare_workspace(Path(args.output), require_curls=False)
        extractor: Optional[Extractor] = ExtractorMetadataStore(workspace).load(args.token_id)
        if extractor is None:
            return {"ok": False, "error": f"extractor not found: {args.token_id}"}
        return {"ok": True, "extractor": self._annotate(workspace, extractor)}

    def _annotate(self, workspace: Workspace, extractor: Extractor) -> Dict[str, Any]:
        payload: Dict[str, Any] = json.loads(extractor.model_dump_json())
        payload["referenced_by"] = self._referencing_curls(workspace, extractor.token_id)
        return payload

    def _referencing_curls(self, workspace: Workspace, token_id: str) -> List[str]:
        referencing: List[str] = []
        for curl_file in sorted(workspace.curls.glob("req_*.curl.sh")):
            curl_text: str = curl_file.read_text(encoding="utf-8")
            if token_id in SessionStore.TOKEN_PLACEHOLDER_PATTERN.findall(curl_text):
                referencing.append(curl_file.name)
        return referencing

    @staticmethod
    def _prepare_workspace(output_dir: Path, require_curls: bool) -> Workspace:
        if not output_dir.exists():
            raise ValueError(f"Workspace directory does not exist: {output_dir}")

        workspace: Workspace = Workspace(output_dir)
        if require_curls and not any(workspace.curls.glob("req_*.curl.sh")):
            raise ValueError(f"Workspace has no curl files: {output_dir}")
        return workspace

    @staticmethod
    def _emit(payload: Dict[str, Any]) -> bool:
        print(json.dumps(payload))
        return bool(payload.get("ok", False))

    def _run_safely(self, action: Callable[[], Dict[str, Any]]) -> bool:
        try:
            payload: Dict[str, Any] = action()
        except Exception as exc:
            return self._emit({"ok": False, "error": str(exc)})
        return self._emit(payload)
