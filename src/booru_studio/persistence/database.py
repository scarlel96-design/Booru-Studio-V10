from __future__ import annotations

import sqlite3
from pathlib import Path

from booru_studio.persistence.schema import configure_connection, initialize_schema


def connect(path: Path, *, now_utc_ms: int) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    configure_connection(connection)
    initialize_schema(connection, now_utc_ms=now_utc_ms)
    return connection
