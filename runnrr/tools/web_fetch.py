"""SSRF-guarded public web page fetch tool."""
from __future__ import annotations

import html
import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from runnrr.tool_errors import ToolExecutionError
from runnrr.tools.definitions import ToolDef
from runnrr.tools.source_metadata import fetch_url_text_metadata

FETCH_TIMEOUT_SECONDS = 10.0
FETCH_DEFAULT_CHARS = 6_000
FETCH_MAX_CHARS = 20_000
FETCH_MAX_BYTES = 250_000
FETCH_MAX_REDIRECTS = 3


def _assert_public_http_url(url: str) -> str:
    """Validate a URL before fetching so tools cannot reach local infrastructure."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise ToolExecutionError("url must use http or https")
    if not parsed.hostname:
        raise ToolExecutionError("url must include a hostname")

    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "ip6-localhost", "ip6-loopback"}:
        raise ToolExecutionError("local hosts are not allowed")

    addresses: set[str] = set()
    try:
        ip = ipaddress.ip_address(host)
        addresses.add(str(ip))
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as e:
            raise ToolExecutionError(f"could not resolve hostname: {host}") from e
        addresses.update(info[4][0] for info in infos)

    if not addresses:
        raise ToolExecutionError(f"could not resolve hostname: {host}")

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as e:
            raise ToolExecutionError(f"invalid resolved address for {host}") from e
        if not ip.is_global:
            raise ToolExecutionError("private, local, or reserved network hosts are not allowed")

    return parsed.geturl()


def _text_content_type(content_type: str) -> bool:
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    return (
        ctype.startswith("text/")
        or ctype in {
            "application/json",
            "application/ld+json",
            "application/xml",
            "application/xhtml+xml",
        }
    )


def _html_title(raw: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()[:160]


def _html_to_text(raw: str) -> str:
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|section|article|li|h[1-6])>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_url_text(url: str, *, max_chars: int = FETCH_DEFAULT_CHARS) -> dict[str, Any]:
    """Fetch one public text page and return a compact excerpt."""
    if not isinstance(url, str) or not url.strip():
        raise ToolExecutionError("url must be a non-empty string")
    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError) as e:
        raise ToolExecutionError("max_chars must be an integer") from e
    max_chars = max(1, min(max_chars, FETCH_MAX_CHARS))

    current_url = url.strip()
    response: httpx.Response | None = None
    for _ in range(FETCH_MAX_REDIRECTS + 1):
        current_url = _assert_public_http_url(current_url)
        try:
            response = httpx.get(
                current_url,
                follow_redirects=False,
                timeout=FETCH_TIMEOUT_SECONDS,
                headers={"User-Agent": "Runnrr research fetch/0.1"},
            )
        except httpx.HTTPError as e:
            raise ToolExecutionError(f"network error: {type(e).__name__}: {e}") from e

        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise ToolExecutionError("redirect response did not include a Location header")
            current_url = urljoin(current_url, location)
            continue
        break
    else:
        raise ToolExecutionError("too many redirects")

    assert response is not None
    if response.status_code >= 400:
        raise ToolExecutionError(f"HTTP {response.status_code} while fetching URL")

    content_type = response.headers.get("content-type", "")
    if not _text_content_type(content_type):
        raise ToolExecutionError(f"non-text content type: {content_type or 'unknown'}")
    if len(response.content) > FETCH_MAX_BYTES:
        raise ToolExecutionError(f"response too large: {len(response.content)} bytes")

    raw = response.text
    title = _html_title(raw) if "html" in content_type.lower() else ""
    readable = _html_to_text(raw) if "html" in content_type.lower() else raw.strip()
    readable = re.sub(r"\s+", " ", readable).strip()
    excerpt = readable[:max_chars]
    if len(readable) > max_chars:
        excerpt = excerpt.rstrip() + "..."

    return {
        "url": str(response.url),
        "status_code": response.status_code,
        "content_type": content_type.split(";", 1)[0].strip().lower(),
        "title": title,
        "excerpt": excerpt,
    }


FETCH_URL_TEXT_TOOL = ToolDef(
    name="fetch_url_text",
    description=(
        "Fetch the readable text from one public HTTP(S) page. Use this after "
        "web_search when a research profile needs to inspect a result more closely. "
        "The tool rejects localhost, private-network hosts, file URLs, non-text "
        "responses, redirects to unsafe hosts, and oversized pages. Returns title "
        "and excerpt, not raw browser DOM."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Public http:// or https:// URL to fetch.",
            },
            "max_chars": {
                "type": "integer",
                "description": (
                    "Maximum excerpt characters to return. Default 6000, hard cap 20000."
                ),
            },
        },
        "required": ["url"],
    },
    handler=lambda args, ctx: fetch_url_text(
        args["url"],
        max_chars=args.get("max_chars", FETCH_DEFAULT_CHARS),
    ),
    source_metadata=fetch_url_text_metadata,
)
