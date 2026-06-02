"""Provider-agnostic Event shape + LLMProvider Protocol.

The agent loop only sees normalized Events. Each concrete provider (Anthropic,
OpenAI/Moonshot) translates its native wire format into these Events.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Literal, Protocol, TypedDict

from backend.profiles import AgentProfile
from backend.tools import ToolResult
from backend.types import ProviderMessage, UsagePayload


class Event(TypedDict, total=False):
    type: Literal[
        "text_delta",
        "thinking_delta",
        "tool_use_start",
        "tool_use_complete",
        "message_done",
        "usage",
        "error",
    ]
    text: str
    tool_use_id: str
    name: str
    arguments: dict
    stop_reason: Literal["end_turn", "tool_use"]
    usage: UsagePayload


class LLMProvider(Protocol):
    async def stream(
        self,
        *,
        model: str,
        messages: list[ProviderMessage],
        system: Any,
        tools: list,
        max_tokens: int,
    ) -> AsyncIterator[Event]:
        """Stream an assistant turn. Mutates `messages` to append the assistant turn before
        yielding `tool_use_complete` events (so a subsequent `append_tool_results` call
        produces a valid message log for the next turn)."""
        ...

    def format_user(self, text: str) -> ProviderMessage: ...

    def append_tool_results(
        self, messages: list[ProviderMessage], results: list[ToolResult]
    ) -> None: ...

    def tools_for_provider(self, profile: AgentProfile) -> list[dict]: ...

    def system_for_provider(self, profile: AgentProfile) -> Any: ...
