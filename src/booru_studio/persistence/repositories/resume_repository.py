from __future__ import annotations

import sqlite3

from booru_studio.domain.resume import ResumeState


def upsert_resume_record(connection: sqlite3.Connection, state: ResumeState, *, now_utc_ms: int) -> None:
    connection.execute(
        """
        INSERT INTO resume_records(
            artifact_id,generation,part_path,sidecar_path,part_size,source_fingerprint,
            validator_json,payload_checksum,updated_at_utc_ms
        ) VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(artifact_id) DO UPDATE SET
            generation=excluded.generation,
            part_path=excluded.part_path,
            sidecar_path=excluded.sidecar_path,
            part_size=excluded.part_size,
            source_fingerprint=excluded.source_fingerprint,
            validator_json=excluded.validator_json,
            payload_checksum=excluded.payload_checksum,
            updated_at_utc_ms=excluded.updated_at_utc_ms
        """,
        (
            str(state.artifact_id), state.generation, str(state.part_path), str(state.sidecar_path),
            state.part_size, state.source_fingerprint, __import__('json').dumps(state.validator, sort_keys=True),
            state.payload_checksum, now_utc_ms,
        ),
    )
