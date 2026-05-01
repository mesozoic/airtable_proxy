"""Tests for the get record endpoint."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from pyairtable.testing import fake_id

from airtable_proxy import app, auth
from airtable_proxy.config import Config

BASE_ID = fake_id("app")
TABLE_ID = fake_id("tbl")
FLD_NAME = fake_id("fld")
FLD_AGE = fake_id("fld")
FLD_ACTIVE = fake_id("fld")
REC_1 = fake_id("rec")
REC_2 = fake_id("rec")

TOKEN = "patFakeTestToken.secret"
TOKEN_HASH = auth.hash_token(TOKEN)
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def make_config(tmp_path):
    return Config.model_validate(
        {
            "hostname": "test.example.com",
            "bases": {},
            "storage": {"sqlite": str(tmp_path / "test.db")},
        }
    )


@pytest.fixture
def test_app(tmp_path):
    return app.create_app(config=make_config(tmp_path))


def populate_test_data(persistence):
    persistence.save_table(BASE_ID, TABLE_ID, "Test Table")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_NAME, "Name", "singleLineText")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_AGE, "Age", "number")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_ACTIVE, "Active", "checkbox")
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_1,
        {FLD_NAME: "Alice", FLD_AGE: 30, FLD_ACTIVE: True},
        "2024-01-01T00:00:00.000Z",
    )
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_2,
        {FLD_NAME: "Bob", FLD_AGE: 25, FLD_ACTIVE: False},
        "2024-01-02T00:00:00.000Z",
    )
    persistence.save_auth(BASE_ID, TOKEN_HASH)


@pytest.fixture
def client_with_data(test_app):
    with TestClient(test_app) as client:
        populate_test_data(test_app.state.persistence)
        yield client, test_app.state.persistence


def test_returns_single_record(client_with_data):
    """GET /v0/{base}/{table}/{record} returns one record from local storage."""
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == REC_1
    assert data["createdTime"] == "2024-01-01T00:00:00.000Z"
    assert data["fields"]["Name"] == "Alice"
    assert data["fields"]["Age"] == 30
    assert data["fields"]["Active"] is True
    assert "records" not in data


@pytest.mark.parametrize("table_id_or_name", [TABLE_ID, "Test Table", "Test%20Table"])
def test_returns_record_by_table_name(client_with_data, table_id_or_name):
    """The route accepts a table ID or table name (URL-encoded or not)."""
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{table_id_or_name}/{REC_1}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["id"] == REC_1


def test_returns_fields_by_name_by_default(client_with_data):
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}", headers=AUTH_HEADERS)

    fields = response.json()["fields"]
    assert "Name" in fields
    assert "Age" in fields
    assert FLD_NAME not in fields


def test_return_fields_by_field_id_true(client_with_data):
    client, _ = client_with_data
    response = client.get(
        f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}?returnFieldsByFieldId=true", headers=AUTH_HEADERS
    )

    fields = response.json()["fields"]
    assert FLD_NAME in fields
    assert FLD_AGE in fields
    assert "Name" not in fields
    assert fields[FLD_NAME] == "Alice"


def test_omits_empty_values(client_with_data):
    """Empty fields are omitted, matching Airtable's behavior."""
    client, persistence = client_with_data
    rec_empty = fake_id("rec")
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        rec_empty,
        {FLD_NAME: "", FLD_AGE: None, FLD_ACTIVE: False},
        "2024-01-04T00:00:00.000Z",
    )

    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}/{rec_empty}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["fields"] == {}


@patch("airtable_proxy.proxy.httpx.AsyncClient")
def test_proxy_when_cell_format_string(mock_client, client_with_data):
    """cellFormat=string forces a proxy to Airtable."""
    mock_response = httpx.Response(200, json={"id": REC_1, "fields": {}, "createdTime": "x"})
    mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.return_value.request = AsyncMock(return_value=mock_response)

    client, _ = client_with_data
    response = client.get(
        f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}?cellFormat=string", headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    mock_client.return_value.request.assert_called_once()


@patch("airtable_proxy.proxy.httpx.AsyncClient")
def test_proxy_when_table_not_in_local_storage(mock_client, test_app):
    """A table not in local storage falls through to the proxy."""
    mock_response = httpx.Response(200, json={"id": REC_1, "fields": {}, "createdTime": "x"})
    mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.return_value.request = AsyncMock(return_value=mock_response)

    with TestClient(test_app) as client:
        response = client.get(f"/v0/{BASE_ID}/UnknownTable/{REC_1}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    mock_client.return_value.request.assert_called_once()


@patch("airtable_proxy.proxy.httpx.AsyncClient")
def test_proxy_when_record_not_in_local_storage(mock_client, client_with_data):
    """A record not in local storage falls through to the proxy."""
    mock_response = httpx.Response(200, json={"id": "recMissing", "fields": {}, "createdTime": "x"})
    mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.return_value.request = AsyncMock(return_value=mock_response)

    client, _ = client_with_data
    missing = fake_id("rec")
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}/{missing}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    mock_client.return_value.request.assert_called_once()


# Authentication tests


def test_returns_401_without_auth_header(client_with_data):
    """Requests without Authorization header return 401."""
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}")
    assert response.status_code == 401


def test_returns_403_with_invalid_token(client_with_data):
    """Requests with an unknown token that fails Airtable verification return 403."""
    client, _ = client_with_data
    with patch("airtable_proxy.auth.httpx.AsyncClient") as mock_client:
        mock_response = httpx.Response(401, json={"error": {}})
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_client.return_value.get = AsyncMock(return_value=mock_response)

        response = client.get(
            f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}",
            headers={"Authorization": "Bearer patBadToken.invalid"},
        )

    assert response.status_code == 403
