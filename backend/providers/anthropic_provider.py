"""Anthropic provider — streaming tool-use loop, mirroring notebook 003/009."""
from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic

from backend.config import PROVIDER_MAX_RETRIES, PROVIDER_TIMEOUT_SECONDS
from backend.profiles import AgentProfile
from backend.providers.base import Event
from backend.tools import ToolResult, schemas_for_tools
from backend.types import ProviderMessage, UsagePayload


# Anthropic is the only provider with a request-side cache control; OpenAI,
# DeepSeek, Kimi, and Gemini all cache implicitly with nothing to send. That
# asymmetry is why the provider itself is the gate here rather than a registry
# flag -- and it is the strongest argument against ever collapsing these three
# behind a single generic client, which would erase the lever entirely.
_EPHEMERAL = {"type": "ephemeral"}


class AnthropicProvider:
    def __init__(self, *, thinking_budget: int | None = None) -> None:
        self.client = AsyncAnthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            timeout=PROVIDER_TIMEOUT_SECONDS,
            # The SDK honours Retry-After on 429/5xx. There was no retry at any
            # level before, so a single rate-limit blip surfaced to the user as a
            # generic "model provider error".
            max_retries=PROVIDER_MAX_RETRIES,
        )
        # When set, enable extended thinking with this budget. The API requires
        # max_tokens > thinking.budget_tokens, so the stream call also bumps
        # max_tokens upward if the caller's value would underflow.
        self.thinking_budget = thinking_budget

    def format_user(self, text: str) -> ProviderMessage:
        return {"role": "user", "content": text}

    def append_tool_results(
        self, messages: list[ProviderMessage], results: list[ToolResult]
    ) -> None:
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r.tool_use_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    }
                    for r in results
                ],
            }
        )

    def tools_for_provider(self, profile: AgentProfile) -> list[dict]:
        """Tool schemas with a cache breakpoint on the last one.

        Anthropic caches by PREFIX, and the render order is tools -> system ->
        messages. A breakpoint on the final tool therefore caches the whole tool
        block. The block is deterministic per profile -- SCHEMAS is built once at
        import and schemas_for_tools preserves profile.tools order -- which is the
        property that makes this a cache READ on hop 2 rather than another write.
        Pinned by test_prefix_is_byte_stable.
        """
        schemas = schemas_for_tools(
            profile.tools,
            description_overrides=profile.tool_descriptions,
        )
        if schemas:
            schemas = [*schemas[:-1], {**schemas[-1], "cache_control": _EPHEMERAL}]
        return schemas

    def system_for_provider(self, profile: AgentProfile) -> Any:
        """System prompt as one cached block.

        Only two breakpoints are used (last tool, system) and deliberately none on
        messages. Messages are where instability creeps in -- switching profile or
        model resets session["messages"] entirely, and hop boundaries move -- and a
        breakpoint on an unstable prefix is worse than none: every turn becomes a
        cache WRITE instead of a read. Decide on a message breakpoint from the
        cache_creation vs cache_read numbers this PR makes trustworthy, not upfront.
        """
        return [
            {
                "type": "text",
                "text": profile.system_prompt,
                "cache_control": _EPHEMERAL,
            }
        ]

    async def stream(
        self,
        *,
        model: str,
        messages: list[ProviderMessage],
        system: Any,
        tools: list,
        max_tokens: int,
    ) -> AsyncIterator[Event]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "tools": tools,
        }
        if self.thinking_budget:
            # Anthropic requires max_tokens strictly greater than budget_tokens; reserve
            # at least 1024 tokens for the visible response so a tight MAX_TOKENS env
            # doesn't starve it.
            kwargs["max_tokens"] = max(max_tokens, self.thinking_budget + 1024)
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": self.thinking_budget}

        async with self.client.messages.stream(**kwargs) as stream:
            async for chunk in stream:
                if chunk.type == "text":
                    yield {"type": "text_delta", "text": chunk.text}
                elif chunk.type == "thinking":
                    yield {"type": "thinking_delta", "text": chunk.thinking}
                elif chunk.type == "content_block_start":
                    cb = getattr(chunk, "content_block", None)
                    if cb is not None and getattr(cb, "type", None) == "tool_use":
                        yield {"type": "tool_use_start", "name": cb.name}
            response = await stream.get_final_message()

        # The assistant turn (including tool_use blocks) must land in the message log
        # before the next turn's tool_result blocks. Otherwise the API rejects the next call.
        messages.append({"role": "assistant", "content": response.content})

        for block in response.content:
            if block.type == "tool_use":
                yield {
                    "type": "tool_use_complete",
                    "tool_use_id": block.id,
                    "name": block.name,
                    "arguments": block.input,
                }

        thinking_est = _estimate_thinking_tokens(
            response.content, getattr(response.usage, "output_tokens", 0) or 0
        )
        yield {"type": "usage", "usage": _norm_usage(response.usage, thinking_tokens=thinking_est)}
        yield {
            "type": "message_done",
            "stop_reason": "tool_use" if response.stop_reason == "tool_use" else "end_turn",
        }


def _estimate_thinking_tokens(content: list, total_output_tokens: int) -> int:
    # Anthropic doesn't expose per-block token counts and rolls thinking into the
    # cumulative output_tokens. Approximate the thinking share by character length
    # across thinking / text / tool_use blocks. Imperfect but stable, and the only
    # signal we have without re-tokenizing the response.
    if not total_output_tokens:
        return 0
    thinking_chars = 0
    other_chars = 0
    for block in content:
        btype = getattr(block, "type", None)
        if btype == "thinking":
            thinking_chars += len(getattr(block, "thinking", "") or "")
        elif btype == "text":
            other_chars += len(getattr(block, "text", "") or "")
        elif btype == "tool_use":
            other_chars += len(json.dumps(getattr(block, "input", {}) or {}))
    total = thinking_chars + other_chars
    if total == 0 or thinking_chars == 0:
        return 0
    return int(total_output_tokens * thinking_chars / total)


def _norm_usage(u: Any, thinking_tokens: int = 0) -> UsagePayload:
    # Anthropic streaming usage rolls extended-thinking tokens into output_tokens
    # without a per-stream split. When thinking_tokens is supplied (estimated from
    # content-block character lengths), expose it on reasoning_tokens and subtract
    # it from output_tokens so the two are disjoint and the frontend can sum them.
    output_total = getattr(u, "output_tokens", 0) or 0
    reasoning = max(0, min(thinking_tokens, output_total))

    # Anthropic is the only provider that reports input_tokens EXCLUDING cached
    # reads; OpenAI, Gemini, and DeepSeek all report the full prompt size with
    # the cached portion as a subset. Normalize to the majority so that
    # `cache_read <= input_tokens` holds everywhere and a cache-hit ratio means
    # the same thing on every provider. See backend/usage.py for the contract.
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    cache_creation = getattr(u, "cache_creation_input_tokens", 0) or 0
    return {
        "input_tokens": (getattr(u, "input_tokens", 0) or 0) + cache_read + cache_creation,
        "output_tokens": output_total - reasoning,
        "reasoning_tokens": reasoning,
        # Anthropic exposes no per-block token split, so reasoning_tokens above is
        # apportioned by character length rather than measured. Flag it: the same
        # field is a real API measurement on the other two providers.
        "reasoning_estimated": reasoning > 0,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation,
    }
