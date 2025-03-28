"""
Utilities for remembering and updating records in Airtable bases.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Iterable, TypeAlias

import diskcache  # type: ignore
import pyairtable
from pyairtable.api.types import (
    RecordDict,
    RecordId,
    assert_typed_dict,
    assert_typed_dicts,
)
from pyairtable.models import Webhook, WebhookPayload
from pyairtable.models.schema import BaseSchema
from pyairtable.utils import chunked
from typing_extensions import ParamSpec, TypeVar

T = TypeVar("T")
P = ParamSpec("P")
Records: TypeAlias = "dict[RecordId, RecordDict]"
TableId: TypeAlias = str
FieldId: TypeAlias = str


class RecordCache:
    """
    Wraps around a persisted cache or database to store record information.
    """

    def __init__(
        self,
        location: Path | str,
        api: pyairtable.Api,
        *,
        size_limit: int = 2**33,  # 8 GB
    ):
        self.location = location if isinstance(location, Path) else Path(location)
        self.api = api
        self.persisted = diskcache.Cache(
            location,
            size_limit=size_limit,
            cull_limit=0,
        )

    def clear(self) -> None:
        """
        Clear the cache.
        """
        self.persisted.clear()

    def reload_base(self, base: str | pyairtable.Base) -> None:
        base_id = base.id if isinstance(base, pyairtable.Base) else base
        base_schema = self.reload_base_schema(base_id)
        for table_schema in base_schema.tables:
            self.reload_table(base_id, table_schema.id)

    def remove_base(self, base_id: str) -> None:
        """
        Remove all data and metadata for the given base.
        """
        self.persisted.set(
            Keys.tracked_bases,
            self.persisted.get(Keys.tracked_bases, set()) - {base_id},
        )
        for table_schema in self.base_schema(base_id).tables:
            self.remove_table(base_id, table_schema.id)
        self.persisted.delete(Keys.webhook(base_id))
        self.persisted.delete(Keys.webhook_cursor(base_id))
        self.persisted.delete(Keys.schema(base_id))

    def webhook(self, base_id: str) -> Webhook:
        """
        Return the webhook for the given base, creating it if necessary,
        along with the cursor we should use to poll for changes.
        """
        cache_key = Keys.webhook(base_id)
        try:
            webhook_id = self.persisted[cache_key]
        except KeyError:
            created = self.api.base(base_id).add_webhook(
                notify_url="",
                spec={
                    "filters": {
                        "dataTypes": ["tableData", "tableFields", "tableMetadata"],
                    },
                    "includes": {
                        "includeCellValuesInFieldIds": "all",
                    },
                },
            )
            self.persisted[cache_key] = created.id
            self.persisted[Keys.webhook_cursor(base_id)] = 1
            webhook_id = created.id
        return self.api.base(base_id).webhook(webhook_id)

    def poll(self, base_id: str) -> None:
        """
        Poll the webhook on this base for changes, and update the cache accordingly.
        """
        webhook = self.webhook(base_id)
        cursor_key = Keys.webhook_cursor(base_id)
        cursor = self.persisted.get(cursor_key, 1)
        payloads = list(webhook.payloads(cursor=cursor))
        self.apply_payloads(base_id, payloads)
        if payloads[-1].cursor is not None:
            self.persisted[cursor_key] = payloads[-1].cursor + 1

    def apply_payloads(
        self,
        base_id: str,
        payloads: Iterable[WebhookPayload],
    ) -> None:
        """
        Apply the changes in the given webhook payloads to the cache.
        """
        raise NotImplementedError("definitely has bugs")

        destroyed_tables: list[TableId] = []
        destroyed_fields: dict[TableId, list[FieldId]] = defaultdict(list)
        destroyed_records: dict[TableId, list[RecordId]] = defaultdict(list)
        tables_with_renamed_fields: set[TableId] = set()
        created_tables: list[TableId] = []
        changed_tables: list[TableId] = []
        changed_records: dict[TableId, list[RecordId]] = defaultdict(list)

        # Load up a list of all the changes we need to make at once,
        # so we can perform them in fewer trips to the API.
        #
        # This is a tradeoff vs freshness of data, since we might spend
        # a long time iterating through the list of payloads. We can
        # reconsider this tradeoff at any point.
        #
        for payload in payloads:
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

        for table_id in destroyed_tables:
            self.remove_table(base_id, table_id)

        for table_id, record_ids in destroyed_records.items():
            if table_id not in destroyed_tables:
                self.remove_records(base_id, table_id, record_ids)

        for table_id, field_ids in destroyed_fields.items():
            if table_id not in destroyed_tables:
                self.remove_fields(base_id, table_id, field_ids)

        if destroyed_tables or created_tables or changed_tables:
            self.reload_base_schema(base_id)

        reload_tables = [*created_tables, *tables_with_renamed_fields]
        for table_id in reload_tables:
            if table_id not in destroyed_tables:
                self.reload_table(base_id, table_id)

        for table_id, record_ids in changed_records.items():
            if table_id in destroyed_tables or table_id in reload_tables:
                continue
            self.reload_records(base_id, table_id, record_ids)

    def base_schema(self, base_id: str) -> BaseSchema:
        """
        Retrieve the schema for the given base from the cache.
        """
        try:
            return BaseSchema(**self.persisted[Keys.schema(base_id)])
        except KeyError:
            return self.reload_base_schema(base_id)

    def reload_base_schema(self, base_id: str) -> BaseSchema:
        """
        Re-read the schema for the given base, and update the cache.
        """
        schema = self.api.base(base_id).schema(force=True)
        self.persisted[Keys.schema(base_id)] = schema._raw
        return schema

    def reload_table(self, base_id: str, table_id_or_name: str) -> None:
        """
        Re-fetch all records for the given table in the given base.
        """
        table = self.api.base(base_id).table(table_id_or_name)
        records = table.all(use_field_ids=True)
        self.update_records(base_id, table_id_or_name, records, replace=True)

    def reload_records(
        self,
        base_id: str,
        table_id_or_name: str,
        record_ids: Iterable[RecordId],
    ) -> None:
        """
        Re-fetch a subset of records for the given table in the given base.
        """
        table = self.api.base(base_id).table(table_id_or_name)
        # passing over 100 conditions at once tends to hang the API request
        formulas = [
            "OR(%s)" % ", ".join(f"RECORD_ID()={record_id!r}" for record_id in chunk)
            for chunk in chunked(list(record_ids), 100)
        ]
        records = [
            record
            for formula in formulas
            for record in table.all(formula=formula, use_field_ids=True)
        ]
        self.update_records(base_id, table_id_or_name, records, replace=False)

    def get_records(
        self, base_id: str, table_id_or_name: str, *, use_field_ids: bool = False
    ) -> list[RecordDict]:
        """
        Get all cached records, or retrieve them from the API and store them.
        """
        if use_field_ids:
            cache_key = Keys.records_using_ids(base_id, table_id_or_name)
        else:
            cache_key = Keys.records(base_id, table_id_or_name)
        try:
            return assert_typed_dicts(RecordDict, self.persisted[cache_key])
        except KeyError:
            self.reload_table(base_id, table_id_or_name)
            return assert_typed_dicts(RecordDict, self.persisted[cache_key])

    def update_records(
        self,
        base_id: str,
        table_id_or_name: str,
        records: Iterable[RecordDict],
        *,
        replace: bool = False,
    ) -> None:
        """
        Add to (or replace) cached records for the given table in the given base.

        Stores several kinds of cache keys:

            * ``${base_id}/${table_id}``
            * ``${base_id}/${table_id}:use_field_ids``
            * ``${base_id}/${table_id}/${record_id}``
            * ``${base_id}/${table_id}/${record_id}:use_field_ids``
            * ``${base_id}/${table_name}``
            * ``${base_id}/${table_name}:use_field_ids``
            * ``${base_id}/${table_name}/${record_id}``
            * ``${base_id}/${table_name}/${record_id}:use_field_ids``
        """
        table_schema = self.base_schema(base_id).table(table_id_or_name)
        table_tag = Keys.table(base_id, table_schema.id)
        if replace:
            self.persisted.evict(table_tag)

        # Cache a list of all records for each table, with and without field IDs.
        # This can be expensive if there are many records, so we do it now
        # instead of on every get_records() call.
        for table_key in (table_schema.id, table_schema.name):
            for table_cache_key, field_attr in [
                (Keys.records_using_ids(base_id, table_key), "id"),
                (Keys.records(base_id, table_key), "name"),
            ]:
                replacements = self.persisted.get(table_cache_key, []) + [
                    {
                        "id": record["id"],
                        "createdTime": record["createdTime"],
                        "fields": {
                            getattr(table_schema.field(field_id), field_attr): value
                            for field_id, value in record["fields"].items()
                        },
                    }
                    for record in records
                ]
                self.persisted.set(table_cache_key, value=replacements, tag=table_tag)

            # Cache each individual record, with and without field IDs
            for record in records:
                for record_key, field_attr in [
                    (Keys.record_using_ids(base_id, table_key, record["id"]), "id"),
                    (Keys.record(base_id, table_key, record["id"]), "name"),
                ]:
                    self.persisted.set(
                        record_key,
                        tag=table_tag,
                        value={
                            "id": record["id"],
                            "createdTime": record["createdTime"],
                            "fields": {
                                getattr(table_schema.field(field_id), field_attr): value
                                for field_id, value in record["fields"].items()
                            },
                        },
                    )

    def get_record(
        self,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
        *,
        use_field_ids: bool = False,
    ) -> RecordDict:
        """
        Get a single record by its ID, or retrieve it from the API and store it.
        """
        key_fn = Keys.record_using_ids if use_field_ids else Keys.record
        key = key_fn(base_id, table_id_or_name, record_id)
        try:
            return assert_typed_dict(RecordDict, self.persisted[key])
        except KeyError:
            self.reload_records(base_id, table_id_or_name, [record_id])
            return assert_typed_dict(RecordDict, self.persisted[key])

    def remove_table(self, base_id: str, table_id_or_name: str) -> None:
        """
        Remove all records and schema information for the given table.
        """
        try:
            table_schema = self.base_schema(base_id).table(table_id_or_name)
        except KeyError:
            # We don't have schema information for this table anymore,
            # so make best effort to clear what we can.
            self.persisted.delete(Keys.records(base_id, table_id_or_name))
            self.persisted.delete(Keys.records_using_ids(base_id, table_id_or_name))
        else:
            self.persisted.evict(Keys.table(base_id, table_schema.id))

    def remove_records(
        self, base_id: str, table_id: str, record_ids: Iterable[str]
    ) -> None:
        """
        Remove the given records from the cache.
        """
        record_ids = list(record_ids)
        records = self.get_records(base_id, table_id, use_field_ids=True)
        records = [record for record in records if record["id"] not in record_ids]
        self.update_records(base_id, table_id, records, replace=True)

    def remove_fields(
        self, base_id: str, table_id: str, field_ids: Iterable[str]
    ) -> None:
        """
        Remove the given fields from all cached records in the given table.
        """
        field_ids = list(field_ids)
        records = self.get_records(base_id, table_id, use_field_ids=True)
        for record in records:
            for field_id in field_ids:
                record["fields"].pop(field_id, None)
        self.update_records(base_id, table_id, records, replace=True)


class Keys:
    tracked_bases = "base_ids"

    @staticmethod
    def webhook(base: str) -> str:
        return f"{base}/webhook"

    @staticmethod
    def webhook_cursor(base: str) -> str:
        return f"{base}/webhook/cursor"

    @staticmethod
    def table(base: str, table: str) -> str:
        return f"{base}/tables/{table}"

    @staticmethod
    def records(base: str, table: str) -> str:
        return f"{base}/tables/{table}/records"

    @staticmethod
    def records_using_ids(base: str, table: str) -> str:
        return f"{base}/tables/{table}/records:use_field_ids"

    @staticmethod
    def record(base: str, table: str, record_id: str) -> str:
        return f"{base}/tables/{table}/{record_id}/records"

    @staticmethod
    def record_using_ids(base: str, table: str, record_id: str) -> str:
        return f"{base}/tables/{table}/{record_id}/records:use_field_ids"

    # Keys prefixed with "@" represent an exact path to the Airtable API.

    @staticmethod
    def schema(base: str) -> str:
        return f"@meta/bases/{base}/tables"
