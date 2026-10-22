from runnrr.tools.schemas import schemas_for_tools


def test_empty_selection_exposes_no_tools():
    assert schemas_for_tools(()) == []
    assert schemas_for_tools(None)


def test_chat_preferences_only_remove_tools(client, monkeypatch):
    c, app = client
    seen = []

    async def capture(message, session, provider, model, profile, **kwargs):
        seen.append(profile.tools)
        yield {"event": "done", "stop_reason": "end_turn"}

    monkeypatch.setattr(app, "run_conversation_stream", capture)
    original = app.get_profile("customer-service").tools
    response = c.post(
        "/api/chat",
        json={
            "session_id": "tool-preferences",
            "message": "hello",
            "model": "claude-sonnet-4-5",
            "profile": "customer-service",
            "disabled_tools": [*original, "unregistered_tool"],
        },
    )
    assert response.status_code == 200
    assert seen == [()]
    assert app.get_profile("customer-service").tools == original
