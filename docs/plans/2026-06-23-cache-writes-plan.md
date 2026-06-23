# Cache Writes After Mutations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the local SQLite cache immediately after a successful POST/PATCH/PUT/DELETE against Airtable, so that reads against the proxy reflect the write without waiting for the webhook poller.

**Architecture:** Three new FastAPI route modules (`create_records`, `update_records`, `delete_records`) sit ahead of the existing catch-all proxy. They resolve the table, forward the request to Airtable via a small refactor of `proxy.py`, and on a 2xx response hand the body to pure-function helpers in a new `cache_writes.py` module that owns Airtable-response-shape knowledge.

**Tech Stack:** Python 3.13, FastAPI, httpx, pyairtable, sqlite3 (via the existing `Storage` / `AirtablePersistence` wrappers), pytest, pytest-httpx, mypy --strict.

---

## Conventions used in this plan

- **Asking before writing tests** — every TDD task starts with a step that asks the user for approval to write the planned test code, per `AGENTS.md` ("Always ask for confirmation when writing or changing tests."). Do not skip this step.
- **Test files** have no type annotations. Use `@patch` decorators rather than `with patch(...)` blocks. Import the module under test (e.g. `from airtable_proxy import cache_writes`), not individual symbols.
- **`pytest-httpx`** is already in use for mocking outbound HTTP. Use `httpx_mock` fixtures the same way the existing route tests do.
- **Commits** — one commit per task, message style matches recent history (short imperative, no co-author lines).
- **After every code change** verify with `mypy --strict && pytest`. Run `pre-commit run` before each commit. Project-style integration tests run via `dotenv -f tmp/integration.sh run -- pytest -k integration` and are gated to Task 8.

---

## File map

```
src/airtable_proxy/
    proxy.py                       # REFACTOR: split into forward() + response_from_httpx()
    cache_writes.py                # NEW: pure functions apply_create / apply_update / apply_delete
    routes/
        create_records.py          # NEW: POST /v0/{base}/{table}
        update_records.py          # NEW: PATCH|PUT /v0/{base}/{table}[/{record}]
        delete_records.py          # NEW: DELETE /v0/{base}/{table}[/{record}]
    app.py                         # MODIFY: register the three new add_routes(app)

tests/
    test_cache_writes.py                       # NEW (Tasks 2-4)
    test_routes_create_records.py              # NEW (Task 5)
    test_routes_update_records.py              # NEW (Task 6)
    test_routes_delete_records.py              # NEW (Task 7)
    integration/
        itest_routes_create_records.py         # NEW (Task 8)
        itest_routes_update_records.py         # NEW (Task 8)
        itest_routes_delete_records.py         # NEW (Task 8)

TODO.md                                        # MODIFY (Task 9)
```

---

### Task 1: Refactor `proxy.py` to expose `forward()` and `response_from_httpx()`

This is a pure refactor — no behavior change. The existing tests (`tests/test_app.py`, `tests/test_routes_list_records.py`, `tests/test_routes_get_record.py`) cover `proxy_to_airtable` end-to-end and are the regression net.

**Files:**
- Modify: `src/airtable_proxy/proxy.py`

- [ ] **Step 1: Replace `proxy.py` with the refactored version**

Current `proxy.py` exposes one async function `proxy_to_airtable`. After this step it exposes three: `forward`, `response_from_httpx`, and `proxy_to_airtable` (composition of the other two).

```python
"""
Proxy functionality for forwarding requests to the Airtable API.
"""

import httpx
from fastapi import Request, Response

AIRTABLE_API_BASE = "https://api.airtable.com"


class ProxyRequest(Exception):
    """
    Raise this exception from a route handler to indicate that the request
    should be proxied to Airtable instead of being handled locally.

    This allows handlers to inspect a request and decide to proxy it
    based on query parameters, missing data, etc.
    """

    pass


async def forward(request: Request, path: str) -> httpx.Response:
    """
    Forward an incoming request to the Airtable API and return the raw
    httpx response.

    Callers that need to read the response body before returning it (for
    example, to update the local cache) should use this helper and then
    pass the result to `response_from_httpx`.
    """
    url = f"{AIRTABLE_API_BASE}/{path}"

    headers: dict[str, str] = {}
    if auth := request.headers.get("Authorization"):
        headers["Authorization"] = auth
    if content_type := request.headers.get("Content-Type"):
        headers["Content-Type"] = content_type

    body = await request.body()

    async with httpx.AsyncClient() as client:
        return await client.request(
            method=request.method,
            url=url,
            params=request.query_params,
            headers=headers,
            content=body if body else None,
        )


def response_from_httpx(response: httpx.Response) -> Response:
    """
    Convert an httpx response into a FastAPI/Starlette Response that
    preserves status code, headers, and content type.
    """
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.headers.get("Content-Type"),
    )


async def proxy_to_airtable(request: Request, path: str) -> Response:
    """
    Forward a request to the Airtable API and return the response.

    Preserved for the existing catch-all proxy callers.
    """
    return response_from_httpx(await forward(request, path))
```

- [ ] **Step 2: Verify the existing test suite still passes**

Run: `mypy --strict && pytest`
Expected: green. Any test failure here means the refactor is wrong — fix before moving on.

- [ ] **Step 3: Run `pre-commit run` and commit**

```bash
pre-commit run
git add src/airtable_proxy/proxy.py
git commit -m "Refactor proxy.py to expose forward and response_from_httpx"
```

---

### Task 2: `cache_writes.apply_create`

Defensive — log and skip on missing/extra keys, never raise shape errors. Storage errors from `persistence` are allowed to propagate (they represent bugs).

**Files:**
- Create: `src/airtable_proxy/cache_writes.py`
- Create: `tests/test_cache_writes.py`

- [ ] **Step 1: Ask the user for approval to write `tests/test_cache_writes.py`**

Project rule (`AGENTS.md`): always ask for confirmation before writing or changing tests. Show this file's planned contents (below) and wait for explicit go.

```python
"""Tests for the cache_writes module."""

from pyairtable.testing import fake_id

from airtable_proxy import cache_writes
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage

BASE_ID = fake_id("app")
TABLE_ID = fake_id("tbl")
FLD_NAME = fake_id("fld")
FLD_AGE = fake_id("fld")
REC_1 = fake_id("rec")
REC_2 = fake_id("rec")


def make_persistence(tmp_path):
    storage = Storage(tmp_path / "test.db")
    persistence = AirtablePersistence(storage)
    persistence.save_table(BASE_ID, TABLE_ID, "Test Table")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_NAME, "Name", "singleLineText")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_AGE, "Age", "number")
    return persistence


def test_apply_create_single_record_with_field_names(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {
        "id": REC_1,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "fields": {"Name": "Alice", "Age": 30},
    }

    cache_writes.apply_create(
        persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False
    )

    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored is not None
    assert stored.created_time == "2024-01-01T00:00:00.000Z"
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 30}


def test_apply_create_multi_record_response(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {
        "records": [
            {
                "id": REC_1,
                "createdTime": "2024-01-01T00:00:00.000Z",
                "fields": {"Name": "Alice"},
            },
            {
                "id": REC_2,
                "createdTime": "2024-01-02T00:00:00.000Z",
                "fields": {"Name": "Bob"},
            },
        ]
    }

    cache_writes.apply_create(
        persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False
    )

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1).fields == {FLD_NAME: "Alice"}
    assert persistence.get_record(BASE_ID, TABLE_ID, REC_2).fields == {FLD_NAME: "Bob"}


def test_apply_create_upsert_response_ignores_created_and_updated_arrays(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {
        "records": [
            {
                "id": REC_1,
                "createdTime": "2024-01-01T00:00:00.000Z",
                "fields": {"Name": "Alice"},
            }
        ],
        "createdRecords": [REC_1],
        "updatedRecords": [],
    }

    cache_writes.apply_create(
        persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False
    )

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1).fields == {FLD_NAME: "Alice"}


def test_apply_create_passes_through_field_ids_when_flag_set(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {
        "id": REC_1,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "fields": {FLD_NAME: "Alice", FLD_AGE: 30},
    }

    cache_writes.apply_create(
        persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=True
    )

    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 30}


def test_apply_create_skips_unknown_field_name(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {
        "id": REC_1,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "fields": {"Name": "Alice", "Unknown": "x"},
    }

    cache_writes.apply_create(
        persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False
    )

    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice"}


def test_apply_create_with_missing_id_logs_and_skips_record(tmp_path, caplog):
    persistence = make_persistence(tmp_path)
    body = {"records": [{"createdTime": "x", "fields": {"Name": "Alice"}}]}

    cache_writes.apply_create(
        persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False
    )

    assert persistence.get_records(BASE_ID, TABLE_ID) == {}
```

- [ ] **Step 2: After approval, write the test file exactly as above**

- [ ] **Step 3: Run the tests to confirm they fail**

Run: `pytest tests/test_cache_writes.py -v`
Expected: every test fails with `ModuleNotFoundError: No module named 'airtable_proxy.cache_writes'`.

- [ ] **Step 4: Create `src/airtable_proxy/cache_writes.py` with `apply_create` and helpers**

```python
"""
Pure functions that translate Airtable mutation responses into local cache
updates. No HTTP or FastAPI dependencies — easy to unit test.

These functions are defensive about response shape: when a field key cannot
be resolved or a required key is missing they log and skip the affected
record/field rather than raising. The webhook poller will reconcile any
gaps within the next poll cycle. Storage exceptions are allowed to
propagate because they indicate bugs, not Airtable-side outcomes.
"""

import logging
from typing import Any

from airtable_proxy.persistence import AirtablePersistence

logger = logging.getLogger(__name__)


def apply_create(
    persistence: AirtablePersistence,
    base_id: str,
    table_id: str,
    body: dict[str, Any],
    *,
    response_uses_field_ids: bool,
) -> None:
    """
    Apply a successful POST response to the local cache.
    """
    records = _records_from_body(body)
    name_to_id = None if response_uses_field_ids else _name_to_id(persistence, base_id, table_id)
    for record in records:
        record_id = record.get("id")
        if not record_id:
            logger.warning("Skipping create: response record missing 'id'")
            continue
        created_time = record.get("createdTime", "")
        fields = _translate_fields(record.get("fields", {}), name_to_id)
        persistence.save_record(
            base_id, table_id, record_id, fields=fields, created_time=created_time
        )


def _records_from_body(body: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Normalize Airtable's two response shapes to a list of record dicts:

    - Single-record:  {"id": ..., "createdTime": ..., "fields": ...}
    - Multi-record:   {"records": [ {...}, {...} ], ...}
    """
    if isinstance(body.get("records"), list):
        return [r for r in body["records"] if isinstance(r, dict)]
    if "id" in body:
        return [body]
    return []


def _name_to_id(
    persistence: AirtablePersistence, base_id: str, table_id: str
) -> dict[str, str]:
    return {info.field_name: fid for fid, info in persistence.get_fields(base_id, table_id).items()}


def _translate_fields(
    fields: dict[str, Any], name_to_id: dict[str, str] | None
) -> dict[str, Any]:
    if name_to_id is None:
        return dict(fields)
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if key in name_to_id:
            out[name_to_id[key]] = value
        else:
            logger.debug("Skipping unknown field key %r in cache write", key)
    return out
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `mypy --strict && pytest tests/test_cache_writes.py -v`
Expected: all six tests pass; no mypy errors.

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `pytest`
Expected: green.

- [ ] **Step 7: `pre-commit run` and commit**

```bash
pre-commit run
git add src/airtable_proxy/cache_writes.py tests/test_cache_writes.py
git commit -m "Add cache_writes.apply_create"
```

---

### Task 3: `cache_writes.apply_update` (merge + replace semantics)

Adds PATCH (merge) and PUT (replace) semantics. A record not yet in the cache is treated as a create.

**Files:**
- Modify: `src/airtable_proxy/cache_writes.py`
- Modify: `tests/test_cache_writes.py`

- [ ] **Step 1: Ask the user for approval to extend `tests/test_cache_writes.py`**

Append the following tests to the existing file. Show the diff and wait for approval.

```python
def test_apply_update_merges_with_existing_record(tmp_path):
    persistence = make_persistence(tmp_path)
    persistence.save_record(
        BASE_ID, TABLE_ID, REC_1,
        {FLD_NAME: "Alice", FLD_AGE: 30},
        "2024-01-01T00:00:00.000Z",
    )
    body = {
        "id": REC_1,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "fields": {"Age": 31},
    }

    cache_writes.apply_update(
        persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False
    )

    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 31}
    assert stored.created_time == "2024-01-01T00:00:00.000Z"


def test_apply_update_replace_clears_unspecified_fields(tmp_path):
    persistence = make_persistence(tmp_path)
    persistence.save_record(
        BASE_ID, TABLE_ID, REC_1,
        {FLD_NAME: "Alice", FLD_AGE: 30},
        "2024-01-01T00:00:00.000Z",
    )
    body = {
        "id": REC_1,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "fields": {"Name": "Alicia"},
    }

    cache_writes.apply_update(
        persistence, BASE_ID, TABLE_ID, body,
        response_uses_field_ids=False, replace=True,
    )

    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alicia"}


def test_apply_update_missing_record_is_treated_as_create(tmp_path):
    persistence = make_persistence(tmp_path)
    body = {
        "id": REC_1,
        "createdTime": "2024-01-01T00:00:00.000Z",
        "fields": {"Name": "Alice"},
    }

    cache_writes.apply_update(
        persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False
    )

    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice"}


def test_apply_update_multi_record_response_with_upsert_shape(tmp_path):
    persistence = make_persistence(tmp_path)
    persistence.save_record(
        BASE_ID, TABLE_ID, REC_1, {FLD_NAME: "Old"}, "2024-01-01T00:00:00.000Z",
    )
    body = {
        "records": [
            {
                "id": REC_1,
                "createdTime": "2024-01-01T00:00:00.000Z",
                "fields": {"Name": "New"},
            },
            {
                "id": REC_2,
                "createdTime": "2024-02-01T00:00:00.000Z",
                "fields": {"Name": "Brand New"},
            },
        ],
        "createdRecords": [REC_2],
        "updatedRecords": [REC_1],
    }

    cache_writes.apply_update(
        persistence, BASE_ID, TABLE_ID, body, response_uses_field_ids=False
    )

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1).fields == {FLD_NAME: "New"}
    assert persistence.get_record(BASE_ID, TABLE_ID, REC_2).fields == {FLD_NAME: "Brand New"}
```

- [ ] **Step 2: After approval, append the tests**

- [ ] **Step 3: Run the tests to confirm they fail**

Run: `pytest tests/test_cache_writes.py -v`
Expected: the four new tests fail (`AttributeError: module 'airtable_proxy.cache_writes' has no attribute 'apply_update'`). Existing tests still pass.

- [ ] **Step 4: Add `apply_update` to `cache_writes.py`**

Insert after `apply_create`:

```python
def apply_update(
    persistence: AirtablePersistence,
    base_id: str,
    table_id: str,
    body: dict[str, Any],
    *,
    response_uses_field_ids: bool,
    replace: bool = False,
) -> None:
    """
    Apply a successful PATCH or PUT response to the local cache.

    With `replace=False` (default, PATCH semantics) the response fields are
    merged with the existing cached record. With `replace=True` (PUT
    semantics) the response fields replace the cached fields entirely.
    """
    records = _records_from_body(body)
    name_to_id = None if response_uses_field_ids else _name_to_id(persistence, base_id, table_id)
    for record in records:
        record_id = record.get("id")
        if not record_id:
            logger.warning("Skipping update: response record missing 'id'")
            continue
        new_fields = _translate_fields(record.get("fields", {}), name_to_id)
        existing = persistence.get_record(base_id, table_id, record_id)
        if existing is None or replace:
            merged_fields = new_fields
            created_time = record.get("createdTime") or (existing.created_time if existing else "")
        else:
            merged_fields = {**existing.fields, **new_fields}
            created_time = existing.created_time
        persistence.save_record(
            base_id, table_id, record_id, fields=merged_fields, created_time=created_time
        )
```

- [ ] **Step 5: Run the full test file and confirm green**

Run: `mypy --strict && pytest tests/test_cache_writes.py -v`
Expected: all tests pass.

- [ ] **Step 6: Run the full suite**

Run: `pytest`
Expected: green.

- [ ] **Step 7: `pre-commit run` and commit**

```bash
pre-commit run
git add src/airtable_proxy/cache_writes.py tests/test_cache_writes.py
git commit -m "Add cache_writes.apply_update with merge and replace semantics"
```

---

### Task 4: `cache_writes.apply_delete`

**Files:**
- Modify: `src/airtable_proxy/cache_writes.py`
- Modify: `tests/test_cache_writes.py`

- [ ] **Step 1: Ask the user for approval to extend `tests/test_cache_writes.py`**

```python
def test_apply_delete_single_record_shape(tmp_path):
    persistence = make_persistence(tmp_path)
    persistence.save_record(
        BASE_ID, TABLE_ID, REC_1, {FLD_NAME: "Alice"}, "2024-01-01T00:00:00.000Z",
    )

    cache_writes.apply_delete(
        persistence, BASE_ID, TABLE_ID, {"id": REC_1, "deleted": True}
    )

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is None


def test_apply_delete_multi_record_shape(tmp_path):
    persistence = make_persistence(tmp_path)
    persistence.save_record(
        BASE_ID, TABLE_ID, REC_1, {FLD_NAME: "Alice"}, "2024-01-01T00:00:00.000Z",
    )
    persistence.save_record(
        BASE_ID, TABLE_ID, REC_2, {FLD_NAME: "Bob"}, "2024-01-02T00:00:00.000Z",
    )

    cache_writes.apply_delete(
        persistence, BASE_ID, TABLE_ID,
        {"records": [{"id": REC_1, "deleted": True}, {"id": REC_2, "deleted": True}]},
    )

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is None
    assert persistence.get_record(BASE_ID, TABLE_ID, REC_2) is None


def test_apply_delete_missing_record_is_a_noop(tmp_path):
    persistence = make_persistence(tmp_path)

    cache_writes.apply_delete(
        persistence, BASE_ID, TABLE_ID, {"id": REC_1, "deleted": True}
    )

    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is None
```

- [ ] **Step 2: After approval, append the tests**

- [ ] **Step 3: Run the tests to confirm they fail**

Run: `pytest tests/test_cache_writes.py -v`
Expected: the three new tests fail with `AttributeError: ... has no attribute 'apply_delete'`.

- [ ] **Step 4: Add `apply_delete` to `cache_writes.py`**

Insert after `apply_update`:

```python
def apply_delete(
    persistence: AirtablePersistence,
    base_id: str,
    table_id: str,
    body: dict[str, Any],
) -> None:
    """
    Apply a successful DELETE response to the local cache.

    Handles both single-record (`{"id": ..., "deleted": true}`) and
    multi-record (`{"records": [{"id": ..., "deleted": true}, ...]}`)
    response shapes. A request to delete a record we don't have cached
    is a no-op.
    """
    if isinstance(body.get("records"), list):
        ids = [r.get("id") for r in body["records"] if isinstance(r, dict)]
    elif "id" in body:
        ids = [body.get("id")]
    else:
        ids = []
    for record_id in ids:
        if not record_id:
            logger.warning("Skipping delete: response record missing 'id'")
            continue
        persistence.delete_record(base_id, table_id, record_id)
```

- [ ] **Step 5: Run the full test file and confirm green**

Run: `mypy --strict && pytest tests/test_cache_writes.py -v`
Expected: all tests pass.

- [ ] **Step 6: Run the full suite**

Run: `pytest`
Expected: green.

- [ ] **Step 7: `pre-commit run` and commit**

```bash
pre-commit run
git add src/airtable_proxy/cache_writes.py tests/test_cache_writes.py
git commit -m "Add cache_writes.apply_delete"
```

---

### Task 5: `routes/create_records.py` — POST handler

**Files:**
- Create: `src/airtable_proxy/routes/create_records.py`
- Create: `tests/test_routes_create_records.py`
- Modify: `src/airtable_proxy/app.py`

- [ ] **Step 1: Ask the user for approval to write `tests/test_routes_create_records.py`**

```python
"""Tests for the create-records mutation route."""

from fastapi.testclient import TestClient
from pyairtable.testing import fake_id

from airtable_proxy import app
from airtable_proxy.config import Config

BASE_ID = fake_id("app")
TABLE_ID = fake_id("tbl")
FLD_NAME = fake_id("fld")
REC_1 = fake_id("rec")


def make_config(tmp_path):
    return Config.model_validate(
        {
            "hostname": "test.example.com",
            "bases": {},
            "storage": {"sqlite": str(tmp_path / "test.db")},
        }
    )


def populate_table(persistence):
    persistence.save_table(BASE_ID, TABLE_ID, "Test Table")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_NAME, "Name", "singleLineText")


def test_post_updates_cache_with_single_record(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={
            "id": REC_1,
            "createdTime": "2024-01-01T00:00:00.000Z",
            "fields": {"Name": "Alice"},
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate_table(test_app.state.persistence)
        response = client.post(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            json={"fields": {"Name": "Alice"}},
        )

    assert response.status_code == 200
    persistence = test_app.state.persistence
    stored = persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice"}


def test_post_updates_cache_with_multi_record_response(httpx_mock, tmp_path):
    rec_2 = fake_id("rec")
    httpx_mock.add_response(
        json={
            "records": [
                {"id": REC_1, "createdTime": "x", "fields": {"Name": "Alice"}},
                {"id": rec_2, "createdTime": "x", "fields": {"Name": "Bob"}},
            ]
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate_table(test_app.state.persistence)
        response = client.post(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            json={"records": [{"fields": {"Name": "Alice"}}, {"fields": {"Name": "Bob"}}]},
        )

    assert response.status_code == 200
    persistence = test_app.state.persistence
    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1).fields == {FLD_NAME: "Alice"}
    assert persistence.get_record(BASE_ID, TABLE_ID, rec_2).fields == {FLD_NAME: "Bob"}


def test_post_with_return_fields_by_field_id(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={
            "id": REC_1,
            "createdTime": "2024-01-01T00:00:00.000Z",
            "fields": {FLD_NAME: "Alice"},
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate_table(test_app.state.persistence)
        response = client.post(
            f"/v0/{BASE_ID}/{TABLE_ID}?returnFieldsByFieldId=true",
            json={"fields": {FLD_NAME: "Alice"}},
        )

    assert response.status_code == 200
    persistence = test_app.state.persistence
    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1).fields == {FLD_NAME: "Alice"}


def test_post_non_2xx_does_not_update_cache(httpx_mock, tmp_path):
    httpx_mock.add_response(status_code=422, json={"error": "bad request"})

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate_table(test_app.state.persistence)
        response = client.post(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            json={"fields": {"Name": "Alice"}},
        )

    assert response.status_code == 422
    assert persistence_records(test_app) == {}


def test_post_unknown_table_falls_through_to_proxy(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={"id": REC_1, "createdTime": "x", "fields": {"Name": "Alice"}}
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        response = client.post(
            f"/v0/{BASE_ID}/UnknownTable",
            json={"fields": {"Name": "Alice"}},
        )

    assert response.status_code == 200
    assert len(httpx_mock.get_requests()) == 1


def persistence_records(test_app):
    return test_app.state.persistence.get_records(BASE_ID, TABLE_ID)
```

- [ ] **Step 2: After approval, write the test file**

- [ ] **Step 3: Run the tests to confirm they fail**

Run: `pytest tests/test_routes_create_records.py -v`
Expected: tests fail — the POST request currently hits the catch-all proxy unconditionally, so the cache is never updated. (`test_post_unknown_table_falls_through_to_proxy` may pass already; the cache-update tests will fail.)

- [ ] **Step 4: Create `src/airtable_proxy/routes/create_records.py`**

```python
"""
POST /v0/{base_id}/{table_id_or_name}

Creates record(s) at Airtable. On a 2xx response the local cache is
updated to match the response, so reads against the proxy see the new
record(s) without waiting for the webhook poller.
"""

import logging

from fastapi import FastAPI, Request, Response

from airtable_proxy import cache_writes
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import ProxyRequest, forward, response_from_httpx
from airtable_proxy.util import resolve_table_id

logger = logging.getLogger(__name__)


def add_routes(app: FastAPI) -> None:
    """
    Register the create-records route on the FastAPI app.
    """

    @app.post("/v0/{base_id}/{table_id_or_name}")
    async def create_records(
        request: Request, base_id: str, table_id_or_name: str
    ) -> Response:
        persistence: AirtablePersistence = request.app.state.persistence

        table_id = resolve_table_id(base_id, table_id_or_name, persistence)
        if table_id is None:
            raise ProxyRequest()

        httpx_response = await forward(request, f"v0/{base_id}/{table_id_or_name}")

        if 200 <= httpx_response.status_code < 300:
            _apply_to_cache(httpx_response, request, persistence, base_id, table_id)

        return response_from_httpx(httpx_response)


def _apply_to_cache(
    httpx_response, request: Request, persistence, base_id: str, table_id: str
) -> None:
    try:
        body = httpx_response.json()
    except ValueError:
        logger.warning("Airtable response was not JSON; skipping cache update")
        return
    response_uses_field_ids = request.query_params.get("returnFieldsByFieldId") == "true"
    cache_writes.apply_create(
        persistence, base_id, table_id, body,
        response_uses_field_ids=response_uses_field_ids,
    )
```

- [ ] **Step 5: Register the route in `app.py`**

Edit `src/airtable_proxy/app.py`:

```python
from airtable_proxy.routes import create_records, get_record, list_records
```

(replacing the existing `from airtable_proxy.routes import get_record, list_records` line) and add the registration call alongside the existing ones:

```python
    list_records.add_routes(app)
    get_record.add_routes(app)
    create_records.add_routes(app)
```

- [ ] **Step 6: Run the new tests and the full suite**

Run: `mypy --strict && pytest`
Expected: green.

- [ ] **Step 7: `pre-commit run` and commit**

```bash
pre-commit run
git add src/airtable_proxy/routes/create_records.py tests/test_routes_create_records.py src/airtable_proxy/app.py
git commit -m "Update cache on successful POST"
```

---

### Task 6: `routes/update_records.py` — PATCH and PUT handlers

Two routes (single + multi), each handling PATCH and PUT. `PUT` sets `replace=True`.

**Files:**
- Create: `src/airtable_proxy/routes/update_records.py`
- Create: `tests/test_routes_update_records.py`
- Modify: `src/airtable_proxy/app.py`

- [ ] **Step 1: Ask the user for approval to write `tests/test_routes_update_records.py`**

```python
"""Tests for the update-records mutation routes."""

from fastapi.testclient import TestClient
from pyairtable.testing import fake_id

from airtable_proxy import app
from airtable_proxy.config import Config

BASE_ID = fake_id("app")
TABLE_ID = fake_id("tbl")
FLD_NAME = fake_id("fld")
FLD_AGE = fake_id("fld")
REC_1 = fake_id("rec")


def make_config(tmp_path):
    return Config.model_validate(
        {
            "hostname": "test.example.com",
            "bases": {},
            "storage": {"sqlite": str(tmp_path / "test.db")},
        }
    )


def populate(persistence):
    persistence.save_table(BASE_ID, TABLE_ID, "Test Table")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_NAME, "Name", "singleLineText")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_AGE, "Age", "number")
    persistence.save_record(
        BASE_ID, TABLE_ID, REC_1,
        {FLD_NAME: "Alice", FLD_AGE: 30},
        "2024-01-01T00:00:00.000Z",
    )


def test_patch_single_merges_with_existing(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={
            "id": REC_1,
            "createdTime": "2024-01-01T00:00:00.000Z",
            "fields": {"Age": 31},
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.patch(
            f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}",
            json={"fields": {"Age": 31}},
        )

    assert response.status_code == 200
    stored = test_app.state.persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 31}


def test_put_single_replaces_existing(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={
            "id": REC_1,
            "createdTime": "2024-01-01T00:00:00.000Z",
            "fields": {"Name": "Alicia"},
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.put(
            f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}",
            json={"fields": {"Name": "Alicia"}},
        )

    assert response.status_code == 200
    stored = test_app.state.persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alicia"}  # Age cleared


def test_patch_multi_with_records_body(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={
            "records": [
                {
                    "id": REC_1,
                    "createdTime": "2024-01-01T00:00:00.000Z",
                    "fields": {"Age": 99},
                }
            ]
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.patch(
            f"/v0/{BASE_ID}/{TABLE_ID}",
            json={"records": [{"id": REC_1, "fields": {"Age": 99}}]},
        )

    assert response.status_code == 200
    stored = test_app.state.persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 99}


def test_patch_non_2xx_does_not_update_cache(httpx_mock, tmp_path):
    httpx_mock.add_response(status_code=422, json={"error": "bad request"})

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.patch(
            f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}",
            json={"fields": {"Age": 31}},
        )

    assert response.status_code == 422
    stored = test_app.state.persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 30}


def test_patch_unknown_table_falls_through(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={"id": REC_1, "createdTime": "x", "fields": {"Name": "Alice"}}
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        response = client.patch(
            f"/v0/{BASE_ID}/UnknownTable/{REC_1}",
            json={"fields": {"Name": "Alice"}},
        )

    assert response.status_code == 200
    assert len(httpx_mock.get_requests()) == 1


def test_patch_with_return_fields_by_field_id(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={
            "id": REC_1,
            "createdTime": "2024-01-01T00:00:00.000Z",
            "fields": {FLD_AGE: 31},
        }
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.patch(
            f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}?returnFieldsByFieldId=true",
            json={"fields": {FLD_AGE: 31}},
        )

    assert response.status_code == 200
    stored = test_app.state.persistence.get_record(BASE_ID, TABLE_ID, REC_1)
    assert stored.fields == {FLD_NAME: "Alice", FLD_AGE: 31}
```

- [ ] **Step 2: After approval, write the test file**

- [ ] **Step 3: Run the tests to confirm they fail**

Run: `pytest tests/test_routes_update_records.py -v`
Expected: cache-update tests fail (PATCH/PUT currently hit the catch-all).

- [ ] **Step 4: Create `src/airtable_proxy/routes/update_records.py`**

```python
"""
PATCH / PUT /v0/{base_id}/{table_id_or_name}[/{record_id}]

Updates record(s) at Airtable. On a 2xx response the local cache is
updated to match the response. PATCH merges with existing cached fields;
PUT replaces them.
"""

import logging

from fastapi import FastAPI, Request, Response

from airtable_proxy import cache_writes
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import ProxyRequest, forward, response_from_httpx
from airtable_proxy.util import resolve_table_id

logger = logging.getLogger(__name__)


def add_routes(app: FastAPI) -> None:
    """
    Register the update-records routes on the FastAPI app.
    """

    @app.api_route(
        "/v0/{base_id}/{table_id_or_name}", methods=["PATCH", "PUT"]
    )
    async def update_records_multi(
        request: Request, base_id: str, table_id_or_name: str
    ) -> Response:
        return await _handle(request, base_id, table_id_or_name, path_suffix="")

    @app.api_route(
        "/v0/{base_id}/{table_id_or_name}/{record_id}", methods=["PATCH", "PUT"]
    )
    async def update_records_single(
        request: Request, base_id: str, table_id_or_name: str, record_id: str
    ) -> Response:
        return await _handle(
            request, base_id, table_id_or_name, path_suffix=f"/{record_id}"
        )


async def _handle(
    request: Request, base_id: str, table_id_or_name: str, *, path_suffix: str
) -> Response:
    persistence: AirtablePersistence = request.app.state.persistence

    table_id = resolve_table_id(base_id, table_id_or_name, persistence)
    if table_id is None:
        raise ProxyRequest()

    httpx_response = await forward(
        request, f"v0/{base_id}/{table_id_or_name}{path_suffix}"
    )

    if 200 <= httpx_response.status_code < 300:
        _apply_to_cache(httpx_response, request, persistence, base_id, table_id)

    return response_from_httpx(httpx_response)


def _apply_to_cache(
    httpx_response, request: Request, persistence, base_id: str, table_id: str
) -> None:
    try:
        body = httpx_response.json()
    except ValueError:
        logger.warning("Airtable response was not JSON; skipping cache update")
        return
    response_uses_field_ids = request.query_params.get("returnFieldsByFieldId") == "true"
    cache_writes.apply_update(
        persistence, base_id, table_id, body,
        response_uses_field_ids=response_uses_field_ids,
        replace=(request.method == "PUT"),
    )
```

- [ ] **Step 5: Register the routes in `app.py`**

Edit the imports and the registration block in `create_app`:

```python
from airtable_proxy.routes import create_records, get_record, list_records, update_records
```

```python
    list_records.add_routes(app)
    get_record.add_routes(app)
    create_records.add_routes(app)
    update_records.add_routes(app)
```

- [ ] **Step 6: Run the new tests and the full suite**

Run: `mypy --strict && pytest`
Expected: green.

- [ ] **Step 7: `pre-commit run` and commit**

```bash
pre-commit run
git add src/airtable_proxy/routes/update_records.py tests/test_routes_update_records.py src/airtable_proxy/app.py
git commit -m "Update cache on successful PATCH and PUT"
```

---

### Task 7: `routes/delete_records.py` — DELETE handlers

**Files:**
- Create: `src/airtable_proxy/routes/delete_records.py`
- Create: `tests/test_routes_delete_records.py`
- Modify: `src/airtable_proxy/app.py`

- [ ] **Step 1: Ask the user for approval to write `tests/test_routes_delete_records.py`**

```python
"""Tests for the delete-records mutation routes."""

from fastapi.testclient import TestClient
from pyairtable.testing import fake_id

from airtable_proxy import app
from airtable_proxy.config import Config

BASE_ID = fake_id("app")
TABLE_ID = fake_id("tbl")
FLD_NAME = fake_id("fld")
REC_1 = fake_id("rec")
REC_2 = fake_id("rec")


def make_config(tmp_path):
    return Config.model_validate(
        {
            "hostname": "test.example.com",
            "bases": {},
            "storage": {"sqlite": str(tmp_path / "test.db")},
        }
    )


def populate(persistence):
    persistence.save_table(BASE_ID, TABLE_ID, "Test Table")
    persistence.save_field(BASE_ID, TABLE_ID, FLD_NAME, "Name", "singleLineText")
    persistence.save_record(
        BASE_ID, TABLE_ID, REC_1, {FLD_NAME: "Alice"}, "2024-01-01T00:00:00.000Z",
    )
    persistence.save_record(
        BASE_ID, TABLE_ID, REC_2, {FLD_NAME: "Bob"}, "2024-01-02T00:00:00.000Z",
    )


def test_delete_single_record_removes_from_cache(httpx_mock, tmp_path):
    httpx_mock.add_response(json={"id": REC_1, "deleted": True})

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.delete(f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}")

    assert response.status_code == 200
    persistence = test_app.state.persistence
    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is None
    assert persistence.get_record(BASE_ID, TABLE_ID, REC_2) is not None


def test_delete_multi_records_removes_from_cache(httpx_mock, tmp_path):
    httpx_mock.add_response(
        json={"records": [{"id": REC_1, "deleted": True}, {"id": REC_2, "deleted": True}]}
    )

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.delete(
            f"/v0/{BASE_ID}/{TABLE_ID}?records[]={REC_1}&records[]={REC_2}"
        )

    assert response.status_code == 200
    persistence = test_app.state.persistence
    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is None
    assert persistence.get_record(BASE_ID, TABLE_ID, REC_2) is None


def test_delete_non_2xx_does_not_update_cache(httpx_mock, tmp_path):
    httpx_mock.add_response(status_code=404, json={"error": "not found"})

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        populate(test_app.state.persistence)
        response = client.delete(f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}")

    assert response.status_code == 404
    persistence = test_app.state.persistence
    assert persistence.get_record(BASE_ID, TABLE_ID, REC_1) is not None


def test_delete_unknown_table_falls_through(httpx_mock, tmp_path):
    httpx_mock.add_response(json={"id": REC_1, "deleted": True})

    test_app = app.create_app(config=make_config(tmp_path))
    with TestClient(test_app) as client:
        response = client.delete(f"/v0/{BASE_ID}/UnknownTable/{REC_1}")

    assert response.status_code == 200
    assert len(httpx_mock.get_requests()) == 1
```

- [ ] **Step 2: After approval, write the test file**

- [ ] **Step 3: Run the tests to confirm they fail**

Run: `pytest tests/test_routes_delete_records.py -v`
Expected: cache-removal tests fail.

- [ ] **Step 4: Create `src/airtable_proxy/routes/delete_records.py`**

```python
"""
DELETE /v0/{base_id}/{table_id_or_name}[/{record_id}]

Deletes record(s) at Airtable. On a 2xx response the local cache is
updated to remove the deleted record(s).
"""

import logging

from fastapi import FastAPI, Request, Response

from airtable_proxy import cache_writes
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import ProxyRequest, forward, response_from_httpx
from airtable_proxy.util import resolve_table_id

logger = logging.getLogger(__name__)


def add_routes(app: FastAPI) -> None:
    """
    Register the delete-records routes on the FastAPI app.
    """

    @app.delete("/v0/{base_id}/{table_id_or_name}")
    async def delete_records_multi(
        request: Request, base_id: str, table_id_or_name: str
    ) -> Response:
        return await _handle(request, base_id, table_id_or_name, path_suffix="")

    @app.delete("/v0/{base_id}/{table_id_or_name}/{record_id}")
    async def delete_records_single(
        request: Request, base_id: str, table_id_or_name: str, record_id: str
    ) -> Response:
        return await _handle(
            request, base_id, table_id_or_name, path_suffix=f"/{record_id}"
        )


async def _handle(
    request: Request, base_id: str, table_id_or_name: str, *, path_suffix: str
) -> Response:
    persistence: AirtablePersistence = request.app.state.persistence

    table_id = resolve_table_id(base_id, table_id_or_name, persistence)
    if table_id is None:
        raise ProxyRequest()

    httpx_response = await forward(
        request, f"v0/{base_id}/{table_id_or_name}{path_suffix}"
    )

    if 200 <= httpx_response.status_code < 300:
        _apply_to_cache(httpx_response, persistence, base_id, table_id)

    return response_from_httpx(httpx_response)


def _apply_to_cache(
    httpx_response, persistence, base_id: str, table_id: str
) -> None:
    try:
        body = httpx_response.json()
    except ValueError:
        logger.warning("Airtable response was not JSON; skipping cache update")
        return
    cache_writes.apply_delete(persistence, base_id, table_id, body)
```

- [ ] **Step 5: Register the routes in `app.py`**

Edit the imports and registration block:

```python
from airtable_proxy.routes import (
    create_records,
    delete_records,
    get_record,
    list_records,
    update_records,
)
```

```python
    list_records.add_routes(app)
    get_record.add_routes(app)
    create_records.add_routes(app)
    update_records.add_routes(app)
    delete_records.add_routes(app)
```

- [ ] **Step 6: Run the new tests and the full suite**

Run: `mypy --strict && pytest`
Expected: green.

- [ ] **Step 7: `pre-commit run` and commit**

```bash
pre-commit run
git add src/airtable_proxy/routes/delete_records.py tests/test_routes_delete_records.py src/airtable_proxy/app.py
git commit -m "Update cache on successful DELETE"
```

---

### Task 8: Integration tests

Verify the round-trip against the real Airtable API. These confirm the design assumption that PATCH responses carry the full post-update record state.

Integration tests require credentials. Run them with `dotenv -f tmp/integration.sh run -- pytest -k integration` per `AGENTS.md`. Set up `tmp/integration.sh` from your existing `.env.itest` if it isn't already in place — see the README's "Integration tests hit the real Airtable API and need credentials" section.

**Files:**
- Create: `tests/integration/itest_routes_create_records.py`
- Create: `tests/integration/itest_routes_update_records.py`
- Create: `tests/integration/itest_routes_delete_records.py`

- [ ] **Step 1: Inspect existing integration tests for the shared fixture pattern**

Run: `ls tests/integration && cat tests/integration/conftest.py 2>/dev/null || true`

Use whatever fixture pattern is already established (live `config.yaml`, real `BASE_ID`, real auth). If no integration test exists yet, model after the README's integration-test note and the unit-test patterns from Tasks 5–7. Document the fixture you adopted at the top of the first new integration file as a one-line comment.

- [ ] **Step 2: Ask the user for approval to write the three integration test files**

Each file exercises a real round-trip via the live Airtable API. They follow this pattern (filled in per file):

```python
"""Integration tests for create_records — round-trip against real Airtable."""

# Use the fixture pattern adopted in Step 1.

def test_post_then_cache_reflects_new_record(live_client, live_persistence, live_table):
    response = live_client.post(
        f"/v0/{live_table.base_id}/{live_table.table_id}",
        json={"fields": {"Name": "ItestAlice"}},
        headers={"Authorization": f"Bearer {live_table.api_key}"},
    )
    assert response.status_code == 200
    record_id = response.json()["id"]

    stored = live_persistence.get_record(live_table.base_id, live_table.table_id, record_id)
    assert stored is not None
    assert stored.fields[live_table.fld_name] == "ItestAlice"
```

The update file additionally verifies the **PATCH-returns-full-state** assumption:

```python
def test_patch_response_carries_full_post_state(live_client, live_persistence, live_table):
    # ... POST a record with Name + Age set ...
    # PATCH only the Age ...
    # Read the cache and assert BOTH Name and Age are present.
```

The delete file verifies that `get_record` against the cache returns `None` after a successful DELETE.

- [ ] **Step 3: After approval, write the three files**

- [ ] **Step 4: Run the integration tests**

Run: `dotenv -f tmp/integration.sh run -- pytest -k integration -v`
Expected: all three round-trip tests pass.

If the PATCH-full-state assertion fails (the merged cache record is missing the field we didn't update), the design needs revisiting; stop and report the failure rather than working around it.

- [ ] **Step 5: Run the unit suite once more to confirm no regressions**

Run: `mypy --strict && pytest`
Expected: green.

- [ ] **Step 6: `pre-commit run` and commit**

```bash
pre-commit run
git add tests/integration/itest_routes_create_records.py tests/integration/itest_routes_update_records.py tests/integration/itest_routes_delete_records.py
git commit -m "Add integration tests for record mutation cache updates"
```

---

### Task 9: Update `TODO.md` and finalize

**Files:**
- Modify: `TODO.md`

- [ ] **Step 1: Tick the 0.2 item**

Replace the line:

```markdown
- [ ] Update the cache after POST/PUT/PATCH/DELETE operations
```

with:

```markdown
- [x] Update the cache after POST/PUT/PATCH/DELETE operations
```

- [ ] **Step 2: Run the full verification pass**

Run: `mypy --strict && pytest && pre-commit run`
Expected: green.

- [ ] **Step 3: Commit**

```bash
git add TODO.md
git commit -m "Mark 0.2 cache writes item complete"
```

---

## Self-review notes

- **Spec coverage:** Every section of the design maps to a task — proxy refactor → T1, cache_writes module → T2–T4, route modules → T5–T7, integration tests / assumption check → T8, TODO bookkeeping → T9. The "skip caching on unknown table" and "skip caching on non-2xx" behaviors are covered by named tests in T5/T6/T7. The "log warning, return success on shape mismatch" behavior is realized by defensive checks inside `cache_writes`, not a handler `try/except`, which keeps the handler clear and respects the "don't catch `Exception`" project rule; this is a minor implementation-level adjustment vs. the design's prose but produces the same observable behavior.
- **Placeholders:** Task 8 Step 1 deliberately defers the integration-test fixture detail because no integration tests exist in the repo today; the engineer reads the existing layout and adopts the convention there, which keeps this plan honest. All other steps include the exact code.
- **Type consistency:** `apply_create`, `apply_update`, `apply_delete` are referenced by name in the route tasks exactly as defined in the cache_writes tasks. The `response_uses_field_ids` keyword and the `replace` keyword are used identically across plan and code blocks. The route helpers `forward` / `response_from_httpx` introduced in T1 are imported with the same names in T5/T6/T7.
