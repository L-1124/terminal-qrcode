"""后端选择优先级专项测试."""

import os
from unittest.mock import patch

from terminal_qrcode.contracts import TerminalCapability
from terminal_qrcode.renderers import KittyRenderer, SixelRenderer, build_default_renderer_registry


def test_renderer_priority_standard():
    """验证标准环境下 Kitty 优先."""
    registry = build_default_renderer_registry()
    caps = [TerminalCapability.KITTY, TerminalCapability.SIXEL, TerminalCapability.FALLBACK]

    with patch.dict(os.environ, {}, clear=True):
        renderer = registry.select_renderer(caps)
        assert isinstance(renderer, KittyRenderer)


def test_renderer_priority_ssh():
    """验证 SSH 环境下 Sixel 优先 (因为带宽效率更高)."""
    registry = build_default_renderer_registry()
    caps = [TerminalCapability.KITTY, TerminalCapability.SIXEL, TerminalCapability.FALLBACK]

    # 模拟 SSH 连接
    with patch.dict(os.environ, {"SSH_CONNECTION": "192.168.1.1 12345 192.168.1.2 22"}):
        renderer = registry.select_renderer(caps)
        assert isinstance(renderer, SixelRenderer)


def test_renderer_priority_fallback():
    """验证降级逻辑."""
    registry = build_default_renderer_registry()
    caps = [TerminalCapability.FALLBACK]

    renderer = registry.select_renderer(caps)
    from terminal_qrcode.renderers import HalfBlockRenderer

    assert isinstance(renderer, HalfBlockRenderer)
