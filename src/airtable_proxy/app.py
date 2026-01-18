from contextlib import asynccontextmanager

from fastapi import FastAPI
from pyairtable import Api

from airtable_proxy.config import Config, load_config


def create_app(config: dict | Config) -> FastAPI:
    if isinstance(config, dict):
        config = load_config(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Test connection to each base on startup
        for base_id, base_config in config.bases.items():
            api = Api(base_config.api_key)
            api.whoami()  # Raises if connection fails
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
