import shutil
from argparse import Namespace
from pathlib import Path
from typing import Optional, Type

from har_reproducer.config import ProjectConfigLoader
from har_reproducer.engines import Engine, EngineFactory, EngineMode
from har_reproducer.fs_io import HARParser
from har_reproducer.models import ProjectConfig
from har_reproducer.reproduction import MitmProxyOrchestrator


class CliHandlers:

    def __init__(
            self,
            engine_factory: Type[EngineFactory],
            har_parser: Type[HARParser],
    ) -> None:
        self._engine_factory: Type[EngineFactory] = engine_factory
        self._har_parser: Type[HARParser] = har_parser

    def handle_run(self, args: Namespace) -> None:
        har_path: Path = Path(args.har)
        output_dir: Path = self._resolve_output_dir(args, har_path)
        self._reset_output_dir(output_dir)
        config_path: Optional[Path] = Path(args.config) if args.config else None

        mode: EngineMode = EngineMode(args.mode)
        result: bool = self._run(mode, har_path, output_dir, config_path)
        self._print_result(result)

    def _run(self, mode: EngineMode, har_path: Path, output_dir: Path, config_path: Optional[Path]) -> bool:
        engine_cls: Type[Engine] = self._engine_factory.resolve_class(mode)
        if not engine_cls.USES_NETWORK:
            return self._run_without_proxy(mode, har_path, output_dir, config_path)
        return self._run_with_proxy(mode, har_path, output_dir, config_path)

    def _run_without_proxy(self, mode, har_path, output_dir, config_path) -> bool:
        engine: Engine = self._engine_factory.create(mode, har_path, output_dir, config_path)
        return engine.run()

    def _run_with_proxy(self, mode, har_path, output_dir, config_path) -> bool:
        project_config: ProjectConfig = ProjectConfigLoader.load(config_path)
        orchestrator: MitmProxyOrchestrator = MitmProxyOrchestrator(
            project_config.proxy_port,
            project_config.ca_cert_path
        )
        engine: Engine = self._engine_factory.create(
            mode,
            har_path,
            output_dir,
            config_path,
            proxy_port=orchestrator.port
        )
        return orchestrator.run(engine.run)

    @staticmethod
    def _print_result(result: bool) -> None:
        if result:
            print("\nReproduction SUCCESSFUL: Target state reached.")
        else:
            print("\nReproduction FAILED: Target state not reached.")

    def handle_parse(self, args: Namespace) -> None:
        har_path: Path = Path(args.har)
        output_dir: Path = self._resolve_output_dir(args, har_path)
        self._reset_output_dir(output_dir)
        count: int = self._har_parser.split_har(har_path, output_dir)
        print(f"Parsed HAR into {count} steps.")

    @staticmethod
    def _resolve_output_dir(args: Namespace, har_path: Path) -> Path:
        return Path(args.output) if args.output else har_path.parent / "output"

    @staticmethod
    def _reset_output_dir(output_dir: Path) -> None:
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
