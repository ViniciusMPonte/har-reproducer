import base64
import subprocess
import urllib.parse
from pathlib import Path
from subprocess import CompletedProcess
from typing import List, Optional, Tuple


def try_decode(value: str) -> str:
    """
    Attempts to decode a value through a sequence: Literal -> URL-decoded -> Base64-decoded.
    Returns the most 'decoded' version that looks like a string.
    """
    # 1. Start with the literal value
    current: str = value

    # 2. URL-decoded
    decoded_url: str = urllib.parse.unquote(current)
    if decoded_url != current:
        current = decoded_url

    # 3. Base64-decoded
    try:
        # Try to decode as base64. We only accept it if it results in valid UTF-8.
        # Base64 strings usually have specific chars; we check if it's possible.
        b64_bytes: bytes = base64.b64decode(current, validate=True)
        decoded_b64: str = b64_bytes.decode("utf-8")
        # Basic heuristic: if it contains non-printable chars, it might not be a token string.
        if decoded_b64.isprintable():
            current = decoded_b64
    except Exception as e:
        pass

    return current


def _build_pattern_variants(pattern: str) -> List[str]:
    """
    Returns a deduplicated list of encode/decode variants of pattern to search against.
    Order: literal → decoded (via try_decode) → URL-encoded → Base64-encoded.
    """
    variants: List[str] = []
    seen: set[str] = set()

    def add(v: str) -> None:
        if v and v not in seen:
            seen.add(v)
            variants.append(v)

    # 1. Literal (always first)
    add(pattern)

    # 2. URL-decoded + Base64-decoded (via try_decode)
    add(try_decode(pattern))

    # 3. URL-encoded (quote the literal; safe='' encodes everything including '/')
    add(urllib.parse.quote(pattern, safe=""))

    # 4. Base64-encoded
    add(base64.b64encode(pattern.encode("utf-8")).decode("ascii"))

    return variants


def _grep_single_pattern(responses_dir: Path, pattern: str) -> Optional[Tuple[int, str]]:
    """Runs grep for a single fixed pattern. Returns (step_index, filename) or None."""
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
        if e.returncode == 1:  # grep: no matches found — expected, not an error
            return None
        raise  # real error (permission denied, directory missing, etc.)


def grep_in_real_responses(responses_dir: Path, pattern: str) -> Optional[Tuple[int, str]]:
    """
    Searches for a pattern in all res_*.json files within the responses_dir.
    Returns the first match as (step_index, filename) or None if not found.

    Tries multiple encode/decode variants of the pattern (literal, URL-decoded,
    URL-encoded, Base64-decoded, Base64-encoded) to handle tokens that are stored
    in a different encoding than the one used in the request.
    The search is performed using the system grep for efficiency.
    """
    for variant in _build_pattern_variants(pattern):
        match: Optional[tuple[int, str]] = _grep_single_pattern(responses_dir, variant)
        if match:
            return match

    return None
