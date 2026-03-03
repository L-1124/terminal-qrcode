"""TurboJPEG cffi 解码后端测试."""

import pytest

import terminal_qrcode.codecs as codecs
from terminal_qrcode.codecs import TurboJpegUnavailableError, decode_jpeg_rgb_cffi


def test_decode_jpeg_raises_when_backend_unavailable(monkeypatch):
    """验证 turbojpeg cffi 后端缺失时抛出不可用错误."""
    monkeypatch.setattr(codecs, "_load_turbojpeg_cffi", lambda: None)
    with pytest.raises(TurboJpegUnavailableError, match="TurboJPEG library not found"):
        decode_jpeg_rgb_cffi(b"\xff\xd8\xff")
