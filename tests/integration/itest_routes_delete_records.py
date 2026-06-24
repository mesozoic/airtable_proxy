# Integration tests for DELETE /v0/{base_id}/{table_id_or_name}/{record_id}
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
def test_delete_then_cache_record_gone(api_key, api, base_id, tmp_path, record_cleanup):
    """
    DELETE a record via the proxy and verify it is removed from the local cache.
    """
    test_app = app_module.create_app(config=_make_config(api_key, tmp_path))

    with TestClient(test_app) as client:
        persistence = test_app.state.persistence
        table_schema = seed_test_table(persistence, api, base_id)
        table_id = table_schema.id

        # Create a record via the proxy so it lands in the cache
        create_resp = client.post(
            f"/v0/{base_id}/TEST_TABLE",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"fields": {"text": "ItestToDelete", "number": 7}},
        )
        assert create_resp.status_code == 200, create_resp.text
        rec_id = create_resp.json()["id"]
        # Track for cleanup in case the DELETE fails partway through
        record_cleanup.append(rec_id)

        # Verify the record is in the cache before deleting
        assert persistence.get_record(base_id, table_id, rec_id) is not None

        # DELETE via the proxy
        del_resp = client.delete(
            f"/v0/{base_id}/TEST_TABLE/{rec_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert del_resp.status_code == 200, del_resp.text

        # Remove from cleanup list – the record no longer exists in Airtable
        record_cleanup.remove(rec_id)

        cached = persistence.get_record(base_id, table_id, rec_id)
        assert cached is None, "Deleted record should be removed from the cache"
