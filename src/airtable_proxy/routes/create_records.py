"""
POST /v0/{base_id}/{table_id_or_name}

Creates record(s) at Airtable. On a 2xx response the local cache is
updated to match the response, so reads against the proxy see the new
record(s) without waiting for the webhook poller.
"""

from fastapi import FastAPI, Request, Response

from airtable_proxy import cache_writes
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import ProxyRequest, forward, parse_2xx_body, response_from_httpx
from airtable_proxy.util import resolve_table_id


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
        if body := parse_2xx_body(httpx_response):
            use_ids = request.query_params.get("returnFieldsByFieldId") == "true"
            cache_writes.apply_create(
                persistence,
                base_id,
                table_id,
                body,
                response_uses_field_ids=use_ids,
            )
        return response_from_httpx(httpx_response)
