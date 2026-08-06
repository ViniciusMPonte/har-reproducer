import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from typing import ClassVar, List, Optional

from har_reproducer.main import main
from tests.support.cli_invocation_result import CliInvocationResult


class CliInvoker:

    PROGRAM_NAME: ClassVar[str] = "har-reproducer"

    def invoke(self, argv: List[str]) -> CliInvocationResult:
        original_argv: List[str] = sys.argv
        sys.argv = [self.PROGRAM_NAME, *argv]
        try:
            stdout_buffer: StringIO = StringIO()
            stderr_buffer: StringIO = StringIO()
            exception: Optional[BaseException] = self._invoke_main(stdout_buffer, stderr_buffer)
        finally:
            sys.argv = original_argv
        return CliInvocationResult(stdout_buffer.getvalue(), stderr_buffer.getvalue(), exception)

    def _invoke_main(self, stdout_buffer: StringIO, stderr_buffer: StringIO) -> Optional[BaseException]:
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            return self._call_main()

    def _call_main(self) -> Optional[BaseException]:
        try:
            main()
        except SystemExit as system_exit:
            return system_exit
        except Exception as exception:
            return exception
        return None
