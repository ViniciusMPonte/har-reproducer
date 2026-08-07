from pydantic import BaseModel


class ScriptExecutionResult(BaseModel):
    timed_out: bool
    return_code: int
    stdout: str
    stderr: str
