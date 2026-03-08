"""规范化渲染专项测试."""

from pathlib import Path

from terminal_qrcode.contracts import QRConfig
from terminal_qrcode.core import RenderConfig, RenderRequest, TerminalCapability, _resolve_render_payload
from terminal_qrcode.simple_image import SimpleImage


def test_resolve_payload_canonical_default():
    """验证默认情况下图像输入被转换为矩阵（规范化渲染）."""
    qr_path = Path(__file__).parent / "qrcode" / "qr_url_basic.png"
    img = SimpleImage.open(str(qr_path))

    config = RenderConfig()
    request = RenderRequest(payload=img, config=config, source="test")

    # 模拟 Kitty 终端
    payload = _resolve_render_payload(request, TerminalCapability.KITTY)

    # 默认应返回矩阵 (list of lists)
    assert isinstance(payload, list)
    assert isinstance(payload[0], list)
    assert isinstance(payload[0][0], bool)
    # qr_url_basic.png 实际上是 version 4 (33x33)，加 4*2 border 后应为 41x41
    assert len(payload) == 41


def test_resolve_payload_preserve_source():
    """验证开启 preserve_source 时图形终端保留原始图像."""
    qr_path = Path(__file__).parent / "qrcode" / "qr_url_basic.png"
    img = SimpleImage.open(str(qr_path))

    # 显式开启 preserve_source
    config = RenderConfig(qr=QRConfig(preserve_source=True))
    request = RenderRequest(payload=img, config=config, source="test")

    # 模拟 Kitty 终端
    payload = _resolve_render_payload(request, TerminalCapability.KITTY)

    # 应返回原始 SimpleImage 对象
    assert isinstance(payload, SimpleImage)
    assert payload.width == img.width


def test_resolve_payload_preserve_source_fallback_still_canonical():
    """验证即开启 preserve_source，在降级终端下仍返回矩阵以确保显示."""
    qr_path = Path(__file__).parent / "qrcode" / "qr_url_basic.png"
    img = SimpleImage.open(str(qr_path))

    config = RenderConfig(qr=QRConfig(preserve_source=True))
    request = RenderRequest(payload=img, config=config, source="test")

    # 模拟 FALLBACK 终端（不支持图形协议）
    payload = _resolve_render_payload(request, TerminalCapability.FALLBACK)

    # 仍应返回矩阵，因为 SimpleImage 无法直接由 HalfBlockRenderer 渲染
    assert isinstance(payload, list)
