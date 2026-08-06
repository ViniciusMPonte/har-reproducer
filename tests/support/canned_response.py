from typing import List, Tuple


class CannedResponse:

    def __init__(self, status: int, headers: List[Tuple[str, str]], body: str) -> None:
        self.status: int = status
        self.headers: List[Tuple[str, str]] = headers
        self.body: str = body
