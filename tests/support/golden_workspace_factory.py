from pathlib import Path

from tests.support.golden_normalizer import GoldenNormalizer
from tests.support.golden_workspace import GoldenWorkspace


class GoldenWorkspaceFactory:

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path: Path = tmp_path

    def create(self, workspace: Path) -> GoldenWorkspace:
        return GoldenWorkspace(workspace, GoldenNormalizer(workspace, self.tmp_path))
