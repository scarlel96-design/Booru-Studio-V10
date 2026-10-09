from __future__ import annotations

import sqlite3

from booru_studio.domain.submission import Submission


def insert_submission(connection: sqlite3.Connection, submission: Submission) -> None:
    connection.execute(
        """
        INSERT INTO submissions(submission_id, input_kind, redacted_input, created_at_utc_ms)
        VALUES(?,?,?,?)
        """,
        (
            str(submission.submission_id),
            submission.input_kind.value,
            submission.redacted_input,
            submission.created_at_utc_ms,
        ),
    )
