from __future__ import annotations

from booru_studio.persistence.schema import SCHEMA_VERSION

MIGRATION_VERSION = 1

if MIGRATION_VERSION != SCHEMA_VERSION:
    raise RuntimeError("initial migration version must match schema version")
