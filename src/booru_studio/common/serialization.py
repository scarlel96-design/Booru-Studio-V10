from __future__ import annotations

import hashlib
import json
from typing import Any


JSONScalar = str | int | float | bool | None
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


def canonical_json_dumps(value: Any) -> str:
    """Serialize JSON-compatible data deterministically.

    Command request hashing and durable result receipts rely on a stable byte
    representation. `ensure_ascii=False` intentionally preserves Unicode while
    UTF-8 encoding below defines the bytes that are hashed.
    """

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_json_sha256(value: Any) -> bytes:
    payload = canonical_json_dumps(value).encode("utf-8")
    return hashlib.sha256(payload).digest()


def json_loads_object(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def json_loads_list(raw: str) -> list[Any]:
    value = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError("expected JSON array")
    return value
