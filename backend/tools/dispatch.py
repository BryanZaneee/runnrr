"""Tool dispatch envelope."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from backend import config
from backend.kb_loader import KBError
from backend.profiles import AgentProfile
from backend.tool_errors import ToolExecutionError
from backend.tools.definitions import ToolContext
from backend.tools.registry import TOOL_HANDLERS
from backend.tools.results import ToolResult, _tool_result
from backend.web_search import WebSearchError

log = logging.getLogger("easyagent.tools")


def _run_tool_inner(
    name: str,
    arguments: dict,
    tool_use_id: str,
    *,
    root: Path | None = None,
    data_root: Path | None = None,
    profile: AgentProfile | None = None,
    allowed_tools: tuple[str, ...] | list[str] | set[str] | None = None,
) -> ToolResult:
    """Dispatch a tool call. Catches expected tool errors into `is_error=True`."""
    context = ToolContext(root=root, data_root=data_root, profile=profile)
    try:
        if allowed_tools is not None and name not in set(allowed_tools):
            return _tool_result(
                tool_use_id=tool_use_id,
                name=name,
                content=json.dumps({"error": f"tool not enabled for this profile: {name}"}),
                is_error=True,
                arguments=arguments,
                context=context,
            )
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return _tool_result(
                tool_use_id=tool_use_id,
                name=name,
                content=json.dumps({"error": f"unknown tool: {name}"}),
                is_error=True,
                arguments=arguments,
                context=context,
            )
        if "_raw_arguments" in arguments:
            # Sentinel from a provider that could not JSON-decode the streamed
            # tool arguments (see _parse_arguments in openai_compat_provider.py).
            # Without this check the handler fails with a misleading
            # "missing required argument" message.
            return _tool_result(
                tool_use_id=tool_use_id,
                name=name,
                content=json.dumps(
                    {"error": "tool arguments were not valid JSON; retry with well-formed JSON arguments"}
                ),
                is_error=True,
                arguments=arguments,
                context=context,
            )
        out = handler(arguments, context)
        return _tool_result(
            tool_use_id=tool_use_id,
            name=name,
            content=json.dumps(out, ensure_ascii=False),
            is_error=False,
            arguments=arguments,
            output=out,
            context=context,
        )
    except (KBError, WebSearchError, ToolExecutionError) as e:
        return _tool_result(
            tool_use_id=tool_use_id,
            name=name,
            content=json.dumps({"error": str(e)}),
            is_error=True,
            arguments=arguments,
            context=context,
        )
    except KeyError as e:
        return _tool_result(
            tool_use_id=tool_use_id,
            name=name,
            content=json.dumps({"error": f"missing required argument: {e.args[0]}"}),
            is_error=True,
            arguments=arguments,
            context=context,
        )
    except Exception as e:
        log.exception("tool %s failed unexpectedly", name)
        if config.TOOL_DEBUG_ERRORS:
            raise
        return _tool_result(
            tool_use_id=tool_use_id,
            name=name,
            content=json.dumps({"error": "tool failed unexpectedly"}),
            is_error=True,
            arguments=arguments,
            context=context,
        )


def run_tool(
    name: str,
    arguments: dict,
    tool_use_id: str,
    *,
    root: Path | None = None,
    data_root: Path | None = None,
    profile: AgentProfile | None = None,
    allowed_tools: tuple[str, ...] | list[str] | set[str] | None = None,
) -> ToolResult:
    """Dispatch a tool call and stamp how long it took.

    Timing lives here rather than at the call site so every caller — the agent
    loop, evals, anything later — gets it for free. Tools are the dominant
    source of turn latency and were previously not timed at all. The dispatch
    itself is `_run_tool_inner`; it has many return paths, so wrapping is
    smaller and less error-prone than stamping each one.
    """
    started = time.perf_counter()
    result = _run_tool_inner(
        name,
        arguments,
        tool_use_id,
        root=root,
        data_root=data_root,
        profile=profile,
        allowed_tools=allowed_tools,
    )
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return result
