from __future__ import annotations

import ctypes
import json
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True, slots=True)
class SourceLocator:
    """Durable, non-secret source identity; its query is opt-in public metadata only."""

    scheme: str
    host: str
    path: str
    public_query: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_url(cls, raw_url: str, *, public_query_keys: frozenset[str] = frozenset()) -> "SourceLocator":
        parts = urlsplit(raw_url.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("source locator requires a public HTTP(S) URL")
        if any(ord(char) < 32 or ord(char) == 127 for char in parts.path):
            raise ValueError("source locator path contains a control character")
        host = parts.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        public_keys = {key.casefold() for key in public_query_keys}
        query = tuple((key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                      if key.casefold() in public_keys)
        return cls(parts.scheme, host, parts.path or "/", query)

    def durable_url(self) -> str:
        return urlunsplit((self.scheme, self.host, self.path, urlencode(self.public_query), ""))


@dataclass(frozen=True, slots=True)
class SourceSecretGrant:
    grant_id: str
    raw_query: str
    headers: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_url(cls, raw_url: str, *, headers: dict[str, str] | None = None) -> "SourceSecretGrant":
        return cls(uuid.uuid4().hex, urlsplit(raw_url.strip()).query,
                   tuple(sorted((headers or {}).items(), key=lambda item: item[0].casefold())))

    def serialize(self) -> bytes:
        return json.dumps({"raw_query": self.raw_query, "headers": self.headers},
                          ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    @classmethod
    def deserialize(cls, grant_id: str, raw: bytes) -> "SourceSecretGrant":
        if len(raw) > 64 * 1024:
            raise ValueError("source grant is too large")
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict) or set(value) != {"raw_query", "headers"}:
            raise ValueError("corrupted source grant")
        headers = value.get("headers", [])
        if not isinstance(value.get("raw_query"), str) or not isinstance(headers, list):
            raise ValueError("corrupted source grant")
        if len(headers) > 64 or len(value["raw_query"]) > 16_384:
            raise ValueError("source grant exceeds limits")
        if any(not isinstance(pair, list) or len(pair) != 2 or
               not all(isinstance(item, str) for item in pair) or
               any("\r" in item or "\n" in item for item in pair) for pair in headers):
            raise ValueError("corrupted source grant headers")
        return cls(grant_id, value["raw_query"], tuple((key, item) for key, item in headers))


class SourceGrantStore:
    """User-bound DPAPI store; durable databases receive only the opaque grant id."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, grant_id: str) -> Path:
        if len(grant_id) != 32 or any(char not in "0123456789abcdef" for char in grant_id):
            raise ValueError("invalid grant id")
        return self.root / f"{grant_id}.grant"

    def _ensure_root(self) -> None:
        _reject_reparse_chain(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        _reject_reparse_chain(self.root)

    def save(self, grant: SourceSecretGrant) -> None:
        self._ensure_root()
        target = self._path(grant.grant_id)
        _reject_reparse_chain(target)
        if target.exists():
            raise ValueError("grant already exists or is unsafe")
        temporary = self.root / f".{grant.grant_id}.{uuid.uuid4().hex}.tmp"
        protected = _protect(grant.serialize())
        try:
            with temporary.open("xb") as handle:
                handle.write(protected)
                handle.flush()
                os.fsync(handle.fileno())
            _reject_reparse_chain(target)
            # Link creation fails if a concurrent writer has already created the
            # target; os.replace would silently overwrite that existing grant.
            os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self, grant_id: str) -> SourceSecretGrant:
        self._ensure_root()
        target = self._path(grant_id)
        _reject_reparse_chain(target)
        if not target.is_file():
            raise ValueError("grant is missing or unsafe")
        return SourceSecretGrant.deserialize(grant_id, _unprotect(target.read_bytes()))


def _reject_reparse_chain(path: Path) -> None:
    current = path
    while True:
        try:
            info = current.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(info.st_mode) or (
                os.name == "nt" and
                info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise ValueError("grant path contains a reparse point")
        if current.parent == current:
            return
        current = current.parent


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _crypt(data: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise OSError("Source grants require Windows DPAPI")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    source_buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    result = _Blob()
    if protect:
        fn = crypt32.CryptProtectData
        fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_Blob)]
        fn.restype = ctypes.c_int
        ok = fn(ctypes.byref(source), "BooruStudio.SourceGrant.v1", None, None, None, 1, ctypes.byref(result))
    else:
        fn = crypt32.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_Blob)]
        fn.restype = ctypes.c_int
        ok = fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    if not ok:
        raise OSError(ctypes.get_last_error(), "DPAPI operation failed")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(result.pbData)


def _protect(data: bytes) -> bytes:
    return _crypt(data, protect=True)


def _unprotect(data: bytes) -> bytes:
    return _crypt(data, protect=False)
