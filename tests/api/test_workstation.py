"""The workstation must be public-asset-only and preserve API routing."""

from dataclasses import replace


def test_workstation_assets_and_private_paths(client):
    c, _ = client
    response = c.get("/")
    assert response.status_code == 200
    assert "Runnrr — Workstation" in response.text
    assert c.get("/js/app.mjs").status_code == 200
    assert c.get("/js/threads.mjs").status_code == 200
    assert c.get("/css/styles.css").status_code == 200
    assert c.get("/css/tool-settings.css").status_code == 200
    assert c.get("/api/health").json()["status"] == "ok"
    for path in [
        "/.env",
        "/.git/config",
        "/profiles/personal-agent/system.md",
        "/docs/design/source/support.js",
        "/builder/",
        "/evals/",
        "/api/missing",
    ]:
        assert c.get(path).status_code == 404, path


def test_profile_skill_metadata_has_no_private_paths(client, monkeypatch, tmp_path):
    from runnrr import app as app_module
    from runnrr.profiles import load_profile

    folder = tmp_path / "skills" / "refunds"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: Refund procedure\ndescription: When someone requests a refund\n---\nPrivate body."
    )
    p = replace(load_profile("research-analyst"), skills_root=folder.parent)
    monkeypatch.setattr(app_module, "get_profile", lambda _: p)
    c, _ = client
    response = c.get("/api/profile?profile_id=research-analyst")
    assert response.json()["skills"] == [
        {
            "slug": "refunds",
            "name": "Refund procedure",
            "description": "When someone requests a refund",
        }
    ]
    assert str(tmp_path) not in response.text
    assert "Private body" not in response.text
