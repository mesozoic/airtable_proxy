from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from airtable_proxy.app import create_app


@pytest.fixture
def valid_config():
    return {
        "hostname": "airtable-proxy.example.com",
        "bases": {
            "appTestBase123": {"api_key": "patTestKey.secret"},
        },
    }


@patch("airtable_proxy.app.Api")
def test_health_endpoint(mock_api, valid_config):
    mock_api.return_value.whoami.return_value = {"id": "usr123"}
    app = create_app(valid_config)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


@patch("airtable_proxy.app.Api")
def test_startup_calls_whoami_for_each_base(mock_api, valid_config):
    mock_api.return_value.whoami.return_value = {"id": "usr123"}
    app = create_app(valid_config)
    with TestClient(app):
        pass
    mock_api.assert_called_once_with("patTestKey.secret")
    mock_api.return_value.whoami.assert_called_once()


@patch("airtable_proxy.app.Api")
def test_startup_fails_if_airtable_unavailable(mock_api, valid_config):
    mock_api.return_value.whoami.side_effect = Exception("Connection failed")
    app = create_app(valid_config)
    with pytest.raises(Exception, match="Connection failed"):
        with TestClient(app):
            pass
