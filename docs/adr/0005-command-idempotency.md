# ADR 0005 — Durable command idempotency receipts

## Status

Accepted for Sprint 1.

## Decision

Every mutating UI command that requires idempotency uses the tuple
`(client_instance_id, command_id)` as its identity. The database transaction must:

1. look up an existing receipt;
2. reject reuse with a different command type or request SHA-256;
3. otherwise perform the domain mutation;
4. advance `state_revision` once;
5. persist the command result/receipt in the same SQLite transaction;
6. respond only after commit.

A replay after a lost response returns the original result and original committed
revision without repeating the mutation.

## Rationale

Network/local-IPC response loss can occur after the Core has durably committed a command.
Without a receipt, retrying `CREATE_JOB` can create duplicate Jobs. A payload hash also
prevents accidental reuse of the same idempotency key for semantically different input.
