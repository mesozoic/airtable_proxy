import sys
from pathlib import Path

import uvicorn

from airtable_proxy.app import create_app
from airtable_proxy.config import load_config_from_file


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m airtable_proxy <config.yaml>")
        sys.exit(1)

    config_path = Path(sys.argv[1])
    config = load_config_from_file(config_path)
    app = create_app(config)
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
