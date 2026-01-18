from typing import Any

from airtable_proxy.storage import Storage


def _webhook_key(base_id: str) -> str:
    return f"webhook:{base_id}"


def _table_key(base_id: str, table_id: str) -> str:
    return _table_prefix(base_id) + table_id


def _table_prefix(base_id: str) -> str:
    return f"table:{base_id}:"


def _record_key(base_id: str, table_id: str, record_id: str) -> str:
    return f"record:{base_id}:{table_id}:{record_id}"


def _record_prefix(base_id: str, table_id: str) -> str:
    return f"record:{base_id}:{table_id}:"


class AirtablePersistence:
    def __init__(self, storage: Storage):
        self._storage = storage

    # Webhook methods

    def get_webhook(self, base_id: str) -> dict[str, Any] | None:
        return self._storage.get(_webhook_key(base_id))

    def save_webhook(self, base_id: str, webhook_id: str, cursor: int) -> None:
        self._storage.set(_webhook_key(base_id), {"webhook_id": webhook_id, "cursor": cursor})

    # Table methods

    def get_table(self, base_id: str, table_id: str) -> dict[str, Any] | None:
        return self._storage.get(_table_key(base_id, table_id))

    def save_table(self, base_id: str, table_id: str, table_name: str) -> None:
        self._storage.set(_table_key(base_id, table_id), {"table_name": table_name})

    def get_tables(self, base_id: str) -> dict[str, dict[str, Any]]:
        prefix = _table_prefix(base_id)
        result = {}
        for key in self._storage.keys(prefix):
            table_id = key[len(prefix) :]
            result[table_id] = self._storage.get(key)
        return result

    # Record methods

    def get_record(self, base_id: str, table_id: str, record_id: str) -> dict[str, Any] | None:
        return self._storage.get(_record_key(base_id, table_id, record_id))

    def save_record(self, base_id: str, table_id: str, record_id: str, fields: dict[str, Any], created_time: str) -> None:
        self._storage.set(_record_key(base_id, table_id, record_id), {"fields": fields, "created_time": created_time})

    def delete_record(self, base_id: str, table_id: str, record_id: str) -> None:
        self._storage.delete(_record_key(base_id, table_id, record_id))

    def get_records(self, base_id: str, table_id: str) -> dict[str, dict[str, Any]]:
        prefix = _record_prefix(base_id, table_id)
        result = {}
        for key in self._storage.keys(prefix):
            record_id = key[len(prefix) :]
            result[record_id] = self._storage.get(key)
        return result
