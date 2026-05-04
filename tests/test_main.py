from unittest.mock import MagicMock, patch

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
def test_main_uses_env_var_when_no_arg(mock_asyncio_run, _mock_poller, tmp_path, monkeypatch):
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
