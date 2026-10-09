from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Iterable
from urllib.parse import urlsplit


class NetworkScope(StrEnum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    LOOPBACK = "LOOPBACK"
    LINK_LOCAL = "LINK_LOCAL"
    MULTICAST = "MULTICAST"
    RESERVED = "RESERVED"
    UNSPECIFIED = "UNSPECIFIED"


class NetworkScopePolicyMode(StrEnum):
    ANY = "ANY"
    PUBLIC_ONLY = "PUBLIC_ONLY"
    ROOT_OR_PUBLIC = "ROOT_OR_PUBLIC"


class NetworkScopeBlocked(ValueError):
    pass


Resolver = Callable[[str, int | None], Iterable[str]]


def _default_resolver(host: str, port: int | None) -> tuple[str, ...]:
    rows = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    return tuple(dict.fromkeys(str(row[4][0]) for row in rows))


def classify_ip(value: str) -> NetworkScope:
    address = ipaddress.ip_address(value)
    if address.is_unspecified:
        return NetworkScope.UNSPECIFIED
    if address.is_loopback:
        return NetworkScope.LOOPBACK
    if address.is_link_local:
        return NetworkScope.LINK_LOCAL
    if address.is_multicast:
        return NetworkScope.MULTICAST
    if address.is_private:
        return NetworkScope.PRIVATE
    if address.is_reserved:
        return NetworkScope.RESERVED
    return NetworkScope.PUBLIC


def normalized_origin(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise NetworkScopeBlocked("only absolute http(s) URLs are permitted")
    if parts.username is not None or parts.password is not None:
        raise NetworkScopeBlocked("userinfo in network URLs is not permitted")
    default = 443 if parts.scheme == "https" else 80
    port = parts.port or default
    return f"{parts.scheme.lower()}://{parts.hostname.casefold().rstrip('.')}:{port}"


@dataclass(frozen=True, slots=True)
class NetworkScopeDecision:
    url: str
    origin: str
    addresses: tuple[str, ...]
    scopes: tuple[NetworkScope, ...]

    @property
    def public_only(self) -> bool:
        return bool(self.scopes) and all(scope is NetworkScope.PUBLIC for scope in self.scopes)


class NetworkScopePolicy:
    """Fail-closed destination policy used by Static Web and Browser Assist.

    A private/LAN destination is permitted only when the *user explicitly supplied* a private root
    and the request stays on that exact origin.  A public page can therefore never derive a request
    to localhost, RFC1918, link-local or another non-public address.  Mixed public/private DNS
    answers are rejected to reduce DNS-rebinding exposure.
    """

    def __init__(
        self,
        root_url: str,
        *,
        user_supplied_root: bool,
        allow_private_root: bool = False,
        resolver: Resolver | None = None,
    ) -> None:
        self._resolver = resolver or _default_resolver
        self.root_origin = normalized_origin(root_url)
        root = self.inspect(root_url)
        self.root_is_private = not root.public_only
        self.allow_private_root = bool(user_supplied_root and allow_private_root and self.root_is_private)
        if self.root_is_private and not self.allow_private_root:
            raise NetworkScopeBlocked("non-public root requires explicit private-network opt-in")

    def inspect(self, url: str) -> NetworkScopeDecision:
        origin = normalized_origin(url)
        parts = urlsplit(url)
        host = parts.hostname or ""
        lowered = host.casefold().rstrip(".")
        if lowered == "localhost" or lowered.endswith(".localhost"):
            addresses = ("127.0.0.1",)
        else:
            try:
                ipaddress.ip_address(host)
            except ValueError:
                try:
                    addresses = tuple(self._resolver(host, parts.port))
                except (OSError, socket.gaierror) as exc:
                    raise NetworkScopeBlocked("destination DNS resolution failed") from exc
            else:
                addresses = (host,)
        if not addresses:
            raise NetworkScopeBlocked("destination resolved to no addresses")
        scopes = tuple(classify_ip(value) for value in addresses)
        return NetworkScopeDecision(url=url, origin=origin, addresses=addresses, scopes=scopes)

    def authorize(self, url: str) -> NetworkScopeDecision:
        decision = self.inspect(url)
        if decision.public_only:
            return decision
        # Reject mixed DNS answers. A hostname that is both public and non-public is not a safe
        # deterministic target and is a common rebinding signal.
        if any(scope is NetworkScope.PUBLIC for scope in decision.scopes):
            raise NetworkScopeBlocked("mixed public/private DNS answers are blocked")
        if self.allow_private_root and decision.origin == self.root_origin:
            return decision
        raise NetworkScopeBlocked("derived non-public network destination is blocked")


def authorize_transfer_url(
    url: str,
    *,
    mode: NetworkScopePolicyMode,
    root_url: str | None = None,
    resolver: Resolver | None = None,
) -> NetworkScopeDecision | None:
    if mode is NetworkScopePolicyMode.ANY:
        normalized_origin(url)
        return None
    if mode is NetworkScopePolicyMode.PUBLIC_ONLY:
        policy = NetworkScopePolicy(url, user_supplied_root=True, allow_private_root=False, resolver=resolver)
        decision = policy.inspect(url)
        if not decision.public_only:
            raise NetworkScopeBlocked("non-public DirectHTTP destination is blocked")
        return decision
    if root_url is None:
        raise NetworkScopeBlocked("ROOT_OR_PUBLIC policy requires a root URL")
    return NetworkScopePolicy(root_url, user_supplied_root=True, allow_private_root=True, resolver=resolver).authorize(url)
