# ADR 0020 — Packaged UI owns QLocal IPC on a dedicated worker thread

## Status
Accepted in Sprint 10.

## Context
Synchronous QLocal request/response waits on the Qt GUI thread can freeze rendering and input during
Core stalls or reconnects. Retrying a mutation with a new command identity after an ambiguous response
loss can also duplicate a Job.

## Decision
The packaged UI's QLocalSocket and request/response loop live on a dedicated IPC worker thread. QML
and the GUI thread enqueue commands and consume completion signals only.

Each UI process has one stable `client_instance_id`; each mutation has one stable `command_id` that is
retained across the single reconnect/replay attempt. The Core's durable command receipt therefore makes
ambiguous response loss idempotent rather than creating duplicate jobs.

A create-job input field is cleared only after the matching Core commit succeeds and only if the user
has not edited that field since the request was submitted.

## Consequences
- Core/pipe latency does not intentionally block the GUI event loop.
- reconnect is fail-closed for mutations and preserves command identity;
- a lost reply cannot be converted into a second logical create/cancel/pause operation.
