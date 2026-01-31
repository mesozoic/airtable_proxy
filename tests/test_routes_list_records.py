"""
Tests for the list records endpoint.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from pyairtable.testing import fake_id

from airtable_proxy import app
from airtable_proxy.config import Config

BASE_ID = fake_id("app")
TABLE_ID = fake_id("tbl")
FLD_NAME = fake_id("fld")
FLD_AGE = fake_id("fld")
FLD_ACTIVE = fake_id("fld")
REC_1 = fake_id("rec")
REC_2 = fake_id("rec")
REC_3 = fake_id("rec")


def make_config(tmp_path):
    return Config.model_validate(
        {
            "hostname": "test.example.com",
            "bases": {},
            "storage": {
                "sqlite": str(tmp_path / "test.db"),
            },
        }
    )


@pytest.fixture
def test_app(tmp_path):
    """
    Create a test application with persistence layer.
    """
    return app.create_app(config=make_config(tmp_path))


def populate_test_data(persistence):
    """
    Populate persistence layer with test data.
    """
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
        {FLD_NAME: "Bob", FLD_AGE: 25},
        "2024-01-02T00:00:00.000Z",
    )
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_3,
        {FLD_NAME: "Charlie", FLD_AGE: 35, FLD_ACTIVE: True},
        "2024-01-03T00:00:00.000Z",
    )


@pytest.fixture
def client_with_data(test_app):
    """
    Test client with pre-populated test data.
    """
    with TestClient(test_app) as client:
        populate_test_data(test_app.state.persistence)
        yield client, test_app.state.persistence


# Basic functionality tests


def test_returns_all_records(client_with_data):
    """
    List records returns all records from local storage.
    """
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}")

    assert response.status_code == 200
    data = response.json()
    assert "records" in data
    assert len(data["records"]) == 3


@pytest.mark.parametrize(
    "table_id_or_name", [TABLE_ID, "Test Table", "Test%20Table"]
)
def test_by_table_name(client_with_data, table_id_or_name):
    """
    List records works when using table name instead of table ID.
    """
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{table_id_or_name}")

    assert response.status_code == 200
    assert len(response.json()["records"]) == 3


def test_returns_fields_by_name(client_with_data):
    """
    By default, fields are keyed by field name, not field ID.
    """
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}")

    records = response.json()["records"]
    alice = next(r for r in records if r["fields"].get("Name") == "Alice")
    assert "Name" in alice["fields"]
    assert "Age" in alice["fields"]
    assert alice["fields"]["Name"] == "Alice"
    assert alice["fields"]["Age"] == 30


def test_includes_created_time(client_with_data):
    """
    Each record includes createdTime.
    """
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}")

    records = response.json()["records"]
    for record in records:
        assert "createdTime" in record
        assert "id" in record


def test_omits_empty_values(client_with_data):
    """
    Records omit fields with empty values (Airtable behavior).
    """
    client, persistence = client_with_data
    rec_empty = fake_id("rec")
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        rec_empty,
        {FLD_NAME: "", FLD_AGE: None, FLD_ACTIVE: False},
        "2024-01-04T00:00:00.000Z",
    )

    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}")

    records = response.json()["records"]
    empty_rec = next(r for r in records if r["id"] == rec_empty)
    # Empty string, None, and False should all be omitted
    assert empty_rec["fields"] == {}


def test_omits_empty_list_values(client_with_data):
    """Records omit fields with empty list values (Airtable behavior)."""
    client, persistence = client_with_data
    rec_empty_list = fake_id("rec")
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        rec_empty_list,
        {FLD_NAME: "Has Empty List", FLD_AGE: 10, FLD_ACTIVE: []},
        "2024-01-05T00:00:00.000Z",
    )

    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}")
    records = response.json()["records"]
    rec = next(r for r in records if r["id"] == rec_empty_list)
    assert "Active" not in rec["fields"]
    assert rec["fields"]["Name"] == "Has Empty List"


# Proxy condition tests


@patch("airtable_proxy.proxy.httpx.AsyncClient")
def test_proxy_when_view_param_present(mock_client, client_with_data):
    """
    Proxy to Airtable when view= parameter is present.
    """
    mock_response = httpx.Response(200, json={"records": []})
    mock_client.return_value.__aenter__ = AsyncMock(
        return_value=mock_client.return_value
    )
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.return_value.request = AsyncMock(return_value=mock_response)

    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}?view=Grid%20view")

    assert response.status_code == 200
    mock_client.return_value.request.assert_called_once()


@patch("airtable_proxy.proxy.httpx.AsyncClient")
def test_proxy_when_filter_by_formula_present(mock_client, client_with_data):
    """
    Proxy to Airtable when filterByFormula= parameter is present.
    """
    mock_response = httpx.Response(200, json={"records": []})
    mock_client.return_value.__aenter__ = AsyncMock(
        return_value=mock_client.return_value
    )
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.return_value.request = AsyncMock(return_value=mock_response)

    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}?filterByFormula={{Name}}='Alice'")

    assert response.status_code == 200
    mock_client.return_value.request.assert_called_once()


@patch("airtable_proxy.proxy.httpx.AsyncClient")
def test_proxy_when_cell_format_string(mock_client, client_with_data):
    """
    Proxy to Airtable when cellFormat=string.
    """
    mock_response = httpx.Response(200, json={"records": []})
    mock_client.return_value.__aenter__ = AsyncMock(
        return_value=mock_client.return_value
    )
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.return_value.request = AsyncMock(return_value=mock_response)

    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}?cellFormat=string")

    assert response.status_code == 200
    mock_client.return_value.request.assert_called_once()


@patch("airtable_proxy.proxy.httpx.AsyncClient")
def test_proxy_when_table_not_in_local_storage(mock_client, test_app):
    """
    Proxy to Airtable when the table is not in local storage.
    """
    mock_response = httpx.Response(200, json={"records": []})
    mock_client.return_value.__aenter__ = AsyncMock(
        return_value=mock_client.return_value
    )
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.return_value.request = AsyncMock(return_value=mock_response)

    with TestClient(test_app) as client:
        # No test data - table doesn't exist
        response = client.get(f"/v0/{BASE_ID}/UnknownTable")

    assert response.status_code == 200
    mock_client.return_value.request.assert_called_once()


# maxRecords tests


def test_max_records_limits_results(client_with_data):
    """
    maxRecords limits the number of records returned.
    """
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}?maxRecords=2")

    assert response.status_code == 200
    assert len(response.json()["records"]) == 2


def test_max_records_returns_all_if_fewer_exist(client_with_data):
    """
    maxRecords returns all records if fewer exist than the limit.
    """
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}?maxRecords=100")

    assert response.status_code == 200
    assert len(response.json()["records"]) == 3


# fields filter tests


def test_fields_filter_by_name(client_with_data):
    """
    fields parameter filters by field name.
    """
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}?fields=Name")

    assert response.status_code == 200
    records = response.json()["records"]
    for record in records:
        # Should only have Name field (if non-empty)
        assert set(record["fields"].keys()).issubset({"Name"})


def test_fields_filter_by_id(client_with_data):
    """
    fields parameter filters by field ID.
    """
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}?fields={FLD_NAME}")

    assert response.status_code == 200
    records = response.json()["records"]
    for record in records:
        assert set(record["fields"].keys()).issubset({"Name"})


def test_fields_filter_multiple(client_with_data):
    """
    fields parameter accepts multiple field names.
    """
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}?fields=Name&fields=Age")

    assert response.status_code == 200
    records = response.json()["records"]
    for record in records:
        assert set(record["fields"].keys()).issubset({"Name", "Age"})


# returnFieldsByFieldId tests


def test_return_fields_by_field_id(client_with_data):
    """
    returnFieldsByFieldId=true returns fields keyed by ID.
    """
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}?returnFieldsByFieldId=true")

    assert response.status_code == 200
    records = response.json()["records"]
    alice = next(r for r in records if r["fields"].get(FLD_NAME) == "Alice")
    assert FLD_NAME in alice["fields"]
    assert FLD_AGE in alice["fields"]
    assert alice["fields"][FLD_NAME] == "Alice"
    assert alice["fields"][FLD_AGE] == 30
