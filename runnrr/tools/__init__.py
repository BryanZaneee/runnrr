"""Tool schemas, results, and dispatch for Runnrr native tools.

Deliberately narrow: only the names other packages import from
``runnrr.tools`` itself. Everything else -- tool definitions, handlers,
the registry, source-metadata builders -- is imported from its owning
submodule (``runnrr.tools.registry``, ``runnrr.tools.sales``, ...).
"""
from __future__ import annotations

from runnrr.tools.dispatch import run_tool
from runnrr.tools.results import ToolResult
from runnrr.tools.schemas import SCHEMAS, schemas_for_tools

__all__ = [
    "SCHEMAS",
    "ToolResult",
    "run_tool",
    "schemas_for_tools",
]
