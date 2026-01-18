from unittest.mock import MagicMock, patch

import pytest

from airtable_proxy import persistence, poller, storage
from airtable_proxy.persistence import RecordInfo, TableInfo


@pytest.fixture
def valid_config(tmp_path):
    return {
        "hostname": "airtable-proxy.example.com",
        "bases": {
            "appTestBase123": {"api_key": "patTestKey.secret"},
        },
        "storage": {"sqlite": str(tmp_path / "test.db")},
    }


def _setup_mock_api(mock_api):
    mock_api.return_value.whoami.return_value = {"id": "usr123"}
    mock_api.return_value.base.return_value.webhooks.return_value = []
    mock_api.return_value.base.return_value.add_webhook.return_value = MagicMock(id="wh_new123")
    mock_api.return_value.base.return_value.webhook.return_value = MagicMock(id="wh_new123")
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
    existing_webhook.notification_url = "https://airtable-proxy.example.com/webhooks/appTestBase123"
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


def test_refresh_tables_saves_tables_and_records(tmp_path):
    mock_base = MagicMock()

    # Set up mock schema with two tables
    mock_table1 = MagicMock()
    mock_table1.id = "tbl1"
    mock_table1.name = "Table One"
    mock_table2 = MagicMock()
    mock_table2.id = "tbl2"
    mock_table2.name = "Table Two"
    mock_base.schema.return_value.tables = [mock_table1, mock_table2]

    # Set up mock records for each table
    mock_base.table.return_value.all.side_effect = [
        [
            {"id": "rec1", "fields": {"fldA": "value1"}, "createdTime": "2024-01-01T00:00:00.000Z"},
            {"id": "rec2", "fields": {"fldA": "value2"}, "createdTime": "2024-01-02T00:00:00.000Z"},
        ],
        [
            {"id": "rec3", "fields": {"fldB": "value3"}, "createdTime": "2024-01-03T00:00:00.000Z"},
        ],
    ]

    store = storage.Storage(tmp_path / "test_db")
    persist = persistence.AirtablePersistence(store)

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

    # Verify table.all was called with return_fields_by_field_id=True
    mock_base.table.return_value.all.assert_called_with(return_fields_by_field_id=True)

    store.close()
