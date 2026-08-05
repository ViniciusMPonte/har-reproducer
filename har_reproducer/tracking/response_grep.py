import base64
import subprocess
import urllib.parse
from pathlib import Path
from subprocess import CompletedProcess
from typing import List, Optional, Set, Tuple


class ResponseGrep:

    @classmethod
    def find(cls, responses_dir: Path, pattern: str, before_step_index: int) -> Optional[Tuple[int, str]]:
        candidate_files: List[Path] = cls._eligible_response_files(responses_dir, before_step_index)
        if not candidate_files:
            return None

        for variant in cls.value_variants(pattern):
            match: Optional[Tuple[int, str]] = cls._grep_single_pattern(candidate_files, variant)
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
    def value_variants(cls, value: str) -> List[str]:
        candidates: List[str] = [
            value,
            cls.try_decode(value),
            urllib.parse.quote(value, safe=""),
            base64.b64encode(value.encode("utf-8")).decode("ascii"),
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
    def _grep_single_pattern(cls, candidate_files: List[Path], pattern: str) -> Optional[Tuple[int, str]]:
        try:
            cmd: List[str] = ["grep", "-lF", pattern, *(str(path) for path in candidate_files)]
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

    @classmethod
    def _eligible_response_files(cls, responses_dir: Path, before_step_index: int) -> List[Path]:
        eligible: List[Path] = []
        for path in sorted(responses_dir.glob("res_*.json")):
            step_index: Optional[int] = cls._extract_step_index(path.name)
            if step_index is not None and step_index < before_step_index:
                eligible.append(path)
        return eligible

    @staticmethod
    def _extract_step_index(filename: str) -> Optional[int]:
        try:
            index_str: str = filename.split("_")[1].split(".")[0]
            return int(index_str)
        except (IndexError, ValueError) as e:
            print(f"[AVISO] Falha ao extrair step index do arquivo '{filename}': {e}")
            return None
