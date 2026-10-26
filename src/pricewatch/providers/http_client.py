"""Resilient async HTTP client with SSRF protection and realistic browser headers."""

import ipaddress
import socket
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from pricewatch.domain.exceptions import ExtractionError


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def validate_url_security(url: str) -> None:
    """SSRF protection: validate scheme and ensure hostname does not resolve to private/loopback IP."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ExtractionError(f"Invalid URL scheme: '{parsed.scheme}'. Only HTTP/HTTPS allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise ExtractionError(f"Invalid URL: missing hostname in '{url}'.")

    # Reject localhost directly
    if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
        raise ExtractionError("Access to localhost is forbidden.")

    # Resolve IP and check if global
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addrinfo:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            if not ip_obj.is_global:
                raise ExtractionError(f"URL resolves to non-global IP address ({ip_str}), blocked by SSRF policy.")
    except socket.gaierror:
        # Host cannot be resolved right now; will fail in request anyway
        pass


try:
    import h2
    _HAS_HTTP2 = True
except ImportError:
    _HAS_HTTP2 = False


class ResilientHttpClient:
    """HTTP client wrapper with timeout, custom headers, and connection pooling."""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers=DEFAULT_HEADERS,
                follow_redirects=True,
                http2=_HAS_HTTP2,
            )
        return self._client

    async def get(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        validate_ssrf: bool = True,
    ) -> httpx.Response:
        """Execute async GET request."""
        if validate_ssrf:
            validate_url_security(url)

        client = await self.get_client()
        req_headers = dict(DEFAULT_HEADERS)
        if headers:
            req_headers.update(headers)

        try:
            resp = await client.get(url, headers=req_headers)
            return resp
        except httpx.HTTPError as exc:
            raise ExtractionError(f"HTTP request failed for {url}: {exc}") from exc

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Global client instance
http_client = ResilientHttpClient()
