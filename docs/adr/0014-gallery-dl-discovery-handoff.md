# ADR 0014 — gallery-dl is a Worker-owned discovery engine

## Status

Accepted for Sprint 6.

## Context

Booru Studio needs gallery-dl's site knowledge without surrendering V10's queue, retry, resume,
FileCommit and durability model. A direct media URL is not sufficient evidence for safe handoff:
some extractors require Referer/User-Agent headers, short-lived query signatures, cookies or custom
HTTP validation state.

The historical V9 line also showed that external-engine/package boundaries become fragile when
runtime identity or helper behavior is inferred indirectly. Sprint 6 therefore makes ownership and
handoff capability explicit instead of letting Core call gallery-dl or parse its stdout.

## Decision

- The concrete gallery-dl adapter is imported only by Engine/Worker code. Core never imports it.
- The Engine Pack pins `gallery-dl==1.32.9` and runtime QA rejects a different version.
- gallery-dl `DataJob` is embedded with `file=None`; Worker stdout may be an IPC transport and must
  never receive DataJob's default JSON dump.
- A scoped gallery-dl `output.private=true` setting preserves `_http_headers`/`_http_validate` long
  enough for handoff-safety analysis. Those private values are not copied to durable normalized
  metadata.
- DataJob's `job.exception` is authoritative because DataJob can capture an extractor exception and
  still return zero. A raw return code is not treated as successful discovery evidence.
- Queue/extractor indirection is resolved to a bounded depth of 8 inside the Worker. Unresolved child
  inputs remain ephemeral runtime inputs.
- Discovery is normalized to V10 `NormalizedItemDescriptor` and crosses the Worker/Core boundary in
  batches of at most 500 items.
- `TransferDescriptor.handoff_safety` is classified `SAFE`, `CONDITIONAL` or `UNSAFE`.
- Only SAFE/CONDITIONAL descriptors can become V10 DirectHTTP execution entries.
- Cookie/Authorization/custom-validator dependent descriptors are UNSAFE. Sprint 6 refuses unsafe
  DirectHTTP handoff rather than silently dropping the required session state.
- Signed URLs, cookies, raw headers and queued child URLs are runtime-only; ordinary SQLite state
  stores only normalized/redacted identity and display information.

## Consequences

Public and header-compatible Booru/Gallery downloads can reuse the already hardened V10 DirectHTTP
and FileCommit pipeline. Sites that need gallery-managed session transfer are identified accurately
instead of failing later with a misleading 403. A future managed-gallery execution mode can be
added behind the same explicit capability boundary without changing Core's domain contract.
