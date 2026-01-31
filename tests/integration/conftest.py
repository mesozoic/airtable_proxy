import pytest

from airtable_proxy import poller
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
