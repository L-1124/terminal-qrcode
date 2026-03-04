"""SimpleImage 模块的测试集."""

from pathlib import Path
from unittest.mock import patch

import pytest

import terminal_qrcode.simple_image as simple_image
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


def test_from_bytes_and_open_consistent_behavior(monkeypatch):
    """验证同一 JPEG 输入在 open 与 from_bytes 的行为一致."""
    jpeg_header = b"\xff\xd8\xff\xe0"
    monkeypatch.setattr(
        simple_image,
        "decode_jpeg_rgb",
        lambda raw: (1, 1, bytes([3, 2, 1])),
    )
    with patch("pathlib.Path.read_bytes", return_value=jpeg_header):
        img_from_open = SimpleImage.open(Path("x.jpg"))
    img_from_bytes = SimpleImage.from_bytes(jpeg_header)
    assert img_from_open.getpixel((0, 0)) == img_from_bytes.getpixel((0, 0))
