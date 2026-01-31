import pytest

from airtable_proxy import persistence
from airtable_proxy.persistence import RecordInfo, TableInfo, WebhookInfo


@pytest.fixture
def persist(storage):
    return persistence.AirtablePersistence(storage)


# Webhook tests


def test_get_webhook_returns_none_when_missing(persist):
    assert persist.get_webhook("appMissing") is None


def test_save_and_get_webhook(persist):
    persist.save_webhook("appBase1", webhook_id="wh123", cursor=42)
    webhook = persist.get_webhook("appBase1")
    assert webhook == WebhookInfo(webhook_id="wh123", cursor=42)


def test_save_webhook_updates_existing(persist):
    persist.save_webhook("appBase1", webhook_id="wh123", cursor=1)
    persist.save_webhook("appBase1", webhook_id="wh123", cursor=99)
    assert persist.get_webhook("appBase1").cursor == 99


# Table tests


def test_get_table_returns_none_when_missing(persist):
    assert persist.get_table("appBase1", "tblMissing") is None


def test_save_and_get_table(persist):
    persist.save_table("appBase1", "tbl123", table_name="My Table")
    table = persist.get_table("appBase1", "tbl123")
    assert table == TableInfo(table_name="My Table")


def test_get_tables_for_base(persist):
    persist.save_table("appBase1", "tblA", table_name="Table A")
    persist.save_table("appBase1", "tblB", table_name="Table B")
    persist.save_table("appBase2", "tblC", table_name="Table C")

    tables = persist.get_tables("appBase1")
    assert sorted(tables.keys()) == ["tblA", "tblB"]


# Record tests


def test_get_record_returns_none_when_missing(persist):
    assert persist.get_record("appBase1", "tbl1", "recMissing") is None


def test_save_and_get_record(persist):
    persist.save_record(
        "appBase1",
        "tbl1",
        "rec123",
        fields={"fld1": "value1", "fld2": 42},
        created_time="2024-01-01T00:00:00.000Z",
    )
    record = persist.get_record("appBase1", "tbl1", "rec123")
    assert record == RecordInfo(
        fields={"fld1": "value1", "fld2": 42}, created_time="2024-01-01T00:00:00.000Z"
    )


def test_delete_record(persist):
    persist.save_record("appBase1", "tbl1", "rec123", fields={}, created_time="")
    persist.delete_record("appBase1", "tbl1", "rec123")
    assert persist.get_record("appBase1", "tbl1", "rec123") is None


def test_get_records_for_table(persist):
    persist.save_record("appBase1", "tbl1", "recA", fields={"x": 1}, created_time="")
    persist.save_record("appBase1", "tbl1", "recB", fields={"x": 2}, created_time="")
    persist.save_record("appBase1", "tbl2", "recC", fields={"x": 3}, created_time="")

    records = persist.get_records("appBase1", "tbl1")
    assert sorted(records.keys()) == ["recA", "recB"]
