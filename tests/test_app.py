from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from airtable_proxy.app import create_app, find_or_create_webhook


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
