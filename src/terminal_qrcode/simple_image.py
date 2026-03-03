"""轻量级图像模块."""

import enum
import io
import logging
import os
import struct
import subprocess
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, Protocol, cast

from terminal_qrcode.codecs import (
    PngDecodeError,
    PngEncodeError,
    PngUnavailableError,
    TurboJpegDecodeError,
    TurboJpegUnavailableError,
    WebPDecodeError,
    WebPUnavailableError,
    decode_jpeg_rgb_cffi,
    decode_png_with_libpng_cffi,
    decode_webp_rgba_cffi,
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
    try:
        from terminal_qrcode import _cimage

        _CIMAGE_ACCEL = cast(CImageAccelProtocol, _cimage)
    except Exception:  # noqa: BLE001
        _CIMAGE_ACCEL = None


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
            mode, width, height, out = decode_png_with_libpng_cffi(data)
            logger.debug("SimpleImage PNG decode: using cffi libpng.")
            return cls(mode, (width, height), out)
        except (PngUnavailableError, PngDecodeError) as exc:
            logger.debug("SimpleImage PNG decode: cffi libpng unavailable/failed. err=%r", exc)

        if _CIMAGE_ACCEL is not None:
            image = cls._decode_png_with_pyd(data)
            if image is not None:
                return image
        logger.debug("SimpleImage PNG decode: fallback to Python parser.")
        return cls._from_png_stream(io.BytesIO(data))

    @classmethod
    def _decode_png_with_pyd(cls, data: bytes) -> "SimpleImage | None":
        accel = _CIMAGE_ACCEL
        if accel is None:
            return None
        try:
            result = accel.decode_png_8bit(data)
        except Exception as exc:  # noqa: BLE001
            logger.debug("SimpleImage PNG decode: pyd failed. err=%r", exc)
            return None
        if not isinstance(result, tuple) or len(result) != 4:
            logger.debug("SimpleImage PNG decode: pyd returned invalid result.")
            return None
        mode_raw, width_raw, height_raw, out_raw = result
        logger.debug("SimpleImage PNG decode: using pyd accelerator.")
        return cls(str(mode_raw), (int(width_raw), int(height_raw)), bytes(out_raw))

    @classmethod
    def _decode_jpeg_pipeline(cls, jpeg_data: bytes) -> "SimpleImage":
        if _CIMAGE_ACCEL is not None:
            decode_jpeg = cls._decode_jpeg_with_pyd
            decoded = decode_jpeg(jpeg_data)
            if decoded is not None:
                width, height, rgb = decoded
                logger.debug("SimpleImage JPEG decode: using pyd accelerator.")
                return cls("RGB", (width, height), rgb)
        try:
            width, height, rgb = decode_jpeg_rgb_cffi(jpeg_data)
            logger.debug("SimpleImage JPEG decode: using cffi turbojpeg.")
            return cls("RGB", (width, height), rgb)
        except TurboJpegUnavailableError as exc:
            logger.debug("SimpleImage JPEG decode: cffi turbojpeg unavailable. err=%r", exc)
            return cls._decode_jpeg_with_djpeg(jpeg_data)
        except TurboJpegDecodeError as exc:
            logger.debug("SimpleImage JPEG decode: cffi turbojpeg failed. err=%r", exc)
            return cls._decode_jpeg_with_djpeg(jpeg_data)

    @classmethod
    def _decode_webp_pipeline(cls, webp_data: bytes) -> "SimpleImage":
        if _CIMAGE_ACCEL is not None:
            decode_webp = cls._decode_webp_with_pyd
            decoded = decode_webp(webp_data)
            if decoded is not None:
                width, height, rgba = decoded
                logger.debug("SimpleImage WEBP decode: using pyd accelerator.")
                return cls("RGBA", (width, height), rgba)
        try:
            width, height, rgba = decode_webp_rgba_cffi(webp_data)
            logger.debug("SimpleImage WEBP decode: using cffi libwebp.")
            return cls("RGBA", (width, height), rgba)
        except WebPUnavailableError as exc:
            logger.debug("SimpleImage WEBP decode: cffi libwebp unavailable. err=%r", exc)
            return cls._decode_webp_with_dwebp(webp_data)
        except WebPDecodeError as exc:
            logger.debug("SimpleImage WEBP decode: cffi libwebp failed. err=%r", exc)
            return cls._decode_webp_with_dwebp(webp_data)

    @staticmethod
    def _decode_jpeg_with_pyd(_jpeg_data: bytes) -> tuple[int, int, bytes] | None:
        """预留 pyd JPEG 解码接口."""
        return None

    @staticmethod
    def _decode_webp_with_pyd(_webp_data: bytes) -> tuple[int, int, bytes] | None:
        """预留 pyd WEBP 解码接口."""
        return None

    @classmethod
    def _decode_jpeg_with_djpeg(cls, jpeg_data: bytes) -> "SimpleImage":
        """使用 libjpeg 工具链(djpeg)回退解码 JPEG."""
        try:
            result = subprocess.run(
                ["djpeg", "-pnm"],
                input=jpeg_data,
                check=True,
                capture_output=True,
            )
            logger.debug("SimpleImage JPEG decode: using djpeg fallback.")
            return cls._from_pnm_bytes(result.stdout)
        except FileNotFoundError as exc:
            logger.debug("SimpleImage JPEG decode: djpeg unavailable. err=%r", exc)
            raise ValueError("JPEG decode requires libjpeg-turbo or libjpeg (djpeg).") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore").strip()
            msg = stderr if stderr else "Failed to decode JPEG with djpeg."
            logger.debug("SimpleImage JPEG decode: djpeg failed. err=%s", msg)
            raise ValueError(msg) from exc

    @classmethod
    def _decode_webp_with_dwebp(cls, webp_data: bytes) -> "SimpleImage":
        """使用 dwebp 命令回退解码 WEBP."""
        try:
            result = subprocess.run(
                ["dwebp", "-", "-pnm", "-o", "-"],
                input=webp_data,
                check=True,
                capture_output=True,
            )
            logger.debug("SimpleImage WEBP decode: using dwebp fallback.")
            return cls._from_pnm_bytes(result.stdout)
        except FileNotFoundError as exc:
            logger.debug("SimpleImage WEBP decode: dwebp unavailable. err=%r", exc)
            raise ValueError("WEBP decode requires libwebp or dwebp.") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore").strip()
            msg = stderr if stderr else "Failed to decode WEBP with dwebp."
            logger.debug("SimpleImage WEBP decode: dwebp failed. err=%s", msg)
            raise ValueError(msg) from exc

    @classmethod
    def _from_png_stream(cls, stream: BinaryIO) -> "SimpleImage":
        """解析 PNG 流."""
        signature = stream.read(8)
        if signature != b"\x89PNG\r\n\x1a\n":
            raise ValueError("Only PNG images are supported.")

        width = height = 0
        bit_depth = 0
        color_type = 0
        idat_parts: list[bytes] = []

        while True:
            length_bytes = stream.read(4)
            if len(length_bytes) != 4:
                raise ValueError("Invalid PNG: missing chunk length.")
            length = struct.unpack(">I", length_bytes)[0]
            ctype = stream.read(4)
            payload = stream.read(length)
            _crc = stream.read(4)
            if len(ctype) != 4 or len(payload) != length:
                raise ValueError("Invalid PNG: broken chunk payload.")

            if ctype == b"IHDR":
                width, height, bit_depth, color_type, compression, flt, interlace = struct.unpack(">IIBBBBB", payload)
                if compression != 0 or flt != 0 or interlace != 0:
                    raise ValueError("Unsupported PNG compression/filter/interlace.")
                if color_type == 0:
                    if bit_depth not in (1, 2, 4, 8):
                        raise ValueError("Only grayscale PNG bit depth 1/2/4/8 is supported.")
                elif color_type in (2, 6):
                    if bit_depth != 8:
                        raise ValueError("Only 8-bit RGB/RGBA PNG is supported.")
                else:
                    raise ValueError("Only grayscale/RGB/RGBA PNG is supported.")
            elif ctype == b"IDAT":
                idat_parts.append(payload)
            elif ctype == b"IEND":
                break

        if width <= 0 or height <= 0:
            raise ValueError("Invalid PNG: missing IHDR.")
        if not idat_parts:
            raise ValueError("Invalid PNG: missing IDAT.")

        raw = zlib.decompress(b"".join(idat_parts))
        channels = {0: 1, 2: 3, 6: 4}[color_type]
        if color_type == 0 and bit_depth < 8:
            stride = (width * bit_depth + 7) // 8
        else:
            stride = width * channels
        expected = (stride + 1) * height
        if len(raw) != expected:
            raise ValueError("Invalid PNG data length.")

        if color_type == 0:
            out = bytearray(width * height)
        else:
            out = bytearray(width * height * channels)
        prev = bytes(stride)
        src = 0
        dst = 0

        for _ in range(height):
            filter_type = raw[src]
            src += 1
            row = bytearray(raw[src : src + stride])
            src += stride
            _unfilter_row(row, prev, filter_type, channels)
            if color_type == 0 and bit_depth < 8:
                expanded = _expand_packed_grayscale(bytes(row), width, bit_depth)
                out[dst : dst + width] = expanded
                dst += width
            else:
                out[dst : dst + stride] = row
                dst += stride
            prev = bytes(row)

        mode = {0: "L", 2: "RGB", 6: "RGBA"}[color_type]
        return cls(mode, (width, height), out)

    @classmethod
    def _from_pnm_bytes(cls, data: bytes) -> "SimpleImage":
        """解析二进制 PNM(P5/P6)."""
        if not data.startswith((b"P5", b"P6")):
            raise ValueError("Unsupported PNM format.")
        mode = "L" if data[:2] == b"P5" else "RGB"

        tokens: list[bytes] = []
        i = 2
        n = len(data)
        while len(tokens) < 3:
            while i < n and data[i] in b" \t\r\n":
                i += 1
            if i >= n:
                raise ValueError("Invalid PNM header.")
            if data[i] == ord("#"):
                while i < n and data[i] != ord("\n"):
                    i += 1
                continue
            start = i
            while i < n and data[i] not in b" \t\r\n":
                i += 1
            tokens.append(data[start:i])

        width = int(tokens[0])
        height = int(tokens[1])
        maxval = int(tokens[2])
        if maxval != 255:
            raise ValueError("Only 8-bit PNM is supported.")

        if i >= n or data[i] not in b" \t\r\n":
            raise ValueError("Invalid PNM payload delimiter.")
        if data[i] == ord("\r") and i + 1 < n and data[i + 1] == ord("\n"):
            i += 2
        else:
            i += 1
        payload = data[i:]
        channels = 1 if mode == "L" else 3
        expected = width * height * channels
        if len(payload) < expected:
            raise ValueError("PNM payload is truncated.")
        return cls(mode, (width, height), payload[:expected])

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
            logger.debug("SimpleImage PNG encode: using libpng.")
            return out
        except (PngUnavailableError, PngEncodeError):
            pass

        if _CIMAGE_ACCEL is not None:
            try:
                out = _CIMAGE_ACCEL.encode_png_8bit(bytes(self._data), self.mode, self.width, self.height)
                logger.debug("SimpleImage PNG encode: using C accelerator.")
                return bytes(out)
            except Exception as exc:  # noqa: BLE001
                logger.debug("SimpleImage PNG encode: C accelerator failed, fallback to Python. err=%r", exc)

        color_type = {"L": 0, "RGB": 2, "RGBA": 6}[self.mode]
        channels = _MODES[self.mode].channels
        stride = self.width * channels

        raw = bytearray()
        for y in range(self.height):
            raw.append(0)  # filter type 0
            start = y * stride
            raw.extend(self._data[start : start + stride])
        compressed = zlib.compress(bytes(raw), level=6)

        out = bytearray(b"\x89PNG\r\n\x1a\n")
        ihdr = struct.pack(">IIBBBBB", self.width, self.height, 8, color_type, 0, 0, 0)
        out.extend(_png_chunk(b"IHDR", ihdr))
        out.extend(_png_chunk(b"IDAT", compressed))
        out.extend(_png_chunk(b"IEND", b""))
        return bytes(out)


def get_c_accel_status() -> dict[str, bool]:
    """返回可选 C 加速能力状态."""
    loaded = _CIMAGE_ACCEL is not None
    return {
        "loaded": loaded,
        "decode_png": loaded,
        "encode_png": loaded,
        "threshold_to_bits": loaded,
        "sixel_encode_mono": loaded,
        "convert": loaded,
        "getbbox_nonwhite": loaded,
        "resize_nearest": loaded,
    }


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


def _png_chunk(ctype: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(ctype + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + ctype + payload + struct.pack(">I", crc)


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter_row(row: bytearray, prev: bytes, filter_type: int, channels: int) -> None:
    if filter_type == 0:
        return
    if filter_type == 1:
        for i in range(len(row)):
            left = row[i - channels] if i >= channels else 0
            row[i] = (row[i] + left) & 0xFF
        return
    if filter_type == 2:
        for i in range(len(row)):
            row[i] = (row[i] + prev[i]) & 0xFF
        return
    if filter_type == 3:
        for i in range(len(row)):
            left = row[i - channels] if i >= channels else 0
            up = prev[i]
            row[i] = (row[i] + ((left + up) // 2)) & 0xFF
        return
    if filter_type == 4:
        for i in range(len(row)):
            left = row[i - channels] if i >= channels else 0
            up = prev[i]
            up_left = prev[i - channels] if i >= channels else 0
            row[i] = (row[i] + _paeth_predictor(left, up, up_left)) & 0xFF
        return
    raise ValueError(f"Unsupported PNG filter type: {filter_type}")


def _expand_packed_grayscale(row: bytes, width: int, bit_depth: int) -> bytes:
    """将打包灰度样本（1/2/4-bit）展开为 8-bit 灰度行."""
    max_sample = (1 << bit_depth) - 1
    mask = max_sample
    out = bytearray(width)

    for x in range(width):
        bit_pos = x * bit_depth
        byte_idx = bit_pos // 8
        shift = 8 - bit_depth - (bit_pos % 8)
        sample = (row[byte_idx] >> shift) & mask
        out[x] = (sample * 255) // max_sample
    return bytes(out)
