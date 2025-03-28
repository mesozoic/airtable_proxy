import functools
from unittest import mock

import pytest
import requests_mock
from flask.testing import FlaskClient
from pyairtable.testing import fake_record

import airtable_proxy.app

pytestmark = [pytest.mark.vcr]


@pytest.fixture
def app():
    return airtable_proxy.app.app


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
def get(client, auth_headers):
    return functools.partial(client.get, headers=auth_headers)


def test_unauthorized(client, base_id):
    response = client.get(f"/v0/meta/bases/{base_id}/tables")
    assert response.status_code == 403


def test_get_records(requests_mock, mock_schema, get, base_id, table_id):
    records = [fake_record() for _ in range(5)]
    requests_mock.get(
        f"https://api.airtable.com/v0/{base_id}/{table_id}?returnFieldsByFieldId=1",
        json={"records": records},
    )
    response = get(f"/v0/{base_id}/{table_id}")
    assert response.status_code == 200
    assert response.json == {"records": records}


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
