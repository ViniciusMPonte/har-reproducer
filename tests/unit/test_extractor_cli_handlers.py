import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import AgentType, Extractor
from har_reproducer.reproduction.extractor_metadata_store import ExtractorMetadataStore
from har_reproducer.reproduction.extractor_runner import ExtractorRunner
from har_reproducer.reproduction.script_executor import ScriptExecutor
from har_reproducer.replay.curl_token_comment import CurlTokenComment
from tests.support.cli_invocation_result import CliInvocationResult
from tests.support.cli_invoker import CliInvoker

VALID_RESPONSE: Dict[str, object] = {
    "status_code": 200,
    "headers": {"X-Token": "valor_certo"},
    "cookies": {},
    "cookie_attributes": {},
    "body": "{}",
    "body_mime": "application/json",
}

WORKING_CODE: str = "def extract_t_deadbeef(response):\n    return response['headers']['X-Token']\n"


def _extractor(token_id: str) -> Extractor:
    return Extractor(token_id=token_id, code="return 1", agent_type=AgentType.REGEX)


def _build_workspace_with_curls(tmp_path: Path) -> Path:
    output_dir: Path = tmp_path / "ws"
    workspace: Workspace = Workspace(output_dir)
    workspace.curl_file(0).write_text("#!/bin/bash\ncurl 'https://exemplo.com'", encoding="utf-8")
    return output_dir


def _write_response(workspace: Workspace, step_index: int, response: Dict[str, object]) -> None:
    workspace.response_file(step_index).write_text(json.dumps(response), encoding="utf-8")


def _write_code_file(tmp_path: Path, code: str) -> Path:
    code_file: Path = tmp_path / "code.py"
    code_file.write_text(code, encoding="utf-8")
    return code_file


def _extractors_dir_files(workspace: Workspace) -> List[str]:
    return sorted(path.name for path in workspace.extractors.iterdir())


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


def test_extractor_create_rejects_divergent_function_name_without_writing_anything(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    code_file: Path = _write_code_file(tmp_path, "def extract_wrong_name(response):\n    return 'x'\n")

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "create", "--output", str(output_dir),
            "--token-id", "deadbeef", "--code-file", str(code_file),
            "--agent-type", AgentType.REGEX.value, "--origin-step", "0",
        ]
    )

    assert payload["ok"] is False
    assert "extract_t_deadbeef" in payload["error"]
    assert _extractors_dir_files(workspace) == []


def test_extractor_create_rejects_missing_response_file_without_writing_anything(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    code_file: Path = _write_code_file(tmp_path, WORKING_CODE)

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "create", "--output", str(output_dir),
            "--token-id", "deadbeef", "--code-file", str(code_file),
            "--agent-type", AgentType.REGEX.value, "--origin-step", "7",
        ]
    )

    assert payload == {"ok": False, "error": "response for step 7 not found"}
    assert _extractors_dir_files(workspace) == []


def test_extractor_create_rejects_mismatched_captured_value_and_leaves_extractors_dir_empty(
        tmp_path: Path,
) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    _write_response(workspace, 0, VALID_RESPONSE)
    code_file: Path = _write_code_file(tmp_path, WORKING_CODE)

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "create", "--output", str(output_dir),
            "--token-id", "deadbeef", "--code-file", str(code_file),
            "--agent-type", AgentType.REGEX.value, "--origin-step", "0",
            "--captured-value", "valor_errado",
        ]
    )

    assert payload["ok"] is False
    assert _extractors_dir_files(workspace) == []
    assert list(workspace.temp_extractors.iterdir()) == []


def test_extractor_create_success_writes_py_and_meta_and_is_runnable(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    _write_response(workspace, 0, VALID_RESPONSE)
    code_file: Path = _write_code_file(tmp_path, WORKING_CODE)

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "create", "--output", str(output_dir),
            "--token-id", "deadbeef", "--code-file", str(code_file),
            "--agent-type", AgentType.REGEX.value, "--origin-step", "0",
            "--captured-value", "valor_certo",
        ]
    )

    assert payload["ok"] is True
    assert payload["token_id"] == "deadbeef"
    assert payload["samples"][0]["sample_label"] == "origin_step"
    assert payload["samples"][0]["matches_expected"] is True
    assert _extractors_dir_files(workspace) == ["extract_deadbeef.meta.json", "extract_deadbeef.py"]

    persisted: Optional[Extractor] = ExtractorMetadataStore(workspace).load("deadbeef")
    assert persisted is not None
    assert persisted.origin_step == 0

    runner: ExtractorRunner = ExtractorRunner(workspace, ScriptExecutor())
    assert runner.run_existing("deadbeef") == "valor_certo"


def test_extractor_create_rejects_already_existing_token_id_without_overwriting(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    _write_response(workspace, 0, VALID_RESPONSE)
    store: ExtractorMetadataStore = ExtractorMetadataStore(workspace)
    store.save(Extractor(token_id="deadbeef", code=WORKING_CODE, agent_type=AgentType.REGEX, origin_step=0))
    code_file: Path = _write_code_file(tmp_path, WORKING_CODE)

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "create", "--output", str(output_dir),
            "--token-id", "deadbeef", "--code-file", str(code_file),
            "--agent-type", AgentType.REGEX.value, "--origin-step", "0",
        ]
    )

    assert payload == {"ok": False, "error": "token_id already exists, use update"}
    reloaded: Optional[Extractor] = store.load("deadbeef")
    assert reloaded is not None
    assert reloaded.code == WORKING_CODE


def test_extractor_create_rejects_non_hex_token_id(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    _write_response(workspace, 0, VALID_RESPONSE)
    code_file: Path = _write_code_file(tmp_path, "def extract_t_ABC(response):\n    return 'x'\n")

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "create", "--output", str(output_dir),
            "--token-id", "ABC", "--code-file", str(code_file),
            "--agent-type", AgentType.REGEX.value, "--origin-step", "0",
        ]
    )

    assert payload["ok"] is False
    assert "token_id" in payload["error"]
    assert _extractors_dir_files(workspace) == []


def test_extractor_update_without_origin_step_reuses_persisted_origin_step(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    _write_response(workspace, 0, VALID_RESPONSE)
    store: ExtractorMetadataStore = ExtractorMetadataStore(workspace)
    store.save(
        Extractor(
            token_id="deadbeef", code="def extract_t_deadbeef(response):\n    return 'old'\n",
            agent_type=AgentType.REGEX, origin_step=0,
        )
    )
    code_file: Path = _write_code_file(tmp_path, WORKING_CODE)

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "update", "--output", str(output_dir),
            "--token-id", "deadbeef", "--code-file", str(code_file),
        ]
    )

    assert payload["ok"] is True
    persisted: Optional[Extractor] = store.load("deadbeef")
    assert persisted is not None
    assert persisted.origin_step == 0
    assert persisted.code == WORKING_CODE


def test_extractor_update_rejects_nonexistent_token_id(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    code_file: Path = _write_code_file(tmp_path, WORKING_CODE)

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "update", "--output", str(output_dir),
            "--token-id", "deadbeef", "--code-file", str(code_file),
        ]
    )

    assert payload == {"ok": False, "error": "token_id does not exist, use create"}


def test_extractor_delete_rejects_when_referenced_by_curl_without_force(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    ExtractorMetadataStore(workspace).save(_extractor("aaaa"))
    workspace.curl_file(0).write_text(
        "#!/bin/bash\n"
        "# [Token aaaa comes from response of step 0000]\n"
        "curl 'https://exemplo.com' -H 'X-Token: {{extractor:aaaa}}'",
        encoding="utf-8",
    )

    payload: Dict[str, Any] = _invoke_json(
        ["extractor", "delete", "--output", str(output_dir), "--token-id", "aaaa"]
    )

    assert payload["ok"] is False
    assert "still referenced by" in payload["error"]
    assert payload["referenced_by"] == ["req_0000.curl.sh"]
    assert workspace.extractor_meta_file("aaaa").exists()


def test_extractor_delete_rejects_when_placeholder_in_body_without_comment_line(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    ExtractorMetadataStore(workspace).save(_extractor("cccc"))
    workspace.curl_file(0).write_text(
        "#!/bin/bash\ncurl 'https://exemplo.com' -H 'X-Token: {{extractor:cccc}}'",
        encoding="utf-8",
    )

    payload: Dict[str, Any] = _invoke_json(
        ["extractor", "delete", "--output", str(output_dir), "--token-id", "cccc"]
    )

    assert payload["ok"] is False
    assert payload["referenced_by"] == ["req_0000.curl.sh"]
    assert workspace.extractor_meta_file("cccc").exists()


def test_extractor_delete_force_removes_despite_reference(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    ExtractorMetadataStore(workspace).save(_extractor("aaaa"))
    workspace.curl_file(0).write_text(
        "#!/bin/bash\n"
        "# [Token aaaa comes from response of step 0000]\n"
        "curl 'https://exemplo.com' -H 'X-Token: {{extractor:aaaa}}'",
        encoding="utf-8",
    )

    payload: Dict[str, Any] = _invoke_json(
        ["extractor", "delete", "--output", str(output_dir), "--token-id", "aaaa", "--force"]
    )

    assert payload["ok"] is True
    assert not workspace.extractor_file("aaaa").exists()
    assert not workspace.extractor_meta_file("aaaa").exists()


def test_extractor_delete_removes_when_not_referenced(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    ExtractorMetadataStore(workspace).save(_extractor("bbbb"))

    payload: Dict[str, Any] = _invoke_json(
        ["extractor", "delete", "--output", str(output_dir), "--token-id", "bbbb"]
    )

    assert payload["ok"] is True
    assert not workspace.extractor_file("bbbb").exists()
    assert not workspace.extractor_meta_file("bbbb").exists()


def test_extractor_delete_is_idempotent_when_meta_missing_but_py_exists(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    workspace.extractor_file("orfaa").write_text("def extract_t_orfaa(response):\n    return 'x'\n", encoding="utf-8")

    payload: Dict[str, Any] = _invoke_json(
        ["extractor", "delete", "--output", str(output_dir), "--token-id", "orfaa"]
    )

    assert payload["ok"] is True
    assert not workspace.extractor_file("orfaa").exists()


def test_extractor_delete_of_totally_nonexistent_token_does_not_raise(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)

    payload: Dict[str, Any] = _invoke_json(
        ["extractor", "delete", "--output", str(output_dir), "--token-id", "naoexiste"]
    )

    assert payload["ok"] is True


def test_extractor_bind_rejects_nonexistent_token_id_without_touching_curl(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    before: str = workspace.curl_file(0).read_text(encoding="utf-8")

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "bind", "--output", str(output_dir),
            "--token-id", "deadbeef", "--curl", "req_0000.curl.sh", "--value", "valor_certo",
        ]
    )

    assert payload == {"ok": False, "error": "token_id does not exist, use create first"}
    assert workspace.curl_file(0).read_text(encoding="utf-8") == before


def test_extractor_bind_success_writes_placeholder_and_dependency_line_from_extractor_origin_step(
        tmp_path: Path,
) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    workspace.curl_file(0).write_text(
        "#!/bin/bash\ncurl 'https://exemplo.com' -H 'X-Token: valor_certo'", encoding="utf-8"
    )
    ExtractorMetadataStore(workspace).save(
        Extractor(token_id="deadbeef", code=WORKING_CODE, agent_type=AgentType.REGEX, origin_step=3)
    )

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "bind", "--output", str(output_dir),
            "--token-id", "deadbeef", "--curl", "req_0000.curl.sh", "--value", "valor_certo",
        ]
    )

    assert payload == {"ok": True, "replacements": 1}
    curl_text: str = workspace.curl_file(0).read_text(encoding="utf-8")
    assert "{{extractor:deadbeef}}" in curl_text
    assert "# [Token deadbeef comes from response of step 0003]" in curl_text
    assert "valor_certo" not in curl_text


def test_extractor_bind_rejects_when_value_not_found_in_curl_without_writing(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    before: str = workspace.curl_file(0).read_text(encoding="utf-8")
    ExtractorMetadataStore(workspace).save(
        Extractor(token_id="deadbeef", code=WORKING_CODE, agent_type=AgentType.REGEX, origin_step=0)
    )

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "bind", "--output", str(output_dir),
            "--token-id", "deadbeef", "--curl", "req_0000.curl.sh", "--value", "nao_existe_no_curl",
        ]
    )

    assert payload == {"ok": False, "error": "literal_value not found in curl"}
    assert workspace.curl_file(0).read_text(encoding="utf-8") == before


def test_extractor_unbind_after_bind_restores_literal_and_removes_dependency_line(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    workspace.curl_file(0).write_text(
        "#!/bin/bash\ncurl 'https://exemplo.com' -H 'X-Token: valor_certo'", encoding="utf-8"
    )
    ExtractorMetadataStore(workspace).save(
        Extractor(token_id="deadbeef", code=WORKING_CODE, agent_type=AgentType.REGEX, origin_step=3)
    )
    bind_payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "bind", "--output", str(output_dir),
            "--token-id", "deadbeef", "--curl", "req_0000.curl.sh", "--value", "valor_certo",
        ]
    )
    assert bind_payload["ok"] is True

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "unbind", "--output", str(output_dir),
            "--token-id", "deadbeef", "--curl", "req_0000.curl.sh", "--value", "valor_certo",
        ]
    )

    assert payload == {"ok": True, "replacements": 1}
    curl_text: str = workspace.curl_file(0).read_text(encoding="utf-8")
    assert "{{extractor:deadbeef}}" not in curl_text
    assert "valor_certo" in curl_text
    assert CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH).parse(curl_text) == {}


def test_extractor_unbind_does_not_require_extractor_to_still_exist(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    workspace.curl_file(0).write_text(
        "#!/bin/bash\n"
        "# [Token deadbeef comes from response of step 0003]\n"
        "curl 'https://exemplo.com' -H 'X-Token: {{extractor:deadbeef}}'",
        encoding="utf-8",
    )

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "unbind", "--output", str(output_dir),
            "--token-id", "deadbeef", "--curl", "req_0000.curl.sh", "--value", "valor_certo",
        ]
    )

    assert payload == {"ok": True, "replacements": 1}
    curl_text: str = workspace.curl_file(0).read_text(encoding="utf-8")
    assert "{{extractor:deadbeef}}" not in curl_text
    assert "valor_certo" in curl_text


def test_extractor_unbind_rejects_when_token_not_bound_to_curl_without_writing(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    before: str = workspace.curl_file(0).read_text(encoding="utf-8")

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "unbind", "--output", str(output_dir),
            "--token-id", "deadbeef", "--curl", "req_0000.curl.sh", "--value", "valor_certo",
        ]
    )

    assert payload == {"ok": False, "error": "token not bound to this curl"}
    assert workspace.curl_file(0).read_text(encoding="utf-8") == before


def test_extractor_bind_unbind_delete_lifecycle_leaves_no_inconsistent_state(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    workspace.curl_file(0).write_text(
        "#!/bin/bash\ncurl 'https://exemplo.com' -H 'X-Token: valor_certo'", encoding="utf-8"
    )
    ExtractorMetadataStore(workspace).save(
        Extractor(token_id="deadbeef", code=WORKING_CODE, agent_type=AgentType.REGEX, origin_step=3)
    )

    bind_payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "bind", "--output", str(output_dir),
            "--token-id", "deadbeef", "--curl", "req_0000.curl.sh", "--value", "valor_certo",
        ]
    )
    assert bind_payload["ok"] is True

    unbind_payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "unbind", "--output", str(output_dir),
            "--token-id", "deadbeef", "--curl", "req_0000.curl.sh", "--value", "valor_certo",
        ]
    )
    assert unbind_payload["ok"] is True

    delete_payload: Dict[str, Any] = _invoke_json(
        ["extractor", "delete", "--output", str(output_dir), "--token-id", "deadbeef"]
    )

    assert delete_payload == {"ok": True, "token_id": "deadbeef"}
    assert not workspace.extractor_file("deadbeef").exists()
    assert not workspace.extractor_meta_file("deadbeef").exists()
    assert "{{extractor:deadbeef}}" not in workspace.curl_file(0).read_text(encoding="utf-8")


def test_extractor_update_changing_only_captured_value_preserves_other_fields(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    _write_response(workspace, 0, VALID_RESPONSE)
    store: ExtractorMetadataStore = ExtractorMetadataStore(workspace)
    store.save(Extractor(token_id="deadbeef", code=WORKING_CODE, agent_type=AgentType.REGEX, origin_step=0))

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "update", "--output", str(output_dir),
            "--token-id", "deadbeef", "--captured-value", "valor_certo",
        ]
    )

    assert payload["ok"] is True
    persisted: Optional[Extractor] = store.load("deadbeef")
    assert persisted is not None
    assert persisted.code == WORKING_CODE
    assert persisted.agent_type == AgentType.REGEX
    assert persisted.origin_step == 0
    assert persisted.captured_value == "valor_certo"


def test_extractor_test_uses_persisted_code_without_writing_anything(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    _write_response(workspace, 3, VALID_RESPONSE)
    store: ExtractorMetadataStore = ExtractorMetadataStore(workspace)
    store.save(Extractor(token_id="deadbeef", code=WORKING_CODE, agent_type=AgentType.REGEX, origin_step=3))
    meta_file: Path = workspace.extractor_meta_file("deadbeef")
    mtime_before: int = meta_file.stat().st_mtime_ns

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "test", "--output", str(output_dir),
            "--token-id", "deadbeef", "--sample", "res_0003.json",
        ]
    )

    assert payload["ok"] is True
    assert len(payload["results"]) == 1
    assert payload["results"][0]["sample_label"] == "res_0003.json"
    assert payload["results"][0]["output"] == "valor_certo"
    assert meta_file.stat().st_mtime_ns == mtime_before
    assert _extractors_dir_files(workspace) == ["extract_deadbeef.meta.json"]


def test_extractor_test_with_code_file_runs_against_multiple_samples_without_token_id(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    _write_response(workspace, 3, VALID_RESPONSE)
    _write_response(workspace, 7, {**VALID_RESPONSE, "headers": {"X-Token": "outro_valor"}})
    code_file: Path = _write_code_file(
        tmp_path, "def extract_token(response):\n    return response['headers']['X-Token']\n"
    )

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "test", "--output", str(output_dir),
            "--code-file", str(code_file),
            "--sample", "res_0003.json", "--sample", "res_0007.json",
        ]
    )

    assert payload["ok"] is True
    assert len(payload["results"]) == 2
    outputs: Dict[str, Any] = {result["sample_label"]: result["output"] for result in payload["results"]}
    assert outputs["res_0003.json"] == "valor_certo"
    assert outputs["res_0007.json"] == "outro_valor"
    assert _extractors_dir_files(workspace) == []


def test_extractor_test_without_token_id_or_code_file_rejects_clearly(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    _write_response(Workspace(output_dir), 3, VALID_RESPONSE)

    payload: Dict[str, Any] = _invoke_json(
        ["extractor", "test", "--output", str(output_dir), "--sample", "res_0003.json"]
    )

    assert payload == {"ok": False, "error": "either --token-id or --code-file must be provided"}


def test_extractor_test_rejects_nonexistent_token_id(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    _write_response(Workspace(output_dir), 3, VALID_RESPONSE)

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "test", "--output", str(output_dir),
            "--token-id", "deadbeef", "--sample", "res_0003.json",
        ]
    )

    assert payload == {"ok": False, "error": "extractor not found: deadbeef"}


def test_extractor_test_isolates_malformed_sample_without_aborting_others(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    _write_response(workspace, 3, VALID_RESPONSE)
    ExtractorMetadataStore(workspace).save(
        Extractor(token_id="deadbeef", code=WORKING_CODE, agent_type=AgentType.REGEX, origin_step=3)
    )
    bad_sample: Path = tmp_path / "malformado.json"
    bad_sample.write_text("{not valid json", encoding="utf-8")

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "test", "--output", str(output_dir),
            "--token-id", "deadbeef",
            "--sample", "res_0003.json", "--sample", str(bad_sample),
        ]
    )

    assert payload["ok"] is True
    results_by_label: Dict[str, Any] = {result["sample_label"]: result for result in payload["results"]}
    assert results_by_label["res_0003.json"]["output"] == "valor_certo"
    assert results_by_label["res_0003.json"]["error"] is None
    assert results_by_label["malformado.json"]["error"] is not None
    assert results_by_label["malformado.json"]["output"] is None


def test_extractor_test_with_expect_marks_matches_expected_and_null_when_absent(tmp_path: Path) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    _write_response(workspace, 3, VALID_RESPONSE)
    _write_response(workspace, 7, VALID_RESPONSE)
    ExtractorMetadataStore(workspace).save(
        Extractor(token_id="deadbeef", code=WORKING_CODE, agent_type=AgentType.REGEX, origin_step=3)
    )

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "test", "--output", str(output_dir),
            "--token-id", "deadbeef",
            "--sample", "res_0003.json", "--sample", "res_0007.json",
            "--expect", "res_0003.json=valor_certo",
        ]
    )

    assert payload["ok"] is True
    results_by_label: Dict[str, Any] = {result["sample_label"]: result for result in payload["results"]}
    assert results_by_label["res_0003.json"]["matches_expected"] is True
    assert results_by_label["res_0007.json"]["matches_expected"] is None


def test_extractor_test_resolves_relative_sample_from_original_responses_when_missing_in_real(
        tmp_path: Path,
) -> None:
    output_dir: Path = _build_workspace_with_curls(tmp_path)
    workspace: Workspace = Workspace(output_dir)
    workspace.original_response_file(9).write_text(json.dumps(VALID_RESPONSE), encoding="utf-8")
    ExtractorMetadataStore(workspace).save(
        Extractor(token_id="deadbeef", code=WORKING_CODE, agent_type=AgentType.REGEX, origin_step=9)
    )

    payload: Dict[str, Any] = _invoke_json(
        [
            "extractor", "test", "--output", str(output_dir),
            "--token-id", "deadbeef", "--sample", "res_0009.json",
        ]
    )

    assert payload["ok"] is True
    assert payload["results"][0]["output"] == "valor_certo"
