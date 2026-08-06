from pathlib import Path

from tests.support.cli_invocation_result import CliInvocationResult
from tests.support.cli_invoker import CliInvoker
from tests.support.golden_workspace_factory import GoldenWorkspaceFactory
from tests.support.success_criterion_scenario import SuccessCriterionScenario


def test_criteria_status_code_success(
        cli_invoker: CliInvoker,
        minimal_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: SuccessCriterionScenario = SuccessCriterionScenario(cli_invoker, minimal_flow_har, tmp_path)
    result: CliInvocationResult = scenario.run('{"success_criteria": [{"type": "status_code", "expected": 200}]}')

    assert result.exception is None
    assert "Final Validation Result: ✓ SUCCESS" in result.stdout
    assert "Reproduction SUCCESSFUL: Target state reached." in result.stdout
    assert not any((scenario.output_dir / "extractors").glob("*"))
    scenario.output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.output_dir).assert_matches(golden_dir / "criteria_status_code_success")


def test_criteria_status_code_failure(
        cli_invoker: CliInvoker,
        minimal_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: SuccessCriterionScenario = SuccessCriterionScenario(cli_invoker, minimal_flow_har, tmp_path)
    result: CliInvocationResult = scenario.run('{"success_criteria": [{"type": "status_code", "expected": 500}]}')

    assert result.exception is None
    assert "Final Validation Result: ✗ FAILURE" in result.stdout
    assert "Reproduction FAILED: Target state not reached." in result.stdout
    assert not any((scenario.output_dir / "extractors").glob("*"))
    scenario.output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.output_dir).assert_matches(golden_dir / "criteria_status_code_failure")


def test_criteria_body_contains_success(
        cli_invoker: CliInvoker,
        minimal_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: SuccessCriterionScenario = SuccessCriterionScenario(cli_invoker, minimal_flow_har, tmp_path)
    result: CliInvocationResult = scenario.run('{"success_criteria": [{"type": "body_contains", "expected": "pronto"}]}')

    assert result.exception is None
    assert "Final Validation Result: ✓ SUCCESS" in result.stdout
    assert "Reproduction SUCCESSFUL: Target state reached." in result.stdout
    assert not any((scenario.output_dir / "extractors").glob("*"))
    scenario.output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.output_dir).assert_matches(golden_dir / "criteria_body_contains_success")


def test_criteria_body_contains_failure(
        cli_invoker: CliInvoker,
        minimal_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: SuccessCriterionScenario = SuccessCriterionScenario(cli_invoker, minimal_flow_har, tmp_path)
    result: CliInvocationResult = scenario.run('{"success_criteria": [{"type": "body_contains", "expected": "ausente"}]}')

    assert result.exception is None
    assert "Final Validation Result: ✗ FAILURE" in result.stdout
    assert "Reproduction FAILED: Target state not reached." in result.stdout
    assert not any((scenario.output_dir / "extractors").glob("*"))
    scenario.output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.output_dir).assert_matches(golden_dir / "criteria_body_contains_failure")


def test_criteria_url_match_success(
        cli_invoker: CliInvoker,
        minimal_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: SuccessCriterionScenario = SuccessCriterionScenario(cli_invoker, minimal_flow_har, tmp_path)
    result: CliInvocationResult = scenario.run('{"success_criteria": [{"type": "url_match", "expected": "done\\\\?ok=1"}]}')

    assert result.exception is None
    assert "Final Validation Result: ✓ SUCCESS" in result.stdout
    assert "Reproduction SUCCESSFUL: Target state reached." in result.stdout
    assert not any((scenario.output_dir / "extractors").glob("*"))
    scenario.output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.output_dir).assert_matches(golden_dir / "criteria_url_match_success")


def test_criteria_url_match_failure(
        cli_invoker: CliInvoker,
        minimal_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: SuccessCriterionScenario = SuccessCriterionScenario(cli_invoker, minimal_flow_har, tmp_path)
    result: CliInvocationResult = scenario.run('{"success_criteria": [{"type": "url_match", "expected": "nunca"}]}')

    assert result.exception is None
    assert "Final Validation Result: ✗ FAILURE" in result.stdout
    assert "Reproduction FAILED: Target state not reached." in result.stdout
    assert not any((scenario.output_dir / "extractors").glob("*"))
    scenario.output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.output_dir).assert_matches(golden_dir / "criteria_url_match_failure")


def test_criteria_html_element_present_success(
        cli_invoker: CliInvoker,
        minimal_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: SuccessCriterionScenario = SuccessCriterionScenario(cli_invoker, minimal_flow_har, tmp_path)
    result: CliInvocationResult = scenario.run('{"success_criteria": [{"type": "html_element_present", "expected": "#marker"}]}')

    assert result.exception is None
    assert "Final Validation Result: ✓ SUCCESS" in result.stdout
    assert "Reproduction SUCCESSFUL: Target state reached." in result.stdout
    assert not any((scenario.output_dir / "extractors").glob("*"))
    scenario.output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.output_dir).assert_matches(
        golden_dir / "criteria_html_element_present_success")


def test_criteria_html_element_present_failure(
        cli_invoker: CliInvoker,
        minimal_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: SuccessCriterionScenario = SuccessCriterionScenario(cli_invoker, minimal_flow_har, tmp_path)
    result: CliInvocationResult = scenario.run('{"success_criteria": [{"type": "html_element_present", "expected": "#nada"}]}')

    assert result.exception is None
    assert "Final Validation Result: ✗ FAILURE" in result.stdout
    assert "Reproduction FAILED: Target state not reached." in result.stdout
    assert not any((scenario.output_dir / "extractors").glob("*"))
    scenario.output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.output_dir).assert_matches(
        golden_dir / "criteria_html_element_present_failure")


def test_criteria_empty_list_is_successful_without_verdict_line(
        cli_invoker: CliInvoker,
        minimal_flow_har: Path,
        golden_workspace_factory: GoldenWorkspaceFactory,
        golden_dir: Path,
        tmp_path: Path,
) -> None:
    scenario: SuccessCriterionScenario = SuccessCriterionScenario(cli_invoker, minimal_flow_har, tmp_path)
    result: CliInvocationResult = scenario.run("")

    assert result.exception is None
    assert "Reproduction SUCCESSFUL" in result.stdout
    assert "Final Validation Result" not in result.stdout
    assert not any((scenario.output_dir / "extractors").glob("*"))
    scenario.output_dir.joinpath("stdout.txt").write_text(result.stdout, encoding="utf-8")

    golden_workspace_factory.create(scenario.output_dir).assert_matches(golden_dir / "criteria_empty_list")
