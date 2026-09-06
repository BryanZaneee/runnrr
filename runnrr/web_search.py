"""Web search tool — Tavily-backed.

Tavily is purpose-built for LLM agents: it returns ranked results with content
snippets pre-trimmed for token efficiency, plus an optional synthesized answer.
Free tier covers 1000 searches/month — enough for a personal-site agent.

Provider-agnostic by design: the result is a plain dict shaped for any model to
read, so Personal Agent can use it whether it's running on DeepSeek, Claude, GPT, etc.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

TAVILY_ENDPOINT = "https://api.tavily.com/search"
DEFAULT_TIMEOUT = 10.0


class WebSearchError(Exception):
    """Raised when the search backend is misconfigured or fails."""


def web_search(
    query: str,
    *,
    max_results: int = 5,
    search_depth: str = "basic",
    include_answer: bool = True,
) -> dict[str, Any]:
    """Run a web search and return a compact result envelope.

    Returns {query, answer, results: [{title, url, content, score}]}.
    `content` is a Tavily-trimmed snippet (~hundreds of chars), not full page HTML.
    """
    if not isinstance(query, str) or not query.strip():
        raise WebSearchError("query must be a non-empty string")
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise WebSearchError("TAVILY_API_KEY not configured on the server")

    if search_depth not in ("basic", "advanced"):
        raise WebSearchError("search_depth must be 'basic' or 'advanced'")
    max_results = max(1, min(int(max_results), 10))

    payload = {
        "api_key": api_key,
        "query": query.strip(),
        "search_depth": search_depth,
        "max_results": max_results,
        "include_answer": bool(include_answer),
        "include_raw_content": False,
        "include_images": False,
    }

    try:
        resp = httpx.post(TAVILY_ENDPOINT, json=payload, timeout=DEFAULT_TIMEOUT)
    except httpx.HTTPError as e:
        raise WebSearchError(f"network error: {type(e).__name__}: {e}") from e

    if resp.status_code == 401:
        raise WebSearchError("invalid TAVILY_API_KEY")
    if resp.status_code == 429:
        raise WebSearchError("rate limited by Tavily — try again later")
    if resp.status_code >= 400:
        raise WebSearchError(f"Tavily HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
            "score": r.get("score"),
        }
        for r in data.get("results", [])
    ]
    return {
        "query": data.get("query", query),
        "answer": data.get("answer") or "",
        "results": results,
    }
