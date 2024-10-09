import pytest
import requests_mock
from flask.testing import FlaskClient

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


def test_unauthorized(app, base_id):
    response = app.test_client().get(f"/v0/meta/bases/{base_id}/tables")
    assert response.status_code == 403


def test_schema(client, auth_headers, base_id, table_id):
    # This will make a network call (that will be intercepted by VCR)
    r1 = client.get(f"/v0/meta/bases/{base_id}/tables", headers=auth_headers)
    assert r1.status_code == 200
    assert table_id in [table["id"] for table in r1.json["tables"]]

    # After this point we should not allow any more network requests.
    with requests_mock.Mocker():
        r2 = client.get(f"/v0/meta/bases/{base_id}/tables", headers=auth_headers)
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
