"""Tool schemas, results, and dispatch for EasyAgent native tools."""
from __future__ import annotations

from backend.tool_errors import ToolExecutionError
from backend.tools.calculator import calculator
from backend.tools.definitions import ToolContext, ToolDef, ToolHandler
from backend.tools.dispatch import (
    run_tool,
)
from backend.tools.registry import TOOL_DEFS, TOOL_DEFS_BY_NAME, TOOL_HANDLERS
from backend.tools.results import ToolResult
from backend.tools.sales import (
    catalog_lookup,
    checkout_link_preview,
    lead_capture_preview,
    qualify_lead,
)
from backend.tools.schemas import (
    DEFAULT_TOOL_NAMES,
    SCHEMAS,
    SCHEMAS_BY_NAME,
    schemas_for_tools,
)
from backend.tools.web_fetch import fetch_url_text, httpx, socket

__all__ = [
    "DEFAULT_TOOL_NAMES",
    "SCHEMAS",
    "SCHEMAS_BY_NAME",
    "TOOL_DEFS",
    "TOOL_DEFS_BY_NAME",
    "TOOL_HANDLERS",
    "ToolContext",
    "ToolDef",
    "ToolExecutionError",
    "ToolHandler",
    "ToolResult",
    "calculator",
    "catalog_lookup",
    "checkout_link_preview",
    "fetch_url_text",
    "httpx",
    "lead_capture_preview",
    "qualify_lead",
    "run_tool",
    "schemas_for_tools",
    "socket",
]
