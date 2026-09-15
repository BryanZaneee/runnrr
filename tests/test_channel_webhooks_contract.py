"""Contract tests for feat/channel-webhooks (Twilio SMS). Design: docs/prs/feat-channel-webhooks.md."""

import pytest

pytestmark = pytest.mark.skip(reason="not implemented: feat/channel-webhooks")


def test_valid_signature_accepted_invalid_rejected_with_403():
    """Known-answer HMAC-SHA1 vector over URL + sorted params with
    TWILIO_AUTH_TOKEN validates; a tampered Body → 403."""
    pytest.fail("contract not implemented")


def test_skip_verify_only_outside_production():
    """EASYAGENT_TWILIO_SKIP_VERIFY=1 bypasses the check when ENV != production;
    in production the flag is ignored and a missing token fails startup."""
    pytest.fail("contract not implemented")


def test_from_to_body_map_to_chat_turn_with_durable_session_key():
    """Inbound From/To/Body runs one agent turn on session 'sms:{tenant}:{from}'
    with the profile mapped from To; a second text continues the same session."""
    pytest.fail("contract not implemented")


def test_auto_reply_profile_returns_twiml_message():
    """Profile with channels.sms.auto_reply=true → 200 text/xml
    <Response><Message>…</Message></Response> containing the agent text."""
    pytest.fail("contract not implemented")


def test_non_auto_reply_profile_returns_empty_response_and_queues_draft():
    """Profile without auto_reply → <Response/> and the reply is queued as a
    pending approval (or logged as a draft until feat/hitl-actions lands)."""
    pytest.fail("contract not implemented")


def test_unmapped_to_number_is_404():
    """A To number absent from TWILIO_NUMBER_MAP → 404, nothing sent to a provider."""
    pytest.fail("contract not implemented")
