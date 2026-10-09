from __future__ import annotations

import pytest

from booru_studio.ipc.framing import FrameDecoder, encode_json_frame


def test_frame_decoder_handles_split_and_multiple_frames() -> None:
    first = encode_json_frame({"x": 1})
    second = encode_json_frame({"y": "한글"})
    stream = first + second
    decoder = FrameDecoder()
    assert decoder.feed(stream[:3]) == []
    frames = decoder.feed(stream[3:])
    assert frames == [{"x": 1}, {"y": "한글"}]


def test_frame_decoder_rejects_oversized_declared_length() -> None:
    decoder = FrameDecoder(max_bytes=8)
    with pytest.raises(ValueError):
        decoder.feed((9).to_bytes(4, "big"))


def test_encoder_rejects_nan() -> None:
    with pytest.raises(ValueError):
        encode_json_frame({"x": float("nan")})
