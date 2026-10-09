# ADR 0001 — Local IPC boundary

Status: Accepted

V10 separates UI, Core and Worker processes. UI↔Core and Core↔Worker protocols are versioned independently. The implementation target is Qt local IPC (`QLocalServer`/`QLocalSocket`) on Windows, with explicit framing and authenticated Worker bootstrap added in later milestones.
