"""Normalized tool result envelope."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from runnrr.tools.definitions import ToolContext
from runnrr.tools.registry import metadata_for_tool

@dataclass
class ToolResult:
    """Normalized tool result. Providers convert this to their wire format."""

    tool_use_id: str
    name: str
    content: str  # JSON string passed back to the model
    is_error: bool = False
    source_summary: str = ""
    source_items: list[dict[str, str]] = field(default_factory=list)
    source_count: int = 0
    hidden_count: int = 0
    rag_trace: dict | None = None
    duration_ms: int | None = None


def _tool_result(
    *,
    tool_use_id: str,
    name: str,
    content: str,
    is_error: bool,
    arguments: dict | None = None,
    output: Any = None,
    context: ToolContext | None = None,
) -> ToolResult:
    meta = metadata_for_tool(
        name,
        arguments or {},
        output,
        is_error=is_error,
        context=context,
    )
    rag_trace = meta.pop("rag_trace", None)
    return ToolResult(
        tool_use_id=tool_use_id,
        name=name,
        content=content,
        is_error=is_error,
        rag_trace=rag_trace,
        **meta,
    )
