"""Public web-search native tool definition."""
from __future__ import annotations

from typing import Any

from backend.tools.definitions import ToolContext, ToolDef
from backend.tools.source_metadata import web_search_metadata
from backend.web_search import web_search


def _handle_web_search(arguments: dict[str, Any], ctx: ToolContext) -> Any:
    return web_search(
        arguments["query"],
        max_results=arguments.get("max_results", 5),
        search_depth=arguments.get("search_depth", "basic"),
        include_answer=arguments.get("include_answer", True),
    )


WEB_SEARCH_TOOL = ToolDef(
    name="web_search",
    description=(
        "Search the public web for up-to-date information not in the active profile's "
        "knowledge base. Use for recent news, current events, company/person/technology "
        "lookups, or to verify a fact that may have changed since the KB was last "
        "updated. Returns a synthesized answer plus ranked results with title, url, "
        "and a short content snippet. Cite the URL when you use a result in your reply."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "How many results to return (1-10, default 5).",
            },
            "search_depth": {
                "type": "string",
                "enum": ["basic", "advanced"],
                "description": (
                    "'basic' is faster and cheaper; 'advanced' returns deeper snippets "
                    "for harder queries. Default 'basic'."
                ),
            },
        },
        "required": ["query"],
    },
    handler=_handle_web_search,
    source_metadata=web_search_metadata,
)
