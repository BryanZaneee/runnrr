"""Gemini provider using Google's official google-genai SDK."""
from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from google import genai
from google.genai import types

from backend.config import PROVIDER_TIMEOUT_SECONDS
from backend.profiles import AgentProfile
from backend.providers.base import Event
from backend.tools import ToolResult, schemas_for_tools
from backend.types import ProviderMessage, UsagePayload


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
        announced_tool_names: set[str] = set()
        usage: UsagePayload | None = None

        async for chunk in response_stream:
            text = _chunk_text(chunk)
            if text:
                text_parts.append(text)
                yield {"type": "text_delta", "text": text}

            usage_obj = getattr(chunk, "usage_metadata", None)
            if usage_obj is not None:
                usage = _norm_usage(usage_obj)

            for part in _chunk_parts(chunk):
                fc = getattr(part, "function_call", None)
                if fc is None:
                    continue
                function_parts.append(part)
                name = getattr(fc, "name", "") or ""
                if name and name not in announced_tool_names:
                    announced_tool_names.add(name)
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
        yield {
            "type": "message_done",
            "stop_reason": "tool_use" if function_parts else "end_turn",
        }


def _response_dict(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {"content": content}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


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
    # Gemini thinking models report `thoughts_token_count` separately from
    # `candidates_token_count`. Expose as reasoning_tokens so the UI can show
    # the breakdown alongside other providers.
    return {
        "input_tokens": getattr(u, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(u, "candidates_token_count", 0) or 0,
        "reasoning_tokens": getattr(u, "thoughts_token_count", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cached_content_token_count", 0) or 0,
        "cache_creation_input_tokens": 0,
    }
