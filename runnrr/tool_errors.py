"""Shared tool-layer exceptions."""
from __future__ import annotations


class ToolExecutionError(Exception):
    """Raised when a non-KB tool rejects input or cannot complete safely."""
