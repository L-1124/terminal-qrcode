"""SimpleImage 模块的测试集."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import terminal_qrcode.simple_image as simple_image
from terminal_qrcode import codecs
from terminal_qrcode.codecs import PngUnavailableError, TurboJpegUnavailableError, WebPUnavailableError
from terminal_qrcode.simple_image import SimpleImage


def _png_fixture_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9ccdbf\x01\x00\x00\x18\x00\x07\x10\xe7'\xc4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


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


def test_open_png_magic_ignores_file_suffix(monkeypatch, tmp_path):
    """验证打开图片时按魔数识别 PNG, 不依赖文件后缀."""
    monkeypatch.setattr(simple_image, "decode_png_with_libpng", lambda _data: ("RGB", 1, 1, bytes([1, 2, 3])))
    path = tmp_path / "x.bin"
    path.write_bytes(_png_fixture_bytes())
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


def test_c_accel_exports_match_runtime_module():
    """验证 simple_image 使用与 codecs 一致的 C 扩展模块引用."""
    assert simple_image._CIMAGE_ACCEL is codecs._cimage


def test_open_png_raises_when_c_backend_unavailable(monkeypatch, tmp_path):
    """验证 PNG 后端缺失时直接报错，不再回退手写解析."""
    monkeypatch.setattr(
        simple_image,
        "decode_png_with_libpng",
        lambda data: (_ for _ in ()).throw(PngUnavailableError("missing")),
    )
    path = tmp_path / "x.png"
    path.write_bytes(_png_fixture_bytes())

    with pytest.raises(ValueError, match="PNG decode requires C backend"):
        SimpleImage.open(path)


def test_c_accel_decode_png_supports_known_rgb_fixture(monkeypatch):
    """验证 PNG 解码入口可处理固定 RGB PNG 样本."""
    monkeypatch.setattr(
        simple_image,
        "decode_png_with_libpng",
        lambda data: ("RGB", 1, 1, bytes([1, 2, 3])),
    )
    img = SimpleImage.from_bytes(_png_fixture_bytes())
    assert img.mode == "RGB"
    assert img.getpixel((0, 0)) == (1, 2, 3)


def test_open_jpeg_raises_when_backend_unavailable(monkeypatch):
    """验证 JPEG 后端不可用时直接报错，不再回退命令行工具."""
    with (
        patch("pathlib.Path.read_bytes", return_value=b"\xff\xd8\xff\xdb"),
        patch(
            "terminal_qrcode.simple_image.decode_jpeg_rgb",
            side_effect=TurboJpegUnavailableError("missing"),
        ),
    ):
        with pytest.raises(ValueError, match="JPEG decode requires C backend"):
            SimpleImage.open(Path("x.jpg"))


def test_open_jpeg_reports_decode_error(monkeypatch):
    """验证 JPEG 后端返回解码错误时上抛统一错误."""
    with (
        patch("pathlib.Path.read_bytes", return_value=b"\xff\xd8\xff\xdb"),
        patch(
            "terminal_qrcode.simple_image.decode_jpeg_rgb",
            side_effect=simple_image.TurboJpegDecodeError("broken"),
        ),
    ):
        with pytest.raises(ValueError, match="Failed to decode JPEG with C backend"):
            SimpleImage.open(Path("x.jpg"))


def test_open_webp_raises_when_backend_unavailable(monkeypatch):
    """验证 WEBP 后端不可用时直接报错，不再回退命令行工具."""
    webp_header = b"RIFF\x10\x00\x00\x00WEBP"
    with (
        patch("pathlib.Path.read_bytes", return_value=webp_header),
        patch(
            "terminal_qrcode.simple_image.decode_webp_rgba",
            side_effect=WebPUnavailableError("missing"),
        ),
    ):
        with pytest.raises(ValueError, match="WEBP decode requires C backend"):
            SimpleImage.open(Path("x.webp"))


def test_open_webp_reports_decode_error(monkeypatch):
    """验证 WEBP 后端返回解码错误时上抛统一错误."""
    webp_header = b"RIFF\x10\x00\x00\x00WEBP"
    with (
        patch("pathlib.Path.read_bytes", return_value=webp_header),
        patch(
            "terminal_qrcode.simple_image.decode_webp_rgba",
            side_effect=simple_image.WebPDecodeError("broken"),
        ),
    ):
        with pytest.raises(ValueError, match="Failed to decode WEBP with C backend"):
            SimpleImage.open(Path("x.webp"))


def test_from_bytes_and_open_consistent_behavior(monkeypatch):
    """验证同一 JPEG 输入在 open 与 from_bytes 的行为一致."""
    jpeg_header = b"\xff\xd8\xff\xe0"
    monkeypatch.setattr(simple_image, "_CIMAGE_ACCEL", None)
    monkeypatch.setattr(
        simple_image,
        "decode_jpeg_rgb",
        lambda raw: (1, 1, bytes([3, 2, 1])),
    )
    with patch("pathlib.Path.read_bytes", return_value=jpeg_header):
        img_from_open = SimpleImage.open(Path("x.jpg"))
    img_from_bytes = SimpleImage.from_bytes(jpeg_header)
    assert img_from_open.getpixel((0, 0)) == img_from_bytes.getpixel((0, 0))


def test_to_png_bytes_raises_when_backend_unavailable(monkeypatch):
    """验证 PNG 编码后端缺失时直接报错，不再回退手写编码."""
    monkeypatch.setattr(
        simple_image,
        "encode_png_with_libpng",
        lambda data, mode, width, height: (_ for _ in ()).throw(PngUnavailableError("missing")),
    )
    img = SimpleImage.new("RGB", (1, 1), (1, 2, 3))
    with pytest.raises(ValueError, match="PNG encode requires C backend"):
        img.to_png_bytes()
