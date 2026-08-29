from typing import Optional

from pydantic import BaseModel


class ExtractorSampleResult(BaseModel):
    sample_label: str
    output: Optional[str] = None
    error: Optional[str] = None
    matches_expected: Optional[bool] = None
