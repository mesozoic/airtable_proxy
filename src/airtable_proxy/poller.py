import click
from pyairtable import Api

from airtable_proxy.config import Config, load_config, load_config_from_file
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage


def find_or_create_webhook(base, callback_url: str):
    """Find existing webhook by callback URL, or create a new one."""
    for webhook in base.webhooks():
        if webhook.notification_url == callback_url:
            return webhook

    # Create new webhook
    spec = {"options": {"filters": {"dataTypes": ["tableData"]}}}
    response = base.add_webhook(callback_url, spec)
    return base.webhook(response.id)


def refresh_tables(base, base_id: str, persistence: AirtablePersistence) -> None:
    """Fetch all tables and records from a base and store them."""
    schema = base.schema()
    for table_info in schema.tables:
        table_id = table_info.id
        table_name = table_info.name
        persistence.save_table(base_id, table_id, table_name)

        table = base.table(table_id)
        for record in table.all(return_fields_by_field_id=True):
            persistence.save_record(
                base_id,
                table_id,
                record["id"],
                fields=record["fields"],
                created_time=record["createdTime"],
            )


def initialize(config: dict | Config) -> None:
    """
    Initialize webhooks and fetch initial data for all configured bases.

    Run this once before polling for updates.
    """
    if isinstance(config, dict):
        config = load_config(config)

    config.storage.sqlite.parent.mkdir(parents=True, exist_ok=True)
    storage = Storage(config.storage.sqlite)
    persistence = AirtablePersistence(storage)

    for base_id, base_config in config.bases.items():
        api = Api(base_config.api_key)
        api.whoami()  # Raises if connection fails

        base = api.base(base_id)
        webhook_info = persistence.get_webhook(base_id)

        if webhook_info:
            # Existing webhook - will poll for updates
            pass
        else:
            # Find or create webhook
            callback_url = f"https://{config.hostname}/webhooks/{base_id}"
            webhook = find_or_create_webhook(base, callback_url)
            persistence.save_webhook(base_id, webhook_id=webhook.id, cursor=0)
            refresh_tables(base, base_id, persistence)


@click.command()
@click.argument("config", type=click.Path(exists=True))
def main(config: str) -> None:
    """
    Initialize and poll Airtable webhooks.
    """
    cfg = load_config_from_file(config)
    initialize(cfg)


if __name__ == "__main__":
    main()
