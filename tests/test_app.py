import functools
from unittest import mock

import pytest
import requests_mock
from flask.testing import FlaskClient
from pyairtable.testing import fake_record

import airtable_proxy.app

pytestmark = [pytest.mark.vcr]


@pytest.fixture(scope="function")
def app():
    app = airtable_proxy.app.app

    # Clear the cache between each test.
    try:
        ctx = app.config[airtable_proxy.app.AIRTABLE_CONTEXT_KEY]
    except KeyError:
        pass
    else:
        for cache in ctx._caches.values():
            cache.clear()

    return app


@pytest.fixture
def client(app) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def auth_headers(api_key):
    return {"Authorization": f"Bearer {api_key}"}


@pytest.fixture
def mock_schema(requests_mock, base_id):
    requests_mock.get(
        f"https://api.airtable.com/v0/meta/bases/{base_id}/tables",
        json=SCHEMA,
    )


@pytest.fixture
def mock_records(mock_schema, requests_mock, base_id, table_id):
    records = [fake_record(Name=f"Record {n}") for n in range(5)]
    requests_mock.get(
        f"https://api.airtable.com/v0/{base_id}/{table_id}",
        json={"records": records},
    )
    for record in records:
        requests_mock.get(
            f"https://api.airtable.com/v0/{base_id}/{table_id}/{record['id']}",
            json=record,
        )
    return records


@pytest.fixture
def mock_record(mock_records):
    return mock_records[0]


@pytest.fixture
def get(client, auth_headers):
    return functools.partial(client.get, headers=auth_headers)


def test_unauthorized(client, base_id):
    response = client.get(f"/v0/meta/bases/{base_id}/tables")
    assert response.status_code == 403


def test_get_records(mock_records, get, base_id, table_id):
    response = get(f"/v0/{base_id}/{table_id}")
    assert response.status_code == 200
    assert response.json == {"records": mock_records}


def test_get_records__field_ids(mock_records, get, base_id, table_id):
    response = get(f"/v0/{base_id}/{table_id}?returnFieldsByFieldId=1")
    assert response.status_code == 200
    assert response.json == {"records": [with_field_ids(r) for r in mock_records]}


@mock.patch("airtable_proxy.record_cache.RecordCache.get_records")
@pytest.mark.parametrize(
    "param",
    (
        "cellFormat",
        "filterByFormula",
        "maxRecords",
        "offset",
        "recordMetadata",
        "sort",
        "view",
    ),
)
def test_get_records__unsupported_params(
    mock_get_records, requests_mock, get, base_id, table_id, param
):
    records = [fake_record() for _ in range(5)]
    requests_mock.get(
        f"https://api.airtable.com/v0/{base_id}/{table_id}?{param}=1",
        json={"records": records},
    )
    response = get(f"/v0/{base_id}/{table_id}?{param}=1")
    assert response.status_code == 200
    assert response.json == {"records": records}
    assert mock_get_records.call_count == 0


def test_get_record(mock_record, get, base_id, table_id):
    response = get(f"/v0/{base_id}/{table_id}/{mock_record['id']}")
    assert response.status_code == 200
    assert response.json == mock_record


def test_get_record__field_ids(mock_record, get, base_id, table_id):
    response = get(
        f"/v0/{base_id}/{table_id}/{mock_record['id']}?returnFieldsByFieldId=1"
    )
    assert response.status_code == 200
    assert response.json == with_field_ids(mock_record)


@mock.patch("airtable_proxy.record_cache.RecordCache.get_record")
@pytest.mark.parametrize(
    "param",
    (
        "cellFormat",
        "filterByFormula",
        "maxRecords",
        "offset",
        "recordMetadata",
        "sort",
        "view",
    ),
)
def test_get_record__unsupported_params(
    mock_get_record, requests_mock, get, base_id, table_id, param
):
    record = fake_record(Name="Test")
    requests_mock.get(
        f"https://api.airtable.com/v0/{base_id}/{table_id}/{record['id']}?{param}=1",
        json=record,
    )
    response = get(f"/v0/{base_id}/{table_id}/{record['id']}?{param}=1")
    assert response.status_code == 200
    assert response.json == record
    assert mock_get_record.call_count == 0


def test_schema(get, base_id, table_id):
    # This will make a network call (that will be intercepted by VCR)
    r1 = get(f"/v0/meta/bases/{base_id}/tables")
    assert r1.status_code == 200
    assert table_id in [table["id"] for table in r1.json["tables"]]

    # After this point we should not allow any more network requests.
    with requests_mock.Mocker():
        r2 = get(f"/v0/meta/bases/{base_id}/tables")
        assert r2.status_code == 200
        assert r2.json == r1.json


SCHEMA = {
    "tables": [
        {
            "fields": [
                {
                    "id": "fldRLjMJMBjUbn6XF",
                    "name": "Name",
                    "type": "singleLineText",
                },
                {
                    "id": "fldKkisWnZGrxzMsx",
                    "name": "Notes",
                    "type": "multilineText",
                },
                {
                    "id": "fldYTRx2Dmsim5LfH",
                    "name": "Status",
                    "options": {
                        "choices": [
                            {
                                "color": "redLight2",
                                "id": "sel0HzeQgEq1qPOET",
                                "name": "Todo",
                            },
                            {
                                "color": "yellowLight2",
                                "id": "sela9yIL63Z5Dax06",
                                "name": "In progress",
                            },
                            {
                                "color": "greenLight2",
                                "id": "selvsCqBEN4FFix0g",
                                "name": "Done",
                            },
                        ]
                    },
                    "type": "singleSelect",
                },
                {
                    "id": "fldC2AiO53FnN3fLM",
                    "name": "Long Text",
                    "type": "multilineText",
                },
                {
                    "id": "fldgdNLBN5MxzpD6Y",
                    "name": "Rich Text",
                    "type": "richText",
                },
                {
                    "id": "fldCAZwjZuUI4rT31",
                    "name": "Assignee",
                    "type": "singleCollaborator",
                },
            ],
            "id": "tblH5kStARFR6wTwX",
            "name": "Table 1",
            "primaryFieldId": "fldRLjMJMBjUbn6XF",
            "views": [{"id": "viwRuTtmaXSV2Xesj", "name": "Grid view", "type": "grid"}],
        }
    ]
}


def with_field_ids(record):
    field_id_by_name = {
        field["name"]: field["id"] for field in SCHEMA["tables"][0]["fields"]
    }
    field_values = {
        field_id_by_name[key]: val for (key, val) in record["fields"].items()
    }
    return dict(record, fields=field_values)
