"""规范化渲染专项测试."""

from pathlib import Path

from terminal_qrcode.contracts import ImageSource, MatrixSource, QRConfig
from terminal_qrcode.core import RenderConfig, RenderRequest, TerminalCapability, _resolve_qr_source
from terminal_qrcode.simple_image import SimpleImage


def test_resolve_payload_canonical_default():
    """验证默认情况下图像输入被转换为矩阵（规范化渲染）."""
    qr_path = Path(__file__).parent / "qrcode" / "qr_url_basic.png"
    img = SimpleImage.open(str(qr_path))

    config = RenderConfig()
    request = RenderRequest(payload=img, config=config, source="test")

    # 模拟 Kitty 终端
    source = _resolve_qr_source(request, TerminalCapability.KITTY)

    # 默认应返回 MatrixSource
    assert isinstance(source, MatrixSource)
    matrix = source.matrix
    assert isinstance(matrix, list)
    assert isinstance(matrix[0], list)
    assert isinstance(matrix[0][0], bool)
    # qr_url_basic.png 实际上是 version 4 (33x33)，加 4*2 border 后应为 41x41
    assert len(matrix) == 41


def test_resolve_payload_preserve_source():
    """验证开启 preserve_source 时图形终端保留原始图像."""
    qr_path = Path(__file__).parent / "qrcode" / "qr_url_basic.png"
    img = SimpleImage.open(str(qr_path))

    # 显式开启 preserve_source
    config = RenderConfig(qr=QRConfig(preserve_source=True))
    request = RenderRequest(payload=img, config=config, source="test")

    # 模拟 Kitty 终端
    source = _resolve_qr_source(request, TerminalCapability.KITTY)

    # 应返回 ImageSource 对象
    assert isinstance(source, ImageSource)
    assert source.image.width == img.width
    assert source.is_original is True


def test_resolve_payload_preserve_source_fallback_still_canonical():
    """验证即开启 preserve_source，在降级终端下仍返回矩阵以确保显示."""
    qr_path = Path(__file__).parent / "qrcode" / "qr_url_basic.png"
    img = SimpleImage.open(str(qr_path))

    config = RenderConfig(qr=QRConfig(preserve_source=True))
    request = RenderRequest(payload=img, config=config, source="test")

    # 模拟 FALLBACK 终端（不支持图形协议）
    source = _resolve_qr_source(request, TerminalCapability.FALLBACK)

    # 仍应返回 MatrixSource，因为 SimpleImage 无法直接由 HalfBlockRenderer 渲染
    assert isinstance(source, MatrixSource)
