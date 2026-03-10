"""Pillow, qrcode 与 CLI 集成测试."""

from io import BytesIO

import pytest

from terminal_qrcode import draw


def test_draw_accepts_pillow_image_object():
    """验证 draw 支持真实 Pillow 图像对象 input."""
    pil_image_mod = pytest.importorskip("PIL.Image")
    qrcode_mod = pytest.importorskip("qrcode")

    qr = qrcode_mod.QRCode(border=4, box_size=4)
    qr.add_data("https://example.com/pillow")
    qr.make(fit=True)
    wrapped = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    wrapped.save(buffer, format="PNG")
    buffer.seek(0)
    image = pil_image_mod.open(buffer)

    output = "".join(draw(image, renderer="halfblock", fit=False, img_width=80))
    assert output
    assert any(c in output for c in ("▄", "▀", "█", " "))


def test_draw_accepts_qrcode_wrapper_object():
    """验证 draw 支持真实 qrcode 包装对象输入."""
    pytest.importorskip("PIL.Image")
    qrcode_mod = pytest.importorskip("qrcode")

    qr = qrcode_mod.QRCode(border=4, box_size=4)
    qr.add_data("https://example.com/qrcode-wrapper")
    qr.make(fit=True)
    wrapped = qr.make_image(fill_color="black", back_color="white")

    output = "".join(draw(wrapped, renderer="halfblock", fit=False, img_width=80))
    assert output
    assert any(c in output for c in ("▄", "▀", "█", " "))
