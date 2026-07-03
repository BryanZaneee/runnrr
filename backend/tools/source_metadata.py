"""Source metadata helpers for tool results."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from backend.tools.definitions import ToolContext

MAX_PUBLIC_SOURCE_ITEMS = 5


def _profile_labels(
    context: ToolContext | None,
) -> tuple[Mapping[str, str], Sequence[tuple[str, str]]]:
    """Pull (source_labels, source_path_labels) off the active profile, if any."""
    profile = context.profile if context else None
    if profile is None:
        return {}, ()
    return profile.source_labels, profile.source_path_labels


def unavailable_metadata() -> dict[str, Any]:
    return {
        "source_summary": "source unavailable",
        "source_items": [],
        "source_count": 0,
        "hidden_count": 0,
    }


def default_metadata() -> dict[str, Any]:
    return {
        "source_summary": "used tool",
        "source_items": [],
        "source_count": 0,
        "hidden_count": 0,
    }


def _clean_label(label: str, fallback: str = "Knowledge base source") -> str:
    """Return a browser-safe source label with no path separators or control chars."""
    label = re.sub(r"[/\\]+", " ", str(label or ""))
    label = "".join(ch for ch in label if ch.isprintable())
    label = re.sub(r"\s+", " ", label).strip()
    if not label:
        return fallback
    return label[:80]


def _label_from_slug(slug: str, labels: Mapping[str, str] | None = None) -> str:
    """Convert a project slug into display text using profile labels when present."""
    slug = str(slug or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,80}", slug):
        return "Project knowledge base"
    if labels and slug in labels:
        return f"Project: {labels[slug]}"
    return f"Project: {slug.replace('-', ' ').title()}"


def _match_path_label(path: str, path_labels: Sequence[tuple[str, str]] | None) -> str | None:
    """Return the first profile path-label whose match applies to `path`.

    A match ending in "/" is a prefix match; otherwise an exact-path match.
    Pairs are tried in declared order so exact paths can precede prefixes.
    """
    for match, label in path_labels or ():
        if match.endswith("/"):
            if path.startswith(match):
                return label
        elif path == match:
            return label
    return None


def label_from_kb_path(
    path: str,
    labels: Mapping[str, str] | None = None,
    path_labels: Sequence[tuple[str, str]] | None = None,
) -> str:
    """Public wrapper around the KB-path → display-label mapper."""
    return _label_from_kb_path(path, labels, path_labels)


def _label_from_kb_path(
    path: str,
    labels: Mapping[str, str] | None = None,
    path_labels: Sequence[tuple[str, str]] | None = None,
) -> str:
    """Map an internal KB path to a sanitized public category label.

    Profile-supplied `source_path_labels` win first, so business taxonomies stay
    in profile config. The engine keeps only data-derived generic conventions:
    INDEX.md, the projects/<slug> -> "Project: <Title>" transform, and a fallback.
    """
    path = str(path or "")
    profile_label = _match_path_label(path, path_labels)
    if profile_label:
        return profile_label
    if path == "INDEX.md":
        return "Knowledge base index"
    if path.startswith("projects/"):
        stem = Path(path).stem
        return _label_from_slug(stem, labels)
    return "Knowledge base document"


def _source_item(label: str, kind: str) -> dict[str, str]:
    return {"label": _clean_label(label), "kind": _clean_label(kind, "kb_read")}


def _unique_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for item in items:
        key = (item["label"], item["kind"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _cap_items(items: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    return items[:MAX_PUBLIC_SOURCE_ITEMS], max(0, len(items) - MAX_PUBLIC_SOURCE_ITEMS)


def _kb_search_metadata(
    matches: Any,
    *,
    kind: str,
    verb: str,
    labels: Mapping[str, str] | None = None,
    path_labels: Sequence[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    matches = matches if isinstance(matches, list) else []
    items = _unique_items([
        _source_item(_label_from_kb_path(str(item.get("path", "")), labels, path_labels), kind)
        for item in matches
        if isinstance(item, dict)
    ])
    visible, hidden = _cap_items(items)
    match_label = "match" if len(matches) == 1 else "matches"
    source_label = "source" if len(items) == 1 else "sources"
    return {
        "source_summary": f"{verb} {len(items)} {source_label}, {len(matches)} {match_label}",
        "source_items": visible,
        "source_count": len(items),
        "hidden_count": hidden,
    }


def _public_domain(url: str) -> str | None:
    parsed = urlparse(str(url or ""))
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or "/" in host or "\\" in host:
        return None
    return host[:80]


def static_source_metadata(
    source_summary: str,
    *,
    label: str,
    kind: str,
    source_count: int = 1,
) -> dict[str, Any]:
    return {
        "source_summary": source_summary,
        "source_items": [_source_item(label, kind)],
        "source_count": source_count,
        "hidden_count": 0,
    }


def read_file_metadata(
    arguments: dict[str, Any],
    out: Any,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    labels, path_labels = _profile_labels(context)
    label = _label_from_kb_path(str((out or {}).get("path", "")), labels, path_labels)
    return static_source_metadata(f"read {label}", label=label, kind="kb_read")


def search_kb_metadata(
    arguments: dict[str, Any],
    out: Any,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    labels, path_labels = _profile_labels(context)
    return _kb_search_metadata(
        out, kind="kb_search", verb="searched", labels=labels, path_labels=path_labels
    )


def semantic_search_metadata(
    arguments: dict[str, Any],
    out: Any,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    labels, path_labels = _profile_labels(context)
    meta = _kb_search_metadata(
        out,
        kind="kb_semantic_search",
        verb="semantic searched",
        labels=labels,
        path_labels=path_labels,
    )
    trace_results = (
        context.scratch.get("rag_trace_results") if context is not None else None
    )
    if trace_results:
        meta["rag_trace"] = {
            "entries": [
                {
                    "label": _clean_label(
                        _label_from_kb_path(r.chunk.path, labels, path_labels)
                    ),
                    "score": round(r.score, 4),
                    "bm25_score": round(r.bm25_score, 3)
                    if r.bm25_score is not None
                    else None,
                    "bm25_rank": r.bm25_rank,
                    "vector_score": round(r.vector_score, 4)
                    if r.vector_score is not None
                    else None,
                    "vector_rank": r.vector_rank,
                }
                for r in trace_results
            ]
        }
    return meta


def list_kb_metadata(
    arguments: dict[str, Any],
    out: Any,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    count = len(out) if isinstance(out, list) else 0
    entry_label = "entry" if count == 1 else "entries"
    return {
        "source_summary": f"listed {count} knowledge-base {entry_label}",
        "source_items": [_source_item("Knowledge base index", "kb_list")],
        "source_count": count,
        "hidden_count": 0,
    }


def web_search_metadata(
    arguments: dict[str, Any],
    out: Any,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    results = (out or {}).get("results", []) if isinstance(out, dict) else []
    items = []
    for result in results:
        if not isinstance(result, dict):
            continue
        domain = _public_domain(result.get("url", ""))
        items.append(_source_item(f"Web result: {domain}" if domain else "Web result", "web"))
    items = _unique_items(items)
    visible, hidden = _cap_items(items)
    result_label = "result" if len(results) == 1 else "results"
    return {
        "source_summary": f"searched public web, {len(results)} {result_label}",
        "source_items": visible,
        "source_count": len(results),
        "hidden_count": hidden,
    }


def fetch_url_text_metadata(
    arguments: dict[str, Any],
    out: Any,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    domain = _public_domain(str((out or {}).get("url", ""))) if isinstance(out, dict) else None
    label = f"Public web page: {domain}" if domain else "Public web page"
    return static_source_metadata(
        "fetched public web page",
        label=label,
        kind="web_fetch",
    )


def catalog_lookup_metadata(
    arguments: dict[str, Any],
    out: Any,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    matches = (out or {}).get("matches", []) if isinstance(out, dict) else []
    count = len(matches)
    package_label = "package" if count == 1 else "packages"
    return {
        "source_summary": f"searched product catalog, {count} {package_label}",
        "source_items": [_source_item("Product catalog", "catalog")],
        "source_count": count,
        "hidden_count": 0,
    }
