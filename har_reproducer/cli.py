import argparse
import sys
from pathlib import Path
from .parser import HARParser
from .engine import Engine

def handle_parse(args):
    har_path = Path(args.har)
    output_dir = Path(args.output)
    count = HARParser.split_har(har_path, output_dir)
    print(f"Parsed HAR into {count} steps.")

def handle_run(args):
    har_path = Path(args.har)
    output_dir = Path("reproduction_results")
    engine = Engine(har_path, output_dir)
    engine.run(dry_run=args.dry_run)
    print("Reproduction completed.")

def handle_diagnose(args):
    # diagnose is not fully implemented in the foundational phase
    print("Diagnose command is not yet implemented.")

def main():
    parser = argparse.ArgumentParser(prog="har-reproducer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Parse
    parse_parser = subparsers.add_parser("parse")
    parse_parser.add_argument("--har", required=True, help="Path to HAR file")
    parse_parser.add_argument("--output", required=True, help="Output directory")
    parse_parser.set_defaults(func=handle_parse)

    # Run
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--har", required=True, help="Path to HAR file")
    run_parser.add_argument("--dry-run", action="store_true", help="Simulate without network calls")
    run_parser.add_argument("--config", help="Path to success criteria config")
    run_parser.set_defaults(func=handle_run)

    # Diagnose
    diag_parser = subparsers.add_parser("diagnose")
    diag_parser.add_argument("--steps", required=True, help="Steps directory")
    diag_parser.add_argument("--real-responses", required=True, help="Responses directory")
    diag_parser.set_defaults(func=handle_diagnose)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
