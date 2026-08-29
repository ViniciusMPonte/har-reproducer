import json
import re
from argparse import Namespace
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, List, Optional

from har_reproducer.fs_io import Workspace
from har_reproducer.models import AgentType, Extractor, ExtractorSampleResult
from har_reproducer.replay.curl_token_comment import CurlTokenComment
from har_reproducer.reproduction import (
    ExtractorCurlBinder,
    ExtractorMetadataStore,
    ExtractorValidator,
    ScriptExecutor,
)
from har_reproducer.session.session_store import SessionStore
from har_reproducer.templates import ExtractorTemplate, IdentifierSanitizer


class ExtractorCliHandlers:
    TOKEN_ID_PATTERN: ClassVar[re.Pattern] = re.compile(r"[a-f0-9]+")

    def handle_list(self, args: Namespace) -> bool:
        return self._run_safely(lambda: self._list(args))

    def handle_get(self, args: Namespace) -> bool:
        return self._run_safely(lambda: self._get(args))

    def handle_create(self, args: Namespace) -> bool:
        return self._run_safely(lambda: self._create_or_update(args, is_update=False))

    def handle_update(self, args: Namespace) -> bool:
        return self._run_safely(lambda: self._create_or_update(args, is_update=True))

    def handle_delete(self, args: Namespace) -> bool:
        return self._run_safely(lambda: self._delete(args))

    def handle_bind(self, args: Namespace) -> bool:
        return self._run_safely(lambda: self._bind(args))

    def handle_unbind(self, args: Namespace) -> bool:
        return self._run_safely(lambda: self._unbind(args))

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

    def _delete(self, args: Namespace) -> Dict[str, Any]:
        workspace: Workspace = self._prepare_workspace(Path(args.output), require_curls=False)
        referencing: List[str] = self._referencing_curls(workspace, args.token_id)
        if referencing and not args.force:
            return {
                "ok": False,
                "error": f"still referenced by {', '.join(referencing)}",
                "referenced_by": referencing,
            }

        workspace.extractor_file(args.token_id).unlink(missing_ok=True)
        workspace.extractor_meta_file(args.token_id).unlink(missing_ok=True)
        return {"ok": True, "token_id": args.token_id}

    def _bind(self, args: Namespace) -> Dict[str, Any]:
        workspace: Workspace = self._prepare_workspace(Path(args.output), require_curls=False)
        extractor: Optional[Extractor] = ExtractorMetadataStore(workspace).load(args.token_id)
        if extractor is None:
            return {"ok": False, "error": "token_id does not exist, use create first"}

        curl_file: Path = workspace.curls / args.curl
        curl_text: str = curl_file.read_text(encoding="utf-8")
        new_curl_text, replacements = self._curl_binder().bind(
            curl_text, args.token_id, extractor.origin_step, args.value
        )
        if replacements == 0:
            return {"ok": False, "error": "literal_value not found in curl"}

        curl_file.write_text(new_curl_text, encoding="utf-8")
        return {"ok": True, "replacements": replacements}

    def _unbind(self, args: Namespace) -> Dict[str, Any]:
        workspace: Workspace = self._prepare_workspace(Path(args.output), require_curls=False)
        curl_file: Path = workspace.curls / args.curl
        curl_text: str = curl_file.read_text(encoding="utf-8")
        new_curl_text, replacements = self._curl_binder().unbind(curl_text, args.token_id, args.value)
        if replacements == 0:
            return {"ok": False, "error": "token not bound to this curl"}

        curl_file.write_text(new_curl_text, encoding="utf-8")
        return {"ok": True, "replacements": replacements}

    @staticmethod
    def _curl_binder() -> ExtractorCurlBinder:
        return ExtractorCurlBinder(CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH))

    def _create_or_update(self, args: Namespace, is_update: bool) -> Dict[str, Any]:
        workspace: Workspace = self._prepare_workspace(Path(args.output), require_curls=False)
        metadata_store: ExtractorMetadataStore = ExtractorMetadataStore(workspace)

        if is_update:
            existing: Optional[Extractor] = metadata_store.load(args.token_id)
            if existing is None:
                return {"ok": False, "error": "token_id does not exist, use create"}
            extractor: Extractor = self._merge_extractor(existing, args)
        else:
            extractor = self._build_extractor(args)

        if self.TOKEN_ID_PATTERN.fullmatch(extractor.token_id) is None:
            return {"ok": False, "error": f"token_id must match [a-f0-9]+: {extractor.token_id}"}

        if not is_update and metadata_store.load(extractor.token_id) is not None:
            return {"ok": False, "error": "token_id already exists, use update"}

        validator: ExtractorValidator = ExtractorValidator(workspace, ScriptExecutor())
        if not validator.defines_expected_function(extractor.token_id, extractor.code):
            expected_name: str = f"extract_{IdentifierSanitizer.sanitize(extractor.token_id)}"
            return {"ok": False, "error": f"code does not define expected function {expected_name}"}

        if extractor.origin_step is None:
            return {"ok": False, "error": "origin_step is required"}

        response_file: Path = workspace.response_file(extractor.origin_step)
        if not response_file.exists():
            return {"ok": False, "error": f"response for step {extractor.origin_step} not found"}

        return self._validate_and_persist(workspace, metadata_store, validator, extractor, response_file)

    @staticmethod
    def _build_extractor(args: Namespace) -> Extractor:
        return Extractor(
            token_id=args.token_id,
            code=Path(args.code_file).read_text(encoding="utf-8"),
            verified=bool(args.verified),
            agent_type=AgentType(args.agent_type),
            origin_step=args.origin_step,
            captured_value=args.captured_value,
        )

    @staticmethod
    def _merge_extractor(existing: Extractor, args: Namespace) -> Extractor:
        code: str = (
            Path(args.code_file).read_text(encoding="utf-8") if args.code_file is not None else existing.code
        )
        agent_type: AgentType = (
            AgentType(args.agent_type) if args.agent_type is not None else existing.agent_type
        )
        origin_step: Optional[int] = args.origin_step if args.origin_step is not None else existing.origin_step
        captured_value: Optional[str] = (
            args.captured_value if args.captured_value is not None else existing.captured_value
        )
        verified: bool = args.verified if args.verified is not None else existing.verified
        return existing.model_copy(update={
            "code": code,
            "agent_type": agent_type,
            "origin_step": origin_step,
            "captured_value": captured_value,
            "verified": verified,
        })

    @staticmethod
    def _validate_and_persist(
            workspace: Workspace,
            metadata_store: ExtractorMetadataStore,
            validator: ExtractorValidator,
            extractor: Extractor,
            response_file: Path,
    ) -> Dict[str, Any]:
        response_dict: Dict[str, Any] = json.loads(response_file.read_text(encoding="utf-8"))
        expected_values: Optional[Dict[str, str]] = (
            {"origin_step": extractor.captured_value} if extractor.captured_value is not None else None
        )
        results: List[ExtractorSampleResult] = validator.run_against_samples(
            extractor.token_id, extractor.code, {"origin_step": response_dict}, expected_values
        )
        samples_payload: List[Dict[str, Any]] = [result.model_dump() for result in results]

        origin_result: ExtractorSampleResult = results[0]
        if origin_result.error is not None or origin_result.matches_expected is False:
            error: str = origin_result.error or "extracted value does not match captured_value"
            return {"ok": False, "error": error, "samples": samples_payload}

        safe_token_id: str = IdentifierSanitizer.sanitize(extractor.token_id)
        workspace.extractor_file(extractor.token_id).write_text(
            ExtractorTemplate.render_script(safe_token_id, extractor.code, extractor.origin_step),
            encoding="utf-8",
        )
        metadata_store.save(extractor)

        return {
            "ok": True,
            "token_id": extractor.token_id,
            "verified": extractor.verified,
            "samples": samples_payload,
        }

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
