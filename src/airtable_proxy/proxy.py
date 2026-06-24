"""
Proxy functionality for forwarding requests to the Airtable API.
"""

import httpx
from fastapi import Request, Response

AIRTABLE_API_BASE = "https://api.airtable.com"


class ProxyRequest(Exception):
    """
    Raise this exception from a route handler to indicate that the request
    should be proxied to Airtable instead of being handled locally.

    This allows handlers to inspect a request and decide to proxy it
    based on query parameters, missing data, etc.
    """

    pass


async def forward(request: Request, path: str) -> httpx.Response:
    """
    Forward an incoming request to the Airtable API and return the raw
    httpx response.

    Callers that need to read the response body before returning it (for
    example, to update the local cache) should use this helper and then
    pass the result to `response_from_httpx`.
    """
    url = f"{AIRTABLE_API_BASE}/{path}"

    headers: dict[str, str] = {}
    if auth := request.headers.get("Authorization"):
        headers["Authorization"] = auth
    if content_type := request.headers.get("Content-Type"):
        headers["Content-Type"] = content_type

    body = await request.body()

    async with httpx.AsyncClient() as client:
        return await client.request(
            method=request.method,
            url=url,
            params=request.query_params,
            headers=headers,
            content=body if body else None,
        )


def response_from_httpx(response: httpx.Response) -> Response:
    """
    Convert an httpx response into a FastAPI/Starlette Response that
    preserves status code, headers, and content type.

    ``httpx`` automatically decompresses the response body, so we must drop
    ``Content-Encoding`` and ``Transfer-Encoding`` from the forwarded headers.
    Sending those headers with an already-decoded body would cause downstream
    clients to attempt a second decompression pass and fail.
    """
    _STRIP = {"content-encoding", "transfer-encoding"}
    headers = {k: v for k, v in response.headers.items() if k.lower() not in _STRIP}
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=headers,
        media_type=response.headers.get("Content-Type"),
    )


async def proxy_to_airtable(request: Request, path: str) -> Response:
    """
    Forward a request to the Airtable API and return the response.

    Convenience wrapper around `forward` and `response_from_httpx` for
    callers that do not need to inspect the response body.
    """
    return response_from_httpx(await forward(request, path))
