"""TurboJPEG API 测试."""

import pytest

import terminal_qrcode.codecs as codecs
from terminal_qrcode.codecs import TurboJpegUnavailableError, decode_jpeg_rgb


def test_decode_jpeg_raises_when_backend_unavailable(monkeypatch):
    """验证 _cimage 缺失方法时抛出不可用错误."""
    monkeypatch.setattr(codecs, "_cimage", None)
    with pytest.raises(TurboJpegUnavailableError, match="TurboJPEG backend not available"):
        decode_jpeg_rgb(b"\xff\xd8\xff")
