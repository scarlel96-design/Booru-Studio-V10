from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def redact_input_for_storage(raw: str) -> str:
    """Keep only a URL's public location; query names and values are private by default.

    Signed-URL vendors use arbitrary query keys, so a deny-list cannot establish
    that an unfamiliar key is safe to persist in SQLite, logs, or UI snapshots.
    """
    value = raw.strip()
    if not value.lower().startswith(("http://", "https://")):
        return value
    parts = urlsplit(value)
    hostname = (parts.hostname or "").lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    if parts.port is not None:
        hostname = f"{hostname}:{parts.port}"
    return urlunsplit((parts.scheme.lower(), hostname, parts.path, "", ""))
