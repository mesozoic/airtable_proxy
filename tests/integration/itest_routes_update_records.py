"""Integration tests for PATCH and PUT — fixtures live in conftest.py."""

import pytest


@pytest.mark.integration
def test_patch_then_cache_reflects_update(proxy, seeded_record):
    """
    PATCH only one field. The cache must preserve the unmodified field, which
    requires that Airtable's PATCH response include it (design assumption).
    """
    patch_resp = proxy.client.patch(
        f"/v0/{proxy.base_id}/TEST_TABLE/{seeded_record}",
        headers=proxy.headers,
        json={"fields": {"number": 99}},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    patch_body = patch_resp.json()
    assert patch_body["fields"].get("text") == "ItestSeed", (
        "Airtable PATCH response should include unmodified field — "
        "design assumption violated; see docs/plans/2026-06-23-cache-writes-design.md"
    )
    assert patch_body["fields"].get("number") == 99

    cached = proxy.persistence.get_record(proxy.base_id, proxy.table_id, seeded_record)
    assert cached is not None
    assert cached.fields.get(proxy.field_ids["text"]) == "ItestSeed", (
        "PATCH must not wipe unmodified fields — design assumption violated"
    )
    assert cached.fields.get(proxy.field_ids["number"]) == 99


@pytest.mark.integration
def test_put_then_cache_clears_unspecified_fields(proxy, seeded_record):
    """PUT only one field; the field omitted from the body must be cleared from the cache."""
    put_resp = proxy.client.put(
        f"/v0/{proxy.base_id}/TEST_TABLE/{seeded_record}",
        headers=proxy.headers,
        json={"fields": {"text": "Updated"}},
    )
    assert put_resp.status_code == 200, put_resp.text

    cached = proxy.persistence.get_record(proxy.base_id, proxy.table_id, seeded_record)
    assert cached is not None
    assert cached.fields.get(proxy.field_ids["text"]) == "Updated"
    assert not cached.fields.get(proxy.field_ids["number"]), (
        "PUT should clear fields not included in the request"
    )
