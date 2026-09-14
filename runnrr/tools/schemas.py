"""Shared tool schemas derived from the native tool registry."""
from __future__ import annotations

from copy import deepcopy
from typing import Mapping

from runnrr.tools.registry import TOOL_DEFS

SCHEMAS: list[dict] = [tool.schema for tool in TOOL_DEFS]
SCHEMAS_BY_NAME: dict[str, dict] = {schema["name"]: schema for schema in SCHEMAS}
DEFAULT_TOOL_NAMES: tuple[str, ...] = tuple(SCHEMAS_BY_NAME)


def schemas_for_tools(
    tool_names: tuple[str, ...] | list[str] | None = None,
    *,
    description_overrides: Mapping[str, str] | None = None,
) -> list[dict]:
    """Return Anthropic-shaped schemas for a profile's allowed tool names."""
    names = tuple(tool_names or DEFAULT_TOOL_NAMES)
    schemas: list[dict] = []
    for name in names:
        schema = SCHEMAS_BY_NAME.get(name)
        if schema is None:
            continue
        if description_overrides and name in description_overrides:
            schema = deepcopy(schema)
            schema["description"] = description_overrides[name]
        schemas.append(schema)
    return schemas
