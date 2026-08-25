from pathlib import Path
from typing import ClassVar, Dict, List

import pytest

from har_reproducer.agents.construction.agent_factory import AgentFactory
from har_reproducer.fs_io.workspace import Workspace
from har_reproducer.models import DynamicToken
from har_reproducer.reproduction.script_executor import ScriptExecutor
from har_reproducer.session import SessionStore
from har_reproducer.tracking.baseline_diff import BaselineDiff
from har_reproducer.tracking.candidate_resolver import CandidateResolver
from har_reproducer.tracking.flow_vocabulary import FlowVocabulary
from har_reproducer.tracking.origin_finder import OriginFinder
from har_reproducer.tracking.response_corpus import ResponseCorpus
from tests.real.support.real_capture import RealCapture
from tests.support.fake_extractor_runner import FakeExtractorRunner
from tests.support.fake_metadata_store import FakeMetadataStore
from tests.support.fake_sleeper import FakeSleeper


class LoginSessionCookieFixture:
    LOGIN_STEP_INDEX: ClassVar[int] = 124
    BASELINE_STEP_INDEX: ClassVar[int] = 0
    SESSION_COOKIE_ORIGIN_STEP_INDEX: ClassVar[int] = 12
    SESSION_COOKIE_PATH: ClassVar[str] = "cookie:JSESSIONID"


def _build_resolver(capture: RealCapture, tmp_path: Path) -> CandidateResolver:
    discovery_corpus: ResponseCorpus = ResponseCorpus(
        capture.original_responses_dir, RealCapture.STEP_INDEX_WIDTH
    )
    execution_corpus: ResponseCorpus = ResponseCorpus(
        capture.real_responses_dir, RealCapture.STEP_INDEX_WIDTH
    )
    workspace: Workspace = Workspace(tmp_path)
    agent_factory: AgentFactory = AgentFactory(workspace, ScriptExecutor(), FakeSleeper(), None)
    return CandidateResolver(
        discovery_corpus,
        OriginFinder(discovery_corpus, FlowVocabulary()),
        SessionStore(),
        FakeExtractorRunner(),
        FakeMetadataStore(),
        agent_factory,
        execution_corpus,
    )


def _session_cookie_candidate(capture: RealCapture) -> DynamicToken:
    diffs: Dict[str, str] = BaselineDiff().compare(
        capture.step(LoginSessionCookieFixture.LOGIN_STEP_INDEX),
        capture.step(LoginSessionCookieFixture.BASELINE_STEP_INDEX),
    )
    candidates: List[DynamicToken] = BaselineDiff().detect_candidates(diffs)
    return next(
        candidate for candidate in candidates
        if candidate.path == LoginSessionCookieFixture.SESSION_COOKIE_PATH
    )


@pytest.mark.real_capture
def test_login_session_cookie_is_resolved_against_the_real_capture(
        unimedriopreto_20260824_capture: RealCapture, tmp_path: Path,
) -> None:
    candidate: DynamicToken = _session_cookie_candidate(unimedriopreto_20260824_capture)
    resolver: CandidateResolver = _build_resolver(unimedriopreto_20260824_capture, tmp_path)

    resolved: List[DynamicToken] = resolver.resolve(
        [candidate], LoginSessionCookieFixture.LOGIN_STEP_INDEX
    )

    assert resolved[0].status in ("Static", "Resolved")
    assert resolved[0].origin_step == LoginSessionCookieFixture.SESSION_COOKIE_ORIGIN_STEP_INDEX
