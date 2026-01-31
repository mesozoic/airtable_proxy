import pytest

from airtable_proxy import poller
from airtable_proxy.config import BaseConfig


@pytest.mark.integration
def test_poll_base(
    api,
    api_key,
    base_id,
    hostname,
    webhook_cleanup,
    record_cleanup,
    persist,
):
    """
    Integration test: initialize poller, create records, poll, verify sync.
    """
    persist, db_path = persist
    base = api.base(base_id)
    table = base.table("TEST_TABLE")

    config = {
        "hostname": hostname,
        "bases": {base_id: {"api_key": api_key}},
        "storage": {"sqlite": str(db_path)},
    }

    # Initialize the poller - creates webhook and syncs existing data
    poller.initialize(config)

    # Verify webhook was created
    webhook_info = persist.get_webhook(base_id)
    assert webhook_info is not None, "Webhook should be created by initialize()"

    # Create test records in Airtable (using TEST_TABLE field names)
    text_field_id = "fldzbVdWW4xJdZ1em"  # field ID for "text"
    records = table.batch_create(
        [
            {"text": "Alice", "number": 100},
            {"text": "Bob", "number": 200},
        ]
    )
    record_cleanup.extend(r["id"] for r in records)
    alice_id, bob_id = record_cleanup

    # Poll and verify records were synced
    base_config = BaseConfig(api_key=api_key)
    poller.poll_base(base_id, base_config, persist)

    for record_id in record_cleanup:
        synced = persist.get_record(base_id, table.id, record_id)
        assert synced is not None, f"Record {record_id} not synced"

    # Verify cursor was updated
    webhook_info = persist.get_webhook(base_id)
    assert webhook_info is not None
    assert webhook_info.cursor > 0, "Cursor should be updated after polling"

    # Update a record and verify sync (fields are stored by field ID)
    table.update(alice_id, {"text": "Alice Updated"})
    poller.poll_base(base_id, base_config, persist)
    updated = persist.get_record(base_id, table.id, alice_id)
    assert updated is not None
    assert updated.fields.get(text_field_id) == "Alice Updated"

    # Delete a record and verify sync
    table.delete(bob_id)
    record_cleanup.remove(bob_id)
    poller.poll_base(base_id, base_config, persist)
    deleted = persist.get_record(base_id, table.id, bob_id)
    assert deleted is None, "Deleted record should be removed from persistence"
