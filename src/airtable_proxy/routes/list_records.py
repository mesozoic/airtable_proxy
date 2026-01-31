"""
List records from local storage, matching the Airtable API response format.
"""

from typing import Any

from fastapi import FastAPI, Query, Request

from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import ProxyRequest


def resolve_table_id(
    base_id: str,
    table_id_or_name: str,
    persistence: AirtablePersistence,
) -> str | None:
    """
    Resolve a table ID or name to a table ID.

    Returns None if the table is not found in local storage.
    """
    # If it looks like a table ID, check directly first
    if table_id_or_name.startswith("tbl"):
        if persistence.get_table(base_id, table_id_or_name) is not None:
            return table_id_or_name

    # Search by name
    for table_id, info in persistence.get_tables(base_id).items():
        if info.table_name == table_id_or_name:
            return table_id

    return None


def is_empty_value(value: Any) -> bool:
    """
    Check if a value is considered "empty" by Airtable.

    Airtable omits fields with empty values (None, "", [], False) from responses.
    """
    if value is None:
        return True
    if value == "":
        return True
    if value == []:
        return True
    if value is False:
        return True
    return False


def add_routes(app: FastAPI) -> None:
    """
    Register list records routes on the FastAPI app.
    """

    @app.get("/v0/{base_id}/{table_id_or_name}")
    def list_records(
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

        # Build field ID/name mappings
        field_info = persistence.get_fields(base_id, table_id)
        field_id_to_name = {fid: info.field_name for fid, info in field_info.items()}
        field_name_to_id = {info.field_name: fid for fid, info in field_info.items()}

        # Resolve requested fields to a set of field IDs
        include_field_ids: set[str] | None = None
        if fields is not None:
            include_field_ids = set()
            for f in fields:
                if f in field_info:
                    include_field_ids.add(f)
                elif f in field_name_to_id:
                    include_field_ids.add(field_name_to_id[f])

        # Build response
        all_records = persistence.get_records(base_id, table_id)
        result_records: list[dict[str, Any]] = []

        for record_id, record_info in all_records.items():
            output_fields: dict[str, Any] = {}
            for field_id, value in record_info.fields.items():
                if include_field_ids is not None and field_id not in include_field_ids:
                    continue
                if is_empty_value(value):
                    continue

                if returnFieldsByFieldId:
                    output_fields[field_id] = value
                else:
                    output_fields[field_id_to_name.get(field_id, field_id)] = value

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
