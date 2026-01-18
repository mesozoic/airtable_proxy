from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from pyairtable import Api

from airtable_proxy.config import Config, load_config
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


def create_app(config: dict | Config, storage_path: Path | str | None = None) -> FastAPI:
    if isinstance(config, dict):
        config = load_config(config)

    if storage_path is None:
        storage_path = Path("data/airtable_proxy")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        storage = Storage(storage_path)
        persistence = AirtablePersistence(storage)

        for base_id, base_config in config.bases.items():
            api = Api(base_config.api_key)
            api.whoami()  # Raises if connection fails

            base = api.base(base_id)
            webhook_info = persistence.get_webhook(base_id)

            if webhook_info:
                # Existing webhook - TODO: start background polling
                pass
            else:
                # Find or create webhook
                callback_url = f"https://{config.hostname}/webhooks/{base_id}"
                webhook = find_or_create_webhook(base, callback_url)
                persistence.save_webhook(base_id, webhook_id=webhook.id, cursor=0)
                # TODO: fetch all records

        yield

        storage.close()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
