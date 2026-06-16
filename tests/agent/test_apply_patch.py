import pytest
from har_reproducer.models import SessionState, Extractor, Patch, PatchAction
from har_reproducer.engine import Engine
from pathlib import Path

def test_apply_patch_inject_value(tmp_path):
    """Test that INJECT_VALUE patch correctly updates the session token."""
    engine = Engine(Path("dummy.har"), tmp_path)
    session = engine.session_store
    
    patch = Patch(
        action="INJECT_VALUE",
        target_token_id="auth_token",
        new_value="fixed_token_123",
        rationale="Manual injection for testing"
    )
    
    # We need a method to apply the patch in Engine
    # Since it's not implemented yet, this test should fail.
    engine.apply_patch(patch)
    
    assert session.get_token("auth_token") == "fixed_token_123"

def test_apply_patch_fix_extractor(tmp_path):
    """Test that FIX_EXTRACTOR patch updates the extractor code."""
    engine = Engine(Path("dummy.har"), tmp_path)
    
    token_id = "my_token"
    old_extractor = Extractor(
        token_id=token_id,
        code="def extract_my_token(r): return 'old'",
        verified=True,
        agent_type="RegexAgent"
    )
    engine.session_store.state.registry[token_id] = old_extractor
    
    patch = Patch(
        action="FIX_EXTRACTOR",
        target_token_id=token_id,
        new_code="def extract_my_token(r): return 'new'",
        rationale="Fixing the regex"
    )
    
    engine.apply_patch(patch)
    
    updated_extractor = engine.session_store.state.registry[token_id]
    assert updated_extractor.code == "def extract_my_token(r): return 'new'"
    assert updated_extractor.verified is False # Should be re-verified
