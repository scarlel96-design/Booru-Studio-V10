# Booru Studio V10 — Sprint 3 Sealed Implementation Report

## Scope completed

Sprint 3 is cumulative over Sprint 0/1/2 and adds the first Core↔Worker process/control
boundary without attaching the future DirectHTTP execution plane.

Implemented:

1. CoreInstanceId / WorkerSessionId and random single-use Worker endpoint identity.
2. Bounded Worker bootstrap with 32-byte secret and Run/Job/EnginePack/PID/generation binding.
3. One-shot inherited bootstrap pipe plus Windows STARTUPINFOEX handle-list source path.
4. Mutual HMAC-SHA256 Core/Worker challenge-response with fresh nonces.
5. HKDF-SHA256 directional session-key derivation.
6. Authentication transcript binding protocol version and both capability sets.
7. Strict Core↔Worker protocol-v1 envelope/payload validation.
8. Transport-independent envelope connection contract.
9. Production-target QLocal server/socket adapter using Qt UserAccessOption.
10. Explicit `--source-stdio-harness` for deterministic Linux process E2E.
11. Durable WorkerSession / WorkerTxReceipt SQLite state.
12. Bounded monotonic Worker transaction lane with contiguous cumulative ACK.
13. Exact replay acceptance, altered replay conflict and sequence-gap rejection.
14. Worker side effect + receipt + sequence advance in one SQLite transaction.
15. Replay-safe durable `CANCEL_JOB` and `CANCEL_REQUESTED` intent.
16. Real subprocess source E2E from bootstrap through authentication, START_RUN and clean Cancel.

## Sealed cumulative validation

Environment: Linux container, CPython 3.13.5. PySide6 is not installed.

- `python -m compileall -q src tests`: PASS
- cumulative `pytest -q`: **96 passed**
- all Sprint 0/1/2 regressions included in the same run: PASS
- bootstrap 32-byte secret/PID fencing tests: PASS
- authentication transcript identity-binding matrix: PASS
- distinct deterministic directional session keys: PASS
- Worker transaction replay/gap/conflict tests: PASS
- same-transaction side-effect rollback: PASS
- durable/idempotent Cancel command: PASS
- real Worker subprocess bootstrap/auth/START_RUN/tx1/Cancel/tx2/GOODBYE: PASS
- 25 sequential real source Worker process lifecycle stress: PASS
  - Worker sessions CLOSED: 25
  - durable Worker transaction receipts: 50
  - open Worker sessions: 0
  - SQLite `integrity_check=ok`
- 250 sequential Artifact commit stress: PASS
  - COMMITTED Artifacts / FileRecords / COMMITTED PathClaims: 250 / 250 / 250
  - open FileCommitIntents: 0
  - SQLite `integrity_check=ok`

## Security/correctness properties demonstrated in source QA

- Bootstrap secret bytes are not part of the Worker argv contract used by the source harness.
- PID, Run, Job, EnginePack, generation, endpoint and capabilities are authentication-bound.
- Directional derived keys are distinct.
- Same Worker transaction sequence cannot be rebound to altered payload content.
- Worker durable side effects cannot commit without the matching receipt/sequence transaction.
- Repeated Cancel command does not invent another state revision.
- Command acceptance and Worker cancellation observation are separate durable facts.

## Validation boundary

Production-target QLocal and Windows inherited-HANDLE code paths are implemented in source,
but not runtime-tested here because this environment is Linux and lacks PySide6. The source
process E2E substitutes only the byte transport with stdio. It does not prove Windows QLocal
named-pipe behavior, Windows HANDLE inheritance, Frozen Worker executable resolution, Job
Objects or executable containment.

No real HTTP transfer, Scheduler, gallery-dl, yt-dlp, FFmpeg, QML, native Supervisor or
Updater is implemented/validated in Sprint 3.
