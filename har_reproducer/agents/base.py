import re
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage

from har_reproducer.models import AgentType, Extractor

# A strategy takes the last error (if any) and returns extractor source code,
# or ``None`` when it is not applicable to the current sample.
Strategy = Callable[[Optional[str]], Optional[str]]


class NoStrategyAvailable(Exception):
    """Raised when every generation strategy (deterministic + LLM) is exhausted."""


class BaseAgent:
    """
    Base class for all Token Extraction Agents.

    Implements the TDD loop for verified extractor generation. Each agent tries a
    ranked list of deterministic strategies first (strongest to weakest), and only
    falls back to the injected LLM as a last resort. Every candidate — deterministic
    or LLM-generated — must pass the exact same verifier before being accepted.
    """

    # How many times the LLM fallback may be attempted once the deterministic
    # strategies are exhausted.
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
        # ``token_id`` may be an MD5 hash or an arbitrary string; sanitize it so it
        # is always a valid Python identifier for the generated function name.
        self.safe_token_id: str = self._sanitize_identifier(token_id)
        self.response_sample: Dict[str, Any] = response_sample
        self.expected_value: str = expected_value
        # The real selector/key (cookie name, header name, JSON key, ...). Provided
        # via ``path`` (e.g. ``"cookie:session_id"``); never derived from token_id.
        self.path: Optional[str] = path
        self.location: Optional[str] = location
        self.llm: Optional[BaseChatModel] = llm

        # Instance state: a fresh agent is created per token, so there is no leak.
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
        """The real key/selector name, stripped of any ``location:`` prefix."""
        if self.path is None:
            return None
        if ":" in self.path:
            return self.path.split(":", 1)[1]
        return self.path

    # ------------------------------------------------------------------ #
    # Strategy plumbing
    # ------------------------------------------------------------------ #
    def deterministic_strategies(self) -> List[Strategy]:
        """Ranked deterministic strategies (strongest first). Overridden by agents."""
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
        """
        Return the next applicable extractor source code.

        Keeps an instance-level attempt counter. On each call it advances through the
        ranked strategy list (deterministic -> ... -> LLM), skipping strategies that
        are not applicable to the current sample (they return ``None``).
        """
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

    # ------------------------------------------------------------------ #
    # LLM fallback
    # ------------------------------------------------------------------ #
    def _llm_strategy(self, last_error: Optional[str] = None) -> Optional[str]:
        if self.llm is None:
            return None
        prompt: str = self._build_llm_prompt(last_error)
        try:
            response: AIMessage = self.llm.invoke(prompt)
        except Exception as exc:  # pragma: no cover - network/provider errors
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
            elif isinstance(part, dict) and (
                part.get("type") == "text" or "text" in part
            ):
                parts.append(str(part.get("text", "")))
        return "".join(parts)

    def _build_llm_prompt(self, last_error: Optional[str]) -> str:
        error_section: str = (
            f"\nThe previous attempt failed with this error:\n{last_error}\n"
            if last_error
            else ""
        )
        return f"""You are a Python code generator for HTTP token extraction.

Write a single Python function named `extract_{self.safe_token_id}` that receives
one argument `response` (a dict with keys like 'headers', 'cookies', 'body') and
returns the extracted token value as a string. Raise an Exception if the token is
not found. Return ONLY the function code inside a ```python code block, with any
required imports inside or above the function.

Token location: {self.location}
Original key/path: {self.path}
Expected returned value: {self.expected_value!r}
Response sample: {self.response_sample!r}
{error_section}"""

    @staticmethod
    def _extract_code_block(text: str) -> str:
        fenced: Optional[re.Match[str]] = re.search(
            r"```(?:python)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE
        )
        if fenced:
            return fenced.group(1).strip()
        return text.strip()

    # ------------------------------------------------------------------ #
    # TDD loop
    # ------------------------------------------------------------------ #
    def run_tdd_loop(
        self, max_attempts: Optional[int] = None, origin_step: Optional[int] = None
    ) -> Optional[Extractor]:
        """
        Runs the TDD loop: generate -> test -> next strategy -> repeat.

        When ``max_attempts`` is ``None`` every ranked strategy (deterministic +
        LLM) is tried once. A concrete integer caps the number of tries.
        """
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
        """
        Verifies the generated code by executing it against the response sample.
        Returns a tuple of (success, error_message).
        """
        script_path: Path = self._write_temp_script(code)
        try:
            return self._execute_script(script_path)
        finally:
            self._cleanup_script(script_path)

    def _write_temp_script(self, code: str) -> Path:
        """Wraps the extractor code in a runnable script and writes it to a temp file."""
        temp_file: Path = Path(f"temp_extractor_{self.safe_token_id}.py")
        wrapped_code: str = f"""
import sys
import json
from typing import Dict
class ExtractorError(Exception): pass

{code}

if __name__ == "__main__":
    response = {self.response_sample!r}
    try:
        result = extract_{self.safe_token_id}(response)
        print(result)
    except Exception as e:
        print(f"ERROR: {{e}}", file=sys.stderr)
        sys.exit(1)
"""
        temp_file.write_text(wrapped_code)
        return temp_file

    def _execute_script(self, script_path: Path) -> Tuple[bool, Optional[str]]:
        """Runs the temp script and checks whether its output matches the expected value."""
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
        """Removes the temporary script file if it exists."""
        if script_path.exists():
            script_path.unlink()
