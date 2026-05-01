"""Tests for the get record endpoint."""

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


@pytest.fixture
def client_with_data(test_app):
    with TestClient(test_app) as client:
        populate_test_data(test_app.state.persistence)
        yield client, test_app.state.persistence


def test_returns_single_record(client_with_data):
    """GET /v0/{base}/{table}/{record} returns one record from local storage."""
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}")

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
    response = client.get(f"/v0/{BASE_ID}/{table_id_or_name}/{REC_1}")

    assert response.status_code == 200
    assert response.json()["id"] == REC_1
