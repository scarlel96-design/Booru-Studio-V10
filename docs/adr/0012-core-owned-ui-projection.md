# ADR 0012 — Core-owned UI projection

## Status
Accepted for Sprint 5.

## Decision
The UI never reads SQLite directly. Core owns a short, revision-pinned projection read through
the single DB Actor and exposes Downloads, Queue and bounded History representations. The UI
stores only a non-authoritative projection copy and rejects revision regression.

Durable state and transient telemetry remain separate. History is bounded to an initial page so
large long-lived installations cannot accidentally materialize unbounded settled-job state in one
QML model reset.

## Consequences
Production UI-Core transport can evolve independently from persistence. QML delegates render
projection roles only. Reconnect can discard transient telemetry and request a fresh snapshot.
