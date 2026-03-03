"""图像编解码后端整合模块（纯 C 扩展实现）."""

import ctypes
import logging
import os
import sys
from pathlib import Path
from typing import Any, Literal, cast

logger = logging.getLogger(__name__)

__all__ = [
    "PngUnavailableError",
    "PngDecodeError",
    "PngEncodeError",
    "decode_png_with_libpng",
    "encode_png_with_libpng",
    "TurboJpegUnavailableError",
    "TurboJpegDecodeError",
    "decode_jpeg_rgb",
    "WebPUnavailableError",
    "WebPDecodeError",
    "decode_webp_rgba",
]


class PngUnavailableError(RuntimeError):
    """系统缺少 libpng 动态库或 C 扩展不可用."""


class PngDecodeError(RuntimeError):
    """PNG 解码失败."""


class PngEncodeError(RuntimeError):
    """PNG 编码失败."""


class TurboJpegUnavailableError(RuntimeError):
    """系统缺少 TurboJPEG 动态库或 C 扩展不可用."""


class TurboJpegDecodeError(RuntimeError):
    """TurboJPEG 解码失败."""


class WebPUnavailableError(RuntimeError):
    """系统缺少 libwebp 动态库或 C 扩展不可用."""


class WebPDecodeError(RuntimeError):
    """libwebp 解码失败."""


_WINDOWS_DLL_DIR_HANDLE: Any | None = None
_WINDOWS_DLL_PREPARED = False


def _prepare_windows_runtime_dlls() -> None:
    """准备 Windows 运行时 DLL 搜索路径与预加载."""
    global _WINDOWS_DLL_DIR_HANDLE
    global _WINDOWS_DLL_PREPARED

    if _WINDOWS_DLL_PREPARED or sys.platform != "win32":
        return
    _WINDOWS_DLL_PREPARED = True

    vendor_dir = Path(__file__).resolve().parent / "_vendor" / "windows"
    if not vendor_dir.exists():
        logger.debug("Windows vendor dir not found: %s", vendor_dir)
        return

    try:
        add_dll_directory = getattr(os, "add_dll_directory", None)
        if add_dll_directory is not None:
            _WINDOWS_DLL_DIR_HANDLE = add_dll_directory(str(vendor_dir))
    except OSError as exc:
        logger.debug("add_dll_directory failed: %r", exc)

    os.environ["PATH"] = f"{vendor_dir}{os.pathsep}{os.environ.get('PATH', '')}"

    preload_candidates = [
        "jpeg62.dll",
        "zlib1.dll",
        "turbojpeg.dll",
        "libpng16.dll",
        "libpng16-16.dll",
        "libsharpyuv.dll",
        "libwebp.dll",
    ]
    for dll_name in preload_candidates:
        dll_path = vendor_dir / dll_name
        if not dll_path.exists():
            continue
        try:
            windll_loader = getattr(ctypes, "WinDLL", None)
            if windll_loader is not None:
                windll_loader(str(dll_path))
        except OSError as exc:
            logger.debug("Preload DLL failed: %s err=%r", dll_path, exc)


_prepare_windows_runtime_dlls()
try:
    from terminal_qrcode import _cimage
except Exception as exc:  # noqa: BLE001
    logger.debug("_cimage module unavailable: %r", exc)
    _cimage = None


def decode_png_with_libpng(png_data: bytes) -> tuple[str, int, int, bytes]:
    """通过 C 扩展 + libpng 解码 PNG."""
    if _cimage is None:
        raise PngUnavailableError("libpng backend not available. Build C extension with libpng.")
    try:
        mode, width, height, out = _cimage.decode_png_8bit(png_data)
    except AttributeError as exc:
        raise PngUnavailableError("libpng backend not available. Build C extension with libpng.") from exc
    except Exception as exc:  # noqa: BLE001
        raise PngDecodeError(str(exc) or "decode_png_8bit failed.") from exc
    return str(mode), int(width), int(height), bytes(out)


def encode_png_with_libpng(data: bytes, mode: str, width: int, height: int) -> bytes:
    """通过 C 扩展 + libpng 编码 PNG."""
    if _cimage is None:
        raise PngUnavailableError("libpng backend not available. Build C extension with libpng.")
    if mode not in {"L", "RGB", "RGBA"}:
        raise PngEncodeError(f"Unsupported mode for PNG encode: {mode}")
    mode_literal = cast(Literal["L", "RGB", "RGBA"], mode)
    try:
        out = _cimage.encode_png_8bit(data, mode_literal, width, height)
    except AttributeError as exc:
        raise PngUnavailableError("libpng backend not available. Build C extension with libpng.") from exc
    except Exception as exc:  # noqa: BLE001
        raise PngEncodeError(str(exc) or "encode_png_8bit failed.") from exc
    return bytes(out)


def decode_jpeg_rgb(jpeg_data: bytes) -> tuple[int, int, bytes]:
    """通过 C 扩展 + turbojpeg 解码 JPEG."""
    if _cimage is None:
        raise TurboJpegUnavailableError("TurboJPEG backend not available in _cimage.")
    try:
        width, height, out = _cimage.decode_jpeg_turbo(jpeg_data)
    except AttributeError as exc:
        raise TurboJpegUnavailableError("TurboJPEG backend not available in _cimage.") from exc
    except Exception as exc:  # noqa: BLE001
        raise TurboJpegDecodeError(str(exc) or "decode_jpeg_turbo failed.") from exc
    return int(width), int(height), bytes(out)


def decode_webp_rgba(webp_data: bytes) -> tuple[int, int, bytes]:
    """通过 C 扩展 + libwebp 解码 WEBP."""
    if _cimage is None:
        raise WebPUnavailableError("libwebp backend not available in _cimage.")
    try:
        width, height, out = _cimage.decode_webp_lib(webp_data)
    except AttributeError as exc:
        raise WebPUnavailableError("libwebp backend not available in _cimage.") from exc
    except Exception as exc:  # noqa: BLE001
        raise WebPDecodeError(str(exc) or "decode_webp_lib failed.") from exc
    return int(width), int(height), bytes(out)
