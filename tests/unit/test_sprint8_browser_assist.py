from __future__ import annotations

import threading

from booru_studio.engine.adapters.playwright_browser.adapter import (
    BrowserAssistAdapter, BrowserBackendResult, BrowserObservation,
)


class FakeBackend:
    def observe(self, raw_input: str, *, policy, cancel_event, timeout_s):
        assert policy.authorize(raw_input).public_only
        return BrowserBackendResult(
            raw_input,
            "Dynamic page",
            (
                BrowserObservation("https://cdn.example/video.mp4?token=TOPSECRET", "video/mp4", "Video"),
                BrowserObservation("http://127.0.0.1/private.jpg", "image/jpeg", "Private"),
                BrowserObservation("javascript:alert(1)", None, "Bad"),
            ),
            blocked_request_count=2,
        )


def resolver(host: str, port: int | None):
    return {"public.example": ("93.184.216.34",), "cdn.example": ("93.184.216.35",)}[host]


def test_browser_observation_revalidates_dom_candidates_and_redacts_secrets() -> None:
    adapter = BrowserAssistAdapter(FakeBackend(), resolver=resolver)
    result = adapter.discover("https://public.example/page", cancel_event=threading.Event())
    assert result.page_title == "Dynamic page"
    assert len(result.items) == 1
    assert result.blocked_candidate_count == 2
    descriptor = result.items[0].candidate_artifacts[0].descriptor
    assert descriptor.network_scope_policy == "PUBLIC_ONLY"
    assert "TOPSECRET" in descriptor.url
    assert "TOPSECRET" not in repr(result.items[0].sanitized_metadata)
    assert "TOPSECRET" not in repr(descriptor.diagnostic_view())
