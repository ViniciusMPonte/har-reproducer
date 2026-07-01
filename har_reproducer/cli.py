import argparse
import shutil
from argparse import ArgumentParser, _SubParsersAction
from argparse import Namespace
from pathlib import Path
from typing import Optional

from .engine import Engine
from .models import Patch
from .parser import HARParser


def _reset_output_dir(output_dir: Path) -> None:
    """Deletes the output directory if it exists, then recreates it empty."""
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def handle_parse(args: Namespace) -> None:
    """Handles the 'parse' subcommand to split a HAR file into steps."""
    har_path: Path = Path(args.har)
    output_dir: Path = Path(args.output) if args.output else har_path.parent / "output"
    _reset_output_dir(output_dir)
    count: int = HARParser.split_har(har_path, output_dir)
    print(f"Parsed HAR into {count} steps.")


def handle_run(args: Namespace) -> None:
    """Handles the 'run' subcommand to execute the reproduction flow."""
    har_path: Path = Path(args.har)
    output_dir: Path = Path(args.output) if args.output else har_path.parent / "output"
    _reset_output_dir(output_dir)
    config_path: Optional[Path] = Path(args.config) if args.config else None
    engine: Engine = Engine(har_path, output_dir, config_path=config_path)
    if args.dry_run:
        engine.dry_run()
        print("\nDry-run analysis completed.")
    else:
        result: bool = engine.run()
        if result:
            print("\nReproduction SUCCESSFUL: Target state reached.")
        else:
            print("\nReproduction FAILED: Target state not reached.")


def handle_diagnose(args: Namespace) -> None:
    """Handles the 'diagnose' subcommand to suggest fixes for failed steps."""
    steps_dir: Path = Path(args.steps)
    res_dir: Path = Path(args.real_responses)

    engine: Engine = Engine.from_disk(steps_dir=steps_dir, real_responses_dir=res_dir)

    print("Analyzing failures...")
    patch: Optional[Patch] = engine.diagnose(step_index=args.step)

    if patch:
        print(f"Proposed Patch: {patch.action}")
        print(f"Target: {patch.target_token_id}")
        print(f"Rationale: {patch.rationale}")
        if hasattr(patch, "new_code"):
            print(f"Suggested Code:\n{patch.new_code}")

        # TODO (TASK-10): Applying the patch is not yet implemented.
        #   When the diagnose → apply → re-execute → verify loop is production-ready,
        #   call engine.apply_patch(patch) here and re-run the failed step to confirm
        #   the fix. Until then, the patch is only printed for manual inspection.
    else:
        print("No deterministic fix found.")


def main() -> None:
    """Entry point for the har-reproducer CLI."""
    parser: ArgumentParser = argparse.ArgumentParser(prog="har-reproducer")
    subparsers: _SubParsersAction[ArgumentParser] = parser.add_subparsers(dest="command", required=True)

    # Parse
    parse_parser: ArgumentParser = subparsers.add_parser("parse")
    parse_parser.add_argument("--har", required=True, help="Path to HAR file")
    parse_parser.add_argument("--output", default=None, help="Output directory (default: <har-dir>/output)")
    parse_parser.set_defaults(func=handle_parse)

    # Run
    run_parser: ArgumentParser = subparsers.add_parser("run")
    run_parser.add_argument("--har", required=True, help="Path to HAR file")
    run_parser.add_argument("--output", default=None, help="Output directory (default: <har-dir>/output)")
    run_parser.add_argument("--dry-run", action="store_true", help="Simulate without network calls")
    run_parser.add_argument("--config", help="Path to success criteria config")
    run_parser.set_defaults(func=handle_run)

    # Diagnose
    diag_parser: ArgumentParser = subparsers.add_parser("diagnose")
    diag_parser.add_argument("--steps", required=True, help="Steps directory")
    diag_parser.add_argument("--real-responses", required=True, help="Responses directory")
    diag_parser.add_argument("--step", type=int, required=True, help="Index of the step to diagnose")
    diag_parser.set_defaults(func=handle_diagnose)

    args: Namespace = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
