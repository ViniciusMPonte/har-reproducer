import base64
from typing import List, Optional

from har_reproducer.tracking.response_grep import ResponseGrep
from har_reproducer.tracking.value_variants import ValueVariants


def test_try_decode_leaves_plain_value_unchanged() -> None:
    assert ValueVariants.try_decode("valor-simples") == "valor-simples"


def test_try_decode_url_decodes_percent_encoded_value() -> None:
    assert ValueVariants.try_decode("valor%20com%20espaco") == "valor com espaco"


def test_try_decode_base64_decodes_valid_payload() -> None:
    encoded: str = base64.b64encode(b"segredo").decode("ascii")

    assert ValueVariants.try_decode(encoded) == "segredo"


def test_value_variants_has_no_duplicates_or_empty_strings() -> None:
    variants: List[str] = ValueVariants.of("abc")

    assert len(variants) == len(set(variants))
    assert "" not in variants
    assert variants[0] == "abc"


def test_extract_step_index_parses_valid_filename() -> None:
    assert ResponseGrep._extract_step_index("res_0007.json") == 7


def test_extract_step_index_returns_none_for_invalid_filename() -> None:
    result: Optional[int] = ResponseGrep._extract_step_index("nomeinvalido.json")

    assert result is None
