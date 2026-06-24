# Integration tests for POST /v0/{base_id}/{table_id_or_name}
#
# Fixtures used (from conftest.py):
#   api_key  – skips if AIRTABLE_API_KEY is unset
#   api      – pyairtable Api client
#   base_id  – pre-existing test base "appaPqizdsNHDvlEm"
#   record_cleanup – list of record IDs to delete after the test
#
# The test builds its own FastAPI app (via create_app) pointed at a
# tmp_path SQLite so that test_app.state.persistence reflects exactly
# what the route handlers wrote.

import pytest
from fastapi.testclient import TestClient

from airtable_proxy import app as app_module
from airtable_proxy.config import Config, StorageConfig


def _make_config(api_key, tmp_path):
    return Config(
        hostname="test.example.com",
        bases={},
        storage=StorageConfig(sqlite=tmp_path / "test.db"),
    )


def seed_test_table(persistence, api, base_id):
    """
    Fetch TEST_TABLE schema from Airtable and populate the local cache with
    table + field metadata so that resolve_table_id succeeds and cache_writes
    can translate field names to IDs.
    """
    schema = api.base(base_id).schema()
    table_schema = schema.table("TEST_TABLE")
    persistence.save_table(base_id, table_schema.id, table_schema.name)
    for field in table_schema.fields:
        persistence.save_field(base_id, table_schema.id, field.id, field.name, field.type)
    return table_schema


@pytest.mark.integration
def test_post_then_cache_reflects_new_record(api_key, api, base_id, tmp_path, record_cleanup):
    """
    POST a record via the proxy and verify the local cache contains it with
    the correct field values (keyed by field ID).
    """
    test_app = app_module.create_app(
        config=_make_config(api_key, tmp_path),
    )

    with TestClient(test_app) as client:
        persistence = test_app.state.persistence
        table_schema = seed_test_table(persistence, api, base_id)
        table_id = table_schema.id

        # Resolve the text field ID so we can assert on it
        fields_by_id = persistence.get_fields(base_id, table_id)
        text_field_id = next(fid for fid, info in fields_by_id.items() if info.field_name == "text")
        number_field_id = next(
            fid for fid, info in fields_by_id.items() if info.field_name == "number"
        )

        resp = client.post(
            f"/v0/{base_id}/TEST_TABLE",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"fields": {"text": "ItestAlice", "number": 42}},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        rec_id = body["id"]
        record_cleanup.append(rec_id)

        cached = persistence.get_record(base_id, table_id, rec_id)
        assert cached is not None, "Record should be in cache after POST"
        assert cached.fields.get(text_field_id) == "ItestAlice"
        assert cached.fields.get(number_field_id) == 42
