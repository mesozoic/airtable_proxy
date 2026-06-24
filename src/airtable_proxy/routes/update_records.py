"""
PATCH / PUT /v0/{base_id}/{table_id_or_name}[/{record_id}]

Updates record(s) at Airtable. On a 2xx response the local cache is
updated to match the response. PATCH merges with existing cached fields;
PUT replaces them.
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
    Register the update-records routes on the FastAPI app.
    """

    @app.api_route("/v0/{base_id}/{table_id_or_name}", methods=["PATCH", "PUT"])
    async def update_records_multi(
        request: Request, base_id: str, table_id_or_name: str
    ) -> Response:
        return await _handle(request, base_id, table_id_or_name, path_suffix="")

    @app.api_route("/v0/{base_id}/{table_id_or_name}/{record_id}", methods=["PATCH", "PUT"])
    async def update_records_single(
        request: Request, base_id: str, table_id_or_name: str, record_id: str
    ) -> Response:
        return await _handle(request, base_id, table_id_or_name, path_suffix=f"/{record_id}")


async def _handle(
    request: Request, base_id: str, table_id_or_name: str, *, path_suffix: str
) -> Response:
    persistence: AirtablePersistence = request.app.state.persistence

    table_id = resolve_table_id(base_id, table_id_or_name, persistence)
    if table_id is None:
        raise ProxyRequest()

    httpx_response = await forward(request, f"v0/{base_id}/{table_id_or_name}{path_suffix}")

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
    cache_writes.apply_update(
        persistence,
        base_id,
        table_id,
        body,
        response_uses_field_ids=response_uses_field_ids,
        replace=(request.method == "PUT"),
    )
