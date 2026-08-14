import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage

from har_reproducer.contracts import Strategy
from har_reproducer.fs_io import Workspace
from har_reproducer.models import AgentType, Extractor, ScriptExecutionResult
from har_reproducer.prompts import ExtractorPrompt
from har_reproducer.reproduction import ScriptExecutor, Sleeper
from har_reproducer.templates import ExtractorTemplate, IdentifierSanitizer


class BaseAgent:
    MAX_LLM_ATTEMPTS: int = 5
    RETRY_DELAY_SECONDS: int = 5

    def __init__(
            self,
            token_id: str,
            response_sample: Dict[str, Any],
            expected_value: str,
            workspace: Workspace,
            script_executor: ScriptExecutor,
            sleeper: Sleeper,
            path: Optional[str] = None,
            location: Optional[str] = None,
            origin_key: Optional[str] = None,
            llm: Optional[BaseChatModel] = None,
    ) -> None:
        self.token_id: str = token_id
        self.safe_token_id: str = IdentifierSanitizer.sanitize(token_id)
        self.response_sample: Dict[str, Any] = response_sample
        self.expected_value: str = expected_value
        self.workspace: Workspace = workspace
        self.script_executor: ScriptExecutor = script_executor
        self.sleeper: Sleeper = sleeper
        self.path: Optional[str] = path
        self.location: Optional[str] = location
        self.origin_key: Optional[str] = origin_key
        self.llm: Optional[BaseChatModel] = llm
        self._attempt_index: int = 0
        self._strategies: Optional[List[Strategy]] = None

    @property
    def key(self) -> Optional[str]:
        if self.origin_key is not None:
            return self.origin_key
        if self.path is None:
            return None
        if ":" in self.path:
            return self.path.split(":", 1)[1]
        return self.path

    def value_char_class(self) -> str:
        if re.fullmatch(r"[\w\-.]+", self.expected_value):
            return r"[\w\-.]+"
        return r".+?"

    def lazy_value_char_class(self) -> str:
        char_class: str = self.value_char_class()
        if char_class.endswith("+"):
            return f"{char_class}?"
        return char_class

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

    def generate_code(self, last_error: Optional[str] = None) -> Optional[str]:
        strategies: List[Strategy] = self._get_strategies()
        while self._attempt_index < len(strategies):
            strategy: Strategy = strategies[self._attempt_index]
            self._attempt_index += 1
            code: Optional[str] = strategy(last_error)
            if code is not None:
                return code
        return None

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
        return ExtractorPrompt.build(
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

    def run_tdd_loop(
            self,
            max_attempts: Optional[int] = None,
            origin_step: Optional[int] = None,
            initial_error: Optional[str] = None,
    ) -> Optional[Extractor]:

        strategies: List[Strategy] = self._get_strategies()
        total: int = len(strategies) if max_attempts is None else max_attempts

        last_error: Optional[str] = initial_error
        for attempt in range(total):
            code: Optional[str] = self.generate_code(last_error=last_error)
            if code is None:
                break

            success: bool
            error: Optional[str]
            success, error = self._verify_code(code)

            if success:
                temp_path: Path = self.workspace.temp_extractor_file(self.safe_token_id)
                return Extractor(
                    token_id=self.token_id,
                    code=code,
                    verified=True,
                    agent_type=AgentType(self.__class__.__name__),
                    origin_step=origin_step,
                    temp_file_path=str(temp_path),
                )

            last_error = error
            print(f"Attempt {attempt + 1} failed for {self.token_id}. Retrying...")
            if attempt < total - 1:
                self.sleeper.sleep(self.RETRY_DELAY_SECONDS)

        self._cleanup_script(self.workspace.temp_extractor_file(self.safe_token_id))
        return None

    def _verify_code(self, code: str) -> Tuple[bool, Optional[str]]:

        script_path: Path = self._write_temp_script(code)
        return self._execute_script(script_path)

    def _write_temp_script(self, code: str) -> Path:
        temp_file: Path = self.workspace.temp_extractor_file(self.safe_token_id)
        wrapped_code: str = ExtractorTemplate.render_temp_script(
            safe_token_id=self.safe_token_id,
            code=code,
            response_sample=self.response_sample,
        )
        temp_file.write_text(wrapped_code)
        return temp_file

    def _execute_script(self, script_path: Path) -> Tuple[bool, Optional[str]]:
        result: ScriptExecutionResult = self.script_executor.run(script_path, 5)
        if result.timed_out:
            print(f"[AVISO] Timeout ao verificar extrator para {self.token_id}")
            return False, "Timeout during verification"

        if result.return_code != 0:
            return False, result.stderr.strip() or "Extractor script failed with no output."

        actual_value: str = result.stdout.strip()
        if actual_value == self.expected_value:
            return True, None

        return False, f"Output mismatch: got {actual_value!r}, expected {self.expected_value!r}"

    def _cleanup_script(self, script_path: Path) -> None:
        if script_path.exists():
            script_path.unlink()
