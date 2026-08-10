from typing import List

from har_reproducer.reproduction.sleeper import Sleeper


class FakeSleeper(Sleeper):

    def __init__(self) -> None:
        self.calls: List[float] = []

    def sleep(self, seconds: float) -> None:
        self.calls.append(seconds)
