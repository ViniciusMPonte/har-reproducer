from pathlib import Path

from tests.support.cli_invocation_result import CliInvocationResult
from tests.support.cli_invoker import CliInvoker


class SuccessCriterionScenario:

    def __init__(self, cli_invoker: CliInvoker, har_path: Path, tmp_path: Path) -> None:
        self.cli_invoker: CliInvoker = cli_invoker
        self.har_path: Path = har_path
        self.tmp_path: Path = tmp_path
        self.output_dir: Path = tmp_path / "out"

    def run(self, config_body: str) -> CliInvocationResult:
        argv: list[str] = ["run", "--har", str(self.har_path), "--mode", "dry", "--output", str(self.output_dir)]
        if config_body:
            argv.extend(["--config", str(self._write_config(config_body))])
        return self.cli_invoker.invoke(argv)

    def _write_config(self, config_body: str) -> Path:
        config_path: Path = self.tmp_path / "config.json"
        config_path.write_text(config_body, encoding="utf-8")
        return config_path
