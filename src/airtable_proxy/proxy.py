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


async def proxy_to_airtable(request: Request, path: str) -> Response:
    """
    Forward a request to the Airtable API and return the response.

    Args:
        request: The incoming FastAPI request
        path: The path to forward (e.g., "v0/appXXX/TableName")

    Returns:
        A FastAPI Response containing the Airtable API response
    """
    url = f"{AIRTABLE_API_BASE}/{path}"

    headers = {}
    if auth := request.headers.get("Authorization"):
        headers["Authorization"] = auth
    if content_type := request.headers.get("Content-Type"):
        headers["Content-Type"] = content_type

    body = await request.body()

    async with httpx.AsyncClient() as client:
        response = await client.request(
            method=request.method,
            url=url,
            params=request.query_params,
            headers=headers,
            content=body if body else None,
        )

    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.headers.get("Content-Type"),
    )
