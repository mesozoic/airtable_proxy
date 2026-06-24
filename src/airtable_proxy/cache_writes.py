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
    return {info.field_name: fid for fid, info in persistence.get_fields(base_id, table_id).items()}


def _translate_fields(fields: dict[str, Any], name_to_id: dict[str, str] | None) -> dict[str, Any]:
    if name_to_id is None:
        return dict(fields)
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key in name_to_id:
            out[name_to_id[key]] = value
        else:
            logger.debug("Skipping unknown field key %r in cache write", key)
    return out
