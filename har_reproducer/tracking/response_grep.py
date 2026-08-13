import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from typing import List, Optional, Tuple

from har_reproducer.tracking.value_variants import ValueVariants


class ResponseGrep:

    @classmethod
    def find(cls, responses_dir: Path, pattern: str, before_step_index: int) -> Optional[Tuple[int, str]]:
        candidate_files: List[Path] = cls._eligible_response_files(responses_dir, before_step_index)
        if not candidate_files:
            return None

        for variant in ValueVariants.of(pattern):
            match: Optional[Tuple[int, str]] = cls._grep_single_pattern(candidate_files, variant)
            if match is not None:
                return match
        return None

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
