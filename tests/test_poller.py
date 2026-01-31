import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from pyairtable.models.webhook import WebhookPayload

from airtable_proxy import persistence, poller
from airtable_proxy.config import BaseConfig, Config
from airtable_proxy.persistence import (
    AirtablePersistence,
    FieldInfo,
    RecordInfo,
    TableInfo,
    WebhookInfo,
)
from airtable_proxy.storage import Storage


@pytest.fixture
def valid_config(tmp_path):
    return {
        "hostname": "airtable-proxy.example.com",
        "bases": {
            "appTestBase123": {"api_key": "patTestKey.secret"},
        },
        "storage": {"sqlite": str(tmp_path / "test.db")},
    }


def _make_mock_field(field_id, name, field_type):
    """Create a mock Airtable field."""
    field = MagicMock()
    field.id = field_id
    field.name = name
    field.type = field_type
    return field


def _make_mock_table(table_id, name, *, fields=None):
    """Create a mock Airtable table schema entry with optional fields."""
    table = MagicMock()
    table.id = table_id
    table.name = name
    table.fields = fields or []
    return table


@pytest.fixture
def mock_base():
    """A MagicMock base that can be extended with tables, fields, and records."""
    base = MagicMock()
    base.schema.return_value.tables = []
    base.table.return_value.all.return_value = []
    return base


def _setup_mock_api(mock_api):
    mock_api.return_value.whoami.return_value = {"id": "usr123"}
    mock_api.return_value.base.return_value.webhooks.return_value = []
    mock_api.return_value.base.return_value.add_webhook.return_value = MagicMock(
        id="wh_new123"
    )
    mock_api.return_value.base.return_value.webhook.return_value = MagicMock(
        id="wh_new123"
    )
    mock_api.return_value.base.return_value.schema.return_value.tables = []


@patch("airtable_proxy.poller.Api")
def test_initialize_calls_whoami_for_each_base(mock_api, valid_config):
    _setup_mock_api(mock_api)
    poller.initialize(valid_config)
    mock_api.assert_called_once_with("patTestKey.secret")
    mock_api.return_value.whoami.assert_called_once()


@patch("airtable_proxy.poller.Api")
def test_initialize_fails_if_airtable_unavailable(mock_api, valid_config):
    mock_api.return_value.whoami.side_effect = Exception("Connection failed")
    with pytest.raises(Exception, match="Connection failed"):
        poller.initialize(valid_config)


@patch("airtable_proxy.poller.Api")
def test_initialize_creates_webhook_if_not_exists(mock_api, valid_config):
    _setup_mock_api(mock_api)
    poller.initialize(valid_config)
    mock_api.return_value.base.return_value.add_webhook.assert_called_once()


@patch("airtable_proxy.poller.Api")
def test_initialize_finds_existing_webhook(mock_api, valid_config):
    _setup_mock_api(mock_api)
    existing_webhook = MagicMock()
    existing_webhook.id = "wh_existing"
    existing_webhook.notification_url = (
        "https://airtable-proxy.example.com/webhooks/appTestBase123"
    )
    mock_api.return_value.base.return_value.webhooks.return_value = [existing_webhook]

    poller.initialize(valid_config)

    mock_api.return_value.base.return_value.add_webhook.assert_not_called()


def test_find_or_create_webhook_finds_existing():
    mock_base = MagicMock()
    existing = MagicMock(notification_url="https://example.com/callback")
    mock_base.webhooks.return_value = [existing]

    result = poller.find_or_create_webhook(mock_base, "https://example.com/callback")

    assert result == existing
    mock_base.add_webhook.assert_not_called()


def test_find_or_create_webhook_creates_new():
    mock_base = MagicMock()
    mock_base.webhooks.return_value = []
    mock_base.add_webhook.return_value = MagicMock(id="wh_new")
    mock_base.webhook.return_value = MagicMock(id="wh_new")

    result = poller.find_or_create_webhook(mock_base, "https://example.com/callback")

    mock_base.add_webhook.assert_called_once()
    assert result.id == "wh_new"


def test_refresh_tables_saves_tables_and_records(mock_base, storage):
    mock_base.schema.return_value.tables = [
        _make_mock_table("tbl1", "Table One"),
        _make_mock_table("tbl2", "Table Two"),
    ]
    mock_base.table.return_value.all.side_effect = [
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
        [
            {
                "id": "rec3",
                "fields": {"fldB": "value3"},
                "createdTime": "2024-01-03T00:00:00.000Z",
            },
        ],
    ]

    persist = persistence.AirtablePersistence(storage)

    poller.refresh_tables(mock_base, "appBase1", persist)

    # Verify tables were saved
    assert persist.get_table("appBase1", "tbl1") == TableInfo(table_name="Table One")
    assert persist.get_table("appBase1", "tbl2") == TableInfo(table_name="Table Two")

    # Verify records were saved
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

    # Verify table.all was called with use_field_ids=True
    mock_base.table.return_value.all.assert_called_with(use_field_ids=True)


def test_refresh_tables_saves_fields(mock_base, storage):
    """refresh_tables saves field metadata for each table."""
    mock_base.schema.return_value.tables = [
        _make_mock_table(
            "tbl1",
            "Table One",
            fields=[_make_mock_field("fldX", "Status", "singleSelect")],
        ),
    ]

    persist = AirtablePersistence(storage)
    poller.refresh_tables(mock_base, "appBase1", persist)

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
    # Should not raise
    poller.poll_base("appMissing", base_config, persist)


@patch("airtable_proxy.poller.Api")
def test_poll_base_processes_payloads(mock_api, storage):
    persist = AirtablePersistence(storage)
    persist.save_webhook("appB", webhook_id="whX", cursor=5)
    persist.save_table("appB", "tbl1", "Table")
    persist.save_record("appB", "tbl1", "rec1", fields={"f": "old"}, created_time="t")

    payload = _make_payload(
        cursor=6,
        changedTablesById={
            "tbl1": {
                "changedRecordsById": {
                    "rec1": {
                        "current": {"cellValuesByFieldId": {"f": "new"}},
                        "previous": {"cellValuesByFieldId": {"f": "old"}},
                        "unchanged": {"cellValuesByFieldId": {}},
                    },
                },
            }
        },
    )
    mock_api.return_value.base.return_value.webhook.return_value.payloads.return_value = [
        payload
    ]

    base_config = BaseConfig(api_key="patXXX")
    poller.poll_base("appB", base_config, persist)

    assert persist.get_record("appB", "tbl1", "rec1").fields["f"] == "new"
    assert persist.get_webhook("appB").cursor == 6


# -- initialize_base with existing webhook --


@patch("airtable_proxy.poller.Api")
def test_initialize_base_existing_webhook_polls(mock_api, storage):
    persist = AirtablePersistence(storage)
    persist.save_webhook("appB", webhook_id="whExist", cursor=3)

    mock_api.return_value.whoami.return_value = {"id": "usr1"}
    mock_api.return_value.base.return_value.webhook.return_value.payloads.return_value = (
        []
    )

    base_config = BaseConfig(api_key="patXXX")
    poller.initialize_base(
        callback_url="https://example.com/webhooks/appB",
        base_id="appB",
        base_config=base_config,
        persistence=persist,
    )

    # Should not have created a new webhook
    mock_api.return_value.base.return_value.add_webhook.assert_not_called()


# -- run_polling_loop tests --


def test_run_polling_loop_polls_and_handles_errors(tmp_path):
    config = Config(
        hostname="test.example.com",
        bases={"appB": BaseConfig(api_key="patXXX")},
        storage={"sqlite": str(tmp_path / "test.db")},
    )

    call_count = 0

    def fake_poll_base(base_id, base_config, persist):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("transient error")
        # Second call succeeds

    async def run():
        task = asyncio.create_task(poller.run_polling_loop(config))
        # Let it run two iterations
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


@patch("airtable_proxy.poller.asyncio")
@patch("airtable_proxy.poller.initialize")
@patch("airtable_proxy.poller.load_config_from_file")
def test_main_without_once_runs_polling(mock_load, _mock_init, mock_asyncio, tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "hostname: test\nbases: {}\nstorage:\n  sqlite: /tmp/test.db\n"
    )
    mock_load.return_value = MagicMock()

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, [str(config_file)])
    assert result.exit_code == 0
    mock_asyncio.run.assert_called_once()
