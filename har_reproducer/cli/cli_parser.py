from __future__ import annotations

import argparse
from argparse import ArgumentParser, _SubParsersAction

from har_reproducer.cli.cli_handlers import CliHandlers
from har_reproducer.cli.extractor_cli_handlers import ExtractorCliHandlers
from har_reproducer.engines import EngineMode


class CliParser:

    def __init__(self, handlers: CliHandlers, extractor_handlers: ExtractorCliHandlers) -> None:
        self._handlers: CliHandlers = handlers
        self._extractor_handlers: ExtractorCliHandlers = extractor_handlers

    def build(self) -> ArgumentParser:
        parser: ArgumentParser = argparse.ArgumentParser(prog="har-reproducer")
        subparsers: _SubParsersAction[ArgumentParser] = parser.add_subparsers(dest="command", required=True)

        self._build_parse_subparser(subparsers)
        self._build_run_subparser(subparsers)
        self._build_replay_subparser(subparsers)
        self._build_optimize_subparser(subparsers)
        self._build_extractor_subparser(subparsers)

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

    def _build_extractor_subparser(self, subparsers: _SubParsersAction[ArgumentParser]) -> None:
        extractor_parser: ArgumentParser = subparsers.add_parser("extractor")
        action_subparsers: _SubParsersAction[ArgumentParser] = extractor_parser.add_subparsers(
            dest="action", required=True
        )

        self._build_extractor_list_subparser(action_subparsers)
        self._build_extractor_get_subparser(action_subparsers)
        self._build_extractor_create_subparser(action_subparsers)
        self._build_extractor_update_subparser(action_subparsers)

    def _build_extractor_list_subparser(self, action_subparsers: _SubParsersAction[ArgumentParser]) -> None:
        list_parser: ArgumentParser = action_subparsers.add_parser("list")
        list_parser.add_argument("--output", required=True, help="Path to an existing workspace directory")
        list_parser.set_defaults(func=self._extractor_handlers.handle_list)

    def _build_extractor_get_subparser(self, action_subparsers: _SubParsersAction[ArgumentParser]) -> None:
        get_parser: ArgumentParser = action_subparsers.add_parser("get")
        get_parser.add_argument("--output", required=True, help="Path to an existing workspace directory")
        get_parser.add_argument("--token-id", dest="token_id", required=True, help="Extractor token_id")
        get_parser.set_defaults(func=self._extractor_handlers.handle_get)

    def _build_extractor_create_subparser(self, action_subparsers: _SubParsersAction[ArgumentParser]) -> None:
        create_parser: ArgumentParser = action_subparsers.add_parser("create")
        create_parser.add_argument("--output", required=True, help="Path to an existing workspace directory")
        create_parser.add_argument("--token-id", dest="token_id", required=True, help="Extractor token_id")
        create_parser.add_argument(
            "--code-file", dest="code_file", required=True, help="Path to a file with the extractor code"
        )
        create_parser.add_argument(
            "--agent-type",
            dest="agent_type",
            required=True,
            help="AgentType value describing how the extractor was produced",
        )
        create_parser.add_argument(
            "--origin-step", dest="origin_step", type=int, required=True, help="Step index the response comes from"
        )
        create_parser.add_argument(
            "--captured-value", dest="captured_value", default=None, help="Value expected from the origin_step sample"
        )
        create_parser.add_argument(
            "--verified", dest="verified", action="store_true", default=None, help="Mark the extractor as verified"
        )
        create_parser.set_defaults(func=self._extractor_handlers.handle_create)

    def _build_extractor_update_subparser(self, action_subparsers: _SubParsersAction[ArgumentParser]) -> None:
        update_parser: ArgumentParser = action_subparsers.add_parser("update")
        update_parser.add_argument("--output", required=True, help="Path to an existing workspace directory")
        update_parser.add_argument("--token-id", dest="token_id", required=True, help="Extractor token_id")
        update_parser.add_argument(
            "--code-file", dest="code_file", default=None, help="Path to a file with the extractor code"
        )
        update_parser.add_argument(
            "--agent-type",
            dest="agent_type",
            default=None,
            help="AgentType value describing how the extractor was produced",
        )
        update_parser.add_argument(
            "--origin-step", dest="origin_step", type=int, default=None, help="Step index the response comes from"
        )
        update_parser.add_argument(
            "--captured-value", dest="captured_value", default=None, help="Value expected from the origin_step sample"
        )
        update_parser.add_argument(
            "--verified", dest="verified", action="store_true", default=None, help="Mark the extractor as verified"
        )
        update_parser.set_defaults(func=self._extractor_handlers.handle_update)
