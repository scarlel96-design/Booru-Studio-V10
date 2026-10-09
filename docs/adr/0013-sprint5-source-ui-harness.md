# ADR 0013 — Sprint 5 source UI harness is not the production process boundary

## Status
Accepted as a temporary development harness.

## Decision
Sprint 5 includes the final UI-Core v1 request/response protocol and Core session handler, but the
Linux execution environment does not contain PySide6 and cannot validate Windows QLocal runtime.
For QML development on a PySide-enabled machine, `booru-studio-ui` uses a clearly named
`core.source_ui_backend` that creates Core services in-process. UI modules still never import
SQLite, Worker, or concrete Engine implementations.

This harness is not a waiver of A.4/F.6: the production app remains a separate UI process and Core
process connected through local IPC. The in-process bridge must not become the packaged production
path.
