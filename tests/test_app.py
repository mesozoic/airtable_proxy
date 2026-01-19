from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from airtable_proxy import app
from airtable_proxy.config import Config


def make_config(tmp_path):
    return Config(
        hostname="test.example.com",
        bases={},
        storage={"sqlite": tmp_path / "test.db"},
    )


def test_health_endpoint(tmp_path):
    application = app.create_app(config=make_config(tmp_path))
    with TestClient(application) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_persistence_available_in_app_state(tmp_path):
    application = app.create_app(config=make_config(tmp_path))
    with TestClient(application):
        assert application.state.persistence is not None


def test_proxy_get_request(tmp_path):
    """Test that GET requests to /v0/* are proxied to Airtable."""
    application = app.create_app(config=make_config(tmp_path))

    mock_response = httpx.Response(
        200,
        json={"records": [{"id": "rec123", "fields": {"Name": "Test"}}]},
    )

    with patch("airtable_proxy.proxy.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_client.return_value.request = AsyncMock(return_value=mock_response)

        with TestClient(application) as client:
            response = client.get(
                "/v0/appXXX/TableName",
                headers={"Authorization": "Bearer patXXX"},
            )

        assert response.status_code == 200
        assert response.json() == {"records": [{"id": "rec123", "fields": {"Name": "Test"}}]}

        mock_client.return_value.request.assert_called_once()
        call_kwargs = mock_client.return_value.request.call_args.kwargs
        assert call_kwargs["method"] == "GET"
        assert call_kwargs["url"] == "https://api.airtable.com/v0/appXXX/TableName"
        assert call_kwargs["headers"]["Authorization"] == "Bearer patXXX"


def test_proxy_post_request_with_body(tmp_path):
    """Test that POST requests with body are proxied correctly."""
    application = app.create_app(config=make_config(tmp_path))

    mock_response = httpx.Response(
        200,
        json={"id": "rec123", "fields": {"Name": "New Record"}},
    )

    with patch("airtable_proxy.proxy.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_client.return_value.request = AsyncMock(return_value=mock_response)

        with TestClient(application) as client:
            response = client.post(
                "/v0/appXXX/TableName",
                json={"fields": {"Name": "New Record"}},
                headers={"Authorization": "Bearer patXXX"},
            )

        assert response.status_code == 200

        call_kwargs = mock_client.return_value.request.call_args.kwargs
        assert call_kwargs["method"] == "POST"
        assert b"New Record" in call_kwargs["content"]


def test_proxy_passes_query_params(tmp_path):
    """Test that query parameters are forwarded to Airtable."""
    application = app.create_app(config=make_config(tmp_path))

    mock_response = httpx.Response(200, json={"records": []})

    with patch("airtable_proxy.proxy.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_client.return_value.request = AsyncMock(return_value=mock_response)

        with TestClient(application) as client:
            client.get(
                "/v0/appXXX/TableName?maxRecords=10&view=Grid",
                headers={"Authorization": "Bearer patXXX"},
            )

        call_kwargs = mock_client.return_value.request.call_args.kwargs
        assert "maxRecords" in str(call_kwargs["params"])
        assert "view" in str(call_kwargs["params"])


def test_proxy_forwards_error_responses(tmp_path):
    """Test that error responses from Airtable are forwarded correctly."""
    application = app.create_app(config=make_config(tmp_path))

    mock_response = httpx.Response(
        401,
        json={"error": {"type": "AUTHENTICATION_REQUIRED"}},
    )

    with patch("airtable_proxy.proxy.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_client.return_value.request = AsyncMock(return_value=mock_response)

        with TestClient(application) as client:
            response = client.get("/v0/appXXX/TableName")

        assert response.status_code == 401
        assert response.json()["error"]["type"] == "AUTHENTICATION_REQUIRED"
