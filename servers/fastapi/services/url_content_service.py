"""
Fetch and clean text content from a public URL.

Wikipedia gets a fast-path through the REST summary API (no scraping, no
markup, very small payload). Every other site falls back to trafilatura,
which strips chrome/menus/footers and returns the article body.

Used by the presentation generator to turn a `source_url` into context for
the outline LLM.
"""

import re
from urllib.parse import unquote, urlparse

import httpx
import trafilatura
from fastapi import HTTPException
from pydantic import BaseModel

from services.safe_url import assert_url_is_safe


_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB hard cap on any HTML page.
_USER_AGENT = (
    "Presenton/0.1 (+https://appbackendnew.store) "
    "url-content-fetcher (httpx)"
)


class FetchedPageContent(BaseModel):
    title: str | None
    text: str
    source_url: str


def _is_wikipedia(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("wikipedia.org")


def _wikipedia_api_url(article_url: str) -> str | None:
    """
    Convert https://<lang>.wikipedia.org/wiki/<Title> to the REST extract
    endpoint. Returns None if the URL doesn't match this shape.
    """
    parsed = urlparse(article_url)
    parts = parsed.path.split("/")
    if len(parts) < 3 or parts[1] != "wiki":
        return None
    title = unquote("/".join(parts[2:]))
    if not title:
        return None
    return (
        f"{parsed.scheme}://{parsed.netloc}/w/api.php"
        f"?action=query&format=json&prop=extracts&explaintext=1"
        f"&redirects=1&titles={title}"
    )


async def _fetch_wikipedia(url: str) -> FetchedPageContent | None:
    api_url = _wikipedia_api_url(url)
    if not api_url:
        return None

    assert_url_is_safe(api_url)
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    ) as client:
        response = await client.get(api_url)
        if response.status_code != 200:
            return None
        payload = response.json()

    pages = payload.get("query", {}).get("pages", {})
    if not pages:
        return None
    page = next(iter(pages.values()))
    extract = (page.get("extract") or "").strip()
    if not extract:
        return None

    return FetchedPageContent(
        title=page.get("title"),
        text=extract,
        source_url=url,
    )


async def _fetch_generic(url: str) -> FetchedPageContent:
    assert_url_is_safe(url)

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
        follow_redirects=True,
    ) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Failed to fetch '{url}': "
                        f"upstream returned {response.status_code}"
                    ),
                )

            buffer = bytearray()
            async for chunk in response.aiter_bytes():
                buffer.extend(chunk)
                if len(buffer) > _MAX_RESPONSE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"Page at '{url}' exceeds the "
                            f"{_MAX_RESPONSE_BYTES // (1024 * 1024)} MB cap."
                        ),
                    )
            html = bytes(buffer).decode(
                response.charset_encoding or "utf-8", errors="replace"
            )

    extracted = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
    )
    if not extracted or not extracted.strip():
        raise HTTPException(
            status_code=422,
            detail=(
                f"Could not extract readable text from '{url}'. "
                f"Try a different page (article-style content works best)."
            ),
        )

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else None

    return FetchedPageContent(title=title, text=extracted.strip(), source_url=url)


async def fetch_url_text(url: str) -> FetchedPageContent:
    """
    Fetch a public URL and return its main text. Wikipedia uses the REST API,
    everything else uses trafilatura over an httpx GET.

    Raises:
        HTTPException(400) if the URL is unsafe or unreachable.
        HTTPException(413) if the response is too large.
        HTTPException(422) if no readable text could be extracted.
    """
    url = url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="source_url is empty.")

    assert_url_is_safe(url)

    if _is_wikipedia(url):
        wiki_result = await _fetch_wikipedia(url)
        if wiki_result is not None:
            return wiki_result
        # Fall through to generic scrape if the REST API didn't help.

    return await _fetch_generic(url)
