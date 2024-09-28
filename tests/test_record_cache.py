import json
import os

import pyairtable
import pytest

from airtable_proxy.record_cache import RecordCache

pytestmark = [pytest.mark.vcr()]


@pytest.fixture
def api():
    return pyairtable.Api(os.environ.get("AIRTABLE_API_KEY", "dummy"))


@pytest.fixture
def base_id():
    return "appG3A7GCIJjrjf8j"


@pytest.fixture
def base(api, base_id):
    return api.base(base_id)


@pytest.fixture
def cache(tmp_path, api):
    return RecordCache(tmp_path, api)


def test_reload(cache, base):
    cache.reload(base)

    assert cache.get("appG3A7GCIJjrjf8j/tables") == ["tblH5kStARFR6wTwX"]
    assert cache.get("appG3A7GCIJjrjf8j/schema")["tables"][0]["name"] == "Table 1"
    assert cache.get("tblH5kStARFR6wTwX/records") == {
        "rec2gjdwMTRE5EewZ": {
            "createdTime": "2023-08-07T17:19:36.000Z",
            "fields": {"fldRLjMJMBjUbn6XF": "Alpha"},
            "id": "rec2gjdwMTRE5EewZ",
        },
        "recFpahsiS8mKSrud": {
            "createdTime": "2023-08-07T17:19:36.000Z",
            "fields": {"fldRLjMJMBjUbn6XF": "Bravo"},
            "id": "recFpahsiS8mKSrud",
        },
        "recSVUi0bwKQ5R0pw": {
            "createdTime": "2023-08-07T17:19:36.000Z",
            "fields": {"fldRLjMJMBjUbn6XF": "Charlie"},
            "id": "recSVUi0bwKQ5R0pw",
        },
    }
    # Test that we store records' JSON keyed by field name, not field ID
    assert json.loads(cache.get("tblH5kStARFR6wTwX/records/json")) == {
        "records": [
            {
                "createdTime": "2023-08-07T17:19:36.000Z",
                "fields": {"Name": "Alpha"},
                "id": "rec2gjdwMTRE5EewZ",
            },
            {
                "createdTime": "2023-08-07T17:19:36.000Z",
                "fields": {"Name": "Bravo"},
                "id": "recFpahsiS8mKSrud",
            },
            {
                "createdTime": "2023-08-07T17:19:36.000Z",
                "fields": {"Name": "Charlie"},
                "id": "recSVUi0bwKQ5R0pw",
            },
        ]
    }


def test_reload_records(cache: RecordCache, base):
    table_id = "tblH5kStARFR6wTwX"
    cache.set(
        f"{table_id}/fields",
        {"fldRLjMJMBjUbn6XF": {"name": "Name"}},
    )
    cache.set_records(
        table_id,
        {
            record_id: {
                "createdTime": "2023-08-07T17:19:36.000Z",
                "fields": {},
                "id": record_id,
            }
            for record_id in ("rec2gjdwMTRE5EewZ", "recFpahsiS8mKSrud")
        },
    )

    cache.reload_records(base.table(table_id), ["rec2gjdwMTRE5EewZ"])

    assert cache.get(f"{table_id}/records") == {
        "rec2gjdwMTRE5EewZ": {
            "createdTime": "2023-08-07T17:19:36.000Z",
            "fields": {"fldRLjMJMBjUbn6XF": "Alpha"},
            "id": "rec2gjdwMTRE5EewZ",
        },
        "recFpahsiS8mKSrud": {
            "createdTime": "2023-08-07T17:19:36.000Z",
            "fields": {},
            "id": "recFpahsiS8mKSrud",
        },
    }
