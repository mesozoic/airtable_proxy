"""Shared helpers for routes that read from local storage."""

from typing import Any

from airtable_proxy.persistence import AirtablePersistence, FieldInfo, RecordInfo


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


def resolve_table_id(
    base_id: str,
    table_id_or_name: str,
    persistence: AirtablePersistence,
) -> str | None:
    """
    Resolve a table ID or name to a table ID.

    Returns None if the table is not found in local storage.
    """
    if table_id_or_name.startswith("tbl"):
        if persistence.get_table(base_id, table_id_or_name) is not None:
            return table_id_or_name

    for table_id, info in persistence.get_tables(base_id).items():
        if info.table_name == table_id_or_name:
            return table_id

    return None


def format_record_fields(
    record: RecordInfo,
    field_info: dict[str, FieldInfo],
    *,
    return_fields_by_field_id: bool,
    include_field_ids: set[str] | None = None,
) -> dict[str, Any]:
    """
    Build the `fields` dict for an API response from a stored record.

    Omits empty values (per `is_empty_value`). Keys output by field ID when
    `return_fields_by_field_id` is true, otherwise by field name (falling back
    to the field ID if no name is known). When `include_field_ids` is given,
    only those field IDs are kept.
    """
    output: dict[str, Any] = {}
    for field_id, value in record.fields.items():
        if include_field_ids is not None and field_id not in include_field_ids:
            continue
        if is_empty_value(value):
            continue

        if return_fields_by_field_id:
            output[field_id] = value
        else:
            info = field_info.get(field_id)
            output[info.field_name if info is not None else field_id] = value

    return output
