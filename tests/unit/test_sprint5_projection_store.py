from __future__ import annotations

import pytest

from booru_studio.ui.action_controller import ActionController
from booru_studio.ui.models.list_data import ListData
from booru_studio.ui.projection_store import ProjectionStore


def _snapshot(revision: int, *, title: str = "A"):
    return {
        "global_state_revision": revision,
        "projection_revision": revision,
        "downloads": [{"job_id": "job-1", "title": title}],
        "queue": [{"job_id": "job-1", "title": title}],
        "history": [],
    }


def test_projection_store_accepts_monotonic_snapshot_and_rejects_regression() -> None:
    store = ProjectionStore()
    assert store.apply_snapshot(_snapshot(5)) is True
    assert store.state.projection_revision == 5
    assert store.apply_snapshot(_snapshot(4, title="stale")) is False
    assert store.state.downloads[0]["title"] == "A"


def test_projection_store_marks_state_stale_without_discarding_rows() -> None:
    store = ProjectionStore()
    store.apply_snapshot(_snapshot(2))
    store.mark_stale()
    assert store.state.stale is True
    assert store.state.downloads[0]["job_id"] == "job-1"


def test_projection_store_rejects_invalid_projection_revision() -> None:
    store = ProjectionStore()
    with pytest.raises(ValueError):
        store.apply_snapshot(
            {
                "global_state_revision": 1,
                "projection_revision": 2,
                "downloads": [],
                "queue": [],
                "history": [],
            }
        )


def test_projection_store_rejects_duplicate_job_ids_per_surface() -> None:
    store = ProjectionStore()
    with pytest.raises(ValueError, match="duplicate job_id"):
        store.apply_snapshot(
            {
                "global_state_revision": 1,
                "projection_revision": 1,
                "downloads": [{"job_id": "same"}, {"job_id": "same"}],
                "queue": [],
                "history": [],
            }
        )


def test_action_controller_disables_mutations_when_stale_or_disconnected() -> None:
    disconnected = ActionController.evaluate(
        connected=False, stale=False, pending_command=False, selected_lifecycle="ACTIVE"
    )
    assert not disconnected.can_submit and not disconnected.can_cancel
    stale = ActionController.evaluate(
        connected=True, stale=True, pending_command=False, selected_lifecycle="ACTIVE"
    )
    assert not stale.can_submit and not stale.can_cancel
    ready = ActionController.evaluate(
        connected=True, stale=False, pending_command=False, selected_lifecycle="ACTIVE"
    )
    assert ready.can_submit and ready.can_cancel


def test_list_data_enforces_stable_unique_job_ids() -> None:
    data = ListData()
    data.replace([{"job_id": "a", "title": "A"}, {"job_id": "b", "title": "B"}])
    assert data.index_of("b") == 1
    assert data.get(0)["title"] == "A"
    with pytest.raises(ValueError):
        data.replace([{"job_id": "a"}, {"job_id": "a"}])
