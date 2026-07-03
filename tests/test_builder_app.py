"""Agent Builder API tests — gating, ownership, caps, and write boundaries."""
from __future__ import annotations

import json
import os
import time

import pytest

OWNER = {"X-Builder-Owner": "test-owner-token-0001"}
OTHER_OWNER = {"X-Builder-Owner": "someone-elses-token-9"}


def _valid_body(**overrides) -> dict:
    body = {
        "label": "Coffee Helper",
        "description": "Answers questions about the shop.",
        "instructions": "You are a friendly assistant for a coffee shop.",
        "welcome": "Hi! Ask me about our menu.",
        "suggestions": ["What's on the menu?", "When are you open?"],
        "tools": ["list_kb", "read_file", "search_kb"],
        "accent": "#8a5a3b",
    }
    body.update(overrides)
    return body


@pytest.fixture
def builder_client(client, tmp_path, monkeypatch):
    """Client with the builder enabled and an isolated profile tree."""
    c, app_module = client
    from backend import config
    from backend import profiles as profiles_module

    profiles_root = tmp_path / "profiles"
    profiles_root.mkdir()
    monkeypatch.setattr(config, "ENABLE_PROFILE_EDITOR", True)
    monkeypatch.setattr(config, "PROFILE_ROOT", profiles_root)
    monkeypatch.setattr(profiles_module, "PROFILE_ROOT", profiles_root)
    monkeypatch.setattr(app_module, "PROFILE_ROOT", profiles_root)
    return c, app_module, profiles_root


class TestGating:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/api/builder/profile/x"),
            ("post", "/api/builder/profile/x"),
            ("get", "/api/builder/kb/x"),
            ("get", "/api/builder/kb/x/file?path=a.md"),
            ("post", "/api/builder/kb/x/file"),
            ("post", "/api/builder/kb/x/file/delete"),
        ],
    )
    def test_disabled_by_default(self, client, method, path):
        c, _ = client
        r = getattr(c, method)(path, **({"json": {}} if method == "post" else {}))
        assert r.status_code == 404

    def test_tools_catalog_is_always_available(self, client):
        from backend.tools.schemas import DEFAULT_TOOL_NAMES

        c, _ = client
        r = c.get("/api/tools")
        assert r.status_code == 200
        names = {t["name"] for t in r.json()["tools"]}
        assert names == set(DEFAULT_TOOL_NAMES)
        assert all(t["description"] for t in r.json()["tools"])


class TestSaveProfile:
    def test_create_writes_files_and_is_immediately_loadable(self, builder_client):
        c, _, profiles_root = builder_client
        r = c.post("/api/builder/profile/coffee-helper", json=_valid_body(), headers=OWNER)
        assert r.status_code == 200
        assert r.json()["label"] == "Coffee Helper"
        assert r.json()["tools"] == ["list_kb", "read_file", "search_kb"]
        assert r.json()["brand"] == {"accent": "#8a5a3b"}

        prof_dir = profiles_root / "coffee-helper"
        assert (prof_dir / "profile.json").is_file()
        assert (prof_dir / "system.md").is_file()
        assert (prof_dir / "kb").is_dir()
        cfg = json.loads((prof_dir / "profile.json").read_text())
        assert cfg["builder"] is True
        assert "inject_kb_manifest" not in cfg

        # No restart needed: the public profile endpoint sees it right away.
        r = c.get("/api/profile", params={"profile_id": "coffee-helper"})
        assert r.status_code == 200
        assert r.json()["welcome"] == "Hi! Ask me about our menu."

    def test_update_preserves_builder_flag(self, builder_client):
        c, _, profiles_root = builder_client
        assert (
            c.post("/api/builder/profile/shop", json=_valid_body(), headers=OWNER).status_code
            == 200
        )
        r = c.post(
            "/api/builder/profile/shop", json=_valid_body(label="New Name"), headers=OWNER
        )
        assert r.status_code == 200
        cfg = json.loads((profiles_root / "shop" / "profile.json").read_text())
        assert cfg["label"] == "New Name"
        assert cfg["builder"] is True

    def test_unknown_tool_rejected_and_nothing_written(self, builder_client):
        c, _, profiles_root = builder_client
        r = c.post(
            "/api/builder/profile/shop",
            json=_valid_body(tools=["not_a_real_tool"]),
            headers=OWNER,
        )
        assert r.status_code == 400
        assert "not_a_real_tool" in r.json()["detail"]
        assert not (profiles_root / "shop").exists()

    @pytest.mark.parametrize("bad_id", ["My Agent", "../x", "UPPER", "a" * 65, "-lead"])
    def test_bad_slugs_rejected(self, builder_client, bad_id):
        c, _, profiles_root = builder_client
        r = c.post(f"/api/builder/profile/{bad_id}", json=_valid_body(), headers=OWNER)
        assert r.status_code in (400, 404)  # 404 when the path itself doesn't route
        assert not any(profiles_root.iterdir())

    def test_bad_accent_rejected(self, builder_client):
        c, _, _ = builder_client
        r = c.post(
            "/api/builder/profile/shop", json=_valid_body(accent="red"), headers=OWNER
        )
        assert r.status_code == 422

    def test_bundled_profile_protected(self, builder_client):
        c, _, profiles_root = builder_client
        prof_dir = profiles_root / "bundled"
        prof_dir.mkdir()
        original = json.dumps({"id": "bundled", "label": "Bundled", "tools": []})
        (prof_dir / "profile.json").write_text(original)

        r = c.post("/api/builder/profile/bundled", json=_valid_body(), headers=OWNER)
        assert r.status_code == 409
        assert (prof_dir / "profile.json").read_text() == original

        r = c.post(
            "/api/builder/kb/bundled/file",
            json={"path": "x.md", "content": "hi"},
            headers=OWNER,
        )
        assert r.status_code == 409

    def test_bundled_profile_readable_as_example(self, builder_client):
        c, _, profiles_root = builder_client
        prof_dir = profiles_root / "bundled"
        prof_dir.mkdir()
        (prof_dir / "profile.json").write_text(
            json.dumps({"id": "bundled", "label": "Bundled", "tools": ["search_kb"]})
        )
        (prof_dir / "system.md").write_text("You are the bundled example.")

        # No owner header needed: bundled profiles are public read-only examples.
        r = c.get("/api/builder/profile/bundled")
        assert r.status_code == 200
        body = r.json()
        assert body["readonly"] is True
        assert body["instructions"] == "You are the bundled example."
        assert body["tools"] == ["search_kb"]

    def test_read_back_editable_fields(self, builder_client):
        c, _, _ = builder_client
        c.post("/api/builder/profile/shop", json=_valid_body(), headers=OWNER)
        r = c.get("/api/builder/profile/shop", headers=OWNER)
        assert r.status_code == 200
        body = r.json()
        assert body["instructions"] == "You are a friendly assistant for a coffee shop."
        assert body["accent"] == "#8a5a3b"
        assert c.get("/api/builder/profile/missing", headers=OWNER).status_code == 404


class TestOwnership:
    def test_create_requires_owner_token(self, builder_client):
        c, _, profiles_root = builder_client
        r = c.post("/api/builder/profile/shop", json=_valid_body())
        assert r.status_code == 400
        assert "owner token" in r.json()["detail"]
        assert not (profiles_root / "shop").exists()

    def test_malformed_token_rejected(self, builder_client):
        c, _, _ = builder_client
        r = c.post(
            "/api/builder/profile/shop",
            json=_valid_body(),
            headers={"X-Builder-Owner": "no spaces allowed!"},
        )
        assert r.status_code == 400

    def test_hash_stored_never_raw_token(self, builder_client):
        import hashlib

        c, _, profiles_root = builder_client
        c.post("/api/builder/profile/shop", json=_valid_body(), headers=OWNER)
        cfg = json.loads((profiles_root / "shop" / "profile.json").read_text())
        token = OWNER["X-Builder-Owner"]
        assert cfg["owner_sha256"] == hashlib.sha256(token.encode()).hexdigest()
        assert token not in (profiles_root / "shop" / "profile.json").read_text()
        # And no endpoint echoes the hash back.
        r = c.get("/api/builder/profile/shop", headers=OWNER)
        assert "owner_sha256" not in r.json()
        r = c.get("/api/profile", params={"profile_id": "shop"})
        assert "owner_sha256" not in json.dumps(r.json())

    def test_wrong_token_forbidden_everywhere(self, builder_client):
        c, _, _ = builder_client
        c.post("/api/builder/profile/shop", json=_valid_body(), headers=OWNER)
        c.post(
            "/api/builder/kb/shop/file",
            json={"path": "menu.md", "content": "x"},
            headers=OWNER,
        )
        assert (
            c.get("/api/builder/profile/shop", headers=OTHER_OWNER).status_code == 403
        )
        assert (
            c.post(
                "/api/builder/profile/shop", json=_valid_body(), headers=OTHER_OWNER
            ).status_code
            == 403
        )
        assert c.get("/api/builder/kb/shop", headers=OTHER_OWNER).status_code == 403
        assert (
            c.get(
                "/api/builder/kb/shop/file",
                params={"path": "menu.md"},
                headers=OTHER_OWNER,
            ).status_code
            == 403
        )
        assert (
            c.post(
                "/api/builder/kb/shop/file",
                json={"path": "menu.md", "content": "y"},
                headers=OTHER_OWNER,
            ).status_code
            == 403
        )
        assert (
            c.post(
                "/api/builder/kb/shop/file/delete",
                json={"path": "menu.md"},
                headers=OTHER_OWNER,
            ).status_code
            == 403
        )

    def test_legacy_ownerless_profile_claimable(self, builder_client):
        c, _, profiles_root = builder_client
        prof_dir = profiles_root / "legacy"
        (prof_dir / "kb").mkdir(parents=True)
        (prof_dir / "profile.json").write_text(
            json.dumps({"id": "legacy", "label": "Legacy", "tools": [], "builder": True})
        )
        (prof_dir / "system.md").write_text("legacy")
        # Readable without ownership...
        assert c.get("/api/builder/profile/legacy", headers=OWNER).status_code == 200
        # ...and the next save binds it to the caller.
        assert (
            c.post("/api/builder/profile/legacy", json=_valid_body(), headers=OWNER).status_code
            == 200
        )
        assert (
            c.get("/api/builder/profile/legacy", headers=OTHER_OWNER).status_code == 403
        )


class TestBuilderToolAllowlist:
    @pytest.mark.parametrize(
        "tool", ["get_resume_summary", "get_project_context", "semantic_search_kb"]
    )
    def test_hidden_tools_rejected(self, builder_client, tool):
        c, _, profiles_root = builder_client
        r = c.post(
            "/api/builder/profile/shop", json=_valid_body(tools=[tool]), headers=OWNER
        )
        assert r.status_code == 400
        assert tool in r.json()["detail"]
        assert not (profiles_root / "shop").exists()

    def test_catalog_tools_provision_demo_catalog(self, builder_client):
        from backend.profiles import load_profile
        from backend.tools import run_tool

        c, _, profiles_root = builder_client
        r = c.post(
            "/api/builder/profile/shop",
            json=_valid_body(tools=["catalog_lookup", "qualify_lead"]),
            headers=OWNER,
        )
        assert r.status_code == 200
        catalog_path = profiles_root / "shop" / "data" / "catalog.json"
        assert catalog_path.is_file()

        p = load_profile("shop", profile_root=profiles_root)
        # Relative data_root resolves against the real project root, so under a
        # tmp PROFILE_ROOT we pass the provisioned dir explicitly. In prod,
        # PROFILE_ROOT lives inside the project root and p.data_root is correct.
        result = run_tool(
            "catalog_lookup",
            {"query": "research report"},
            tool_use_id="t1",
            data_root=profiles_root / "shop" / "data",
            profile=p,
        )
        assert result.is_error is False
        assert "research-profile" in result.content


class TestBuilderLimits:
    def test_profile_cap(self, builder_client, monkeypatch):
        from backend import config

        c, _, _ = builder_client
        monkeypatch.setattr(config, "MAX_BUILDER_PROFILES", 1)
        assert (
            c.post("/api/builder/profile/one", json=_valid_body(), headers=OWNER).status_code
            == 200
        )
        r = c.post("/api/builder/profile/two", json=_valid_body(), headers=OWNER)
        assert r.status_code == 503
        # Updating the existing one is still allowed.
        assert (
            c.post("/api/builder/profile/one", json=_valid_body(), headers=OWNER).status_code
            == 200
        )

    def test_note_cap_blocks_new_but_not_overwrite(self, builder_client, monkeypatch):
        from backend import config

        c, _, _ = builder_client
        monkeypatch.setattr(config, "MAX_NOTES_PER_PROFILE", 1)
        c.post("/api/builder/profile/shop", json=_valid_body(), headers=OWNER)
        assert (
            c.post(
                "/api/builder/kb/shop/file",
                json={"path": "a.md", "content": "x"},
                headers=OWNER,
            ).status_code
            == 200
        )
        r = c.post(
            "/api/builder/kb/shop/file",
            json={"path": "b.md", "content": "x"},
            headers=OWNER,
        )
        assert r.status_code == 400
        assert "note limit" in r.json()["detail"]
        # Overwriting the existing note is fine.
        assert (
            c.post(
                "/api/builder/kb/shop/file",
                json={"path": "a.md", "content": "updated"},
                headers=OWNER,
            ).status_code
            == 200
        )

    def test_ttl_sweep_reaps_stale_builder_spares_bundled(self, builder_client):
        c, _, profiles_root = builder_client
        c.post("/api/builder/profile/stale", json=_valid_body(), headers=OWNER)

        bundled = profiles_root / "bundled"
        bundled.mkdir()
        (bundled / "profile.json").write_text(json.dumps({"id": "bundled", "tools": []}))

        # Backdate everything past the 30-day TTL.
        old = time.time() - 40 * 86400
        for d in (profiles_root / "stale", bundled):
            for p in [d, *d.rglob("*")]:
                os.utime(p, (old, old))

        # The next create triggers the sweep.
        c.post("/api/builder/profile/fresh", json=_valid_body(), headers=OWNER)
        assert not (profiles_root / "stale").exists()
        assert bundled.exists()
        assert (profiles_root / "fresh").exists()


class TestBuilderRateLimit:
    def test_rapid_saves_hit_429(self, builder_client):
        # Toggle the limiter instance the builder decorators are bound to
        # (module reloads elsewhere can leave backend.ratelimit.limiter as a
        # different, newer instance).
        from backend import builder as builder_module

        c, app_module, _ = builder_client
        lim = builder_module.limiter
        lim.enabled = True  # conftest disables the app-level limiter
        app_module.limiter.enabled = True
        lim.reset()
        try:
            codes = [
                c.post(
                    "/api/builder/profile/rl-test", json=_valid_body(), headers=OWNER
                ).status_code
                for _ in range(11)
            ]
            assert codes[:10] == [200] * 10
            assert codes[10] == 429
        finally:
            lim.enabled = False
            app_module.limiter.enabled = False
            lim.reset()


class TestKbNotes:
    @pytest.fixture
    def shop(self, builder_client):
        c, app_module, profiles_root = builder_client
        assert (
            c.post("/api/builder/profile/shop", json=_valid_body(), headers=OWNER).status_code
            == 200
        )
        return c, app_module, profiles_root

    def test_write_list_read_delete_roundtrip(self, shop):
        c, _, _ = shop
        r = c.post(
            "/api/builder/kb/shop/file",
            json={"path": "menu.md", "content": "# Menu\n\nLatte $4\n"},
            headers=OWNER,
        )
        assert r.status_code == 200

        r = c.get("/api/builder/kb/shop", headers=OWNER)
        assert [f["path"] for f in r.json()["files"]] == ["menu.md"]

        r = c.get("/api/builder/kb/shop/file", params={"path": "menu.md"}, headers=OWNER)
        assert "Latte $4" in r.json()["content"]

        assert (
            c.post(
                "/api/builder/kb/shop/file/delete", json={"path": "menu.md"}, headers=OWNER
            ).status_code
            == 200
        )
        assert c.get("/api/builder/kb/shop", headers=OWNER).json()["files"] == []

    @pytest.mark.parametrize(
        "path", ["../../evil.md", "/etc/passwd", "a/../../../b.md", "notes.txt"]
    )
    def test_write_path_boundary(self, shop, path, tmp_path):
        c, _, profiles_root = shop
        r = c.post(
            "/api/builder/kb/shop/file", json={"path": path, "content": "x"}, headers=OWNER
        )
        assert r.status_code == 400
        assert not (tmp_path / "evil.md").exists()
        assert not (profiles_root / "evil.md").exists()
        assert not (profiles_root / "shop" / "evil.md").exists()

    def test_symlink_escape_rejected(self, shop, tmp_path):
        c, _, profiles_root = shop
        outside = tmp_path / "outside"
        outside.mkdir()
        (profiles_root / "shop" / "kb" / "link").symlink_to(outside)
        r = c.post(
            "/api/builder/kb/shop/file",
            json={"path": "link/evil.md", "content": "x"},
            headers=OWNER,
        )
        assert r.status_code == 400
        assert not (outside / "evil.md").exists()

    def test_oversized_note_rejected(self, shop):
        c, _, _ = shop
        r = c.post(
            "/api/builder/kb/shop/file",
            json={"path": "big.md", "content": "x" * 200_001},
            headers=OWNER,
        )
        assert r.status_code == 400

    def test_delete_missing_and_traversal(self, shop):
        c, _, _ = shop
        assert (
            c.post(
                "/api/builder/kb/shop/file/delete", json={"path": "nope.md"}, headers=OWNER
            ).status_code
            == 404
        )
        assert (
            c.post(
                "/api/builder/kb/shop/file/delete", json={"path": "../../x.md"}, headers=OWNER
            ).status_code
            == 400
        )

    def test_kb_ops_on_missing_profile_404(self, builder_client):
        c, _, _ = builder_client
        assert c.get("/api/builder/kb/ghost", headers=OWNER).status_code == 404
        assert (
            c.post(
                "/api/builder/kb/ghost/file",
                json={"path": "a.md", "content": "x"},
                headers=OWNER,
            ).status_code
            == 404
        )


class TestChatAgainstBuiltProfile:
    def test_chat_uses_freshly_created_profile(
        self, builder_client, monkeypatch, fake_provider_cls
    ):
        c, app_module, _ = builder_client
        assert (
            c.post("/api/builder/profile/shop", json=_valid_body(), headers=OWNER).status_code
            == 200
        )

        fake = fake_provider_cls(
            [
                [
                    {"type": "text_delta", "text": "Hello from shop"},
                    {"type": "message_done", "stop_reason": "end_turn"},
                ]
            ]
        )
        monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)
        with c.stream(
            "POST",
            "/api/chat",
            json={
                "session_id": "b1",
                "message": "hi",
                "model": "claude-sonnet-4-5",
                "profile": "shop",
            },
        ) as r:
            assert r.status_code == 200
            body = b"".join(r.iter_bytes()).decode("utf-8")
        assert "Hello from shop" in body


class TestBuilderProfilesUnlisted:
    def test_builder_profiles_hidden_from_listing_but_loadable(self, builder_client):
        c, _, _ = builder_client
        c.post("/api/builder/profile/hidden-agent", json=_valid_body(), headers=OWNER)
        listed = {p["id"] for p in c.get("/api/profiles").json()["profiles"]}
        assert "hidden-agent" not in listed
        r = c.get("/api/profile", params={"profile_id": "hidden-agent"})
        assert r.status_code == 200
        assert r.json()["label"] == "Coffee Helper"
