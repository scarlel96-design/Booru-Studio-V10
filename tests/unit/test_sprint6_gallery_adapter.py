from __future__ import annotations

from pathlib import Path

import pytest

from booru_studio.common.errors import ErrorCode
from booru_studio.engine.adapters.gallery_dl.adapter import (
    GalleryDlAdapter,
    GalleryDlEngineError,
    GalleryDlPythonBackend,
    GalleryDlRecord,
    GalleryDirectHandoffPlanner,
)
from booru_studio.engine.contracts import HandoffSafety, ProbeSupport


class FakeBackend:
    def __init__(self, records):
        self.records = tuple(records)

    def collect(self, raw_input: str):
        assert raw_input.startswith("https://")
        return self.records


def test_probe_is_side_effect_free_and_conservative() -> None:
    adapter = GalleryDlAdapter(FakeBackend(()))
    assert adapter.probe("https://example.test/gallery").support is ProbeSupport.MAYBE
    assert adapter.probe("not a url").support is ProbeSupport.NO


def test_gallery_normalization_and_handoff_safety() -> None:
    records = (
        GalleryDlRecord(3, "https://cdn.test/a.jpg", {
            "category": "example", "subcategory": "post", "id": 10,
            "title": "First", "filename": "first", "extension": "jpg", "filesize": 123,
        }),
        GalleryDlRecord(3, "https://cdn.test/b.jpg?token=abc", {
            "category": "example", "subcategory": "post", "id": 11,
            "filename": "second", "extension": "jpg",
            "_http_headers": {"Referer": "https://example.test/post/11", "User-Agent": "UA"},
        }),
        GalleryDlRecord(3, "https://private.test/c.jpg", {
            "category": "private", "id": 12, "filename": "third", "extension": "jpg",
            "_http_headers": {"Cookie": "session=secret"},
        }),
        GalleryDlRecord(3, "https://validator.test/d.jpg", {
            "category": "special", "id": 13, "filename": "fourth", "extension": "jpg",
            "_http_validate": object(),
        }),
        GalleryDlRecord(6, "https://example.test/child?secret=runtime-only", {}),
    )
    result = GalleryDlAdapter(FakeBackend(records)).discover("https://example.test/gallery")
    assert len(result.items) == 4
    assert result.queued_inputs == ("https://example.test/child?secret=runtime-only",)
    assert [item.candidate_artifacts[0].descriptor.handoff_safety for item in result.items] == [
        HandoffSafety.SAFE,
        HandoffSafety.CONDITIONAL,
        HandoffSafety.UNSAFE,
        HandoffSafety.UNSAFE,
    ]
    first = result.items[0]
    assert first.source_identity == "gallery:example:post:10"
    assert first.media_kind == "IMAGE"
    assert first.candidate_artifacts[0].suggested_filename == "first.jpg"
    assert first.candidate_artifacts[0].expected_size == 123
    assert "_http_headers" not in first.sanitized_metadata
    assert "url" not in first.sanitized_metadata


def test_filename_is_single_segment_and_metadata_cannot_traverse() -> None:
    result = GalleryDlAdapter(FakeBackend((
        GalleryDlRecord(3, "https://cdn.test/file.png", {
            "category": "x", "id": 1, "filename": "../../evil/name", "extension": "png"
        }),
    ))).discover("https://example.test/gallery")
    name = result.items[0].candidate_artifacts[0].suggested_filename
    assert "/" not in name and "\\" not in name and ".." not in name


def test_direct_handoff_refuses_unsafe_descriptor() -> None:
    result = GalleryDlAdapter(FakeBackend((
        GalleryDlRecord(3, "https://private.test/file.jpg", {
            "category": "x", "id": 1, "filename": "a", "extension": "jpg",
            "_http_headers": {"Authorization": "Bearer secret"},
        }),
    ))).discover("https://example.test/gallery")
    with pytest.raises(ValueError, match="UNSAFE"):
        GalleryDirectHandoffPlanner.build(
            result.items[0].candidate_artifacts[0], artifact_id="00000000-0000-0000-0000-000000000000",
            generation=1, staging_path=Path("x.part"),
        )


def test_missing_gallery_dl_maps_to_engine_unavailable_when_not_installed() -> None:
    # The source QA environment intentionally does not need the optional Engine Pack dependency.
    try:
        import gallery_dl  # type: ignore[import-not-found]  # noqa: F401
    except ModuleNotFoundError:
        with pytest.raises(GalleryDlEngineError) as caught:
            GalleryDlPythonBackend().collect("https://example.test")
        assert caught.value.error.code is ErrorCode.ENGINE_UNAVAILABLE


def test_python_backend_embeds_datajob_without_stdout_and_preserves_private_metadata(monkeypatch) -> None:
    import sys
    import types
    from contextlib import contextmanager
    import booru_studio.engine.adapters.gallery_dl.adapter as module

    calls: dict[str, object] = {}

    @contextmanager
    def apply(values):
        calls["config_values"] = values
        yield

    class FakeDataJob:
        def __init__(self, *, url, file, resolve):
            calls["url"] = url
            calls["file"] = file
            calls["resolve"] = resolve
            self.exception = None
            self.data = [
                (3, "https://cdn.test/private.jpg", {
                    "category": "x", "id": 7, "_http_headers": {"Referer": "https://site.test/post/7"},
                }),
            ]

        def run(self):
            calls["ran"] = True
            return 0

    package = types.ModuleType("gallery_dl")
    package.__path__ = []  # mark as package for import machinery
    package.config = types.SimpleNamespace(apply=apply)
    job_module = types.ModuleType("gallery_dl.job")
    job_module.DataJob = FakeDataJob
    monkeypatch.setitem(sys.modules, "gallery_dl", package)
    monkeypatch.setitem(sys.modules, "gallery_dl.job", job_module)
    monkeypatch.setattr(module, "version", lambda _: module.GALLERY_DL_PIN)

    records = module.GalleryDlPythonBackend().collect("https://site.test/gallery")
    assert calls["file"] is None  # stdout can be the Worker IPC transport
    assert calls["resolve"] == module._MAX_QUEUE_RESOLVE_DEPTH
    assert calls["config_values"] == [(('output',), 'private', True)]
    assert calls["ran"] is True
    assert records[0].metadata["_http_headers"]["Referer"] == "https://site.test/post/7"


def test_python_backend_honors_datajob_exception_even_when_run_returns_zero(monkeypatch) -> None:
    import sys
    import types
    from contextlib import contextmanager
    import booru_studio.engine.adapters.gallery_dl.adapter as module

    @contextmanager
    def apply(_):
        yield

    class FakeDataJob:
        def __init__(self, **_):
            self.exception = TimeoutError("timed out")
            self.data = [(-1, {"error": "TimeoutError", "message": "timed out"})]

        def run(self):
            return 0

    package = types.ModuleType("gallery_dl")
    package.__path__ = []
    package.config = types.SimpleNamespace(apply=apply)
    job_module = types.ModuleType("gallery_dl.job")
    job_module.DataJob = FakeDataJob
    monkeypatch.setitem(sys.modules, "gallery_dl", package)
    monkeypatch.setitem(sys.modules, "gallery_dl.job", job_module)
    monkeypatch.setattr(module, "version", lambda _: module.GALLERY_DL_PIN)

    with pytest.raises(GalleryDlEngineError) as caught:
        module.GalleryDlPythonBackend().collect("https://site.test/gallery")
    assert caught.value.error.code is ErrorCode.NETWORK_TIMEOUT
