from __future__ import annotations

from pathlib import Path

import pytest

from booru_studio.domain.source_grant import SourceGrantStore, SourceLocator, SourceSecretGrant


def test_locator_drops_signed_query_and_grant_is_not_plaintext(tmp_path: Path) -> None:
    raw = "https://cdn.example/path/file.jpg?Policy=secret-policy&Key-Pair-Id=key&token=private&id=42"
    locator = SourceLocator.from_url(raw, public_query_keys=frozenset({"id"}))
    assert locator.durable_url() == "https://cdn.example/path/file.jpg?id=42"
    grant = SourceSecretGrant.from_url(raw, headers={"Authorization": "Bearer private"})
    store = SourceGrantStore(tmp_path / "grants")
    store.save(grant)
    assert "secret-policy" not in (tmp_path / "grants" / f"{grant.grant_id}.grant").read_bytes().decode("latin1")
    assert store.load(grant.grant_id) == grant


def test_locator_handles_ipv6_and_rejects_controls() -> None:
    assert SourceLocator.from_url("https://[::1]:8443/file?Policy=secret").durable_url() == (
        "https://[::1]:8443/file"
    )
    with pytest.raises(ValueError):
        SourceLocator.from_url("https://example.test/path\x00bad")


def test_grant_save_does_not_overwrite_existing_target_or_legacy_temp(tmp_path: Path) -> None:
    store = SourceGrantStore(tmp_path / "grants")
    store._ensure_root()
    grant = SourceSecretGrant.from_url("https://example.test/file?Policy=private")
    target = store._path(grant.grant_id)
    target.write_bytes(b"foreign")
    legacy_temp = target.with_suffix(".tmp")
    legacy_temp.write_bytes(b"unrelated")
    with pytest.raises(ValueError):
        store.save(grant)
    assert target.read_bytes() == b"foreign"
    assert legacy_temp.read_bytes() == b"unrelated"


def test_malformed_grant_payload_is_rejected() -> None:
    grant_id = "a" * 32
    for raw in (b"[]", b'{"raw_query":"x","headers":[["Authorization",3]]}',
                b'{"raw_query":"x","headers":[["X-Test","a\\nb"]]}'):
        with pytest.raises(ValueError):
            SourceSecretGrant.deserialize(grant_id, raw)


def test_corrupt_or_symlink_grant_fails_closed(tmp_path: Path) -> None:
    store = SourceGrantStore(tmp_path / "grants")
    store._ensure_root()
    bad = "a" * 32
    (tmp_path / "grants" / f"{bad}.grant").write_bytes(b"corrupt")
    with pytest.raises((OSError, ValueError)):
        store.load(bad)
