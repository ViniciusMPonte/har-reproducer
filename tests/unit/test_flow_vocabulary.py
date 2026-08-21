from har_reproducer.tracking.flow_vocabulary import FlowVocabulary


def test_rejects_an_address_observed_before_the_origin_step() -> None:
    vocabulary: FlowVocabulary = FlowVocabulary()
    vocabulary.observe("http://127.0.0.1:8080/x", 5)

    assert vocabulary.rejects("http://127.0.0.1:8080", 10) is True


def test_does_not_reject_an_address_observed_after_the_origin_step() -> None:
    vocabulary: FlowVocabulary = FlowVocabulary()
    vocabulary.observe("http://127.0.0.1:8080/x", 5)

    assert vocabulary.rejects("http://127.0.0.1:8080", 3) is False


def test_does_not_reject_text_that_was_never_observed_as_an_address() -> None:
    vocabulary: FlowVocabulary = FlowVocabulary()

    assert vocabulary.rejects("anything", 10) is False


def test_does_not_reject_by_containment_only_exact_equality() -> None:
    vocabulary: FlowVocabulary = FlowVocabulary()
    vocabulary.observe("https://api.example.com/x", 1)

    assert vocabulary.rejects("api", 10) is False


def test_observe_keeps_the_first_step_index_across_repeated_observations() -> None:
    vocabulary: FlowVocabulary = FlowVocabulary()
    vocabulary.observe("http://127.0.0.1:8080/x", 2)
    vocabulary.observe("http://127.0.0.1:8080/y", 5)

    assert vocabulary.rejects("http://127.0.0.1:8080", 3) is True
    assert vocabulary.rejects("http://127.0.0.1:8080", 2) is False


def test_observe_registers_hostname_netloc_and_scheme_netloc() -> None:
    vocabulary: FlowVocabulary = FlowVocabulary()
    vocabulary.observe("http://127.0.0.1:8080/x", 5)

    assert vocabulary.rejects("127.0.0.1", 10) is True
    assert vocabulary.rejects("127.0.0.1:8080", 10) is True
    assert vocabulary.rejects("http://127.0.0.1:8080", 10) is True
    assert vocabulary.rejects("https://127.0.0.1:8080", 10) is False
