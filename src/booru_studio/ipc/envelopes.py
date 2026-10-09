from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class ProtocolFamily(StrEnum):
    UI_CORE = "ui-core"
    CORE_WORKER = "core-worker"


class MessagePlane(StrEnum):
    COMMAND = "COMMAND"
    STATE = "STATE"
    CONTROL = "CONTROL"
    TRANSACTION = "TRANSACTION"
    RESOURCE = "RESOURCE"
    TELEMETRY = "TELEMETRY"


@dataclass(frozen=True, slots=True)
class ProtocolVersion:
    major: int
    minor: int

    def __post_init__(self) -> None:
        if self.major < 0 or self.minor < 0:
            raise ValueError("protocol version components must be non-negative")


@dataclass(frozen=True, slots=True)
class Envelope:
    family: ProtocolFamily
    version: ProtocolVersion
    plane: MessagePlane
    message_type: str
    message_id: str
    trace_id: str | None
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.message_type or len(self.message_type) > 128:
            raise ValueError("message_type must contain 1..128 characters")
        if not self.message_id or len(self.message_id) > 128:
            raise ValueError("message_id must contain 1..128 characters")
        if self.trace_id is not None and len(self.trace_id) > 128:
            raise ValueError("trace_id is too long")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


def envelope_to_wire_dict(envelope: Envelope) -> dict[str, Any]:
    """Serialize any protocol-family Envelope without applying family-specific semantics."""
    return {
        "family": envelope.family.value,
        "version": {"major": envelope.version.major, "minor": envelope.version.minor},
        "plane": envelope.plane.value,
        "message_type": envelope.message_type,
        "message_id": envelope.message_id,
        "trace_id": envelope.trace_id,
        "payload": dict(envelope.payload),
    }


def envelope_from_wire_dict(obj: dict[str, Any]) -> Envelope:
    """Decode the common wire envelope; protocol handlers validate family-specific rules."""
    version = obj.get("version")
    payload = obj.get("payload")
    if not isinstance(version, dict):
        raise ValueError("missing protocol version")
    if not isinstance(payload, dict):
        raise ValueError("payload must be object")
    return Envelope(
        family=ProtocolFamily(str(obj["family"])),
        version=ProtocolVersion(int(version["major"]), int(version["minor"])),
        plane=MessagePlane(str(obj["plane"])),
        message_type=str(obj["message_type"]),
        message_id=str(obj["message_id"]),
        trace_id=None if obj.get("trace_id") is None else str(obj["trace_id"]),
        payload=payload,
    )
