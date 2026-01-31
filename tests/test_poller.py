import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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


@pytest.fixture
def valid_config(tmp_path):
    return {
        "hostname": HOSTNAME,
        "bases": {BASE_ID: {"api_key": API_KEY}},
        "storage": {"sqlite": str(tmp_path / "test.db")},
    }


@pytest.fixture
def mock_at():
    """MockAirtable with passthrough for requests_mock to handle non-table API calls."""
    with MockAirtable() as m:
        with m.enable_passthrough():
            yield m


# -- JSON response helpers --


def _webhook_json(webhook_id, notification_url=None):
    """Webhook JSON matching Airtable's API response format."""
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


def _table_schema_json(table_id, name, fields=None):
    return {
        "id": table_id,
        "name": name,
        "primaryFieldId": "fldPrimary",
        "fields": fields or [],
        "views": [{"id": "viwXXX", "name": "Grid view", "type": "grid"}],
    }


def _field_schema_json(field_id, name, field_type):
    return {"id": field_id, "name": name, "type": field_type}


# -- requests_mock registration helpers --


def _setup_whoami(rm):
    rm.get(f"{API_URL}/v0/meta/whoami", json={"id": "usr123"})


def _setup_schema(rm, base_id, tables):
    rm.get(f"{API_URL}/v0/meta/bases/{base_id}/tables", json={"tables": tables})


def _setup_webhooks(rm, base_id, webhooks):
    rm.get(f"{API_URL}/v0/bases/{base_id}/webhooks", json={"webhooks": webhooks})


def _setup_webhooks_sequence(rm, base_id, responses):
    """Register sequential responses for the webhooks list endpoint."""
    rm.get(
        f"{API_URL}/v0/bases/{base_id}/webhooks",
        [{"json": {"webhooks": wh}} for wh in responses],
    )


def _setup_create_webhook(rm, base_id, webhook_id="achNew"):
    rm.post(
        f"{API_URL}/v0/bases/{base_id}/webhooks",
        json={
            "id": webhook_id,
            "macSecretBase64": "dGVzdA==",
            "expirationTime": "2025-01-01T00:00:00.000Z",
        },
    )


def _setup_payloads(rm, base_id, webhook_id, payloads_json, cursor=1):
    rm.get(
        f"{API_URL}/v0/bases/{base_id}/webhooks/{webhook_id}/payloads",
        json={"payloads": payloads_json, "cursor": cursor, "mightHaveMore": False},
    )


# -- initialize tests --


def test_initialize_calls_whoami_for_each_base(mock_at, requests_mock, valid_config):
    _setup_whoami(requests_mock)
    _setup_webhooks_sequence(
        requests_mock,
        BASE_ID,
        [
            [],
            [_webhook_json("achNew", CALLBACK_URL)],
        ],
    )
    _setup_create_webhook(requests_mock, BASE_ID)
    _setup_schema(requests_mock, BASE_ID, [])

    poller.initialize(valid_config)

    assert any(r.path == "/v0/meta/whoami" for r in requests_mock.request_history)


def test_initialize_fails_if_airtable_unavailable(mock_at, requests_mock, valid_config):
    requests_mock.get(f"{API_URL}/v0/meta/whoami", status_code=500)
    with pytest.raises(Exception):
        poller.initialize(valid_config)


def test_initialize_creates_webhook_if_not_exists(mock_at, requests_mock, valid_config):
    _setup_whoami(requests_mock)
    _setup_webhooks_sequence(
        requests_mock,
        BASE_ID,
        [
            [],
            [_webhook_json("achNew", CALLBACK_URL)],
        ],
    )
    _setup_create_webhook(requests_mock, BASE_ID)
    _setup_schema(requests_mock, BASE_ID, [])

    poller.initialize(valid_config)

    assert any(
        r.method == "POST" and "webhooks" in r.path
        for r in requests_mock.request_history
    )


def test_initialize_finds_existing_webhook(mock_at, requests_mock, valid_config):
    _setup_whoami(requests_mock)
    _setup_webhooks(
        requests_mock, BASE_ID, [_webhook_json("achExisting", CALLBACK_URL)]
    )
    _setup_schema(requests_mock, BASE_ID, [])

    poller.initialize(valid_config)

    assert not any(
        r.method == "POST" and "webhooks" in r.path
        for r in requests_mock.request_history
    )


# -- find_or_create_webhook tests --


def test_find_or_create_webhook_finds_existing(mock_at, requests_mock):
    _setup_webhooks(
        requests_mock,
        "appX",
        [
            _webhook_json("achExist", "https://example.com/callback"),
        ],
    )

    api = Api(API_KEY)
    base = api.base("appX")
    result = poller.find_or_create_webhook(base, "https://example.com/callback")

    assert result.id == "achExist"


def test_find_or_create_webhook_creates_new(mock_at, requests_mock):
    _setup_webhooks_sequence(
        requests_mock,
        "appX",
        [
            [],
            [_webhook_json("achNew", "https://example.com/callback")],
        ],
    )
    _setup_create_webhook(requests_mock, "appX", "achNew")

    api = Api(API_KEY)
    base = api.base("appX")
    result = poller.find_or_create_webhook(base, "https://example.com/callback")

    assert result.id == "achNew"


# -- refresh_tables tests --


def test_refresh_tables_saves_tables_and_records(mock_at, requests_mock, storage):
    _setup_schema(
        requests_mock,
        "appBase1",
        [
            _table_schema_json("tbl1", "Table One"),
            _table_schema_json("tbl2", "Table Two"),
        ],
    )
    mock_at.add_records(
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
    mock_at.add_records(
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


def test_refresh_tables_saves_fields(mock_at, requests_mock, storage):
    """refresh_tables saves field metadata for each table."""
    _setup_schema(
        requests_mock,
        "appBase1",
        [
            _table_schema_json(
                "tbl1",
                "Table One",
                fields=[_field_schema_json("fldX", "Status", "singleSelect")],
            ),
        ],
    )
    mock_at.add_records("appBase1", "tbl1", [])

    api = Api(API_KEY)
    base = api.base("appBase1")
    persist = AirtablePersistence(storage)

    poller.refresh_tables(base, "appBase1", persist)

    assert persist.get_field("appBase1", "tbl1", "fldX") == FieldInfo(
        field_name="Status", field_type="singleSelect"
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
    persist.save_record(
        "appB", "tbl1", "rec1", fields={"fld1": "old"}, created_time="t"
    )

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
    poller.process_payload(payload, "appB", persist)

    rec = persist.get_record("appB", "tbl1", "rec1")
    assert rec.fields["fld1"] == "new"
    assert rec.created_time == "t"


def test_process_payload_changed_record_missing_raises(storage):
    persist = AirtablePersistence(storage)

    payload = _make_payload(
        changedTablesById={
            "tbl1": {
                "changedRecordsById": {
                    "recGhost": {
                        "current": {"cellValuesByFieldId": {"fld1": "x"}},
                        "previous": {"cellValuesByFieldId": {}},
                        "unchanged": {"cellValuesByFieldId": {}},
                    },
                },
            }
        }
    )
    with pytest.raises(RuntimeError, match="non-existent record"):
        poller.process_payload(payload, "appB", persist)


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


# -- poll_base tests --


def test_poll_base_no_webhook_info(storage):
    """poll_base returns early when no webhook info is stored."""
    persist = AirtablePersistence(storage)
    base_config = BaseConfig(api_key="patXXX")
    poller.poll_base("appMissing", base_config, persist)


def test_poll_base_processes_payloads(mock_at, requests_mock, storage):
    persist = AirtablePersistence(storage)
    persist.save_webhook("appB", webhook_id="whX", cursor=5)
    persist.save_table("appB", "tbl1", "Table")
    persist.save_record("appB", "tbl1", "rec1", fields={"f": "old"}, created_time="t")

    _setup_webhooks(requests_mock, "appB", [_webhook_json("whX")])
    _setup_payloads(
        requests_mock,
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

    base_config = BaseConfig(api_key=API_KEY)
    poller.poll_base("appB", base_config, persist)

    assert persist.get_record("appB", "tbl1", "rec1").fields["f"] == "new"
    assert persist.get_webhook("appB").cursor == 6


# -- initialize_base with existing webhook --


def test_initialize_base_existing_webhook_polls(mock_at, requests_mock, storage):
    persist = AirtablePersistence(storage)
    persist.save_webhook("appB", webhook_id="whExist", cursor=3)

    _setup_whoami(requests_mock)
    _setup_webhooks(requests_mock, "appB", [_webhook_json("whExist")])
    _setup_payloads(requests_mock, "appB", "whExist", [], cursor=3)

    base_config = BaseConfig(api_key=API_KEY)
    poller.initialize_base(
        callback_url="https://example.com/webhooks/appB",
        base_id="appB",
        base_config=base_config,
        persistence=persist,
    )

    assert not any(
        r.method == "POST" and "webhooks" in r.path
        for r in requests_mock.request_history
    )


# -- run_polling_loop tests --


def test_run_polling_loop_polls_and_handles_errors(tmp_path):
    config = Config.model_validate(
        {
            "hostname": "test.example.com",
            "bases": {"appB": BaseConfig(api_key="patXXX")},
            "storage": {"sqlite": str(tmp_path / "test.db")},
        }
    )

    call_count = 0

    def fake_poll_base(base_id, base_config, persist):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("transient error")

    async def run():
        task = asyncio.create_task(poller.run_polling_loop(config))
        await asyncio.sleep(poller.POLL_INTERVAL * 2 + 0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    with patch("airtable_proxy.poller.poll_base", side_effect=fake_poll_base):
        asyncio.run(run())

    assert call_count >= 2


# -- main CLI tests --


@patch("airtable_proxy.poller.initialize")
@patch("airtable_proxy.poller.load_config_from_file")
def test_main_once(mock_load, mock_init, tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "hostname: test\nbases: {}\nstorage:\n  sqlite: /tmp/test.db\n"
    )
    mock_load.return_value = MagicMock()

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, [str(config_file), "--once"])
    assert result.exit_code == 0
    mock_init.assert_called_once()


@patch("airtable_proxy.poller.asyncio.run")
@patch("airtable_proxy.poller.load_config_from_file")
@patch("airtable_proxy.poller.initialize")
def test_main_without_once_runs_polling(
    _mock_init, mock_load, mock_asyncio_run, tmp_path
):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "hostname: test\nbases: {}\nstorage:\n  sqlite: /tmp/test.db\n"
    )
    mock_load.return_value = MagicMock()

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, [str(config_file)])
    assert result.exit_code == 0
    mock_asyncio_run.assert_called_once()
    # Close the coroutine to avoid "was never awaited" warning
    mock_asyncio_run.call_args[0][0].close()
