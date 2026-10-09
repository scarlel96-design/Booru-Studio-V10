from __future__ import annotations

from booru_studio.engine.contracts import CapabilityLevel, EngineCapabilities
from booru_studio.engine.adapters.direct_http.transfer import DirectHttpWorker


class DirectHttpAdapter:
    adapter_id = "direct-http-v10"

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            parallelism=CapabilityLevel.EXACT,
            bandwidth_limit=CapabilityLevel.UNSUPPORTED,
            pause_resume=CapabilityLevel.BEST_EFFORT,
            exact_progress=CapabilityLevel.EXACT,
        )

    def make_worker(self) -> DirectHttpWorker:
        return DirectHttpWorker()
