"""
Get a single record from local storage, matching the Airtable API response format.
"""

from typing import Any

from fastapi import FastAPI, Request

from airtable_proxy.auth import require_auth
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import ProxyRequest
from airtable_proxy.util import format_record_fields, resolve_table_id


def add_routes(app: FastAPI) -> None:
    """
    Register get record routes on the FastAPI app.
    """

    @app.get("/v0/{base_id}/{table_id_or_name}/{record_id}")
    async def get_record(
        request: Request,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
        returnFieldsByFieldId: bool = False,
        cellFormat: str | None = None,
    ) -> dict[str, Any]:
        """
        Return a single record. Falls back to the proxy when local storage
        cannot satisfy the request.
        """
        if cellFormat == "string":
            raise ProxyRequest()

        persistence: AirtablePersistence = request.app.state.persistence

        table_id = resolve_table_id(base_id, table_id_or_name, persistence)
        if table_id is None:
            raise ProxyRequest()
        if persistence.is_refreshing(base_id, table_id):
            raise ProxyRequest()

        await require_auth(request, base_id, persistence)

        record = persistence.get_record(base_id, table_id, record_id)
        if record is None:
            raise ProxyRequest()

        field_info = persistence.get_fields(base_id, table_id)
        output_fields = format_record_fields(
            record,
            field_info,
            return_fields_by_field_id=returnFieldsByFieldId,
        )

        return {
            "id": record_id,
            "createdTime": record.created_time,
            "fields": output_fields,
        }
