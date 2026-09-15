"""Contract tests for feat/mcp-runtime. Design: docs/prs/feat-mcp-runtime.md."""

import pytest

pytestmark = pytest.mark.skip(reason="not implemented: feat/mcp-runtime")


def test_declared_server_tools_appear_namespaced_in_catalog():
    """A profile declaring server 'notes' whose tools/list returns 'add' exposes
    'mcp__notes__add' to the provider — only if the allowlist names it."""
    pytest.fail("contract not implemented")


def test_mcp_tool_use_is_dispatched_to_client_not_run_tool():
    """tool_use_complete for mcp__notes__add calls the fake server and returns a
    ToolResult; run_tool is never invoked for that name."""
    pytest.fail("contract not implemented")


def test_command_not_on_allowlist_fails_profile_load():
    """mcp_servers[].command absent from EASYAGENT_MCP_ALLOWED_COMMANDS → profile
    load error, no subprocess spawned."""
    pytest.fail("contract not implemented")


def test_server_env_is_minimal_and_excludes_provider_keys():
    """The spawned server sees only the env keys named in its config; no
    ANTHROPIC_API_KEY / OPENAI_API_KEY etc. leak in."""
    pytest.fail("contract not implemented")


def test_sms_and_voice_profiles_cannot_declare_mcp_servers():
    """channels.sms or channels.voice + non-empty mcp_servers → load-time error."""
    pytest.fail("contract not implemented")


def test_tool_list_frozen_per_session():
    """tools/list is called once per session; a changed list mid-session does not
    alter the schemas sent to the provider (prefix-cache rule)."""
    pytest.fail("contract not implemented")
