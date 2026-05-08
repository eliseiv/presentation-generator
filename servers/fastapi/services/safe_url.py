"""
SSRF guard for user-supplied URLs.

Two paths consume external URLs (video transcribe, page scrape) — both must
refuse anything that resolves to a private/loopback/link-local address before
opening a connection. Without this guard a caller could point us at an
internal service (FastAPI, mem0, the Docker host, the cloud metadata
endpoint…) and we would happily fetch it with our own credentials.

`assert_url_is_safe(url)` is the only function callers should need:
    raise HTTPException(400) on an invalid scheme / unparseable URL,
    raise HTTPException(400) on a hostname that resolves to a private range.
On success it returns nothing.
"""

import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException


_ALLOWED_SCHEMES = {"http", "https"}

# Disallow IP families that should never be reachable from a user-supplied URL.
_FORBIDDEN_IP_PROPERTIES = (
    "is_private",
    "is_loopback",
    "is_link_local",
    "is_multicast",
    "is_reserved",
    "is_unspecified",
)


def _resolve_all_addresses(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resolve host '{host}': {exc}",
        ) from exc

    return list({info[4][0] for info in infos})


def assert_url_is_safe(url: str) -> None:
    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"URL scheme '{parsed.scheme}' is not allowed. "
                f"Use http(s)://."
            ),
        )

    host = (parsed.hostname or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="URL has no host.")

    addresses = _resolve_all_addresses(host)
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot parse resolved address '{addr}'.",
            )

        for prop in _FORBIDDEN_IP_PROPERTIES:
            if getattr(ip, prop, False):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Refusing to fetch '{url}': host '{host}' resolves "
                        f"to a non-public address ({addr})."
                    ),
                )
