from __future__ import annotations

import argparse
from argparse import ArgumentParser, _SubParsersAction

from har_reproducer.engines import EngineMode
from har_reproducer.cli.cli_handlers import CliHandlers


class CliParser:

    def __init__(self, handlers: CliHandlers) -> None:
        self._handlers: CliHandlers = handlers

    def build(self) -> ArgumentParser:
        parser: ArgumentParser = argparse.ArgumentParser(prog="har-reproducer")
        subparsers: _SubParsersAction[ArgumentParser] = parser.add_subparsers(dest="command", required=True)

        self._build_parse_subparser(subparsers)
        self._build_run_subparser(subparsers)

        return parser

    def _build_parse_subparser(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        parse_parser: ArgumentParser = subparsers.add_parser("parse")
        parse_parser.add_argument("--har", required=True, help="Path to HAR file")
        parse_parser.add_argument("--output", default=None, help="Output directory (default: <har-dir>/output)")
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
        run_parser.set_defaults(func=self._handlers.handle_run)
