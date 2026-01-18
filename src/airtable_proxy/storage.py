import shelve
from pathlib import Path
from typing import Any, Iterator


class Storage:
    def __init__(self, path: Path | str):
        self._path = str(path)
        self._db = shelve.open(self._path)

    def get(self, key: str) -> Any:
        return self._db.get(key)

    def set(self, key: str, value: Any) -> None:
        self._db[key] = value
        self._db.sync()

    def delete(self, key: str) -> None:
        if key in self._db:
            del self._db[key]
            self._db.sync()

    def keys(self, prefix: str = "") -> Iterator[str]:
        for key in self._db.keys():
            if key.startswith(prefix):
                yield key

    def close(self) -> None:
        self._db.close()
