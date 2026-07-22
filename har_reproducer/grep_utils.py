import base64
import subprocess
import urllib.parse
from pathlib import Path
from subprocess import CompletedProcess
from typing import List, Optional, Tuple


def try_decode(value: str) -> str:

    current: str = value

    decoded_url: str = urllib.parse.unquote(current)
    if decoded_url != current:
        current = decoded_url

    try:
        b64_bytes: bytes = base64.b64decode(current, validate=True)
        decoded_b64: str = b64_bytes.decode("utf-8")

        if decoded_b64.isprintable():
            current = decoded_b64
    except Exception as e:
        pass

    return current


def _build_pattern_variants(pattern: str) -> List[str]:

    variants: List[str] = []
    seen: set[str] = set()

    def add(v: str) -> None:
        if v and v not in seen:
            seen.add(v)
            variants.append(v)

    add(pattern)
    add(try_decode(pattern))
    add(urllib.parse.quote(pattern, safe=""))
    add(base64.b64encode(pattern.encode("utf-8")).decode("ascii"))

    return variants


def _grep_single_pattern(responses_dir: Path, pattern: str) -> Optional[Tuple[int, str]]:

    try:
        cmd: list[str] = ["grep", "-rl", "--include=res_*.json", pattern, str(responses_dir)]
        result: CompletedProcess[str] = subprocess.run(cmd, capture_output=True, text=True, check=True)

        if not result.stdout:
            return None

        first_match_file: str = sorted(result.stdout.splitlines())[0]
        file_path: Path = Path(first_match_file)
        filename: str = file_path.name
        try:
            index_str: str = filename.split("_")[1].split(".")[0]
            step_index: int = int(index_str)
        except (IndexError, ValueError) as e:
            print(f"[AVISO] Falha ao extrair step index do arquivo '{filename}': {e}")
            return None

        return step_index, filename

    except subprocess.CalledProcessError as e:
        if e.returncode == 1:
            return None
        raise


def grep_in_real_responses(responses_dir: Path, pattern: str) -> Optional[Tuple[int, str]]:

    for variant in _build_pattern_variants(pattern):
        match: Optional[tuple[int, str]] = _grep_single_pattern(responses_dir, variant)
        if match:
            return match

    return None
