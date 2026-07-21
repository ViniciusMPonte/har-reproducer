import re
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from har_reproducer.prompts import build_extractor_prompt
from har_reproducer.templates import render_extractor_script
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage

from har_reproducer.models import AgentType, Extractor

Strategy = Callable[[Optional[str]], Optional[str]]


class NoStrategyAvailable(Exception):
    """Raised when every generation strategy (deterministic + LLM) is exhausted."""


class BaseAgent:
    MAX_LLM_ATTEMPTS: int = 5

    def __init__(
            self,
            token_id: str,
            response_sample: Dict[str, Any],
            expected_value: str,
            path: Optional[str] = None,
            location: Optional[str] = None,
            llm: Optional[BaseChatModel] = None,
    ) -> None:
        self.token_id: str = token_id
        self.safe_token_id: str = self._sanitize_identifier(token_id)
        self.response_sample: Dict[str, Any] = response_sample
        self.expected_value: str = expected_value
        self.path: Optional[str] = path
        self.location: Optional[str] = location
        self.llm: Optional[BaseChatModel] = llm
        self._attempt_index: int = 0
        self._strategies: Optional[List[Strategy]] = None

    @staticmethod
    def _sanitize_identifier(raw: str) -> str:
        sanitized: str = re.sub(r"\W", "_", str(raw))
        if sanitized and sanitized[0].isdigit():
            sanitized = f"t_{sanitized}"
        return sanitized or "token"

    @property
    def key(self) -> Optional[str]:
        if self.path is None:
            return None
        if ":" in self.path:
            return self.path.split(":", 1)[1]
        return self.path

    def deterministic_strategies(self) -> List[Strategy]:
        return []

    def _build_strategies(self) -> List[Strategy]:
        deterministic: List[Strategy] = self.deterministic_strategies()
        llm_attempts: List[Strategy] = [self._llm_strategy] * self.MAX_LLM_ATTEMPTS
        return deterministic + llm_attempts

    def _get_strategies(self) -> List[Strategy]:
        if self._strategies is None:
            self._strategies = self._build_strategies()
        return self._strategies

    def generate_code(self, last_error: Optional[str] = None) -> str:
        strategies: List[Strategy] = self._get_strategies()
        while self._attempt_index < len(strategies):
            strategy: Strategy = strategies[self._attempt_index]
            self._attempt_index += 1
            code: Optional[str] = strategy(last_error)
            if code is not None:
                return code
        raise NoStrategyAvailable(
            f"No extractor strategy could be generated for '{self.token_id}'"
        )

    def _llm_strategy(self, last_error: Optional[str] = None) -> Optional[str]:
        if self.llm is None:
            return None
        prompt: str = self._build_llm_prompt(last_error)
        try:
            response: AIMessage = self.llm.invoke(prompt)
        except Exception as exc:
            print(f"[AVISO] Falha na chamada ao LLM para {self.token_id}: {exc}")
            return None
        text: str = self._response_to_text(response)
        return self._extract_code_block(text)

    @staticmethod
    def _response_to_text(response: AIMessage) -> str:
        content: Union[str, List[Union[str, Dict[str, Any]]]] = response.content
        if isinstance(content, str):
            return content
        parts: List[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and (part.get("type") == "text" or "text" in part):
                parts.append(str(part.get("text", "")))
        return "".join(parts)

    def _build_llm_prompt(self, last_error: Optional[str]) -> str:
        return build_extractor_prompt(
            safe_token_id=self.safe_token_id,
            location=self.location,
            path=self.path,
            expected_value=self.expected_value,
            response_sample=self.response_sample,
            last_error=last_error,
        )

    @staticmethod
    def _extract_code_block(text: str) -> str:
        fenced: Optional[re.Match[str]] = re.search(
            r"```(?:python)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE
        )
        if fenced:
            return fenced.group(1).strip()
        return text.strip()

    def run_tdd_loop(self, max_attempts: Optional[int] = None, origin_step: Optional[int] = None) -> Optional[
        Extractor]:

        strategies: List[Strategy] = self._get_strategies()
        total: int = len(strategies) if max_attempts is None else max_attempts

        last_error: Optional[str] = None
        for attempt in range(total):
            try:
                code: str = self.generate_code(last_error=last_error)
            except NoStrategyAvailable:
                break

            success: bool
            error: Optional[str]
            success, error = self._verify_code(code)

            if success:
                return Extractor(
                    token_id=self.token_id,
                    code=code,
                    verified=True,
                    agent_type=AgentType(self.__class__.__name__),
                    origin_step=origin_step,
                )

            last_error = error
            print(f"Attempt {attempt + 1} failed for {self.token_id}. Retrying...")

        return None

    def _verify_code(self, code: str) -> Tuple[bool, Optional[str]]:

        script_path: Path = self._write_temp_script(code)
        try:
            return self._execute_script(script_path)
        finally:
            self._cleanup_script(script_path)

    def _write_temp_script(self, code: str) -> Path:
        temp_file: Path = Path(f"temp_extractor_{self.safe_token_id}.py")
        wrapped_code: str = render_extractor_script(
            safe_token_id=self.safe_token_id,
            code=code,
            response_sample=self.response_sample,
        )
        temp_file.write_text(wrapped_code)
        return temp_file

    def _execute_script(self, script_path: Path) -> Tuple[bool, Optional[str]]:
        try:
            result: CompletedProcess[str] = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            print(f"[AVISO] Timeout ao verificar extrator para {self.token_id}")
            return False, "Timeout during verification"

        if result.returncode == 0 and result.stdout.strip() == self.expected_value:
            return True, None

        error: str = result.stderr.strip() or (
            f"Output mismatch: got {result.stdout.strip()!r}, expected {self.expected_value!r}"
        )
        return False, error

    def _cleanup_script(self, script_path: Path) -> None:
        if script_path.exists():
            script_path.unlink()
