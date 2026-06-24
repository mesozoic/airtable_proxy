import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response

from airtable_proxy.config import Config, load_config_from_file
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import ProxyRequest, proxy_to_airtable
from airtable_proxy.routes import create_records, get_record, list_records
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

    list_records.add_routes(app)
    get_record.add_routes(app)
    create_records.add_routes(app)

    @app.exception_handler(ProxyRequest)
    async def handle_proxy_request(request: Request, _exc: ProxyRequest) -> Response:
        """
        When a route handler raises ProxyRequest, forward the request to Airtable.
        """
        path = request.url.path.lstrip("/")
        return await proxy_to_airtable(request, path)

    @app.api_route("/v0/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def proxy_v0(request: Request, path: str) -> Response:
        """
        Catch-all route for /v0/* requests. Proxies to Airtable API.
        """
        return await proxy_to_airtable(request, f"v0/{path}")

    return app
