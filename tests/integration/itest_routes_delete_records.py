"""Integration test for DELETE — fixtures live in conftest.py."""

import pytest


@pytest.mark.integration
def test_delete_then_cache_record_gone(proxy, seeded_record, record_cleanup):
    """DELETE a record via the proxy and verify it is removed from the local cache."""
    assert proxy.persistence.get_record(proxy.base_id, proxy.table_id, seeded_record) is not None

    del_resp = proxy.client.delete(
        f"/v0/{proxy.base_id}/TEST_TABLE/{seeded_record}",
        headers=proxy.headers,
    )
    assert del_resp.status_code == 200, del_resp.text

    record_cleanup.remove(seeded_record)

    cached = proxy.persistence.get_record(proxy.base_id, proxy.table_id, seeded_record)
    assert cached is None
