"""Contract tests for feat/dlp-redact. Design: docs/prs/feat-dlp-redact.md."""

import pytest

pytestmark = pytest.mark.skip(reason="not implemented: feat/dlp-redact")


def test_luhn_valid_pan_is_redacted_with_last4_tag():
    """'4111 1111 1111 1111' → '[PAN:****1111]'; a 16-digit non-Luhn number is
    left alone."""
    pytest.fail("contract not implemented")


def test_ssn_and_secret_shaped_tokens_are_redacted():
    """'123-45-6789' → '[SSN]'; 'sk-abc…' / 'AKIA…' / 'Bearer …' → '[SECRET]'."""
    pytest.fail("contract not implemented")


def test_user_message_and_tool_results_redacted_before_provider_call():
    """A fake provider records the messages it receives; both the user turn and
    a tool result containing a PAN arrive redacted, for any provider."""
    pytest.fail("contract not implemented")


def test_redaction_happens_before_append_never_after():
    """The stored transcript already contains the redacted text; no message is
    modified after it has been appended (prefix-cache rule)."""
    pytest.fail("contract not implemented")


def test_do_not_embed_front_matter_skips_indexing():
    """A KB file with 'do_not_embed: true' produces zero chunks in the index and
    is counted under 'excluded' in the index status payload."""
    pytest.fail("contract not implemented")


def test_embedded_chunks_are_redacted():
    """An unlabeled KB file containing a PAN is indexed with the PAN redacted;
    the fake embedding backend never sees the raw digits."""
    pytest.fail("contract not implemented")


def test_dlp_cannot_be_disabled_on_channel_profiles():
    """dlp.enabled=false on a profile with channels.sms/voice fails profile load."""
    pytest.fail("contract not implemented")
