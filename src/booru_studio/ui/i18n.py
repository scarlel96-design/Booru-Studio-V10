from __future__ import annotations

import json
from pathlib import Path


class TranslationCatalog:
    def __init__(self, root: Path | None = None, *, language: str = "en") -> None:
        self._root = root or Path(__file__).with_name("translations")
        self._catalogs = {
            "ko": self._load("ko_KR.json"),
            "en": self._load("en_US.json"),
        }
        self._language = "ko" if language.lower().startswith("ko") else "en"

    def _load(self, name: str) -> dict[str, str]:
        obj = json.loads((self._root / name).read_text(encoding="utf-8"))
        if not isinstance(obj, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in obj.items()):
            raise ValueError(f"invalid translation catalog: {name}")
        return dict(obj)

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> bool:
        normalized = "ko" if language.lower().startswith("ko") else "en"
        if normalized == self._language:
            return False
        self._language = normalized
        return True

    def text(self, key: str) -> str:
        return self._catalogs[self._language].get(key, key)

    def validate_parity(self) -> None:
        keys = [set(catalog) for catalog in self._catalogs.values()]
        if not keys or any(current != keys[0] for current in keys[1:]):
            raise ValueError("translation catalogs do not have identical key sets")
