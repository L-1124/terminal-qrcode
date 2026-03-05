"""轻量级图像模块."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias, cast

from terminal_qrcode import _cimage
from terminal_qrcode.codecs import (
    PngDecodeError,
    PngEncodeError,
    PngUnavailableError,
    TurboJpegDecodeError,
    TurboJpegUnavailableError,
    WebPDecodeError,
    WebPUnavailableError,
    decode_jpeg_rgb,
    decode_png_with_libpng,
    decode_webp_rgba,
    encode_png_with_libpng,
)

if TYPE_CHECKING:
    from terminal_qrcode._cimage import PixelMode
else:
    PixelMode: TypeAlias = Literal["L", "RGB", "RGBA"]


@dataclass(frozen=True)
class _ModeInfo:
    channels: int


_MODES: dict[PixelMode, _ModeInfo] = {
    "L": _ModeInfo(channels=1),
    "RGB": _ModeInfo(channels=3),
    "RGBA": _ModeInfo(channels=4),
}

logger = logging.getLogger(__name__)


class SimpleImage:
    """轻量级图像对象."""

    mode: PixelMode
    width: int
    height: int
    _data: bytearray

    def __init__(self, mode: PixelMode, size: tuple[int, int], data: bytes | bytearray):
        """构建图像对象."""
        if mode not in _MODES:
            raise ValueError(f"Unsupported mode: {mode}")
        width, height = size
        if width <= 0 or height <= 0:
            raise ValueError("Image size must be positive.")
        expected = width * height * _MODES[mode].channels
        if len(data) != expected:
            raise ValueError("Raw data length does not match image size/mode.")
        self.mode = mode
        self.width = width
        self.height = height
        self._data = bytearray(data)

    @classmethod
    def new(
        cls,
        mode: PixelMode,
        size: tuple[int, int],
        color: int | tuple[int, ...] | str = 0,
    ) -> "SimpleImage":
        """创建纯色图像."""
        if mode not in _MODES:
            raise ValueError(f"Unsupported mode: {mode}")
        width, height = size
        channels = _MODES[mode].channels
        pixel = _normalize_color(mode, color)
        data = pixel * (width * height)
        if len(data) != width * height * channels:
            raise ValueError("Invalid color for mode.")
        return cls(mode, size, data)

    @classmethod
    def open(cls, path: str | Path) -> "SimpleImage":
        """从本地图片文件读取图像."""
        return cls._decode_image_bytes(Path(path).read_bytes())

    @classmethod
    def from_bytes(cls, data: bytes | bytearray) -> "SimpleImage":
        """从图像字节流读取图像."""
        return cls._decode_image_bytes(bytes(data))

    @classmethod
    def from_qr_matrix(cls, matrix: list[list[bool]]) -> "SimpleImage":
        """从二维码布尔矩阵创建 L 模式图像."""
        width, height, pixels = _cimage.qr_matrix_to_luma(matrix)
        return cls("L", (width, height), pixels)

    @classmethod
    def _decode_image_bytes(cls, data: bytes) -> "SimpleImage":
        file_type = _detect_image_type(data)
        if file_type == "png":
            return cls._decode_png_pipeline(data)
        if file_type == "jpeg":
            return cls._decode_jpeg_pipeline(data)
        if file_type == "webp":
            return cls._decode_webp_pipeline(data)
        raise ValueError("Unsupported image format. Supported formats: JPEG, PNG, WEBP.")

    @classmethod
    def _decode_png_pipeline(cls, data: bytes) -> "SimpleImage":
        try:
            mode, width, height, out = decode_png_with_libpng(data)
            logger.debug("SimpleImage PNG decode: using C backend.")
            return cls(mode, (width, height), out)
        except (PngUnavailableError, PngDecodeError) as exc:
            logger.debug("SimpleImage PNG decode: C backend unavailable/failed. err=%r", exc)
            raise ValueError("PNG decode requires C backend (libpng).") from exc

    @classmethod
    def _decode_jpeg_pipeline(cls, jpeg_data: bytes) -> "SimpleImage":
        try:
            width, height, rgb = decode_jpeg_rgb(jpeg_data)
            logger.debug("SimpleImage JPEG decode: using C backend.")
            return cls(cast(PixelMode, "RGB"), (width, height), rgb)
        except TurboJpegUnavailableError as exc:
            logger.debug("SimpleImage JPEG decode: C backend unavailable. err=%r", exc)
            raise ValueError("JPEG decode requires C backend (turbojpeg).") from exc
        except TurboJpegDecodeError as exc:
            logger.debug("SimpleImage JPEG decode: C backend failed. err=%r", exc)
            raise ValueError("Failed to decode JPEG with C backend.") from exc

    @classmethod
    def _decode_webp_pipeline(cls, webp_data: bytes) -> "SimpleImage":
        try:
            width, height, rgba = decode_webp_rgba(webp_data)
            logger.debug("SimpleImage WEBP decode: using C backend.")
            return cls(cast(PixelMode, "RGBA"), (width, height), rgba)
        except WebPUnavailableError as exc:
            logger.debug("SimpleImage WEBP decode: C backend unavailable. err=%r", exc)
            raise ValueError("WEBP decode requires C backend (libwebp).") from exc
        except WebPDecodeError as exc:
            logger.debug("SimpleImage WEBP decode: C backend failed. err=%r", exc)
            raise ValueError("Failed to decode WEBP with C backend.") from exc

    def copy(self) -> "SimpleImage":
        """复制图像."""
        return SimpleImage(self.mode, (self.width, self.height), self._data)

    def _index(self, x: int, y: int) -> int:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            raise ValueError("Pixel index out of bounds.")
        return (y * self.width + x) * _MODES[self.mode].channels

    def getpixel(self, xy: tuple[int, int]) -> int | tuple[int, ...]:
        """读取像素."""
        x, y = xy
        idx = self._index(x, y)
        channels = _MODES[self.mode].channels
        if channels == 1:
            return self._data[idx]
        return tuple(self._data[idx + i] for i in range(channels))

    def putpixel(self, xy: tuple[int, int], value: int | tuple[int, ...]) -> None:
        """写入像素."""
        x, y = xy
        idx = self._index(x, y)
        pixel = _normalize_pixel(self.mode, value)
        for i, val in enumerate(pixel):
            self._data[idx + i] = val

    def convert(self, mode: PixelMode) -> "SimpleImage":
        """转换图像模式."""
        if mode not in _MODES:
            raise ValueError(f"Unsupported mode: {mode}")
        if mode == self.mode:
            return self.copy()

        src_mode = self.mode
        dst_mode = mode
        out = _cimage.convert(bytes(self._data), src_mode, dst_mode, self.width, self.height)
        return SimpleImage(mode, (self.width, self.height), out)

    def crop(self, box: tuple[int, int, int, int]) -> "SimpleImage":
        """裁切图像."""
        left, top, right, bottom = box
        if not (0 <= left < right <= self.width and 0 <= top < bottom <= self.height):
            raise ValueError("Invalid crop box.")
        channels = _MODES[self.mode].channels
        out_w = right - left
        out_h = bottom - top
        out = bytearray(out_w * out_h * channels)
        dst = 0
        for y in range(top, bottom):
            src_start = (y * self.width + left) * channels
            src_end = src_start + out_w * channels
            out[dst : dst + out_w * channels] = self._data[src_start:src_end]
            dst += out_w * channels
        return SimpleImage(self.mode, (out_w, out_h), out)

    def getbbox_nonwhite(self) -> tuple[int, int, int, int] | None:
        """返回非白色像素包围盒."""
        result = _cimage.getbbox_nonwhite(bytes(self._data), self.mode, self.width, self.height)
        if result is None:
            return None
        if isinstance(result, tuple) and len(result) == 4:
            return (
                int(result[0]),
                int(result[1]),
                int(result[2]),
                int(result[3]),
            )
        return None

    def resize(self, size: tuple[int, int]) -> "SimpleImage":
        """缩放图像（最近邻采样）."""
        new_w, new_h = size
        if new_w <= 0 or new_h <= 0:
            raise ValueError("Resize target must be positive.")

        out = _cimage.resize_nearest(
            bytes(self._data),
            self.mode,
            self.width,
            self.height,
            new_w,
            new_h,
        )
        return SimpleImage(self.mode, (new_w, new_h), out)

    def thumbnail(self, size: tuple[int, int]) -> None:
        """原地等比缩略图."""
        max_w, max_h = size
        if self.width <= max_w and self.height <= max_h:
            return
        ratio = min(max_w / self.width, max_h / self.height)
        new_w = max(1, int(self.width * ratio))
        new_h = max(1, int(self.height * ratio))
        resized = self.resize((new_w, new_h))
        self.mode = resized.mode
        self.width = resized.width
        self.height = resized.height
        self._data = resized._data

    def tobytes(self) -> bytes:
        """导出原始像素字节."""
        return bytes(self._data)

    def to_png_bytes(self) -> bytes:
        """编码为 PNG."""
        try:
            out = encode_png_with_libpng(bytes(self._data), self.mode, self.width, self.height)
            logger.debug("SimpleImage PNG encode: using C backend.")
            return out
        except (PngUnavailableError, PngEncodeError) as exc:
            raise ValueError("PNG encode requires C backend (libpng).") from exc


def _detect_image_type(data: bytes) -> Literal["png", "jpeg", "webp"] | None:
    """根据文件头魔数检测图像格式."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _normalize_color(mode: PixelMode, color: int | tuple[int, ...] | str) -> bytes:
    if isinstance(color, str):
        named = {"white": 255, "black": 0}
        if color.lower() not in named:
            raise ValueError(f"Unsupported color name: {color}")
        color = named[color.lower()]
    return bytes(_normalize_pixel(mode, color))


def _normalize_pixel(mode: PixelMode, value: int | tuple[int, ...]) -> tuple[int, ...]:
    channels = _MODES[mode].channels
    if isinstance(value, int):
        if channels == 1:
            return (_clamp_u8(value),)
        if channels == 3:
            v = _clamp_u8(value)
            return (v, v, v)
        v = _clamp_u8(value)
        return (v, v, v, 255)

    vals = tuple(_clamp_u8(v) for v in value)
    if len(vals) == channels:
        return vals
    if channels == 4 and len(vals) == 3:
        return (vals[0], vals[1], vals[2], 255)
    if channels == 3 and len(vals) == 4:
        return vals[:3]
    raise ValueError("Pixel length does not match image mode.")


def _clamp_u8(value: int) -> int:
    return max(0, min(255, int(value)))
