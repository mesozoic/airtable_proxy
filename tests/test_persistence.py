import pytest

from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage


@pytest.fixture
def persistence(tmp_path):
    storage = Storage(tmp_path / "test_db")
    return AirtablePersistence(storage)


# Webhook tests


def test_get_webhook_returns_none_when_missing(persistence):
    assert persistence.get_webhook("appMissing") is None


def test_save_and_get_webhook(persistence):
    persistence.save_webhook("appBase1", webhook_id="wh123", cursor=42)
    webhook = persistence.get_webhook("appBase1")
    assert webhook == {"webhook_id": "wh123", "cursor": 42}


def test_save_webhook_updates_existing(persistence):
    persistence.save_webhook("appBase1", webhook_id="wh123", cursor=1)
    persistence.save_webhook("appBase1", webhook_id="wh123", cursor=99)
    assert persistence.get_webhook("appBase1")["cursor"] == 99


# Table tests


def test_get_table_returns_none_when_missing(persistence):
    assert persistence.get_table("appBase1", "tblMissing") is None


def test_save_and_get_table(persistence):
    persistence.save_table("appBase1", "tbl123", table_name="My Table")
    table = persistence.get_table("appBase1", "tbl123")
    assert table == {"table_name": "My Table"}


def test_get_tables_for_base(persistence):
    persistence.save_table("appBase1", "tblA", table_name="Table A")
    persistence.save_table("appBase1", "tblB", table_name="Table B")
    persistence.save_table("appBase2", "tblC", table_name="Table C")

    tables = persistence.get_tables("appBase1")
    assert sorted(tables.keys()) == ["tblA", "tblB"]


# Record tests


def test_get_record_returns_none_when_missing(persistence):
    assert persistence.get_record("appBase1", "tbl1", "recMissing") is None


def test_save_and_get_record(persistence):
    persistence.save_record(
        "appBase1", "tbl1", "rec123", fields={"fld1": "value1", "fld2": 42}, created_time="2024-01-01T00:00:00.000Z"
    )
    record = persistence.get_record("appBase1", "tbl1", "rec123")
    assert record == {"fields": {"fld1": "value1", "fld2": 42}, "created_time": "2024-01-01T00:00:00.000Z"}


def test_delete_record(persistence):
    persistence.save_record("appBase1", "tbl1", "rec123", fields={}, created_time="")
    persistence.delete_record("appBase1", "tbl1", "rec123")
    assert persistence.get_record("appBase1", "tbl1", "rec123") is None


def test_get_records_for_table(persistence):
    persistence.save_record("appBase1", "tbl1", "recA", fields={"x": 1}, created_time="")
    persistence.save_record("appBase1", "tbl1", "recB", fields={"x": 2}, created_time="")
    persistence.save_record("appBase1", "tbl2", "recC", fields={"x": 3}, created_time="")

    records = persistence.get_records("appBase1", "tbl1")
    assert sorted(records.keys()) == ["recA", "recB"]
