"""Contract tests for feat/audit-log-kill-switch. Design: docs/prs/feat-audit-log-kill-switch.md."""

import pytest

pytestmark = pytest.mark.skip(reason="not implemented: feat/audit-log-kill-switch")


def test_turn_writes_prompt_tool_call_result_and_reply_records(tmp_path):
    """One chat turn with one tool hop appends user_message, tool_call,
    tool_result, assistant_message records, all sharing session_id/turn_id."""
    pytest.fail("contract not implemented")


def test_audit_records_scrub_obvious_secrets(tmp_path):
    """A user message containing an sk-… key is stored as [REDACTED]."""
    pytest.fail("contract not implemented")


def test_disable_endpoint_requires_admin_token():
    """POST /api/agents/{id}/disable without X-Admin-Token → 403; with ADMIN_TOKEN
    unset the endpoint is 404."""
    pytest.fail("contract not implemented")


def test_disabled_agent_rejects_chat_with_503():
    """After POST /api/agents/{id}/disable, POST /api/chat for that profile →
    503 'agent disabled' and a disabled_rejection audit record."""
    pytest.fail("contract not implemented")


def test_disable_stops_in_flight_turn_at_next_hop():
    """Disable mid-turn (between tool hops) → the loop stops before the next
    provider call instead of running to MAX_TOOL_HOPS."""
    pytest.fail("contract not implemented")


def test_disabled_set_survives_restart(tmp_path):
    """Disabled ids persist to disk; a fresh app on the same data dir still
    rejects the agent."""
    pytest.fail("contract not implemented")
