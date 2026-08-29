import json
from pathlib import Path
from typing import Any, Dict

from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import AgentType, Extractor
from har_reproducer.reproduction.extractor_metadata_store import ExtractorMetadataStore
from tests.support.cli_invocation_result import CliInvocationResult
from tests.support.cli_invoker import CliInvoker


def _extractor(token_id: str) -> Extractor:
    return Extractor(token_id=token_id, code="return 1", agent_type=AgentType.REGEX)


def _build_workspace_with_curls(tmp_path: Path) -> Path:
    output_dir: Path = tmp_path / "ws"
    workspace: Workspace = Workspace(output_dir)
    workspace.curl_file(0).write_text("#!/bin/bash\ncurl 'https://exemplo.com'", encoding="utf-8")
    return output_dir


def _invoke_json(argv: list) -> Dict[str, Any]:
    invoker: CliInvoker = CliInvoker()
    result: CliInvocationResult = invoker.invoke(argv)
    assert result.exception is None or isinstance(result.exception, SystemExit)
    return json.loads(result.stdout.strip())


def test_extractor_list_rejects_nonexistent_output_dir_without_creating_it(tmp_path: Path) -> None:
    output_dir: Path = tmp_path / "does-not-exist"

    payload: Dict[str, Any] = _invoke_json(["extractor", "list", "--output", str(output_dir)])

    assert payload == {"ok": False, "error": f"Workspace directory does not exist: {output_dir}"}
    assert not output_dir.exists()


def test_extractor_list_on_empty_workspace_returns_empty_list(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)

    payload: Dict[str, Any] = _invoke_json(["extractor", "list", "--output", str(output_dir)])

    assert payload == {"ok": True, "extractors": []}


def test_extractor_list_annotates_extractors_with_referencing_curls(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    store: ExtractorMetadataStore = ExtractorMetadataStore(workspace)
    store.save(_extractor("aaaa"))
    store.save(_extractor("bbbb"))
    workspace.curl_file(0).write_text(
        "#!/bin/bash\n"
        "# [Token aaaa comes from response of step 0000]\n"
        "curl 'https://exemplo.com' -H 'X-Token: {{extractor:aaaa}}'",
        encoding="utf-8",
    )

    payload: Dict[str, Any] = _invoke_json(["extractor", "list", "--output", str(output_dir)])

    assert payload["ok"] is True
    by_id: Dict[str, Dict[str, Any]] = {item["token_id"]: item for item in payload["extractors"]}
    assert by_id["aaaa"]["referenced_by"] == ["req_0000.curl.sh"]
    assert by_id["bbbb"]["referenced_by"] == []


def test_extractor_list_uses_placeholder_in_body_even_without_comment_line(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    store: ExtractorMetadataStore = ExtractorMetadataStore(workspace)
    store.save(_extractor("cccc"))
    workspace.curl_file(0).write_text(
        "#!/bin/bash\ncurl 'https://exemplo.com' -H 'X-Token: {{extractor:cccc}}'",
        encoding="utf-8",
    )

    payload: Dict[str, Any] = _invoke_json(["extractor", "list", "--output", str(output_dir)])

    by_id: Dict[str, Dict[str, Any]] = {item["token_id"]: item for item in payload["extractors"]}
    assert by_id["cccc"]["referenced_by"] == ["req_0000.curl.sh"]


def test_extractor_get_returns_not_found_for_missing_token(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)

    payload: Dict[str, Any] = _invoke_json(
        ["extractor", "get", "--output", str(output_dir), "--token-id", "deadbeef"]
    )

    assert payload == {"ok": False, "error": "extractor not found: deadbeef"}


def test_extractor_get_returns_extractor_with_referenced_by(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    ExtractorMetadataStore(workspace).save(_extractor("aaaa"))

    payload: Dict[str, Any] = _invoke_json(
        ["extractor", "get", "--output", str(output_dir), "--token-id", "aaaa"]
    )

    assert payload["ok"] is True
    assert payload["extractor"]["token_id"] == "aaaa"
    assert payload["extractor"]["referenced_by"] == []


def test_extractor_get_missing_required_flag_routes_argparse_error_to_json(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    invoker: CliInvoker = CliInvoker()

    result: CliInvocationResult = invoker.invoke(["extractor", "get", "--output", str(output_dir)])

    assert isinstance(result.exception, SystemExit)
    payload: Dict[str, Any] = json.loads(result.stdout.strip())
    assert payload == {"ok": False, "error": "invalid arguments for extractor command"}
    assert "usage" not in result.stdout.lower()


def test_extractor_unknown_action_routes_argparse_error_to_json() -> None:
    invoker: CliInvoker = CliInvoker()

    result: CliInvocationResult = invoker.invoke(["extractor", "not-a-real-action"])

    assert isinstance(result.exception, SystemExit)
    payload: Dict[str, Any] = json.loads(result.stdout.strip())
    assert payload == {"ok": False, "error": "invalid arguments for extractor command"}


def test_existing_commands_still_work_after_extractor_wiring(tmp_path: Path) -> None:
    invoker: CliInvoker = CliInvoker()

    result: CliInvocationResult = invoker.invoke(["parse"])

    assert isinstance(result.exception, SystemExit)
