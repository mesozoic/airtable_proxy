"""
DELETE /v0/{base_id}/{table_id_or_name}[/{record_id}]

Deletes record(s) at Airtable. On a 2xx response the local cache is
updated to remove the deleted record(s).
"""

from fastapi import FastAPI, Request, Response

from airtable_proxy import cache_writes
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import ProxyRequest, forward, parse_2xx_body, response_from_httpx
from airtable_proxy.util import resolve_table_id


def add_routes(app: FastAPI) -> None:
    """
    Register the delete-records routes on the FastAPI app.
    """

    @app.delete("/v0/{base_id}/{table_id_or_name}")
    async def delete_records_multi(
        request: Request, base_id: str, table_id_or_name: str
    ) -> Response:
        return await _handle(request, base_id, table_id_or_name, path_suffix="")

    @app.delete("/v0/{base_id}/{table_id_or_name}/{record_id}")
    async def delete_records_single(
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
    if body := parse_2xx_body(httpx_response):
        cache_writes.apply_delete(persistence, base_id, table_id, body)
    return response_from_httpx(httpx_response)
