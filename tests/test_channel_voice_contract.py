"""Contract tests for feat/channel-voice. Design: docs/prs/feat-channel-voice.md."""

import pytest

pytestmark = pytest.mark.skip(reason="not implemented: feat/channel-voice")


def test_voice_webhook_returns_connect_stream_twiml():
    """POST /webhooks/twilio/voice with a valid signature → TwiML containing
    <Connect><Stream url=…/></Connect>."""
    pytest.fail("contract not implemented")


def test_final_transcript_runs_agent_turn_and_tts_reply():
    """Fake STT yields a final segment → one run_conversation_stream call on
    session 'voice:{tenant}:{from}' → fake TTS receives the agent's text."""
    pytest.fail("contract not implemented")


def test_barge_in_cancels_tts():
    """New speech during TTS playback stops the current TTS stream."""
    pytest.fail("contract not implemented")


def test_transfer_to_human_ends_ai_leg_with_dial():
    """transfer_to_human tool result → <Dial> to the profile's transfer_number
    and no further agent turns on that call."""
    pytest.fail("contract not implemented")


def test_voice_profile_rejects_mcp_shell_browser_tools():
    """A profile with channels.voice and non-empty mcp_servers, or with
    web_search/fetch_url_text in tools, fails to load."""
    pytest.fail("contract not implemented")


def test_no_recording_by_default():
    """The voice handler never sets <Record> or Twilio recording params unless
    EASYAGENT_VOICE_RECORD=1 (which is not implemented in this branch)."""
    pytest.fail("contract not implemented")
