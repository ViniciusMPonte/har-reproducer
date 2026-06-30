import argparse
from argparse import ArgumentParser, _SubParsersAction
from argparse import Namespace
from pathlib import Path
from typing import Optional

from .models import Patch
from .engine import Engine
from .parser import HARParser


def handle_parse(args: Namespace) -> None:
    """Handles the 'parse' subcommand to split a HAR file into steps."""
    har_path: Path = Path(args.har)
    output_dir: Path = Path(args.output)
    count: int = HARParser.split_har(har_path, output_dir)
    print(f"Parsed HAR into {count} steps.")


def handle_run(args: Namespace) -> None:
    """Handles the 'run' subcommand to execute the reproduction flow."""
    har_path: Path = Path(args.har)
    output_dir: Path = Path("reproduction_results")
    config_path: Optional[Path] = Path(args.config) if args.config else None
    engine: Engine = Engine(har_path, output_dir, config_path=config_path)
    result: Optional[bool] = engine.run(dry_run=args.dry_run)
    if not args.dry_run:
        if result:
            print("\nReproduction SUCCESSFUL: Target state reached.")
        else:
            print("\nReproduction FAILED: Target state not reached.")
    else:
        print("\nDry-run analysis completed.")


def handle_diagnose(args: Namespace) -> None:
    """Handles the 'diagnose' subcommand to suggest fixes for failed steps."""
    steps_dir: Path = Path(args.steps)
    res_dir: Path = Path(args.real_responses)

    # We use a dummy HAR path since we are only diagnosing from disk
    engine: Engine = Engine(Path("dummy.har"), steps_dir)
    engine.real_responses_dir = res_dir

    # For the CLI, we might want to diagnose a specific step or all failed ones.
    # For now, we diagnose step 1 as an example.
    print("Analyzing failures...")
    patch: Optional[Patch] = engine.diagnose(step_index=1)

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
    parse_parser.add_argument("--output", required=True, help="Output directory")
    parse_parser.set_defaults(func=handle_parse)

    # Run
    run_parser: ArgumentParser = subparsers.add_parser("run")
    run_parser.add_argument("--har", required=True, help="Path to HAR file")
    run_parser.add_argument("--dry-run", action="store_true", help="Simulate without network calls")
    run_parser.add_argument("--config", help="Path to success criteria config")
    run_parser.set_defaults(func=handle_run)

    # Diagnose
    diag_parser: ArgumentParser = subparsers.add_parser("diagnose")
    diag_parser.add_argument("--steps", required=True, help="Steps directory")
    diag_parser.add_argument("--real-responses", required=True, help="Responses directory")
    diag_parser.set_defaults(func=handle_diagnose)

    args: Namespace = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
