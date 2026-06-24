"""
Pure functions that translate Airtable mutation responses into local cache
updates. No HTTP or FastAPI dependencies — easy to unit test.

These functions are defensive about response shape: when a field key cannot
be resolved or a required key is missing they log and skip the affected
record/field rather than raising. The webhook poller will reconcile any
gaps within the next poll cycle. Storage exceptions are allowed to
propagate because they indicate bugs, not Airtable-side outcomes.
"""

import logging
from typing import Any

from airtable_proxy.persistence import AirtablePersistence

logger = logging.getLogger(__name__)


def apply_create(
    persistence: AirtablePersistence,
    base_id: str,
    table_id: str,
    body: dict[str, Any],
    *,
    response_uses_field_ids: bool,
) -> None:
    """
    Apply a successful POST response to the local cache.
    """
    records = _records_from_body(body)
    name_to_id = None if response_uses_field_ids else _name_to_id(persistence, base_id, table_id)
    for record in records:
        record_id = record.get("id")
        if not record_id:
            logger.warning("Skipping create: response record missing 'id'")
            continue
        created_time = record.get("createdTime", "")
        fields = _translate_fields(record.get("fields", {}), name_to_id)
        persistence.save_record(
            base_id, table_id, record_id, fields=fields, created_time=created_time
        )


def apply_update(
    persistence: AirtablePersistence,
    base_id: str,
    table_id: str,
    body: dict[str, Any],
    *,
    response_uses_field_ids: bool,
    replace: bool = False,
) -> None:
    """
    Apply a successful PATCH or PUT response to the local cache.

    With `replace=False` (default, PATCH semantics) the response fields are
    merged with the existing cached record. With `replace=True` (PUT
    semantics) the response fields replace the cached fields entirely.
    """
    records = _records_from_body(body)
    name_to_id = None if response_uses_field_ids else _name_to_id(persistence, base_id, table_id)
    for record in records:
        record_id = record.get("id")
        if not record_id:
            logger.warning("Skipping update: response record missing 'id'")
            continue
        new_fields = _translate_fields(record.get("fields", {}), name_to_id)
        existing = persistence.get_record(base_id, table_id, record_id)
        if existing is None or replace:
            merged_fields = new_fields
            created_time = record.get("createdTime") or (existing.created_time if existing else "")
        else:
            merged_fields = {**existing.fields, **new_fields}
            created_time = existing.created_time
        persistence.save_record(
            base_id, table_id, record_id, fields=merged_fields, created_time=created_time
        )


def apply_delete(
    persistence: AirtablePersistence,
    base_id: str,
    table_id: str,
    body: dict[str, Any],
) -> None:
    """
    Apply a successful DELETE response to the local cache.

    Handles both single-record (`{"id": ..., "deleted": true}`) and
    multi-record (`{"records": [{"id": ..., "deleted": true}, ...]}`)
    response shapes. A request to delete a record we don't have cached
    is a no-op.
    """
    if isinstance(body.get("records"), list):
        ids = [r.get("id") for r in body["records"] if isinstance(r, dict)]
    elif "id" in body:
        ids = [body.get("id")]
    else:
        ids = []
    for record_id in ids:
        if not record_id:
            logger.warning("Skipping delete: response record missing 'id'")
            continue
        persistence.delete_record(base_id, table_id, record_id)


def _records_from_body(body: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Normalize Airtable's two response shapes to a list of record dicts:

    - Single-record:  {"id": ..., "createdTime": ..., "fields": ...}
    - Multi-record:   {"records": [ {...}, {...} ], ...}
    """
    if isinstance(body.get("records"), list):
        return [r for r in body["records"] if isinstance(r, dict)]
    if "id" in body:
        return [body]
    return []


def _name_to_id(persistence: AirtablePersistence, base_id: str, table_id: str) -> dict[str, str]:
    """
    Build a lookup map from field name → field ID for the given table.
    """
    return {info.field_name: fid for fid, info in persistence.get_fields(base_id, table_id).items()}


def _translate_fields(fields: dict[str, Any], name_to_id: dict[str, str] | None) -> dict[str, Any]:
    """
    Translate field keys in *fields* from names to IDs using *name_to_id*.

    When *name_to_id* is ``None`` the response already uses field IDs, so the
    fields dict is returned as-is. Unknown field names are logged and dropped.
    """
    if name_to_id is None:
        return dict(fields)
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key in name_to_id:
            out[name_to_id[key]] = value
        else:
            logger.debug("Skipping unknown field key %r in cache write", key)
    return out
