from har_reproducer.replay.curl_token_comment import DependencyPhrase, OriginStatusPhrase, ReplayStatusPhrase


def test_dependency_phrase_comes_from_step_value() -> None:
    assert DependencyPhrase.COMES_FROM_STEP.value == "comes from response of step"


def test_origin_status_phrase_undetermined_value() -> None:
    assert OriginStatusPhrase.UNDETERMINED.value == "origin location undetermined — using literal captured value"


def test_origin_status_phrase_extraction_exhausted_value() -> None:
    assert OriginStatusPhrase.EXTRACTION_EXHAUSTED.value == (
        "origin location determined but extraction exhausted — using literal captured value"
    )


def test_replay_status_phrase_probably_static_value() -> None:
    assert ReplayStatusPhrase.PROBABLY_STATIC.value == "probably static"


def test_replay_status_phrase_could_not_extract_value() -> None:
    assert ReplayStatusPhrase.COULD_NOT_EXTRACT.value == (
        "could not extract value from response, using captured value"
    )


def test_phrase_enums_are_str_enum() -> None:
    assert isinstance(DependencyPhrase.COMES_FROM_STEP, str)
    assert isinstance(OriginStatusPhrase.UNDETERMINED, str)
    assert isinstance(ReplayStatusPhrase.PROBABLY_STATIC, str)
