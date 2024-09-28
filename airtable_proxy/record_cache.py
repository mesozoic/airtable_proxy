"""
Utilities for remembering and updating records in Airtable bases.
"""

from __future__ import annotations

import functools
import time
from collections import defaultdict
from json import dumps as json_dumps
from pathlib import Path
from typing import Any, Callable, TypeAlias

import diskcache  # type: ignore
import pyairtable
from pyairtable.api.types import RecordDict, RecordId
from pyairtable.models.schema import BaseSchema
from typing_extensions import ParamSpec, TypeVar

T = TypeVar("T")
P = ParamSpec("P")
Records: TypeAlias = "dict[RecordId, RecordDict]"
TableId: TypeAlias = str
FieldId: TypeAlias = str


def rpartial(func: Callable[P, T], *p_args: Any, **p_kwargs: Any) -> Callable[..., T]:
    """
    Like functools.partial, but appends arguments instead of prepending them.
    """

    @functools.wraps(func)
    def _wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        return func(*args, *p_args, **p_kwargs, **kwargs)

    return _wrapped


def key(obj: Any, suffix: str) -> str:
    if not isinstance(obj, (str, int)):
        try:
            obj = obj["id"]
        except (KeyError, TypeError):
            try:
                obj = obj.id
            except AttributeError:
                obj = obj.name
    return f"{obj}/{suffix}"


hook_key = rpartial(key, "webhook")
cursor_key = rpartial(key, "webhook/cursor")
tables_key = rpartial(key, "tables")
records_key = rpartial(key, "records")
schema_key = rpartial(key, "schema")
fields_key = rpartial(key, "fields")


class RecordCache:
    """
    Wraps around a persisted cache or database to store record information.

    Assumes a flat key-value store, so uses the following key conventions:

        * ``{base_id}/webhook`` - the webhook ID that we use to poll for data changes
        * ``{base_id}/webhook/cursor`` - the next cursor to use when fetching webhook payloads
        * ``{base_id}/tables`` - a list of table IDs in the given base
        * ``{base_id}/schema`` - the full schema of every table in the base
        * ``{table_id}/records`` - every record in the table, keyed by ID
        * ``{table_id}/schema`` - the full schema of the given table
        * ``{table_id}/fields`` - a mapping of field IDs to field information
        * ``{record_id}`` - a single Airtable record

    Each key will also have corresponding metadata keys, in the following format:

        * ``{key}:ts`` - Unix timestamp of when the key's data was last fetched
    """

    def __init__(self, location: Path, api: pyairtable.Api):
        self.location = location
        self.api = api
        self._cache = diskcache.Cache(
            directory=location,
            size_limit=int(4e9),
            cull_limit=0,
        )

    def dump(self) -> dict[str, Any]:
        return {key: self.get(key) for key in self._cache.iterkeys()}

    def set(self, key: str, value: Any, ts: float | None = None) -> None:
        ts = time.time() if ts is None else ts
        self._cache.set(key, value, expire=None, retry=True)
        self._cache.set(key + ":ts", ts, expire=None, retry=None)

    def get(self, key: str, /, default: Any = None) -> Any:
        return self._cache.get(key, default=default)

    def get_with_ts(self, key: str, /, default: Any = None) -> tuple[Any, int]:
        return (self.get(key, default=default), self.get(key + ":ts"))

    def set_records(
        self,
        table: pyairtable.Table | str,
        records: list[RecordDict] | Records,
        ts: float | None = None,
    ) -> None:
        ts = time.time() if ts is None else ts
        if isinstance(records, list):
            records = {record["id"]: record for record in records}
        json = json_dumps(
            {"records": self.convert_field_ids(table, list(records.values()))}
        )
        self.set(records_key(table), records, ts=ts)
        self.set(records_key(table) + "/json", json, ts=ts)

    def reload(self, base: pyairtable.Base) -> None:
        schema = self.reload_base_schema(base)
        tables = [base.table(t.id) for t in schema.tables]
        for table in tables:
            self.reload_table(table)

    def reload_base_schema(self, base: pyairtable.Base) -> BaseSchema:
        schema = base.schema()
        self.set(schema_key(base), schema._raw)
        self.set(tables_key(base), [t.id for t in schema.tables])
        for table_schema in schema.tables:
            fields_by_id = {f.id: f.dict() for f in table_schema.fields}
            self.set(schema_key(table_schema), table_schema.dict())
            self.set(fields_key(table_schema), fields_by_id)
        return schema

    def reload_table(self, table: pyairtable.Table) -> None:
        records_ts = time.time()
        records = table.all(use_field_ids=True)
        self.set_records(table, records, ts=records_ts)
        for record in records:
            self.set(record["id"], record, ts=records_ts)

    def reload_records(self, table: pyairtable.Table, record_ids: list[str]) -> None:
        formula = "OR(%s)" % ", ".join(
            f"RECORD_ID()={record_id!r}" for record_id in record_ids
        )
        records: Records = self.get(records_key(table), {})
        updated_ts = time.time()
        updated = table.all(formula=formula, use_field_ids=True)
        records.update({record["id"]: record for record in updated})
        self.set_records(table, list(records.values()), ts=updated_ts)
        for record in updated:
            self.set(record["id"], record, ts=updated_ts)

    def delete_records(self, table: pyairtable.Table, record_ids: list[str]) -> None:
        records: Records = self.get(records_key(table), {})
        records_ts = self.get(records_key(table) + ":ts")  # preserve timestamp
        if not (records and record_ids):
            return
        for deleted_id in record_ids:
            records.pop(deleted_id, None)
        self.set(records_key(table), records, ts=records_ts)
        for deleted_id in record_ids:
            self._cache.delete(deleted_id)

    def convert_field_ids(
        self,
        table: pyairtable.Table | str,
        records: list[RecordDict],
    ) -> list[RecordDict]:
        fields_by_id = self.get(fields_key(table), {})
        return [
            {
                "id": record["id"],
                "createdTime": record["createdTime"],
                "fields": {
                    fields_by_id[field_id]["name"]: field_value
                    for (field_id, field_value) in record["fields"].items()
                },
            }
            for record in records
        ]

    def poll(self, base_id: str) -> None:
        base = self.api.base(base_id)
        webhook = base.webhook(self.get(hook_key(base)))
        cursor = self.get(cursor_key(base), 1)
        destroyed_tables: list[TableId] = []
        destroyed_fields: dict[TableId, list[FieldId]] = defaultdict(list)
        destroyed_records: dict[TableId, list[RecordId]] = defaultdict(list)
        tables_with_renamed_fields: set[TableId] = set()
        created_tables: list[TableId] = []
        changed_tables: list[TableId] = []
        changed_records: dict[TableId, list[RecordId]] = defaultdict(list)

        # Load up a list of all the changes we need to make at once,
        # so we can perform them in fewer trips to the database.
        #
        # This is a tradeoff vs freshness of data, since we might spend
        # a long time iterating through the list of payloads. We can
        # reconsider this tradeoff at any point.
        #
        for payload in webhook.payloads(cursor=cursor):
            created_tables.extend(payload.created_tables_by_id)
            destroyed_tables.extend(payload.destroyed_table_ids)
            changed_tables.extend(payload.changed_tables_by_id)
            for table_id, table_change in payload.changed_tables_by_id.items():
                destroyed_fields[table_id].extend(table_change.destroyed_field_ids)
                destroyed_records[table_id].extend(table_change.destroyed_record_ids)
                changed_records[table_id].extend(table_change.changed_records_by_id)
                for field_change in table_change.changed_fields_by_id.values():
                    if (
                        field_change.previous
                        and field_change.current
                        and field_change.previous != field_change.current
                    ):
                        tables_with_renamed_fields.add(table_id)

        if payload.cursor is not None:
            self.set(cursor_key(base), payload.cursor + 1)

        # This series of steps is inefficient; we will read and write
        # the 'records' key/value pair several times. Optimization is
        # saved for a future point where the algorithm is reliable.

        for table_id in destroyed_tables:
            self.destroy_table(table_id)

        for table_id, field_ids in destroyed_fields.items():
            self.destroy_fields(table_id, field_ids)

        for table_id, record_ids in destroyed_records.items():
            self.destroy_records(table_id, record_ids)

        if destroyed_tables or created_tables or changed_tables:
            self.reload_base_schema(base)

        for table_id in created_tables:
            self.reload_table(base.table(table_id))

        for table_id, record_ids in changed_records.items():
            self.reload_records(base.table(table_id), record_ids)

        for table_id in tables_with_renamed_fields:
            if table_id not in changed_records:
                self.rebuild_table_json(table_id)

    def destroy_table(self, table_id: str) -> None:
        self._cache.delete(records_key(table_id))
        self._cache.delete(schema_key(table_id))
        self._cache.delete(fields_key(table_id))

    def destroy_fields(self, table_id: str, field_ids: list[str]) -> None:
        records: Records = self.get(records_key(table_id), {})
        for record_id, record in records.items():
            for field_id in field_ids:
                try:
                    del record["fields"][field_id]
                except KeyError:
                    pass
            self.set(record_id, record)

        self.set_records(table_id, records)

    def destroy_records(self, table_id: str, record_ids: list[str]) -> None:
        records: Records = self.get(records_key(table_id), {}).items()
        self.set_records(
            table_id,
            {
                record_id: record
                for (record_id, record) in records.items()
                if record_id not in record_ids
            },
        )
        for record_id in record_ids:
            self._cache.delete(record_id)

    def rebuild_table_json(self, table_id: str) -> None:
        """
        Regenerate the precomputed JSON for a table's records, so that
        any new field names get
        """
        records: Records = self.get(records_key(table_id), {})
        self.set_records(table_id, records)
