"""Plain-English skills: `<profile>/skills/<slug>/SKILL.md`.

A skill is how someone who does not write Python teaches an agent to *do*
something. Knowledge notes are facts the agent knows; a skill is a procedure it
follows. Both are markdown, neither involves JSON or a schema.

Progressive disclosure, three tiers
-----------------------------------
1. **Discovery** — a catalog of `name: description` lines goes into the system
   prompt. One line per skill, so a hundred skills cost a hundred lines rather
   than a hundred bodies.
2. **Activation** — the model calls `read_skill` and the full body comes back as
   a tool result.
3. **Reference** — anything else in the skill folder is reachable with the
   existing `read_file`.

Why the body arrives as a tool result and never as a prompt rewrite
-------------------------------------------------------------------
The system block carries a cache breakpoint. Injecting a skill body into the
system prompt mid-conversation would invalidate the cached prefix on the exact
turn the agent starts doing real work — and that failure is silent, visible only
as a cost and latency curve. Tool results land in the append-only message tail
instead, where they are free. Pinned by
`test_load_skill_does_not_touch_the_system_prompt`.

The frontmatter parser handles two string keys and nothing else. That is not an
oversight: it keeps the format authorable by hand and avoids a YAML dependency
for `name` and `description`. Anything richer belongs in the body.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("easyagent.skills")

MAX_DESCRIPTION_CHARS = 200
# The catalog sits inside the cached prompt prefix, so it is stable and cheap —
# but it is not free, and an unbounded one would re-inflate the very prefix the
# caching work exists to shrink.
MAX_CATALOG_CHARS = 8000


@dataclass(frozen=True)
class Skill:
    slug: str
    name: str
    description: str
    path: Path


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split `---`-delimited `key: value` frontmatter from the body.

    Deliberately minimal: flat string values only, no lists, no nesting, no YAML
    dependency. A file with no frontmatter returns `({}, text)` rather than
    raising, so a half-written skill degrades to "unlisted" instead of breaking
    profile load.
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta, parts[2].lstrip("\n")


def discover_skills(skills_root: Path | None) -> tuple[Skill, ...]:
    """Scan `<skills_root>/<slug>/SKILL.md`. Never raises; a bad skill is skipped.

    Sorted by slug so the catalog is byte-stable across calls — the prompt prefix
    depends on it.
    """
    if skills_root is None or not skills_root.is_dir():
        return ()

    found: list[Skill] = []
    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            meta, _ = _parse_frontmatter(skill_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            log.warning("skipping unreadable skill %s: %s", entry.name, exc)
            continue

        description = meta.get("description", "").strip()
        if not description:
            # Without a description the model has nothing to match on and would
            # never call read_skill, so listing it would only cost prompt tokens.
            log.warning("skipping skill %s: no description in frontmatter", entry.name)
            continue

        found.append(
            Skill(
                slug=entry.name,
                name=meta.get("name", "").strip() or entry.name,
                description=description[:MAX_DESCRIPTION_CHARS],
                path=skill_file,
            )
        )
    return tuple(found)


def build_skill_catalog(skills: tuple[Skill, ...]) -> str:
    """Render the tier-1 catalog block prepended to the system prompt."""
    if not skills:
        return ""
    lines = [
        "<skills>",
        "Procedures you can follow. Call read_skill with the id to get the full steps.",
    ]
    used = 0
    listed = 0
    for skill in skills:
        line = f"- {skill.slug}: {skill.name} — {skill.description}"
        if used + len(line) > MAX_CATALOG_CHARS:
            lines.append(f"- (+{len(skills) - listed} more not shown)")
            break
        lines.append(line)
        used += len(line)
        listed += 1
    lines.append("</skills>")
    return "\n".join(lines)


def read_skill_body(slug: str, skills_root: Path | None) -> dict:
    """Return one skill's full body. Confined to `skills_root` by construction.

    `slug` is matched against discovered directory names rather than joined into
    a path, so traversal is impossible here — there is no attacker-controlled
    path arithmetic to get wrong.
    """
    if not isinstance(slug, str) or not slug.strip():
        raise SkillError("skill id must be a non-empty string")

    for skill in discover_skills(skills_root):
        if skill.slug == slug.strip():
            _, body = _parse_frontmatter(skill.path.read_text(encoding="utf-8"))
            return {"id": skill.slug, "name": skill.name, "steps": body.strip()}

    raise SkillError(f"no skill named {slug!r}")


class SkillError(RuntimeError):
    """Raised when a skill cannot be read. Surfaced to the model as a tool error."""
