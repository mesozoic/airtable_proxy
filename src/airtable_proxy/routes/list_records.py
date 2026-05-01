"""
List records from local storage, matching the Airtable API response format.
"""

from typing import Any

from fastapi import FastAPI, Query, Request

from airtable_proxy.auth import require_auth
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import ProxyRequest
from airtable_proxy.util import format_record_fields, resolve_table_id


def add_routes(app: FastAPI) -> None:
    """
    Register list records routes on the FastAPI app.
    """

    @app.get("/v0/{base_id}/{table_id_or_name}")
    async def list_records(
        request: Request,
        base_id: str,
        table_id_or_name: str,
        maxRecords: int | None = None,
        fields: list[str] | None = Query(None),
        returnFieldsByFieldId: bool = False,
        view: str | None = None,
        filterByFormula: str | None = None,
        cellFormat: str | None = None,
    ) -> dict[str, Any]:
        """
        List records from a table. Returns records from local storage,
        or proxies to Airtable when necessary.
        """
        if view:
            raise ProxyRequest()
        if filterByFormula:
            raise ProxyRequest()
        if cellFormat == "string":
            raise ProxyRequest()

        persistence: AirtablePersistence = request.app.state.persistence

        table_id = resolve_table_id(base_id, table_id_or_name, persistence)
        if table_id is None:
            raise ProxyRequest()

        await require_auth(request, base_id, persistence)

        field_info = persistence.get_fields(base_id, table_id)
        field_name_to_id = {info.field_name: fid for fid, info in field_info.items()}

        include_field_ids: set[str] | None = None
        if fields is not None:
            include_field_ids = set()
            for f in fields:
                if f in field_info:
                    include_field_ids.add(f)
                elif f in field_name_to_id:
                    include_field_ids.add(field_name_to_id[f])

        all_records = persistence.get_records(base_id, table_id)
        result_records: list[dict[str, Any]] = []

        for record_id, record_info in all_records.items():
            output_fields = format_record_fields(
                record_info,
                field_info,
                return_fields_by_field_id=returnFieldsByFieldId,
                include_field_ids=include_field_ids,
            )
            result_records.append(
                {
                    "id": record_id,
                    "createdTime": record_info.created_time,
                    "fields": output_fields,
                }
            )

            if maxRecords is not None and len(result_records) >= maxRecords:
                break

        return {"records": result_records}
