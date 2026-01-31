from unittest.mock import MagicMock, patch

from airtable_proxy.__main__ import main


@patch("airtable_proxy.__main__.uvicorn")
@patch("airtable_proxy.__main__.create_app")
@patch("airtable_proxy.__main__.load_config_from_file")
@patch("sys.argv", ["airtable_proxy", "/tmp/config.yaml"])
def test_main_runs_uvicorn(mock_load, mock_create_app, mock_uvicorn):
    mock_load.return_value = MagicMock()
    mock_create_app.return_value = MagicMock()

    main()

    mock_load.assert_called_once()
    mock_create_app.assert_called_once()
    mock_uvicorn.run.assert_called_once()


@patch("sys.argv", ["airtable_proxy"])
def test_main_exits_without_config():
    import pytest

    with pytest.raises(SystemExit, match="1"):
        main()
