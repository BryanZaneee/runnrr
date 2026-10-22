import json
import time

from runnrr import sessions

OWNER = {"X-Workspace-Owner": "a" * 64}
OTHER = {"X-Workspace-Owner": "b" * 64}


def state(id="saved", **changes):
    now = time.time() * 1000
    return {
        "id": id,
        "profileId": "customer-service",
        "model": "claude-sonnet-4-5",
        "projectId": None,
        "title": "Saved conversation",
        "created": now,
        "updated": now,
        **changes,
    }


def test_thread_metadata_is_scoped_and_snooze_expires(client):
    c, _ = client
    payload = state(draft="Keep this draft", pinned=True, snoozedUntil=time.time() * 1000 + 10000)
    assert c.post("/api/threads", headers=OWNER, json=payload).status_code == 200
    assert c.get("/api/threads", headers=OTHER).json()["threads"] == []
    assert c.post("/api/threads", headers=OTHER, json=payload).status_code == 404
    saved = c.get("/api/threads", headers=OWNER).json()["threads"][0]
    assert saved["draft"] == "Keep this draft"
    with sessions.database() as db:
        ui = json.loads(db.execute("SELECT ui FROM threads").fetchone()[0])
        ui["snoozedUntil"] = 1
        db.execute("UPDATE threads SET ui=?", (json.dumps(ui),))
    assert c.get("/api/threads", headers=OWNER).json()["threads"][0]["snoozedUntil"] is None


def test_chat_context_survives_cache_reset(client, monkeypatch, fake_provider_cls):
    c, app = client
    captured = []

    class Provider(fake_provider_cls):
        async def stream(self, **kwargs):
            captured.append(list(kwargs["messages"]))
            async for event in super().stream(**kwargs):
                yield event

    def provider(_):
        return Provider(
            [
                [
                    {"type": "text_delta", "text": "Remembered"},
                    {"type": "message_done", "stop_reason": "end_turn"},
                ]
            ]
        )

    monkeypatch.setattr(app, "get_provider", provider)
    request = {
        "session_id": "saved",
        "profile": "customer-service",
        "model": "claude-sonnet-4-5",
        "message": "Remember my question",
    }
    first = c.post("/api/chat", headers=OWNER, json=request)
    assert "event: done" in first.text, first.text
    app.SESSIONS.clear()
    second = c.post("/api/chat", headers=OWNER, json=request | {"message": "Continue"})
    assert "event: done" in second.text, second.text
    assert len(captured[0]) == 1
    assert len(captured[1]) == 3
    history = c.get("/api/threads", headers=OWNER).json()["threads"][0]["history"]
    assert len(history) == 2
    assert history[0]["events"][-1]["event"] == "done"
    assert c.post("/api/chat", headers=OTHER, json=request).status_code == 404
    assert c.post("/api/chat", json=request).status_code == 404
    assert (
        c.post(
            "/api/chat", headers=OWNER, json=request | {"profile": "research-analyst"}
        ).status_code
        == 409
    )
    saved = c.get("/api/threads", headers=OWNER).json()["threads"][0]
    assert c.post("/api/threads/saved/delete", headers=OWNER).status_code == 200
    assert c.post("/api/threads", headers=OWNER, json=saved).status_code == 200
    restored = c.get("/api/threads", headers=OWNER).json()["threads"][0]
    assert restored["history"] == history
    third = c.post("/api/chat", headers=OWNER, json=request | {"message": "After undo"})
    assert "event: done" in third.text
    assert len(captured[2]) == 5


def test_settled_thread_does_not_wake_and_delete_undo_keeps_context(client):
    c, _ = client
    payload = state(settled=True)
    assert c.post("/api/threads", headers=OWNER, json=payload).status_code == 200
    assert c.get("/api/threads", headers=OWNER).json()["threads"][0]["settled"]
    assert c.post("/api/threads/saved/delete", headers=OTHER).status_code == 404
    assert c.post("/api/threads/saved/delete", headers=OWNER).status_code == 200
    assert c.get("/api/threads", headers=OWNER).json()["threads"] == []
    assert c.post("/api/threads", headers=OWNER, json=payload).status_code == 200
    assert len(c.get("/api/threads", headers=OWNER).json()["threads"]) == 1


def test_saved_messages_serialize_provider_objects(tmp_path):
    from google.genai import types

    owner = "owner"
    sessions.save_ui(owner, sessions.ThreadInput(**state()))
    sessions.begin_turn("saved", owner, "turn", "Hi", "customer-service", "claude-sonnet-4-5", None)
    session = {
        "messages": [types.Content(role="user", parts=[types.Part.from_text(text="Hi")])],
        "provider": "gemini",
        "profile": "customer-service",
        "last_seen": time.time(),
    }
    sessions.finish_turn("saved", owner, "turn", [], session)
    restored = sessions.load_session("saved", owner)
    assert types.Content.model_validate(restored["messages"][0]).parts[0].text == "Hi"


def test_binding_is_locked_during_first_turn(client):
    c, _ = client
    payload = state()
    c.post("/api/threads", headers=OWNER, json=payload)
    from runnrr.projects import owner_key

    owner = owner_key(type("R", (), {"headers": OWNER})())
    sessions.begin_turn(
        "saved", owner, "first", "Question", "customer-service", "claude-sonnet-4-5", None
    )
    assert (
        c.post("/api/threads", headers=OWNER, json=payload | {"model": "other"}).status_code == 409
    )
    assert (
        c.post("/api/threads", headers=OWNER, json=payload | {"title": "Renamed"}).status_code
        == 200
    )


async def test_interrupted_turn_rolls_back_context_and_saves_visible_history(client):
    _, app = client
    session = {"messages": [{"role": "user", "content": "Previous"}], "busy": True}
    sessions.save_ui("owner", sessions.ThreadInput(**state()))
    sessions.begin_turn(
        "saved", "owner", "interrupt", "Question", "customer-service", "claude-sonnet-4-5", None
    )

    async def events():
        session["messages"].append({"role": "user", "content": "Question"})
        yield {"event": "thinking_delta", "text": "Private reasoning"}
        yield {"event": "delta", "text": "Partial response"}
        yield {"event": "error", "message": "Provider unavailable"}

    assert (
        len(
            [e async for e in app._durable_stream(events(), session, "saved", "owner", "interrupt")]
        )
        == 3
    )
    assert len(sessions.load_session("saved", "owner")["messages"]) == 1
    assert session["busy"] is False
    with sessions.database() as db:
        events = db.execute("SELECT events FROM thread_turns").fetchone()[0]
    assert "Partial response" in events
    assert "Private reasoning" not in events
