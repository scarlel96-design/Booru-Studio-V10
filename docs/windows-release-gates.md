# Windows / Frozen / Updater release gates seeded at Gate 6.5

These are future executable E2E/fault-injection gates. Source-unit coverage records the contract now;
passing Windows results are not claimed by Gate 6.5.

| ID | Area | Required result |
|---|---|---|
| G65-WIN-IPC-SAME-USER | QLocal | cross-user access rejected; same-user intended client works |
| G65-WIN-IPC-BOOTSTRAP | QLocal/auth | stale endpoint/nonce/session knowledge cannot authenticate a new Core |
| G65-WIN-JOB-KILL | Supervisor | closing/crashing Supervisor leaves 0 Worker/FFmpeg/engine child orphans |
| G65-FROZEN-QML-LOAD | Frozen UI | installed UI loads QML, Qt plugins and translations |
| G65-FROZEN-WORKER-SPAWN | Frozen Worker | installed candidate self-spawns/authenticates/exits a Worker successfully |
| G65-UPD-100PCT-NOT-SUCCESS | Updater | download/stage progress can reach 100% without marking SUCCESS |
| G65-UPD-CANDIDATE-KILL | Updater | candidate crash before commit preserves/restores previous capsule |
| G65-UPD-REPLAY | Update trust | valid but stale signed metadata/package cannot lower rollback floor |
| G65-UPD-FILENAME-INDEPENDENT | Update identity | renaming executable does not break or authorize product identity |
| G65-UPD-HELPER-DIAGNOSTIC | Diagnostics | failed handoff remains durably/redacted diagnosable next launch |
| G65-MIGRATION-FAIL | Migration | failed migration preserves last bootable app and recoverable user DB |

Additional Sprint 14 matrix must combine these with Unicode/space paths, long paths, Defender/AV file
holds, sleep/resume, disk-full, destination removal, 429/reset storms, Core/UI/Worker hangs and
forced power-loss recovery.


## Sprint 10 additions

| ID | Area | Required result |
|---|---|---|
| S10-WIN-HANDLE-IDENTITY | Worker bootstrap | raw inherited HANDLE is reopened in child; parent CRT fd identity is never assumed |
| S10-WIN-CORE-HANG | Supervisor | Qt event-loop hang stops heartbeat and eventually terminates the supervised Job Object |
| S10-WIN-SLEEP | Supervisor | sleep/hibernate duration does not age the hang lease; false kill = 0 |
| S10-WIN-ASSIGN-BEFORE-RESUME | Process | Core is assigned to Job Object while suspended before its first instruction runs |
| S10-UI-RECONNECT | UI/Core | UI termination does not stop Core; relaunched UI can reconnect to authoritative projection |

| S10-UI-IPC-NONBLOCKING | UI/Core | Core/pipe delay does not block the Qt GUI thread; completion arrives asynchronously |
| S10-UI-IDEMPOTENT-REPLAY | UI/Core | response loss + reconnect reuses the same client/command identity and creates at most one mutation |
| S10-WORKER-PAUSE-OBSERVED | Worker control | active Pause becomes PAUSED only after durable PAUSE_OBSERVED |
| S10-WORKER-CANCEL-OBSERVED | Worker control | active Cancel becomes CANCELLED only after durable CANCEL_OBSERVED |
| S10-FILECOMMIT-FENCE | FileCommit | Pause/Cancel observed before FILE_COMMIT_GRANT leaves final FileRecord count unchanged |
| S10-HEALTH-PROBE-BOUNDED | Supervisor | unresponsive named pipe cannot block Supervisor health evaluation indefinitely |
