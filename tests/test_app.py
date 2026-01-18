from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from airtable_proxy.app import create_app, find_or_create_webhook, refresh_tables
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage


@pytest.fixture
def valid_config():
    return {
        "hostname": "airtable-proxy.example.com",
        "bases": {
            "appTestBase123": {"api_key": "patTestKey.secret"},
        },
    }


def _setup_mock_api(mock_api):
    mock_api.return_value.whoami.return_value = {"id": "usr123"}
    mock_api.return_value.base.return_value.webhooks.return_value = []
    mock_api.return_value.base.return_value.add_webhook.return_value = MagicMock(id="wh_new123")
    mock_api.return_value.base.return_value.webhook.return_value = MagicMock(id="wh_new123")
    # Set up empty schema for refresh_tables
    mock_api.return_value.base.return_value.schema.return_value.tables = []


@patch("airtable_proxy.app.Api")
def test_health_endpoint(mock_api, valid_config, tmp_path):
    _setup_mock_api(mock_api)
    app = create_app(valid_config, storage_path=tmp_path / "test_db")
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


@patch("airtable_proxy.app.Api")
def test_startup_calls_whoami_for_each_base(mock_api, valid_config, tmp_path):
    _setup_mock_api(mock_api)
    app = create_app(valid_config, storage_path=tmp_path / "test_db")
    with TestClient(app):
        pass
    mock_api.assert_called_once_with("patTestKey.secret")
    mock_api.return_value.whoami.assert_called_once()


@patch("airtable_proxy.app.Api")
def test_startup_fails_if_airtable_unavailable(mock_api, valid_config, tmp_path):
    mock_api.return_value.whoami.side_effect = Exception("Connection failed")
    app = create_app(valid_config, storage_path=tmp_path / "test_db")
    with pytest.raises(Exception, match="Connection failed"):
        with TestClient(app):
            pass


@patch("airtable_proxy.app.Api")
def test_startup_creates_webhook_if_not_exists(mock_api, valid_config, tmp_path):
    _setup_mock_api(mock_api)
    app = create_app(valid_config, storage_path=tmp_path / "test_db")
    with TestClient(app):
        pass
    mock_api.return_value.base.return_value.add_webhook.assert_called_once()


@patch("airtable_proxy.app.Api")
def test_startup_finds_existing_webhook(mock_api, valid_config, tmp_path):
    _setup_mock_api(mock_api)
    existing_webhook = MagicMock()
    existing_webhook.id = "wh_existing"
    existing_webhook.notification_url = "https://airtable-proxy.example.com/webhooks/appTestBase123"
    mock_api.return_value.base.return_value.webhooks.return_value = [existing_webhook]

    app = create_app(valid_config, storage_path=tmp_path / "test_db")
    with TestClient(app):
        pass

    mock_api.return_value.base.return_value.add_webhook.assert_not_called()


def test_find_or_create_webhook_finds_existing():
    mock_base = MagicMock()
    existing = MagicMock(notification_url="https://example.com/callback")
    mock_base.webhooks.return_value = [existing]

    result = find_or_create_webhook(mock_base, "https://example.com/callback")

    assert result == existing
    mock_base.add_webhook.assert_not_called()


def test_find_or_create_webhook_creates_new():
    mock_base = MagicMock()
    mock_base.webhooks.return_value = []
    mock_base.add_webhook.return_value = MagicMock(id="wh_new")
    mock_base.webhook.return_value = MagicMock(id="wh_new")

    result = find_or_create_webhook(mock_base, "https://example.com/callback")

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

    storage = Storage(tmp_path / "test_db")
    persistence = AirtablePersistence(storage)

    refresh_tables(mock_base, "appBase1", persistence)

    # Verify tables were saved
    assert persistence.get_table("appBase1", "tbl1") == {"table_name": "Table One"}
    assert persistence.get_table("appBase1", "tbl2") == {"table_name": "Table Two"}

    # Verify records were saved
    assert persistence.get_record("appBase1", "tbl1", "rec1") == {
        "fields": {"fldA": "value1"},
        "created_time": "2024-01-01T00:00:00.000Z",
    }
    assert persistence.get_record("appBase1", "tbl1", "rec2") == {
        "fields": {"fldA": "value2"},
        "created_time": "2024-01-02T00:00:00.000Z",
    }
    assert persistence.get_record("appBase1", "tbl2", "rec3") == {
        "fields": {"fldB": "value3"},
        "created_time": "2024-01-03T00:00:00.000Z",
    }

    # Verify table.all was called with return_fields_by_field_id=True
    mock_base.table.return_value.all.assert_called_with(return_fields_by_field_id=True)

    storage.close()
