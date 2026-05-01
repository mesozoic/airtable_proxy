import asyncio
import logging
from typing import Any

import click
from pyairtable import Api, Base
from pyairtable.models.webhook import Webhook, WebhookPayload

from airtable_proxy.config import BaseConfig, Config, load_config, load_config_from_file
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage

logger = logging.getLogger(__name__)

POLL_INTERVAL = 1.0  # seconds


def callback_url(hostname: str, base_id: str) -> str:
    """Construct webhook callback URL for a given base."""
    return f"https://{hostname}/webhooks/{base_id}"


def find_or_create_webhook(base: Base, callback_url: str) -> Webhook:
    """Find existing webhook by callback URL, or create a new one."""
    for webhook in base.webhooks():
        if webhook.notification_url == callback_url:
            return webhook

    # Create new webhook
    spec = {"options": {"filters": {"dataTypes": ["tableData"]}}}
    response = base.add_webhook(callback_url, spec)
    return base.webhook(response.id)


def refresh_tables(base: Base, base_id: str, persistence: AirtablePersistence) -> None:
    """Fetch all tables and records from a base and store them."""
    schema = base.schema()
    for table_info in schema.tables:
        table_id = table_info.id
        table_name = table_info.name
        persistence.save_table(base_id, table_id, table_name)

        # Save field metadata
        for field in table_info.fields:
            persistence.save_field(
                base_id,
                table_id,
                field.id,
                field_name=field.name,
                field_type=field.type,
            )

        table = base.table(table_id)
        for record in table.all(use_field_ids=True):
            persistence.save_record(
                base_id,
                table_id,
                record["id"],
                fields=record["fields"],
                created_time=record["createdTime"],
            )


def process_payload(payload: WebhookPayload, base_id: str, persistence: AirtablePersistence) -> None:
    """Process a single webhook payload and update local storage."""
    # Handle destroyed tables
    for table_id in payload.destroyed_table_ids:
        logger.debug(f"Deleted table {table_id} from base {base_id}")
        persistence.delete_table(base_id, table_id)

    # Handle created tables
    for table_id, table_created in payload.created_tables_by_id.items():
        table_name = table_created.metadata.name if table_created.metadata else table_id
        record_count = len(table_created.records_by_id)
        logger.debug(f"Created table {table_id} ({table_name}) with {record_count} record(s)")
        persistence.save_table(base_id, table_id, table_name)

        # Save field metadata for the new table
        for field_id, field_info in table_created.fields_by_id.items():
            persistence.save_field(
                base_id=base_id,
                table_id=table_id,
                field_id=field_id,
                field_name=field_info.name or field_id,
                field_type=field_info.type or "unknown",
            )

        for record_id, record_created in table_created.records_by_id.items():
            persistence.save_record(
                base_id=base_id,
                table_id=table_id,
                record_id=record_id,
                fields=record_created.cell_values_by_field_id,
                created_time=record_created.created_time.isoformat(),
            )

    # Handle changes to existing tables
    for table_id, table_changed in payload.changed_tables_by_id.items():
        # Handle table rename
        if table_changed.changed_metadata:
            old_name = table_changed.changed_metadata.previous.name
            new_name = table_changed.changed_metadata.current.name
            if old_name != new_name:
                logger.debug(f"Renamed table {table_id} from {old_name!r} to {new_name!r}")
                persistence.save_table(
                    base_id=base_id,
                    table_id=table_id,
                    table_name=new_name,
                )

        # Handle destroyed fields
        for field_id in table_changed.destroyed_field_ids:
            logger.debug(f"Deleted field {field_id} from table {table_id}")
            persistence.delete_field(base_id, table_id, field_id)

        # Handle created fields
        for field_id, field_info in table_changed.created_fields_by_id.items():
            logger.debug(f"Created field {field_id} in table {table_id}")
            persistence.save_field(
                base_id=base_id,
                table_id=table_id,
                field_id=field_id,
                field_name=field_info.name or field_id,
                field_type=field_info.type or "unknown",
            )

        # Handle changed fields (renames and type changes)
        for field_id, field_changed in table_changed.changed_fields_by_id.items():
            logger.debug(f"Updated field {field_id} in table {table_id}")
            persistence.save_field(
                base_id=base_id,
                table_id=table_id,
                field_id=field_id,
                field_name=field_changed.current.name or field_id,
                field_type=field_changed.current.type or "unknown",
            )

        # Handle created records
        for record_id, record_created in table_changed.created_records_by_id.items():
            logger.debug(f"Created record {record_id} in table {table_id}")
            persistence.save_record(
                base_id=base_id,
                table_id=table_id,
                record_id=record_id,
                fields=record_created.cell_values_by_field_id,
                created_time=record_created.created_time.isoformat(),
            )

        # Handle changed records
        for record_id, record_changed in table_changed.changed_records_by_id.items():
            existing = persistence.get_record(base_id, table_id, record_id)
            if not existing:
                raise RuntimeError(
                    f"Received change for non-existent record {record_id} in table {table_id}"
                )
            logger.debug(f"Updated record {record_id} in table {table_id}")
            new_fields = {
                **existing.fields,
                **record_changed.current.cell_values_by_field_id,
            }
            persistence.save_record(
                base_id=base_id,
                table_id=table_id,
                record_id=record_id,
                fields=new_fields,
                created_time=existing.created_time,
            )

        # Handle destroyed records
        for record_id in table_changed.destroyed_record_ids:
            logger.debug(f"Deleted record {record_id} from table {table_id}")
            persistence.delete_record(
                base_id=base_id,
                table_id=table_id,
                record_id=record_id,
            )


def poll_base(base_id: str, base_config: BaseConfig, persistence: AirtablePersistence) -> None:
    """Poll a single base for webhook payloads and process them."""
    webhook_info = persistence.get_webhook(base_id)
    if not webhook_info:
        logger.warning(f"No webhook info for base {base_id}, skipping")
        return

    api = Api(base_config.api_key)
    base = api.base(base_id)
    webhook = base.webhook(webhook_info.webhook_id)

    # Start from cursor + 1 (cursor is last processed, we want next)
    cursor = webhook_info.cursor + 1 if webhook_info.cursor > 0 else 1

    for payload in webhook.payloads(cursor=cursor):
        process_payload(payload, base_id, persistence)
        # cursor is always set by pyairtable when iterating payloads
        assert payload.cursor is not None
        persistence.save_webhook(base_id, webhook_info.webhook_id, payload.cursor)
        logger.info(f"Processed payload {payload.cursor} for base {base_id}")


def initialize(config: dict[str, Any] | Config) -> None:
    """
    Initialize webhooks and fetch initial data for all configured bases.

    Run this once before polling for updates.
    """
    if isinstance(config, dict):
        config = load_config(config)

    config.storage.sqlite.parent.mkdir(parents=True, exist_ok=True)
    with Storage(config.storage.sqlite) as storage:
        persistence = AirtablePersistence(storage)

        for base_id, base_config in config.bases.items():
            url = callback_url(config.hostname, base_id)
            initialize_base(
                callback_url=url,
                base_id=base_id,
                base_config=base_config,
                persistence=persistence,
            )


def initialize_base(
    callback_url: str,
    base_id: str,
    base_config: BaseConfig,
    persistence: AirtablePersistence,
) -> None:
    api = Api(base_config.api_key)
    api.whoami()  # Raises if connection fails

    base = api.base(base_id)
    webhook_info = persistence.get_webhook(base_id)

    if webhook_info:
        # Existing webhook - poll for any missed payloads
        logger.info(f"Found existing webhook {webhook_info.webhook_id} for base {base_id}")
        poll_base(base_id, base_config, persistence)
    else:
        # Find or create webhook
        webhook = find_or_create_webhook(base, callback_url)
        persistence.save_webhook(base_id, webhook_id=webhook.id, cursor=0)
        refresh_tables(base, base_id, persistence)


async def run_polling_loop(config: Config) -> None:
    """
    Main polling loop that runs continuously.

    Polls all bases in parallel, then waits POLL_INTERVAL seconds.
    """
    config.storage.sqlite.parent.mkdir(parents=True, exist_ok=True)
    with Storage(config.storage.sqlite) as storage:
        persistence = AirtablePersistence(storage)

        logger.info(f"Starting polling loop for {len(config.bases)} base(s)")

        try:
            while True:
                threads = [
                    asyncio.to_thread(poll_base, base_id, base_config, persistence)
                    for base_id, base_config in config.bases.items()
                ]
                results = await asyncio.gather(*threads, return_exceptions=True)

                for base_id, result in zip(config.bases, results):
                    if isinstance(result, Exception):
                        logger.error(f"Error polling base {base_id}: {result}")

                await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Polling loop cancelled")


@click.command()
@click.argument("config", type=click.Path(exists=True))
@click.option("--once", is_flag=True, help="Run once and exit (for testing)")
def main(config: str, once: bool = False) -> None:
    """
    Initialize and poll Airtable webhooks.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config_from_file(config)
    initialize(cfg)

    if not once:
        asyncio.run(run_polling_loop(cfg))


if __name__ == "__main__":
    main()
