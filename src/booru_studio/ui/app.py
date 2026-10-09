from __future__ import annotations

import locale
import os
import sys
from pathlib import Path

from booru_studio.common.text_safety import sanitize_display_text
from booru_studio.ui.action_controller import ActionController
from booru_studio.ui.i18n import TranslationCatalog
from booru_studio.ui.projection_store import ProjectionStore
from booru_studio.ui.platform_actions import open_file, reveal_file


def default_state_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "BooruStudio" / "V10" / "booru-studio.sqlite3"
    return Path.home() / ".local" / "share" / "BooruStudio" / "V10" / "booru-studio.sqlite3"


def main() -> int:
    try:
        from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine
    except ImportError:
        print(
            "PySide6 is required for the Sprint 5 GUI. Install with: uv sync --extra dev --extra gui",
            file=sys.stderr,
        )
        return 2

    from booru_studio.ui.qt_models import ProjectionListModel

    endpoint = os.environ.get("BOORU_STUDIO_CORE_ENDPOINT", "").strip()
    packaged = os.environ.get("BOORU_STUDIO_PACKAGED", "").strip().lower() in {"1", "true", "yes"}
    if packaged and not endpoint:
        print("Packaged Booru Studio UI requires BOORU_STUDIO_CORE_ENDPOINT", file=sys.stderr)
        return 4

    class Controller(QObject):
        revisionChanged = Signal()
        uiStateChanged = Signal()
        languageChanged = Signal()
        commandError = Signal(str)
        submissionCommitted = Signal(str)
        remoteProjection = Signal(object)
        remoteError = Signal(str, bool, bool)
        remoteIdle = Signal()
        remoteSuccess = Signal(str, object)

        def __init__(self) -> None:
            super().__init__()
            self.downloads = ProjectionListModel(self)
            self.queue = ProjectionListModel(self)
            self.history = ProjectionListModel(self)
            self._store = ProjectionStore()
            language = (locale.getlocale()[0] or "en").lower()
            self._i18n = TranslationCatalog(language=language)
            self._i18n.validate_parity()
            self._connected = not bool(endpoint)
            self._pending_command = False
            self._closed = False
            self.remoteProjection.connect(self._apply)
            self.remoteError.connect(self._handle_remote_error)
            self.remoteIdle.connect(self._handle_remote_idle)
            self.remoteSuccess.connect(self._handle_remote_success)
            if endpoint:
                from booru_studio.ui.remote_backend import RemoteUiBackend
                self._backend = RemoteUiBackend(
                    endpoint,
                    lambda snapshot: self.remoteProjection.emit(snapshot),
                    on_error=lambda message, may_desync, disconnected: self.remoteError.emit(message, may_desync, disconnected),
                    on_idle=lambda: self.remoteIdle.emit(),
                    on_success=lambda operation, context: self.remoteSuccess.emit(operation, context),
                )
            else:
                # Development-only fallback. Packaged mode fails closed above if no endpoint exists.
                from booru_studio.core.source_ui_backend import SourceUiBackend
                self._backend = SourceUiBackend(default_state_path(), self._apply)
            self._async_backend = bool(getattr(self._backend, "is_async", False))
            self._refresh(mark_busy=False)

        def close(self) -> None:
            if self._closed:
                return
            self._closed = True
            self._connected = False
            self.uiStateChanged.emit()
            self._backend.close()

        def _apply(self, snapshot: dict[str, object]) -> None:
            if self._store.apply_snapshot(snapshot):
                state = self._store.state
                self.downloads.replace(state.downloads)
                self.queue.replace(state.queue)
                self.history.replace(state.history)
                self.revisionChanged.emit()
            self._connected = True
            self.uiStateChanged.emit()

        def _handle_remote_error(self, message: str, may_desync: bool, disconnected: bool) -> None:
            if may_desync:
                self._store.mark_stale()
            if disconnected:
                self._connected = False
            safe = sanitize_display_text(message, limit=512).strip()
            self.commandError.emit(safe or "The operation could not be completed.")
            self.uiStateChanged.emit()

        def _handle_remote_idle(self) -> None:
            self._set_pending(False)

        def _handle_remote_success(self, operation: str, context: object) -> None:
            if operation == "submit" and isinstance(context, str):
                self.submissionCommitted.emit(context)

        def _set_pending(self, value: bool) -> None:
            if value == self._pending_command:
                return
            self._pending_command = value
            self.uiStateChanged.emit()

        def _surface_error(self, exc: BaseException, *, may_desync: bool) -> None:
            if may_desync:
                self._store.mark_stale()
            message = sanitize_display_text(str(exc), limit=512).strip()
            self.commandError.emit(message or "The operation could not be completed.")
            self.uiStateChanged.emit()

        def _refresh(self, *, mark_busy: bool = True) -> bool:
            if self._closed:
                return False
            if mark_busy:
                self._set_pending(True)
            try:
                self._backend.refresh()
                return True
            except Exception as exc:
                self._surface_error(exc, may_desync=True)
                return False
            finally:
                if mark_busy and not self._async_backend:
                    self._set_pending(False)

        def _actions(self):
            return ActionController.evaluate(
                connected=self._connected and not self._closed,
                stale=self._store.state.stale,
                pending_command=self._pending_command,
                selected_lifecycle=None,
            )

        @Property(int, notify=revisionChanged)
        def revision(self) -> int:
            return self._store.state.projection_revision

        @Property(str, notify=uiStateChanged)
        def status(self) -> str:
            if self._closed or not self._connected:
                return "DISCONNECTED"
            if self._pending_command:
                return "BUSY"
            if self._store.state.stale:
                return "STALE"
            return "READY"

        @Property(bool, notify=uiStateChanged)
        def stale(self) -> bool:
            return self._store.state.stale

        @Property(bool, notify=uiStateChanged)
        def pendingCommand(self) -> bool:  # noqa: N802 - QML API
            return self._pending_command

        @Property(bool, notify=uiStateChanged)
        def canSubmit(self) -> bool:  # noqa: N802 - QML API
            return self._actions().can_submit

        @Property(bool, notify=uiStateChanged)
        def historyHasMore(self) -> bool:  # noqa: N802 - QML API
            return self._store.state.history_has_more

        @Property(str, notify=languageChanged)
        def language(self) -> str:
            return self._i18n.language

        @Slot(str, result=str)
        def trKey(self, key: str) -> str:  # noqa: N802 - QML API
            return self._i18n.text(key)

        @Slot(str)
        def setLanguage(self, language: str) -> None:  # noqa: N802 - QML API
            if self._i18n.set_language(language):
                self.languageChanged.emit()

        @Slot(result=bool)
        def refresh(self) -> bool:
            return self._refresh(mark_busy=True)

        @Slot(str, result=bool)
        def submitInput(self, raw_input: str) -> bool:  # noqa: N802 - QML API
            if not self.canSubmit:
                return False
            self._set_pending(True)
            try:
                self._backend.submit(raw_input)
                if not self._async_backend:
                    self.submissionCommitted.emit(raw_input)
                return True
            except Exception as exc:
                self._surface_error(exc, may_desync=isinstance(exc, (TimeoutError, RuntimeError)))
                return False
            finally:
                if not self._async_backend:
                    self._set_pending(False)

        @Slot(str, result=bool)
        def cancelJob(self, job_id: str) -> bool:  # noqa: N802 - QML API
            if self._closed or self._store.state.stale or self._pending_command:
                return False
            self._set_pending(True)
            try:
                self._backend.cancel(job_id)
                return True
            except Exception as exc:
                self._surface_error(exc, may_desync=isinstance(exc, (TimeoutError, RuntimeError)))
                return False
            finally:
                if not self._async_backend:
                    self._set_pending(False)

        def _job_command(self, operation, *args) -> bool:
            if self._closed or self._store.state.stale or self._pending_command:
                return False
            self._set_pending(True)
            try:
                operation(*args)
                return True
            except Exception as exc:
                self._surface_error(exc, may_desync=isinstance(exc, (TimeoutError, RuntimeError)))
                return False
            finally:
                if not self._async_backend:
                    self._set_pending(False)

        @Slot(str, result=bool)
        def pauseJob(self, job_id: str) -> bool:  # noqa: N802
            return self._job_command(self._backend.pause, job_id)

        @Slot(str, result=bool)
        def resumeJob(self, job_id: str) -> bool:  # noqa: N802
            return self._job_command(self._backend.resume, job_id)

        @Slot(str, str, result=bool)
        def moveQueueJob(self, job_id: str, direction: str) -> bool:  # noqa: N802
            return self._job_command(self._backend.move_queue, job_id, direction)

        @Slot(str, str, result=bool)
        def canJobAction(self, lifecycle: str, action: str) -> bool:  # noqa: N802
            state = ActionController.evaluate(connected=self._connected and not self._closed, stale=self._store.state.stale, pending_command=self._pending_command, selected_lifecycle=lifecycle)
            return {"cancel": state.can_cancel, "pause": state.can_pause, "resume": state.can_resume}.get(action, False)

        @Slot(str, result=bool)
        def openDownloadedFile(self, path: str) -> bool:  # noqa: N802
            try:
                open_file(path)
                return True
            except Exception as exc:
                self._surface_error(exc, may_desync=False)
                return False

        @Slot(str, result=bool)
        def revealDownloadedFile(self, path: str) -> bool:  # noqa: N802
            try:
                reveal_file(path)
                return True
            except Exception as exc:
                self._surface_error(exc, may_desync=False)
                return False

    app = QGuiApplication(sys.argv)
    app.setApplicationName("Booru Studio")
    app.setApplicationDisplayName("Booru Studio")
    app.setOrganizationName("Booru Studio")
    controller = Controller()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("appController", controller)
    engine.rootContext().setContextProperty("downloadsModel", controller.downloads)
    engine.rootContext().setContextProperty("queueModel", controller.queue)
    engine.rootContext().setContextProperty("historyModel", controller.history)
    qml_path = Path(__file__).with_name("qml") / "App.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        controller.close()
        return 3
    app.aboutToQuit.connect(controller.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
