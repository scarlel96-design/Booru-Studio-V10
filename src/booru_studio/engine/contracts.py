from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence
from urllib.parse import urlsplit, urlunsplit


class CapabilityLevel(StrEnum):
    EXACT = "EXACT"
    CONFIGURABLE = "CONFIGURABLE"
    BEST_EFFORT = "BEST_EFFORT"
    OPAQUE = "OPAQUE"
    UNSUPPORTED = "UNSUPPORTED"


class HandoffSafety(StrEnum):
    SAFE = "SAFE"
    CONDITIONAL = "CONDITIONAL"
    UNSAFE = "UNSAFE"


class RuntimeDurability(StrEnum):
    """Whether an execution object may cross the durable-state boundary."""

    EPHEMERAL_ONLY = "EPHEMERAL_ONLY"


class PauseSemantics(StrEnum):
    CHECKPOINT = "CHECKPOINT"
    RESTART_RESUME = "RESTART_RESUME"
    RESTART_PHASE = "RESTART_PHASE"
    UNSUPPORTED = "UNSUPPORTED"


class ResumeControl(StrEnum):
    V10_CHECKPOINT = "V10_CHECKPOINT"
    ENGINE_MANAGED = "ENGINE_MANAGED"
    RESTART_OPERATION = "RESTART_OPERATION"
    UNSUPPORTED = "UNSUPPORTED"


class ManagedNetworkControlLevel(StrEnum):
    EXACT = "EXACT"
    CONFIGURABLE = "CONFIGURABLE"
    BEST_EFFORT = "BEST_EFFORT"
    OPAQUE = "OPAQUE"


@dataclass(frozen=True, slots=True)
class ManagedNetworkEnvelope:
    """Truthful resource contract for an engine that may create internal network activity.

    ``granted_parallelism`` is a configuration value sent to engines that expose a concurrency
    control.  It is intentionally ``None`` for OPAQUE engines: the Core may reserve an
    ``admission_weight`` for them, but must not pretend that the real connection count is known.
    """

    requested_parallelism: int
    control_level: ManagedNetworkControlLevel
    admission_weight: int
    granted_parallelism: int | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.requested_parallelism <= 256:
            raise ValueError("requested_parallelism must be between 1 and 256")
        if not 1 <= self.admission_weight <= 256:
            raise ValueError("admission_weight must be between 1 and 256")
        if self.control_level is ManagedNetworkControlLevel.OPAQUE:
            if self.granted_parallelism is not None:
                raise ValueError("opaque engines cannot claim a configured parallelism")
            return
        if self.granted_parallelism is None:
            raise ValueError("non-opaque engines require granted_parallelism")
        if not 1 <= self.granted_parallelism <= self.requested_parallelism:
            raise ValueError("granted_parallelism must be within the requested bound")
        if self.admission_weight < self.granted_parallelism:
            raise ValueError("admission_weight cannot be smaller than granted_parallelism")

    @property
    def has_exact_connection_bound(self) -> bool:
        return self.control_level is ManagedNetworkControlLevel.EXACT


@dataclass(frozen=True, slots=True)
class RetryEnvelope:
    """Compound-attempt ceiling shared by V10 and a managed external engine.

    Limits are expressed as *attempt* ceilings (including the first attempt) to avoid retry-count
    off-by-one ambiguity.  The product must fit under ``hard_compound_attempt_ceiling`` so an
    external engine's internal retry loop cannot multiply V10's outer retry loop into an unbounded
    storm.
    """

    outer_episode_attempt_limit: int
    inner_operation_attempt_limit: int
    hard_compound_attempt_ceiling: int

    def __post_init__(self) -> None:
        values = (
            self.outer_episode_attempt_limit,
            self.inner_operation_attempt_limit,
            self.hard_compound_attempt_ceiling,
        )
        if any(value < 1 for value in values):
            raise ValueError("retry envelope attempt limits must be positive")
        if any(value > 100 for value in values):
            raise ValueError("retry envelope attempt limits are unreasonably large")
        if self.worst_case_attempts > self.hard_compound_attempt_ceiling:
            raise ValueError("compound retry product exceeds the hard attempt ceiling")

    @property
    def worst_case_attempts(self) -> int:
        return self.outer_episode_attempt_limit * self.inner_operation_attempt_limit


@dataclass(frozen=True, slots=True)
class ExecutionCapabilityProfile:
    """What V10 can honestly control for one planned engine execution path."""

    transfer_control: CapabilityLevel
    network_parallelism_control: CapabilityLevel
    progress_control: CapabilityLevel
    postprocess_control: CapabilityLevel
    pause_semantics: PauseSemantics
    resume_control: ResumeControl
    direct_handoff: HandoffSafety


@dataclass(frozen=True, slots=True)
class ManagedMediaExecutionPolicy:
    """Complete Core->Worker policy envelope for Sprint-7 managed media adapters."""

    capabilities: ExecutionCapabilityProfile
    network: ManagedNetworkEnvelope
    retry: RetryEnvelope


@dataclass(frozen=True, slots=True)
class EngineCapabilities:
    parallelism: CapabilityLevel = CapabilityLevel.UNSUPPORTED
    bandwidth_limit: CapabilityLevel = CapabilityLevel.UNSUPPORTED
    pause_resume: CapabilityLevel = CapabilityLevel.UNSUPPORTED
    exact_progress: CapabilityLevel = CapabilityLevel.UNSUPPORTED


@dataclass(frozen=True, slots=True)
class TransferDescriptor:
    url: str
    method: str = "GET"
    headers: Mapping[str, str] = field(default_factory=dict)
    referer: str | None = None
    credential_grant_id: str | None = None
    expected_size: int | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    expires_at_utc_ms: int | None = None
    origin_scope: str | None = None
    redirect_policy: str = "SAME_ORIGIN"
    network_scope_policy: str = "ANY"
    network_scope_root: str | None = None
    resume_semantics: str = "VALIDATOR_REQUIRED"
    handoff_safety: HandoffSafety = HandoffSafety.UNSAFE
    durability: RuntimeDurability = RuntimeDurability.EPHEMERAL_ONLY

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("transfer URL cannot be empty")
        if self.expected_size is not None and self.expected_size < 0:
            raise ValueError("expected_size cannot be negative")
        if self.durability is not RuntimeDurability.EPHEMERAL_ONLY:
            raise ValueError("TransferDescriptor must remain ephemeral")
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))

    def diagnostic_view(self) -> Mapping[str, object]:
        """Return a bounded secret-free representation safe for structured diagnostics.

        Header values, userinfo, query strings, fragments, credential grant identifiers and signed
        tokens are deliberately absent.  The method is diagnostic-only; it is not a persistence
        serialization format for the descriptor itself.
        """

        try:
            parts = urlsplit(self.url)
            host = parts.hostname or ""
            if parts.port is not None:
                host = f"{host}:{parts.port}"
            safe_url = urlunsplit((parts.scheme, host, parts.path, "", ""))
        except (TypeError, ValueError):
            safe_url = "invalid://redacted"
        return MappingProxyType({
            "url": safe_url,
            "method": self.method,
            "header_names": tuple(sorted({str(name).casefold() for name in self.headers})),
            "has_referer": self.referer is not None,
            "has_credential_grant": self.credential_grant_id is not None,
            "expected_size": self.expected_size,
            "content_type": self.content_type,
            "origin_scope": self.origin_scope,
            "redirect_policy": self.redirect_policy,
            "network_scope_policy": self.network_scope_policy,
            "has_network_scope_root": self.network_scope_root is not None,
            "resume_semantics": self.resume_semantics,
            "handoff_safety": self.handoff_safety.value,
            "durability": self.durability.value,
        })


class ProbeSupport(StrEnum):
    YES = "YES"
    MAYBE = "MAYBE"
    NO = "NO"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    support: ProbeSupport
    confidence: float
    specificity: int = 0
    cost_class: str = "LOW"
    requires_network_probe: bool = False
    requires_browser: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("probe confidence must be between 0 and 1")
        if self.specificity < 0:
            raise ValueError("probe specificity cannot be negative")


@dataclass(frozen=True, slots=True)
class CandidateArtifact:
    role: str
    suggested_filename: str
    descriptor: TransferDescriptor
    expected_size: int | None = None
    content_type: str | None = None

    def __post_init__(self) -> None:
        if not self.role:
            raise ValueError("artifact role cannot be empty")
        if not self.suggested_filename:
            raise ValueError("suggested filename cannot be empty")
        if self.expected_size is not None and self.expected_size < 0:
            raise ValueError("expected_size cannot be negative")


@dataclass(frozen=True, slots=True)
class NormalizedItemDescriptor:
    source_identity: str
    media_kind: str
    display_title: str
    source_index: int
    discovery_sequence: int
    candidate_artifacts: Sequence[CandidateArtifact] = field(default_factory=tuple)
    width: int | None = None
    height: int | None = None
    sanitized_metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_identity:
            raise ValueError("source identity cannot be empty")
        if not self.display_title:
            raise ValueError("display title cannot be empty")
        if self.source_index < 0 or self.discovery_sequence < 0:
            raise ValueError("item indices cannot be negative")
        object.__setattr__(self, "candidate_artifacts", tuple(self.candidate_artifacts))
        object.__setattr__(self, "sanitized_metadata", MappingProxyType(dict(self.sanitized_metadata)))


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    source_kind: str
    items: Sequence[NormalizedItemDescriptor] = field(default_factory=tuple)
    queued_inputs: Sequence[str] = field(default_factory=tuple)
    completeness: str = "COMPLETE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "queued_inputs", tuple(self.queued_inputs))


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    source_kind: str
    display_title: str
    descriptors: Sequence[TransferDescriptor] = field(default_factory=tuple)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "descriptors", tuple(self.descriptors))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class ResolverAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...

    def capabilities(self) -> EngineCapabilities: ...

    def resolve(self, raw_input: str) -> ResolutionResult: ...


class DiscoveryAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...

    def discover(self, raw_input: str) -> DiscoveryResult: ...


class TransferAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...

    def capabilities(self) -> EngineCapabilities: ...


class ManagedMediaAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...

    def capabilities(self) -> EngineCapabilities: ...


class BrowserAssistAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...


class PostProcessorAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...


class VerifierAdapter(Protocol):
    @property
    def adapter_id(self) -> str: ...
