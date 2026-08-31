"""Contract tests for feat/durable-sessions. Design: docs/prs/feat-durable-sessions.md.

Each test names one behavior the branch must deliver. Bodies are placeholders
until the store exists; the skip marker keeps the suite green meanwhile.
"""

import pytest

pytestmark = pytest.mark.skip(reason="not implemented: feat/durable-sessions")


def test_session_survives_process_restart(tmp_path):
    """POST /api/chat with session_id S against a file-backed store; build a fresh
    app + store on the same file (simulated uvicorn restart); POST S again; the
    provider receives the first turn's user+assistant messages as prefix."""
    pytest.fail("contract not implemented")


def test_session_row_carries_profile_id_and_nullable_tenant_id(tmp_path):
    """Stored session exposes profile_id == the profile used; tenant_id is None
    until PR #2 supplies one."""
    pytest.fail("contract not implemented")


def test_messages_are_append_only(tmp_path):
    """Two turns produce strictly increasing seq rows; no row is ever updated or
    deleted by a normal turn (prefix-cache rule)."""
    pytest.fail("contract not implemented")


def test_profile_switch_resets_messages_without_deleting_rows(tmp_path):
    """Switching profile mid-session yields an empty messages list on the next
    turn (existing contract) while the old rows remain readable for audit."""
    pytest.fail("contract not implemented")


def test_ttl_sweep_removes_only_stale_sessions(tmp_path):
    """Sessions with last_seen older than SESSION_TTL_SECONDS are swept; fresh
    ones survive; MAX_ACTIVE_SESSIONS counts live rows."""
    pytest.fail("contract not implemented")
