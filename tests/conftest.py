import os
import uuid

import pytest
from fastapi import FastAPI, Request
from pyairtable import Api, Base

from airtable_proxy import auth
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage


@pytest.fixture
def storage(tmp_path):
    """
    A Storage instance that is automatically closed after the test.
    """
    with Storage(tmp_path / "test.db") as s:
        yield s


@pytest.fixture
def persist(storage):
    """
    An AirtablePersistence backed by a fresh per-test Storage.
    """
    return AirtablePersistence(storage)


@pytest.fixture
def auth_app(persist):
    """
    A minimal FastAPI app exposing a single route that delegates to
    `auth.require_auth`. Used to test authentication in isolation
    from the real route handlers.
    """
    app = FastAPI()
    app.state.persistence = persist

    @app.get("/v0/{base_id}/{table_id_or_name}")
    async def test_route(request: Request, base_id: str, table_id_or_name: str):
        await auth.require_auth(request, base_id, persist)
        return {"ok": True}

    return app


@pytest.fixture
def api_key():
    """
    Get API key from environment, skip if not set.
    """
    api_key = os.environ.get("AIRTABLE_API_KEY")
    if not api_key:
        pytest.skip("AIRTABLE_API_KEY not set")
    return api_key


@pytest.fixture
def api(api_key) -> Api:
    """
    Airtable API client for integration tests.
    """
    return Api(api_key)


@pytest.fixture
def base(api, base_id) -> Base:
    """
    Pre-existing test base for integration tests.
    """
    return api.base(base_id)


@pytest.fixture
def base_id():
    """
    Pre-existing test base for integration tests.
    """
    return "appaPqizdsNHDvlEm"


@pytest.fixture
def nonce():
    """
    Random nonce to ensure unique webhooks per test run.
    """
    return uuid.uuid4().hex[:8]


@pytest.fixture
def hostname(nonce):
    """
    Unique hostname for webhook callback URL.
    """
    return f"{nonce}.test.example.com"
