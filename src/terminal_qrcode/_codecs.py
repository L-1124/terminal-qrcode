"""图像编解码后端整合模块（纯 C 扩展实现）."""

from . import _cimage
from ._contracts import PixelMode

__all__ = [
    "PngDecodeError",
    "PngEncodeError",
    "decode_png_with_libpng",
    "encode_png_with_libpng",
    "TurboJpegDecodeError",
    "decode_jpeg_rgb",
    "WebPDecodeError",
    "decode_webp_rgba",
]


class PngDecodeError(RuntimeError):
    """PNG 解码失败."""


class PngEncodeError(RuntimeError):
    """PNG 编码失败."""


class TurboJpegDecodeError(RuntimeError):
    """TurboJPEG 解码失败."""


class WebPDecodeError(RuntimeError):
    """WEBP 解码失败."""


def decode_png_with_libpng(png_data: bytes) -> tuple["PixelMode", int, int, bytes]:
    """通过静态链接 C 后端解码 PNG."""
    try:
        mode, width, height, out = _cimage.decode_png_8bit(png_data)
    except Exception as exc:  # noqa: BLE001
        raise PngDecodeError(str(exc) or "PNG decode failed.") from exc
    return mode, int(width), int(height), bytes(out)


def encode_png_with_libpng(data: bytes, mode: "PixelMode", width: int, height: int) -> bytes:
    """通过静态链接 C 后端编码 PNG."""
    try:
        out = _cimage.encode_png_8bit(data, mode, width, height)
    except Exception as exc:  # noqa: BLE001
        raise PngEncodeError(str(exc) or "PNG encode failed.") from exc
    return bytes(out)


def decode_jpeg_rgb(jpeg_data: bytes) -> tuple[int, int, bytes]:
    """通过静态链接 C 后端解码 JPEG."""
    try:
        width, height, out = _cimage.decode_jpeg_turbo(jpeg_data)
    except Exception as exc:  # noqa: BLE001
        raise TurboJpegDecodeError(str(exc) or "JPEG decode failed.") from exc
    return int(width), int(height), bytes(out)


def decode_webp_rgba(webp_data: bytes) -> tuple[int, int, bytes]:
    """通过静态链接 C 后端解码 WEBP."""
    try:
        width, height, out = _cimage.decode_webp_lib(webp_data)
    except Exception as exc:  # noqa: BLE001
        raise WebPDecodeError(str(exc) or "WEBP decode failed.") from exc
    return int(width), int(height), bytes(out)
