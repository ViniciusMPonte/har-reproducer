from pathlib import Path
from typing import Dict, List, Optional

from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import ExtractorSampleResult
from har_reproducer.reproduction.extractor_validator import ExtractorValidator
from har_reproducer.reproduction.script_executor import ScriptExecutor

VALID_RESPONSE: Dict[str, object] = {
    "status_code": 200,
    "headers": {"X-Token": "certo"},
    "cookies": {},
    "cookie_attributes": {},
    "body": "{}",
    "body_mime": "application/json",
}


def _build_validator(tmp_path: Path) -> ExtractorValidator:
    workspace: Workspace = Workspace(tmp_path)
    return ExtractorValidator(workspace, ScriptExecutor())


def test_defines_expected_function_true_for_matching_name(tmp_path: Path) -> None:
    validator: ExtractorValidator = _build_validator(tmp_path)

    result: bool = validator.defines_expected_function(
        "deadbeef", "def extract_t_deadbeef(response):\n    return 'x'\n"
    )

    assert result is True


def test_defines_expected_function_false_for_divergent_name(tmp_path: Path) -> None:
    validator: ExtractorValidator = _build_validator(tmp_path)

    result: bool = validator.defines_expected_function(
        "deadbeef", "def extract_wrong_name(response):\n    return 'x'\n"
    )

    assert result is False


def test_defines_expected_function_does_not_match_substring_mid_line(tmp_path: Path) -> None:
    validator: ExtractorValidator = _build_validator(tmp_path)

    result: bool = validator.defines_expected_function(
        "deadbeef", "    # def extract_t_deadbeef(response): not a real def\n"
    )

    assert result is False


def test_run_against_samples_rejects_sample_with_invalid_shape_without_executing(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    validator: ExtractorValidator = ExtractorValidator(workspace, ScriptExecutor())
    code: str = "def extract_t_tok1(response):\n    return response['headers']['X-Token']\n"

    results: List[ExtractorSampleResult] = validator.run_against_samples(
        "tok1", code, {"bad_sample": {"foo": "bar"}}
    )

    assert len(results) == 1
    assert results[0].sample_label == "bad_sample"
    assert results[0].error is not None
    assert results[0].output is None
    assert list(workspace.temp_extractors.iterdir()) == []


def test_run_against_samples_runs_two_samples_independently(tmp_path: Path) -> None:
    validator: ExtractorValidator = _build_validator(tmp_path)
    code: str = "def extract_t_tok1(response):\n    return response['headers']['X-Token']\n"
    correct_response: Dict[str, object] = dict(VALID_RESPONSE, headers={"X-Token": "certo"})
    wrong_response: Dict[str, object] = dict(VALID_RESPONSE, headers={"X-Token": "errado"})

    results: List[ExtractorSampleResult] = validator.run_against_samples(
        "tok1", code, {"sample_a": correct_response, "sample_b": wrong_response}
    )

    by_label: Dict[str, ExtractorSampleResult] = {result.sample_label: result for result in results}
    assert by_label["sample_a"].output == "certo"
    assert by_label["sample_b"].output == "errado"


def test_run_against_samples_leaves_no_residual_temp_file(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    validator: ExtractorValidator = ExtractorValidator(workspace, ScriptExecutor())
    code: str = "def extract_t_tok1(response):\n    return response['headers']['X-Token']\n"

    validator.run_against_samples(
        "tok1", code, {"ok": VALID_RESPONSE, "bad_shape": {"foo": "bar"}}
    )

    assert list(workspace.temp_extractors.iterdir()) == []


def test_run_against_samples_leaves_no_residual_temp_file_on_execution_failure(tmp_path: Path) -> None:
    workspace: Workspace = Workspace(tmp_path)
    validator: ExtractorValidator = ExtractorValidator(workspace, ScriptExecutor())
    code: str = "def extract_t_tok1(response):\n    raise ValueError('boom')\n"

    results: List[ExtractorSampleResult] = validator.run_against_samples(
        "tok1", code, {"ok": VALID_RESPONSE}
    )

    assert results[0].error is not None
    assert list(workspace.temp_extractors.iterdir()) == []


def test_run_against_samples_matches_expected_value(tmp_path: Path) -> None:
    validator: ExtractorValidator = _build_validator(tmp_path)
    code: str = "def extract_t_tok1(response):\n    return response['headers']['X-Token']\n"
    correct_response: Dict[str, object] = dict(VALID_RESPONSE, headers={"X-Token": "certo"})
    wrong_response: Dict[str, object] = dict(VALID_RESPONSE, headers={"X-Token": "errado"})

    results: List[ExtractorSampleResult] = validator.run_against_samples(
        "tok1",
        code,
        {"origin_step": correct_response, "other": wrong_response},
        expected_values={"origin_step": "certo"},
    )

    by_label: Dict[str, ExtractorSampleResult] = {result.sample_label: result for result in results}
    assert by_label["origin_step"].matches_expected is True
    assert by_label["other"].matches_expected is None


def test_run_against_samples_matches_expected_value_false_when_mismatched(tmp_path: Path) -> None:
    validator: ExtractorValidator = _build_validator(tmp_path)
    code: str = "def extract_t_tok1(response):\n    return response['headers']['X-Token']\n"
    wrong_response: Dict[str, object] = dict(VALID_RESPONSE, headers={"X-Token": "errado"})

    results: List[ExtractorSampleResult] = validator.run_against_samples(
        "tok1",
        code,
        {"origin_step": wrong_response},
        expected_values={"origin_step": "certo"},
    )

    assert results[0].matches_expected is False
