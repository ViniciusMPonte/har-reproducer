from pathlib import Path
from typing import Dict, Set

from har_reproducer.fs_io import Workspace
from har_reproducer.replay.curl_token_comment import CurlTokenComment
from har_reproducer.replay.replay_token_resolver import ReplayTokenResolver
from har_reproducer.reproduction import ExtractorMetadataStore, ExtractorRunner
from har_reproducer.reproduction.script_executor import ScriptExecutor
from har_reproducer.session import SessionStore


def test_replay_resolves_tokens_from_original_responses_in_dry_workspace(
        dry_workspace: Path,
        tmp_path: Path,
) -> None:
    assert list((dry_workspace / "real_responses").glob("res_*.json")) == []

    curl_token_comment: CurlTokenComment = CurlTokenComment(step_index_width=Workspace.STEP_INDEX_WIDTH)
    curl_text: str = (dry_workspace / "curls" / "req_0004.curl.sh").read_text(encoding="utf-8")
    dependencies: Dict[str, int] = curl_token_comment.parse(curl_text)
    assert set(dependencies.values()).isdisjoint({4})

    resolver: ReplayTokenResolver = ReplayTokenResolver(
        SessionStore(),
        ExtractorRunner(Workspace(dry_workspace), ScriptExecutor()),
        curl_token_comment,
        ExtractorMetadataStore(Workspace(dry_workspace)),
    )

    static_ids: Set[str]
    fallback_ids: Set[str]
    static_ids, fallback_ids = resolver.resolve(
        curl_text, schedule={4}, replay_run_dir=tmp_path / "replay",
        res_refer_dir=dry_workspace / "real_responses",
        original_responses_dir=dry_workspace / "original_responses",
    )

    assert resolver.session_store.state.tokens == {
        "ade6a53080262635799eb7ec66e824e8": "4242",
        "f04743b512e6241375b3226e7f7c69d3": "scr_NONCE_2",
    }
    assert static_ids == set()
    assert fallback_ids == set()
