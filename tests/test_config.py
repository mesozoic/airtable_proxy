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
