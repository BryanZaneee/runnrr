"""Structured JSON via Anthropic sync client (prefill + stop at closing fence)."""
from __future__ import annotations

import json
import os
from typing import Any

from anthropic import Anthropic

from backend import config
from backend.config import MODEL_REGISTRY


class LLMJsonError(RuntimeError):
    """Raised when LLM JSON completion or parsing fails."""


def complete_json(
    prompt: str,
    *,
    model_id: str | None = None,
    system: str | None = None,
    max_tokens: int = 512,
) -> Any:
    resolved = model_id or config.GRADER_MODEL_ID
    model = MODEL_REGISTRY[resolved]["model"]
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMJsonError(
            "ANTHROPIC_API_KEY required for LLM JSON grading/reranking"
        )
    try:
        client = Anthropic()
        messages = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "```json\n"},
        ]
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "stop_sequences": ["```"],
        }
        if system is not None:
            kwargs["system"] = [{"type": "text", "text": system}]
        resp = client.messages.create(**kwargs)
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )
        return json.loads(text.strip())
    except json.JSONDecodeError as exc:
        raise LLMJsonError(f"invalid JSON from model: {exc}") from exc
    except Exception as exc:
        raise LLMJsonError(str(exc)) from exc
