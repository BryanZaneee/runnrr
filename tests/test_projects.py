import json
from dataclasses import replace

import pytest
from fastapi import HTTPException

from runnrr import projects
from runnrr.profiles import load_profile
from runnrr.tools.definitions import ToolContext
from runnrr.tools.project_knowledge import read_project_file, search_project

OWNER = {"X-Workspace-Owner": "a" * 64}
OTHER = {"X-Workspace-Owner": "b" * 64}


@pytest.fixture(autouse=True)
def project_db(monkeypatch, tmp_path):
    monkeypatch.setattr(projects, "DB_PATH", tmp_path / "projects.sqlite3")


def create(c):
    return c.post(
        "/api/projects",
        headers=OWNER,
        json={"name": "Desk", "documents": {"notes.md": "The secret project color is lavender."}},
    )


def test_owner_isolation_and_persistence(client):
    c, _ = client
    assert c.get("/api/projects").status_code == 401
    made = create(c)
    assert made.status_code == 200, made.text
    pid = made.json()["id"]
    assert c.get("/api/projects", headers=OWNER).json()["projects"][0]["name"] == "Desk"
    assert c.get("/api/projects", headers=OTHER).json()["projects"] == []
    assert c.post(f"/api/projects/{pid}/delete", headers=OTHER).status_code == 404
    # A new connection sees the saved project; removing it does not affect others.
    with projects.database() as db:
        assert db.execute("SELECT count(*) FROM projects").fetchone()[0] == 1
    assert c.post(f"/api/projects/{pid}/delete", headers=OWNER).status_code == 200
    assert c.get("/api/projects", headers=OWNER).json()["projects"] == []


@pytest.mark.parametrize(
    "path", ["../escape.md", "/private.md", ".env", ".git/config.txt", "x\\secret.txt", "notes.pdf"]
)
def test_reject_unsafe_uploads(client, path):
    c, _ = client
    assert (
        c.post(
            "/api/projects", headers=OWNER, json={"name": "Bad", "documents": {path: "x"}}
        ).status_code
        == 400
    )


def test_limits_and_public_read_only(client, monkeypatch):
    c, _ = client
    assert c.post("/api/projects", headers=OWNER, content=b"x" * 2_000_001).status_code == 413
    assert (
        c.post(
            "/api/projects",
            headers=OWNER,
            json={"name": "Large", "documents": {"a.md": "x" * 200001}},
        ).status_code
        == 400
    )
    monkeypatch.setattr(projects, "PUBLIC_DEMO", True)
    row = projects.save_project("public", "Public", {"README.md": "Public content"})
    assert c.get("/api/projects", headers=OTHER).json()["projects"][0]["shared"]
    assert c.post(f"/api/projects/{row['id']}/delete", headers=OTHER).status_code == 403


@pytest.mark.parametrize(
    "value",
    ["http://127.0.0.1/a", "https://github.com.evil.com/a/b", "a/b/../../x", "a/b?x=y", "a/b#x"],
)
def test_github_urls_are_not_arbitrary_fetches(value):
    with pytest.raises(HTTPException):
        projects.repository_name(value)


def test_refresh_failure_preserves_previous_copy(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(projects, "github_snapshot", lambda _: ("repo", {"README.md": "original"}))
    made = c.post(
        "/api/projects", headers=OWNER, json={"name": "Repo", "repository": "someone/repo"}
    ).json()

    def fail(_):
        raise HTTPException(502, "GitHub unavailable")

    monkeypatch.setattr(projects, "github_snapshot", fail)
    assert c.post(f"/api/projects/{made['id']}/refresh", headers=OWNER).status_code == 502
    with projects.database() as db:
        assert (
            json.loads(db.execute("SELECT documents FROM projects").fetchone()[0])["README.md"]
            == "original"
        )


def test_chat_project_binding(client, monkeypatch, fake_provider_cls):
    c, app = client
    pid = create(c).json()["id"]
    fake = fake_provider_cls(
        [
            [
                {"type": "text_delta", "text": "ok"},
                {"type": "message_done", "stop_reason": "end_turn"},
            ]
        ]
    )
    monkeypatch.setattr(app, "get_provider", lambda _: fake)
    captured = []
    original = app.run_conversation_stream

    async def capture(message, session, provider, model, profile, **kwargs):
        captured.append(profile)
        async for ev in original(message, session, provider, model, profile, **kwargs):
            yield ev

    monkeypatch.setattr(app, "run_conversation_stream", capture)
    body = {
        "session_id": "project-session",
        "message": "What color?",
        "model": "claude-sonnet-4-5",
        "project_id": pid,
    }
    assert c.post("/api/chat", headers=OTHER, json=body).status_code == 404
    assert c.post("/api/chat", headers=OWNER, json=body).status_code == 200
    assert captured[0].project_documents["notes.md"].endswith("lavender.")
    assert "read_project_file" in captured[0].tools
    assert c.post("/api/chat", headers=OWNER, json=body | {"project_id": None}).status_code == 409
    profile = replace(
        load_profile("research-analyst"),
        project_documents={"notes.md": "color: lavender"},
        project_name="Desk",
    )
    ctx = ToolContext(profile=profile)
    assert search_project({"query": "lavender"}, ctx)["matches"][0]["path"] == "notes.md"
    assert read_project_file({"path": "notes.md"}, ctx)["content"] == "color: lavender"
    assert "error" in read_project_file({"path": "../resume.md"}, ctx)


def test_local_picker_never_exposes_portfolio(client, monkeypatch):
    c, _ = client
    shared = projects.save_project("public", "Portfolio", {"website.md": "Public"})
    assert c.get("/api/projects", headers=OWNER).json()["projects"] == []
    with pytest.raises(HTTPException) as exc:
        projects.get_project(shared["id"], projects.owner_key(type("R", (), {"headers": OWNER})()))
    assert exc.value.status_code == 404
    monkeypatch.setattr(projects, "PUBLIC_DEMO", True)
    assert c.get("/api/projects", headers=OWNER).json()["projects"][0]["name"] == "Portfolio"
    assert create(c).status_code == 403


def test_website_inventory_includes_projects_without_public_repositories():
    from runnrr.github_sync import PortfolioParser

    parser = PortfolioParser()
    parser.feed(
        '<article class="work-row" data-id="photo"><h4><a>Photo Studio</a></h4><p>Public description</p></article><article class="work-row" data-id="runnrr"><h4>Runnrr</h4><a href="https://github.com/BryanZaneee/runnrr">Code</a></article>'
    )
    assert len(parser.projects) == 2
    assert parser.projects[0]["repository"] is None
    assert parser.projects[0]["name"] == "Photo Studio"
    assert parser.projects[1]["repository"] == "BryanZaneee/runnrr"


@pytest.mark.asyncio
async def test_demo_prompt_limit_prevents_provider_call(monkeypatch, fake_provider_cls):
    from runnrr.agent import run_conversation_stream

    monkeypatch.setattr("runnrr.agent.MAX_REQUEST_TOKEN_RESERVATION", 100)
    provider = fake_provider_cls([])
    events = [
        event
        async for event in run_conversation_stream("hello", {"messages": []}, provider, "test")
    ]
    assert events[-1]["event"] == "error"
    assert "too large" in events[-1]["message"]


def test_portfolio_refresh_keeps_last_snapshot_when_github_fails(monkeypatch, tmp_path):
    from runnrr import github_sync

    profile_root = tmp_path / "profiles"
    (profile_root / "test").mkdir(parents=True)
    (profile_root / "test" / "github.json").write_text('{"website":"https://bryanzane.com/"}')
    kb = tmp_path / "kb"
    (kb / "github").mkdir(parents=True)
    saved = kb / "github" / "sample.md"
    saved.write_text("Previously verified knowledge")
    profile = replace(load_profile("research-analyst"), id="test", kb_root=kb)
    monkeypatch.setattr(github_sync, "PROFILE_ROOT", profile_root)
    monkeypatch.setattr(github_sync, "load_profile", lambda _: profile)
    monkeypatch.setattr(
        github_sync,
        "website_projects",
        lambda _: [
            {
                "slug": "sample",
                "name": "Sample",
                "text": ["New text"],
                "repository": "example/sample",
            }
        ],
    )

    def failed_snapshot(_):
        raise HTTPException(502, "GitHub unavailable")

    monkeypatch.setattr(github_sync, "github_snapshot", failed_snapshot)
    assert github_sync.sync("test") == ["Sample"]
    assert saved.read_text() == "Previously verified knowledge"
    with projects.database() as db:
        assert db.execute("SELECT count(*) FROM projects").fetchone()[0] == 0
