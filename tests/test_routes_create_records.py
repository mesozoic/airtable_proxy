"""Tests for the create-records mutation route."""

from fastapi.testclient import TestClient
from pyairtable.testing import fake_id

from airtable_proxy import app
from airtable_proxy.config import Config

BASE_ID = fake_id("app")
TABLE_ID = fake_id("tbl")
FLD_NAME = fake_id("fld")
REC_1 = fake_id("rec")


def make_config(tmp_path):
    return Config.model_validate(
        {
            "hostname": "test.example.com",
            "bases": {},
            "storage": {"sqlite": str(tmp_path / "test.db")},
        }
    )


def populate_table(persistence):
    persistence.save_table(BASE_ID, TABLE_ID, "Test Table")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_NAME, "Name", "singleLineText")


def test_post_updates_cache_with_single_record(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={
            "id": REC_1,
            "createdTime": "2024-01-01T00:00:00.000Z",
            "fields": {"Name": "Alice"},
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate_table(test_app.state.persistence)
        response = client.post(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            json={"fields": {"Name": "Alice"}},
        )

        assert response.status_code == 200
        persistence = test_app.state.persistence
        stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
        assert stored.fields == {FLD_NAME: "Alice"}


def test_post_updates_cache_with_multi_record_response(httpx_mock, tmp_path):
    rec_2 = fake_id("rec")
    httpx_mock.add_response(
        json={
            "records": [
                {"id": REC_1, "createdTime": "x", "fields": {"Name": "Alice"}},
                {"id": rec_2, "createdTime": "x", "fields": {"Name": "Bob"}},
            ]
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate_table(test_app.state.persistence)
        response = client.post(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            json={"records": [{"fields": {"Name": "Alice"}}, {"fields": {"Name": "Bob"}}]},
        )

        assert response.status_code == 200
        persistence = test_app.state.persistence
        assert persistence.get_record(BASE_ID, TABLE_ID, REC_1).fields == {FLD_NAME: "Alice"}
        assert persistence.get_record(BASE_ID, TABLE_ID, rec_2).fields == {FLD_NAME: "Bob"}


def test_post_with_return_fields_by_field_id(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={
            "id": REC_1,
            "createdTime": "2024-01-01T00:00:00.000Z",
            "fields": {FLD_NAME: "Alice"},
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate_table(test_app.state.persistence)
        response = client.post(
            f"/v0/{BASE_ID}/{TABLE_ID}?returnFieldsByFieldId=true",
            json={"fields": {FLD_NAME: "Alice"}},
        )

        assert response.status_code == 200
        persistence = test_app.state.persistence
        assert persistence.get_record(BASE_ID, TABLE_ID, REC_1).fields == {FLD_NAME: "Alice"}


def test_post_non_2xx_does_not_update_cache(httpx_mock, tmp_path):
    httpx_mock.add_response(status_code=422, json={"error": "bad request"})

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate_table(test_app.state.persistence)
        response = client.post(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            json={"fields": {"Name": "Alice"}},
        )

        assert response.status_code == 422
        assert persistence_records(test_app) == {}


def test_post_unknown_table_falls_through_to_proxy(httpx_mock, tmp_path):
    httpx_mock.add_response(json={"id": REC_1, "createdTime": "x", "fields": {"Name": "Alice"}})

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        response = client.post(
            f"/v0/{BASE_ID}/UnknownTable",
            json={"fields": {"Name": "Alice"}},
        )

    assert response.status_code == 200
    assert len(httpx_mock.get_requests()) == 1


def test_post_non_json_response_does_not_update_cache(httpx_mock, tmp_path):
    # Coverage for the ValueError branch in _apply_to_cache when Airtable
    # returns a 2xx with non-JSON content (e.g. plain text or HTML error pages).
    httpx_mock.add_response(
        status_code=200, content=b"not-json", headers={"Content-Type": "text/plain"}
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate_table(test_app.state.persistence)
        response = client.post(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            json={"fields": {"Name": "Alice"}},
        )

        assert response.status_code == 200
        assert persistence_records(test_app) == {}


def persistence_records(test_app):
    return test_app.state.persistence.get_records(BASE_ID, TABLE_ID)
