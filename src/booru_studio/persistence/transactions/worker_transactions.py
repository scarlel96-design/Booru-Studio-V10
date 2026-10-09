from __future__ import annotations

import sqlite3
from collections.abc import Callable

from booru_studio.common.ids import WorkerSessionId
from booru_studio.common.serialization import canonical_json_dumps, canonical_json_sha256
from booru_studio.persistence.repositories.worker_repository import get_worker_session
from booru_studio.persistence.transactions.base import write_transaction


class WorkerTransactionConflict(RuntimeError):
    pass


class WorkerTransactionGap(RuntimeError):
    pass


def commit_worker_transaction(
    connection: sqlite3.Connection,
    *,
    worker_session_id: WorkerSessionId,
    tx_seq: int,
    tx_type: str,
    payload: dict[str, object],
    now_utc_ms: int,
    side_effect: Callable[[sqlite3.Connection], None] | None = None,
) -> int:
    if tx_seq <= 0:
        raise ValueError("worker tx sequence must be positive")
    payload_json = canonical_json_dumps(payload)
    payload_hash = canonical_json_sha256(payload)
    with write_transaction(connection):
        session = get_worker_session(connection, worker_session_id)
        if session is None:
            raise KeyError("worker session not found")
        last = int(session["last_contiguous_tx_seq"])
        existing = connection.execute(
            "SELECT payload_hash,tx_type FROM worker_tx_receipts WHERE worker_session_id=? AND tx_seq=?",
            (str(worker_session_id), tx_seq),
        ).fetchone()
        if existing is not None:
            if bytes(existing["payload_hash"]) != payload_hash or str(existing["tx_type"]) != tx_type:
                raise WorkerTransactionConflict("same Worker tx sequence has different content")
            return last
        if tx_seq != last + 1:
            raise WorkerTransactionGap(f"expected tx sequence {last + 1}, got {tx_seq}")
        if side_effect is not None:
            side_effect(connection)
        connection.execute(
            """
            INSERT INTO worker_tx_receipts(
                worker_session_id,tx_seq,payload_hash,tx_type,payload_json,committed_at_utc_ms
            ) VALUES(?,?,?,?,?,?)
            """,
            (str(worker_session_id), tx_seq, payload_hash, tx_type, payload_json, now_utc_ms),
        )
        connection.execute(
            "UPDATE worker_sessions SET last_contiguous_tx_seq=? WHERE worker_session_id=?",
            (tx_seq, str(worker_session_id)),
        )
        return tx_seq
