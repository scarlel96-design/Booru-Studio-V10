from __future__ import annotations

import pytest

from booru_studio.domain.presentation import (
    CollectionSemantics,
    MediaPresentationContract,
    PresentationMode,
)
from booru_studio.engine.contracts import (
    CapabilityLevel,
    ExecutionCapabilityProfile,
    HandoffSafety,
    ManagedMediaExecutionPolicy,
    ManagedNetworkControlLevel,
    ManagedNetworkEnvelope,
    PauseSemantics,
    ResumeControl,
    RetryEnvelope,
    RuntimeDurability,
    TransferDescriptor,
)


def test_single_media_is_individual_and_collections_are_batches() -> None:
    single = MediaPresentationContract.single_media()
    assert single.mode is PresentationMode.INDIVIDUAL
    assert single.collection is CollectionSemantics.NONE
    assert MediaPresentationContract.playlist().collection is CollectionSemantics.PLAYLIST
    assert MediaPresentationContract.channel().collection is CollectionSemantics.CHANNEL
    assert MediaPresentationContract.multi_input().mode is PresentationMode.BATCH
    assert MediaPresentationContract.gallery().collection is CollectionSemantics.GALLERY


def test_presentation_contract_rejects_ambiguous_semantics() -> None:
    with pytest.raises(ValueError, match="individual"):
        MediaPresentationContract(PresentationMode.INDIVIDUAL, CollectionSemantics.PLAYLIST)
    with pytest.raises(ValueError, match="batch"):
        MediaPresentationContract(PresentationMode.BATCH, CollectionSemantics.NONE)


def test_managed_network_envelope_never_claims_unknown_parallelism() -> None:
    exact = ManagedNetworkEnvelope(
        requested_parallelism=4,
        granted_parallelism=3,
        admission_weight=3,
        control_level=ManagedNetworkControlLevel.EXACT,
    )
    assert exact.has_exact_connection_bound is True

    opaque = ManagedNetworkEnvelope(
        requested_parallelism=4,
        granted_parallelism=None,
        admission_weight=4,
        control_level=ManagedNetworkControlLevel.OPAQUE,
    )
    assert opaque.has_exact_connection_bound is False

    with pytest.raises(ValueError, match="opaque"):
        ManagedNetworkEnvelope(
            requested_parallelism=4,
            granted_parallelism=4,
            admission_weight=4,
            control_level=ManagedNetworkControlLevel.OPAQUE,
        )


def test_compound_retry_envelope_blocks_retry_multiplication() -> None:
    bounded = RetryEnvelope(
        outer_episode_attempt_limit=3,
        inner_operation_attempt_limit=2,
        hard_compound_attempt_ceiling=6,
    )
    assert bounded.worst_case_attempts == 6

    with pytest.raises(ValueError, match="compound"):
        RetryEnvelope(
            outer_episode_attempt_limit=5,
            inner_operation_attempt_limit=10,
            hard_compound_attempt_ceiling=12,
        )


def test_execution_capability_profile_can_report_non_exact_managed_media() -> None:
    profile = ExecutionCapabilityProfile(
        transfer_control=CapabilityLevel.CONFIGURABLE,
        network_parallelism_control=CapabilityLevel.BEST_EFFORT,
        progress_control=CapabilityLevel.BEST_EFFORT,
        postprocess_control=CapabilityLevel.CONFIGURABLE,
        pause_semantics=PauseSemantics.RESTART_PHASE,
        resume_control=ResumeControl.ENGINE_MANAGED,
        direct_handoff=HandoffSafety.UNSAFE,
    )
    assert profile.network_parallelism_control is not CapabilityLevel.EXACT
    assert profile.direct_handoff is HandoffSafety.UNSAFE


def test_transfer_descriptor_is_ephemeral_and_diagnostic_view_is_secret_free() -> None:
    descriptor = TransferDescriptor(
        url="https://user:password@cdn.example.test/media.mp4?token=TOP_SECRET&sig=abc#fragment",
        headers={
            "Authorization": "Bearer SUPER_SECRET",
            "Cookie": "session=COOKIE_SECRET",
            "Referer": "https://site.example.test/post/1?auth=REF_SECRET",
        },
        referer="https://site.example.test/post/1?auth=REF_SECRET",
        credential_grant_id="credential-secret-ref",
        handoff_safety=HandoffSafety.UNSAFE,
    )
    assert descriptor.durability is RuntimeDurability.EPHEMERAL_ONLY
    view = dict(descriptor.diagnostic_view())
    rendered = repr(view)
    for secret in (
        "TOP_SECRET",
        "SUPER_SECRET",
        "COOKIE_SECRET",
        "REF_SECRET",
        "password",
        "credential-secret-ref",
    ):
        assert secret not in rendered
    assert view["url"] == "https://cdn.example.test/media.mp4"
    assert view["has_credential_grant"] is True
    assert set(view["header_names"]) == {"authorization", "cookie", "referer"}

def test_managed_media_policy_bundles_capability_network_and_retry_contracts() -> None:
    capability = ExecutionCapabilityProfile(
        transfer_control=CapabilityLevel.CONFIGURABLE,
        network_parallelism_control=CapabilityLevel.CONFIGURABLE,
        progress_control=CapabilityLevel.BEST_EFFORT,
        postprocess_control=CapabilityLevel.CONFIGURABLE,
        pause_semantics=PauseSemantics.RESTART_PHASE,
        resume_control=ResumeControl.ENGINE_MANAGED,
        direct_handoff=HandoffSafety.UNSAFE,
    )
    network = ManagedNetworkEnvelope(
        requested_parallelism=4, granted_parallelism=3, admission_weight=3,
        control_level=ManagedNetworkControlLevel.CONFIGURABLE,
    )
    retry = RetryEnvelope(3, 2, 6)
    policy = ManagedMediaExecutionPolicy(capability, network, retry)
    assert policy.network.granted_parallelism == 3
    assert policy.retry.worst_case_attempts == 6

