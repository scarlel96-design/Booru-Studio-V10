# ADR 0006 — PREPARED-before-filesystem FileCommit

Status: Accepted.

A final filesystem mutation may begin only after a durable FileCommitIntent reaches PREPARED.
Core independently verifies the resulting final file before Artifact/FileRecord COMMITTED.
Ambiguous finals are preserved for recovery review rather than overwritten or deleted.
