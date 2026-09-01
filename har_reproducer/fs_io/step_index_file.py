from pathlib import Path
from typing import List


def parse_step_index_file(path: Path) -> List[int]:
    lines: List[str] = path.read_text(encoding="utf-8").splitlines()
    return [int(line.strip()) for line in lines if line.strip()]
