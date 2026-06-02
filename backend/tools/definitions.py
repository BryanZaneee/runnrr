"""Shared native tool definition types."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from backend.profiles import AgentProfile


@dataclass(frozen=True)
class ToolContext:
    root: Path | None = None
    data_root: Path | None = None
    profile: AgentProfile | None = None


ToolHandler = Callable[[dict[str, Any], ToolContext], Any]
# Builders receive the same ToolContext as handlers, so KB builders can read
# profile.source_labels / profile.source_path_labels; non-KB builders ignore it.
SourceMetadataBuilder = Callable[[dict[str, Any], Any, ToolContext], dict[str, Any]]


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    source_metadata: SourceMetadataBuilder

    @property
    def schema(self) -> dict[str, Any]:
        """Return the Anthropic-shaped schema consumed by provider adapters."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
