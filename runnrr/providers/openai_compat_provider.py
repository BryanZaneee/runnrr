"""OpenAI-compatible chat-completions provider.

This covers OpenAI proper and Moonshot/Kimi because Kimi exposes an
OpenAI-compatible /chat/completions API for function tools.
"""
from __future__ import annotations

import json
import os
import logging
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from runnrr.config import PROVIDER_MAX_RETRIES, PROVIDER_TIMEOUT_SECONDS
from runnrr.profiles import AgentProfile
from runnrr.providers.base import Event
from runnrr.tools import ToolResult, schemas_for_tools
from runnrr.types import ProviderMessage, UsagePayload

log = logging.getLogger("runnrr.providers.openai_compat")


class OpenAICompatProvider:
    def __init__(
        self,
        *,
        api_key_env: str,
        base_url: str | None = None,
        token_param: str = "max_completion_tokens",
        stream_options: bool = True,
        include_tool_result_name: bool = False,
        extra_body: dict | None = None,
        reasoning_effort: str | None = None,
        preserve_reasoning_content: bool = False,
        client: Any | None = None,
    ) -> None:
        self.token_param = token_param
        self.stream_options = stream_options
        self.include_tool_result_name = include_tool_result_name
        self.extra_body = extra_body
        self.reasoning_effort = reasoning_effort
        self.preserve_reasoning_content = preserve_reasoning_content
        self.client = client or AsyncOpenAI(
            api_key=os.environ[api_key_env],
            base_url=base_url,
            timeout=PROVIDER_TIMEOUT_SECONDS,
            max_retries=PROVIDER_MAX_RETRIES,
        )

    def format_user(self, text: str) -> ProviderMessage:
        return {"role": "user", "content": text}

    def append_tool_results(
        self, messages: list[ProviderMessage], results: list[ToolResult]
    ) -> None:
        for r in results:
            msg = {
                "role": "tool",
                "tool_call_id": r.tool_use_id,
                "content": r.content,
            }
            if self.include_tool_result_name:
                msg["name"] = r.name
            messages.append(msg)

    def tools_for_provider(self, profile: AgentProfile) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": s["name"],
                    "description": s["description"],
                    "parameters": s["input_schema"],
                },
            }
            for s in schemas_for_tools(
                profile.tools,
                description_overrides=profile.tool_descriptions,
            )
        ]

    def system_for_provider(self, profile: AgentProfile) -> dict:
        return {"role": "system", "content": profile.system_prompt}

    async def stream(
        self,
        *,
        model: str,
        messages: list[ProviderMessage],
        system: Any,
        tools: list,
        max_tokens: int,
    ) -> AsyncIterator[Event]:
        request: dict[str, Any] = {
            "model": model,
            "messages": [system, *messages],
            "tools": tools,
            "stream": True,
            self.token_param: max_tokens,
        }
        if self.stream_options:
            request["stream_options"] = {"include_usage": True}
        if self.reasoning_effort:
            request["reasoning_effort"] = self.reasoning_effort
        if self.extra_body:
            request["extra_body"] = self.extra_body

        stream = await self.client.chat.completions.create(**request)

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        stop_reason = "end_turn"
        usage: UsagePayload | None = None

        async for chunk in stream:
            usage_obj = getattr(chunk, "usage", None)
            if usage_obj is not None:
                usage = _norm_usage(usage_obj)

            for choice in getattr(chunk, "choices", []) or []:
                finish_reason = getattr(choice, "finish_reason", None)
                if finish_reason:
                    stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"

                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue

                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    reasoning_parts.append(reasoning)
                    yield {"type": "thinking_delta", "text": reasoning}
                    # No `continue` here. It used to skip the rest of THIS delta,
                    # so any provider that interleaves reasoning with content or
                    # tool_calls in one chunk silently lost those fragments -- a
                    # dropped tool call with no error anywhere.

                text = getattr(delta, "content", None)
                if text:
                    content_parts.append(text)
                    yield {"type": "text_delta", "text": text}

                for tc in getattr(delta, "tool_calls", None) or []:
                    index = getattr(tc, "index", None)
                    if index is None:
                        index = len(tool_calls)
                    acc = tool_calls.setdefault(
                        index,
                        {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )

                    tc_id = getattr(tc, "id", None)
                    if tc_id:
                        acc["id"] = tc_id
                    tc_type = getattr(tc, "type", None)
                    if tc_type:
                        acc["type"] = tc_type

                    fn = getattr(tc, "function", None)
                    if fn is None:
                        continue
                    name = getattr(fn, "name", None)
                    if name:
                        # One event per CALL. Deduping by name under-reported a
                        # hop that called the same tool twice, so identical work
                        # looked different here than on Anthropic.
                        first_name = not acc["function"]["name"]
                        acc["function"]["name"] = name
                        if first_name:
                            yield {"type": "tool_use_start", "name": name}
                    args = getattr(fn, "arguments", None)
                    if args:
                        acc["function"]["arguments"] += args

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content_parts) or None,
        }
        completed_tool_calls = [tool_calls[i] for i in sorted(tool_calls)]
        if completed_tool_calls:
            assistant_msg["tool_calls"] = completed_tool_calls
            stop_reason = "tool_use"
        # DeepSeek thinking mode requires reasoning_content to round-trip on every
        # assistant turn that streamed reasoning, not just tool-call turns — empirically,
        # plain-text turns 400 the next request too if their reasoning_content is dropped.
        # Other providers don't accept the field, so this is gated by the registry flag.
        if self.preserve_reasoning_content and reasoning_parts:
            assistant_msg["reasoning_content"] = "".join(reasoning_parts)
        messages.append(assistant_msg)

        for i, tc in enumerate(completed_tool_calls):
            fn = tc.get("function", {})
            name = fn.get("name") or ""
            tool_use_id = tc.get("id") or f"call_{i}"
            yield {
                "type": "tool_use_complete",
                "tool_use_id": tool_use_id,
                "name": name,
                "arguments": _parse_arguments(fn.get("arguments", "")),
            }

        if usage is None:
            # An endpoint that refuses stream_options (or drops the final usage
            # chunk) used to yield NO usage event at all, so its traffic spent
            # completely unmetered budget — that was Kimi's behavior for every
            # turn. An explicit estimate is strictly better than silence: it is
            # marked `estimated` so nothing mistakes it for a measurement, and
            # the budget stops being free. chars/4 is deliberately crude; the
            # point is a floor, not precision.
            log.warning(
                "usage_estimated",
                extra={"model": model, "reason": "provider returned no usage"},
            )
            usage = _estimate_usage(
                request["messages"], content_parts, reasoning_parts, completed_tool_calls
            )
        yield {"type": "usage", "usage": usage}
        yield {"type": "message_done", "stop_reason": stop_reason}


def _estimate_usage(
    prompt_messages: list,
    content_parts: list[str],
    reasoning_parts: list[str],
    tool_calls: list[dict],
) -> UsagePayload:
    """Crude chars/4 fallback for endpoints that report no usage at all."""
    prompt_chars = len(json.dumps(prompt_messages, default=str))
    output_chars = sum(len(t) for t in content_parts) + len(
        json.dumps(tool_calls, default=str)
    )
    reasoning_chars = sum(len(t) for t in reasoning_parts)
    return {
        "input_tokens": max(1, prompt_chars // 4),
        "output_tokens": max(0, output_chars // 4),
        "reasoning_tokens": max(0, reasoning_chars // 4),
        "estimated": True,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


def _parse_arguments(raw: str) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Sentinel recognized by run_tool in runnrr/tools/dispatch.py: it turns
        # this into a "retry with well-formed JSON" error the model can act on,
        # while the raw text stays available for logs.
        return {"_raw_arguments": raw}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _norm_usage(u: Any) -> UsagePayload:
    input_tokens = getattr(u, "prompt_tokens", None)
    if input_tokens is None:
        input_tokens = getattr(u, "input_tokens", 0) or 0
    output_tokens = getattr(u, "completion_tokens", None)
    if output_tokens is None:
        output_tokens = getattr(u, "output_tokens", 0) or 0
    # OpenAI o1-style + DeepSeek thinking models report reasoning tokens inside
    # completion_tokens_details. They are a subset of completion_tokens, not in
    # addition to them — surface separately so the UI can break out the share.
    reasoning_tokens = 0
    details = getattr(u, "completion_tokens_details", None)
    if details is not None:
        reasoning_tokens = (
            getattr(details, "reasoning_tokens", None)
            or (details.get("reasoning_tokens", 0) if isinstance(details, dict) else 0)
            or 0
        )
    # DeepSeek surfaces KV-cache hits as prompt_cache_hit_tokens; OpenAI puts the
    # same quantity on prompt_tokens_details.cached_tokens. They are mutually
    # exclusive per endpoint, so read both — before this, OpenAI cache hits were
    # invisible and always logged as 0. Both are subsets of prompt_tokens, which
    # is the semantics runnrr/usage.py requires.
    cache_hit = getattr(u, "prompt_cache_hit_tokens", 0) or 0
    if not cache_hit:
        prompt_details = getattr(u, "prompt_tokens_details", None)
        if prompt_details is not None:
            cache_hit = (
                getattr(prompt_details, "cached_tokens", None)
                or (
                    prompt_details.get("cached_tokens", 0)
                    if isinstance(prompt_details, dict)
                    else 0
                )
                or 0
            )
    # reasoning_tokens is a subset of completion_tokens (see comment above), so make
    # them disjoint here — the frontend buckets reasoning separately and would
    # double-count if output_tokens still included it.
    output_total = output_tokens or 0
    reasoning = max(0, min(reasoning_tokens, output_total))
    return {
        "input_tokens": input_tokens or 0,
        "output_tokens": output_total - reasoning,
        "reasoning_tokens": reasoning,
        "cache_read_input_tokens": cache_hit,
        "cache_creation_input_tokens": 0,
    }
