# Authentication Design

## Scope

Authentication applies only to routes served from local storage (e.g.
`list_records`, `get_record`). The catch-all proxy route and `/health`
have no auth check — Airtable validates tokens on proxied requests
directly.

## Flow

1. Extract `Authorization: Bearer <token>` from the request.
2. If no header is present, return 401.
3. Hash the token with SHA-256.
4. Check local storage for key `auth:{base_id}:{token_hash}`.
5. If found, allow the request.
6. If not found, pick any table from local storage for the base
   and hit Airtable's list-records endpoint with `maxRecords=1`
   using the caller's bearer token.
   - If Airtable returns success, store the hash and allow the request.
   - If Airtable returns an error, return 403.

## Implementation

New module: `src/airtable_proxy/auth.py`

Auth check function:

```python
async def require_auth(request, base_id, persistence, config) -> None
```

- Extracts the bearer token from the `Authorization` header.
- Hashes with SHA-256.
- Checks `persistence` for `auth:{base_id}:{token_hash}`.
- On cache miss, picks a table from local storage for the base
  and hits `GET https://api.airtable.com/v0/{base_id}/{table_id}?maxRecords=1`
  using the caller's token.
- Stores the hash on success; raises 403 on failure.

Each route handler that serves from cache calls `require_auth()` early
in the function body, before doing any work. No middleware is needed
because auth only applies to specific cached routes and requires a
`base_id`.

Storage uses the existing `AirtablePersistence` layer with key pattern
`auth:{base_id}:{token_hash}` storing a simple truthy value.

## Edge Cases

- **No tables in local storage for a base:** Raise `ProxyRequest` to
  fall through to Airtable. This is consistent with the existing
  behavior when a table is missing from local storage.
- **Token hash eviction:** No expiry for MVP. Hashes persist until
  the database is cleared.

## Testing

Unit tests in `tests/test_auth.py`:

- Token present and hash found in storage -> allow
- Token present, hash miss, Airtable returns 200 -> store hash, allow
- Token present, hash miss, Airtable returns 401/403 -> return 403
- No Authorization header -> return 401
- No tables in local storage for base -> raise ProxyRequest

Integration with `list_records` in `tests/test_routes_list_records.py`:

- Existing tests updated to include a pre-stored auth hash.
- New test for rejected token.
