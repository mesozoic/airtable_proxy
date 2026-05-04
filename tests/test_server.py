from unittest.mock import MagicMock, patch

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
def test_main_uses_env_var_when_no_arg(mock_create_app, _mock_uvicorn, tmp_path, monkeypatch):
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
