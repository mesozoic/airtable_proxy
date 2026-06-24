"""
POST /v0/{base_id}/{table_id_or_name}

Creates record(s) at Airtable. On a 2xx response the local cache is
updated to match the response, so reads against the proxy see the new
record(s) without waiting for the webhook poller.
"""

import logging

import httpx
from fastapi import FastAPI, Request, Response

from airtable_proxy import cache_writes
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import ProxyRequest, forward, response_from_httpx
from airtable_proxy.util import resolve_table_id

logger = logging.getLogger(__name__)


def add_routes(app: FastAPI) -> None:
    """
    Register the create-records route on the FastAPI app.
    """

    @app.post("/v0/{base_id}/{table_id_or_name}")
    async def create_records(request: Request, base_id: str, table_id_or_name: str) -> Response:
        persistence: AirtablePersistence = request.app.state.persistence

        table_id = resolve_table_id(base_id, table_id_or_name, persistence)
        if table_id is None:
            raise ProxyRequest()

        httpx_response = await forward(request, f"v0/{base_id}/{table_id_or_name}")

        if 200 <= httpx_response.status_code < 300:
            _apply_to_cache(httpx_response, request, persistence, base_id, table_id)

        return response_from_httpx(httpx_response)


def _apply_to_cache(
    httpx_response: httpx.Response,
    request: Request,
    persistence: AirtablePersistence,
    base_id: str,
    table_id: str,
) -> None:
    try:
        body = httpx_response.json()
    except ValueError:
        logger.warning("Airtable response was not JSON; skipping cache update")
        return
    response_uses_field_ids = request.query_params.get("returnFieldsByFieldId") == "true"
    cache_writes.apply_create(
        persistence,
        base_id,
        table_id,
        body,
        response_uses_field_ids=response_uses_field_ids,
    )
