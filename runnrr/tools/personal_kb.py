"""Personal-site KB tools: resume + curated project pitches.

These are NOT engine defaults. They encode the personal-agent KB's path
conventions (``resume/resume.md`` and ``projects/<slug>.md``), so they live
outside the generic KB toolset. They stay globally registered — any profile can
opt in by listing them in its ``profile.json`` ``tools`` — but a generic
business profile should never inherit them. See ``DEFAULT_PROFILE_TOOLS`` in
``runnrr/profiles.py``: it intentionally excludes these.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from runnrr.kb_loader import KBError, read_file
from runnrr.tools.definitions import ToolContext, ToolDef
from runnrr.tools.source_metadata import _label_from_slug, static_source_metadata


def get_resume_summary(*, root: Path | None = None) -> dict:
    """Specialized: return resume.md as if read_file was called on it."""
    return read_file("resume/resume.md", root=root)


def get_project_context(
    project_name: str,
    *,
    root: Path | None = None,
    aliases: dict[str, str] | None = None,
) -> dict:
    """Specialized: return the curated pitch summary for a named project.

    Tries the literal slug first (e.g., 'shuttrr' → projects/shuttrr.md), then
    profile-provided aliases for friendly names ('bryanzane.com' → bryanzane-com).
    """
    name = (project_name or "").lower().strip()
    if not name:
        raise KBError("project_name must not be empty")
    slug = (aliases or {}).get(name, name)
    rel = f"projects/{slug}.md"
    try:
        loaded = read_file(rel, root=root)
    except KBError:
        raise KBError(
            f"no project file for '{project_name}'. Try list_kb(subdir='projects') to see what's available."
        )
    return {"project": slug, "summary": loaded["content"]}


def project_context_metadata(
    arguments: dict[str, Any],
    out: Any,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    labels = context.profile.source_labels if context and context.profile else {}
    label = _label_from_slug(str((out or {}).get("project", "")), labels)
    return static_source_metadata(f"read {label}", label=label, kind="kb_read")


PERSONAL_KB_TOOL_DEFS: tuple[ToolDef, ...] = (
    ToolDef(
        name="get_resume_summary",
        description=(
            "Return the active profile's resume or candidate summary in markdown. "
            "Use for employment history, education, certifications, or overall "
            "qualifications when that profile includes resume data."
        ),
        input_schema={"type": "object", "properties": {}, "required": []},
        handler=lambda args, ctx: get_resume_summary(root=ctx.root),
        source_metadata=lambda args, out, ctx: static_source_metadata(
            "read Resume", label="Resume", kind="kb_read"
        ),
    ),
    ToolDef(
        name="get_project_context",
        description=(
            "Return a curated project summary for one active-profile project. Use when "
            "a visitor asks about a specific project or whether it is relevant to a "
            "role, domain, or use case."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": (
                        "Project name or slug, case-insensitive. Available projects "
                        "depend on the active profile's KB."
                    ),
                }
            },
            "required": ["project_name"],
        },
        handler=lambda args, ctx: get_project_context(
            args["project_name"],
            root=ctx.root,
            aliases=ctx.profile.project_aliases if ctx.profile else {},
        ),
        source_metadata=project_context_metadata,
    ),
)
