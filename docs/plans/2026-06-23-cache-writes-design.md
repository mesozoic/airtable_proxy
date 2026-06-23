# Cache Writes After Mutations — Design

## Goal

Implement the first item in the `0.2` section of `TODO.md`: update the local
cache after POST/PUT/PATCH/DELETE operations succeed at Airtable, so that
reads against the proxy reflect the write within the same request instead of
having to wait for the webhook poller to catch up.

Without this, a client that does `POST` followed by `GET` against the proxy
may see stale data for up to one poll interval (~1s plus payload processing).

## Scope

In scope:

- Record-level mutations under `/v0/{base_id}/{table_id_or_name}` and
  `/v0/{base_id}/{table_id_or_name}/{record_id}`:
    - `POST` (create one or many)
    - `PATCH` (update one or many, including `performUpsert`)
    - `PUT` (replace one or many, including `performUpsert`)
    - `DELETE` (single via path, multi via `records[]` query)
- Translate response field names to field IDs using the cached field metadata.
- Honor `returnFieldsByFieldId=true` (response already in field-ID form).
- Refactor: split `proxy.proxy_to_airtable` into `forward()` and
  `response_from_httpx()` so the new route handlers can read the response
  body before returning it.

Out of scope (deferred):

- Metadata mutations under `/v0/meta/...` (table/field create/edit/delete).
  These are part of the `0.4` work which also pulls in the get-base-schema
  endpoint.
- Locally generated responses for writes; we always forward to Airtable.
- Authentication on the mutation routes (Airtable rejects bad tokens with
  4xx, in which case we skip the cache write).

## Behavior

For each mutation route the handler runs:

1. `table_id = resolve_table_id(base_id, table_id_or_name, persistence)`.
   If `None`, `raise ProxyRequest` — the catch-all handles it without cache
   side effects.
2. Forward the request via the shared `forward(request, path)` helper, which
   returns an `httpx.Response`.
3. If the status is not 2xx, return `response_from_httpx(...)` immediately.
   No cache write.
4. If the status is 2xx, parse the response body as JSON. If the body is
   missing or not JSON, log a warning and skip the cache write (still return
   success to the client — Airtable accepted the write).
5. Call the matching `cache_writes.apply_*` function with the parsed body,
   the `returnFieldsByFieldId` flag from the query string, and the resolved
   `base_id` / `table_id`. Storage errors from inside `apply_*` propagate —
   those represent bugs, not Airtable-side outcomes.
6. Return `response_from_httpx(response)` so the client sees Airtable's
   response byte-for-byte.

If any cache-writes work raises a known shape mismatch (`KeyError`,
`pydantic.ValidationError`), the handler logs a warning and returns Airtable's
response. The webhook poller will reconcile within the next poll cycle.

### Route → cache_writes dispatch

| Route                                   | Method | `cache_writes` call             |
| --------------------------------------- | ------ | ------------------------------- |
| `/v0/{base}/{table}`                    | POST   | `apply_create`                  |
| `/v0/{base}/{table}`                    | PATCH  | `apply_update`                  |
| `/v0/{base}/{table}`                    | PUT    | `apply_update(..., replace=True)` |
| `/v0/{base}/{table}/{record}`           | PATCH  | `apply_update`                  |
| `/v0/{base}/{table}/{record}`           | PUT    | `apply_update(..., replace=True)` |
| `/v0/{base}/{table}`                    | DELETE | `apply_delete`                  |
| `/v0/{base}/{table}/{record}`           | DELETE | `apply_delete`                  |

The catch-all `/v0/{path:path}` continues to handle everything else
(metadata API, future verbs, malformed requests).

## `cache_writes.py`

A new module of pure functions that owns Airtable response-shape knowledge.
No HTTP imports, no FastAPI imports, no `request` parameter.

```
apply_create(persistence, base_id, table_id, body, *, response_uses_field_ids)
apply_update(persistence, base_id, table_id, body, *, response_uses_field_ids, replace=False)
apply_delete(persistence, base_id, table_id, body)
```

Behavior notes:

- **Response normalization.** Single-record (`{id, createdTime, fields}`) and
  multi-record (`{records: [...]}`) shapes are normalized to a list up front.
  Upsert responses carry the post-state of each record in the `records`
  array; we ignore the `createdRecords` / `updatedRecords` index arrays.
- **Field key translation.** When `response_uses_field_ids` is true the keys
  are already field IDs and we save them as-is. Otherwise we look up
  `persistence.get_fields(base_id, table_id)` once per call and translate
  name → ID. Any name we cannot resolve is skipped with `logger.debug`; the
  webhook poller will fill it in.
- **PATCH semantics.** `apply_update` with `replace=False` (default) loads
  the existing record, merges its fields with the response fields, then
  saves. Mirrors the merge the webhook poller already does in
  `process_payload` for `changed_records_by_id`.
- **PUT semantics.** `apply_update(..., replace=True)` saves the response
  fields as the complete field set, clobbering any cached fields the
  response omits.
- **POST semantics.** `apply_create` always saves the response fields as-is.
- **DELETE semantics.** `apply_delete` calls `persistence.delete_record` for
  every record in the body. Handles both `{id, deleted: true}` and
  `{records: [{id, deleted: true}, ...]}` shapes.

### Assumption to verify

The design assumes Airtable's PATCH responses return the **full** post-update
record state (not just the changed fields). The integration tests below
verify this empirically. If they fail, `apply_update` already merges with the
existing record on the default path, so PATCH semantics remain correct; only
the `replace=True` path would need extra care, and PUT bodies typically
include every field anyway.

## Refactor: `proxy.py`

Today `proxy.proxy_to_airtable(request, path)` does both the httpx call and
the FastAPI `Response` build. Split it:

```python
async def forward(request: Request, path: str) -> httpx.Response: ...

def response_from_httpx(response: httpx.Response) -> Response: ...

async def proxy_to_airtable(request: Request, path: str) -> Response:
    return response_from_httpx(await forward(request, path))
```

`proxy_to_airtable` keeps its existing signature so `app.handle_proxy_request`
and `app.proxy_v0` don't change. The new mutation routes call `forward()`
directly so they can inspect the parsed JSON before deciding whether to
update the cache.

## Module layout

```
src/airtable_proxy/
    proxy.py                       # REFACTOR: forward + response_from_httpx
    cache_writes.py                # NEW
    routes/
        list_records.py            # unchanged
        get_record.py              # unchanged
        create_records.py          # NEW
        update_records.py          # NEW
        delete_records.py          # NEW
    app.py                         # register the three new add_routes(app)
```

Route registration order in `create_app` puts the new modules before the
catch-all `proxy_v0` declaration, matching `list_records` / `get_record`.

## Tests

Per `AGENTS.md` testing conventions: TDD throughout, ask before writing or
changing each test file, no type annotations in test files, prefer `@patch`
decorators, import the module under test.

### Unit tests (run with `pytest`)

`tests/test_cache_writes.py`:

- `apply_create` with single-record response shape
- `apply_create` with multi-record response shape
- `apply_create` with upsert response (records array drives caching;
  `createdRecords`/`updatedRecords` ignored)
- `apply_update` PATCH semantics merges with existing fields
- `apply_update` with `replace=True` clears unspecified fields
- `apply_update` for a record not yet in cache treats as create
- `apply_delete` single-record shape
- `apply_delete` multi-record shape
- Field-name → ID translation when `response_uses_field_ids=False`
- Field-ID pass-through when `response_uses_field_ids=True`
- Unknown field name in response is skipped; other fields still cached

`tests/test_routes_create_records.py`, `tests/test_routes_update_records.py`,
`tests/test_routes_delete_records.py`:

- Happy path: forwards correctly, calls correct `apply_*`, returns Airtable
  response
- Non-2xx response → no `apply_*` call, response passed through
- Unknown table → `raise ProxyRequest`, catch-all handles it
- `returnFieldsByFieldId=true` propagates to `apply_*`
- `apply_*` raises a known shape error → warning logged, success returned

`tests/test_proxy.py` (new): cover the `forward` / `response_from_httpx`
split so the refactor is verifiable independent of any route handler.

### Integration tests (run with `dotenv -f tmp/integration.sh run -- pytest -k integration`)

`tests/integration/itest_routes_create_records.py`,
`tests/integration/itest_routes_update_records.py`,
`tests/integration/itest_routes_delete_records.py`:

- POST → read back via list/get → cached fields match response
- PATCH → read back → updated fields reflected, untouched fields preserved
- PUT → read back → omitted fields cleared (verifies replace semantics)
- DELETE → read back → record gone from cache
- PATCH "full post-state" assumption verified by setting field A, leaving
  field B untouched, PATCHing field A, and checking field B in the cache.

## Risks

- **Race with the webhook poller.** Both paths call
  `persistence.save_record`. SQLite serializes writes, so last-write-wins
  per record is fine. The poller advances its cursor independently and is
  idempotent against the same record state.
- **Response shape drift.** Airtable could change its response shape. The
  defensive validation in `cache_writes` (skip on missing keys, log on
  unknown fields) keeps a shape change from breaking the proxy — the webhook
  poller would still bring the cache up to date. Failures during the
  transition would show up as `logger.warning` lines, not 5xx responses.
- **Catch-all ordering.** New routes must register before
  `proxy_v0`; otherwise `/v0/{path:path}` swallows them. Same constraint
  `list_records` and `get_record` already work around; verified by mirroring
  their `add_routes(app)` calls in `create_app`.
- **PATCH-returns-partial-state.** If the assumption above is wrong for some
  field types, PUT replace would clobber fields the response omitted. PATCH
  merge is already safe. Integration tests catch this.
