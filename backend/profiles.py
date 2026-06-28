"""Agent profile loading.

Profiles keep persona and knowledge-base choices out of the reusable EasyAgent
engine. The bundled `personal-agent` example profile lives under
profiles/personal-agent/, but the engine can run another profile by loading a
different profile.json + system prompt.

The `mcp_servers` field on a profile is parsed and stored, but no MCP client is
wired up yet — that integration is a follow-up task. See backend/agent.py for
the planned shape.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from backend.config import DEFAULT_PROFILE, KB_ROOT, PROFILE_ROOT
from backend.kb_loader import iter_kb_files
from backend.types import BrandMetadata

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Generic defaults only. Personal-site shortcuts (get_resume_summary,
# get_project_context) live in backend/tools/personal_kb.py and must be opted
# into via a profile's "tools" list — they are deliberately NOT defaults so a
# business profile never inherits portfolio-specific tooling.
DEFAULT_PROFILE_TOOLS: tuple[str, ...] = (
    "list_kb",
    "read_file",
    "search_kb",
    "web_search",
)

# Caps for the optional KB manifest prepended to a profile's system prompt.
MANIFEST_MAX_FILES_PER_CATEGORY = 30
MANIFEST_MAX_TOP_LEVEL_FILES = 40


class ProfileConfigError(ValueError):
    """Raised when a profile's configuration is invalid (e.g. unknown tool names)."""


def _category_filenames(kb_root: Path, category: str) -> list[str]:
    """Return deduped, sorted basenames (no extension) of markdown files under a category."""
    seen: set[str] = set()
    for rel_path, _path in iter_kb_files(category, root=kb_root, pattern="*.md"):
        seen.add(Path(rel_path).stem)
    return sorted(seen, key=str.lower)


def _format_filenames(names: list[str], cap: int) -> str:
    if len(names) <= cap:
        return ", ".join(names)
    extra = len(names) - cap
    return ", ".join(names[:cap]) + f", +{extra} more"


_MANIFEST_CACHE: dict[str, str] = {}


def clear_manifest_cache() -> None:
    """Reset the KB-manifest cache.

    KB content is process-stable in prod (it changes only on deploy/rebuild,
    which restarts the service); tests reset it between cases via an autouse
    fixture.
    """
    _MANIFEST_CACHE.clear()


def build_kb_manifest(kb_root: Path) -> str:
    """Build a compact text index of categories + page names under `kb_root`.

    Top-level markdown files are listed under a single "Top-level" line. Each
    top-level subdirectory becomes one line listing the basenames of its
    markdown files (recursively, deduped). Long categories are truncated with a
    "+N more" suffix so the manifest stays bounded.

    Returns an empty string if the root has no readable content. Memoized per
    resolved kb_root for the process lifetime so large KBs (e.g. frampton, ~1.4k
    files) are not re-walked on every profile load; dev edits to KB markdown need
    a process restart to show up (uvicorn --reload restarts on .py changes only).
    """
    key = str(kb_root.resolve())
    cached = _MANIFEST_CACHE.get(key)
    if cached is not None:
        return cached
    manifest = _compute_kb_manifest(kb_root)
    _MANIFEST_CACHE[key] = manifest
    return manifest


def _compute_kb_manifest(kb_root: Path) -> str:
    kb_root = kb_root.resolve()
    if not kb_root.exists() or not kb_root.is_dir():
        return ""

    markdown_files = list(iter_kb_files(root=kb_root, pattern="*.md"))
    top_files = sorted(
        (Path(rel_path).stem
        for rel_path, _path in markdown_files
        if len(Path(rel_path).parts) == 1),
        key=str.lower,
    )
    subdirs = sorted(
        {
            Path(rel_path).parts[0]
            for rel_path, _path in markdown_files
            if len(Path(rel_path).parts) > 1
        },
        key=str.lower,
    )

    lines: list[str] = []
    if top_files:
        lines.append("Top-level: " + _format_filenames(top_files, MANIFEST_MAX_TOP_LEVEL_FILES))
    for category in subdirs:
        files = _category_filenames(kb_root, category)
        if not files:
            continue
        lines.append(
            f"{category}/: " + _format_filenames(files, MANIFEST_MAX_FILES_PER_CATEGORY)
        )

    if not lines:
        return ""
    return "<knowledge_base_index>\n" + "\n".join(lines) + "\n</knowledge_base_index>"


@dataclass(frozen=True)
class AgentProfile:
    id: str
    label: str
    description: str
    kb_root: Path
    system_prompt: str
    welcome: str = ""
    suggestions: tuple[str, ...] = ()
    tools: tuple[str, ...] = DEFAULT_PROFILE_TOOLS
    tool_descriptions: dict[str, str] = field(default_factory=dict)
    brand: BrandMetadata = field(default_factory=dict)
    data_root: Path | None = None
    mcp_servers: tuple[dict, ...] = ()
    project_aliases: dict[str, str] = field(default_factory=dict)
    source_labels: dict[str, str] = field(default_factory=dict)
    # Ordered (match, label) pairs mapping KB paths to public source labels.
    # A match ending in "/" is a prefix match; otherwise an exact-path match.
    # Tried in declared order, first match wins, so list exact paths before
    # the prefixes they fall under. Case-sensitive (unlike source_labels).
    source_path_labels: tuple[tuple[str, str], ...] = ()


def _project_path(value: str | None, fallback: Path) -> Path:
    if not value:
        return fallback.resolve()
    p = Path(value)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()


def _brand_metadata(value: Any) -> BrandMetadata:
    """Parse profile brand metadata while keeping the public shape dict-like."""
    return cast(BrandMetadata, dict(value or {}))


def _validate_tool_names(tools: tuple[str, ...], *, profile_id: str) -> None:
    """Reject unknown tool names so a typo in profile.json fails loudly, not silently.

    The import is deferred because backend.tools -> ... -> backend.rag.tools imports
    this module, so importing it at module scope would close an import cycle. An empty
    tools tuple is valid (e.g. closed-book / non-KB profiles).
    """
    from backend.tools.schemas import DEFAULT_TOOL_NAMES

    known = set(DEFAULT_TOOL_NAMES)
    unknown = [name for name in tools if name not in known]
    if unknown:
        raise ProfileConfigError(
            f"profile '{profile_id}' lists unknown tool(s): "
            f"{', '.join(sorted(unknown))}. "
            f"Valid tools: {', '.join(sorted(known))}."
        )


def profile_from_config(
    cfg: dict[str, Any],
    *,
    system_prompt: str,
    kb_root: Path,
    data_root: Path | None,
    profile_id: str,
) -> AgentProfile:
    """Build an AgentProfile from a parsed config dict plus already-resolved paths.

    Shared by the filesystem loader (load_profile) and any other source that holds
    the same shape as profile.json — e.g. a per-tenant DB row whose `config` jsonb
    stores the profile. Path/system-prompt resolution differs by source, so callers
    pass `system_prompt`, `kb_root`, and `data_root` already resolved; everything
    else (tools, brand, source labels, mcp) is derived here so both paths stay in
    sync and tool names are validated the same way.
    """
    tools = tuple(cfg.get("tools", DEFAULT_PROFILE_TOOLS))
    _validate_tool_names(tools, profile_id=profile_id)

    return AgentProfile(
        id=cfg.get("id", profile_id),
        label=cfg.get("label", profile_id.title()),
        description=cfg.get("description", ""),
        kb_root=kb_root,
        system_prompt=system_prompt,
        welcome=cfg.get("welcome", ""),
        suggestions=tuple(cfg.get("suggestions", ())),
        tools=tools,
        tool_descriptions=dict(cfg.get("tool_descriptions", {})),
        brand=_brand_metadata(cfg.get("brand", {})),
        data_root=data_root,
        mcp_servers=tuple(cfg.get("mcp_servers", ())),
        project_aliases={
            str(k).lower(): str(v)
            for k, v in dict(cfg.get("project_aliases", {})).items()
        },
        source_labels={
            str(k).lower(): str(v)
            for k, v in dict(cfg.get("source_labels", {})).items()
        },
        source_path_labels=tuple(
            (str(pair[0]), str(pair[1]))
            for pair in cfg.get("source_path_labels", [])
            if isinstance(pair, (list, tuple)) and len(pair) == 2
        ),
    )


def load_profile(
    profile_id: str | None = None,
    *,
    profile_root: Path | None = None,
) -> AgentProfile:
    """Load a profile by id. Missing profile.json is an explicit configuration error."""
    pid = profile_id or DEFAULT_PROFILE
    root = (profile_root or PROFILE_ROOT).resolve()
    profile_dir = (root / pid).resolve()
    cfg_path = profile_dir / "profile.json"

    if not cfg_path.exists():
        raise FileNotFoundError(cfg_path)

    cfg: dict[str, Any] = json.loads(cfg_path.read_text(encoding="utf-8"))
    system_path = _project_path(cfg.get("system_prompt_path"), profile_dir / "system.md")
    system_prompt = system_path.read_text(encoding="utf-8").strip()
    kb_root = _project_path(cfg.get("kb_root"), KB_ROOT)
    if cfg.get("inject_kb_manifest"):
        manifest = build_kb_manifest(kb_root)
        if manifest:
            system_prompt = manifest + "\n\n" + system_prompt
    data_root = (
        _project_path(cfg.get("data_root"), profile_dir / "data")
        if cfg.get("data_root")
        else None
    )

    return profile_from_config(
        cfg,
        system_prompt=system_prompt,
        kb_root=kb_root,
        data_root=data_root,
        profile_id=pid,
    )
