# ADR 0008 — Private Worker bootstrap and mutual authentication

Status: Accepted.

Worker bootstrap secret material is delivered via a one-shot inherited pipe/handle and binds
Worker PID, WorkerSession, JobRun, Job, EnginePack, generation and endpoint. Core/Worker then
perform mutual HMAC-SHA256 proof verification with fresh nonces and derive directional HKDF
session keys. Endpoint randomness is not treated as authentication.
