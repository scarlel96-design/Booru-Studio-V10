from __future__ import annotations

import pytest

from booru_studio.common.errors import ErrorCode, ErrorConfidence, ErrorInstance


def test_error_evidence_is_frozen_copy() -> None:
    source = {"native": "10054"}
    error = ErrorInstance(
        code=ErrorCode.NETWORK_RESET,
        confidence=ErrorConfidence.EXACT,
        user_message_key="error.network_reset",
        retryable=True,
        evidence=source,
    )
    source["native"] = "changed"
    assert error.evidence["native"] == "10054"
    with pytest.raises(TypeError):
        error.evidence["x"] = "y"  # type: ignore[index]
