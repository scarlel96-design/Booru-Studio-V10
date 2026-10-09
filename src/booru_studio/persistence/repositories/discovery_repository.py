from __future__ import annotations

import sqlite3

from booru_studio.common.ids import DiscoveryCycleId, ItemId, JobId
from booru_studio.domain.enums import DiscoveryCompleteness, DiscoveryCycleState, ItemLifecycle


def next_cycle_sequence(connection: sqlite3.Connection, job_id: JobId) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(cycle_sequence),-1)+1 FROM discovery_cycles WHERE job_id=?",
        (str(job_id),),
    ).fetchone()
    return int(row[0])


def insert_cycle(
    connection: sqlite3.Connection, *, cycle_id: DiscoveryCycleId, job_id: JobId,
    sequence: int, now_utc_ms: int,
) -> None:
    connection.execute(
        """INSERT INTO discovery_cycles(
               cycle_id,job_id,cycle_sequence,state,completeness,next_batch_sequence,
               created_at_utc_ms,sealed_at_utc_ms
           ) VALUES(?,?,?,'OPEN','UNKNOWN',0,?,NULL)""",
        (str(cycle_id), str(job_id), sequence, now_utc_ms),
    )


def insert_item_batch(
    connection: sqlite3.Connection, *, cycle_id: DiscoveryCycleId, job_id: JobId,
    batch_sequence: int, items: list[dict[str, object]], now_utc_ms: int,
) -> None:
    cycle = connection.execute(
        "SELECT state,next_batch_sequence,job_id FROM discovery_cycles WHERE cycle_id=?",
        (str(cycle_id),),
    ).fetchone()
    if cycle is None:
        raise KeyError("discovery cycle not found")
    if str(cycle["job_id"]) != str(job_id):
        raise ValueError("discovery cycle belongs to a different Job")
    if str(cycle["state"]) != DiscoveryCycleState.OPEN.value:
        raise RuntimeError("discovery cycle is not open")
    if int(cycle["next_batch_sequence"]) != batch_sequence:
        raise ValueError("discovery batch sequence is not contiguous")
    for item in items:
        connection.execute(
            """INSERT INTO items(
                   item_id,job_id,discovery_cycle_id,source_key,display_title,source_index,
                   lifecycle,outcome,disposition,created_at_utc_ms,updated_at_utc_ms
               ) VALUES(?,?,?,?,?,?,'PENDING',NULL,NULL,?,?)
               ON CONFLICT(job_id,source_key) WHERE source_key IS NOT NULL DO NOTHING""",
            (
                str(item["item_id"]), str(job_id), str(cycle_id), str(item["source_key"]),
                str(item["display_title"]), int(item["source_index"]), now_utc_ms, now_utc_ms,
            ),
        )
    connection.execute(
        "UPDATE discovery_cycles SET next_batch_sequence=next_batch_sequence+1 WHERE cycle_id=?",
        (str(cycle_id),),
    )


def seal_cycle(
    connection: sqlite3.Connection, *, cycle_id: DiscoveryCycleId,
    completeness: DiscoveryCompleteness, now_utc_ms: int,
) -> None:
    cursor = connection.execute(
        """UPDATE discovery_cycles
           SET state='SEALED',completeness=?,sealed_at_utc_ms=?
           WHERE cycle_id=? AND state='OPEN'""",
        (completeness.value, now_utc_ms, str(cycle_id)),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("discovery cycle cannot be sealed")


def list_items(connection: sqlite3.Connection, job_id: JobId) -> list[sqlite3.Row]:
    return list(connection.execute(
        "SELECT * FROM items WHERE job_id=? ORDER BY source_index,item_id", (str(job_id),)
    ).fetchall())
