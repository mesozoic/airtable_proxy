# Integration tests for PATCH/PUT /v0/{base_id}/{table_id_or_name}/{record_id}
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
def test_patch_then_cache_reflects_update(api_key, api, base_id, tmp_path, record_cleanup):
    """
    PATCH a record via the proxy and verify the cache merges only the changed
    fields while preserving the ones not mentioned in the request.

    This test validates the PATCH design assumption: Airtable returns the full
    record state after PATCH, so the cache ends up with all fields populated.
    If this test fails it means the assumption is wrong – stop and report.
    """
    test_app = app_module.create_app(config=_make_config(api_key, tmp_path))

    with TestClient(test_app) as client:
        persistence = test_app.state.persistence
        table_schema = seed_test_table(persistence, api, base_id)
        table_id = table_schema.id

        fields_by_id = persistence.get_fields(base_id, table_id)
        text_field_id = next(fid for fid, info in fields_by_id.items() if info.field_name == "text")
        number_field_id = next(
            fid for fid, info in fields_by_id.items() if info.field_name == "number"
        )

        # Create a record via the proxy so it lands in the cache
        create_resp = client.post(
            f"/v0/{base_id}/TEST_TABLE",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"fields": {"text": "ItestAlice", "number": 1}},
        )
        assert create_resp.status_code == 200, create_resp.text
        rec_id = create_resp.json()["id"]
        record_cleanup.append(rec_id)

        # PATCH – only change number
        patch_resp = client.patch(
            f"/v0/{base_id}/TEST_TABLE/{rec_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"fields": {"number": 99}},
        )
        assert patch_resp.status_code == 200, patch_resp.text

        cached = persistence.get_record(base_id, table_id, rec_id)
        assert cached is not None, "Record should still be in cache after PATCH"
        assert cached.fields.get(text_field_id) == "ItestAlice", (
            "PATCH must not wipe unmodified fields — design assumption violated"
        )
        assert cached.fields.get(number_field_id) == 99


@pytest.mark.integration
def test_put_then_cache_clears_unspecified_fields(api_key, api, base_id, tmp_path, record_cleanup):
    """
    PUT a record with only one field and verify the cache no longer contains
    the field that was not specified (PUT semantics: full replace).
    """
    test_app = app_module.create_app(config=_make_config(api_key, tmp_path))

    with TestClient(test_app) as client:
        persistence = test_app.state.persistence
        table_schema = seed_test_table(persistence, api, base_id)
        table_id = table_schema.id

        fields_by_id = persistence.get_fields(base_id, table_id)
        text_field_id = next(fid for fid, info in fields_by_id.items() if info.field_name == "text")
        number_field_id = next(
            fid for fid, info in fields_by_id.items() if info.field_name == "number"
        )

        # Create a record via the proxy
        create_resp = client.post(
            f"/v0/{base_id}/TEST_TABLE",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"fields": {"text": "ItestAlice", "number": 1}},
        )
        assert create_resp.status_code == 200, create_resp.text
        rec_id = create_resp.json()["id"]
        record_cleanup.append(rec_id)

        # PUT – only send text; number should be cleared
        put_resp = client.put(
            f"/v0/{base_id}/TEST_TABLE/{rec_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"fields": {"text": "Updated"}},
        )
        assert put_resp.status_code == 200, put_resp.text

        cached = persistence.get_record(base_id, table_id, rec_id)
        assert cached is not None, "Record should still be in cache after PUT"
        assert cached.fields.get(text_field_id) == "Updated"
        # Airtable omits empty/cleared fields from the response body, so after
        # a replace-mode write the number key should be absent or None.
        assert not cached.fields.get(number_field_id), (
            "PUT should clear fields not included in the request"
        )
