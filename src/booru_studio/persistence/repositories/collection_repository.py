from __future__ import annotations

import sqlite3

from booru_studio.common.ids import CollectionId, ItemId, JobId


def get_or_create_collection(
    connection: sqlite3.Connection,
    *,
    collection_id: CollectionId,
    job_id: JobId,
    kind: str,
    title: str,
    source_key: str,
    now_utc_ms: int,
) -> CollectionId:
    row = connection.execute(
        """
        SELECT collection_id FROM collections
        WHERE job_id=? AND kind=? AND source_key=?
        ORDER BY created_at_utc_ms, collection_id
        LIMIT 1
        """,
        (str(job_id), kind, source_key),
    ).fetchone()
    if row is not None:
        return CollectionId.parse(str(row["collection_id"]))
    connection.execute(
        """
        INSERT INTO collections(
            collection_id,job_id,parent_collection_id,kind,title,source_key,sort_index,created_at_utc_ms
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (str(collection_id), str(job_id), None, kind, title, source_key, 0, now_utc_ms),
    )
    return collection_id


def add_collection_memberships(
    connection: sqlite3.Connection,
    *,
    collection_id: CollectionId,
    memberships: list[tuple[ItemId, int]],
) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO collection_memberships(collection_id,item_id,sort_index)
        VALUES(?,?,?)
        """,
        [(str(collection_id), str(item_id), sort_index) for item_id, sort_index in memberships],
    )
