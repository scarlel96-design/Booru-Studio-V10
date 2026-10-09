from __future__ import annotations

from typing import Any, Iterable, Mapping

from booru_studio.ui.models.list_data import ListData

try:  # Import-safe in source QA environments where the GUI extra is not installed.
    from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt
except ImportError:  # pragma: no cover - environment dependent
    QAbstractListModel = None  # type: ignore[assignment,misc]


if QAbstractListModel is not None:
    class ProjectionListModel(QAbstractListModel):
        _ROLE_NAMES = (
            "job_id", "title", "kind", "lifecycle", "outcome", "control_intent",
            "primary_activity", "waiting_reason", "priority", "position", "display_input",
            "item_total", "item_settled", "artifact_total", "artifact_committed",
            "committed_bytes", "expected_bytes", "progress", "created_at_utc_ms",
            "updated_at_utc_ms", "primary_file_path", "latest_error_code", "latest_native_code",
        )

        def __init__(self, parent=None) -> None:
            super().__init__(parent)
            self._data = ListData()
            self._roles = {Qt.UserRole + 1 + i: name for i, name in enumerate(self._ROLE_NAMES)}

        def roleNames(self):  # noqa: N802 - Qt API
            return {role: QByteArray(name.encode("utf-8")) for role, name in self._roles.items()}

        def rowCount(self, parent=QModelIndex()):  # noqa: N802 - Qt API
            return 0 if parent.isValid() else len(self._data)

        def data(self, index, role=Qt.DisplayRole):  # noqa: ANN001
            if not index.isValid() or not 0 <= index.row() < len(self._data):
                return None
            name = self._roles.get(role)
            if name is None:
                return None
            return self._data.get(index.row()).get(name)

        def replace(self, rows: Iterable[Mapping[str, object]]) -> None:
            replacement = ListData()
            replacement.replace(rows)

            # Preserve delegates and selection when the identity/order of rows is unchanged.
            # Progress-only snapshots are frequent; resetting the whole model for those updates
            # causes unnecessary QML delegate churn and visible scroll/selection instability.
            if replacement.job_ids == self._data.job_ids:
                previous = self._data.rows
                current = replacement.rows
                self._data = replacement
                all_roles = list(self._roles)
                for row_index, (before, after) in enumerate(zip(previous, current, strict=True)):
                    if before != after:
                        model_index = self.index(row_index, 0)
                        self.dataChanged.emit(model_index, model_index, all_roles)
                return

            self.beginResetModel()
            self._data = replacement
            self.endResetModel()
else:
    class ProjectionListModel:  # pragma: no cover - only defensive error path
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError("PySide6 GUI runtime is not installed; install the 'gui' extra")
