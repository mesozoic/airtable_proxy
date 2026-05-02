"""
Tests for bearer token authentication.
"""

from fastapi import Request
from fastapi.testclient import TestClient

from airtable_proxy import auth
from airtable_proxy.proxy import ProxyRequest

BASE_ID = "appTestBase1"
TABLE_ID = "tblTestTable1"
TOKEN = "patFakeToken123.secret"
TOKEN_HASH = auth.hash_token(TOKEN)


def test_allow_when_hash_found(persist, auth_app):
    """
    Requests with a known token hash are allowed.
    """
    persist.save_table(BASE_ID, TABLE_ID, "Test Table")
    persist.save_auth(BASE_ID, TOKEN_HASH)

    with TestClient(auth_app) as client:
        response = client.get(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert response.status_code == 200


def test_allow_and_cache_on_airtable_success(httpx_mock, persist, auth_app):
    """
    Unknown tokens are verified against Airtable.
    On success, the hash is stored and the request is allowed.
    """
    persist.save_table(BASE_ID, TABLE_ID, "Test Table")

    httpx_mock.add_response(json={"records": []}, status_code=200)

    with TestClient(auth_app) as client:
        response = client.get(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    assert persist.has_auth(BASE_ID, TOKEN_HASH)


def test_deny_on_airtable_failure(httpx_mock, persist, auth_app):
    """
    Unknown tokens that fail Airtable verification return 403.
    """
    persist.save_table(BASE_ID, TABLE_ID, "Test Table")

    httpx_mock.add_response(json={"error": {"type": "AUTHENTICATION_REQUIRED"}}, status_code=401)

    with TestClient(auth_app) as client:
        response = client.get(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 403
    assert not persist.has_auth(BASE_ID, TOKEN_HASH)


def test_deny_when_no_auth_header(persist, auth_app):
    """
    Requests without an Authorization header return 401.
    """
    persist.save_table(BASE_ID, TABLE_ID, "Test Table")

    with TestClient(auth_app) as client:
        response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}")

    assert response.status_code == 401


def test_proxy_when_no_tables(persist, auth_app):
    """
    If no tables exist for the base, raise ProxyRequest
    so Airtable handles it directly.
    """
    persist.save_auth(BASE_ID, TOKEN_HASH)

    @auth_app.exception_handler(ProxyRequest)
    async def handle_proxy(request: Request, _exc: ProxyRequest):
        from fastapi.responses import JSONResponse

        return JSONResponse({"proxied": True}, status_code=299)

    with TestClient(auth_app) as client:
        response = client.get(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 299
