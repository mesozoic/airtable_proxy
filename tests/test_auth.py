"""
Tests for bearer token authentication.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from airtable_proxy import auth
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import ProxyRequest

BASE_ID = "appTestBase1"
TABLE_ID = "tblTestTable1"
TOKEN = "patFakeToken123.secret"
TOKEN_HASH = auth.hash_token(TOKEN)


@pytest.fixture
def persist(storage):
    return AirtablePersistence(storage)


def make_app(persist):
    """
    Create a minimal FastAPI app with a single route that requires auth.
    """
    app = FastAPI()
    app.state.persistence = persist

    @app.get("/v0/{base_id}/{table_id_or_name}")
    async def test_route(request: Request, base_id: str, table_id_or_name: str):
        await auth.require_auth(request, base_id, persist)
        return {"ok": True}

    return app


def test_allow_when_hash_found(persist):
    """
    Requests with a known token hash are allowed.
    """
    persist.save_table(BASE_ID, TABLE_ID, "Test Table")
    persist.save_auth(BASE_ID, TOKEN_HASH)

    app = make_app(persist)
    with TestClient(app) as client:
        response = client.get(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert response.status_code == 200


@patch("airtable_proxy.auth.httpx.AsyncClient")
def test_allow_and_cache_on_airtable_success(mock_client, persist):
    """
    Unknown tokens are verified against Airtable.
    On success, the hash is stored and the request is allowed.
    """
    persist.save_table(BASE_ID, TABLE_ID, "Test Table")

    mock_response = httpx.Response(200, json={"records": []})
    mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.return_value.get = AsyncMock(return_value=mock_response)

    app = make_app(persist)
    with TestClient(app) as client:
        response = client.get(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    assert persist.has_auth(BASE_ID, TOKEN_HASH)


@patch("airtable_proxy.auth.httpx.AsyncClient")
def test_deny_on_airtable_failure(mock_client, persist):
    """
    Unknown tokens that fail Airtable verification return 403.
    """
    persist.save_table(BASE_ID, TABLE_ID, "Test Table")

    mock_response = httpx.Response(401, json={"error": {"type": "AUTHENTICATION_REQUIRED"}})
    mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.return_value.get = AsyncMock(return_value=mock_response)

    app = make_app(persist)
    with TestClient(app) as client:
        response = client.get(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 403
    assert not persist.has_auth(BASE_ID, TOKEN_HASH)


def test_deny_when_no_auth_header(persist):
    """
    Requests without an Authorization header return 401.
    """
    persist.save_table(BASE_ID, TABLE_ID, "Test Table")

    app = make_app(persist)
    with TestClient(app) as client:
        response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}")

    assert response.status_code == 401


def test_proxy_when_no_tables(persist):
    """
    If no tables exist for the base, raise ProxyRequest
    so Airtable handles it directly.
    """
    persist.save_auth(BASE_ID, TOKEN_HASH)

    app = make_app(persist)

    @app.exception_handler(ProxyRequest)
    async def handle_proxy(request: Request, _exc: ProxyRequest):
        from fastapi.responses import JSONResponse

        return JSONResponse({"proxied": True}, status_code=299)

    with TestClient(app) as client:
        response = client.get(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 299
