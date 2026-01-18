import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterator


class Storage:
    """
    A simple key-value store backed by sqlite3.

    Thread-safe for concurrent access from multiple threads within a process.
    Write operations are serialized with a lock; reads are lock-free.
    Values are JSON-serialized for storage.
    """

    def __init__(self, path: Path | str):
        self._path = str(path)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
            self._conn.commit()

    def get(self, key: str) -> Any:
        cursor = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
            self._conn.commit()

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            self._conn.commit()

    def keys(self, prefix: str = "") -> Iterator[str]:
        cursor = self._conn.execute("SELECT key FROM kv WHERE key LIKE ?", (prefix + "%",))
        for row in cursor:
            yield row[0]

    def close(self) -> None:
        self._conn.close()
