"""Gemini provider using Google's official google-genai SDK."""
from __future__ import annotations

import os
from typing import Any, AsyncIterator

from google import genai
from google.genai import types

from backend.config import PROVIDER_TIMEOUT_SECONDS
from backend.profiles import AgentProfile
from backend.providers.base import Event
from backend.tools import ToolResult, schemas_for_tools
from backend.types import ProviderMessage, UsagePayload

# Finishes where the answer is incomplete for a reason the user needs to know.
_BLOCKED_FINISHES = frozenset({"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"})


class GeminiProvider:
    def __init__(self, *, api_key_env: str = "GEMINI_API_KEY", client: Any | None = None) -> None:
        self.client = client or genai.Client(
            api_key=os.environ[api_key_env],
            # google-genai takes the timeout in milliseconds.
            http_options=types.HttpOptions(timeout=int(PROVIDER_TIMEOUT_SECONDS * 1000)),
        )

    def format_user(self, text: str) -> ProviderMessage:
        return types.Content(role="user", parts=[types.Part.from_text(text=text)])

    def append_tool_results(
        self, messages: list[ProviderMessage], results: list[ToolResult]
    ) -> None:
        parts = []
        for r in results:
            parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        id=r.tool_use_id,
                        name=r.name,
                        response=_response_dict(r.content),
                    )
                )
            )
        messages.append(types.Content(role="user", parts=parts))

    def tools_for_provider(self, profile: AgentProfile) -> list[Any]:
        declarations = [
            types.FunctionDeclaration(
                name=s["name"],
                description=s["description"],
                parameters_json_schema=s["input_schema"],
            )
            for s in schemas_for_tools(
                profile.tools,
                description_overrides=profile.tool_descriptions,
            )
        ]
        return [types.Tool(function_declarations=declarations)]

    def system_for_provider(self, profile: AgentProfile) -> str:
        return profile.system_prompt

    async def stream(
        self,
        *,
        model: str,
        messages: list[ProviderMessage],
        system: Any,
        tools: list,
        max_tokens: int,
    ) -> AsyncIterator[Event]:
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=tools,
            max_output_tokens=max_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        response_stream = await self.client.aio.models.generate_content_stream(
            model=model,
            contents=messages,
            config=config,
        )

        text_parts: list[str] = []
        function_parts: list[Any] = []
        usage: UsagePayload | None = None
        finish_reason: str | None = None

        async for chunk in response_stream:
            text = _chunk_text(chunk)
            if text:
                text_parts.append(text)
                yield {"type": "text_delta", "text": text}

            usage_obj = getattr(chunk, "usage_metadata", None)
            if usage_obj is not None:
                usage = _norm_usage(usage_obj)

            for candidate in getattr(chunk, "candidates", None) or []:
                fr = getattr(candidate, "finish_reason", None)
                if fr is not None:
                    finish_reason = getattr(fr, "name", None) or str(fr)

            for part in _chunk_parts(chunk):
                fc = getattr(part, "function_call", None)
                if fc is None:
                    continue
                function_parts.append(part)
                name = getattr(fc, "name", "") or ""
                if name:
                    # One event per CALL, not per distinct name. Deduping by name
                    # meant two read_file calls in one hop announced once, so the
                    # same workload reported differently than on Anthropic.
                    yield {"type": "tool_use_start", "name": name}

        model_parts = []
        if text_parts:
            model_parts.append(types.Part.from_text(text="".join(text_parts)))
        model_parts.extend(function_parts)
        if not model_parts:
            model_parts.append(types.Part.from_text(text=""))
        messages.append(types.Content(role="model", parts=model_parts))

        for i, part in enumerate(function_parts):
            fc = part.function_call
            yield {
                "type": "tool_use_complete",
                "tool_use_id": getattr(fc, "id", None) or f"gemini_call_{i}",
                "name": getattr(fc, "name", "") or "",
                "arguments": getattr(fc, "args", None) or {},
            }

        if usage is not None:
            yield {"type": "usage", "usage": usage}

        # stop_reason used to be inferred purely from content: "tool_use" if any
        # function parts, else "end_turn". That reported a MAX_TOKENS truncation,
        # a SAFETY block, or a RECITATION stop as a clean completion -- the user
        # saw a half-answer with no indication anything went wrong, and the other
        # two providers read the real field. Blocked finishes are surfaced on the
        # `error` event, which existed for exactly this and had no producer.
        if function_parts:
            stop_reason = "tool_use"
        elif finish_reason in _BLOCKED_FINISHES:
            yield {
                "type": "error",
                "text": f"the model stopped early ({finish_reason.lower()})",
            }
            return
        elif finish_reason == "MAX_TOKENS":
            stop_reason = "max_tokens"
        else:
            stop_reason = "end_turn"
        yield {"type": "message_done", "stop_reason": stop_reason}


# Gemini requires a dict response, but the shape must match what Anthropic and
# OpenAI show the model for the same tool -- they pass the raw string through.
# Parsing and re-wrapping meant the model saw structurally different tool output
# per provider for identical work, which quietly invalidates any cross-model
# eval comparison.
def _response_dict(content: str) -> dict[str, Any]:
    return {"content": content}


def _chunk_text(chunk: Any) -> str:
    try:
        return getattr(chunk, "text", None) or ""
    except Exception:
        return ""


def _chunk_parts(chunk: Any) -> list[Any]:
    parts = []
    for candidate in getattr(chunk, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        parts.extend(getattr(content, "parts", None) or [])
    return parts


def _norm_usage(u: Any) -> UsagePayload:
    # Gemini already satisfies backend/usage.py's contract natively, so unlike
    # the other two providers this function does no arithmetic. Do not "fix" it:
    #
    #   total = prompt_token_count + candidates_token_count + thoughts_token_count
    #
    # Thoughts are ALREADY disjoint from candidates, so subtracting reasoning out
    # of output here (as Anthropic and OpenAI must, because their APIs roll it in)
    # would double-discount it. And cached_content_token_count is already a subset
    # of prompt_token_count, which is exactly the semantics the contract wants.
    # Pinned by test_gemini_reasoning_disjoint_from_output.
    return {
        "input_tokens": getattr(u, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(u, "candidates_token_count", 0) or 0,
        "reasoning_tokens": getattr(u, "thoughts_token_count", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cached_content_token_count", 0) or 0,
        "cache_creation_input_tokens": 0,
    }
