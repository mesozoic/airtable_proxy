from unittest.mock import MagicMock, patch

import pytest

from airtable_proxy import persistence, poller, storage
from airtable_proxy.config import BaseConfig
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

    # Verify table.all was called with use_field_ids=True
    mock_base.table.return_value.all.assert_called_with(use_field_ids=True)

    store.close()


# Integration tests against real Airtable API


@pytest.fixture
def webhook_cleanup(hostname, base):
    """
    Clean up any webhook matching our hostname after the test.
    """
    url = poller.callback_url(hostname, base.id)
    try:
        yield
    finally:
        for webhook in base.webhooks():
            if webhook.notification_url == url:
                webhook.delete()


@pytest.fixture
def record_cleanup(base):
    """
    Track and clean up test records after the test.
    """
    table = base.table("TEST_TABLE")
    record_ids = []
    try:
        yield record_ids
    finally:
        for record_id in record_ids:
            table.delete(record_id)


@pytest.mark.integration
def test_poll_base(api, api_key, base_id, hostname, tmp_path, webhook_cleanup, record_cleanup):
    """
    Integration test: initialize poller, create records, poll, verify sync.
    """
    db_path = tmp_path / "test.db"
    base = api.base(base_id)
    table = base.table("TEST_TABLE")

    config = {
        "hostname": hostname,
        "bases": {base_id: {"api_key": api_key}},
        "storage": {"sqlite": str(db_path)},
    }

    # Open persistence to verify polling results
    store = storage.Storage(db_path)
    persist = persistence.AirtablePersistence(store)

    # Initialize the poller - creates webhook and syncs existing data
    poller.initialize(config)

    # Verify webhook was created
    webhook_info = persist.get_webhook(base_id)
    assert webhook_info is not None, "Webhook should be created by initialize()"

    # Create test records in Airtable (using TEST_TABLE field names)
    text_field_id = "fldzbVdWW4xJdZ1em"  # field ID for "text"
    records = table.batch_create(
        [
            {"text": "Alice", "number": 100},
            {"text": "Bob", "number": 200},
        ]
    )
    record_cleanup.extend(r["id"] for r in records)
    alice_id, bob_id = record_cleanup

    # Poll and verify records were synced
    base_config = BaseConfig(api_key=api_key)
    poller.poll_base(base_id, base_config, persist)

    for record_id in record_cleanup:
        synced = persist.get_record(base_id, table.id, record_id)
        assert synced is not None, f"Record {record_id} not synced"

    # Verify cursor was updated
    webhook_info = persist.get_webhook(base_id)
    assert webhook_info is not None
    assert webhook_info.cursor > 0, "Cursor should be updated after polling"

    # Update a record and verify sync (fields are stored by field ID)
    table.update(alice_id, {"text": "Alice Updated"})
    poller.poll_base(base_id, base_config, persist)
    updated = persist.get_record(base_id, table.id, alice_id)
    assert updated is not None
    assert updated.fields.get(text_field_id) == "Alice Updated"

    # Delete a record and verify sync
    table.delete(bob_id)
    record_cleanup.remove(bob_id)
    poller.poll_base(base_id, base_config, persist)
    deleted = persist.get_record(base_id, table.id, bob_id)
    assert deleted is None, "Deleted record should be removed from persistence"

    store.close()
