"""Integration test for POST /v0/{base_id}/{table_id_or_name} — fixtures live in conftest.py."""

import pytest


@pytest.mark.integration
def test_post_then_cache_reflects_new_record(proxy, record_cleanup):
    """POST a record via the proxy and verify the local cache contains it."""
    resp = proxy.client.post(
        f"/v0/{proxy.base_id}/TEST_TABLE",
        headers=proxy.headers,
        json={"fields": {"text": "ItestAlice", "number": 42}},
    )
    assert resp.status_code == 200, resp.text
    rec_id = resp.json()["id"]
    record_cleanup.append(rec_id)

    cached = proxy.persistence.get_record(proxy.base_id, proxy.table_id, rec_id)
    assert cached is not None
    assert cached.fields.get(proxy.field_ids["text"]) == "ItestAlice"
    assert cached.fields.get(proxy.field_ids["number"]) == 42
