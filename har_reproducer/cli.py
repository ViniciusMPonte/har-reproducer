import argparse
import shutil
from argparse import ArgumentParser, _SubParsersAction
from argparse import Namespace
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .engines import EngineFactory, EngineMode, Engine
from .fs_io import HARParser


def _reset_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def handle_parse(args: Namespace) -> None:
    har_path: Path = Path(args.har)
    output_dir: Path = Path(args.output) if args.output else har_path.parent / "output"
    _reset_output_dir(output_dir)
    count: int = HARParser.split_har(har_path, output_dir)
    print(f"Parsed HAR into {count} steps.")


def handle_run(args: Namespace) -> None:
    har_path: Path = Path(args.har)
    output_dir: Path = Path(args.output) if args.output else har_path.parent / "output"
    _reset_output_dir(output_dir)
    config_path: Optional[Path] = Path(args.config) if args.config else None

    mode: EngineMode = EngineMode(args.mode)
    engine: Engine = EngineFactory.create(mode, har_path, output_dir, config_path)
    result: bool = engine.run()
    if result:
        print("\nReproduction SUCCESSFUL: Target state reached.")
    else:
        print("\nReproduction FAILED: Target state not reached.")


def main() -> None:
    load_dotenv()

    parser: ArgumentParser = argparse.ArgumentParser(prog="har-reproducer")
    subparsers: _SubParsersAction[ArgumentParser] = parser.add_subparsers(dest="command", required=True)

    parse_parser: ArgumentParser = subparsers.add_parser("parse")
    parse_parser.add_argument("--har", required=True, help="Path to HAR file")
    parse_parser.add_argument("--output", default=None, help="Output directory (default: <har-dir>/output)")
    parse_parser.set_defaults(func=handle_parse)

    run_parser: ArgumentParser = subparsers.add_parser("run")
    run_parser.add_argument("--har", required=True, help="Path to HAR file")
    run_parser.add_argument("--output", default=None, help="Output directory (default: <har-dir>/output)")
    run_parser.add_argument(
        "--mode",
        choices=[mode.value for mode in EngineMode],
        default=EngineMode.MAIN.value,
        help="Engine execution mode",
    )
    run_parser.add_argument("--config", help="Path to project config (JSON)")
    run_parser.set_defaults(func=handle_run)

    args: Namespace = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
