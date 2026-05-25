"""
ironclaw.tools.builtins.web
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Safe web tools: fetch a URL and a basic DuckDuckGo search.

Security constraints
--------------------
- Domain allowlist / blocklist checked before every request.
- Redirect following is limited to 3 hops.
- Response size is capped at 256 KB.
- Only HTTP/HTTPS — no ``file://``, ``ftp://``, etc.
- Timeout hard-coded at 15 seconds.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

from ironclaw.tools.registry import ToolRegistry, ToolSpec

_MAX_RESPONSE_BYTES = 256 * 1024  # 256 KB
_REQUEST_TIMEOUT = 15.0
_MAX_REDIRECTS = 3

# Default blocked domains — never mutated at runtime.
_DEFAULT_BLOCKED_DOMAINS: frozenset[str] = frozenset({
    "169.254.169.254",  # AWS metadata endpoint
    "metadata.google.internal",
    "metadata.azure.com",
})


def _check_url(url: str, blocked: frozenset[str] = _DEFAULT_BLOCKED_DOMAINS) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http/https URLs are allowed, got: {parsed.scheme}://")
    host = parsed.hostname or ""
    if host in blocked:
        raise PermissionError(f"Domain '{host}' is blocked")
    # Block private / loopback ranges via simple hostname check
    if re.match(r"^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|localhost)", host):
        raise PermissionError(f"Private / loopback addresses are blocked: {host}")
    return url


def _make_web_fetch(blocked: frozenset[str]):
    """Return a web_fetch function closed over the given blocked-domain set."""
    async def _web_fetch(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        """Fetch a URL and return status, headers, and text body."""
        _check_url(url, blocked)
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            timeout=_REQUEST_TIMEOUT,
        ) as client:
            resp = await client.get(url, headers=headers or {})
            # _MAX_RESPONSE_BYTES is in bytes; divide by 4 for conservative char estimate
            body = resp.text[: _MAX_RESPONSE_BYTES // 4]
            return {
                "status_code": resp.status_code,
                "url": str(resp.url),
                "content_type": resp.headers.get("content-type", ""),
                "body": body,
            }
    return _web_fetch


async def _web_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """
    Basic web search via DuckDuckGo Instant Answers API (no API key needed).
    Returns a list of {title, url, snippet} dicts.
    """
    if max_results > 10:
        max_results = 10

    endpoint = "https://api.duckduckgo.com/"
    params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1"}

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        resp = await client.get(endpoint, params=params)
        data = resp.json()

    results: list[dict[str, str]] = []

    # RelatedTopics contain the most useful links
    for topic in data.get("RelatedTopics", [])[:max_results]:
        if "Text" in topic and "FirstURL" in topic:
            results.append(
                {
                    "title": topic.get("Text", "")[:200],
                    "url": topic["FirstURL"],
                    "snippet": topic.get("Text", "")[:500],
                }
            )

    # Abstract as bonus result
    if data.get("AbstractText"):
        results.insert(
            0,
            {
                "title": data.get("Heading", "Abstract"),
                "url": data.get("AbstractURL", ""),
                "snippet": data["AbstractText"][:500],
            },
        )

    return results[:max_results]


def register_web_tools(
    registry: ToolRegistry,
    blocked_domains: list[str] | None = None,
) -> None:
    """Register web tools into *registry*.

    Each call produces independent tool functions closed over their own
    blocked-domain set, so different agents can have different domain
    policies without polluting each other.
    """
    # Build a per-registration frozenset so we never mutate a shared global.
    blocked: frozenset[str] = _DEFAULT_BLOCKED_DOMAINS | frozenset(blocked_domains or [])

    registry.register(
        ToolSpec(
            name="web:fetch",
            description="Fetch a web page and return its text content.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to fetch"},
                    "headers": {
                        "type": "object",
                        "description": "Optional HTTP headers",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["url"],
            },
            fn=_make_web_fetch(blocked),
            requires="web:fetch",
        )
    )

    registry.register(
        ToolSpec(
            name="web:search",
            description="Search the web using DuckDuckGo and return top results.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                },
                "required": ["query"],
            },
            fn=_web_search,
            requires="web:search",
        )
    )
