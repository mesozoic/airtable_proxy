import asyncio
import logging
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
    poller.initialize(cfg)
    asyncio.run(serve_and_poll(cfg))


if __name__ == "__main__":
    main()
