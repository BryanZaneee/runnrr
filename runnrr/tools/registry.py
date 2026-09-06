"""Native tool registry assembled from domain-owned tool definitions."""
from __future__ import annotations

from typing import Any

from runnrr.rag.tools import build_semantic_search_tool
from runnrr.tools.calculator import CALCULATOR_TOOL
from runnrr.tools.definitions import ToolContext, ToolDef, ToolHandler
from runnrr.tools.kb import KB_TOOL_DEFS
from runnrr.tools.personal_kb import PERSONAL_KB_TOOL_DEFS
from runnrr.tools.sales import SALES_TOOL_DEFS
from runnrr.tools.skills_tool import READ_SKILL_TOOL
from runnrr.tools.source_metadata import default_metadata, unavailable_metadata
from runnrr.tools.web_fetch import FETCH_URL_TEXT_TOOL
from runnrr.tools.web_search_tool import WEB_SEARCH_TOOL

# Built via factory so runnrr.rag.tools carries no module-level runnrr.tools
# import (avoids the registry <-> rag.tools circular import when the RAG CLI
# imports runnrr.rag.tools first). By here, registry's own imports are loaded.
SEMANTIC_SEARCH_TOOL: ToolDef = build_semantic_search_tool()

TOOL_DEFS: tuple[ToolDef, ...] = (
    *KB_TOOL_DEFS,
    *PERSONAL_KB_TOOL_DEFS,
    SEMANTIC_SEARCH_TOOL,
    WEB_SEARCH_TOOL,
    FETCH_URL_TEXT_TOOL,
    CALCULATOR_TOOL,
    READ_SKILL_TOOL,
    *SALES_TOOL_DEFS,
)
TOOL_DEFS_BY_NAME: dict[str, ToolDef] = {tool.name: tool for tool in TOOL_DEFS}
TOOL_HANDLERS: dict[str, ToolHandler] = {
    name: tool.handler for name, tool in TOOL_DEFS_BY_NAME.items()
}


def metadata_for_tool(
    name: str,
    arguments: dict[str, Any],
    output: Any,
    *,
    is_error: bool,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    """Build browser-safe metadata from the registered tool definition."""
    if is_error:
        return unavailable_metadata()
    tool = TOOL_DEFS_BY_NAME.get(name)
    if tool is None:
        return default_metadata()
    return tool.source_metadata(arguments, output, context or ToolContext())
