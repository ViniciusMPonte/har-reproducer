from har_reproducer.models import ExtractorSampleResult


def test_round_trips_through_json_serialization() -> None:
    result: ExtractorSampleResult = ExtractorSampleResult(
        sample_label="origin_step", output="abc", error=None, matches_expected=True,
    )
    restored: ExtractorSampleResult = ExtractorSampleResult.model_validate_json(result.model_dump_json())
    assert restored == result


def test_optional_fields_default_to_none() -> None:
    result: ExtractorSampleResult = ExtractorSampleResult(sample_label="x")
    assert result.output is None
    assert result.error is None
    assert result.matches_expected is None


def test_importable_from_models_package() -> None:
    from har_reproducer.models import ExtractorSampleResult as ImportedResult

    assert ImportedResult is ExtractorSampleResult
