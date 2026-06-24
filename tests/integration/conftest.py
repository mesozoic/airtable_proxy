from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from airtable_proxy import app as app_module
from airtable_proxy import poller
from airtable_proxy.config import Config, StorageConfig
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage


@pytest.fixture
def persist(tmp_path):
    """
    Persistence layer backed by a temporary database, for integration tests.
    """
    db_path = tmp_path / "test.db"
    with Storage(db_path) as store:
        yield AirtablePersistence(store), db_path


@pytest.fixture
def webhook_cleanup(hostname, base):
    """
    Clean up any webhook matching our hostname after the test.
    """
    url = poller.callback_url(hostname, base.id)
    try:
        yield
    finally:
        for webhook in base.webhooks():
            if webhook.notification_url == url:
                webhook.delete()


@pytest.fixture
def record_cleanup(base):
    """
    Track and clean up test records after the test.
    """
    table = base.table("TEST_TABLE")
    record_ids = []
    try:
        yield record_ids
    finally:
        for record_id in record_ids:
            table.delete(record_id)


def _seed_test_table(persistence, api, base_id):
    """
    Fetch TEST_TABLE schema from Airtable and populate the local cache with
    table + field metadata so resolve_table_id succeeds and cache_writes can
    translate field names to IDs.
    """
    schema = api.base(base_id).schema()
    table_schema = schema.table("TEST_TABLE")
    persistence.save_table(base_id, table_schema.id, table_schema.name)
    for field in table_schema.fields:
        persistence.save_field(base_id, table_schema.id, field.id, field.name, field.type)
    return table_schema


@pytest.fixture
def proxy(api, api_key, base_id, tmp_path):
    """
    Stand up a proxy FastAPI app with a per-test SQLite cache, open a
    TestClient, seed TEST_TABLE metadata into the cache, and yield a namespace
    with everything an integration test needs to drive the mutation routes
    against the real Airtable API.

    Attributes on the yielded namespace:
        client       - fastapi.testclient.TestClient
        persistence  - the app's AirtablePersistence (reads SQLite state)
        base_id      - the test base id (from the base_id fixture)
        table_id     - the TEST_TABLE id resolved from Airtable schema
        headers      - {"Authorization": "Bearer <api_key>"}
        field_ids    - dict mapping field name to field id for TEST_TABLE
    """
    config = Config(
        hostname="test.example.com",
        bases={},
        storage=StorageConfig(sqlite=tmp_path / "test.db"),
    )
    test_app = app_module.create_app(config=config)
    with TestClient(test_app) as client:
        persistence = test_app.state.persistence
        table_schema = _seed_test_table(persistence, api, base_id)
        field_ids = {
            info.field_name: fid
            for fid, info in persistence.get_fields(base_id, table_schema.id).items()
        }
        yield SimpleNamespace(
            client=client,
            persistence=persistence,
            base_id=base_id,
            table_id=table_schema.id,
            headers={"Authorization": f"Bearer {api_key}"},
            field_ids=field_ids,
        )


@pytest.fixture
def seeded_record(proxy, record_cleanup):
    """
    POST a TEST_TABLE record via the proxy with text=ItestSeed and number=1.
    Track for cleanup. Return the record id. Use this in update/delete tests
    that need an existing record to act on.
    """
    resp = proxy.client.post(
        f"/v0/{proxy.base_id}/TEST_TABLE",
        headers=proxy.headers,
        json={"fields": {"text": "ItestSeed", "number": 1}},
    )
    assert resp.status_code == 200, resp.text
    rec_id = resp.json()["id"]
    record_cleanup.append(rec_id)
    return rec_id
