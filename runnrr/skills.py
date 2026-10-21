"""Profile skills: catalog in the prompt, bodies and references as tool results.

Tool results preserve the cached system prefix. Frontmatter accepts only flat
name/description strings; richer instructions belong in the Markdown body.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("runnrr.skills")

MAX_DESCRIPTION_CHARS = 200
# Bound the cached prompt prefix even for large skill collections.
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
