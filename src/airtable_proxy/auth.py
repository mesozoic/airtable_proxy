"""
Bearer token authentication for cached routes.
"""

import hashlib

import httpx
from fastapi import HTTPException, Request

from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import AIRTABLE_API_BASE, ProxyRequest


def hash_token(token: str) -> str:
    """
    Return the SHA-256 hex digest of a bearer token.
    """
    return hashlib.sha256(token.encode()).hexdigest()


async def require_auth(
    request: Request,
    base_id: str,
    persistence: AirtablePersistence,
) -> None:
    """
    Validate the caller's bearer token for a given base.

    Checks the token hash against local storage. On a cache miss,
    verifies the token by hitting Airtable's list-records endpoint
    with maxRecords=1.

    Raises:
        HTTPException(401) if no Authorization header is present.
        HTTPException(403) if the token is invalid for this base.
        ProxyRequest if no tables exist for this base (can't verify).
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401)

    token = auth_header.removeprefix("Bearer ")
    token_hash = hash_token(token)

    # Check if we have any tables to work with
    tables = persistence.get_tables(base_id)
    if not tables:
        raise ProxyRequest()

    if persistence.has_auth(base_id, token_hash):
        return

    table_id = next(iter(tables))
    url = f"{AIRTABLE_API_BASE}/v0/{base_id}/{table_id}"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            params={"maxRecords": "1"},
            headers={"Authorization": auth_header},
        )

    if response.is_success:
        persistence.save_auth(base_id, token_hash)
        return

    raise HTTPException(status_code=403)
