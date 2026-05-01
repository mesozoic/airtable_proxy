# Get Record Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `GET /v0/{base_id}/{table_id_or_name}/{record_id}` served from local storage, with proxy fallbacks, while extracting helpers shared with `list_records`.

**Architecture:** A new `airtable_proxy.util` module holds the helpers (`is_empty_value`, `resolve_table_id`, `format_record_fields`). `list_records` is refactored to consume them; `get_record` is a new route in `routes/get_record.py` that uses the same helpers. The handler raises `ProxyRequest` when local storage cannot satisfy the request, falling through to the existing catch-all proxy.

**Tech Stack:** Python 3.13, FastAPI, pytest, pyairtable.testing (for ID fixtures), httpx (mocked in tests).

**Spec:** `docs/plans/2026-05-01-get-record-design.md`

**Coverage requirement:** The project enforces `--cov-fail-under=100` in `pyproject.toml`. Every line of new code must be exercised by tests.

---

### Task 1: Create `util` module with `is_empty_value`

**Files:**
- Create: `src/airtable_proxy/util.py`
- Create: `tests/test_util.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_util.py`:

```python
"""Tests for airtable_proxy.util."""

import pytest

from airtable_proxy.util import is_empty_value


@pytest.mark.parametrize("value", [None, "", [], False])
def test_is_empty_value_true(value):
    assert is_empty_value(value) is True


@pytest.mark.parametrize("value", ["x", 0, [None], True, {"k": "v"}])
def test_is_empty_value_false(value):
    assert is_empty_value(value) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_util.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'airtable_proxy.util'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/airtable_proxy/util.py`:

```python
"""Shared helpers for routes that read from local storage."""

from typing import Any


def is_empty_value(value: Any) -> bool:
    """
    Check if a value is considered "empty" by Airtable.

    Airtable omits fields with empty values (None, "", [], False) from responses.
    """
    if value is None:
        return True
    if value == "":
        return True
    if value == []:
        return True
    if value is False:
        return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_util.py -v --no-cov`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add src/airtable_proxy/util.py tests/test_util.py
git commit -m "Add util.is_empty_value helper"
```

---

### Task 2: Add `resolve_table_id` to `util`

**Files:**
- Modify: `src/airtable_proxy/util.py`
- Modify: `tests/test_util.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_util.py`:

```python
from pyairtable.testing import fake_id

from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage
from airtable_proxy.util import resolve_table_id


@pytest.fixture
def persist(tmp_path):
    storage = Storage(tmp_path / "test.db")
    yield AirtablePersistence(storage)
    storage.close()


def test_resolve_table_id_by_id(persist):
    base_id = fake_id("app")
    table_id = fake_id("tbl")
    persist.save_table(base_id, table_id, "My Table")

    assert resolve_table_id(base_id, table_id, persist) == table_id


def test_resolve_table_id_by_name(persist):
    base_id = fake_id("app")
    table_id = fake_id("tbl")
    persist.save_table(base_id, table_id, "My Table")

    assert resolve_table_id(base_id, "My Table", persist) == table_id


def test_resolve_table_id_unknown_id(persist):
    base_id = fake_id("app")
    assert resolve_table_id(base_id, fake_id("tbl"), persist) is None


def test_resolve_table_id_unknown_name(persist):
    base_id = fake_id("app")
    assert resolve_table_id(base_id, "Nope", persist) is None


def test_resolve_table_id_id_prefix_but_missing_falls_through_to_name(persist):
    """A 'tbl'-prefixed value that isn't stored should still match by name if a table is named that way."""
    base_id = fake_id("app")
    table_id = fake_id("tbl")
    fake_name = fake_id("tbl")  # also looks like a table id
    persist.save_table(base_id, table_id, fake_name)

    assert resolve_table_id(base_id, fake_name, persist) == table_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_util.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'resolve_table_id' from 'airtable_proxy.util'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/airtable_proxy/util.py`:

```python
from airtable_proxy.persistence import AirtablePersistence


def resolve_table_id(
    base_id: str,
    table_id_or_name: str,
    persistence: AirtablePersistence,
) -> str | None:
    """
    Resolve a table ID or name to a table ID.

    Returns None if the table is not found in local storage.
    """
    if table_id_or_name.startswith("tbl"):
        if persistence.get_table(base_id, table_id_or_name) is not None:
            return table_id_or_name

    for table_id, info in persistence.get_tables(base_id).items():
        if info.table_name == table_id_or_name:
            return table_id

    return None
```

Move the new `from airtable_proxy.persistence import AirtablePersistence` import to the top of the file with the other imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_util.py -v --no-cov`
Expected: PASS, 13 tests.

- [ ] **Step 5: Commit**

```bash
git add src/airtable_proxy/util.py tests/test_util.py
git commit -m "Add util.resolve_table_id helper"
```

---

### Task 3: Add `format_record_fields` to `util`

**Files:**
- Modify: `src/airtable_proxy/util.py`
- Modify: `tests/test_util.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_util.py`:

```python
from airtable_proxy.persistence import FieldInfo, RecordInfo
from airtable_proxy.util import format_record_fields


def _record(fields):
    return RecordInfo(fields=fields, created_time="2024-01-01T00:00:00.000Z")


def _fields(*specs):
    """specs is an iterable of (field_id, field_name) tuples."""
    return {fid: FieldInfo(field_name=name, field_type="singleLineText") for fid, name in specs}


def test_format_record_fields_keys_by_name_by_default():
    record = _record({"fld1": "Alice", "fld2": 30})
    fields = _fields(("fld1", "Name"), ("fld2", "Age"))

    result = format_record_fields(record, fields, return_fields_by_field_id=False)

    assert result == {"Name": "Alice", "Age": 30}


def test_format_record_fields_keys_by_id_when_requested():
    record = _record({"fld1": "Alice", "fld2": 30})
    fields = _fields(("fld1", "Name"), ("fld2", "Age"))

    result = format_record_fields(record, fields, return_fields_by_field_id=True)

    assert result == {"fld1": "Alice", "fld2": 30}


def test_format_record_fields_omits_empty_values():
    record = _record({"fld1": "Alice", "fld2": "", "fld3": None, "fld4": False, "fld5": []})
    fields = _fields(
        ("fld1", "Name"), ("fld2", "Empty"), ("fld3", "Null"), ("fld4", "Off"), ("fld5", "List")
    )

    result = format_record_fields(record, fields, return_fields_by_field_id=False)

    assert result == {"Name": "Alice"}


def test_format_record_fields_falls_back_to_id_when_name_unknown():
    """If a record has a field that isn't in field_info, fall back to the field ID."""
    record = _record({"fld1": "Alice", "fld_unknown": "Mystery"})
    fields = _fields(("fld1", "Name"))

    result = format_record_fields(record, fields, return_fields_by_field_id=False)

    assert result == {"Name": "Alice", "fld_unknown": "Mystery"}


def test_format_record_fields_filters_by_include_set_by_id():
    record = _record({"fld1": "Alice", "fld2": 30, "fld3": True})
    fields = _fields(("fld1", "Name"), ("fld2", "Age"), ("fld3", "Active"))

    result = format_record_fields(
        record, fields, return_fields_by_field_id=False, include_field_ids={"fld1", "fld3"}
    )

    assert result == {"Name": "Alice", "Active": True}


def test_format_record_fields_empty_include_set_returns_no_fields():
    record = _record({"fld1": "Alice"})
    fields = _fields(("fld1", "Name"))

    result = format_record_fields(
        record, fields, return_fields_by_field_id=False, include_field_ids=set()
    )

    assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_util.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'format_record_fields' from 'airtable_proxy.util'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/airtable_proxy/util.py`:

```python
from airtable_proxy.persistence import FieldInfo, RecordInfo


def format_record_fields(
    record: RecordInfo,
    field_info: dict[str, FieldInfo],
    *,
    return_fields_by_field_id: bool,
    include_field_ids: set[str] | None = None,
) -> dict[str, Any]:
    """
    Build the `fields` dict for an API response from a stored record.

    Omits empty values (per `is_empty_value`). Keys output by field ID when
    `return_fields_by_field_id` is true, otherwise by field name (falling back
    to the field ID if no name is known). When `include_field_ids` is given,
    only those field IDs are kept.
    """
    output: dict[str, Any] = {}
    for field_id, value in record.fields.items():
        if include_field_ids is not None and field_id not in include_field_ids:
            continue
        if is_empty_value(value):
            continue

        if return_fields_by_field_id:
            output[field_id] = value
        else:
            info = field_info.get(field_id)
            output[info.field_name if info is not None else field_id] = value

    return output
```

Move the `FieldInfo, RecordInfo` import to the top of the file alongside the existing persistence import.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_util.py -v --no-cov`
Expected: PASS, 19 tests.

- [ ] **Step 5: Commit**

```bash
git add src/airtable_proxy/util.py tests/test_util.py
git commit -m "Add util.format_record_fields helper"
```

---

### Task 4: Refactor `list_records` to use `util` helpers

**Files:**
- Modify: `src/airtable_proxy/routes/list_records.py`

- [ ] **Step 1: Confirm existing tests pass before changes**

Run: `poetry run pytest tests/test_routes_list_records.py -v --no-cov`
Expected: PASS for all existing list-records tests.

- [ ] **Step 2: Replace `list_records.py` content**

Overwrite `src/airtable_proxy/routes/list_records.py` with:

```python
"""
List records from local storage, matching the Airtable API response format.
"""

from typing import Any

from fastapi import FastAPI, Query, Request

from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import ProxyRequest
from airtable_proxy.util import format_record_fields, resolve_table_id


def add_routes(app: FastAPI) -> None:
    """
    Register list records routes on the FastAPI app.
    """

    @app.get("/v0/{base_id}/{table_id_or_name}")
    def list_records(
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

        table_id = resolve_table_id(base_id, table_id_or_name, persistence)
        if table_id is None:
            raise ProxyRequest()

        field_info = persistence.get_fields(base_id, table_id)
        field_name_to_id = {info.field_name: fid for fid, info in field_info.items()}

        include_field_ids: set[str] | None = None
        if fields is not None:
            include_field_ids = set()
            for f in fields:
                if f in field_info:
                    include_field_ids.add(f)
                elif f in field_name_to_id:
                    include_field_ids.add(field_name_to_id[f])

        all_records = persistence.get_records(base_id, table_id)
        result_records: list[dict[str, Any]] = []

        for record_id, record_info in all_records.items():
            output_fields = format_record_fields(
                record_info,
                field_info,
                return_fields_by_field_id=returnFieldsByFieldId,
                include_field_ids=include_field_ids,
            )
            result_records.append(
                {
                    "id": record_id,
                    "createdTime": record_info.created_time,
                    "fields": output_fields,
                }
            )

            if maxRecords is not None and len(result_records) >= maxRecords:
                break

        return {"records": result_records}
```

- [ ] **Step 3: Re-run existing list-records tests**

Run: `poetry run pytest tests/test_routes_list_records.py -v --no-cov`
Expected: PASS — same set of tests as before, no behavior change.

- [ ] **Step 4: Run full test suite with coverage to ensure 100%**

Run: `poetry run pytest`
Expected: PASS, coverage at 100%. If coverage is below 100% for `util.py` or `list_records.py`, the new helpers have lines unreached by tests — add cases until covered.

- [ ] **Step 5: Commit**

```bash
git add src/airtable_proxy/routes/list_records.py
git commit -m "Refactor list_records to use util helpers"
```

---

### Task 5: Get-record endpoint — happy path test

**Files:**
- Create: `tests/test_routes_get_record.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_routes_get_record.py`:

```python
"""Tests for the get record endpoint."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from pyairtable.testing import fake_id

from airtable_proxy import app
from airtable_proxy.config import Config

BASE_ID = fake_id("app")
TABLE_ID = fake_id("tbl")
FLD_NAME = fake_id("fld")
FLD_AGE = fake_id("fld")
FLD_ACTIVE = fake_id("fld")
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


@pytest.fixture
def test_app(tmp_path):
    return app.create_app(config=make_config(tmp_path))


def populate_test_data(persistence):
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
        {FLD_NAME: "Bob", FLD_AGE: 25, FLD_ACTIVE: False},
        "2024-01-02T00:00:00.000Z",
    )


@pytest.fixture
def client_with_data(test_app):
    with TestClient(test_app) as client:
        populate_test_data(test_app.state.persistence)
        yield client, test_app.state.persistence


def test_returns_single_record(client_with_data):
    """GET /v0/{base}/{table}/{record} returns one record from local storage."""
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == REC_1
    assert data["createdTime"] == "2024-01-01T00:00:00.000Z"
    assert data["fields"]["Name"] == "Alice"
    assert data["fields"]["Age"] == 30
    assert data["fields"]["Active"] is True
    # Response is a single record object, not wrapped in {"records": [...]}
    assert "records" not in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_routes_get_record.py -v --no-cov`
Expected: FAIL — the catch-all proxy will attempt a real HTTP request and fail (or succeed against the proxy mock setup). Either way, `response.json()["id"] == REC_1` should fail because the real route does not exist yet.

- [ ] **Step 3: Create the new route module**

Create `src/airtable_proxy/routes/get_record.py`:

```python
"""
Get a single record from local storage, matching the Airtable API response format.
"""

from typing import Any

from fastapi import FastAPI, Request

from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.proxy import ProxyRequest
from airtable_proxy.util import format_record_fields, resolve_table_id


def add_routes(app: FastAPI) -> None:
    """
    Register get record routes on the FastAPI app.
    """

    @app.get("/v0/{base_id}/{table_id_or_name}/{record_id}")
    def get_record(
        request: Request,
        base_id: str,
        table_id_or_name: str,
        record_id: str,
        returnFieldsByFieldId: bool = False,
        cellFormat: str | None = None,
    ) -> dict[str, Any]:
        """
        Return a single record. Falls back to the proxy when local storage
        cannot satisfy the request.
        """
        if cellFormat == "string":
            raise ProxyRequest()

        persistence: AirtablePersistence = request.app.state.persistence

        table_id = resolve_table_id(base_id, table_id_or_name, persistence)
        if table_id is None:
            raise ProxyRequest()

        record = persistence.get_record(base_id, table_id, record_id)
        if record is None:
            raise ProxyRequest()

        field_info = persistence.get_fields(base_id, table_id)
        output_fields = format_record_fields(
            record,
            field_info,
            return_fields_by_field_id=returnFieldsByFieldId,
        )

        return {
            "id": record_id,
            "createdTime": record.created_time,
            "fields": output_fields,
        }
```

- [ ] **Step 4: Register the route in `app.py`**

Modify `src/airtable_proxy/app.py`. Update the routes import and add a registration call.

Change line 11 from:

```python
from airtable_proxy.routes import list_records
```

to:

```python
from airtable_proxy.routes import get_record, list_records
```

Then, immediately after the existing `list_records.add_routes(app)` line (line 46), add:

```python
    get_record.add_routes(app)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `poetry run pytest tests/test_routes_get_record.py::test_returns_single_record -v --no-cov`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/airtable_proxy/routes/get_record.py src/airtable_proxy/app.py tests/test_routes_get_record.py
git commit -m "Add get-record route — happy path"
```

---

### Task 6: Get-record — table name in URL

**Files:**
- Modify: `tests/test_routes_get_record.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes_get_record.py`:

```python
@pytest.mark.parametrize("table_id_or_name", [TABLE_ID, "Test Table", "Test%20Table"])
def test_returns_record_by_table_name(client_with_data, table_id_or_name):
    """The route accepts a table ID or table name (URL-encoded or not)."""
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{table_id_or_name}/{REC_1}")

    assert response.status_code == 200
    assert response.json()["id"] == REC_1
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `poetry run pytest tests/test_routes_get_record.py::test_returns_record_by_table_name -v --no-cov`
Expected: PASS — `resolve_table_id` already handles both forms; this test confirms it for the new route.

- [ ] **Step 3: Commit**

```bash
git add tests/test_routes_get_record.py
git commit -m "Test get-record by table name"
```

---

### Task 7: Get-record — `returnFieldsByFieldId` and empty-value omission

**Files:**
- Modify: `tests/test_routes_get_record.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes_get_record.py`:

```python
def test_returns_fields_by_name_by_default(client_with_data):
    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}")

    fields = response.json()["fields"]
    assert "Name" in fields
    assert "Age" in fields
    assert FLD_NAME not in fields


def test_return_fields_by_field_id_true(client_with_data):
    client, _ = client_with_data
    response = client.get(
        f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}?returnFieldsByFieldId=true"
    )

    fields = response.json()["fields"]
    assert FLD_NAME in fields
    assert FLD_AGE in fields
    assert "Name" not in fields
    assert fields[FLD_NAME] == "Alice"


def test_omits_empty_values(client_with_data):
    """Empty fields are omitted, matching Airtable's behavior."""
    client, persistence = client_with_data
    rec_empty = fake_id("rec")
    persistence.save_record(
        BASE_ID,
        TABLE_ID,
        rec_empty,
        {FLD_NAME: "", FLD_AGE: None, FLD_ACTIVE: False},
        "2024-01-04T00:00:00.000Z",
    )

    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}/{rec_empty}")

    assert response.status_code == 200
    assert response.json()["fields"] == {}
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `poetry run pytest tests/test_routes_get_record.py -v --no-cov`
Expected: PASS for all four tests so far.

- [ ] **Step 3: Commit**

```bash
git add tests/test_routes_get_record.py
git commit -m "Test get-record field formatting"
```

---

### Task 8: Get-record — proxy fallbacks

**Files:**
- Modify: `tests/test_routes_get_record.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_routes_get_record.py`:

```python
@patch("airtable_proxy.proxy.httpx.AsyncClient")
def test_proxy_when_cell_format_string(mock_client, client_with_data):
    """cellFormat=string forces a proxy to Airtable."""
    mock_response = httpx.Response(200, json={"id": REC_1, "fields": {}, "createdTime": "x"})
    mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.return_value.request = AsyncMock(return_value=mock_response)

    client, _ = client_with_data
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}/{REC_1}?cellFormat=string")

    assert response.status_code == 200
    mock_client.return_value.request.assert_called_once()


@patch("airtable_proxy.proxy.httpx.AsyncClient")
def test_proxy_when_table_not_in_local_storage(mock_client, test_app):
    """A table not in local storage falls through to the proxy."""
    mock_response = httpx.Response(200, json={"id": REC_1, "fields": {}, "createdTime": "x"})
    mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.return_value.request = AsyncMock(return_value=mock_response)

    with TestClient(test_app) as client:
        response = client.get(f"/v0/{BASE_ID}/UnknownTable/{REC_1}")

    assert response.status_code == 200
    mock_client.return_value.request.assert_called_once()


@patch("airtable_proxy.proxy.httpx.AsyncClient")
def test_proxy_when_record_not_in_local_storage(mock_client, client_with_data):
    """A record not in local storage falls through to the proxy."""
    mock_response = httpx.Response(200, json={"id": "recMissing", "fields": {}, "createdTime": "x"})
    mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
    mock_client.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_client.return_value.request = AsyncMock(return_value=mock_response)

    client, _ = client_with_data
    missing = fake_id("rec")
    response = client.get(f"/v0/{BASE_ID}/{TABLE_ID}/{missing}")

    assert response.status_code == 200
    mock_client.return_value.request.assert_called_once()
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `poetry run pytest tests/test_routes_get_record.py -v --no-cov`
Expected: PASS for all proxy-fallback tests. Each `mock_client.return_value.request.assert_called_once()` confirms we hit the proxy, not the local handler.

- [ ] **Step 3: Commit**

```bash
git add tests/test_routes_get_record.py
git commit -m "Test get-record proxy fallbacks"
```

---

### Task 9: Final verification — full test suite at 100% coverage

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite with coverage**

Run: `poetry run pytest`
Expected: All tests pass; coverage report shows 100% for the project (matches `--cov-fail-under=100`).

If coverage is below 100%:
- Check which lines in `src/airtable_proxy/util.py`, `src/airtable_proxy/routes/get_record.py`, or modified `list_records.py` are unreached.
- Add the smallest test that exercises that branch. Do not add untested defensive code.

- [ ] **Step 2: Run linters**

Run: `poetry run ruff check .` and `poetry run ruff format --check .`
Expected: PASS for both. If `ruff format --check` reports differences, run `poetry run ruff format .` and re-stage.

- [ ] **Step 3: Update TODO.md**

Modify `TODO.md` to check off the four lines under "Support [get record]" (lines 69-72):

```markdown
- [x] Support [get record](https://airtable.com/developers/web/api/get-record)
    - [x] implement `returnFieldsByFieldId`
    - [x] proxy to Airtable if `cellFormat=string`
    - [x] proxy to Airtable if record is missing from local storage
```

- [ ] **Step 4: Commit**

```bash
git add TODO.md
git commit -m "Mark get-record MVP item complete"
```
