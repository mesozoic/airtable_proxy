# README rewrite and combined-runner defaults

Status: draft, pending implementation
Author: design produced via brainstorming with the project owner

## Goal

Make airtable_proxy "dead simple" to set up for a new developer reading the README. Two coupled changes:

1. Rewrite the README so a new developer can go from clone to verifying a working proxy without consulting the source.
2. Restructure the CLI so `python -m airtable_proxy` runs both the API and the poller together by default, with `python -m airtable_proxy.server` and `python -m airtable_proxy.poller` available for finer control.

These were originally scoped as separate phases ("B" and "D") but collapsed into one because the README must describe the final CLI shape.

## Non-goals

- A `python -m airtable_proxy init` scaffolding command. Users can copy `config.yaml.example` and edit it.
- A `uvx airtable_proxy` one-shot install. Worth doing later as a packaging change; out of scope here.
- Production process management recommendations (supervisor, overmind, etc.). The combined runner covers dev; production users can use systemd/docker/whatever they prefer, and the README will say so in one line.
- Any change to authentication, persistence, or routing.

## Code changes

### 1. `src/airtable_proxy/config.py`

- `Config.bases` defaults to `{}`. A config without a `bases:` key now loads cleanly. With no bases, the poller has nothing to do; the API still proxies every `/v0/...` request through to Airtable using the caller's bearer token.
- New helper `resolve_config_path(explicit: Path | str | None) -> Path` that resolves in this order:
  1. `explicit` argument if provided
  2. `AIRTABLE_PROXY_CONFIG` env var
  3. `./config.yaml`
- New exception `ConfigNotFoundError(FileNotFoundError)` raised by `resolve_config_path` when the resolved path doesn't exist. Message:
  > Config file not found at '{path}'. Copy config.yaml.example to get started, or set AIRTABLE_PROXY_CONFIG to point at your config file.

### 2. `src/airtable_proxy/server.py` (new)

A standalone API server entry point. Click command that takes an optional config path and runs uvicorn. Logic mirrors today's `__main__.py`, but uses `resolve_config_path` and catches `ConfigNotFoundError` to print the friendly message and `sys.exit(1)`.

Invocation: `python -m airtable_proxy.server [CONFIG_PATH]`.

Host `0.0.0.0`, port `8000` — same defaults as today.

### 3. `src/airtable_proxy/poller.py`

- `main()`'s `config` argument becomes optional; uses `resolve_config_path` and the new exception path.
- No other behavior changes.

Invocation: `python -m airtable_proxy.poller [CONFIG_PATH]` (and `--once` still works).

### 4. `src/airtable_proxy/__main__.py`

Replaces the current "run uvicorn" body with a combined runner that starts both the API and the poller in a single asyncio event loop:

- Resolve config (with friendly error on miss).
- Call `poller.initialize(cfg)` synchronously to set up webhooks before serving.
- Run two tasks concurrently via `asyncio.gather`:
  - `uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000)).serve()`
  - `poller.run_polling_loop(cfg)`
- KeyboardInterrupt / SIGTERM cancels both tasks; uvicorn handles its own graceful shutdown via the cancelled-task path.

Single process, single event loop. The poller already wraps its blocking pyairtable + sqlite work in `asyncio.to_thread`, so it doesn't stall the API. Sqlite is in WAL mode (`storage.py`) so the poller's writes don't block API reads.

### Trade-offs

- **A crash in either subsystem brings down the other.** Acceptable: dev-mode users want fast feedback; prod users run `python -m airtable_proxy.server` and `python -m airtable_proxy.poller` separately under their own supervisor.
- **`bases: {}` default could mask config typos.** Mitigated by the existing `pydantic` strict-mode validation on the rest of the config; misnaming `bases:` as `base:` will fail loudly if pydantic strict mode rejects unknown keys (verify during implementation; if not, accept the trade — it's the same risk as today).

## README rewrite

Full structure (preserving the existing intro paragraph and mermaid diagram verbatim):

1. Title + intro
2. How it works (with diagram, "API" instead of "web server" labels)
3. **Requirements** — Python 3.13+, an Airtable account, a hostname you control (does not need to resolve yet, but Airtable will eventually POST webhook payloads to it; whoever controls the domain controls the data).
4. **Install** — `git clone && cd airtable_proxy && pip install -e .`. One-line note that this installs `pyairtable`, `fastapi`, `uvicorn`, `httpx`. Replaces the old "Dependencies" section.
5. **Get an Airtable personal access token** — short numbered list pointing at https://airtable.com/create/tokens; required scopes: `data.records:read`, `schema.bases:read`, `webhook:manage`. Note on finding base ID from the Airtable URL.
6. **Configure** — `cp config.yaml.example config.yaml`, walk through each key (one sentence each). Recommend `api_key: env(AIRTABLE_PROXY_API_KEY)` to keep the PAT out of the file. Note that `bases:` and `storage:` are optional.
7. **Run it**
   ```bash
   export AIRTABLE_PROXY_API_KEY=pat...
   python -m airtable_proxy
   ```
   Plus a "for finer control" subsection showing `python -m airtable_proxy.server` and `python -m airtable_proxy.poller` separately. One-line note that all three commands auto-discover `./config.yaml` and respect `AIRTABLE_PROXY_CONFIG`.
8. **Verify it's working** — `curl http://localhost:8000/health` with expected JSON, then `curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/v0/<baseId>/<table>`.
9. **Contributing** — `poetry install`, `mypy --strict && pytest`, `pre-commit run`, integration test invocation (`dotenv -f tmp/integration.sh run -- pytest -k integration`).

## Tests

Per project TDD discipline (CLAUDE.md): write tests first, get sign-off, make them pass. New tests follow project conventions — no type annotations, `@patch` decorator, import the module not its members.

### New tests

**`tests/test_config.py`** additions:
- `test_load_config_bases_defaults_to_empty` — config without `bases:` loads, `cfg.bases == {}`
- `test_resolve_config_path_explicit`
- `test_resolve_config_path_env_var`
- `test_resolve_config_path_default`
- `test_resolve_config_path_missing_raises` — non-existent path → `ConfigNotFoundError` with helpful message

**`tests/test_poller.py`** additions (Click `CliRunner`):
- `test_main_uses_explicit_config_arg`
- `test_main_uses_env_var_when_no_arg`
- `test_main_falls_back_to_default_config_yaml`
- `test_main_friendly_error_when_config_missing`

**`tests/test_server.py`** (new file):
- `test_main_runs_uvicorn` — mocks `uvicorn` and `create_app`; asserts host `0.0.0.0`, port `8000`
- `test_main_uses_explicit_config_arg`
- `test_main_uses_env_var_when_no_arg`
- `test_main_falls_back_to_default_config_yaml`
- `test_main_friendly_error_when_config_missing`

**`tests/test_main.py`** (replaces existing tests):
- `test_main_runs_server_and_poller` — mocks `run_polling_loop`, `initialize`, `uvicorn.Server.serve`; asserts both awaited inside `asyncio.gather`
- `test_main_calls_initialize_before_loop`
- `test_main_friendly_error_when_config_missing`

### Existing tests changed

- `tests/test_config.py::test_load_config_missing_bases` — currently asserts `ValidationError`; replaced by `test_load_config_bases_defaults_to_empty`.
- Both tests in `tests/test_main.py` — obsolete; replaced as listed above.

Both changes pre-approved by user.

## Risks

- **Existing users invoking `python -m airtable_proxy` to run only the API silently get the poller too.** Pre-1.0; the README is the source of truth for the CLI shape.
- **Combined runner masks production concerns.** Mitigated by the README explicitly recommending the split-process invocations for production and by the fact that the split commands continue to exist.

## Open questions

None at design time. Implementation may surface uvicorn programmatic-API quirks (signal handling, lifespan integration) — handle inline if they come up.
