"""测试公共夹具."""

import pytest

import terminal_qrcode.codecs as codecs
import terminal_qrcode.simple_image as simple_image


@pytest.fixture(autouse=True)
def _patch_codec_backend_when_extension_missing(monkeypatch):
    """当本地未构建 C 扩展时，用最小桩函数隔离无关测试."""
    if codecs._cimage is not None:
        return

    def _fake_encode_png(_data: bytes, _mode: str, _width: int, _height: int) -> bytes:
        return (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx\x9ccdbf\x01\x00\x00\x18\x00\x07\x10\xe7'\xc4"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    def _fake_decode_png(_data: bytes) -> tuple[str, int, int, bytes]:
        return ("RGB", 1, 1, bytes([0, 0, 0]))

    monkeypatch.setattr(simple_image, "encode_png_with_libpng", _fake_encode_png)
    monkeypatch.setattr(simple_image, "decode_png_with_libpng", _fake_decode_png)
