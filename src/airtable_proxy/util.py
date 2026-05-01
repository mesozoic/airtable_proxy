"""Shared helpers for routes that read from local storage."""

from typing import Any

from airtable_proxy.persistence import AirtablePersistence


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
