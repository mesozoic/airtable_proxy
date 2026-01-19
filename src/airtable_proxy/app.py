import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from airtable_proxy.config import Config, load_config_from_file
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage


def create_app(config: Config | None = None) -> FastAPI:
    if config is None:
        config_path = os.environ.get("AIRTABLE_PROXY_CONFIG", "config.yaml")
        config = load_config_from_file(config_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """
        Manage application startup and shutdown.

        Opens the storage connection before accepting requests, closes it
        during graceful shutdown. Multiple workers can safely share the
        same storage file (sqlite3 handles concurrent access).

        See: https://fastapi.tiangolo.com/advanced/events/#lifespan
        """
        config.storage.sqlite.parent.mkdir(parents=True, exist_ok=True)
        storage = Storage(config.storage.sqlite)
        app.state.persistence = AirtablePersistence(storage)

        try:
            yield
        finally:
            storage.close()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok"}

    return app
