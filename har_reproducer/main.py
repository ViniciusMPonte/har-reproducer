import sys
from argparse import ArgumentParser, Namespace

from dotenv import load_dotenv

from har_reproducer.cli import CliHandlers, CliParser
from har_reproducer.engines import EngineFactory
from har_reproducer.fs_io import HARParser


def main() -> None:
    load_dotenv()

    handlers: CliHandlers = CliHandlers(engine_factory=EngineFactory, har_parser=HARParser)
    cli_parser: CliParser = CliParser(handlers)
    parser: ArgumentParser = cli_parser.build()

    args: Namespace = parser.parse_args()
    success: bool = args.func(args)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
