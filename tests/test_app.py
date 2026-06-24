from unittest.mock import patch

import pytest
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


def test_proxy_get_request(httpx_mock, tmp_path):
    """Test that GET requests to /v0/* are proxied to Airtable."""
    application = app.create_app(config=make_config(tmp_path))

    httpx_mock.add_response(
        json={"records": [{"id": "rec123", "fields": {"Name": "Test"}}]},
    )

    with TestClient(application) as client:
        response = client.get(
            "/v0/appXXX/TableName",
            headers={"Authorization": "Bearer patXXX"},
        )

    assert response.status_code == 200
    assert response.json() == {"records": [{"id": "rec123", "fields": {"Name": "Test"}}]}

    request = httpx_mock.get_request()
    assert request.method == "GET"
    assert str(request.url) == "https://api.airtable.com/v0/appXXX/TableName"
    assert request.headers["Authorization"] == "Bearer patXXX"


def test_proxy_post_request_with_body(httpx_mock, tmp_path):
    """Test that POST requests with body are proxied correctly."""
    application = app.create_app(config=make_config(tmp_path))

    httpx_mock.add_response(
        json={"id": "rec123", "fields": {"Name": "New Record"}},
    )

    with TestClient(application) as client:
        response = client.post(
            "/v0/appXXX/TableName",
            json={"fields": {"Name": "New Record"}},
            headers={"Authorization": "Bearer patXXX"},
        )

    assert response.status_code == 200

    request = httpx_mock.get_request()
    assert request.method == "POST"
    assert b"New Record" in request.content


def test_proxy_delete_request(httpx_mock, tmp_path):
    """Test that DELETE requests to /v0/* are proxied via the catch-all route."""
    application = app.create_app(config=make_config(tmp_path))

    httpx_mock.add_response(json={"deleted": True, "id": "rec123"})

    with TestClient(application) as client:
        response = client.delete(
            "/v0/appXXX/TableName/rec123",
            headers={"Authorization": "Bearer patXXX"},
        )

    assert response.status_code == 200
    request = httpx_mock.get_request()
    assert request.method == "DELETE"


def test_proxy_passes_query_params(httpx_mock, tmp_path):
    """Test that query parameters are forwarded to Airtable."""
    application = app.create_app(config=make_config(tmp_path))

    httpx_mock.add_response(json={"records": []})

    with TestClient(application) as client:
        client.get(
            "/v0/appXXX/TableName?maxRecords=10&view=Grid",
            headers={"Authorization": "Bearer patXXX"},
        )

    request = httpx_mock.get_request()
    assert "maxRecords" in str(request.url)
    assert "view" in str(request.url)


def test_create_app_loads_config_from_env(tmp_path):
    """When config is None, create_app loads from AIRTABLE_PROXY_CONFIG env var."""
    config_file = tmp_path / "env_config.yaml"
    config_file.write_text(
        f"hostname: test.example.com\nbases: {{}}\nstorage:\n  sqlite: {tmp_path / 'test.db'}\n"
    )
    with patch.dict("os.environ", {"AIRTABLE_PROXY_CONFIG": str(config_file)}):
        application = app.create_app(config=None)
    with TestClient(application) as client:
        response = client.get("/health")
        assert response.status_code == 200


@pytest.mark.parametrize(
    "status_code, error_type",
    [
        (401, "AUTHENTICATION_REQUIRED"),
        (403, "INVALID_PERMISSIONS_OR_MODEL_NOT_FOUND"),
        (404, "NOT_FOUND"),
        (500, "INTERNAL_SERVER_ERROR"),
    ],
)
def test_proxy_forwards_error_responses(httpx_mock, tmp_path, status_code, error_type):
    """Test that error responses from Airtable are forwarded correctly."""
    application = app.create_app(config=make_config(tmp_path))

    httpx_mock.add_response(
        status_code=status_code,
        json={"error": {"type": error_type}},
    )

    with TestClient(application) as client:
        response = client.get("/v0/appXXX/TableName")

    assert response.status_code == status_code
    assert response.json()["error"]["type"] == error_type
