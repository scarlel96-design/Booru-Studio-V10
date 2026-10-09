from __future__ import annotations

import sqlite3
from pathlib import Path

from booru_studio.domain.enums import (
    ArtifactLifecycle,
    CleanupState,
    ControlIntent,
    DiscoveryCompleteness,
    DiscoveryCycleState,
    EnginePackEligibility,
    FileCommitState,
    FileSystemState,
    ItemDisposition,
    ItemLifecycle,
    ItemOutcome,
    JobKind,
    JobLifecycle,
    JobOutcome,
    PathClaimState,
    RunOutcome,
)

SCHEMA_VERSION = 1
APPLICATION_ID = 0x42535631  # "BSV1"


def _values(enum_type: type) -> str:
    return ", ".join(f"'{member.value}'" for member in enum_type)


DDL = f"""
CREATE TABLE IF NOT EXISTS state_meta (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
    state_revision INTEGER NOT NULL CHECK (state_revision >= 0),
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS submissions (
    submission_id TEXT PRIMARY KEY,
    input_kind TEXT NOT NULL,
    redacted_input TEXT NOT NULL,
    created_at_utc_ms INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS storage_targets (
    storage_target_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    kind TEXT NOT NULL,
    normalized_root TEXT NOT NULL,
    identity_json TEXT NOT NULL,
    capability_json TEXT NOT NULL,
    last_verified_at_utc_ms INTEGER,
    created_at_utc_ms INTEGER NOT NULL,
    PRIMARY KEY(storage_target_id, generation)
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL REFERENCES submissions(submission_id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK (kind IN ({_values(JobKind)})),
    title TEXT NOT NULL,
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ({_values(JobLifecycle)})),
    outcome TEXT CHECK (outcome IS NULL OR outcome IN ({_values(JobOutcome)})),
    control_intent TEXT NOT NULL CHECK (control_intent IN ({_values(ControlIntent)})),
    activities_json TEXT NOT NULL DEFAULT '[]',
    waiting_reasons_json TEXT NOT NULL DEFAULT '[]',
    storage_target_id TEXT,
    storage_target_generation INTEGER,
    priority INTEGER NOT NULL DEFAULT 0,
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL,
    CHECK ((lifecycle = 'SETTLED' AND outcome IS NOT NULL) OR
           (lifecycle <> 'SETTLED' AND outcome IS NULL)),
    CHECK (storage_target_generation IS NULL OR storage_target_generation >= 0),
    CHECK ((storage_target_id IS NULL) = (storage_target_generation IS NULL)),
    FOREIGN KEY(storage_target_id, storage_target_generation)
        REFERENCES storage_targets(storage_target_id, generation) ON DELETE RESTRICT
) STRICT;

CREATE TABLE IF NOT EXISTS queue_entries (
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
    sort_key INTEGER NOT NULL,
    enqueued_at_utc_ms INTEGER NOT NULL,
    UNIQUE(sort_key)
) STRICT;

CREATE TABLE IF NOT EXISTS job_runs (
    run_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    engine_pack_id TEXT NOT NULL,
    execution_spec_json TEXT NOT NULL,
    runtime_policy_json TEXT NOT NULL,
    worker_generation INTEGER NOT NULL CHECK (worker_generation >= 0),
    started_at_utc_ms INTEGER NOT NULL,
    ended_at_utc_ms INTEGER,
    outcome TEXT CHECK (outcome IS NULL OR outcome IN ({_values(RunOutcome)})),
    CHECK ((ended_at_utc_ms IS NULL AND outcome IS NULL) OR
           (ended_at_utc_ms IS NOT NULL AND outcome IS NOT NULL))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_job_runs_job ON job_runs(job_id, started_at_utc_ms);
CREATE INDEX IF NOT EXISTS idx_job_runs_open ON job_runs(job_id) WHERE ended_at_utc_ms IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_job_runs_one_open
    ON job_runs(job_id) WHERE ended_at_utc_ms IS NULL;

CREATE TABLE IF NOT EXISTS discovery_cycles (
    cycle_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    cycle_sequence INTEGER NOT NULL CHECK (cycle_sequence >= 0),
    state TEXT NOT NULL CHECK (state IN ({_values(DiscoveryCycleState)})),
    completeness TEXT NOT NULL CHECK (completeness IN ({_values(DiscoveryCompleteness)})),
    next_batch_sequence INTEGER NOT NULL DEFAULT 0 CHECK (next_batch_sequence >= 0),
    created_at_utc_ms INTEGER NOT NULL,
    sealed_at_utc_ms INTEGER,
    UNIQUE(job_id, cycle_sequence)
) STRICT;

CREATE TABLE IF NOT EXISTS job_operation_attempts (
    attempt_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    run_id TEXT REFERENCES job_runs(run_id) ON DELETE CASCADE,
    operation_kind TEXT NOT NULL,
    attempt_sequence INTEGER NOT NULL CHECK (attempt_sequence >= 0),
    state TEXT NOT NULL,
    error_code TEXT,
    started_at_utc_ms INTEGER NOT NULL,
    ended_at_utc_ms INTEGER,
    UNIQUE(job_id, operation_kind, attempt_sequence)
) STRICT;

CREATE TABLE IF NOT EXISTS items (
    item_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    discovery_cycle_id TEXT REFERENCES discovery_cycles(cycle_id) ON DELETE SET NULL,
    source_key TEXT,
    display_title TEXT NOT NULL,
    source_index INTEGER,
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ({_values(ItemLifecycle)})),
    outcome TEXT CHECK (outcome IS NULL OR outcome IN ({_values(ItemOutcome)})),
    disposition TEXT CHECK (disposition IS NULL OR disposition IN ({_values(ItemDisposition)})),
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL,
    CHECK ((lifecycle = 'SETTLED' AND outcome IS NOT NULL) OR
           (lifecycle <> 'SETTLED' AND outcome IS NULL))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_items_job_source_index ON items(job_id, source_index, item_id);
CREATE INDEX IF NOT EXISTS idx_items_job_lifecycle ON items(job_id, lifecycle);
CREATE UNIQUE INDEX IF NOT EXISTS uq_items_source_key
    ON items(job_id, source_key) WHERE source_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS item_execution_attempts (
    attempt_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES job_runs(run_id) ON DELETE CASCADE,
    attempt_sequence INTEGER NOT NULL CHECK (attempt_sequence >= 0),
    state TEXT NOT NULL,
    error_code TEXT,
    started_at_utc_ms INTEGER NOT NULL,
    ended_at_utc_ms INTEGER,
    UNIQUE(item_id, attempt_sequence)
) STRICT;

CREATE TABLE IF NOT EXISTS operation_attempts (
    operation_id TEXT PRIMARY KEY,
    item_attempt_id TEXT REFERENCES item_execution_attempts(attempt_id) ON DELETE CASCADE,
    job_operation_attempt_id TEXT REFERENCES job_operation_attempts(attempt_id) ON DELETE CASCADE,
    operation_kind TEXT NOT NULL,
    attempt_sequence INTEGER NOT NULL CHECK (attempt_sequence >= 0),
    state TEXT NOT NULL,
    error_code TEXT,
    native_code TEXT,
    started_at_utc_ms INTEGER NOT NULL,
    ended_at_utc_ms INTEGER,
    CHECK ((item_attempt_id IS NOT NULL) <> (job_operation_attempt_id IS NOT NULL))
) STRICT;

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    item_id TEXT REFERENCES items(item_id) ON DELETE SET NULL,
    role TEXT NOT NULL,
    lifecycle TEXT NOT NULL CHECK (lifecycle IN ({_values(ArtifactLifecycle)})),
    filesystem_state TEXT NOT NULL CHECK (filesystem_state IN ({_values(FileSystemState)})),
    commit_owned INTEGER NOT NULL DEFAULT 0 CHECK (commit_owned IN (0, 1)),
    expected_size INTEGER CHECK (expected_size IS NULL OR expected_size >= 0),
    sha256 BLOB CHECK (sha256 IS NULL OR length(sha256) = 32),
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_artifacts_job ON artifacts(job_id, artifact_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_item ON artifacts(item_id, artifact_id);

CREATE TABLE IF NOT EXISTS path_claims (
    path_claim_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
    storage_target_id TEXT NOT NULL,
    storage_generation INTEGER NOT NULL CHECK (storage_generation >= 0),
    normalized_relative_path TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ({_values(PathClaimState)})),
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL,
    UNIQUE(storage_target_id, storage_generation, normalized_relative_path),
    FOREIGN KEY(storage_target_id, storage_generation)
        REFERENCES storage_targets(storage_target_id, generation) ON DELETE RESTRICT
) STRICT;

CREATE TABLE IF NOT EXISTS file_commit_intents (
    commit_intent_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
    path_claim_id TEXT NOT NULL REFERENCES path_claims(path_claim_id) ON DELETE RESTRICT,
    strategy TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ({_values(FileCommitState)})),
    staging_path TEXT NOT NULL,
    final_relative_path TEXT NOT NULL,
    expected_size INTEGER CHECK (expected_size IS NULL OR expected_size >= 0),
    expected_sha256 BLOB CHECK (expected_sha256 IS NULL OR length(expected_sha256) = 32),
    prepared_at_utc_ms INTEGER NOT NULL,
    terminal_at_utc_ms INTEGER
) STRICT;

CREATE INDEX IF NOT EXISTS idx_file_commit_open
    ON file_commit_intents(state, prepared_at_utc_ms)
    WHERE state IN ('PREPARED', 'UNCERTAIN');

CREATE TABLE IF NOT EXISTS file_records (
    file_record_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
    storage_target_id TEXT NOT NULL,
    storage_generation INTEGER NOT NULL CHECK (storage_generation >= 0),
    normalized_relative_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    sha256 BLOB CHECK (sha256 IS NULL OR length(sha256) = 32),
    filesystem_state TEXT NOT NULL CHECK (filesystem_state IN ({_values(FileSystemState)})),
    committed_at_utc_ms INTEGER NOT NULL,
    last_verified_at_utc_ms INTEGER,
    FOREIGN KEY(storage_target_id, storage_generation)
        REFERENCES storage_targets(storage_target_id, generation) ON DELETE RESTRICT
) STRICT;

CREATE TABLE IF NOT EXISTS resume_records (
    artifact_id TEXT PRIMARY KEY REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    part_path TEXT NOT NULL,
    sidecar_path TEXT NOT NULL,
    part_size INTEGER NOT NULL CHECK (part_size >= 0),
    source_fingerprint TEXT NOT NULL,
    validator_json TEXT NOT NULL,
    payload_checksum BLOB NOT NULL CHECK (length(payload_checksum) = 32),
    updated_at_utc_ms INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS collections (
    collection_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    parent_collection_id TEXT REFERENCES collections(collection_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    source_key TEXT,
    sort_index INTEGER,
    created_at_utc_ms INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS collection_memberships (
    collection_id TEXT NOT NULL REFERENCES collections(collection_id) ON DELETE CASCADE,
    item_id TEXT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
    sort_index INTEGER,
    PRIMARY KEY(collection_id, item_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS retry_episodes (
    retry_episode_id TEXT PRIMARY KEY,
    scope_kind TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    error_code TEXT NOT NULL,
    attempt_count INTEGER NOT NULL CHECK (attempt_count >= 0),
    hard_ceiling INTEGER NOT NULL CHECK (hard_ceiling >= 0),
    state TEXT NOT NULL,
    next_retry_at_utc_ms INTEGER,
    first_failure_at_utc_ms INTEGER NOT NULL,
    last_failure_at_utc_ms INTEGER NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_retry_scope ON retry_episodes(scope_kind, scope_id, state);

CREATE TABLE IF NOT EXISTS recovery_episodes (
    recovery_episode_id TEXT PRIMARY KEY,
    scope_kind TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    failure_signature TEXT NOT NULL,
    signature_version INTEGER NOT NULL CHECK (signature_version >= 1),
    automatic_recoveries INTEGER NOT NULL CHECK (automatic_recoveries >= 0),
    consecutive_failures INTEGER NOT NULL CHECK (consecutive_failures >= 0),
    state TEXT NOT NULL,
    first_failure_at_utc_ms INTEGER NOT NULL,
    last_failure_at_utc_ms INTEGER NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_recovery_scope
    ON recovery_episodes(scope_kind, scope_id, state);

CREATE TABLE IF NOT EXISTS rate_limit_gates (
    gate_key TEXT PRIMARY KEY,
    network_context_key TEXT NOT NULL,
    deadline_utc_ms INTEGER NOT NULL,
    source TEXT NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS command_receipts (
    client_instance_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    command_type TEXT NOT NULL,
    request_hash BLOB NOT NULL CHECK (length(request_hash) = 32),
    result_json TEXT NOT NULL,
    committed_state_revision INTEGER NOT NULL CHECK (committed_state_revision >= 0),
    committed_at_utc_ms INTEGER NOT NULL,
    PRIMARY KEY(client_instance_id, command_id)
) STRICT, WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS engine_pack_refs (
    run_id TEXT PRIMARY KEY REFERENCES job_runs(run_id) ON DELETE CASCADE,
    engine_pack_id TEXT NOT NULL,
    manifest_hash BLOB NOT NULL CHECK (length(manifest_hash) = 32),
    eligibility TEXT NOT NULL CHECK (eligibility IN ({_values(EnginePackEligibility)}))
) STRICT;

CREATE TABLE IF NOT EXISTS engine_quarantines (
    quarantine_key TEXT PRIMARY KEY,
    engine_pack_id TEXT NOT NULL,
    provider_key TEXT,
    capability_key TEXT,
    failure_signature TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS cleanup_obligations (
    cleanup_id TEXT PRIMARY KEY,
    owner_kind TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    storage_target_id TEXT NOT NULL,
    storage_generation INTEGER NOT NULL CHECK (storage_generation >= 0),
    relative_path TEXT NOT NULL,
    action TEXT NOT NULL,
    ownership_evidence_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ({_values(CleanupState)})),
    next_attempt_at_utc_ms INTEGER,
    last_error_code TEXT,
    created_at_utc_ms INTEGER NOT NULL,
    updated_at_utc_ms INTEGER NOT NULL,
    FOREIGN KEY(storage_target_id, storage_generation)
        REFERENCES storage_targets(storage_target_id, generation) ON DELETE RESTRICT
) STRICT;

CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    severity TEXT NOT NULL,
    component TEXT NOT NULL,
    failure_signature TEXT,
    summary_key TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at_utc_ms INTEGER NOT NULL,
    resolved_at_utc_ms INTEGER
) STRICT;

CREATE TABLE IF NOT EXISTS domain_events (
    event_id INTEGER PRIMARY KEY,
    state_revision INTEGER NOT NULL CHECK (state_revision >= 0),
    event_type TEXT NOT NULL,
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_utc_ms INTEGER NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_domain_events_revision
    ON domain_events(state_revision, event_id);

CREATE TABLE IF NOT EXISTS worker_sessions (
    worker_session_id TEXT PRIMARY KEY,
    core_instance_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES job_runs(run_id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    engine_pack_id TEXT NOT NULL,
    worker_generation INTEGER NOT NULL CHECK(worker_generation >= 0),
    expected_pid INTEGER NOT NULL CHECK(expected_pid > 0),
    endpoint_name TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('OPEN','AUTHENTICATED','RUNNING','CLOSED','FAILED')),
    last_contiguous_tx_seq INTEGER NOT NULL DEFAULT 0 CHECK(last_contiguous_tx_seq >= 0),
    opened_at_utc_ms INTEGER NOT NULL,
    closed_at_utc_ms INTEGER,
    UNIQUE(run_id, worker_generation)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_worker_sessions_open
    ON worker_sessions(state, opened_at_utc_ms)
    WHERE state <> 'CLOSED';

CREATE TABLE IF NOT EXISTS worker_tx_receipts (
    worker_session_id TEXT NOT NULL REFERENCES worker_sessions(worker_session_id) ON DELETE CASCADE,
    tx_seq INTEGER NOT NULL CHECK(tx_seq > 0),
    payload_hash BLOB NOT NULL CHECK(length(payload_hash)=32),
    tx_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    committed_at_utc_ms INTEGER NOT NULL,
    PRIMARY KEY(worker_session_id, tx_seq)
) STRICT, WITHOUT ROWID;
"""


def configure_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA synchronous=FULL")
    # journal_mode may return the actual selected mode (e.g. memory databases cannot use WAL).
    connection.execute("PRAGMA journal_mode=WAL")


def initialize_schema(connection: sqlite3.Connection, *, now_utc_ms: int) -> None:
    configure_connection(connection)
    connection.executescript(DDL)
    connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    connection.execute(
        """
        INSERT INTO state_meta(singleton_id, schema_version, state_revision,
                               created_at_utc_ms, updated_at_utc_ms)
        VALUES(1, ?, 0, ?, ?)
        ON CONFLICT(singleton_id) DO NOTHING
        """,
        (SCHEMA_VERSION, now_utc_ms, now_utc_ms),
    )
    connection.commit()


def open_database(path: Path, *, now_utc_ms: int) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    initialize_schema(connection, now_utc_ms=now_utc_ms)
    return connection
