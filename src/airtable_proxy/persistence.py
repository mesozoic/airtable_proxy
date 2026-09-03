from typing import Any

from pydantic import BaseModel

from airtable_proxy.storage import Storage


class WebhookInfo(BaseModel):
    webhook_id: str
    cursor: int

    @staticmethod
    def key(base_id: str) -> str:
        return f"webhook:{base_id}"


class TableInfo(BaseModel):
    table_name: str

    @staticmethod
    def key(base_id: str, table_id: str) -> str:
        return TableInfo.prefix(base_id) + table_id

    @staticmethod
    def prefix(base_id: str) -> str:
        return f"table:{base_id}:"


class FieldInfo(BaseModel):
    field_name: str
    field_type: str

    @staticmethod
    def key(base_id: str, table_id: str, field_id: str) -> str:
        return FieldInfo.prefix(base_id, table_id) + field_id

    @staticmethod
    def prefix(base_id: str, table_id: str) -> str:
        return f"field:{base_id}:{table_id}:"


class RecordInfo(BaseModel):
    fields: dict[str, Any]
    created_time: str

    @staticmethod
    def key(base_id: str, table_id: str, record_id: str) -> str:
        return RecordInfo.prefix(base_id, table_id) + record_id

    @staticmethod
    def prefix(base_id: str, table_id: str) -> str:
        return f"record:{base_id}:{table_id}:"


class AirtablePersistence:
    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    # Webhook methods

    def get_webhook(self, base_id: str) -> WebhookInfo | None:
        data = self._storage.get(WebhookInfo.key(base_id))
        return WebhookInfo.model_validate(data) if data else None

    def save_webhook(self, base_id: str, webhook_id: str, cursor: int) -> None:
        self._storage.set(
            WebhookInfo.key(base_id),
            WebhookInfo(webhook_id=webhook_id, cursor=cursor),
        )

    # Table methods

    def get_table(self, base_id: str, table_id: str) -> TableInfo | None:
        data = self._storage.get(TableInfo.key(base_id, table_id))
        return TableInfo.model_validate(data) if data else None

    def save_table(self, base_id: str, table_id: str, table_name: str) -> None:
        self._storage.set(
            TableInfo.key(base_id, table_id),
            TableInfo(table_name=table_name),
        )

    def delete_table(self, base_id: str, table_id: str) -> None:
        """Delete a table and all its fields and records."""
        self._storage.delete(TableInfo.key(base_id, table_id))
        for prefix in [
            FieldInfo.prefix(base_id, table_id),
            RecordInfo.prefix(base_id, table_id),
        ]:
            for key in list(self._storage.keys(prefix)):
                self._storage.delete(key)

    def delete_base(self, base_id: str) -> None:
        """
        Delete every cached table (and its fields and records) for a base,
        along with any leftover refresh markers.
        """
        for table_id in list(self.get_tables(base_id)):
            self.delete_table(base_id, table_id)
        base_marker = self._refresh_key(base_id)
        for key in list(self._storage.keys(base_marker)):
            if key != base_marker:
                self._storage.delete(key)

    def get_tables(self, base_id: str) -> dict[str, TableInfo]:
        prefix = TableInfo.prefix(base_id)
        result = {}
        for key in self._storage.keys(prefix):
            table_id = key[len(prefix) :]
            data = self._storage.get(key)
            result[table_id] = TableInfo.model_validate(data)
        return result

    # Field methods

    def get_field(self, base_id: str, table_id: str, field_id: str) -> FieldInfo | None:
        data = self._storage.get(FieldInfo.key(base_id, table_id, field_id))
        return FieldInfo.model_validate(data) if data else None

    def save_field(
        self,
        base_id: str,
        table_id: str,
        field_id: str,
        field_name: str,
        field_type: str,
    ) -> None:
        self._storage.set(
            FieldInfo.key(base_id, table_id, field_id),
            FieldInfo(field_name=field_name, field_type=field_type),
        )

    def delete_field(self, base_id: str, table_id: str, field_id: str) -> None:
        self._storage.delete(FieldInfo.key(base_id, table_id, field_id))

    def get_fields(self, base_id: str, table_id: str) -> dict[str, FieldInfo]:
        prefix = FieldInfo.prefix(base_id, table_id)
        result = {}
        for key in self._storage.keys(prefix):
            field_id = key[len(prefix) :]
            data = self._storage.get(key)
            result[field_id] = FieldInfo.model_validate(data)
        return result

    # Record methods

    def get_record(self, base_id: str, table_id: str, record_id: str) -> RecordInfo | None:
        data = self._storage.get(RecordInfo.key(base_id, table_id, record_id))
        return RecordInfo.model_validate(data) if data else None

    def save_record(
        self,
        base_id: str,
        table_id: str,
        record_id: str,
        fields: dict[str, Any],
        created_time: str,
    ) -> None:
        key = RecordInfo.key(base_id, table_id, record_id)
        self._storage.set(
            key,
            RecordInfo(fields=fields, created_time=created_time),
        )

    def delete_record(self, base_id: str, table_id: str, record_id: str) -> None:
        self._storage.delete(RecordInfo.key(base_id, table_id, record_id))

    def get_records(self, base_id: str, table_id: str) -> dict[str, RecordInfo]:
        prefix = RecordInfo.prefix(base_id, table_id)
        result = {}
        for key in self._storage.keys(prefix):
            record_id = key[len(prefix) :]
            data = self._storage.get(key)
            result[record_id] = RecordInfo.model_validate(data)
        return result

    # Refresh marker methods

    @staticmethod
    def _refresh_key(base_id: str, table_id: str | None = None) -> str:
        # Trailing separator matches TableInfo.prefix etc., so a prefix scan
        # for one base's markers can't match a base whose ID extends it.
        key = f"refreshing:{base_id}:"
        if table_id is not None:
            key += table_id
        return key

    def is_refreshing(self, base_id: str, table_id: str | None = None) -> bool:
        return self._storage.get(self._refresh_key(base_id, table_id)) is not None

    def mark_refresh_started(self, base_id: str, table_id: str | None = None) -> None:
        self._storage.set(self._refresh_key(base_id, table_id), True)

    def mark_refresh_complete(self, base_id: str, table_id: str | None = None) -> None:
        self._storage.delete(self._refresh_key(base_id, table_id))

    # Auth methods

    def has_auth(self, base_id: str, token_hash: str) -> bool:
        return self._storage.get(f"auth:{base_id}:{token_hash}") is not None

    def save_auth(self, base_id: str, token_hash: str) -> None:
        self._storage.set(f"auth:{base_id}:{token_hash}", True)
