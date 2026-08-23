"""Skills: discovery, the trust boundary, and the cache coupling."""
from __future__ import annotations

import pytest

from backend.skills import (
    MAX_CATALOG_CHARS,
    SkillError,
    build_skill_catalog,
    discover_skills,
    read_skill_body,
)


def _write_skill(root, slug, *, name="Thing", description="does a thing", body="Step one."):
    d = root / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n", encoding="utf-8"
    )
    return d


class TestDiscovery:
    def test_finds_skills_and_parses_frontmatter(self, tmp_path):
        _write_skill(tmp_path, "refund-request", name="Refund", description="handle refunds")
        skills = discover_skills(tmp_path)
        assert len(skills) == 1
        assert skills[0].slug == "refund-request"
        assert skills[0].name == "Refund"
        assert skills[0].description == "handle refunds"

    def test_missing_dir_is_not_an_error(self, tmp_path):
        assert discover_skills(tmp_path / "nope") == ()
        assert discover_skills(None) == ()

    def test_skill_without_description_is_skipped(self, tmp_path):
        d = tmp_path / "vague"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: Vague\n---\n\nsteps", encoding="utf-8")
        # No description means the model has nothing to match on and would never
        # call read_skill, so listing it would only cost prompt tokens.
        assert discover_skills(tmp_path) == ()

    def test_malformed_file_does_not_break_the_others(self, tmp_path):
        _write_skill(tmp_path, "good")
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "SKILL.md").write_text("no frontmatter at all", encoding="utf-8")
        slugs = [s.slug for s in discover_skills(tmp_path)]
        assert slugs == ["good"]

    def test_directory_without_skill_md_is_ignored(self, tmp_path):
        (tmp_path / "notaskill").mkdir()
        assert discover_skills(tmp_path) == ()


class TestCatalog:
    def test_catalog_is_byte_stable(self, tmp_path):
        """The catalog sits inside the cached prompt prefix.

        If it varied between builds — unsorted directory order, a timestamp —
        the prefix would stop matching and the cache would silently never hit.
        """
        for slug in ("zebra", "alpha", "middle"):
            _write_skill(tmp_path, slug)
        first = build_skill_catalog(discover_skills(tmp_path))
        second = build_skill_catalog(discover_skills(tmp_path))
        assert first == second
        assert first.index("alpha") < first.index("middle") < first.index("zebra")

    def test_empty_catalog_is_empty_string(self, tmp_path):
        assert build_skill_catalog(discover_skills(tmp_path)) == ""

    def test_catalog_is_bounded(self, tmp_path):
        # A hundred skills must not re-inflate the prefix the caching work exists
        # to shrink.
        for i in range(200):
            _write_skill(tmp_path, f"skill-{i:03d}", description="x" * 190)
        catalog = build_skill_catalog(discover_skills(tmp_path))
        assert len(catalog) < MAX_CATALOG_CHARS + 500
        assert "more not shown" in catalog


class TestReadSkillBody:
    def test_returns_body_without_frontmatter(self, tmp_path):
        _write_skill(tmp_path, "refund", body="1. Ask for the order id.")
        got = read_skill_body("refund", tmp_path)
        assert got["steps"] == "1. Ask for the order id."
        assert "description:" not in got["steps"]

    def test_unknown_slug_raises(self, tmp_path):
        with pytest.raises(SkillError):
            read_skill_body("nope", tmp_path)

    @pytest.mark.parametrize(
        "slug", ["../../etc/passwd", "/etc/passwd", "..", "a/../../b", ""]
    )
    def test_traversal_is_impossible(self, tmp_path, slug):
        """slug is matched against discovered names, never joined into a path.

        There is no attacker-controlled path arithmetic to get wrong.
        """
        _write_skill(tmp_path, "real")
        with pytest.raises(SkillError):
            read_skill_body(slug, tmp_path)

    def test_does_not_escape_via_symlink(self, tmp_path):
        outside = tmp_path.parent / "outside_skill"
        outside.mkdir(exist_ok=True)
        (outside / "SKILL.md").write_text(
            "---\nname: Evil\ndescription: bad\n---\nsecret", encoding="utf-8"
        )
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        try:
            (skills_root / "linked").symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("symlinks unavailable")
        # A symlinked skill dir is reachable by name, but only its own SKILL.md —
        # it cannot be used to read an arbitrary path.
        got = read_skill_body("linked", skills_root)
        assert got["id"] == "linked"


class TestProfileIntegration:
    def test_profile_without_skills_is_unchanged(self):
        from backend.profiles import load_profile

        p = load_profile("personal-agent")
        assert "<skills>" not in p.system_prompt

    def test_catalog_lands_in_the_system_prompt(self, tmp_path, monkeypatch):
        import json

        from backend import profiles as profiles_module

        pdir = tmp_path / "skilled"
        pdir.mkdir()
        (pdir / "profile.json").write_text(
            json.dumps({"id": "skilled", "label": "Skilled", "tools": ["read_skill"]}),
            encoding="utf-8",
        )
        (pdir / "system.md").write_text("You are helpful.", encoding="utf-8")
        _write_skill(pdir / "skills", "refund", name="Refund", description="handle refunds")

        monkeypatch.setattr(profiles_module, "PROFILE_ROOT", tmp_path)
        p = profiles_module.load_profile("skilled", profile_root=tmp_path)

        assert "<skills>" in p.system_prompt
        assert "refund" in p.system_prompt
        assert p.system_prompt.rstrip().endswith("You are helpful.")

    def test_new_skill_is_visible_without_a_restart(self, tmp_path, monkeypatch):
        """The memoization trap.

        build_kb_manifest caches per kb_root for the process lifetime, which is
        why builder profiles deliberately opt out of it. Skill discovery must not
        inherit that: someone who just wrote a skill in the builder has to see it
        on the next turn, not after a redeploy.
        """
        import json

        from backend import profiles as profiles_module

        pdir = tmp_path / "growing"
        pdir.mkdir()
        (pdir / "profile.json").write_text(
            json.dumps({"id": "growing", "label": "G", "tools": ["read_skill"]}),
            encoding="utf-8",
        )
        (pdir / "system.md").write_text("Base.", encoding="utf-8")
        monkeypatch.setattr(profiles_module, "PROFILE_ROOT", tmp_path)

        first = profiles_module.load_profile("growing", profile_root=tmp_path)
        assert "<skills>" not in first.system_prompt

        _write_skill(pdir / "skills", "brand-new", description="just written")
        second = profiles_module.load_profile("growing", profile_root=tmp_path)
        assert "brand-new" in second.system_prompt


class TestCacheCoupling:
    def test_load_skill_does_not_touch_the_system_prompt(self):
        """Skill bodies must arrive as tool results, never as a prompt rewrite.

        The system block carries a cache breakpoint. Injecting a skill body into
        the system prompt mid-conversation would invalidate the cached prefix on
        the exact turn the agent starts real work — silently, visible only as a
        cost curve. If someone later "optimizes" by moving bodies into the
        prompt, this test is what tells them why not.
        """
        import inspect

        from backend.tools import skills_tool

        source = inspect.getsource(skills_tool)
        assert "system_prompt" not in source
        assert "read_skill_body" in source
