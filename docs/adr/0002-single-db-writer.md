# ADR 0002 — Single SQLite writer

Status: Accepted

The Core owns durable state through one bounded DB Actor. The SQLite connection is created and used only on that actor thread. UI and Worker processes never write the database directly.
