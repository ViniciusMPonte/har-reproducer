import contextlib
import io
import json
import sys
from argparse import ArgumentParser, Namespace
from typing import List

from dotenv import load_dotenv

from har_reproducer.cli import CliHandlers, CliParser, ExtractorCliHandlers
from har_reproducer.engines import EngineFactory
from har_reproducer.fs_io import HARParser


def main() -> None:
    load_dotenv()

    handlers: CliHandlers = CliHandlers(engine_factory=EngineFactory, har_parser=HARParser)
    extractor_handlers: ExtractorCliHandlers = ExtractorCliHandlers()
    cli_parser: CliParser = CliParser(handlers, extractor_handlers)
    parser: ArgumentParser = cli_parser.build()

    if len(sys.argv) > 1 and sys.argv[1] == "extractor":
        success: bool = _dispatch_extractor(parser, sys.argv[1:])
    else:
        args: Namespace = parser.parse_args()
        success = args.func(args)
    if not success:
        sys.exit(1)


def _dispatch_extractor(parser: ArgumentParser, argv: List[str]) -> bool:
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            args: Namespace = parser.parse_args(argv)
        except SystemExit:
            print(json.dumps({"ok": False, "error": "invalid arguments for extractor command"}))
            return False
    return args.func(args)


if __name__ == "__main__":
    main()
