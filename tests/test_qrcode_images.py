"""二维码图像样本验证."""

from pathlib import Path

import pytest

from terminal_qrcode import draw
from terminal_qrcode.simple_image import SimpleImage

_QRCODE_IMAGE_DIR = Path(__file__).parent / "qrcode"
_SAMPLE_IDS = ("qr_url_basic", "qr_text_unicode", "qr_wifi_wpa", "qr_text_multiline")


def _expected_files(sample_id: str) -> list[Path]:
    return [
        _QRCODE_IMAGE_DIR / f"{sample_id}.png",
        _QRCODE_IMAGE_DIR / f"{sample_id}.webp",
        _QRCODE_IMAGE_DIR / f"{sample_id}.jpeg",
    ]


@pytest.mark.parametrize("sample_id", _SAMPLE_IDS)
def test_qrcode_image_files_exist(sample_id):
    """验证固定二维码样本对应的三种格式文件都存在."""
    for image_path in _expected_files(sample_id):
        assert image_path.is_file(), f"missing fixture: {image_path}"


@pytest.mark.parametrize("sample_id", _SAMPLE_IDS)
def test_qrcode_images_are_decodable(sample_id):
    """验证固定二维码样本可被 SimpleImage.open 成功解码."""
    for image_path in _expected_files(sample_id):
        image = SimpleImage.open(image_path)
        assert image.width > 0
        assert image.height > 0
        assert image.mode in {"L", "RGB", "RGBA"}


def test_draw_accepts_qrcode_pillow_image():
    """验证 draw 支持 qrcode 结合 Pillow 生成的图像对象."""
    qrcode_mod = pytest.importorskip("qrcode")

    qr = qrcode_mod.QRCode(border=4, box_size=4)
    qr.add_data("https://example.com")
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").get_image()

    output = str(draw(image, renderer="halfblock", fit=False, img_width=80))
    assert any(c in output for c in ("▄", "▀", "█", " "))


def test_draw_accepts_qrcode_base_image_wrapper():
    """验证 draw 支持 qrcode BaseImage 包装对象."""
    qrcode_mod = pytest.importorskip("qrcode")

    qr = qrcode_mod.QRCode(border=4, box_size=4)
    qr.add_data("terminal-qrcode")
    qr.make(fit=True)
    wrapped_image = qr.make_image(fill_color="black", back_color="white")

    output = str(draw(wrapped_image, renderer="halfblock", fit=False, img_width=80))
    assert any(c in output for c in ("▄", "▀", "█", " "))
