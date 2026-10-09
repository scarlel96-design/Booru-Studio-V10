from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator


@contextmanager
def write_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Run one semantic write transaction.

    Sprint 1 has a single DB writer, but `BEGIN IMMEDIATE` still makes the
    transaction boundary explicit and prevents a future accidental second writer
    from interleaving after the semantic operation has started.
    """

    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()
