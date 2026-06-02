"""Knowledge-base native tool definitions."""
from __future__ import annotations

from typing import Any

from backend.kb_loader import (
    list_kb,
    read_file,
    search_kb,
)
from backend.tools.definitions import ToolContext, ToolDef
from backend.tools.source_metadata import (
    list_kb_metadata,
    read_file_metadata,
    search_kb_metadata,
)


def _handle_list_kb(arguments: dict[str, Any], ctx: ToolContext) -> Any:
    return list_kb(arguments.get("subdir", ""), root=ctx.root)


def _handle_read_file(arguments: dict[str, Any], ctx: ToolContext) -> Any:
    return read_file(
        arguments["path"],
        arguments.get("start_line", 1),
        arguments.get("end_line"),
        root=ctx.root,
    )


def _handle_search_kb(arguments: dict[str, Any], ctx: ToolContext) -> Any:
    return search_kb(
        arguments["query"],
        regex=arguments.get("regex", False),
        subdir=arguments.get("subdir", ""),
        max_results=arguments.get("max_results", 20),
        root=ctx.root,
    )


KB_TOOL_DEFS: tuple[ToolDef, ...] = (
    ToolDef(
        name="list_kb",
        description=(
            "List files under the active profile's knowledge base, optionally filtered by "
            "a subdirectory. Returns relative paths so they can be passed to read_file. "
            "Empty subdir lists top-level entries only (categories). Pass an explicit "
            "subdir like 'Bosses' or 'projects' to drill in one level. Prefer the "
            "manifest already embedded in the system prompt over calling this."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "subdir": {
                    "type": "string",
                    "description": (
                        "Relative subdirectory under the KB root (e.g. 'projects', "
                        "'codebases'). Empty string lists top-level entries only."
                    ),
                }
            },
            "required": ["subdir"],
        },
        handler=_handle_list_kb,
        source_metadata=list_kb_metadata,
    ),
    ToolDef(
        name="read_file",
        description=(
            "Read a single file from the active profile's knowledge base by relative "
            "path. Files are usually markdown pages or repomix XML codebase dumps. "
            "Default returns the first 400 lines (~16KB). For longer pages, pass "
            "start_line/end_line. Returns {path, lines: 'X-Y of Z', content} so you "
            "know exactly what you did not see and can request more with a follow-up call."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative path under the KB root, e.g. 'guide/intro.md' "
                        "or 'data/reference.xml'."
                    ),
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional 1-indexed start line (default 1).",
                },
                "end_line": {
                    "type": "integer",
                    "description": (
                        "Optional 1-indexed end line, inclusive. Default: start+399. "
                        "Hard cap: start+2999."
                    ),
                },
            },
            "required": ["path"],
        },
        handler=_handle_read_file,
        source_metadata=read_file_metadata,
    ),
    ToolDef(
        name="search_kb",
        description=(
            "Search the active profile's knowledge base for a substring or regex match. "
            "Returns matching file paths with up to 3 lines of context per match "
            "(240 char cap). Use to find which file mentions a topic before you "
            "read_file. Defaults to case-insensitive substring; pass regex=true for regex."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "regex": {"type": "boolean", "default": False},
                "subdir": {"type": "string", "default": ""},
                "max_results": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
        handler=_handle_search_kb,
        source_metadata=search_kb_metadata,
    ),
)
