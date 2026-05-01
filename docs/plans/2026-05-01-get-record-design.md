# Get Record Endpoint — Design

## Goal

Implement the [get record](https://airtable.com/developers/web/api/get-record)
endpoint locally, completing one of the two remaining MVP items in `TODO.md`.

The endpoint serves a single record from local storage when possible, and falls
back to proxying the request to Airtable when local storage cannot satisfy the
request.

## Scope

In scope:

- New route: `GET /v0/{base_id}/{table_id_or_name}/{record_id}`
- Query parameter `returnFieldsByFieldId` (handled locally)
- Proxy to Airtable when `cellFormat=string`
- Proxy to Airtable when the table is not in local storage
- Proxy to Airtable when the record is not in local storage
- Refactor: extract the helpers shared with `list_records` into
  `airtable_proxy.util`

Out of scope (deferred):

- `timeZone` and `userLocale` query parameters
- A locally-generated 404 for missing records (we always proxy, matching the
  TODO entry)

## Behavior

The handler runs the following checks, raising `ProxyRequest` to fall through
to the catch-all proxy whenever a check fails:

1. If `cellFormat == "string"`, proxy.
2. Resolve `table_id_or_name` to a table ID via the existing helper. If the
   table is not in local storage, proxy.
3. Load the record with `persistence.get_record(base_id, table_id, record_id)`.
   If `None`, proxy.
4. Build the `fields` dictionary, omitting empty values and keying by field ID
   when `returnFieldsByFieldId` is true (otherwise by field name, falling back
   to field ID if a name is not known).
5. Return a single-record response shaped like Airtable's:
   ```json
   {
     "id": "rec...",
     "createdTime": "2024-01-01T00:00:00.000Z",
     "fields": { ... }
   }
   ```

Note: this shape differs from `list_records`, which wraps results in
`{"records": [...]}`.

## Refactor: shared helpers

`list_records.py` currently defines two helpers and an inline field-formatting
block that the get-record route also needs. Extract them to a new module
`src/airtable_proxy/util.py`:

- `resolve_table_id(base_id, table_id_or_name, persistence) -> str | None`
- `is_empty_value(value) -> bool`
- `format_record_fields(record_info, field_info, *, return_fields_by_field_id) -> dict[str, Any]`

`list_records.py` is updated to import from `airtable_proxy.util`. No behavior
change to the list endpoint.

The `format_record_fields` helper takes the field-info mapping as an argument
(rather than re-fetching it per record) so callers handling many records can
fetch it once.

## Module layout

```
src/airtable_proxy/
    util.py            # NEW
    routes/
        list_records.py     # imports helpers from util
        get_record.py       # NEW
    app.py             # registers get_record.add_routes(app)
```

The new route follows the same `add_routes(app)` pattern as `list_records`.

## Tests

New file `tests/test_routes_get_record.py`. Reuse the test-data fixture pattern
from `tests/test_routes_list_records.py` (same `BASE_ID`, `TABLE_ID`, fields,
records).

Cases:

- `test_returns_record_by_table_id`
- `test_returns_record_by_table_name` (with and without URL-encoded space)
- `test_returns_fields_by_name_by_default`
- `test_return_fields_by_field_id_true`
- `test_omits_empty_values`
- `test_proxy_when_cell_format_string`
- `test_proxy_when_table_not_in_local_storage`
- `test_proxy_when_record_not_in_local_storage`

The proxy-condition tests follow the same `httpx.AsyncClient` mocking pattern
already used in `test_routes_list_records.py`.

The existing list-records tests must continue to pass after the helper
refactor.

## Risks

- The shared helpers' signatures are public-ish within the package, so any
  small mistake during the refactor could affect list-records. Mitigated by
  running the existing test suite after the move and before adding new code.
- The catch-all `/v0/{path:path}` route is registered in `app.py`. FastAPI
  matches more specific routes first, so the new path-with-record-id route
  needs to be registered before the catch-all (it already is, by virtue of
  being registered inside `add_routes`, which runs before the catch-all
  declaration). Verified by inspection of `app.py`.
