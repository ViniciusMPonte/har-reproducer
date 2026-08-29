import re
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import ValidationError

from har_reproducer.fs_io import Workspace
from har_reproducer.models import ExtractorSampleResult, ScriptExecutionResult, StepResponse
from har_reproducer.reproduction.script_executor import ScriptExecutor
from har_reproducer.templates import ExtractorTemplate, IdentifierSanitizer


class ExtractorValidator:
    SAMPLE_TIMEOUT_SECONDS: ClassVar[int] = 5
    INVALID_SHAPE_ERROR: ClassVar[str] = (
        "sample is not a valid response structure (missing headers/body/status_code/...)"
    )

    def __init__(self, workspace: Workspace, script_executor: ScriptExecutor) -> None:
        self.workspace: Workspace = workspace
        self.script_executor: ScriptExecutor = script_executor

    def defines_expected_function(self, token_id: str, code: str) -> bool:
        expected_name: str = f"extract_{IdentifierSanitizer.sanitize(token_id)}"
        return re.search(rf"^def {re.escape(expected_name)}\(", code, re.MULTILINE) is not None

    def run_against_samples(
            self,
            token_id: str,
            code: str,
            samples: Dict[str, Dict[str, Any]],
            expected_values: Optional[Dict[str, str]] = None,
    ) -> List[ExtractorSampleResult]:
        safe_token_id: str = IdentifierSanitizer.sanitize(token_id)
        results: List[ExtractorSampleResult] = []
        for index, (label, response) in enumerate(samples.items()):
            results.append(
                self._run_single_sample(safe_token_id, code, label, response, index, expected_values)
            )
        return results

    def _run_single_sample(
            self,
            safe_token_id: str,
            code: str,
            label: str,
            response: Dict[str, Any],
            index: int,
            expected_values: Optional[Dict[str, str]],
    ) -> ExtractorSampleResult:
        shape_error: Optional[str] = self._validate_sample_shape(response)
        if shape_error is not None:
            return ExtractorSampleResult(sample_label=label, error=shape_error)

        script_path: Path = self.workspace.temp_extractor_file(f"{safe_token_id}__{index}")
        try:
            script_path.write_text(
                ExtractorTemplate.render_temp_script(safe_token_id, code, response), encoding="utf-8"
            )
            return self._execute_sample(script_path, label, expected_values)
        finally:
            if script_path.exists():
                script_path.unlink()

    @staticmethod
    def _validate_sample_shape(response: Dict[str, Any]) -> Optional[str]:
        try:
            StepResponse.model_validate(response)
        except ValidationError:
            return ExtractorValidator.INVALID_SHAPE_ERROR
        return None

    def _execute_sample(
            self,
            script_path: Path,
            label: str,
            expected_values: Optional[Dict[str, str]],
    ) -> ExtractorSampleResult:
        result: ScriptExecutionResult = self.script_executor.run(script_path, self.SAMPLE_TIMEOUT_SECONDS)
        if result.timed_out:
            return ExtractorSampleResult(sample_label=label, error="Timeout during verification")
        if result.return_code != 0:
            error: str = result.stderr.strip() or "Extractor script failed with no output."
            return ExtractorSampleResult(sample_label=label, error=error)

        output: str = result.stdout.strip()
        matches_expected: Optional[bool] = self._matches_expected(label, output, expected_values)
        return ExtractorSampleResult(sample_label=label, output=output, matches_expected=matches_expected)

    @staticmethod
    def _matches_expected(
            label: str,
            output: str,
            expected_values: Optional[Dict[str, str]],
    ) -> Optional[bool]:
        if expected_values is None or label not in expected_values:
            return None
        return output == expected_values[label]
