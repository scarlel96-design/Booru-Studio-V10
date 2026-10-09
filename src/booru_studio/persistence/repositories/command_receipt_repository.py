from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from booru_studio.common.ids import ClientInstanceId, CommandId


@dataclass(frozen=True, slots=True)
class CommandReceiptRecord:
    client_instance_id: ClientInstanceId
    command_id: CommandId
    command_type: str
    request_hash: bytes
    result_json: str
    committed_state_revision: int
    committed_at_utc_ms: int


def get_command_receipt(
    connection: sqlite3.Connection,
    *,
    client_instance_id: ClientInstanceId,
    command_id: CommandId,
) -> CommandReceiptRecord | None:
    row = connection.execute(
        """
        SELECT client_instance_id, command_id, command_type, request_hash, result_json,
               committed_state_revision, committed_at_utc_ms
        FROM command_receipts
        WHERE client_instance_id=? AND command_id=?
        """,
        (str(client_instance_id), str(command_id)),
    ).fetchone()
    if row is None:
        return None
    return CommandReceiptRecord(
        client_instance_id=ClientInstanceId.parse(row["client_instance_id"]),
        command_id=CommandId.parse(row["command_id"]),
        command_type=str(row["command_type"]),
        request_hash=bytes(row["request_hash"]),
        result_json=str(row["result_json"]),
        committed_state_revision=int(row["committed_state_revision"]),
        committed_at_utc_ms=int(row["committed_at_utc_ms"]),
    )


def insert_command_receipt(
    connection: sqlite3.Connection,
    *,
    client_instance_id: ClientInstanceId,
    command_id: CommandId,
    command_type: str,
    request_hash: bytes,
    result_json: str,
    committed_state_revision: int,
    now_utc_ms: int,
) -> None:
    connection.execute(
        """
        INSERT INTO command_receipts(
            client_instance_id, command_id, command_type, request_hash, result_json,
            committed_state_revision, committed_at_utc_ms
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (
            str(client_instance_id),
            str(command_id),
            command_type,
            request_hash,
            result_json,
            committed_state_revision,
            now_utc_ms,
        ),
    )
