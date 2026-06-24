"""Tests for the update-records mutation routes."""

from fastapi.testclient import TestClient
from pyairtable.testing import fake_id

from airtable_proxy import app
from airtable_proxy.config import Config

BASE_ID = fake_id("app")
TABLE_ID = fake_id("tbl")
FLD_NAME = fake_id("fld")
FLD_AGE = fake_id("fld")
REC_1 = fake_id("rec")


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
    persistence.save_field(BASE_ID, TABLE_ID, FLD_AGE, "Age", "number")
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_1,
        {FLD_NAME: "Alice", FLD_AGE: 30},
        "2024-01-01T00:00:00.000Z",
    )


def test_patch_single_merges_with_existing(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={
            "id": REC_1,
            "createdTime": "2024-01-01T00:00:00.000Z",
            "fields": {"Age": 31},
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.patch(
            f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}",
            json={"fields": {"Age": 31}},
        )
        stored = test_app.state.persistence.get_record(BASE_ID, TABLE_ID, REC_1)

    assert response.status_code == 200
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 31}


def test_put_single_replaces_existing(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={
            "id": REC_1,
            "createdTime": "2024-01-01T00:00:00.000Z",
            "fields": {"Name": "Alicia"},
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.put(
            f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}",
            json={"fields": {"Name": "Alicia"}},
        )
        stored = test_app.state.persistence.get_record(BASE_ID, TABLE_ID, REC_1)

    assert response.status_code == 200
    assert stored.fields == {FLD_NAME: "Alicia"}


def test_patch_multi_with_records_body(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={
            "records": [
                {
                    "id": REC_1,
                    "createdTime": "2024-01-01T00:00:00.000Z",
                    "fields": {"Age": 99},
                }
            ]
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.patch(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            json={"records": [{"id": REC_1, "fields": {"Age": 99}}]},
        )
        stored = test_app.state.persistence.get_record(BASE_ID, TABLE_ID, REC_1)

    assert response.status_code == 200
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 99}


def test_patch_non_2xx_does_not_update_cache(httpx_mock, tmp_path):
    httpx_mock.add_response(status_code=422, json={"error": "bad request"})

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.patch(
            f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}",
            json={"fields": {"Age": 31}},
        )
        stored = test_app.state.persistence.get_record(BASE_ID, TABLE_ID, REC_1)

    assert response.status_code == 422
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 30}


def test_patch_unknown_table_falls_through(httpx_mock, tmp_path):
    httpx_mock.add_response(json={"id": REC_1, "createdTime": "x", "fields": {"Name": "Alice"}})

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        response = client.patch(
            f"/v0/{BASE_ID}/UnknownTable/{REC_1}",
            json={"fields": {"Name": "Alice"}},
        )

    assert response.status_code == 200
    assert len(httpx_mock.get_requests()) == 1


def test_patch_non_json_response_does_not_update_cache(httpx_mock, tmp_path):
    # Coverage for the ValueError branch in _apply_to_cache when Airtable
    # returns a 2xx with non-JSON content (e.g. plain text or HTML error pages).
    httpx_mock.add_response(
        status_code=200, content=b"not-json", headers={"Content-Type": "text/plain"}
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.patch(
            f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}",
            json={"fields": {"Age": 31}},
        )
        stored = test_app.state.persistence.get_record(BASE_ID, TABLE_ID, REC_1)

    assert response.status_code == 200
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 30}


def test_patch_with_return_fields_by_field_id(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={
            "id": REC_1,
            "createdTime": "2024-01-01T00:00:00.000Z",
            "fields": {FLD_AGE: 31},
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.patch(
            f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}?returnFieldsByFieldId=true",
            json={"fields": {FLD_AGE: 31}},
        )
        stored = test_app.state.persistence.get_record(BASE_ID, TABLE_ID, REC_1)

    assert response.status_code == 200
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 31}
