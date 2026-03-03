"""TurboJPEG cffi 解码后端测试."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import terminal_qrcode.codecs as codecs
from terminal_qrcode.codecs import TurboJpegUnavailableError, decode_jpeg_rgb_cffi


def test_decode_jpeg_raises_when_backend_unavailable(monkeypatch):
    """验证 turbojpeg cffi 后端缺失时抛出不可用错误."""
    monkeypatch.setattr(codecs, "_load_turbojpeg_cffi", lambda: None)
    with pytest.raises(TurboJpegUnavailableError, match="TurboJPEG library not found"):
        decode_jpeg_rgb_cffi(b"\xff\xd8\xff")


def test_load_cffi_lib_prefers_packaged_library_path(monkeypatch, tmp_path):
    """验证加载动态库时优先尝试包内 _vendor 路径."""
    packaged_lib = tmp_path / "libturbojpeg.so"
    packaged_lib.write_bytes(b"fake")
    dlopen_calls: list[str] = []

    class _FakeFFI:
        def cdef(self, _sig: str) -> None:
            return None

        def dlopen(self, target: str):
            dlopen_calls.append(target)
            if target == str(packaged_lib):
                return object()
            raise OSError(target)

    fake_ffi = _FakeFFI()
    monkeypatch.setitem(sys.modules, "cffi", SimpleNamespace(FFI=lambda: fake_ffi))
    monkeypatch.setattr(codecs, "_iter_packaged_library_resources", lambda _candidates: [packaged_lib])

    lib_ctx = codecs._load_cffi_lib(
        cdef="int x(void);",
        win_candidates=("turbojpeg.dll",),
        posix_candidates=("libturbojpeg.so",),
    )

    assert lib_ctx is not None
    assert dlopen_calls
    assert Path(dlopen_calls[0]) == packaged_lib
