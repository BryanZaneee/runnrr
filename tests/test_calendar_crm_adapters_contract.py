"""Contract tests for feat/calendar-crm-adapters. Design: docs/prs/feat-calendar-crm-adapters.md."""

import pytest

pytestmark = pytest.mark.skip(reason="not implemented: feat/calendar-crm-adapters")


def test_book_appointment_and_crm_note_require_approval_by_default():
    """Both ToolDefs declare requires_approval=True; a profile cannot relax it."""
    pytest.fail("contract not implemented")


def test_schemas_reject_out_of_allowlist_arguments():
    """duration_min=45, a summary over 120 chars, or an extra 'calendar_id' key
    is rejected at schema validation, before any handler runs."""
    pytest.fail("contract not implemented")


def test_missing_tenant_token_returns_tool_error_not_exception():
    """No OAuth token for the tenant → ToolResult(is_error=True) with a
    connect-your-account message; no traceback, no provider-visible secret."""
    pytest.fail("contract not implemented")


def test_calendar_insert_uses_approval_id_as_ical_uid():
    """Approving the same proposal twice sends the same iCalUID → one event."""
    pytest.fail("contract not implemented")


def test_oauth_refresh_on_expired_token():
    """A 401 from the calendar API triggers one refresh and one retry."""
    pytest.fail("contract not implemented")


def test_preview_tools_unchanged():
    """lead_capture_preview / checkout_link_preview still return previews and
    are not aliased to the live adapters."""
    pytest.fail("contract not implemented")
