from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

import pytest

from har_reproducer.cli import cli_handlers as cli_handlers_module
from har_reproducer.replay.replay_runner import ReplayRunner
from har_reproducer.reproduction import MitmProxyOrchestrator
from har_reproducer.session import CookieJar
from tests.support.cli_invocation_result import CliInvocationResult
from tests.support.cli_invoker import CliInvoker


class FakeReplayOptimizer:
    CAPTURED_KWARGS: ClassVar[Optional[Dict[str, Any]]] = None

    def __init__(self, **kwargs: Any) -> None:
        FakeReplayOptimizer.CAPTURED_KWARGS = kwargs

    def optimize(self, *args: Any, **kwargs: Any) -> List[int]:
        return [0]


def _bypass_mitm_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MitmProxyOrchestrator, "run", lambda self, callback: callback())


def _build_optimize_workspace(tmp_path: Path) -> Path:
    output_dir: Path = tmp_path / "ws"
    (output_dir / "curls").mkdir(parents=True)
    (output_dir / "curls" / "req_0000.curl.sh").write_text("curl 'https://exemplo.com'", encoding="utf-8")
    return output_dir


def test_handle_optimize_shares_cookie_jar_between_runner_and_optimizer(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir: Path = _build_optimize_workspace(tmp_path)
    _bypass_mitm_process(monkeypatch)
    monkeypatch.setattr(cli_handlers_module, "ReplayOptimizer", FakeReplayOptimizer)

    cli_invoker: CliInvoker = CliInvoker()
    result: CliInvocationResult = cli_invoker.invoke([
        "optimize", "--output", str(output_dir), "--to", "0",
        "--success-criteria", '[{"type":"status_code","expected":200}]',
    ])

    assert result.exception is None
    captured: Optional[Dict[str, Any]] = FakeReplayOptimizer.CAPTURED_KWARGS
    assert captured is not None
    runner: ReplayRunner = captured["schedule_executor"]
    cookie_jar: CookieJar = captured["cookie_jar"]
    assert runner.cookie_jar is cookie_jar
