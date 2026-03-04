"""图像编解码后端整合模块（纯 C 扩展实现）."""

import logging
from typing import TYPE_CHECKING

from terminal_qrcode import _cimage

if TYPE_CHECKING:
    from terminal_qrcode._cimage import PixelMode

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


def decode_png_with_libpng(png_data: bytes) -> tuple[PixelMode, int, int, bytes]:
    """通过 C 扩展 + libpng 解码 PNG."""
    try:
        mode, width, height, out = _cimage.decode_png_8bit(png_data)
    except AttributeError as exc:
        raise PngUnavailableError("libpng backend not available. Build C extension with libpng.") from exc
    except Exception as exc:  # noqa: BLE001
        raise PngDecodeError(str(exc) or "decode_png_8bit failed.") from exc
    return mode, int(width), int(height), bytes(out)


def encode_png_with_libpng(data: bytes, mode: PixelMode, width: int, height: int) -> bytes:
    """通过 C 扩展 + libpng 编码 PNG."""
    try:
        out = _cimage.encode_png_8bit(data, mode, width, height)
    except AttributeError as exc:
        raise PngUnavailableError("libpng backend not available. Build C extension with libpng.") from exc
    except Exception as exc:  # noqa: BLE001
        raise PngEncodeError(str(exc) or "encode_png_8bit failed.") from exc
    return bytes(out)


def decode_jpeg_rgb(jpeg_data: bytes) -> tuple[int, int, bytes]:
    """通过 C 扩展 + turbojpeg 解码 JPEG."""
    try:
        width, height, out = _cimage.decode_jpeg_turbo(jpeg_data)
    except AttributeError as exc:
        raise TurboJpegUnavailableError("TurboJPEG backend not available in _cimage.") from exc
    except Exception as exc:  # noqa: BLE001
        raise TurboJpegDecodeError(str(exc) or "decode_jpeg_turbo failed.") from exc
    return int(width), int(height), bytes(out)


def decode_webp_rgba(webp_data: bytes) -> tuple[int, int, bytes]:
    """通过 C 扩展 + libwebp 解码 WEBP."""
    try:
        width, height, out = _cimage.decode_webp_lib(webp_data)
    except AttributeError as exc:
        raise WebPUnavailableError("libwebp backend not available in _cimage.") from exc
    except Exception as exc:  # noqa: BLE001
        raise WebPDecodeError(str(exc) or "decode_webp_lib failed.") from exc
    return int(width), int(height), bytes(out)
