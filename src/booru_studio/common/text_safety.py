from __future__ import annotations

import unicodedata

# Unicode bidi controls and isolates can visually reorder untrusted remote names.
_BIDI_CONTROLS = {
    "\u061c", "\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
    "\u2066", "\u2067", "\u2068", "\u2069",
}


def sanitize_display_text(value: str, *, limit: int = 2048) -> str:
    out: list[str] = []
    for char in value:
        if char in _BIDI_CONTROLS:
            continue
        category = unicodedata.category(char)
        if category in {"Cc", "Cs"} and char not in {"\t", "\n"}:
            continue
        out.append(char)
        if len(out) >= limit:
            break
    return "".join(out)
