"""Contract tests for feat/hitl-actions. Design: docs/prs/feat-hitl-actions.md."""

import pytest

pytestmark = pytest.mark.skip(reason="not implemented: feat/hitl-actions")


def test_requires_approval_tool_is_queued_not_executed():
    """run_tool on a ToolDef with requires_approval=True does not call the
    handler; the ToolResult says the action is queued with an apr_ id."""
    pytest.fail("contract not implemented")


def test_approve_runs_original_handler_with_frozen_arguments():
    """POST /api/approvals/{id}/approve invokes the handler once with the
    arguments captured at proposal time and returns its result."""
    pytest.fail("contract not implemented")


def test_approval_result_is_appended_to_session_not_inserted():
    """After approval the session gains one new trailing message; earlier
    messages are byte-identical (prefix-cache rule)."""
    pytest.fail("contract not implemented")


def test_reject_never_runs_handler():
    """POST /api/approvals/{id}/reject → handler not called; status rejected;
    second approve/reject on the same id → 409."""
    pytest.fail("contract not implemented")


def test_existing_preview_tools_stay_preview():
    """lead_capture_preview and checkout_link_preview have requires_approval
    False and still return preview payloads — nothing silently went live."""
    pytest.fail("contract not implemented")


def test_profile_can_only_tighten_approval():
    """profile.json tool_approval may set a tool to True; setting a ToolDef with
    requires_approval=True to False is rejected at profile load."""
    pytest.fail("contract not implemented")
