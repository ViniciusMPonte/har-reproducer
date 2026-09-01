from pathlib import Path

import pytest

from har_reproducer.models import Step, StepRequest
from tests.real.support.real_capture import RealCapture


def _write_step_request(base_dir: Path, index: int, request: StepRequest) -> None:
    original_requests_dir: Path = base_dir / "original_requests"
    original_requests_dir.mkdir(parents=True, exist_ok=True)
    path: Path = original_requests_dir / f"req_{index:04d}.json"
    path.write_text(request.model_dump_json(indent=2), encoding="utf-8")


def test_step_request_reconstructs_the_fabricated_request(tmp_path: Path) -> None:
    fabricated: StepRequest = StepRequest(
        url="https://example.com/login",
        method="POST",
        headers={"X-Custom": "abc"},
        cookies={"JSESSIONID": "segredo"},
        body='{"user":"a"}',
    )
    _write_step_request(tmp_path, 12, fabricated)
    capture: RealCapture = RealCapture(tmp_path)

    loaded: StepRequest = capture.step_request(12)

    assert loaded == fabricated


def test_step_wraps_the_step_request_with_the_matching_index(tmp_path: Path) -> None:
    fabricated: StepRequest = StepRequest(url="https://example.com/x", method="GET")
    _write_step_request(tmp_path, 12, fabricated)
    capture: RealCapture = RealCapture(tmp_path)

    step: Step = capture.step(12)

    assert step.index == 12
    assert step.request == capture.step_request(12)


def test_response_dirs_are_formatted_without_requiring_existence_on_disk(tmp_path: Path) -> None:
    capture: RealCapture = RealCapture(tmp_path)

    assert capture.real_responses_dir == tmp_path / "real_responses"
    assert capture.original_responses_dir == tmp_path / "original_responses"


def test_step_request_propagates_file_not_found_for_a_missing_index(tmp_path: Path) -> None:
    capture: RealCapture = RealCapture(tmp_path)

    with pytest.raises(FileNotFoundError):
        capture.step_request(999)
