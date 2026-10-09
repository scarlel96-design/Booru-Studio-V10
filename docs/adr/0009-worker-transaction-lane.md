# ADR 0009 — Durable Worker transaction lane

Status: Accepted.

Durable Worker→Core mutations use per-session monotonically increasing `worker_tx_seq`.
Core accepts exact replay, rejects changed-content replay and gaps, performs the side effect +
receipt + contiguous-sequence update in one SQLite transaction, and sends cumulative ACK only
after commit. Telemetry never uses this durable lane.
