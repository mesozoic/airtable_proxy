# Authentication Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add bearer token authentication to routes served from local storage.

**Architecture:** Routes that serve from the local cache (e.g. `list_records`) call an `require_auth()` function before doing any work. This function checks a SHA-256 hash of the bearer token against local storage. On cache miss, it verifies the token against Airtable by hitting list-records with `maxRecords=1`, then caches the result. No middleware needed — auth is called explicitly by each cached route.

**Tech Stack:** FastAPI, httpx, hashlib (SHA-256), existing Storage/AirtablePersistence layers.

---

### Task 1: Add auth persistence methods

**Files:**
- Modify: `src/airtable_proxy/persistence.py:55-163`
- Test: `tests/test_persistence.py`

**Step 1: Write the failing tests**

Add to the end of `tests/test_persistence.py`:

```python
# Auth tests


def test_has_auth_returns_false_when_missing(persist):
    assert persist.has_auth("appBase1", "somehash") is False


def test_save_and_has_auth(persist):
    persist.save_auth("appBase1", "somehash")
    assert persist.has_auth("appBase1", "somehash") is True


def test_auth_is_scoped_to_base(persist):
    persist.save_auth("appBase1", "somehash")
    assert persist.has_auth("appBase2", "somehash") is False
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_persistence.py::test_has_auth_returns_false_when_missing tests/test_persistence.py::test_save_and_has_auth tests/test_persistence.py::test_auth_is_scoped_to_base -v`
Expected: FAIL (AttributeError: 'AirtablePersistence' object has no attribute 'has_auth')

**Step 3: Write minimal implementation**

Add to the end of `AirtablePersistence` in `src/airtable_proxy/persistence.py`:

```python
    # Auth methods

    def has_auth(self, base_id: str, token_hash: str) -> bool:
        return self._storage.get(f"auth:{base_id}:{token_hash}") is not None

    def save_auth(self, base_id: str, token_hash: str) -> None:
        self._storage.set(f"auth:{base_id}:{token_hash}", True)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_persistence.py -v`
Expected: All PASS

**Step 5: Commit**

```
git add src/airtable_proxy/persistence.py tests/test_persistence.py
git commit -m "Add auth hash persistence methods"
```

---

### Task 2: Create auth module

**Files:**
- Create: `src/airtable_proxy/auth.py`
- Create: `tests/test_auth.py`

**Step 1: Write the failing tests**

Create `tests/test_auth.py`:

```python
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
from airtable_proxy.storage import Storage

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
    mock_client.return_value.__aenter__ = AsyncMock(
        return_value=mock_client.return_value
    )
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
    mock_client.return_value.__aenter__ = AsyncMock(
        return_value=mock_client.return_value
    )
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
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL (ImportError — auth module doesn't exist yet)

**Step 3: Write minimal implementation**

Create `src/airtable_proxy/auth.py`:

```python
"""
Bearer token authentication for cached routes.
"""

import hashlib

import httpx
from fastapi import HTTPException, Request

from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import AIRTABLE_API_BASE, ProxyRequest


def hash_token(token: str) -> str:
    """
    Return the SHA-256 hex digest of a bearer token.
    """
    return hashlib.sha256(token.encode()).hexdigest()


async def require_auth(
    request: Request,
    base_id: str,
    persistence: AirtablePersistence,
) -> None:
    """
    Validate the caller's bearer token for a given base.

    Checks the token hash against local storage. On a cache miss,
    verifies the token by hitting Airtable's list-records endpoint
    with maxRecords=1.

    Raises:
        HTTPException(401) if no Authorization header is present.
        HTTPException(403) if the token is invalid for this base.
        ProxyRequest if no tables exist for this base (can't verify).
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401)

    token = auth_header.removeprefix("Bearer ")
    token_hash = hash_token(token)

    if persistence.has_auth(base_id, token_hash):
        return

    # Pick any table to use for verification
    tables = persistence.get_tables(base_id)
    if not tables:
        raise ProxyRequest()

    table_id = next(iter(tables))
    url = f"{AIRTABLE_API_BASE}/v0/{base_id}/{table_id}"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            params={"maxRecords": "1"},
            headers={"Authorization": auth_header},
        )

    if response.is_success:
        persistence.save_auth(base_id, token_hash)
        return

    raise HTTPException(status_code=403)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_auth.py -v`
Expected: All PASS

**Step 5: Commit**

```
git add src/airtable_proxy/auth.py tests/test_auth.py
git commit -m "Add bearer token authentication module"
```

---

### Task 3: Wire auth into list_records

**Files:**
- Modify: `src/airtable_proxy/routes/list_records.py:53-131`
- Modify: `tests/test_routes_list_records.py`

**Step 1: Update existing tests to pass auth**

In `tests/test_routes_list_records.py`, import the auth module:

```python
from airtable_proxy import auth
```

Add a module-level constant:

```python
TOKEN = "patFakeTestToken.secret"
TOKEN_HASH = auth.hash_token(TOKEN)
AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}
```

Update `populate_test_data` to also store the auth hash:

```python
def populate_test_data(persistence):
    """
    Populate persistence layer with test data.
    """
    persistence.save_table(BASE_ID, TABLE_ID, "Test Table")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_NAME, "Name", "singleLineText")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_AGE, "Age", "number")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_ACTIVE, "Active", "checkbox")
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_1,
        {FLD_NAME: "Alice", FLD_AGE: 30, FLD_ACTIVE: True},
        "2024-01-01T00:00:00.000Z",
    )
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_2,
        {FLD_NAME: "Bob", FLD_AGE: 25},
        "2024-01-02T00:00:00.000Z",
    )
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        REC_3,
        {FLD_NAME: "Charlie", FLD_AGE: 35, FLD_ACTIVE: True},
        "2024-01-03T00:00:00.000Z",
    )
    persistence.save_auth(BASE_ID, TOKEN_HASH)
```

Update every `client.get(...)` call in existing tests to include `headers=AUTH_HEADERS`.

Add new tests for auth behavior:

```python
# Authentication tests


def test_returns_401_without_auth_header(client_with_data):
    """
    Requests without Authorization header return 401.
    """
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}")
    assert response.status_code == 401


def test_returns_403_with_invalid_token(client_with_data):
    """
    Requests with an unknown token that fails Airtable verification return 403.
    """
    client, _ = client_with_data
    with patch("airtable_proxy.auth.httpx.AsyncClient") as mock_client:
        mock_response = httpx.Response(401, json={"error": {}})
        mock_client.return_value.__aenter__ = AsyncMock(
            return_value=mock_client.return_value
        )
        mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_client.return_value.get = AsyncMock(return_value=mock_response)

        response = client.get(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            headers={"Authorization": "Bearer patBadToken.invalid"},
        )

    assert response.status_code == 403
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routes_list_records.py -v`
Expected: FAIL — list_records doesn't call require_auth yet, so the no-header test fails (gets 200 instead of 401).

**Step 3: Wire auth into the route handler**

In `src/airtable_proxy/routes/list_records.py`, add the import:

```python
from airtable_proxy.auth import require_auth
```

Change `list_records` from `def` to `async def` and add the auth call as the first line after the proxy-condition checks:

```python
    @app.get("/v0/{base_id}/{table_id_or_name}")
    async def list_records(
        request: Request,
        base_id: str,
        table_id_or_name: str,
        maxRecords: int | None = None,
        fields: list[str] | None = Query(None),
        returnFieldsByFieldId: bool = False,
        view: str | None = None,
        filterByFormula: str | None = None,
        cellFormat: str | None = None,
    ) -> dict[str, Any]:
        """
        List records from a table. Returns records from local storage,
        or proxies to Airtable when necessary.
        """
        if view:
            raise ProxyRequest()
        if filterByFormula:
            raise ProxyRequest()
        if cellFormat == "string":
            raise ProxyRequest()

        persistence: AirtablePersistence = request.app.state.persistence

        await require_auth(request, base_id, persistence)

        table_id = resolve_table_id(base_id, table_id_or_name, persistence)
        if table_id is None:
            raise ProxyRequest()

        # ... rest unchanged
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_routes_list_records.py -v`
Expected: All PASS

**Step 5: Run full test suite and type checks**

Run: `mypy --strict && pytest`
Expected: All PASS

**Step 6: Commit**

```
git add src/airtable_proxy/routes/list_records.py tests/test_routes_list_records.py
git commit -m "Wire authentication into list_records route"
```

---

### Task 4: Update TODO.md

**Files:**
- Modify: `TODO.md:21-27`

Mark the authentication items as complete:

```markdown
- [x] Authentication
    - [x] Use the api_key in the configuration to retrieve records
    - [x] Hash the bearer token and check against local storage
        - [x] If hash present and allowed, allow access
        - [x] If hash not present, check base access by retrieving one record directly from Airtable using the bearer token
            - [x] If successful, store hash and allow access
            - [x] If not successful, return 403
```

**Step 1: Commit**

```
git add TODO.md
git commit -m "Mark authentication as complete in TODO"
```
