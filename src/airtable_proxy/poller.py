import asyncio
import logging
import sys
from typing import Any

import click
from pyairtable import Api, Base
from pyairtable.models.webhook import Webhook, WebhookPayload

from airtable_proxy.config import (
    BaseConfig,
    Config,
    ConfigNotFoundError,
    load_config,
    load_config_from_file,
    resolve_config_path,
)
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage

logger = logging.getLogger(__name__)

POLL_INTERVAL = 1.0  # seconds


def callback_url(hostname: str, base_id: str) -> str:
    """Construct webhook callback URL for a given base."""
    return f"https://{hostname}/webhooks/{base_id}"


def find_or_create_webhook(base: Base, callback_url: str) -> Webhook:
    """Find existing webhook by callback URL, or create a new one."""
    logger.info(f"Looking for existing webhook with callback URL {callback_url}")
    for webhook in base.webhooks():
        if webhook.notification_url == callback_url:
            logger.info(f"Found existing webhook {webhook.id}")
            return webhook

    # Create new webhook
    spec = {"options": {"filters": {"dataTypes": ["tableData"]}}}
    response = base.add_webhook(callback_url, spec)
    logger.info(f"Created new webhook {response.id}")
    return base.webhook(response.id)


def refresh_tables(base: Base, base_id: str, persistence: AirtablePersistence) -> None:
    """Fetch all tables and records from a base and store them."""
    logger.info(f"Fetching schema for base {base_id}")
    schema = base.schema()
    logger.info(f"Refreshing {len(schema.tables)} table(s) for base {base_id}")
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
        record_count = 0
        for record in table.all(use_field_ids=True):
            persistence.save_record(
                base_id,
                table_id,
                record["id"],
                fields=record["fields"],
                created_time=record["createdTime"],
            )
            record_count += 1
        logger.info(f"Cached {record_count} record(s) from table {table_id} ({table_name})")


def refresh_table(base: Base, base_id: str, table_id: str, persistence: AirtablePersistence) -> None:
    """
    Fetch one table's schema and records from Airtable, replacing the cached
    copy — including deleting cached records Airtable no longer has.

    Skips silently if the table is missing from Airtable's schema; deleting
    the cached table is the destroyed-table payload's job.
    """
    schema = base.schema()
    table_info = next((t for t in schema.tables if t.id == table_id), None)
    if table_info is None:
        logger.warning(f"Table {table_id} missing from schema for base {base_id}; skipping refresh")
        return

    persistence.save_table(base_id, table_id, table_info.name)
    for field in table_info.fields:
        persistence.save_field(
            base_id,
            table_id,
            field.id,
            field_name=field.name,
            field_type=field.type,
        )

    stale_record_ids = set(persistence.get_records(base_id, table_id))
    table = base.table(table_id)
    for record in table.all(use_field_ids=True):
        persistence.save_record(
            base_id,
            table_id,
            record["id"],
            fields=record["fields"],
            created_time=record["createdTime"],
        )
        stale_record_ids.discard(record["id"])
    for record_id in stale_record_ids:
        persistence.delete_record(base_id, table_id, record_id)


def process_payload(
    payload: WebhookPayload, base_id: str, persistence: AirtablePersistence
) -> set[str]:
    """
    Process a single webhook payload and update local storage.

    Returns the IDs of tables that need a full refresh because the payload
    referenced a record the cache doesn't have.
    """
    dirty_table_ids: set[str] = set()

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
                # Change payloads are deltas; without the cached record we
                # can't reconstruct full state, so refresh the whole table.
                logger.warning(
                    f"Received change for uncached record {record_id} in "
                    f"table {table_id}; marking table for refresh"
                )
                dirty_table_ids.add(table_id)
                continue
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

    # Handle destroyed tables
    for table_id in payload.destroyed_table_ids:
        logger.debug(f"Deleted table {table_id} from base {base_id}")
        persistence.delete_table(base_id, table_id)
        dirty_table_ids.discard(table_id)

    return dirty_table_ids


class BasePoller:
    """Polls a single Airtable base for webhook payloads."""

    def __init__(
        self, base_id: str, base_config: BaseConfig, persistence: AirtablePersistence
    ) -> None:
        self.base_id = base_id
        self.base_config = base_config
        self.persistence = persistence
        self._webhook: Webhook | None = None  # Cached webhook handle

    def poll(self) -> None:
        """Poll the base for webhook payloads and process them."""
        webhook_info = self.persistence.get_webhook(self.base_id)
        if not webhook_info:
            logger.warning(f"No webhook info for base {self.base_id}, skipping")
            return

        if self._webhook is None:
            api = Api(self.base_config.api_key)
            base = api.base(self.base_id)
            self._webhook = base.webhook(webhook_info.webhook_id)

        # Start from cursor + 1 (cursor is last processed, we want next)
        cursor = webhook_info.cursor + 1 if webhook_info.cursor > 0 else 1

        dirty_table_ids: set[str] = set()
        for payload in self._webhook.payloads(cursor=cursor):
            dirty_table_ids |= process_payload(payload, self.base_id, self.persistence)
            # cursor is always set by pyairtable when iterating payloads
            assert payload.cursor is not None
            self.persistence.save_webhook(self.base_id, webhook_info.webhook_id, payload.cursor)
            logger.info(f"Processed payload {payload.cursor} for base {self.base_id}")

        # Refresh dirty tables only after draining all payloads, so the API
        # snapshot and the saved cursor describe the same point in time.
        if dirty_table_ids:
            base = Api(self.base_config.api_key).base(self.base_id)
            for table_id in sorted(dirty_table_ids):
                logger.info(f"Refreshing dirty table {table_id} in base {self.base_id}")
                refresh_table(base, self.base_id, table_id, self.persistence)

    def _resolve_webhook(self, base: Base, webhook_id: str) -> Webhook | None:
        """Return the live webhook handle, or None if Airtable no longer has it."""
        try:
            return base.webhook(webhook_id)
        except KeyError:
            return None

    def _create_webhook_and_refresh(self, base: Base, callback_url: str) -> None:
        """Create (or adopt) a webhook, reset the cursor, and refresh the cache."""
        webhook = find_or_create_webhook(base, callback_url)
        self.persistence.save_webhook(self.base_id, webhook_id=webhook.id, cursor=0)
        refresh_tables(base, self.base_id, self.persistence)
        logger.info(f"Initialization complete for base {self.base_id}")

    def initialize(self, callback_url: str) -> None:
        """Initialize the webhook for this base, polling if one already exists."""
        logger.info(f"Initializing base {self.base_id}")
        api = Api(self.base_config.api_key)
        api.whoami()  # Raises if connection fails
        logger.info(f"Connected to Airtable for base {self.base_id}")

        base = api.base(self.base_id)
        webhook_info = self.persistence.get_webhook(self.base_id)

        if not webhook_info:
            self._create_webhook_and_refresh(base, callback_url)
            return

        # Airtable culls webhooks that go unpolled for 7 days, so a stored ID
        # may no longer resolve. Recreate it from scratch when that happens.
        self._webhook = self._resolve_webhook(base, webhook_info.webhook_id)
        if self._webhook is None:
            logger.warning(
                f"Stored webhook {webhook_info.webhook_id} no longer exists "
                f"for base {self.base_id}; recreating"
            )
            self._create_webhook_and_refresh(base, callback_url)
        else:
            logger.info(f"Found existing webhook {webhook_info.webhook_id} for base {self.base_id}")
            self.poll()


def initialize(config: dict[str, Any] | Config) -> None:
    """
    Initialize webhooks and fetch initial data for all configured bases.

    Run this once before polling for updates.
    """
    if isinstance(config, dict):
        config = load_config(config)

    logger.info(f"Opening storage at {config.storage.sqlite}")
    config.storage.sqlite.parent.mkdir(parents=True, exist_ok=True)
    with Storage(config.storage.sqlite) as storage:
        persistence = AirtablePersistence(storage)

        for base_id, base_config in config.bases.items():
            url = callback_url(config.hostname, base_id)
            BasePoller(base_id, base_config, persistence).initialize(url)


async def run_polling_loop(config: Config) -> None:
    """
    Main polling loop that runs continuously.

    Polls all bases in parallel, then waits POLL_INTERVAL seconds.
    """
    config.storage.sqlite.parent.mkdir(parents=True, exist_ok=True)
    with Storage(config.storage.sqlite) as storage:
        persistence = AirtablePersistence(storage)

        logger.info(f"Starting polling loop for {len(config.bases)} base(s)")

        # Create pollers once so the webhook cache survives across iterations
        pollers = [
            BasePoller(base_id, base_config, persistence)
            for base_id, base_config in config.bases.items()
        ]

        try:
            while True:
                threads = [asyncio.to_thread(p.poll) for p in pollers]
                results = await asyncio.gather(*threads, return_exceptions=True)

                for base_id, result in zip(config.bases, results):
                    if isinstance(result, Exception):
                        logger.error(f"Error polling base {base_id}: {result}")

                await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Polling loop cancelled")


@click.command()
@click.argument("config", type=click.Path(), required=False)
@click.option("--once", is_flag=True, help="Run once and exit (for testing)")
def main(config: str | None = None, once: bool = False) -> None:
    """
    Initialize and poll Airtable webhooks.

    If CONFIG is omitted, looks for AIRTABLE_PROXY_CONFIG, then ./config.yaml.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config_path = resolve_config_path(config)
    except ConfigNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    cfg = load_config_from_file(config_path)
    initialize(cfg)

    if not once:
        asyncio.run(run_polling_loop(cfg))


if __name__ == "__main__":
    main()
