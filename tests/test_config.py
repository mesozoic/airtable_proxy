from pathlib import Path

import pytest
from pydantic import ValidationError

from airtable_proxy import config


def test_load_valid_config():
    cfg = config.load_config(
        {
            "hostname": "airtable-proxy.example.com",
            "bases": {
                "appCRvRn3LxhzqYUZ": {"api_key": "patCRvRn3LxhzqYUZ.secret"},
                "appAnotherBase123": {"api_key": "patAnotherKey456.secret"},
            },
        }
    )

    assert cfg.hostname == "airtable-proxy.example.com"
    assert len(cfg.bases) == 2
    assert cfg.bases["appCRvRn3LxhzqYUZ"].api_key == "patCRvRn3LxhzqYUZ.secret"
    assert cfg.bases["appAnotherBase123"].api_key == "patAnotherKey456.secret"


def test_load_config_missing_hostname():
    with pytest.raises(ValidationError) as exc_info:
        config.load_config(
            {
                "bases": {"appCRvRn3LxhzqYUZ": {"api_key": "patCRvRn3LxhzqYUZ.secret"}},
            }
        )
    assert "hostname" in str(exc_info.value)


def test_load_config_missing_bases():
    with pytest.raises(ValidationError) as exc_info:
        config.load_config({"hostname": "airtable-proxy.example.com"})
    assert "bases" in str(exc_info.value)


def test_load_config_api_key_from_default_env(monkeypatch):
    monkeypatch.setenv("AIRTABLE_API_KEY", "patFromEnv.secret")
    cfg = config.load_config(
        {
            "hostname": "airtable-proxy.example.com",
            "bases": {"appCRvRn3LxhzqYUZ": {}},
        }
    )
    assert cfg.bases["appCRvRn3LxhzqYUZ"].api_key == "patFromEnv.secret"


def test_load_config_api_key_env_keyword(monkeypatch):
    monkeypatch.setenv("AIRTABLE_API_KEY", "patFromEnv.secret")
    cfg = config.load_config(
        {
            "hostname": "airtable-proxy.example.com",
            "bases": {"appCRvRn3LxhzqYUZ": {"api_key": "env"}},
        }
    )
    assert cfg.bases["appCRvRn3LxhzqYUZ"].api_key == "patFromEnv.secret"


def test_load_config_api_key_env_custom_var(monkeypatch):
    monkeypatch.setenv("MY_CUSTOM_KEY", "patCustom.secret")
    cfg = config.load_config(
        {
            "hostname": "airtable-proxy.example.com",
            "bases": {"appCRvRn3LxhzqYUZ": {"api_key": "env(MY_CUSTOM_KEY)"}},
        }
    )
    assert cfg.bases["appCRvRn3LxhzqYUZ"].api_key == "patCustom.secret"


def test_load_config_api_key_env_not_set(monkeypatch):
    monkeypatch.delenv("AIRTABLE_API_KEY", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        config.load_config(
            {
                "hostname": "airtable-proxy.example.com",
                "bases": {"appCRvRn3LxhzqYUZ": {}},
            }
        )
    assert "AIRTABLE_API_KEY" in str(exc_info.value)


def test_load_config_from_file(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
hostname: airtable-proxy.example.com
bases:
    appCRvRn3LxhzqYUZ:
        api_key: patCRvRn3LxhzqYUZ.secret
"""
    )
    cfg = config.load_config_from_file(config_file)

    assert cfg.hostname == "airtable-proxy.example.com"
    assert cfg.bases["appCRvRn3LxhzqYUZ"].api_key == "patCRvRn3LxhzqYUZ.secret"


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
