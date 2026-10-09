from __future__ import annotations

import sqlite3

from booru_studio.common.ids import JobId
from booru_studio.domain.queue import QueueEntry, QueuedJob

QUEUE_SORT_STEP = 1024


def next_queue_sort_key(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT MAX(sort_key) AS max_key FROM queue_entries").fetchone()
    max_key = row["max_key"] if row is not None else None
    if max_key is None:
        return QUEUE_SORT_STEP
    return int(max_key) + QUEUE_SORT_STEP


def enqueue_job(
    connection: sqlite3.Connection,
    *,
    job_id: JobId,
    now_utc_ms: int,
    sort_key: int | None = None,
) -> QueueEntry:
    key = next_queue_sort_key(connection) if sort_key is None else sort_key
    connection.execute(
        "INSERT INTO queue_entries(job_id, sort_key, enqueued_at_utc_ms) VALUES(?,?,?)",
        (str(job_id), key, now_utc_ms),
    )
    return QueueEntry(job_id=job_id, sort_key=key, enqueued_at_utc_ms=now_utc_ms)


def remove_job_from_queue(connection: sqlite3.Connection, job_id: JobId) -> None:
    connection.execute("DELETE FROM queue_entries WHERE job_id=?", (str(job_id),))


def list_queued_jobs(connection: sqlite3.Connection) -> list[QueuedJob]:
    rows = connection.execute(
        """
        SELECT q.job_id, q.sort_key, q.enqueued_at_utc_ms, j.title, j.priority
        FROM queue_entries q
        JOIN jobs j ON j.job_id=q.job_id
        ORDER BY q.sort_key ASC
        """
    ).fetchall()
    return [
        QueuedJob(
            job_id=JobId.parse(row["job_id"]),
            title=str(row["title"]),
            sort_key=int(row["sort_key"]),
            enqueued_at_utc_ms=int(row["enqueued_at_utc_ms"]),
            priority=int(row["priority"]),
            position=index + 1,
        )
        for index, row in enumerate(rows)
    ]
