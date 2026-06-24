"""Tests for the delete-records mutation routes."""

from fastapi.testclient import TestClient
from pyairtable.testing import fake_id

from airtable_proxy import app
from airtable_proxy.config import Config

BASE_ID = fake_id("app")
TABLE_ID = fake_id("tbl")
FLD_NAME = fake_id("fld")
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


def populate(persistence):
    persistence.save_table(BASE_ID, TABLE_ID, "Test Table")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_NAME, "Name", "singleLineText")
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_1,
        {FLD_NAME: "Alice"},
        "2024-01-01T00:00:00.000Z",
    )
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_2,
        {FLD_NAME: "Bob"},
        "2024-01-02T00:00:00.000Z",
    )


def test_delete_single_record_removes_from_cache(httpx_mock, tmp_path):
    httpx_mock.add_response(json={"id": REC_1, "deleted": True})

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.delete(f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}")

        assert response.status_code == 200
        persistence = test_app.state.persistence
        assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is None
        assert persistence.get_record(BASE_ID, TABLE_ID, REC_2) is not None


def test_delete_multi_records_removes_from_cache(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={"records": [{"id": REC_1, "deleted": True}, {"id": REC_2, "deleted": True}]}
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.delete(f"/v0/{BASE_ID}/{TABLE_ID}?records[]={REC_1}&records[]={REC_2}")

        assert response.status_code == 200
        persistence = test_app.state.persistence
        assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is None
        assert persistence.get_record(BASE_ID, TABLE_ID, REC_2) is None


def test_delete_non_2xx_does_not_update_cache(httpx_mock, tmp_path):
    httpx_mock.add_response(status_code=404, json={"error": "not found"})

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.delete(f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}")

        assert response.status_code == 404
        persistence = test_app.state.persistence
        assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is not None


def test_delete_unknown_table_falls_through(httpx_mock, tmp_path):
    httpx_mock.add_response(json={"id": REC_1, "deleted": True})

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        response = client.delete(f"/v0/{BASE_ID}/UnknownTable/{REC_1}")

    assert response.status_code == 200
    assert len(httpx_mock.get_requests()) == 1


def test_delete_non_json_response_does_not_update_cache(httpx_mock, tmp_path):
    # Coverage for the ValueError branch in _apply_to_cache when Airtable
    # returns a 2xx with non-JSON content (e.g. plain text or HTML error pages).
    httpx_mock.add_response(
        status_code=200, content=b"not-json", headers={"Content-Type": "text/plain"}
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.delete(f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}")

        assert response.status_code == 200
        persistence = test_app.state.persistence
        assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is not None
