"""Tool schemas, results, and dispatch for EasyAgent native tools.

Deliberately narrow: only the names other packages import from
``backend.tools`` itself. Everything else -- tool definitions, handlers,
the registry, source-metadata builders -- is imported from its owning
submodule (``backend.tools.registry``, ``backend.tools.sales``, ...).
"""
from __future__ import annotations

from backend.tools.dispatch import run_tool
from backend.tools.results import ToolResult
from backend.tools.schemas import SCHEMAS, schemas_for_tools

__all__ = [
    "SCHEMAS",
    "ToolResult",
    "run_tool",
    "schemas_for_tools",
]
