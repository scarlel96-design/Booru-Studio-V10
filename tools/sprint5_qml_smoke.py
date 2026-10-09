from __future__ import annotations

"""Offscreen Sprint-5 QML runtime smoke gate.

This is intended for the network-enabled Windows development environment after the ``gui`` extra
has been installed.  It validates that the shipped QML shell can be instantiated with the real
ProjectionListModel role surface without starting a persistent Core process.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402

from booru_studio.ui.qt_models import ProjectionListModel  # noqa: E402


def qml_root() -> Path:
    """Resolve the shipped QML tree in either source or a PyInstaller capsule."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "booru_studio" / "ui" / "qml"
    return Path(__file__).parents[1] / "src" / "booru_studio" / "ui" / "qml"


class SmokeController(QObject):
    stateChanged = Signal()
    languageChanged = Signal()
    commandError = Signal(str)

    @Property(int, notify=stateChanged)
    def revision(self) -> int:
        return 0

    @Property(str, notify=stateChanged)
    def status(self) -> str:
        return "READY"

    @Property(bool, notify=stateChanged)
    def stale(self) -> bool:
        return False

    @Property(bool, notify=stateChanged)
    def pendingCommand(self) -> bool:  # noqa: N802
        return False

    @Property(bool, notify=stateChanged)
    def canSubmit(self) -> bool:  # noqa: N802
        return True

    @Property(bool, notify=stateChanged)
    def historyHasMore(self) -> bool:  # noqa: N802
        return False

    @Property(str, notify=languageChanged)
    def language(self) -> str:
        return "en"

    @Slot(str, result=str)
    def trKey(self, key: str) -> str:  # noqa: N802
        return key

    @Slot(str)
    def setLanguage(self, _language: str) -> None:  # noqa: N802
        return

    @Slot(result=bool)
    def refresh(self) -> bool:
        return True

    @Slot(str, result=bool)
    def submitInput(self, _raw_input: str) -> bool:  # noqa: N802
        return True

    @Slot(str, result=bool)
    def cancelJob(self, _job_id: str) -> bool:  # noqa: N802
        return True


def main() -> int:
    app = QGuiApplication([])
    controller = SmokeController()
    downloads = ProjectionListModel(controller)
    queue = ProjectionListModel(controller)
    history = ProjectionListModel(controller)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("appController", controller)
    engine.rootContext().setContextProperty("downloadsModel", downloads)
    engine.rootContext().setContextProperty("queueModel", queue)
    engine.rootContext().setContextProperty("historyModel", history)
    qml_path = qml_root() / "App.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    app.processEvents()
    if not engine.rootObjects():
        return 3
    engine.deleteLater()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
