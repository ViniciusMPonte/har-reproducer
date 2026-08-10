from pathlib import Path
from typing import Dict

from har_reproducer.reproduction.script_executor import ScriptExecutor


def _write_script(tmp_path: Path, name: str, content: str) -> Path:
    script_path: Path = tmp_path / name
    script_path.write_text(content, encoding="utf-8")
    return script_path


def test_run_returns_stdout_and_success_return_code(tmp_path: Path) -> None:
    script: Path = _write_script(tmp_path, "hello.py", "print('hello')")
    executor: ScriptExecutor = ScriptExecutor()

    result = executor.run(script, 5)

    assert result.return_code == 0
    assert result.stdout.strip() == "hello"
    assert result.timed_out is False


def test_run_propagates_non_zero_exit_code(tmp_path: Path) -> None:
    script: Path = _write_script(tmp_path, "exit3.py", "import sys\nsys.exit(3)")
    executor: ScriptExecutor = ScriptExecutor()

    result = executor.run(script, 5)

    assert result.return_code == 3


def test_run_marks_timed_out_when_exceeding_timeout(tmp_path: Path) -> None:
    script: Path = _write_script(tmp_path, "sleep.py", "import time\ntime.sleep(2)")
    executor: ScriptExecutor = ScriptExecutor()

    result = executor.run(script, 0.1)

    assert result.timed_out is True
    assert result.return_code == ScriptExecutor.TIMEOUT_RETURN_CODE == -1


def test_run_passes_environment_variables_to_subprocess(tmp_path: Path) -> None:
    script: Path = _write_script(tmp_path, "env.py", "import os\nprint(os.environ.get('MY_VAR'))")
    executor: ScriptExecutor = ScriptExecutor()
    env: Dict[str, str] = {"MY_VAR": "x"}

    result = executor.run(script, 5, env)

    assert result.stdout.strip() == "x"
