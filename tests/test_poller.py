import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from pyairtable import Api
from pyairtable.models.webhook import WebhookPayload
from pyairtable.testing import MockAirtable

from airtable_proxy import poller
from airtable_proxy.config import BaseConfig, Config
from airtable_proxy.persistence import (
    AirtablePersistence,
    FieldInfo,
    RecordInfo,
    TableInfo,
)

API_URL = "https://api.airtable.com"
BASE_ID = "appTestBase123"
API_KEY = "patTestKey.secret"
HOSTNAME = "airtable-proxy.example.com"
CALLBACK_URL = f"https://{HOSTNAME}/webhooks/{BASE_ID}"


class MockAirtableApi:
    """
    Extends MockAirtable with requests_mock to support endpoints that
    MockAirtable doesn't handle: whoami, schema, webhooks, and payloads.

    MockAirtable handles table-level CRUD (iterate, get, create, etc.).
    This class layers on requests_mock (via ``enable_passthrough``) to
    provide the remaining Airtable REST API surface area.
    """

    def __init__(self, mock_at: MockAirtable, requests_mock):
        self.mock_at = mock_at
        self.requests_mock = requests_mock

    # -- MockAirtable delegation --

    def add_records(self, base_id, table_id_or_name, records):
        """Add records that will be returned by Table.all() / Table.iterate()."""
        self.mock_at.add_records(base_id, table_id_or_name, records)

    # -- JSON builders for Airtable API responses --

    @staticmethod
    def webhook_json(webhook_id, notification_url=None):
        """Build a webhook object matching Airtable's ``GET .../webhooks`` response."""
        return {
            "id": webhook_id,
            "type": "client",
            "isHookEnabled": True,
            "areNotificationsEnabled": True,
            "notificationUrl": notification_url,
            "cursorForNextPayload": 1,
            "createdTime": "2024-01-01T00:00:00.000Z",
            "specification": {"options": {"filters": {"dataTypes": ["tableData"]}}},
        }

    @staticmethod
    def table_json(table_id, name, fields=None):
        """Build a table object matching Airtable's schema (``GET .../tables``) response."""
        return {
            "id": table_id,
            "name": name,
            "primaryFieldId": "fldPrimary",
            "fields": fields or [],
            "views": [{"id": "viwXXX", "name": "Grid view", "type": "grid"}],
        }

    @staticmethod
    def field_json(field_id, name, field_type):
        """Build a field object for use inside ``table_json(fields=[...])``."""
        return {"id": field_id, "name": name, "type": field_type}

    # -- Endpoint registration --

    def mock_whoami(self, user_id="usr123"):
        """Mock ``GET /v0/meta/whoami``."""
        self.requests_mock.get(f"{API_URL}/v0/meta/whoami", json={"id": user_id})

    def mock_schema(self, base_id, tables):
        """Mock ``GET /v0/meta/bases/{base_id}/tables``."""
        self.requests_mock.get(
            f"{API_URL}/v0/meta/bases/{base_id}/tables",
            json={"tables": tables},
        )

    def mock_list_webhooks(self, base_id, webhooks):
        """Mock ``GET /v0/bases/{base_id}/webhooks`` with a single response."""
        self.requests_mock.get(
            f"{API_URL}/v0/bases/{base_id}/webhooks",
            json={"webhooks": webhooks},
        )

    def mock_list_webhooks_sequence(self, base_id, *webhook_lists):
        """Mock ``GET /v0/bases/{base_id}/webhooks`` with sequential responses."""
        self.requests_mock.get(
            f"{API_URL}/v0/bases/{base_id}/webhooks",
            [{"json": {"webhooks": wh}} for wh in webhook_lists],
        )

    def mock_create_webhook(self, base_id, webhook_id="achNew"):
        """Mock ``POST /v0/bases/{base_id}/webhooks``."""
        self.requests_mock.post(
            f"{API_URL}/v0/bases/{base_id}/webhooks",
            json={
                "id": webhook_id,
                "macSecretBase64": "dGVzdA==",
                "expirationTime": "2025-01-01T00:00:00.000Z",
            },
        )

    def mock_webhook_payloads(self, base_id, webhook_id, payloads, cursor=1):
        """Mock ``GET /v0/bases/{base_id}/webhooks/{webhook_id}/payloads``."""
        self.requests_mock.get(
            f"{API_URL}/v0/bases/{base_id}/webhooks/{webhook_id}/payloads",
            json={
                "payloads": payloads,
                "cursor": cursor,
                "mightHaveMore": False,
            },
        )

    @property
    def request_history(self):
        """Shortcut for ``requests_mock.request_history``."""
        return self.requests_mock.request_history


@pytest.fixture
def airtable_api(requests_mock):
    """
    A ``MockAirtableApi`` fixture that combines ``MockAirtable`` (for table CRUD)
    with ``requests_mock`` (for schema, webhooks, whoami, and payloads).
    """
    with MockAirtable() as m:
        with m.enable_passthrough():
            yield MockAirtableApi(m, requests_mock)


@pytest.fixture
def valid_config(tmp_path):
    return {
        "hostname": HOSTNAME,
        "bases": {BASE_ID: {"api_key": API_KEY}},
        "storage": {"sqlite": str(tmp_path / "test.db")},
    }


# -- initialize tests --


def test_initialize_calls_whoami_for_each_base(airtable_api, valid_config):
    airtable_api.mock_whoami()
    airtable_api.mock_list_webhooks_sequence(
        BASE_ID,
        [],
        [airtable_api.webhook_json("achNew", CALLBACK_URL)],
    )
    airtable_api.mock_create_webhook(BASE_ID)
    airtable_api.mock_schema(BASE_ID, [])

    poller.initialize(valid_config)

    assert any(r.path == "/v0/meta/whoami" for r in airtable_api.request_history)


def test_initialize_fails_if_airtable_unavailable(airtable_api, valid_config):
    airtable_api.requests_mock.get(f"{API_URL}/v0/meta/whoami", status_code=500)
    with pytest.raises(Exception):
        poller.initialize(valid_config)


def test_initialize_creates_webhook_if_not_exists(airtable_api, valid_config):
    airtable_api.mock_whoami()
    airtable_api.mock_list_webhooks_sequence(
        BASE_ID,
        [],
        [airtable_api.webhook_json("achNew", CALLBACK_URL)],
    )
    airtable_api.mock_create_webhook(BASE_ID)
    airtable_api.mock_schema(BASE_ID, [])

    poller.initialize(valid_config)

    assert any(r.method == "POST" and "webhooks" in r.path for r in airtable_api.request_history)


def test_initialize_finds_existing_webhook(airtable_api, valid_config):
    airtable_api.mock_whoami()
    airtable_api.mock_list_webhooks(
        BASE_ID, [airtable_api.webhook_json("achExisting", CALLBACK_URL)]
    )
    airtable_api.mock_schema(BASE_ID, [])

    poller.initialize(valid_config)

    assert not any(r.method == "POST" and "webhooks" in r.path for r in airtable_api.request_history)


# -- find_or_create_webhook tests --


def test_find_or_create_webhook_finds_existing(airtable_api):
    airtable_api.mock_list_webhooks(
        "appX",
        [airtable_api.webhook_json("achExist", "https://example.com/callback")],
    )

    api = Api(API_KEY)
    base = api.base("appX")
    result = poller.find_or_create_webhook(base, "https://example.com/callback")

    assert result.id == "achExist"


def test_find_or_create_webhook_creates_new(airtable_api):
    airtable_api.mock_list_webhooks_sequence(
        "appX",
        [],
        [airtable_api.webhook_json("achNew", "https://example.com/callback")],
    )
    airtable_api.mock_create_webhook("appX", "achNew")

    api = Api(API_KEY)
    base = api.base("appX")
    result = poller.find_or_create_webhook(base, "https://example.com/callback")

    assert result.id == "achNew"


# -- refresh_tables tests --


def test_refresh_tables_saves_tables_and_records(airtable_api, storage):
    airtable_api.mock_schema(
        "appBase1",
        [
            airtable_api.table_json("tbl1", "Table One"),
            airtable_api.table_json("tbl2", "Table Two"),
        ],
    )
    airtable_api.add_records(
        "appBase1",
        "tbl1",
        [
            {
                "id": "rec1",
                "fields": {"fldA": "value1"},
                "createdTime": "2024-01-01T00:00:00.000Z",
            },
            {
                "id": "rec2",
                "fields": {"fldA": "value2"},
                "createdTime": "2024-01-02T00:00:00.000Z",
            },
        ],
    )
    airtable_api.add_records(
        "appBase1",
        "tbl2",
        [
            {
                "id": "rec3",
                "fields": {"fldB": "value3"},
                "createdTime": "2024-01-03T00:00:00.000Z",
            },
        ],
    )

    api = Api(API_KEY)
    base = api.base("appBase1")
    persist = AirtablePersistence(storage)

    poller.refresh_tables(base, "appBase1", persist)

    assert persist.get_table("appBase1", "tbl1") == TableInfo(table_name="Table One")
    assert persist.get_table("appBase1", "tbl2") == TableInfo(table_name="Table Two")
    assert persist.get_record("appBase1", "tbl1", "rec1") == RecordInfo(
        fields={"fldA": "value1"},
        created_time="2024-01-01T00:00:00.000Z",
    )
    assert persist.get_record("appBase1", "tbl1", "rec2") == RecordInfo(
        fields={"fldA": "value2"},
        created_time="2024-01-02T00:00:00.000Z",
    )
    assert persist.get_record("appBase1", "tbl2", "rec3") == RecordInfo(
        fields={"fldB": "value3"},
        created_time="2024-01-03T00:00:00.000Z",
    )


def test_refresh_tables_saves_fields(airtable_api, storage):
    """refresh_tables saves field metadata for each table."""
    airtable_api.mock_schema(
        "appBase1",
        [
            airtable_api.table_json(
                "tbl1",
                "Table One",
                fields=[airtable_api.field_json("fldX", "Status", "singleSelect")],
            ),
        ],
    )
    airtable_api.add_records("appBase1", "tbl1", [])

    api = Api(API_KEY)
    base = api.base("appBase1")
    persist = AirtablePersistence(storage)

    poller.refresh_tables(base, "appBase1", persist)

    assert persist.get_field("appBase1", "tbl1", "fldX") == FieldInfo(
        field_name="Status", field_type="singleSelect"
    )


# -- refresh_table tests --


def test_refresh_table_replaces_records(airtable_api, storage):
    """refresh_table overwrites the cached table, deleting records Airtable no longer has."""
    persist = AirtablePersistence(storage)
    persist.save_table("appBase1", "tbl1", "Old Name")
    persist.save_record(
        "appBase1",
        "tbl1",
        "recOld",
        fields={"fldA": "stale"},
        created_time="2023-12-31T00:00:00.000Z",
    )

    airtable_api.mock_schema(
        "appBase1",
        [
            airtable_api.table_json(
                "tbl1",
                "Table One",
                fields=[airtable_api.field_json("fldA", "Name", "singleLineText")],
            ),
        ],
    )
    airtable_api.add_records(
        "appBase1",
        "tbl1",
        [
            {
                "id": "rec1",
                "fields": {"fldA": "value1"},
                "createdTime": "2024-01-01T00:00:00.000Z",
            },
        ],
    )

    api = Api(API_KEY)
    base = api.base("appBase1")

    poller.refresh_table(base, "appBase1", "tbl1", persist)

    assert persist.get_record("appBase1", "tbl1", "recOld") is None
    assert persist.get_record("appBase1", "tbl1", "rec1") == RecordInfo(
        fields={"fldA": "value1"},
        created_time="2024-01-01T00:00:00.000Z",
    )
    assert persist.get_table("appBase1", "tbl1") == TableInfo(table_name="Table One")
    assert persist.get_field("appBase1", "tbl1", "fldA") == FieldInfo(
        field_name="Name", field_type="singleLineText"
    )


def test_refresh_table_marks_table_during_refresh(airtable_api, storage):
    """
    refresh_table marks the table as refreshing while records are being
    written and clears the marker once the stale-record sweep completes.
    """
    persist = AirtablePersistence(storage)
    persist.save_record(
        "appBase1",
        "tbl1",
        "recOld",
        fields={"fldA": "stale"},
        created_time="2023-12-31T00:00:00.000Z",
    )

    airtable_api.mock_schema(
        "appBase1",
        [airtable_api.table_json("tbl1", "Table One")],
    )
    airtable_api.add_records(
        "appBase1",
        "tbl1",
        [
            {
                "id": "rec1",
                "fields": {"fldA": "value1"},
                "createdTime": "2024-01-01T00:00:00.000Z",
            },
        ],
    )

    marked_during_write = []

    original_save_record = persist.save_record

    def spy_save_record(base_id, table_id, record_id, **kwargs):
        marked_during_write.append(persist.is_refreshing(base_id, table_id))
        return original_save_record(base_id, table_id, record_id, **kwargs)

    api = Api(API_KEY)
    base = api.base("appBase1")

    with patch.object(persist, "save_record", side_effect=spy_save_record):
        poller.refresh_table(base, "appBase1", "tbl1", persist)

    assert marked_during_write == [True]
    assert persist.is_refreshing("appBase1", "tbl1") is False


def test_refresh_table_leaves_marker_set_when_refresh_fails(airtable_api, storage):
    """
    If refresh_table dies while writing records, the table stays marked as
    refreshing so readers proxy instead of trusting the half-written cache.
    """
    persist = AirtablePersistence(storage)
    persist.save_table("appBase1", "tbl1", "Table One")

    airtable_api.mock_schema(
        "appBase1",
        [airtable_api.table_json("tbl1", "Table One")],
    )
    airtable_api.add_records(
        "appBase1",
        "tbl1",
        [
            {
                "id": "rec1",
                "fields": {"fldA": "value1"},
                "createdTime": "2024-01-01T00:00:00.000Z",
            },
        ],
    )

    api = Api(API_KEY)
    base = api.base("appBase1")

    with patch.object(persist, "save_record", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            poller.refresh_table(base, "appBase1", "tbl1", persist)

    assert persist.is_refreshing("appBase1", "tbl1") is True


def test_refresh_table_skips_table_missing_from_schema(airtable_api, storage):
    """refresh_table leaves the cache untouched if Airtable's schema lacks the table."""
    persist = AirtablePersistence(storage)
    persist.save_table("appBase1", "tbl1", "Table One")
    persist.save_record(
        "appBase1",
        "tbl1",
        "rec1",
        fields={"fldA": "value1"},
        created_time="2024-01-01T00:00:00.000Z",
    )

    airtable_api.mock_schema("appBase1", [airtable_api.table_json("tbl2", "Other")])

    api = Api(API_KEY)
    base = api.base("appBase1")

    poller.refresh_table(base, "appBase1", "tbl1", persist)

    assert persist.get_record("appBase1", "tbl1", "rec1") == RecordInfo(
        fields={"fldA": "value1"},
        created_time="2024-01-01T00:00:00.000Z",
    )


# -- process_payload tests --


def _make_payload(**kwargs):
    """Helper to build a WebhookPayload with sensible defaults."""
    defaults = dict(
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        baseTransactionNumber=1,
        payloadFormat="v0",
    )
    defaults.update(kwargs)
    return WebhookPayload(**defaults)


def test_process_payload_destroyed_tables(storage):
    persist = AirtablePersistence(storage)
    persist.save_table("appB", "tblDel", "Doomed")
    persist.save_record("appB", "tblDel", "rec1", fields={"x": 1}, created_time="t")

    payload = _make_payload(destroyedTableIds=["tblDel"])
    poller.process_payload(payload, "appB", persist)

    assert persist.get_table("appB", "tblDel") is None
    assert persist.get_record("appB", "tblDel", "rec1") is None


def test_process_payload_created_tables(storage):
    persist = AirtablePersistence(storage)

    payload = _make_payload(
        createdTablesById={
            "tblNew": {
                "metadata": {"name": "New Table"},
                "fieldsById": {
                    "fld1": {"name": "Name", "type": "singleLineText"},
                },
                "recordsById": {
                    "recA": {
                        "createdTime": "2024-01-01T00:00:00.000Z",
                        "cellValuesByFieldId": {"fld1": "Alice"},
                    },
                },
            }
        }
    )
    poller.process_payload(payload, "appB", persist)

    assert persist.get_table("appB", "tblNew") == TableInfo(table_name="New Table")
    assert persist.get_field("appB", "tblNew", "fld1") == FieldInfo(
        field_name="Name", field_type="singleLineText"
    )
    rec = persist.get_record("appB", "tblNew", "recA")
    assert rec is not None
    assert rec.fields == {"fld1": "Alice"}


def test_process_payload_changed_table_rename(storage):
    persist = AirtablePersistence(storage)
    persist.save_table("appB", "tbl1", "Old Name")

    payload = _make_payload(
        changedTablesById={
            "tbl1": {
                "changedMetadata": {
                    "current": {"name": "New Name"},
                    "previous": {"name": "Old Name"},
                },
            }
        }
    )
    poller.process_payload(payload, "appB", persist)

    assert persist.get_table("appB", "tbl1") == TableInfo(table_name="New Name")


def test_process_payload_destroyed_fields(storage):
    persist = AirtablePersistence(storage)
    persist.save_field("appB", "tbl1", "fldDel", field_name="Gone", field_type="text")

    payload = _make_payload(
        changedTablesById={
            "tbl1": {"destroyedFieldIds": ["fldDel"]},
        }
    )
    poller.process_payload(payload, "appB", persist)

    assert persist.get_field("appB", "tbl1", "fldDel") is None


def test_process_payload_created_fields(storage):
    persist = AirtablePersistence(storage)

    payload = _make_payload(
        changedTablesById={
            "tbl1": {
                "createdFieldsById": {
                    "fldNew": {"name": "Status", "type": "singleSelect"},
                },
            }
        }
    )
    poller.process_payload(payload, "appB", persist)

    assert persist.get_field("appB", "tbl1", "fldNew") == FieldInfo(
        field_name="Status", field_type="singleSelect"
    )


def test_process_payload_changed_fields(storage):
    persist = AirtablePersistence(storage)
    persist.save_field("appB", "tbl1", "fld1", field_name="Old", field_type="text")

    payload = _make_payload(
        changedTablesById={
            "tbl1": {
                "changedFieldsById": {
                    "fld1": {
                        "current": {"name": "Renamed", "type": "richText"},
                        "previous": {"name": "Old", "type": "text"},
                    },
                },
            }
        }
    )
    poller.process_payload(payload, "appB", persist)

    assert persist.get_field("appB", "tbl1", "fld1") == FieldInfo(
        field_name="Renamed", field_type="richText"
    )


def test_process_payload_created_records(storage):
    persist = AirtablePersistence(storage)

    payload = _make_payload(
        changedTablesById={
            "tbl1": {
                "createdRecordsById": {
                    "recNew": {
                        "createdTime": "2024-06-01T00:00:00.000Z",
                        "cellValuesByFieldId": {"fld1": "hello"},
                    },
                },
            }
        }
    )
    poller.process_payload(payload, "appB", persist)

    rec = persist.get_record("appB", "tbl1", "recNew")
    assert rec is not None
    assert rec.fields == {"fld1": "hello"}
    assert "2024-06-01" in rec.created_time


def test_process_payload_changed_records(storage):
    persist = AirtablePersistence(storage)
    persist.save_record("appB", "tbl1", "rec1", fields={"fld1": "old"}, created_time="t")

    payload = _make_payload(
        changedTablesById={
            "tbl1": {
                "changedRecordsById": {
                    "rec1": {
                        "current": {"cellValuesByFieldId": {"fld1": "new"}},
                        "previous": {"cellValuesByFieldId": {"fld1": "old"}},
                        "unchanged": {"cellValuesByFieldId": {}},
                    },
                },
            }
        }
    )
    dirty = poller.process_payload(payload, "appB", persist)

    assert dirty == set()
    rec = persist.get_record("appB", "tbl1", "rec1")
    assert rec.fields["fld1"] == "new"
    assert rec.created_time == "t"


def test_process_payload_changed_record_missing_marks_table_dirty(storage):
    """A change for an uncached record marks the table dirty instead of raising."""
    persist = AirtablePersistence(storage)
    persist.save_record("appB", "tbl1", "rec1", fields={"fld1": "old"}, created_time="t")

    payload = _make_payload(
        changedTablesById={
            "tbl1": {
                "changedRecordsById": {
                    "rec1": {
                        "current": {"cellValuesByFieldId": {"fld1": "new"}},
                        "previous": {"cellValuesByFieldId": {"fld1": "old"}},
                        "unchanged": {"cellValuesByFieldId": {}},
                    },
                    "recGhost": {
                        "current": {"cellValuesByFieldId": {"fld1": "x"}},
                        "previous": {"cellValuesByFieldId": {}},
                        "unchanged": {"cellValuesByFieldId": {}},
                    },
                },
            }
        }
    )
    dirty = poller.process_payload(payload, "appB", persist)

    assert dirty == {"tbl1"}
    assert persist.get_record("appB", "tbl1", "recGhost") is None
    assert persist.get_record("appB", "tbl1", "rec1").fields["fld1"] == "new"


def test_process_payload_destroyed_records(storage):
    persist = AirtablePersistence(storage)
    persist.save_record("appB", "tbl1", "recDel", fields={}, created_time="t")

    payload = _make_payload(
        changedTablesById={
            "tbl1": {"destroyedRecordIds": ["recDel"]},
        }
    )
    poller.process_payload(payload, "appB", persist)

    assert persist.get_record("appB", "tbl1", "recDel") is None


# -- BasePoller tests --


@pytest.fixture
def base_poller(storage):
    """
    A BasePoller instance for "appB" with a fresh persistence layer.
    """
    persist = AirtablePersistence(storage)
    return poller.BasePoller("appB", BaseConfig(api_key=API_KEY), persist)


def test_base_poller_poll_no_webhook_info(base_poller):
    """
    BasePoller.poll returns early when no webhook info is stored.
    """
    base_poller.poll()


def test_base_poller_poll_processes_payloads(airtable_api, base_poller):
    base_poller.persistence.save_webhook("appB", webhook_id="whX", cursor=5)
    base_poller.persistence.save_table("appB", "tbl1", "Table")
    base_poller.persistence.save_record(
        "appB", "tbl1", "rec1", fields={"f": "old"}, created_time="t"
    )

    airtable_api.mock_list_webhooks("appB", [airtable_api.webhook_json("whX")])
    airtable_api.mock_webhook_payloads(
        "appB",
        "whX",
        [
            {
                "timestamp": "2024-01-01T00:00:00.000Z",
                "baseTransactionNumber": 6,
                "payloadFormat": "v0",
                "changedTablesById": {
                    "tbl1": {
                        "changedRecordsById": {
                            "rec1": {
                                "current": {"cellValuesByFieldId": {"f": "new"}},
                                "previous": {"cellValuesByFieldId": {"f": "old"}},
                                "unchanged": {"cellValuesByFieldId": {}},
                            },
                        },
                    },
                },
            }
        ],
        cursor=6,
    )

    base_poller.poll()

    assert base_poller.persistence.get_record("appB", "tbl1", "rec1").fields["f"] == "new"
    assert base_poller.persistence.get_webhook("appB").cursor == 6


def test_base_poller_poll_refreshes_dirty_tables(airtable_api, base_poller):
    """
    A payload referencing an uncached record doesn't stall the poller: the
    cursor advances past it, and the table is refreshed from the API after
    the payload drain (replacing stale cached records).
    """
    base_poller.persistence.save_webhook("appB", webhook_id="whX", cursor=5)
    base_poller.persistence.save_table("appB", "tbl1", "Table")
    base_poller.persistence.save_record(
        "appB", "tbl1", "recStale", fields={"f": "stale"}, created_time="t"
    )

    airtable_api.mock_list_webhooks("appB", [airtable_api.webhook_json("whX")])
    airtable_api.mock_webhook_payloads(
        "appB",
        "whX",
        [
            {
                "timestamp": "2024-01-01T00:00:00.000Z",
                "baseTransactionNumber": 6,
                "payloadFormat": "v0",
                "changedTablesById": {
                    "tbl1": {
                        "changedRecordsById": {
                            "recGhost": {
                                "current": {"cellValuesByFieldId": {"f": "new"}},
                                "previous": {"cellValuesByFieldId": {}},
                                "unchanged": {"cellValuesByFieldId": {}},
                            },
                        },
                    },
                },
            }
        ],
        cursor=6,
    )
    airtable_api.mock_schema("appB", [airtable_api.table_json("tbl1", "Table")])
    airtable_api.add_records(
        "appB",
        "tbl1",
        [
            {
                "id": "recGhost",
                "fields": {"f": "new"},
                "createdTime": "2024-01-01T00:00:00.000Z",
            },
        ],
    )

    base_poller.poll()

    assert base_poller.persistence.get_webhook("appB").cursor == 6
    assert base_poller.persistence.get_record("appB", "tbl1", "recGhost") == RecordInfo(
        fields={"f": "new"},
        created_time="2024-01-01T00:00:00.000Z",
    )
    assert base_poller.persistence.get_record("appB", "tbl1", "recStale") is None
    assert base_poller.persistence.is_refreshing("appB", "tbl1") is False


def test_base_poller_poll_leaves_table_marked_when_refresh_fails(airtable_api, base_poller):
    """
    If the post-drain refresh of a dirty table raises, the table stays
    marked as refreshing so readers proxy instead of trusting the
    half-refreshed cache; the next successful refresh clears the marker.

    The failure is injected into persistence.save_record: the payload drain
    never calls it (the ghost record is uncached and skipped), so the first
    call happens inside the real refresh_table, after the marker is set.
    """
    base_poller.persistence.save_webhook("appB", webhook_id="whX", cursor=5)
    base_poller.persistence.save_table("appB", "tbl1", "Table")
    base_poller.persistence.save_record(
        "appB", "tbl1", "recStale", fields={"f": "stale"}, created_time="t"
    )

    airtable_api.mock_list_webhooks("appB", [airtable_api.webhook_json("whX")])
    airtable_api.mock_webhook_payloads(
        "appB",
        "whX",
        [
            {
                "timestamp": "2024-01-01T00:00:00.000Z",
                "baseTransactionNumber": 6,
                "payloadFormat": "v0",
                "changedTablesById": {
                    "tbl1": {
                        "changedRecordsById": {
                            "recGhost": {
                                "current": {"cellValuesByFieldId": {"f": "new"}},
                                "previous": {"cellValuesByFieldId": {}},
                                "unchanged": {"cellValuesByFieldId": {}},
                            },
                        },
                    },
                },
            }
        ],
        cursor=6,
    )
    airtable_api.mock_schema("appB", [airtable_api.table_json("tbl1", "Table")])
    airtable_api.add_records(
        "appB",
        "tbl1",
        [
            {
                "id": "recGhost",
                "fields": {"f": "new"},
                "createdTime": "2024-01-01T00:00:00.000Z",
            },
        ],
    )

    with patch.object(
        base_poller.persistence, "save_record", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError, match="boom"):
            base_poller.poll()

    assert base_poller.persistence.get_webhook("appB").cursor == 6
    assert base_poller.persistence.is_refreshing("appB", "tbl1") is True


def test_base_poller_poll_skips_refresh_of_destroyed_dirty_table(airtable_api, base_poller):
    """
    A table marked dirty and then destroyed by a later payload in the same
    drain is not resurrected by the post-drain refresh.
    """
    base_poller.persistence.save_webhook("appB", webhook_id="whX", cursor=5)
    base_poller.persistence.save_table("appB", "tbl1", "Table")

    airtable_api.mock_list_webhooks("appB", [airtable_api.webhook_json("whX")])
    airtable_api.mock_webhook_payloads(
        "appB",
        "whX",
        [
            {
                "timestamp": "2024-01-01T00:00:00.000Z",
                "baseTransactionNumber": 6,
                "payloadFormat": "v0",
                "changedTablesById": {
                    "tbl1": {
                        "changedRecordsById": {
                            "recGhost": {
                                "current": {"cellValuesByFieldId": {"f": "x"}},
                                "previous": {"cellValuesByFieldId": {}},
                                "unchanged": {"cellValuesByFieldId": {}},
                            },
                        },
                    },
                },
            },
            {
                "timestamp": "2024-01-01T00:00:01.000Z",
                "baseTransactionNumber": 7,
                "payloadFormat": "v0",
                "destroyedTableIds": ["tbl1"],
            },
        ],
        cursor=7,
    )
    airtable_api.mock_schema("appB", [])

    base_poller.poll()

    assert base_poller.persistence.get_webhook("appB").cursor == 7
    assert base_poller.persistence.get_table("appB", "tbl1") is None
    assert base_poller.persistence.get_record("appB", "tbl1", "recGhost") is None


@patch.object(poller, "refresh_tables")
def test_create_webhook_saves_webhook_after_refresh(
    mock_refresh_tables, airtable_api, base_poller
):
    """
    The webhook row is saved only after refresh_tables completes, so a crash
    mid-refresh leaves no webhook info and the next startup re-initializes
    instead of trusting a half-populated cache. The base is marked as
    refreshing for the duration of the refresh.
    """
    callback = "https://example.com/webhooks/appB"

    airtable_api.mock_list_webhooks_sequence(
        "appB",
        [],  # find_or_create: no match -> create
        [airtable_api.webhook_json("achNew", callback)],  # resolve achNew
    )
    airtable_api.mock_create_webhook("appB", "achNew")

    state_during_refresh = None

    def check_refresh(refresh_base, refresh_base_id, refresh_persistence):
        nonlocal state_during_refresh
        state_during_refresh = (
            refresh_persistence.get_webhook(refresh_base_id),
            refresh_persistence.is_refreshing(refresh_base_id),
        )

    mock_refresh_tables.side_effect = check_refresh

    base_poller._create_webhook_and_refresh(Api(API_KEY).base("appB"), callback)

    assert state_during_refresh == (None, True)
    assert base_poller.persistence.get_webhook("appB").webhook_id == "achNew"
    assert base_poller.persistence.is_refreshing("appB") is False


@patch.object(poller, "refresh_tables", side_effect=RuntimeError("boom"))
def test_failed_initial_refresh_leaves_base_marked_refreshing(
    mock_refresh_tables, airtable_api, base_poller
):
    """
    If refresh_tables dies partway through, the base stays marked as
    refreshing and no webhook info is saved, so readers don't trust the
    partial cache and the next startup re-initializes.
    """
    callback = "https://example.com/webhooks/appB"

    airtable_api.mock_list_webhooks_sequence(
        "appB",
        [],
        [airtable_api.webhook_json("achNew", callback)],
    )
    airtable_api.mock_create_webhook("appB", "achNew")

    with pytest.raises(RuntimeError, match="boom"):
        base_poller._create_webhook_and_refresh(Api(API_KEY).base("appB"), callback)

    assert base_poller.persistence.get_webhook("appB") is None
    assert base_poller.persistence.is_refreshing("appB") is True


def test_base_poller_poll_clears_stale_refresh_marker(airtable_api, base_poller):
    """
    A base-level refreshing marker left behind by a crashed refresh_tables
    is cleared on the first successful poll: the saved cursor was only
    written after the refresh completed, so replaying from it brings the
    cache up to date.
    """
    base_poller.persistence.save_webhook("appB", webhook_id="whX", cursor=5)
    base_poller.persistence.mark_refresh_started("appB")

    airtable_api.mock_list_webhooks("appB", [airtable_api.webhook_json("whX")])
    airtable_api.mock_webhook_payloads("appB", "whX", [], cursor=5)

    base_poller.poll()

    assert base_poller.persistence.is_refreshing("appB") is False


def test_base_poller_webhook_is_cached(airtable_api, base_poller):
    """
    Calling poll() twice only fetches the webhook object once.
    """
    base_poller.persistence.save_webhook("appB", webhook_id="whX", cursor=0)

    airtable_api.mock_list_webhooks("appB", [airtable_api.webhook_json("whX")])
    airtable_api.mock_webhook_payloads("appB", "whX", [], cursor=0)

    base_poller.poll()
    base_poller.poll()

    webhook_gets = [
        r for r in airtable_api.request_history if r.method == "GET" and r.path.endswith("/webhooks")
    ]
    assert len(webhook_gets) == 1


def test_base_poller_initialize_existing_webhook_polls(airtable_api, base_poller):
    base_poller.persistence.save_webhook("appB", webhook_id="whExist", cursor=3)

    airtable_api.mock_whoami()
    airtable_api.mock_list_webhooks("appB", [airtable_api.webhook_json("whExist")])
    airtable_api.mock_webhook_payloads("appB", "whExist", [], cursor=3)

    base_poller.initialize("https://example.com/webhooks/appB")

    assert not any(r.method == "POST" and "webhooks" in r.path for r in airtable_api.request_history)


def test_base_poller_initialize_recreates_culled_webhook(airtable_api, base_poller):
    """
    When the stored webhook ID no longer exists at Airtable (culled after
    7 days without polling), initialize() recreates the webhook, resets the
    cursor, and refreshes the cache instead of crashing.
    """
    base_poller.persistence.save_webhook("appB", webhook_id="whGone", cursor=5)
    callback = "https://example.com/webhooks/appB"

    airtable_api.mock_whoami()
    # GET /webhooks never contains whGone -> base.webhook("whGone") raises
    # KeyError; find_or_create then creates achNew and resolves it.
    airtable_api.mock_list_webhooks_sequence(
        "appB",
        [],  # poll(): resolve whGone -> KeyError
        [],  # find_or_create: no match -> create
        [airtable_api.webhook_json("achNew", callback)],  # resolve achNew
    )
    airtable_api.mock_create_webhook("appB", "achNew")
    airtable_api.mock_schema("appB", [airtable_api.table_json("tbl1", "Table One")])
    airtable_api.add_records(
        "appB",
        "tbl1",
        [{"id": "rec1", "fields": {"fldA": "v"}, "createdTime": "2024-01-01T00:00:00.000Z"}],
    )

    base_poller.initialize(callback)

    info = base_poller.persistence.get_webhook("appB")
    assert info.webhook_id == "achNew"
    assert info.cursor == 0
    assert base_poller.persistence.get_record("appB", "tbl1", "rec1") is not None


def test_base_poller_initialize_purges_stale_cache_on_recreate(airtable_api, base_poller):
    """
    When initialize() recreates the webhook, the cache is purged before
    refreshing: records left behind by a crashed earlier refresh (or
    deleted from the base while we were away) don't linger.
    """
    base_poller.persistence.save_webhook("appB", webhook_id="whGone", cursor=5)
    base_poller.persistence.save_table("appB", "tbl1", "Table One")
    base_poller.persistence.save_record(
        "appB", "tbl1", "recPhantom", fields={"fldA": "stale"}, created_time="t"
    )
    callback = "https://example.com/webhooks/appB"

    airtable_api.mock_whoami()
    airtable_api.mock_list_webhooks_sequence(
        "appB",
        [],  # poll(): resolve whGone -> KeyError
        [],  # find_or_create: no match -> create
        [airtable_api.webhook_json("achNew", callback)],  # resolve achNew
    )
    airtable_api.mock_create_webhook("appB", "achNew")
    airtable_api.mock_schema("appB", [airtable_api.table_json("tbl1", "Table One")])
    airtable_api.add_records(
        "appB",
        "tbl1",
        [{"id": "rec1", "fields": {"fldA": "v"}, "createdTime": "2024-01-01T00:00:00.000Z"}],
    )

    base_poller.initialize(callback)

    assert base_poller.persistence.get_record("appB", "tbl1", "recPhantom") is None
    assert base_poller.persistence.get_record("appB", "tbl1", "rec1") is not None


# -- run_polling_loop tests --


@patch("airtable_proxy.poller.BasePoller.poll")
def test_run_polling_loop_polls_and_handles_errors(mock_poll, tmp_path):
    config = Config.model_validate(
        {
            "hostname": "test.example.com",
            "bases": {"appB": BaseConfig(api_key="patXXX")},
            "storage": {"sqlite": str(tmp_path / "test.db")},
        }
    )

    call_count = 0

    def fake_poll():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("transient error")

    mock_poll.side_effect = fake_poll

    async def run():
        task = asyncio.create_task(poller.run_polling_loop(config))
        await asyncio.sleep(poller.POLL_INTERVAL * 2 + 0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())

    assert call_count >= 2


# -- main CLI tests --


@patch("airtable_proxy.poller.initialize")
def test_main_once(mock_init, tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"hostname: test.example.com\nbases: {{}}\nstorage:\n  sqlite: {tmp_path / 'test.db'}\n"
    )

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, [str(config_file), "--once"])
    assert result.exit_code == 0
    mock_init.assert_called_once()


@patch("airtable_proxy.poller.asyncio.run")
@patch("airtable_proxy.poller.initialize")
def test_main_without_once_runs_polling(_mock_init, mock_asyncio_run, tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"hostname: test.example.com\nbases: {{}}\nstorage:\n  sqlite: {tmp_path / 'test.db'}\n"
    )

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, [str(config_file)])
    assert result.exit_code == 0
    mock_asyncio_run.assert_called_once()
    mock_asyncio_run.call_args[0][0].close()


@patch("airtable_proxy.poller.initialize")
def test_main_uses_explicit_config_arg(mock_init, tmp_path):
    config_file = tmp_path / "explicit.yaml"
    config_file.write_text("hostname: test.example.com\nbases: {}\n")

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, [str(config_file), "--once"])
    assert result.exit_code == 0
    mock_init.assert_called_once()


@patch("airtable_proxy.poller.initialize")
def test_main_uses_env_var_when_no_arg(mock_init, tmp_path, monkeypatch):
    config_file = tmp_path / "from-env.yaml"
    config_file.write_text("hostname: test.example.com\nbases: {}\n")
    monkeypatch.setenv("AIRTABLE_PROXY_CONFIG", str(config_file))

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, ["--once"])
    assert result.exit_code == 0
    mock_init.assert_called_once()


@patch("airtable_proxy.poller.initialize")
def test_main_falls_back_to_default_config_yaml(mock_init, tmp_path, monkeypatch):
    monkeypatch.delenv("AIRTABLE_PROXY_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("hostname: test.example.com\nbases: {}\n")

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, ["--once"])
    assert result.exit_code == 0
    mock_init.assert_called_once()


def test_main_friendly_error_when_config_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("AIRTABLE_PROXY_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, [])
    assert result.exit_code == 1
    assert "config.yaml.example" in result.output
