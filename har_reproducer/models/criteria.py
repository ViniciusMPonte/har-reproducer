from typing import Annotated, List, Literal, Union

from pydantic import BaseModel, Field


class StatusCodeCriterion(BaseModel):
    type: Literal["status_code"]
    expected: int


class BodyContainsCriterion(BaseModel):
    type: Literal["body_contains"]
    expected: str


class UrlMatchCriterion(BaseModel):
    type: Literal["url_match"]
    expected: str


class HtmlElementPresentCriterion(BaseModel):
    type: Literal["html_element_present"]
    expected: str


class CompositeCriterion(BaseModel):
    type: Literal["composite"]
    expected: List["SuccessCriterion"]


SuccessCriterion = Annotated[
    Union[
        StatusCodeCriterion,
        BodyContainsCriterion,
        UrlMatchCriterion,
        HtmlElementPresentCriterion,
        CompositeCriterion,
    ],
    Field(discriminator="type"),
]
