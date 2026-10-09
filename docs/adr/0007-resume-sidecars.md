# ADR 0007 — Atomic resume sidecars

Status: Accepted.

Resume metadata is bounded and checksummed, written through tmp+fsync+atomic replace, and
validated against the actual `.part` size before Core mirrors it into SQLite. Sidecars are
untrusted input and are never sufficient by themselves to authorize final-file mutation.
