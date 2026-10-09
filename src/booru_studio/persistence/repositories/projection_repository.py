from __future__ import annotations

import json
import ntpath
import posixpath
import sqlite3
from typing import Any

from booru_studio.common.text_safety import sanitize_display_text

DEFAULT_HISTORY_PAGE_SIZE = 200


def _joined_file_path(root: object, relative: object) -> str | None:
    if root is None or relative is None:
        return None
    root_text = str(root)
    relative_text = str(relative).replace("\\", "/")
    if not root_text or not relative_text:
        return None
    if ":\\" in root_text or "\\" in root_text:
        return ntpath.normpath(ntpath.join(root_text, relative_text.replace("/", "\\")))
    return posixpath.normpath(posixpath.join(root_text, relative_text))


def _primary_activity(activities_json: str) -> str | None:
    values = json.loads(activities_json)
    if not isinstance(values, list) or not values:
        return None
    preferred = (
        "RECONCILING",
        "VERIFYING",
        "POSTPROCESSING",
        "TRANSFERRING",
        "RESOLVING",
        "DISCOVERING",
        "ANALYZING",
    )
    present = {str(value) for value in values}
    return next((value for value in preferred if value in present), sorted(present)[0])


def _waiting_reason(waiting_json: str) -> str | None:
    values = json.loads(waiting_json)
    if not isinstance(values, list) or not values:
        return None
    return sorted(str(value) for value in values)[0]


def _project_row(row: sqlite3.Row) -> dict[str, Any]:
    expected = int(row["expected_bytes"] or 0)
    committed = int(row["committed_bytes"] or 0)
    artifact_total = int(row["artifact_total"])
    artifact_committed = int(row["artifact_committed"])
    progress: float | None
    if expected > 0:
        progress = min(1.0, max(0.0, committed / expected))
    elif artifact_total > 0:
        progress = min(1.0, artifact_committed / artifact_total)
    else:
        progress = None
    return {
        "job_id": str(row["job_id"]),
        "kind": str(row["kind"]),
        "title": sanitize_display_text(str(row["title"])),
        "lifecycle": str(row["lifecycle"]),
        "outcome": str(row["outcome"]) if row["outcome"] is not None else None,
        "control_intent": str(row["control_intent"]),
        "primary_activity": _primary_activity(str(row["activities_json"])),
        "waiting_reason": _waiting_reason(str(row["waiting_reasons_json"])),
        "priority": int(row["priority"]),
        "created_at_utc_ms": int(row["created_at_utc_ms"]),
        "updated_at_utc_ms": int(row["updated_at_utc_ms"]),
        "input_kind": str(row["input_kind"]),
        "display_input": sanitize_display_text(str(row["redacted_input"])),
        "item_total": int(row["item_total"]),
        "item_settled": int(row["item_settled"]),
        "artifact_total": artifact_total,
        "artifact_committed": artifact_committed,
        "committed_bytes": committed,
        "expected_bytes": expected,
        "progress": progress,
        "primary_file_path": _joined_file_path(row["primary_file_root"], row["primary_file_relative"]),
        "latest_error_code": str(row["latest_error_code"]) if row["latest_error_code"] is not None else None,
        "latest_native_code": str(row["latest_native_code"]) if row["latest_native_code"] is not None else None,
    }


def _job_query(where_sql: str, *, order_sql: str, limit: int | None = None) -> str:
    suffix = f" LIMIT {int(limit)}" if limit is not None else ""
    return f"""
        SELECT
            j.job_id, j.kind, j.title, j.lifecycle, j.outcome, j.control_intent,
            j.activities_json, j.waiting_reasons_json, j.priority,
            j.created_at_utc_ms, j.updated_at_utc_ms,
            s.input_kind, s.redacted_input,
            (SELECT COUNT(*) FROM items i WHERE i.job_id=j.job_id) AS item_total,
            (SELECT COUNT(*) FROM items i WHERE i.job_id=j.job_id AND i.lifecycle='SETTLED') AS item_settled,
            (SELECT COUNT(*) FROM artifacts a WHERE a.job_id=j.job_id) AS artifact_total,
            (SELECT COUNT(*) FROM artifacts a WHERE a.job_id=j.job_id AND a.lifecycle='COMMITTED') AS artifact_committed,
            COALESCE((SELECT SUM(fr.size_bytes)
                      FROM file_records fr
                      JOIN artifacts a2 ON a2.artifact_id=fr.artifact_id
                      WHERE a2.job_id=j.job_id), 0) AS committed_bytes,
            COALESCE((SELECT SUM(a3.expected_size)
                      FROM artifacts a3
                      WHERE a3.job_id=j.job_id AND a3.expected_size IS NOT NULL), 0) AS expected_bytes
,
            (SELECT st.normalized_root
               FROM file_records fr
               JOIN artifacts af ON af.artifact_id=fr.artifact_id
               JOIN storage_targets st ON st.storage_target_id=fr.storage_target_id AND st.generation=fr.storage_generation
              WHERE af.job_id=j.job_id
              ORDER BY fr.committed_at_utc_ms DESC, fr.file_record_id DESC LIMIT 1) AS primary_file_root,
            (SELECT fr.normalized_relative_path
               FROM file_records fr
               JOIN artifacts af ON af.artifact_id=fr.artifact_id
              WHERE af.job_id=j.job_id
              ORDER BY fr.committed_at_utc_ms DESC, fr.file_record_id DESC LIMIT 1) AS primary_file_relative,
            COALESCE(
              (SELECT oa.error_code
                 FROM operation_attempts oa
                 LEFT JOIN item_execution_attempts iea ON iea.attempt_id=oa.item_attempt_id
                 LEFT JOIN items ii ON ii.item_id=iea.item_id
                 LEFT JOIN job_operation_attempts joa ON joa.attempt_id=oa.job_operation_attempt_id
                WHERE (ii.job_id=j.job_id OR joa.job_id=j.job_id) AND oa.error_code IS NOT NULL
                ORDER BY COALESCE(oa.ended_at_utc_ms, oa.started_at_utc_ms) DESC, oa.operation_id DESC LIMIT 1),
              (SELECT ja.error_code FROM job_operation_attempts ja WHERE ja.job_id=j.job_id AND ja.error_code IS NOT NULL
                ORDER BY COALESCE(ja.ended_at_utc_ms, ja.started_at_utc_ms) DESC, ja.attempt_id DESC LIMIT 1)
            ) AS latest_error_code,
            (SELECT oa.native_code
               FROM operation_attempts oa
               LEFT JOIN item_execution_attempts iea ON iea.attempt_id=oa.item_attempt_id
               LEFT JOIN items ii ON ii.item_id=iea.item_id
               LEFT JOIN job_operation_attempts joa ON joa.attempt_id=oa.job_operation_attempt_id
              WHERE (ii.job_id=j.job_id OR joa.job_id=j.job_id) AND oa.native_code IS NOT NULL
              ORDER BY COALESCE(oa.ended_at_utc_ms, oa.started_at_utc_ms) DESC, oa.operation_id DESC LIMIT 1) AS latest_native_code
        FROM jobs j
        JOIN submissions s ON s.submission_id=j.submission_id
        WHERE {where_sql}
        ORDER BY {order_sql}
        {suffix}
    """


def _queue_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT q.job_id, q.enqueued_at_utc_ms, q.sort_key, j.title, j.priority,
               j.lifecycle, j.control_intent
        FROM queue_entries q
        JOIN jobs j ON j.job_id=q.job_id
        ORDER BY q.sort_key ASC, q.job_id ASC
        """
    ).fetchall()
    return [
        {
            "job_id": str(row["job_id"]),
            "title": sanitize_display_text(str(row["title"])),
            "priority": int(row["priority"]),
            "lifecycle": str(row["lifecycle"]),
            "position": index + 1,
            "enqueued_at_utc_ms": int(row["enqueued_at_utc_ms"]),
            "control_intent": str(row["control_intent"]),
        }
        for index, row in enumerate(rows)
    ]


def read_projection_snapshot(
    connection: sqlite3.Connection,
    *,
    history_page_size: int = DEFAULT_HISTORY_PAGE_SIZE,
) -> dict[str, Any]:
    """Read a self-consistent Core-owned UI projection snapshot.

    History is intentionally bounded.  The full history/detail pagination protocol is a later
    UI-Core extension, but Sprint 5 must not regress into loading unbounded settled history into
    one model reset.
    """
    if history_page_size <= 0 or history_page_size > 1000:
        raise ValueError("history_page_size must be in 1..1000")

    connection.execute("BEGIN")
    try:
        revision_row = connection.execute(
            "SELECT state_revision FROM state_meta WHERE singleton_id=1"
        ).fetchone()
        if revision_row is None:
            raise RuntimeError("state_meta singleton is missing")
        revision = int(revision_row["state_revision"])
        downloads = [
            _project_row(row)
            for row in connection.execute(
                _job_query("j.lifecycle <> 'SETTLED'", order_sql="j.created_at_utc_ms DESC, j.job_id DESC")
            ).fetchall()
        ]
        history_rows = connection.execute(
            _job_query(
                "j.lifecycle = 'SETTLED'",
                order_sql="j.updated_at_utc_ms DESC, j.job_id DESC",
                limit=history_page_size + 1,
            )
        ).fetchall()
        queue = _queue_rows(connection)
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise

    history_has_more = len(history_rows) > history_page_size
    history = [_project_row(row) for row in history_rows[:history_page_size]]
    return {
        "global_state_revision": revision,
        "projection_revision": revision,
        "downloads": downloads,
        "queue": queue,
        "history": history,
        "history_page_size": history_page_size,
        "history_has_more": history_has_more,
    }
