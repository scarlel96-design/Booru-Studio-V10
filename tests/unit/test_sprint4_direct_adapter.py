from booru_studio.engine.adapters.direct_http import DirectHttpAdapter
from booru_studio.engine.contracts import CapabilityLevel


def test_direct_http_adapter_declares_only_controls_it_owns() -> None:
    caps = DirectHttpAdapter().capabilities()
    assert caps.parallelism is CapabilityLevel.EXACT
    assert caps.exact_progress is CapabilityLevel.EXACT
    assert caps.bandwidth_limit is CapabilityLevel.UNSUPPORTED
    assert caps.pause_resume is CapabilityLevel.BEST_EFFORT
