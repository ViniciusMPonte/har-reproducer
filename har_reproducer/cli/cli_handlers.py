import shutil
from argparse import Namespace
from pathlib import Path
from typing import Optional, Type

from har_reproducer.engines import Engine, EngineFactory, EngineMode
from har_reproducer.fs_io import HARParser


class CliHandlers:

    def __init__(self, engine_factory: Type[EngineFactory], har_parser: Type[HARParser]) -> None:
        self._engine_factory: Type[EngineFactory] = engine_factory
        self._har_parser: Type[HARParser] = har_parser

    def handle_parse(self, args: Namespace) -> None:
        har_path: Path = Path(args.har)
        output_dir: Path = self._resolve_output_dir(args, har_path)
        self._reset_output_dir(output_dir)
        count: int = self._har_parser.split_har(har_path, output_dir)
        print(f"Parsed HAR into {count} steps.")

    def handle_run(self, args: Namespace) -> None:
        har_path: Path = Path(args.har)
        output_dir: Path = self._resolve_output_dir(args, har_path)
        self._reset_output_dir(output_dir)
        config_path: Optional[Path] = Path(args.config) if args.config else None

        mode: EngineMode = EngineMode(args.mode)
        engine: Engine = self._engine_factory.create(mode, har_path, output_dir, config_path)
        result: bool = engine.run()
        if result:
            print("\nReproduction SUCCESSFUL: Target state reached.")
        else:
            print("\nReproduction FAILED: Target state not reached.")

    @staticmethod
    def _resolve_output_dir(args: Namespace, har_path: Path) -> Path:
        return Path(args.output) if args.output else har_path.parent / "output"

    @staticmethod
    def _reset_output_dir(output_dir: Path) -> None:
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
