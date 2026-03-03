"""轻量级图像模块."""

import enum
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

import terminal_qrcode.codecs as codecs_module
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


@dataclass(frozen=True)
class _ModeInfo:
    channels: int


_MODES: dict[str, _ModeInfo] = {
    "L": _ModeInfo(channels=1),
    "RGB": _ModeInfo(channels=3),
    "RGBA": _ModeInfo(channels=4),
}

logger = logging.getLogger(__name__)


class CImageAccelProtocol(Protocol):
    """_cimage 模块静态协议."""

    def convert(self, data: bytes, src_mode: str, dst_mode: str, width: int, height: int) -> bytes:
        """转换像素模式."""
        ...

    def getbbox_nonwhite(self, data: bytes, mode: str, width: int, height: int) -> tuple[int, int, int, int] | None:
        """获取非白像素包围盒."""
        ...

    def resize_nearest(self, data: bytes, mode: str, src_w: int, src_h: int, dst_w: int, dst_h: int) -> bytes:
        """最近邻缩放."""
        ...

    def decode_png_8bit(self, data: bytes) -> tuple[str, int, int, bytes]:
        """解码 PNG."""
        ...

    def encode_png_8bit(self, data: bytes, mode: str, width: int, height: int) -> bytes:
        """编码 PNG."""
        ...

    def threshold_to_bits(self, data: bytes, mode: str, width: int, height: int, threshold: int) -> bytes:
        """阈值化."""
        ...

    def sixel_encode_mono(self, bits: bytes, width: int, height: int) -> str:
        """编码 sixel."""
        ...


_CIMAGE_ACCEL: CImageAccelProtocol | None = None
if os.environ.get("QRT_DISABLE_C_ACCEL", "") != "1":
    cimage = codecs_module._cimage
    if cimage is not None:
        _CIMAGE_ACCEL = cast(CImageAccelProtocol, cimage)


class SimpleImage:
    """轻量级图像对象."""

    class Resampling(enum.Enum):
        """采样模式."""

        NEAREST = 0
        LANCZOS = 1

    def __init__(self, mode: str, size: tuple[int, int], data: bytes | bytearray):
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
        mode: str,
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
            return cls("RGB", (width, height), rgb)
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
            return cls("RGBA", (width, height), rgba)
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

    def convert(self, mode: str) -> "SimpleImage":
        """转换图像模式."""
        if mode not in _MODES:
            raise ValueError(f"Unsupported mode: {mode}")
        if mode == self.mode:
            return self.copy()

        if _CIMAGE_ACCEL is not None:
            try:
                out = _CIMAGE_ACCEL.convert(bytes(self._data), self.mode, mode, self.width, self.height)
                return SimpleImage(mode, (self.width, self.height), out)
            except Exception:  # noqa: BLE001
                pass

        data = self._data
        pixels = self.width * self.height

        if self.mode == "L" and mode == "RGB":
            out = bytearray(pixels * 3)
            out_idx = 0
            for v in data:
                out[out_idx : out_idx + 3] = bytes((v, v, v))
                out_idx += 3
            return SimpleImage(mode, (self.width, self.height), out)

        if self.mode == "L" and mode == "RGBA":
            out = bytearray(pixels * 4)
            out_idx = 0
            for v in data:
                out[out_idx : out_idx + 4] = bytes((v, v, v, 255))
                out_idx += 4
            return SimpleImage(mode, (self.width, self.height), out)

        if self.mode == "RGB" and mode == "L":
            out = bytearray(pixels)
            src = memoryview(data)
            out_idx = 0
            for i in range(0, len(data), 3):
                r = src[i]
                g = src[i + 1]
                b = src[i + 2]
                out[out_idx] = (299 * r + 587 * g + 114 * b) // 1000
                out_idx += 1
            return SimpleImage(mode, (self.width, self.height), out)

        if self.mode == "RGB" and mode == "RGBA":
            out = bytearray(pixels * 4)
            src = memoryview(data)
            out_idx = 0
            for i in range(0, len(data), 3):
                out[out_idx] = src[i]
                out[out_idx + 1] = src[i + 1]
                out[out_idx + 2] = src[i + 2]
                out[out_idx + 3] = 255
                out_idx += 4
            return SimpleImage(mode, (self.width, self.height), out)

        if self.mode == "RGBA" and mode == "RGB":
            out = bytearray(pixels * 3)
            src = memoryview(data)
            out_idx = 0
            for i in range(0, len(data), 4):
                out[out_idx] = src[i]
                out[out_idx + 1] = src[i + 1]
                out[out_idx + 2] = src[i + 2]
                out_idx += 3
            return SimpleImage(mode, (self.width, self.height), out)

        if self.mode == "RGBA" and mode == "L":
            out = bytearray(pixels)
            src = memoryview(data)
            out_idx = 0
            for i in range(0, len(data), 4):
                r = src[i]
                g = src[i + 1]
                b = src[i + 2]
                out[out_idx] = (299 * r + 587 * g + 114 * b) // 1000
                out_idx += 1
            return SimpleImage(mode, (self.width, self.height), out)

        out = bytearray(self.width * self.height * _MODES[mode].channels)
        src_channels = _MODES[self.mode].channels
        dst_channels = _MODES[mode].channels
        out_idx = 0
        for i in range(0, len(data), src_channels):
            rgb = _to_rgb_tuple(self.mode, data[i : i + src_channels])
            if dst_channels == 1:
                out[out_idx] = (299 * rgb[0] + 587 * rgb[1] + 114 * rgb[2]) // 1000
                out_idx += 1
            elif dst_channels == 3:
                out[out_idx : out_idx + 3] = bytes(rgb)
                out_idx += 3
            else:
                out[out_idx : out_idx + 4] = bytes((rgb[0], rgb[1], rgb[2], 255))
                out_idx += 4

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
        if _CIMAGE_ACCEL is not None:
            try:
                result = _CIMAGE_ACCEL.getbbox_nonwhite(bytes(self._data), self.mode, self.width, self.height)
                if result is None:
                    return None
                if isinstance(result, tuple) and len(result) == 4:
                    return (
                        int(result[0]),
                        int(result[1]),
                        int(result[2]),
                        int(result[3]),
                    )
            except Exception:  # noqa: BLE001
                pass

        left = self.width
        top = self.height
        right = -1
        bottom = -1
        width = self.width
        height = self.height
        data = self._data

        if self.mode == "L":
            for y in range(height):
                row_start = y * width
                row_has = False
                for x in range(width):
                    if data[row_start + x] < 255:
                        if x < left:
                            left = x
                        if x > right:
                            right = x
                        row_has = True
                if row_has:
                    if y < top:
                        top = y
                    bottom = y
        else:
            channels = _MODES[self.mode].channels
            for y in range(height):
                row_start = y * width * channels
                row_has = False
                for x in range(width):
                    idx = row_start + x * channels
                    if (
                        data[idx] < 255
                        or data[idx + 1] < 255
                        or data[idx + 2] < 255
                        or (channels == 4 and data[idx + 3] < 255)
                    ):
                        if x < left:
                            left = x
                        if x > right:
                            right = x
                        row_has = True
                if row_has:
                    if y < top:
                        top = y
                    bottom = y

        if right < 0:
            return None
        return (left, top, right + 1, bottom + 1)

    def resize(self, size: tuple[int, int], resample: Resampling = Resampling.NEAREST) -> "SimpleImage":
        """缩放图像."""
        # 当前仅实现最近邻，保持接口兼容。
        _ = resample
        new_w, new_h = size
        if new_w <= 0 or new_h <= 0:
            raise ValueError("Resize target must be positive.")

        if _CIMAGE_ACCEL is not None:
            try:
                out = _CIMAGE_ACCEL.resize_nearest(
                    bytes(self._data),
                    self.mode,
                    self.width,
                    self.height,
                    new_w,
                    new_h,
                )
                return SimpleImage(self.mode, (new_w, new_h), out)
            except Exception:  # noqa: BLE001
                pass

        channels = _MODES[self.mode].channels
        out = bytearray(new_w * new_h * channels)
        x_offsets = [(min((x * self.width) // new_w, self.width - 1) * channels) for x in range(new_w)]
        src_row_stride = self.width * channels
        dst_row_stride = new_w * channels

        for y in range(new_h):
            src_y = min((y * self.height) // new_h, self.height - 1)
            src_row = src_y * src_row_stride
            dst_row = y * dst_row_stride
            for x, src_off in enumerate(x_offsets):
                dst_idx = dst_row + x * channels
                src_idx = src_row + src_off
                out[dst_idx : dst_idx + channels] = self._data[src_idx : src_idx + channels]

        return SimpleImage(self.mode, (new_w, new_h), out)

    def thumbnail(self, size: tuple[int, int], resample: Resampling = Resampling.NEAREST) -> None:
        """原地等比缩略图."""
        max_w, max_h = size
        if self.width <= max_w and self.height <= max_h:
            return
        ratio = min(max_w / self.width, max_h / self.height)
        new_w = max(1, int(self.width * ratio))
        new_h = max(1, int(self.height * ratio))
        resized = self.resize((new_w, new_h), resample=resample)
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


def _normalize_color(mode: str, color: int | tuple[int, ...] | str) -> bytes:
    if isinstance(color, str):
        named = {"white": 255, "black": 0}
        if color.lower() not in named:
            raise ValueError(f"Unsupported color name: {color}")
        color = named[color.lower()]
    return bytes(_normalize_pixel(mode, color))


def _normalize_pixel(mode: str, value: int | tuple[int, ...]) -> tuple[int, ...]:
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


def _to_rgb_tuple(mode: str, data: bytearray | bytes) -> tuple[int, int, int]:
    if mode == "L":
        v = data[0]
        return (v, v, v)
    if mode == "RGB":
        return (data[0], data[1], data[2])
    return (data[0], data[1], data[2])


def _clamp_u8(value: int) -> int:
    return max(0, min(255, int(value)))
