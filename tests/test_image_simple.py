"""SimpleImage 模块的测试集."""

import io
import struct
import subprocess
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import terminal_qrcode.simple_image as simple_image
from terminal_qrcode.codecs import PngUnavailableError, TurboJpegUnavailableError, WebPUnavailableError
from terminal_qrcode.simple_image import SimpleImage, get_c_accel_status


def test_open_bmp_unsupported_format(tmp_path):
    """验证 BMP 输入直接报不支持格式."""
    path = tmp_path / "x.bmp"
    path.write_bytes(b"BM")
    with pytest.raises(ValueError, match="Supported formats: JPEG, PNG, WEBP"):
        SimpleImage.open(path)


def test_open_gif_unsupported_format(tmp_path):
    """验证 GIF 输入直接报不支持格式."""
    path = tmp_path / "x.gif"
    path.write_bytes(b"GIF89a")
    with pytest.raises(ValueError, match="Supported formats: JPEG, PNG, WEBP"):
        SimpleImage.open(path)


def test_open_unknown_ext_unsupported_format(tmp_path):
    """验证未知后缀直接报不支持格式."""
    path = tmp_path / "x.tiff"
    path.write_bytes(b"dummy")
    with pytest.raises(ValueError, match="Supported formats: JPEG, PNG, WEBP"):
        SimpleImage.open(path)


def test_open_png_magic_ignores_file_suffix(tmp_path):
    """验证打开图片时按魔数识别 PNG, 不依赖文件后缀."""
    path = tmp_path / "x.bin"
    path.write_bytes(SimpleImage.new("RGB", (1, 1), (1, 2, 3)).to_png_bytes())

    img = SimpleImage.open(path)
    assert img.mode == "RGB"
    assert img.getpixel((0, 0)) == (1, 2, 3)


def test_convert_rgba_to_l_ignores_alpha_channel():
    """验证 RGBA 转灰度时仅按 RGB 通道计算."""
    img = SimpleImage.new("RGBA", (1, 1), (10, 20, 30, 0))
    gray = img.convert("L")
    assert gray.mode == "L"
    assert gray.getpixel((0, 0)) == (299 * 10 + 587 * 20 + 114 * 30) // 1000


def test_getbbox_nonwhite_rgb_returns_minimal_box():
    """验证 RGB 模式下 nonwhite 包围盒计算正确."""
    img = SimpleImage.new("RGB", (4, 4), (255, 255, 255))
    img.putpixel((2, 1), (0, 0, 0))
    img.putpixel((3, 2), (10, 255, 255))
    assert img.getbbox_nonwhite() == (2, 1, 4, 3)


def test_convert_prefers_c_accel_when_available(monkeypatch):
    """验证存在 C 加速模块时 convert 优先调用加速实现."""
    calls: list[tuple[str, str, int, int]] = []

    def fake_convert(data, src_mode, dst_mode, width, height):
        calls.append((src_mode, dst_mode, width, height))
        return bytes([7, 8, 9])

    monkeypatch.setattr(simple_image, "_CIMAGE_ACCEL", SimpleNamespace(convert=fake_convert))
    img = SimpleImage.new("L", (1, 1), 3)
    out = img.convert("RGB")

    assert calls == [("L", "RGB", 1, 1)]
    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (7, 8, 9)


def test_convert_falls_back_when_c_accel_raises(monkeypatch):
    """验证 C 加速实现异常时 convert 会自动回退 Python 路径."""

    def fake_convert(data, src_mode, dst_mode, width, height):
        raise RuntimeError("boom")

    monkeypatch.setattr(simple_image, "_CIMAGE_ACCEL", SimpleNamespace(convert=fake_convert))
    img = SimpleImage.new("L", (1, 1), 9)
    out = img.convert("RGB")

    assert out.mode == "RGB"
    assert out.getpixel((0, 0)) == (9, 9, 9)


def test_resize_prefers_c_accel_when_available(monkeypatch):
    """验证存在 C 加速模块时 resize 优先调用加速实现."""
    calls: list[tuple[str, int, int, int, int]] = []

    def fake_resize(data, mode, src_w, src_h, dst_w, dst_h):
        calls.append((mode, src_w, src_h, dst_w, dst_h))
        return bytes([5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])

    monkeypatch.setattr(simple_image, "_CIMAGE_ACCEL", SimpleNamespace(resize_nearest=fake_resize))
    img = SimpleImage.new("RGB", (1, 1), (1, 2, 3))
    out = img.resize((2, 2))

    assert calls == [("RGB", 1, 1, 2, 2)]
    assert out.mode == "RGB"
    assert out.width == 2
    assert out.height == 2


def test_c_accel_status_reports_png_and_render_flags():
    """验证加速状态包含 PNG 与渲染相关能力键."""
    status = get_c_accel_status()
    assert "decode_png" in status
    assert "encode_png" in status
    assert "threshold_to_bits" in status
    assert "sixel_encode_mono" in status


def test_c_accel_status_excludes_bmp_gif_flags():
    """验证加速状态不再暴露 BMP/GIF 解码标志."""
    status = get_c_accel_status()
    assert "decode_bmp" not in status
    assert "decode_gif_first_frame" not in status


def test_open_png_prefers_cffi_then_pyd(monkeypatch, tmp_path):
    """验证 PNG 打开按 cffi 优先，且不会继续走 pyd."""
    calls: list[bytes] = []

    def fake_decode_png(data: bytes) -> tuple[str, int, int, bytes]:
        calls.append(data)
        return ("RGB", 1, 1, bytes([9, 8, 7]))

    monkeypatch.setattr(
        simple_image,
        "decode_png_with_libpng_cffi",
        lambda data: ("RGB", 1, 1, bytes([4, 5, 6])),
    )
    monkeypatch.setattr(simple_image, "_CIMAGE_ACCEL", SimpleNamespace(decode_png_8bit=fake_decode_png))
    path = tmp_path / "x.png"
    path.write_bytes(SimpleImage.new("RGB", (1, 1), (1, 2, 3)).to_png_bytes())

    img = SimpleImage.open(path)
    assert calls == []
    assert img.getpixel((0, 0)) == (4, 5, 6)


def test_open_png_falls_back_to_pyd_when_cffi_fails(monkeypatch, tmp_path):
    """验证 PNG 的 cffi 失败时会回退 pyd 路径."""
    monkeypatch.setattr(
        simple_image,
        "decode_png_with_libpng_cffi",
        lambda data: (_ for _ in ()).throw(PngUnavailableError("missing")),
    )
    monkeypatch.setattr(
        simple_image,
        "_CIMAGE_ACCEL",
        SimpleNamespace(decode_png_8bit=lambda data: ("RGB", 1, 1, bytes([9, 8, 7]))),
    )
    path = tmp_path / "x.png"
    path.write_bytes(SimpleImage.new("RGB", (1, 1), (1, 2, 3)).to_png_bytes())

    img = SimpleImage.open(path)
    assert img.getpixel((0, 0)) == (9, 8, 7)


def test_open_png_falls_back_to_python_when_cffi_unavailable(monkeypatch, tmp_path):
    """验证 PNG 的 cffi 不可用时会回退 Python 解析."""
    monkeypatch.setattr(
        simple_image,
        "decode_png_with_libpng_cffi",
        lambda data: (_ for _ in ()).throw(PngUnavailableError("missing")),
    )
    monkeypatch.setattr(simple_image, "_CIMAGE_ACCEL", None)
    path = tmp_path / "x.png"
    path.write_bytes(SimpleImage.new("RGB", (1, 1), (1, 2, 3)).to_png_bytes())

    img = SimpleImage.open(path)
    assert img.getpixel((0, 0)) == (1, 2, 3)


def test_open_1bit_grayscale_png_via_python_fallback(monkeypatch):
    """验证纯 Python PNG 解析支持 1-bit 灰度图."""
    png_sig = b"\x89PNG\r\n\x1a\n"

    def _chunk(ctype: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(ctype + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + ctype + payload + struct.pack(">I", crc)

    # 8x1, 1-bit grayscale, pattern: 10101010 -> 255,0,255,0,255,0,255,0
    ihdr = struct.pack(">IIBBBBB", 8, 1, 1, 0, 0, 0, 0)
    idat_payload = zlib.compress(b"\x00\xaa")
    png_data = png_sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat_payload) + _chunk(b"IEND", b"")

    monkeypatch.setattr(
        simple_image,
        "decode_png_with_libpng_cffi",
        lambda data: (_ for _ in ()).throw(PngUnavailableError("missing")),
    )
    monkeypatch.setattr(
        simple_image,
        "_CIMAGE_ACCEL",
        SimpleNamespace(decode_png_8bit=lambda data: (_ for _ in ()).throw(ValueError("unsupported"))),
    )

    img = SimpleImage.from_bytes(png_data)
    assert img.mode == "L"
    assert img.width == 8
    assert img.height == 1
    assert [img.getpixel((x, 0)) for x in range(8)] == [255, 0, 255, 0, 255, 0, 255, 0]


def test_c_accel_decode_png_supports_1bit_grayscale():
    """验证 _cimage.decode_png_8bit 支持 1-bit 灰度 PNG."""
    accel = simple_image._CIMAGE_ACCEL
    if accel is None:
        pytest.skip("C accelerator unavailable")

    png_sig = b"\x89PNG\r\n\x1a\n"

    def _chunk(ctype: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(ctype + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + ctype + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 8, 1, 1, 0, 0, 0, 0)
    idat_payload = zlib.compress(b"\x00\xaa")
    png_data = png_sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat_payload) + _chunk(b"IEND", b"")

    mode, width, height, pixels = accel.decode_png_8bit(png_data)

    assert mode == "L"
    assert width == 8
    assert height == 1
    assert list(pixels) == [255, 0, 255, 0, 255, 0, 255, 0]


def test_open_jpeg_falls_back_to_djpeg(monkeypatch):
    """验证 JPEG cffi 不可用时会回退 djpeg."""
    pnm = b"P6\n1 1\n255\n" + bytes([1, 2, 3])
    with (
        patch("pathlib.Path.read_bytes", return_value=b"\xff\xd8\xff\xdb"),
        patch(
            "terminal_qrcode.simple_image.decode_jpeg_rgb_cffi",
            side_effect=TurboJpegUnavailableError("missing"),
        ),
        patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(args=["djpeg", "-pnm"], returncode=0, stdout=pnm, stderr=b""),
        ),
    ):
        img = SimpleImage.open(Path("x.jpg"))
    assert img.getpixel((0, 0)) == (1, 2, 3)


def test_open_jpeg_reports_error_when_djpeg_missing(monkeypatch):
    """验证 JPEG 后端都不可用且 djpeg 缺失时抛明确错误."""
    with (
        patch("pathlib.Path.read_bytes", return_value=b"\xff\xd8\xff\xdb"),
        patch(
            "terminal_qrcode.simple_image.decode_jpeg_rgb_cffi",
            side_effect=TurboJpegUnavailableError("missing"),
        ),
        patch("subprocess.run", side_effect=FileNotFoundError("djpeg")),
    ):
        with pytest.raises(ValueError, match="libjpeg-turbo or libjpeg"):
            SimpleImage.open(Path("x.jpg"))


def test_open_webp_falls_back_to_dwebp(monkeypatch):
    """验证 WEBP cffi 不可用时会回退 dwebp."""
    webp_header = b"RIFF\x10\x00\x00\x00WEBP"
    pnm = b"P6\n1 1\n255\n" + bytes([6, 7, 8])
    with (
        patch("pathlib.Path.read_bytes", return_value=webp_header),
        patch(
            "terminal_qrcode.simple_image.decode_webp_rgba_cffi",
            side_effect=WebPUnavailableError("missing"),
        ),
        patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["dwebp", "-", "-pnm", "-o", "-"],
                returncode=0,
                stdout=pnm,
                stderr=b"",
            ),
        ),
    ):
        img = SimpleImage.open(Path("x.webp"))
    assert img.getpixel((0, 0)) == (6, 7, 8)


def test_open_webp_reports_error_when_dwebp_missing(monkeypatch):
    """验证 WEBP 后端都不可用且 dwebp 缺失时抛明确错误."""
    webp_header = b"RIFF\x10\x00\x00\x00WEBP"
    with (
        patch("pathlib.Path.read_bytes", return_value=webp_header),
        patch(
            "terminal_qrcode.simple_image.decode_webp_rgba_cffi",
            side_effect=WebPUnavailableError("missing"),
        ),
        patch("subprocess.run", side_effect=FileNotFoundError("dwebp")),
    ):
        with pytest.raises(ValueError, match="libwebp or dwebp"):
            SimpleImage.open(Path("x.webp"))


def test_from_bytes_and_open_consistent_behavior(monkeypatch):
    """验证同一 JPEG 输入在 open 与 from_bytes 的行为一致."""
    jpeg_header = b"\xff\xd8\xff\xe0"
    monkeypatch.setattr(simple_image, "_CIMAGE_ACCEL", None)
    monkeypatch.setattr(
        simple_image,
        "decode_jpeg_rgb_cffi",
        lambda raw: (1, 1, bytes([3, 2, 1])),
    )
    with patch("pathlib.Path.read_bytes", return_value=jpeg_header):
        img_from_open = SimpleImage.open(Path("x.jpg"))
    img_from_bytes = SimpleImage.from_bytes(jpeg_header)
    assert img_from_open.getpixel((0, 0)) == img_from_bytes.getpixel((0, 0))


def test_to_png_bytes_prefers_c_accel(monkeypatch):
    """验证 PNG 编码会优先走可选 C 加速路径."""
    calls: list[tuple[bytes, str, int, int]] = []

    def fake_encode_png(data: bytes, mode: str, width: int, height: int) -> bytes:
        calls.append((data, mode, width, height))
        return b"\x89PNG\r\n\x1a\nFAKE"

    monkeypatch.setattr(
        simple_image,
        "encode_png_with_libpng",
        lambda data, mode, width, height: (_ for _ in ()).throw(PngUnavailableError("missing")),
    )
    monkeypatch.setattr(simple_image, "_CIMAGE_ACCEL", SimpleNamespace(encode_png_8bit=fake_encode_png))
    img = SimpleImage.new("RGB", (1, 1), (1, 2, 3))
    out = img.to_png_bytes()

    assert calls and calls[0][1:] == ("RGB", 1, 1)
    assert out.startswith(b"\x89PNG\r\n\x1a\n")


def test_to_png_bytes_falls_back_when_c_accel_raises(monkeypatch):
    """验证 PNG 编码的 C 路径异常时会回退 Python 实现."""

    def fake_encode_png(data: bytes, mode: str, width: int, height: int) -> bytes:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        simple_image,
        "encode_png_with_libpng",
        lambda data, mode, width, height: (_ for _ in ()).throw(PngUnavailableError("missing")),
    )
    monkeypatch.setattr(simple_image, "_CIMAGE_ACCEL", SimpleNamespace(encode_png_8bit=fake_encode_png))
    img = SimpleImage.new("RGB", (1, 1), (1, 2, 3))
    out = img.to_png_bytes()
    reopened = SimpleImage._from_png_stream(io.BytesIO(out))
    assert out.startswith(b"\x89PNG\r\n\x1a\n")
    assert reopened.getpixel((0, 0)) == (1, 2, 3)
