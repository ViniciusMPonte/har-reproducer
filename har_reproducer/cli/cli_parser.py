from __future__ import annotations

import argparse
from argparse import ArgumentParser, _SubParsersAction

from har_reproducer.cli.cli_handlers import CliHandlers
from har_reproducer.engines import EngineMode


class CliParser:

    def __init__(self, handlers: CliHandlers) -> None:
        self._handlers: CliHandlers = handlers

    def build(self) -> ArgumentParser:
        parser: ArgumentParser = argparse.ArgumentParser(prog="har-reproducer")
        subparsers: _SubParsersAction[ArgumentParser] = parser.add_subparsers(dest="command", required=True)

        self._build_parse_subparser(subparsers)
        self._build_run_subparser(subparsers)
        self._build_replay_subparser(subparsers)
        self._build_optimize_subparser(subparsers)

        return parser

    def _build_parse_subparser(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        parse_parser: ArgumentParser = subparsers.add_parser("parse")
        parse_parser.add_argument("--har", required=True, help="Path to HAR file")
        parse_parser.add_argument("--output", default=None, help="Output directory (default: <har-dir>/output)")
        parse_parser.add_argument(
            "--reset",
            dest="reset_output_dir",
            action="store_true",
            default=False,
            help="Apagar/recriar o diretório de saída antes de rodar (default: preservar)",
        )
        parse_parser.set_defaults(func=self._handlers.handle_parse)

    def _build_run_subparser(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
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
        run_parser.add_argument(
            "--reset",
            dest="reset_output_dir",
            action="store_true",
            default=False,
            help="Apagar/recriar o diretório de saída antes de rodar (default: preservar)",
        )
        run_parser.set_defaults(func=self._handlers.handle_run)

    def _build_replay_subparser(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        replay_parser: ArgumentParser = subparsers.add_parser("replay")
        replay_parser.add_argument("--output", required=True, help="Path to an existing workspace directory")
        replay_parser.add_argument(
            "--mode",
            choices=["all", "slice", "smart", "list"],
            required=True,
            help="Replay execution mode",
        )
        replay_parser.add_argument(
            "--from", dest="from_index", type=int, default=None, help="Starting step index (slice/smart only)"
        )
        replay_parser.add_argument(
            "--to", dest="to_index", type=int, default=None, help="Ending step index (slice/smart only)"
        )
        replay_parser.add_argument(
            "--steps-file",
            dest="steps_file",
            default=None,
            help="Path to a txt file with one step index per line (list mode only)",
        )
        replay_parser.add_argument("--config", help="Path to project config (JSON)")
        replay_parser.set_defaults(func=self._handlers.handle_replay)

    def _build_optimize_subparser(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        optimize_parser: ArgumentParser = subparsers.add_parser("optimize")
        optimize_parser.add_argument("--output", required=True, help="Path to an existing workspace directory")
        optimize_parser.add_argument("--to", dest="to_index", type=int, required=True, help="Target step index")
        optimize_parser.add_argument(
            "--from", dest="from_index", type=int, default=0, help="Floor step index (default: 0)"
        )
        optimize_parser.add_argument("--config", help="Path to project config (JSON)")
        optimize_parser.add_argument(
            "--success-criteria",
            dest="success_criteria",
            default=None,
            help="Inline JSON list of SuccessCriterion, overrides config.json for this call",
        )
        optimize_parser.add_argument(
            "--steps-out", dest="steps_out", default=None, help="Custom output path for the optimized steps .txt"
        )
        optimize_parser.add_argument(
            "--max-requests",
            dest="max_requests",
            type=int,
            default=500,
            help="Worst-case request budget before aborting",
        )
        optimize_parser.set_defaults(func=self._handlers.handle_optimize)
