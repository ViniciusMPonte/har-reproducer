from typing import Optional


class CliInvocationResult:

    def __init__(self, stdout: str, stderr: str, exception: Optional[BaseException]) -> None:
        self.stdout: str = stdout
        self.stderr: str = stderr
        self.exception: Optional[BaseException] = exception
