from __future__ import annotations

import sys
from pathlib import Path

from tools.sprint5_qml_smoke import qml_root


def test_qml_root_uses_source_tree_outside_pyinstaller(monkeypatch) -> None:
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert (qml_root() / "App.qml").is_file()


def test_qml_root_uses_pyinstaller_data_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert qml_root() == tmp_path / "booru_studio" / "ui" / "qml"
