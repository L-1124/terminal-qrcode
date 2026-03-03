"""图像编解码后端整合模块."""

import logging
import os
import sys
import tempfile
from functools import lru_cache
from importlib import resources as importlib_resources
from typing import Any

PNG_IMAGE_VERSION = 1
PNG_FORMAT_FLAG_COLOR = 0x02
PNG_FORMAT_FLAG_ALPHA = 0x04
PNG_FORMAT_GRAY = 0x00
PNG_FORMAT_RGB = PNG_FORMAT_FLAG_COLOR
PNG_FORMAT_RGBA = PNG_FORMAT_FLAG_COLOR | PNG_FORMAT_FLAG_ALPHA

TJPF_RGB = 0
_MAX_SAFE_PIXELS = 8_294_400

logger = logging.getLogger(__name__)

_LIBPNG_CDEF = """
typedef unsigned int uint32_t;
typedef unsigned long size_t;
typedef int int32_t;
typedef struct {
    void *opaque;
    uint32_t version;
    uint32_t width;
    uint32_t height;
    uint32_t format;
    uint32_t flags;
    uint32_t colormap_entries;
    uint32_t warning_or_error;
    char message[64];
} png_image;
int png_image_begin_read_from_memory(png_image *image, const void *memory, size_t size);
int png_image_finish_read(
    png_image *image,
    const void *background,
    void *buffer,
    int32_t row_stride,
    void *colormap
);
int png_image_write_to_memory(
    png_image *image,
    void *memory,
    size_t *memory_bytes,
    int convert_to_8bit,
    const void *buffer,
    int32_t row_stride,
    const void *colormap
);
void png_image_free(png_image *image);
"""

_TURBOJPEG_CDEF = """
typedef void *tjhandle;
tjhandle tjInitDecompress(void);
int tjDecompressHeader3(
    tjhandle handle,
    const unsigned char *jpegBuf,
    unsigned long jpegSize,
    int *width,
    int *height,
    int *jpegSubsamp,
    int *jpegColorspace
);
int tjDecompress2(
    tjhandle handle,
    const unsigned char *jpegBuf,
    unsigned long jpegSize,
    unsigned char *dstBuf,
    int width,
    int pitch,
    int height,
    int pixelFormat,
    int flags
);
int tjDestroy(tjhandle handle);
char *tjGetErrorStr2(tjhandle handle);
char *tjGetErrorStr(void);
"""

_WEBP_CDEF = """
typedef unsigned char uint8_t;
typedef unsigned long size_t;
int WebPGetInfo(const uint8_t *data, size_t data_size, int *width, int *height);
uint8_t *WebPDecodeRGBA(const uint8_t *data, size_t data_size, int *width, int *height);
void WebPFree(void *ptr);
"""

_SIXEL_CDEF = """
typedef struct sixel_encoder sixel_encoder_t;
int sixel_encoder_new(sixel_encoder_t **ppencoder, void *allocator);
void sixel_encoder_unref(sixel_encoder_t *encoder);
int sixel_encoder_setopt(sixel_encoder_t *encoder, int arg, const char *value);
int sixel_encoder_encode(sixel_encoder_t *encoder, const char *filename);
"""

__all__ = [
    "PngUnavailableError",
    "PngDecodeError",
    "PngEncodeError",
    "decode_png_with_libpng_cffi",
    "decode_png_with_libpng",
    "encode_png_with_libpng",
    "TurboJpegUnavailableError",
    "TurboJpegDecodeError",
    "decode_jpeg_rgb_cffi",
    "decode_jpeg_rgb",
    "WebPUnavailableError",
    "WebPDecodeError",
    "decode_webp_rgba_cffi",
    "decode_webp_rgba",
    "SixelUnavailableError",
    "SixelEncodeError",
    "encode_sixel_with_libsixel",
    "_decode_with_lib",
]


class PngUnavailableError(RuntimeError):
    """系统缺少 libpng 动态库."""


class PngDecodeError(RuntimeError):
    """libpng 解码失败."""


class PngEncodeError(RuntimeError):
    """libpng 编码失败."""


class TurboJpegUnavailableError(RuntimeError):
    """系统缺少 TurboJPEG 动态库."""


class TurboJpegDecodeError(RuntimeError):
    """TurboJPEG 解码失败."""


class WebPUnavailableError(RuntimeError):
    """系统缺少 libwebp 动态库."""


class WebPDecodeError(RuntimeError):
    """libwebp 解码失败."""


class SixelUnavailableError(RuntimeError):
    """系统缺少 libsixel 动态库或 cffi 运行时."""


class SixelEncodeError(RuntimeError):
    """libsixel 编码失败."""


def decode_png_with_libpng_cffi(png_data: bytes) -> tuple[str, int, int, bytes]:
    """通过 cffi + libpng 解码 PNG."""
    lib_ctx = _load_libpng_cffi()
    if lib_ctx is None:
        raise PngUnavailableError("libpng library not found. Install libpng runtime.")
    return _decode_png_with_lib(lib_ctx, png_data)


def decode_png_with_libpng(png_data: bytes) -> tuple[str, int, int, bytes]:
    """兼容旧名称: 通过 cffi + libpng 解码 PNG."""
    return decode_png_with_libpng_cffi(png_data)


def encode_png_with_libpng(data: bytes, mode: str, width: int, height: int) -> bytes:
    """通过 cffi + libpng 编码 PNG."""
    lib_ctx = _load_libpng_cffi()
    if lib_ctx is None:
        raise PngUnavailableError("libpng library not found. Install libpng runtime.")
    return _encode_png_with_lib(lib_ctx, data, mode, width, height)


def decode_jpeg_rgb_cffi(jpeg_data: bytes) -> tuple[int, int, bytes]:
    """通过 cffi + turbojpeg 解码 JPEG."""
    lib_ctx = _load_turbojpeg_cffi()
    if lib_ctx is None:
        raise TurboJpegUnavailableError("TurboJPEG library not found. Install libjpeg-turbo runtime.")
    return _decode_with_lib(lib_ctx, jpeg_data)


def decode_jpeg_rgb(jpeg_data: bytes) -> tuple[int, int, bytes]:
    """兼容旧名称: 通过 cffi + turbojpeg 解码 JPEG."""
    return decode_jpeg_rgb_cffi(jpeg_data)


def decode_webp_rgba_cffi(webp_data: bytes) -> tuple[int, int, bytes]:
    """通过 cffi + libwebp 解码 WEBP."""
    lib_ctx = _load_libwebp_cffi()
    if lib_ctx is None:
        raise WebPUnavailableError("libwebp library not found. Install libwebp runtime.")
    return _decode_webp_with_lib(lib_ctx, webp_data)


def decode_webp_rgba(webp_data: bytes) -> tuple[int, int, bytes]:
    """兼容旧名称: 通过 cffi + libwebp 解码 WEBP."""
    return decode_webp_rgba_cffi(webp_data)


def encode_sixel_with_libsixel(png_data: bytes) -> str:
    """通过 cffi 调用 libsixel 编码 PNG 字节为 sixel 字符串."""
    if not png_data:
        raise SixelEncodeError("PNG payload is empty.")
    lib_ctx = _load_libsixel_cffi()
    if lib_ctx is None:
        raise SixelUnavailableError("libsixel/cffi unavailable.")
    return _encode_sixel_with_lib(lib_ctx, png_data)


@lru_cache(maxsize=1)
def _load_libpng_cffi() -> tuple[Any, Any] | None:
    return _load_cffi_lib(
        cdef=_LIBPNG_CDEF,
        win_candidates=("libpng16-16.dll", "libpng16.dll", "libpng.dll"),
        posix_candidates=("libpng16.so", "libpng.so", "libpng16.dylib", "libpng.dylib"),
    )


@lru_cache(maxsize=1)
def _load_turbojpeg_cffi() -> tuple[Any, Any] | None:
    return _load_cffi_lib(
        cdef=_TURBOJPEG_CDEF,
        win_candidates=("turbojpeg.dll", "libturbojpeg.dll"),
        posix_candidates=("libturbojpeg.so", "libturbojpeg.dylib", "turbojpeg.dylib"),
    )


@lru_cache(maxsize=1)
def _load_libwebp_cffi() -> tuple[Any, Any] | None:
    return _load_cffi_lib(
        cdef=_WEBP_CDEF,
        win_candidates=("libwebp.dll", "webp.dll"),
        posix_candidates=("libwebp.so", "libwebp.dylib", "webp.dylib"),
    )


@lru_cache(maxsize=1)
def _load_libsixel_cffi() -> tuple[Any, Any] | None:
    return _load_cffi_lib(
        cdef=_SIXEL_CDEF,
        win_candidates=("libsixel.dll", "sixel.dll"),
        posix_candidates=("libsixel.so", "libsixel.dylib", "sixel.dylib"),
    )


def _load_cffi_lib(
    *,
    cdef: str,
    win_candidates: tuple[str, ...],
    posix_candidates: tuple[str, ...],
) -> tuple[Any, Any] | None:
    try:
        cffi_module = __import__("cffi")
    except Exception as exc:
        logger.debug("cffi runtime unavailable: %r", exc)
        return None

    ffi = cffi_module.FFI()
    ffi.cdef(cdef)

    candidates: list[str] = []
    if os.name == "nt":
        candidates.extend(win_candidates)
    elif os.name == "posix":
        candidates.extend(posix_candidates)

    seen_path: set[str] = set()
    for resource in _iter_packaged_library_resources(tuple(candidates)):
        try:
            with importlib_resources.as_file(resource) as lib_path:
                path = str(lib_path)
                if not lib_path.exists() or path in seen_path:
                    continue
                seen_path.add(path)
                lib = ffi.dlopen(path)
        except Exception as exc:
            logger.debug("Failed to load packaged library candidate '%s': %r", resource, exc)
            continue
        logger.debug("Loaded packaged library candidate '%s' via cffi.", path)
        return ffi, lib

    seen: set[str] = set()
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        try:
            lib = ffi.dlopen(name)
        except Exception as exc:
            logger.debug("Failed to load dynamic library candidate '%s': %r", name, exc)
            continue
        logger.debug("Loaded dynamic library candidate '%s' via cffi.", name)
        return ffi, lib
    logger.debug("No dynamic library candidates could be loaded. candidates=%s", candidates)
    return None


def _iter_packaged_library_resources(candidates: tuple[str, ...]) -> list[Any]:
    try:
        package_root = importlib_resources.files("terminal_qrcode")
    except Exception as exc:
        logger.debug("Failed to resolve package resources for dynamic libraries: %r", exc)
        return []

    resources: list[Any] = []
    for subdir in _get_vendor_subdirs():
        base = package_root.joinpath(*subdir)
        for name in candidates:
            resources.append(base.joinpath(name))
    return resources


def _get_vendor_subdirs() -> tuple[tuple[str, ...], ...]:
    if os.name == "nt":
        return (("_vendor", "windows"), ("_vendor",))
    if os.name == "posix":
        if sys.platform == "darwin":
            return (("_vendor", "macos"), ("_vendor",))
        return (("_vendor", "linux"), ("_vendor",))
    return (("_vendor",),)


def _decode_png_with_lib(lib_ctx: tuple[Any, Any], png_data: bytes) -> tuple[str, int, int, bytes]:
    if not png_data:
        raise PngDecodeError("PNG payload is empty.")

    ffi, lib = lib_ctx
    image = ffi.new("png_image *")
    image.version = PNG_IMAGE_VERSION
    src = ffi.new("unsigned char[]", png_data)
    ok = int(lib.png_image_begin_read_from_memory(image, src, len(png_data)))
    if ok == 0:
        msg = ffi.string(image.message).decode("utf-8", errors="ignore")
        lib.png_image_free(image)
        raise PngDecodeError(msg or "png_image_begin_read_from_memory failed.")

    width = int(image.width)
    height = int(image.height)
    if width <= 0 or height <= 0:
        lib.png_image_free(image)
        raise PngDecodeError("Invalid PNG dimensions.")

    src_format = int(image.format)
    if src_format & PNG_FORMAT_FLAG_COLOR:
        if src_format & PNG_FORMAT_FLAG_ALPHA:
            mode = "RGBA"
            channels = 4
            image.format = PNG_FORMAT_RGBA
        else:
            mode = "RGB"
            channels = 3
            image.format = PNG_FORMAT_RGB
    else:
        mode = "L"
        channels = 1
        image.format = PNG_FORMAT_GRAY

    out_len = width * height * channels
    out = ffi.new("unsigned char[]", out_len)
    ok = int(lib.png_image_finish_read(image, ffi.NULL, out, 0, ffi.NULL))
    msg = ffi.string(image.message).decode("utf-8", errors="ignore")
    lib.png_image_free(image)
    if ok == 0:
        raise PngDecodeError(msg or "png_image_finish_read failed.")
    return mode, width, height, bytes(ffi.buffer(out, out_len))


def _encode_png_with_lib(lib_ctx: tuple[Any, Any], data: bytes, mode: str, width: int, height: int) -> bytes:
    if mode not in {"L", "RGB", "RGBA"}:
        raise PngEncodeError(f"Unsupported mode for PNG encode: {mode}")
    if width <= 0 or height <= 0:
        raise PngEncodeError("Invalid PNG dimensions.")
    channels = 1 if mode == "L" else (3 if mode == "RGB" else 4)
    expected = width * height * channels
    if len(data) != expected:
        raise PngEncodeError("Raw data length mismatch.")

    ffi, lib = lib_ctx
    image = ffi.new("png_image *")
    image.version = PNG_IMAGE_VERSION
    image.width = width
    image.height = height
    image.format = PNG_FORMAT_GRAY if mode == "L" else (PNG_FORMAT_RGB if mode == "RGB" else PNG_FORMAT_RGBA)

    src = ffi.new("unsigned char[]", data)
    size = ffi.new("size_t *", 0)
    ok = int(lib.png_image_write_to_memory(image, ffi.NULL, size, 0, src, 0, ffi.NULL))
    if ok == 0 and int(size[0]) == 0:
        msg = ffi.string(image.message).decode("utf-8", errors="ignore")
        lib.png_image_free(image)
        raise PngEncodeError(msg or "png_image_write_to_memory sizing failed.")

    out_len = int(size[0])
    out = ffi.new("unsigned char[]", out_len)
    ok = int(lib.png_image_write_to_memory(image, out, size, 0, src, 0, ffi.NULL))
    msg = ffi.string(image.message).decode("utf-8", errors="ignore")
    lib.png_image_free(image)
    if ok == 0:
        raise PngEncodeError(msg or "png_image_write_to_memory failed.")
    return bytes(ffi.buffer(out, out_len))


def _decode_with_lib(lib_ctx: tuple[Any, Any], jpeg_data: bytes) -> tuple[int, int, bytes]:
    if not jpeg_data:
        raise TurboJpegDecodeError("JPEG payload is empty.")

    ffi, lib = lib_ctx
    handle = lib.tjInitDecompress()
    if handle == ffi.NULL:
        raise TurboJpegDecodeError("tjInitDecompress failed.")

    src = ffi.new("unsigned char[]", jpeg_data)
    width = ffi.new("int *", 0)
    height = ffi.new("int *", 0)
    subsamp = ffi.new("int *", 0)
    colorspace = ffi.new("int *", 0)

    try:
        rc = int(
            lib.tjDecompressHeader3(
                handle,
                src,
                len(jpeg_data),
                width,
                height,
                subsamp,
                colorspace,
            )
        )
        if rc != 0:
            raise TurboJpegDecodeError(_get_error_message(lib, handle))

        width_val = int(width[0])
        height_val = int(height[0])
        if width_val <= 0 or height_val <= 0:
            raise TurboJpegDecodeError("Invalid JPEG dimensions.")
        total_pixels = width_val * height_val
        if total_pixels > _MAX_SAFE_PIXELS:
            raise TurboJpegDecodeError(
                f"Safety threshold exceeded: {width_val}x{height_val} "
                f"({total_pixels} pixels) > {_MAX_SAFE_PIXELS} pixels."
            )

        out_len = total_pixels * 3
        out = ffi.new("unsigned char[]", out_len)
        rc = int(
            lib.tjDecompress2(
                handle,
                src,
                len(jpeg_data),
                out,
                width_val,
                0,
                height_val,
                TJPF_RGB,
                0,
            )
        )
        if rc != 0:
            raise TurboJpegDecodeError(_get_error_message(lib, handle))
        return width_val, height_val, bytes(ffi.buffer(out, out_len))
    finally:
        lib.tjDestroy(handle)


def _decode_webp_with_lib(lib_ctx: tuple[Any, Any], webp_data: bytes) -> tuple[int, int, bytes]:
    if not webp_data:
        raise WebPDecodeError("WEBP payload is empty.")

    ffi, lib = lib_ctx
    src = ffi.new("uint8_t[]", webp_data)
    width = ffi.new("int *", 0)
    height = ffi.new("int *", 0)

    ok = int(lib.WebPGetInfo(src, len(webp_data), width, height))
    if ok == 0:
        raise WebPDecodeError("Invalid WEBP header.")
    width_val = int(width[0])
    height_val = int(height[0])
    if width_val <= 0 or height_val <= 0:
        raise WebPDecodeError("Invalid WEBP dimensions.")
    total_pixels = width_val * height_val
    if total_pixels > _MAX_SAFE_PIXELS:
        raise WebPDecodeError(
            f"Safety threshold exceeded: {width_val}x{height_val} ({total_pixels} pixels) > {_MAX_SAFE_PIXELS} pixels."
        )

    out_ptr = lib.WebPDecodeRGBA(src, len(webp_data), width, height)
    if out_ptr == ffi.NULL:
        raise WebPDecodeError("WebPDecodeRGBA failed.")
    try:
        out_len = width_val * height_val * 4
        return width_val, height_val, bytes(ffi.buffer(out_ptr, out_len))
    finally:
        lib.WebPFree(out_ptr)


def _encode_sixel_with_lib(lib_ctx: tuple[Any, Any], png_data: bytes) -> str:
    ffi, lib = lib_ctx
    encoder_ptr = ffi.new("sixel_encoder_t **")
    rc = int(lib.sixel_encoder_new(encoder_ptr, ffi.NULL))
    if rc != 0 or encoder_ptr[0] == ffi.NULL:
        raise SixelEncodeError("sixel_encoder_new failed.")

    in_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    out_file = tempfile.NamedTemporaryFile(suffix=".sixel", delete=False)
    in_path = in_file.name
    out_path = out_file.name
    in_file.close()
    out_file.close()

    try:
        with open(in_path, "wb") as f:
            f.write(png_data)

        rc = int(lib.sixel_encoder_setopt(encoder_ptr[0], ord("o"), ffi.new("char[]", out_path.encode("utf-8"))))
        if rc != 0:
            raise SixelEncodeError("sixel_encoder_setopt(output) failed.")

        rc = int(lib.sixel_encoder_encode(encoder_ptr[0], ffi.new("char[]", in_path.encode("utf-8"))))
        if rc != 0:
            raise SixelEncodeError("sixel_encoder_encode failed.")

        with open(out_path, "rb") as f:
            return f.read().decode("ascii", errors="ignore")
    finally:
        try:
            lib.sixel_encoder_unref(encoder_ptr[0])
        except Exception:
            pass
        try:
            os.remove(in_path)
        except OSError:
            pass
        try:
            os.remove(out_path)
        except OSError:
            pass


def _get_error_message(lib: Any, handle: Any) -> str:
    try:
        raw = lib.tjGetErrorStr2(handle)
    except Exception:
        try:
            raw = lib.tjGetErrorStr()
        except Exception:
            return "TurboJPEG decode failed."
    if raw is None:
        return "TurboJPEG decode failed."
    try:
        return bytes(raw).decode("utf-8", errors="ignore")
    except Exception:
        return "TurboJPEG decode failed."
