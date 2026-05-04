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
