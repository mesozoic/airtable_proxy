import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


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


class BaseConfig(BaseModel):
    api_key: str = Field(default="env", validate_default=True)

    @field_validator("api_key")
    @classmethod
    def resolve_api_key(cls, value: str) -> str:
        if value == "env":
            env_var = "AIRTABLE_API_KEY"
        elif match := re.match(r"^env\((\w+)\)$", value):
            env_var = match.group(1)
        else:
            return value

        if not (result := os.environ.get(env_var)):
            raise ValueError(f"Environment variable {env_var} is not set")
        return result


class StorageConfig(BaseModel):
    sqlite: Path = Path("data/airtable_proxy.db")


class Config(BaseModel):
    hostname: str
    bases: dict[str, BaseConfig]
    storage: StorageConfig = StorageConfig()


def load_config(data: dict[str, Any]) -> Config:
    return Config.model_validate(data)


def load_config_from_file(path: Path | str) -> Config:
    with open(path) as f:
        data = yaml.safe_load(f)
    return load_config(data)
