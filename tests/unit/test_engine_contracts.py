from __future__ import annotations

import pytest

from booru_studio.engine.contracts import HandoffSafety, TransferDescriptor


def test_transfer_descriptor_freezes_headers() -> None:
    headers = {"Referer": "https://example.invalid"}
    descriptor = TransferDescriptor(
        url="https://cdn.example.invalid/file.jpg",
        headers=headers,
        handoff_safety=HandoffSafety.SAFE,
    )
    headers["Referer"] = "changed"
    assert descriptor.headers["Referer"] == "https://example.invalid"


def test_transfer_descriptor_rejects_negative_size() -> None:
    with pytest.raises(ValueError):
        TransferDescriptor(url="https://example.invalid/x", expected_size=-1)
