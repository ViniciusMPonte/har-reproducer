import base64
import subprocess
import urllib.parse
from pathlib import Path
from subprocess import CompletedProcess
from typing import List, Optional, Set, Tuple


class ResponseGrep:

    @classmethod
    def find(cls, responses_dir: Path, pattern: str) -> Optional[Tuple[int, str]]:
        for variant in cls._build_pattern_variants(pattern):
            match: Optional[Tuple[int, str]] = cls._grep_single_pattern(responses_dir, variant)
            if match is not None:
                return match
        return None

    @staticmethod
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
        except Exception:
            pass

        return current

    @classmethod
    def _build_pattern_variants(cls, pattern: str) -> List[str]:
        candidates: List[str] = [
            pattern,
            cls.try_decode(pattern),
            urllib.parse.quote(pattern, safe=""),
            base64.b64encode(pattern.encode("utf-8")).decode("ascii"),
        ]
        return cls._deduplicate(candidates)

    @staticmethod
    def _deduplicate(values: List[str]) -> List[str]:
        seen: Set[str] = set()
        unique: List[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                unique.append(value)
        return unique

    @classmethod
    def _grep_single_pattern(cls, responses_dir: Path, pattern: str) -> Optional[Tuple[int, str]]:
        try:
            cmd: List[str] = ["grep", "-rl", "--include=res_*.json", pattern, str(responses_dir)]
            result: CompletedProcess[str] = subprocess.run(cmd, capture_output=True, text=True, check=True)

            if not result.stdout:
                return None

            first_match_file: str = sorted(result.stdout.splitlines())[0]
            filename: str = Path(first_match_file).name

            step_index: Optional[int] = cls._extract_step_index(filename)
            if step_index is None:
                return None

            return step_index, filename

        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                return None
            raise

    @staticmethod
    def _extract_step_index(filename: str) -> Optional[int]:
        try:
            index_str: str = filename.split("_")[1].split(".")[0]
            return int(index_str)
        except (IndexError, ValueError) as e:
            print(f"[AVISO] Falha ao extrair step index do arquivo '{filename}': {e}")
            return None
