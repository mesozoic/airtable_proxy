import json
import os

import pyairtable
import pytest

from airtable_proxy.record_cache import RecordCache


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


@pytest.mark.vcr()
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
    assert json.loads(cache.get("tblH5kStARFR6wTwX/records:json")) == {
        "rec2gjdwMTRE5EewZ": {
            "createdTime": "2023-08-07T17:19:36.000Z",
            "fields": {"Name": "Alpha"},
            "id": "rec2gjdwMTRE5EewZ",
        },
        "recFpahsiS8mKSrud": {
            "createdTime": "2023-08-07T17:19:36.000Z",
            "fields": {"Name": "Bravo"},
            "id": "recFpahsiS8mKSrud",
        },
        "recSVUi0bwKQ5R0pw": {
            "createdTime": "2023-08-07T17:19:36.000Z",
            "fields": {"Name": "Charlie"},
            "id": "recSVUi0bwKQ5R0pw",
        },
    }
