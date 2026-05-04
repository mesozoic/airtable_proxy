# README rewrite and combined-runner CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make airtable_proxy dead-simple to set up — restructure the CLI so `python -m airtable_proxy` runs both the API server and the poller together, expose `python -m airtable_proxy.server` and `python -m airtable_proxy.poller` for finer control, and rewrite the README so a new developer can clone, install, configure, and verify without reading source.

**Architecture:** A new `resolve_config_path(...)` helper in `config.py` centralises the (explicit arg → `AIRTABLE_PROXY_CONFIG` → `./config.yaml`) precedence and raises a friendly `ConfigNotFoundError` on miss. A new `server.py` module hosts the API-only entry point (Click command). `__main__.py` becomes the combined runner: it calls `poller.initialize` synchronously, then runs `uvicorn.Server.serve()` and `poller.run_polling_loop()` concurrently via `asyncio.gather` in a single event loop. `Config.bases` defaults to `{}` so a config without bases boots cleanly in proxy-only mode.

**Tech Stack:** Python 3.13, FastAPI, uvicorn, Click, pytest, `pytest-httpx`, `requests-mock`, `pyairtable.testing` (already in use).

**Spec:** `docs/plans/2026-05-04-readme-and-defaults-design.md`

**Coverage requirement:** The project enforces `--cov-fail-under=100` in `pyproject.toml`. Every line of new code must be exercised by tests.

**Test conventions (from `.claude/CLAUDE.md`):**
- Tests do not use type annotations.
- Use `@patch` decorator, not `with patch(...)`.
- Import the module under test (`from airtable_proxy import config`), not its members.
- Always ask the user before adding or changing tests — for this plan, the user pre-approved the test list in the design doc.

---

### Task 1: Add `resolve_config_path` + `ConfigNotFoundError` to `config.py`

**Files:**
- Modify: `src/airtable_proxy/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_resolve_config_path_explicit(tmp_path):
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("hostname: x\n")
    assert config.resolve_config_path(explicit) == explicit


def test_resolve_config_path_explicit_str(tmp_path):
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("hostname: x\n")
    assert config.resolve_config_path(str(explicit)) == explicit


def test_resolve_config_path_env_var(tmp_path, monkeypatch):
    target = tmp_path / "from-env.yaml"
    target.write_text("hostname: x\n")
    monkeypatch.setenv("AIRTABLE_PROXY_CONFIG", str(target))
    assert config.resolve_config_path(None) == target


def test_resolve_config_path_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AIRTABLE_PROXY_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("hostname: x\n")
    assert config.resolve_config_path(None) == Path("config.yaml")


def test_resolve_config_path_missing_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("AIRTABLE_PROXY_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(config.ConfigNotFoundError) as exc_info:
        config.resolve_config_path(None)
    msg = str(exc_info.value)
    assert "config.yaml" in msg
    assert "config.yaml.example" in msg
    assert "AIRTABLE_PROXY_CONFIG" in msg


def test_resolve_config_path_explicit_missing_raises(tmp_path):
    missing = tmp_path / "nope.yaml"
    with pytest.raises(config.ConfigNotFoundError) as exc_info:
        config.resolve_config_path(missing)
    assert str(missing) in str(exc_info.value)


def test_config_not_found_error_is_filenotfounderror():
    assert issubclass(config.ConfigNotFoundError, FileNotFoundError)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_config.py -v --no-cov`
Expected: FAIL with `AttributeError: module 'airtable_proxy.config' has no attribute 'resolve_config_path'` (or `ConfigNotFoundError`).

- [ ] **Step 3: Implement `resolve_config_path` and `ConfigNotFoundError`**

Edit `src/airtable_proxy/config.py`. Add at module level (after the existing imports, before `class BaseConfig`):

```python
class ConfigNotFoundError(FileNotFoundError):
    """
    Raised when the config file cannot be located.
    """


def resolve_config_path(explicit: Path | str | None) -> Path:
    """
    Resolve the config file path.

    Precedence: explicit argument, then ``AIRTABLE_PROXY_CONFIG`` env var,
    then ``./config.yaml``. Raises ``ConfigNotFoundError`` if the resolved
    path does not exist.
    """
    if explicit is not None:
        path = Path(explicit)
    elif env_path := os.environ.get("AIRTABLE_PROXY_CONFIG"):
        path = Path(env_path)
    else:
        path = Path("config.yaml")

    if not path.exists():
        raise ConfigNotFoundError(
            f"Config file not found at '{path}'. "
            f"Copy config.yaml.example to get started, or set "
            f"AIRTABLE_PROXY_CONFIG to point at your config file."
        )
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/test_config.py -v --no-cov`
Expected: PASS, all tests including the seven new ones.

- [ ] **Step 5: Run mypy to confirm types**

Run: `poetry run mypy --strict src/airtable_proxy/config.py`
Expected: `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add src/airtable_proxy/config.py tests/test_config.py
git commit -m "Add resolve_config_path helper and ConfigNotFoundError"
```

---

### Task 2: Make `Config.bases` default to `{}`

**Files:**
- Modify: `src/airtable_proxy/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Replace the existing test that asserts `bases` is required**

In `tests/test_config.py`, find this block:

```python
def test_load_config_missing_bases():
    with pytest.raises(ValidationError) as exc_info:
        config.load_config({"hostname": "airtable-proxy.example.com"})
    assert "bases" in str(exc_info.value)
```

Replace it with:

```python
def test_load_config_bases_defaults_to_empty():
    cfg = config.load_config({"hostname": "airtable-proxy.example.com"})
    assert cfg.bases == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `poetry run pytest tests/test_config.py::test_load_config_bases_defaults_to_empty -v --no-cov`
Expected: FAIL — pydantic raises `ValidationError` because `bases` is currently required.

- [ ] **Step 3: Make `bases` default to `{}`**

Edit `src/airtable_proxy/config.py`. Change the `Config` class:

```python
class Config(BaseModel):
    hostname: str
    bases: dict[str, BaseConfig] = {}
    storage: StorageConfig = StorageConfig()
```

- [ ] **Step 4: Run the new test and the full config suite**

Run: `poetry run pytest tests/test_config.py -v --no-cov`
Expected: PASS, all tests.

- [ ] **Step 5: Sanity-check the rest of the codebase still loads**

Run: `poetry run pytest --no-cov`
Expected: PASS, full suite.

- [ ] **Step 6: Commit**

```bash
git add src/airtable_proxy/config.py tests/test_config.py
git commit -m "Default Config.bases to empty dict"
```

---

### Task 3: Update `poller.py` to use `resolve_config_path`

**Files:**
- Modify: `src/airtable_proxy/poller.py`
- Modify: `tests/test_poller.py`

- [ ] **Step 1: Write failing tests for the new CLI behaviour**

Append to `tests/test_poller.py`:

```python
@patch("airtable_proxy.poller.initialize")
def test_main_uses_explicit_config_arg(mock_init, tmp_path):
    config_file = tmp_path / "explicit.yaml"
    config_file.write_text("hostname: test.example.com\nbases: {}\n")

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, [str(config_file), "--once"])
    assert result.exit_code == 0
    mock_init.assert_called_once()


@patch("airtable_proxy.poller.initialize")
def test_main_uses_env_var_when_no_arg(mock_init, tmp_path, monkeypatch):
    config_file = tmp_path / "from-env.yaml"
    config_file.write_text("hostname: test.example.com\nbases: {}\n")
    monkeypatch.setenv("AIRTABLE_PROXY_CONFIG", str(config_file))

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, ["--once"])
    assert result.exit_code == 0
    mock_init.assert_called_once()


@patch("airtable_proxy.poller.initialize")
def test_main_falls_back_to_default_config_yaml(mock_init, tmp_path, monkeypatch):
    monkeypatch.delenv("AIRTABLE_PROXY_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("hostname: test.example.com\nbases: {}\n")

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, ["--once"])
    assert result.exit_code == 0
    mock_init.assert_called_once()


def test_main_friendly_error_when_config_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("AIRTABLE_PROXY_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, [])
    assert result.exit_code == 1
    assert "config.yaml.example" in result.output
```

Also update the existing `test_main_once` and `test_main_without_once_runs_polling` tests so they no longer rely on `load_config_from_file` being patched directly. Find this block at the bottom of `tests/test_poller.py`:

```python
@patch("airtable_proxy.poller.initialize")
@patch("airtable_proxy.poller.load_config_from_file")
def test_main_once(mock_load, mock_init, tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("hostname: test\nbases: {}\nstorage:\n  sqlite: /tmp/test.db\n")
    mock_load.return_value = MagicMock()

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, [str(config_file), "--once"])
    assert result.exit_code == 0
    mock_init.assert_called_once()


@patch("airtable_proxy.poller.asyncio.run")
@patch("airtable_proxy.poller.load_config_from_file")
@patch("airtable_proxy.poller.initialize")
def test_main_without_once_runs_polling(_mock_init, mock_load, mock_asyncio_run, tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("hostname: test\nbases: {}\nstorage:\n  sqlite: /tmp/test.db\n")
    mock_load.return_value = MagicMock()

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, [str(config_file)])
    assert result.exit_code == 0
    mock_asyncio_run.assert_called_once()
    # Close the coroutine to avoid "was never awaited" warning
    mock_asyncio_run.call_args[0][0].close()
```

Replace with:

```python
@patch("airtable_proxy.poller.initialize")
def test_main_once(mock_init, tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"hostname: test.example.com\nbases: {{}}\nstorage:\n  sqlite: {tmp_path / 'test.db'}\n"
    )

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, [str(config_file), "--once"])
    assert result.exit_code == 0
    mock_init.assert_called_once()


@patch("airtable_proxy.poller.asyncio.run")
@patch("airtable_proxy.poller.initialize")
def test_main_without_once_runs_polling(_mock_init, mock_asyncio_run, tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        f"hostname: test.example.com\nbases: {{}}\nstorage:\n  sqlite: {tmp_path / 'test.db'}\n"
    )

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(poller.main, [str(config_file)])
    assert result.exit_code == 0
    mock_asyncio_run.assert_called_once()
    mock_asyncio_run.call_args[0][0].close()
```

Why the changes: the existing tests bypass `load_config_from_file` entirely with a mock, but the new CLI flow needs to actually resolve the path. Writing real (tiny) config files keeps the path-resolution logic exercised.

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `poetry run pytest tests/test_poller.py -v --no-cov -k "test_main_"`
Expected: FAIL — `test_main_uses_env_var_when_no_arg`, `test_main_falls_back_to_default_config_yaml`, and `test_main_friendly_error_when_config_missing` fail because Click currently requires the `config` argument (`exists=True`).

- [ ] **Step 3: Update `poller.main` to use `resolve_config_path`**

Edit `src/airtable_proxy/poller.py`. Replace the existing `main` function (currently:

```python
@click.command()
@click.argument("config", type=click.Path(exists=True))
@click.option("--once", is_flag=True, help="Run once and exit (for testing)")
def main(config: str, once: bool = False) -> None:
    """
    Initialize and poll Airtable webhooks.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config_from_file(config)
    initialize(cfg)

    if not once:
        asyncio.run(run_polling_loop(cfg))
```

) with:

```python
@click.command()
@click.argument("config", type=click.Path(), required=False)
@click.option("--once", is_flag=True, help="Run once and exit (for testing)")
def main(config: str | None = None, once: bool = False) -> None:
    """
    Initialize and poll Airtable webhooks.

    If CONFIG is omitted, looks for AIRTABLE_PROXY_CONFIG, then ./config.yaml.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config_path = resolve_config_path(config)
    except ConfigNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    cfg = load_config_from_file(config_path)
    initialize(cfg)

    if not once:
        asyncio.run(run_polling_loop(cfg))
```

Add the missing imports at the top of `poller.py`. The existing import block looks like:

```python
import asyncio
import logging
from typing import Any

import click
from pyairtable import Api, Base
from pyairtable.models.webhook import Webhook, WebhookPayload

from airtable_proxy.config import BaseConfig, Config, load_config, load_config_from_file
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage
```

Add `import sys` and extend the config import:

```python
import asyncio
import logging
import sys
from typing import Any

import click
from pyairtable import Api, Base
from pyairtable.models.webhook import Webhook, WebhookPayload

from airtable_proxy.config import (
    BaseConfig,
    Config,
    ConfigNotFoundError,
    load_config,
    load_config_from_file,
    resolve_config_path,
)
from airtable_proxy.persistence import AirtablePersistence
from airtable_proxy.storage import Storage
```

- [ ] **Step 4: Run the poller tests**

Run: `poetry run pytest tests/test_poller.py -v --no-cov`
Expected: PASS, all tests.

- [ ] **Step 5: Run the full suite to confirm nothing else broke**

Run: `poetry run pytest --no-cov`
Expected: PASS.

- [ ] **Step 6: Run mypy**

Run: `poetry run mypy --strict src/airtable_proxy/`
Expected: `Success: no issues found`.

- [ ] **Step 7: Commit**

```bash
git add src/airtable_proxy/poller.py tests/test_poller.py
git commit -m "Auto-discover config path in poller CLI"
```

---

### Task 4: Extract API server into `src/airtable_proxy/server.py`

**Files:**
- Create: `src/airtable_proxy/server.py`
- Create: `tests/test_server.py`

This task creates the standalone API entry point. `__main__.py` is left alone for now — Task 5 rewrites it as the combined runner.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from airtable_proxy import server


@patch("airtable_proxy.server.uvicorn")
@patch("airtable_proxy.server.create_app")
def test_main_runs_uvicorn(mock_create_app, mock_uvicorn, tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("hostname: test.example.com\n")
    mock_create_app.return_value = MagicMock()

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(server.main, [str(config_file)])
    assert result.exit_code == 0, result.output
    mock_uvicorn.run.assert_called_once()
    args, kwargs = mock_uvicorn.run.call_args
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8000


@patch("airtable_proxy.server.uvicorn")
@patch("airtable_proxy.server.create_app")
def test_main_uses_explicit_config_arg(mock_create_app, _mock_uvicorn, tmp_path):
    config_file = tmp_path / "explicit.yaml"
    config_file.write_text("hostname: test.example.com\n")
    mock_create_app.return_value = MagicMock()

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(server.main, [str(config_file)])
    assert result.exit_code == 0


@patch("airtable_proxy.server.uvicorn")
@patch("airtable_proxy.server.create_app")
def test_main_uses_env_var_when_no_arg(
    mock_create_app, _mock_uvicorn, tmp_path, monkeypatch
):
    config_file = tmp_path / "from-env.yaml"
    config_file.write_text("hostname: test.example.com\n")
    monkeypatch.setenv("AIRTABLE_PROXY_CONFIG", str(config_file))
    mock_create_app.return_value = MagicMock()

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(server.main, [])
    assert result.exit_code == 0


@patch("airtable_proxy.server.uvicorn")
@patch("airtable_proxy.server.create_app")
def test_main_falls_back_to_default_config_yaml(
    mock_create_app, _mock_uvicorn, tmp_path, monkeypatch
):
    monkeypatch.delenv("AIRTABLE_PROXY_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("hostname: test.example.com\n")
    mock_create_app.return_value = MagicMock()

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(server.main, [])
    assert result.exit_code == 0


def test_main_friendly_error_when_config_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("AIRTABLE_PROXY_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(server.main, [])
    assert result.exit_code == 1
    assert "config.yaml.example" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest tests/test_server.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'airtable_proxy.server'`.

- [ ] **Step 3: Implement `server.py`**

Create `src/airtable_proxy/server.py`:

```python
import sys

import click
import uvicorn

from airtable_proxy.app import create_app
from airtable_proxy.config import (
    ConfigNotFoundError,
    load_config_from_file,
    resolve_config_path,
)


@click.command()
@click.argument("config", type=click.Path(), required=False)
def main(config: str | None = None) -> None:
    """
    Run the airtable_proxy API server.

    If CONFIG is omitted, looks for AIRTABLE_PROXY_CONFIG, then ./config.yaml.
    """
    try:
        config_path = resolve_config_path(config)
    except ConfigNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    cfg = load_config_from_file(config_path)
    app = create_app(cfg)
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `poetry run pytest tests/test_server.py -v --no-cov`
Expected: PASS, 5 tests.

- [ ] **Step 5: Run mypy**

Run: `poetry run mypy --strict src/airtable_proxy/server.py`
Expected: `Success: no issues found`.

- [ ] **Step 6: Run the full suite**

Run: `poetry run pytest --no-cov`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/airtable_proxy/server.py tests/test_server.py
git commit -m "Add airtable_proxy.server entry point"
```

---

### Task 5: Rewrite `__main__.py` as the combined runner

**Files:**
- Modify: `src/airtable_proxy/__main__.py`
- Modify (replace contents): `tests/test_main.py`

- [ ] **Step 1: Replace `tests/test_main.py` with the new test list**

Per CLAUDE.md, this replaces existing tests — pre-approved by the user in the design doc. Overwrite `tests/test_main.py` with:

```python
from unittest.mock import MagicMock, patch

import pytest

from airtable_proxy import __main__ as main_module


@patch("airtable_proxy.__main__.asyncio.run")
@patch("airtable_proxy.__main__.poller")
def test_main_calls_initialize_before_running_loop(mock_poller, mock_asyncio_run, tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("hostname: test.example.com\n")
    call_order = []
    mock_poller.initialize.side_effect = lambda cfg: call_order.append("initialize")
    mock_asyncio_run.side_effect = lambda coro: (call_order.append("run"), coro.close())

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(main_module.main, [str(config_file)])
    assert result.exit_code == 0, result.output
    assert call_order == ["initialize", "run"]


@patch("airtable_proxy.__main__.run_polling_loop")
@patch("airtable_proxy.__main__.uvicorn")
@patch("airtable_proxy.__main__.create_app")
def test_serve_and_poll_runs_uvicorn_and_polling(
    mock_create_app, mock_uvicorn, mock_run_polling_loop
):
    import asyncio

    mock_create_app.return_value = MagicMock()

    server_instance = MagicMock()

    async def fake_serve():
        return None

    server_instance.serve = fake_serve
    mock_uvicorn.Server.return_value = server_instance

    async def fake_run_polling_loop(cfg):
        return None

    mock_run_polling_loop.side_effect = fake_run_polling_loop

    asyncio.run(main_module.serve_and_poll(MagicMock()))

    mock_uvicorn.Config.assert_called_once()
    _, kwargs = mock_uvicorn.Config.call_args
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8000
    mock_uvicorn.Server.assert_called_once()
    mock_run_polling_loop.assert_called_once()


@patch("airtable_proxy.__main__.poller")
@patch("airtable_proxy.__main__.asyncio.run")
def test_main_uses_env_var_when_no_arg(
    mock_asyncio_run, _mock_poller, tmp_path, monkeypatch
):
    config_file = tmp_path / "from-env.yaml"
    config_file.write_text("hostname: test.example.com\n")
    monkeypatch.setenv("AIRTABLE_PROXY_CONFIG", str(config_file))
    mock_asyncio_run.side_effect = lambda coro: coro.close()

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(main_module.main, [])
    assert result.exit_code == 0, result.output


@patch("airtable_proxy.__main__.poller")
@patch("airtable_proxy.__main__.asyncio.run")
def test_main_falls_back_to_default_config_yaml(
    mock_asyncio_run, _mock_poller, tmp_path, monkeypatch
):
    monkeypatch.delenv("AIRTABLE_PROXY_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("hostname: test.example.com\n")
    mock_asyncio_run.side_effect = lambda coro: coro.close()

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(main_module.main, [])
    assert result.exit_code == 0, result.output


def test_main_friendly_error_when_config_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("AIRTABLE_PROXY_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)

    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(main_module.main, [])
    assert result.exit_code == 1
    assert "config.yaml.example" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `poetry run pytest tests/test_main.py -v --no-cov`
Expected: FAIL — the new test names don't exist on the current `__main__.py`, and `serve_and_poll` doesn't exist either.

- [ ] **Step 3: Rewrite `__main__.py`**

Overwrite `src/airtable_proxy/__main__.py` with:

```python
import asyncio
import sys

import click
import uvicorn

from airtable_proxy import poller
from airtable_proxy.app import create_app
from airtable_proxy.config import (
    Config,
    ConfigNotFoundError,
    load_config_from_file,
    resolve_config_path,
)
from airtable_proxy.poller import run_polling_loop


async def serve_and_poll(cfg: Config) -> None:
    """
    Run the API server and the polling loop concurrently in one event loop.
    """
    app = create_app(cfg)
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000))
    await asyncio.gather(server.serve(), run_polling_loop(cfg))


@click.command()
@click.argument("config", type=click.Path(), required=False)
def main(config: str | None = None) -> None:
    """
    Run the airtable_proxy API server and poller together.

    If CONFIG is omitted, looks for AIRTABLE_PROXY_CONFIG, then ./config.yaml.
    For finer control, run airtable_proxy.server and airtable_proxy.poller
    as separate processes.
    """
    try:
        config_path = resolve_config_path(config)
    except ConfigNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    cfg = load_config_from_file(config_path)
    poller.initialize(cfg)
    asyncio.run(serve_and_poll(cfg))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `poetry run pytest tests/test_main.py -v --no-cov`
Expected: PASS, 5 tests.

- [ ] **Step 5: Run the full test suite WITH coverage**

This is the moment of truth — coverage must hit 100%.

Run: `poetry run pytest`
Expected: PASS, with `Required test coverage of 100% reached.` in the output.

If coverage drops below 100%, look at the `Missing` column in the report and add a test that exercises the missing line. Common culprits:
- The `if __name__ == "__main__"` line is excluded by `pyproject.toml` so should be fine.
- An untested branch in `serve_and_poll` — make sure the `test_serve_and_poll_runs_uvicorn_and_polling` test runs the function fully.

- [ ] **Step 6: Run mypy**

Run: `poetry run mypy --strict src/airtable_proxy/`
Expected: `Success: no issues found`.

- [ ] **Step 7: Smoke test the combined runner manually (optional but recommended)**

Create a minimal `/tmp/smoke-config.yaml`:

```yaml
hostname: smoke.test.example.com
```

(no `bases:` — proves the empty-default works end-to-end).

Run in one terminal:
```bash
cd /Users/mesozoic/dev/mesozoic/airtable_proxy
poetry run python -m airtable_proxy /tmp/smoke-config.yaml
```

In another:
```bash
curl http://localhost:8000/health
```

Expected: `{"status":"ok"}`. Ctrl-C the server, confirm it exits cleanly.

- [ ] **Step 8: Commit**

```bash
git add src/airtable_proxy/__main__.py tests/test_main.py
git commit -m "Run API and poller together in python -m airtable_proxy"
```

---

### Task 6: Rewrite the README

**Files:**
- Modify: `README.md`

No tests for prose. The hard rules: keep the existing intro paragraph and the mermaid diagram (with the user's recent label edit) verbatim; reflect the final CLI shape established in Tasks 4 and 5.

- [ ] **Step 1: Read the current README**

Run: `cat /Users/mesozoic/dev/mesozoic/airtable_proxy/README.md`

Confirm the title, intro paragraph, and `## How it works` section (including the mermaid block) are present. Carry these forward verbatim.

- [ ] **Step 2: Overwrite the README**

Replace the entire `README.md` with the structure below. Preserve the title, intro paragraph, and `How it works` section (including the mermaid diagram) exactly as they are in the current file — only edit the sections that follow.

The new structure (in order):

1. `# airtable_proxy` (existing title)
2. Existing intro paragraph
3. `## How it works` with the existing mermaid diagram
4. `## Requirements`
5. `## Install`
6. `## Get an Airtable personal access token`
7. `## Configure`
8. `## Run it`
9. `## Verify it's working`
10. `## Contributing`

Section content (paste verbatim into the appropriate spot):

````markdown
## Requirements

- Python 3.13 or newer
- An Airtable account with at least one base
- A hostname **you control**. It does not need to resolve yet, but Airtable will eventually POST webhook payloads to that URL — anyone who controls the domain controls your data.

## Install

```bash
git clone https://github.com/mesozoic/airtable_proxy
cd airtable_proxy
pip install -e .
```

This installs `pyairtable`, `fastapi`, `uvicorn`, and `httpx`.

## Get an Airtable personal access token

1. Visit https://airtable.com/create/tokens.
2. Create a token with these scopes:
   - `data.records:read`
   - `schema.bases:read`
   - `webhook:manage`
3. Grant the token access to each base you want to proxy.

Find your **base ID** in any Airtable URL: `https://airtable.com/appXXXXXXXXXXXXXX/tblYYYY...` — the `app...` segment is the base ID.

## Configure

Copy the example and edit it:

```bash
cp config.yaml.example config.yaml
```

```yaml
hostname: airtable-proxy.your.domain.name
storage:
    sqlite: data/airtable_proxy.db
bases:
    appCRvRn3LxhzqYUZ:
        api_key: env(AIRTABLE_PROXY_API_KEY)
```

| Key | Purpose |
| --- | --- |
| `hostname` | The domain Airtable will POST webhook payloads to. Required. |
| `storage.sqlite` | Path to the SQLite cache file. Optional; defaults to `data/airtable_proxy.db`. |
| `bases` | Map of base ID → per-base config. Optional; if omitted, every request is proxied straight through to Airtable using the caller's bearer token. |
| `bases.<baseId>.api_key` | The PAT to use when polling this base. Use `env(VAR_NAME)` to read it from the environment instead of the file. |

## Run it

```bash
export AIRTABLE_PROXY_API_KEY=patXXXXXXXXXXXXXX.secret
python -m airtable_proxy
```

This starts the API server on port 8000 and the poller in the same process. Both auto-discover `./config.yaml`. To use a different file, set `AIRTABLE_PROXY_CONFIG=/path/to/config.yaml` or pass the path as the only argument.

For finer control (separate processes, separate logs, independent restarts), run them apart:

```bash
python -m airtable_proxy.server   # API only
python -m airtable_proxy.poller   # poller only
```

In production, supervise these with whatever your platform provides — systemd, docker-compose, or a process manager.

## Verify it's working

The API answers a health check without authentication:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Then list records (replace `<baseId>` and `<TableNameOrId>` with values from your base):

```bash
curl -H "Authorization: Bearer $AIRTABLE_PROXY_API_KEY" \
     http://localhost:8000/v0/<baseId>/<TableNameOrId>
```

The first request to a new bearer token verifies it against Airtable, then caches the hash. Subsequent requests are served from the local SQLite cache.

## Contributing

This project uses Poetry:

```bash
poetry install
poetry run mypy --strict && poetry run pytest
poetry run pre-commit run
```

Integration tests hit the real Airtable API and need credentials in `tmp/integration.sh`:

```bash
poetry run dotenv -f tmp/integration.sh run -- pytest -k integration
```
````

Drop the existing `## Dependencies` section — the dependency list is now mentioned inline in `## Install`.

- [ ] **Step 3: Spot-check the rendered output**

Run: `cat /Users/mesozoic/dev/mesozoic/airtable_proxy/README.md`

Skim for: section ordering matches the structure above; the mermaid block is intact; `## Dependencies` is gone; no leftover `uvicorn airtable_proxy.app:create_app` (the old run command).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Rewrite README for new combined-runner CLI and onboarding"
```

---

### Task 7: Final cross-checks

**Files:** none modified.

- [ ] **Step 1: Full test suite with coverage**

Run: `poetry run pytest`
Expected: PASS, 100% coverage.

- [ ] **Step 2: mypy strict**

Run: `poetry run mypy --strict`
Expected: `Success: no issues found`.

- [ ] **Step 3: pre-commit**

Run: `poetry run pre-commit run --all-files`
Expected: all hooks pass.

- [ ] **Step 4: Confirm the three CLI shapes work**

```bash
poetry run python -m airtable_proxy --help
poetry run python -m airtable_proxy.server --help
poetry run python -m airtable_proxy.poller --help
```

Expected: each prints Click usage, no traceback.

- [ ] **Step 5: Final commit if anything was tweaked**

If `pre-commit` or the smoke tests surfaced fixes, commit them with a message describing the fix. Otherwise skip.

---

## Done condition

- All seven tasks marked complete.
- `poetry run pytest` passes with 100% coverage.
- `poetry run mypy --strict` is clean.
- `python -m airtable_proxy`, `python -m airtable_proxy.server`, and `python -m airtable_proxy.poller` all work with no args (auto-discover `./config.yaml`), with a path arg, and with `AIRTABLE_PROXY_CONFIG` set.
- README walks a new dev from clone to verifying `/health`.
