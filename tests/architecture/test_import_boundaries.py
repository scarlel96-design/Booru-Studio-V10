from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parents[2] / "src" / "booru_studio"


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module)
    return roots


def python_files(relative: str) -> list[Path]:
    return list((SRC / relative).rglob("*.py"))


def collect_violations(relative: str, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for path in python_files(relative):
        for imported in imported_roots(path):
            if imported.startswith(forbidden_prefixes):
                violations.append(f"{path.relative_to(SRC)} -> {imported}")
    return violations


def test_common_does_not_depend_on_higher_layers() -> None:
    forbidden = (
        "booru_studio.domain",
        "booru_studio.persistence",
        "booru_studio.scheduler",
        "booru_studio.engine",
        "booru_studio.ipc",
        "booru_studio.core",
        "booru_studio.worker",
        "booru_studio.ui",
    )
    assert collect_violations("common", forbidden) == []


def test_domain_has_no_framework_storage_or_higher_layer_dependencies() -> None:
    forbidden = (
        "PySide6",
        "sqlite3",
        "requests",
        "yt_dlp",
        "gallery_dl",
        "playwright",
        "booru_studio.persistence",
        "booru_studio.scheduler",
        "booru_studio.engine",
        "booru_studio.ipc",
        "booru_studio.core",
        "booru_studio.worker",
        "booru_studio.ui",
    )
    assert collect_violations("domain", forbidden) == []


def test_core_does_not_import_engine_implementations() -> None:
    forbidden = (
        "yt_dlp",
        "gallery_dl",
        "playwright",
        "requests",
        "booru_studio.engine.adapters",
    )
    assert collect_violations("core", forbidden) == []


def test_ui_does_not_import_storage_worker_or_engine_implementations() -> None:
    forbidden = (
        "sqlite3",
        "requests",
        "yt_dlp",
        "gallery_dl",
        "playwright",
        "booru_studio.persistence",
        "booru_studio.worker",
        "booru_studio.engine.adapters",
    )
    assert collect_violations("ui", forbidden) == []

def test_persistence_cannot_depend_on_secret_bearing_runtime_contracts() -> None:
    forbidden = (
        "booru_studio.engine.contracts",
        "booru_studio.engine.adapters",
        "yt_dlp",
        "gallery_dl",
        "playwright",
    )
    assert collect_violations("persistence", forbidden) == []


def test_update_contract_layer_has_no_ui_engine_or_storage_dependency() -> None:
    forbidden = (
        "PySide6",
        "sqlite3",
        "requests",
        "yt_dlp",
        "gallery_dl",
        "playwright",
        "booru_studio.persistence",
        "booru_studio.engine.adapters",
        "booru_studio.ui",
    )
    assert collect_violations("update", forbidden) == []

