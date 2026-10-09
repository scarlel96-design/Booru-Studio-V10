from __future__ import annotations

import pytest

from booru_studio.engine.network_scope import NetworkScopeBlocked, NetworkScopePolicy, NetworkScopePolicyMode, authorize_transfer_url


def resolver(host: str, port: int | None):
    table = {
        "public.example": ("93.184.216.34",),
        "cdn.example": ("93.184.216.35",),
        "mixed.example": ("93.184.216.36", "10.0.0.8"),
        "internal.example": ("10.0.0.5",),
    }
    return table[host]


def test_public_page_cannot_derive_private_or_mixed_dns_target() -> None:
    policy = NetworkScopePolicy("https://public.example/page", user_supplied_root=True, resolver=resolver)
    assert policy.authorize("https://cdn.example/media.mp4").public_only
    with pytest.raises(NetworkScopeBlocked):
        policy.authorize("http://127.0.0.1/admin")
    with pytest.raises(NetworkScopeBlocked):
        policy.authorize("https://internal.example/secret")
    with pytest.raises(NetworkScopeBlocked):
        policy.authorize("https://mixed.example/rebind")


def test_explicit_private_root_allows_only_same_private_origin() -> None:
    policy = NetworkScopePolicy("http://10.0.0.5:8080/page", user_supplied_root=True, allow_private_root=True, resolver=resolver)
    assert policy.authorize("http://10.0.0.5:8080/media.mp4").origin == "http://10.0.0.5:8080"
    with pytest.raises(NetworkScopeBlocked):
        policy.authorize("http://10.0.0.6:8080/media.mp4")
    with pytest.raises(NetworkScopeBlocked):
        policy.authorize("http://10.0.0.5:9090/media.mp4")


def test_direct_http_public_only_scope_rejects_private_destination() -> None:
    with pytest.raises(NetworkScopeBlocked):
        authorize_transfer_url(
            "http://internal.example/file", mode=NetworkScopePolicyMode.PUBLIC_ONLY, resolver=resolver,
        )
