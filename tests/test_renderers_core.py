"""渲染核心功能的测试模块."""

import os
from collections.abc import Generator
from typing import Literal
from unittest.mock import patch

import pytest

from terminal_qrcode import layout
from terminal_qrcode.contracts import (
    ColorLevelName,
    LayoutConfig,
    MatrixSource,
    ProbeConfig,
    QRConfig,
    RendererId,
)
from terminal_qrcode.core import DEFAULT_RENDERER_REGISTRY, RenderConfig
from terminal_qrcode.renderers import HalfBlockRenderer, ITerm2Renderer, KittyRenderer, SixelRenderer, WezTermRenderer


@pytest.fixture(autouse=True)
def _mock_terminal_size(monkeypatch):
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((80, 24)))


def _build_qr_like_matrix(size: int = 25) -> list[list[bool]]:
    matrix = [[False for _ in range(size)] for _ in range(size)]

    def add_finder(ox: int, oy: int) -> None:
        for y in range(7):
            for x in range(7):
                if x in (0, 6) or y in (0, 6):
                    matrix[oy + y][ox + x] = True
                elif x in (1, 5) or y in (1, 5):
                    matrix[oy + y][ox + x] = False
                else:
                    matrix[oy + y][ox + x] = True

    add_finder(0, 0)
    add_finder(size - 7, 0)
    add_finder(0, size - 7)

    for y in range(size):
        for x in range(size):
            if matrix[y][x]:
                continue
            if (x * y) % 3 == 0:
                matrix[y][x] = True
    return matrix


def _render_config(
    *,
    invert: bool | None = None,
    fit: bool = False,
    img_width: int | None = None,
    color_level: ColorLevelName = "auto",
    tmux_passthrough: Literal["auto", "always", "never"] = "auto",
) -> RenderConfig:
    return RenderConfig(
        qr=QRConfig(invert=invert),
        layout=LayoutConfig(fit=fit, img_width=img_width),
        probe=ProbeConfig(color_level=color_level, tmux_passthrough=tmux_passthrough),
    )


def test_halfblock_fit_false_rejects_lossy_downscale():
    """验证 fit=False 且列宽不足时 halfblock 会拒绝有损缩小."""
    matrix = _build_qr_like_matrix(size=25)
    renderer = HalfBlockRenderer()
    with pytest.raises(ValueError, match="Refusing lossy halfblock downscale"):
        _ = "".join(renderer.render(MatrixSource(matrix), _render_config(fit=False, img_width=10, color_level="none")))


def test_halfblock_fit_true_rejects_too_narrow_terminal(monkeypatch):
    """验证 fit=True 且终端过窄时会拒绝不可扫输出."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((20, 20)))
    matrix = _build_qr_like_matrix(size=37)
    renderer = HalfBlockRenderer()
    with pytest.raises(ValueError, match="too narrow to render scannable QR"):
        _ = "".join(renderer.render(MatrixSource(matrix), _render_config(fit=True, color_level="none")))


def test_halfblock_color_level_none_keeps_plain_halfblocks():
    """验证 color_level=none 不输出 ANSI 序列."""
    matrix = [[True, False, True], [False, True, False]]
    config = _render_config(fit=False, img_width=10, color_level="none")
    output = "".join(HalfBlockRenderer().render(MatrixSource(matrix), config))
    assert "\x1b[" not in output
    assert "▀" in output


def test_halfblock_color_level_ansi16_contains_sgr_sequences():
    """验证 ansi16 等级下输出 ANSI 序列."""
    matrix = [[True, False], [False, True]]
    config = _render_config(fit=False, img_width=10, color_level="ansi16")
    output = "".join(HalfBlockRenderer().render(MatrixSource(matrix), config))
    assert "\x1b[" in output
    assert "▀" in output


def test_halfblock_invert_behavior():
    """验证半块渲染 invert 行为."""
    matrix = [[True, True], [True, True]]
    out_default = "".join(
        HalfBlockRenderer().render(MatrixSource(matrix), _render_config(img_width=2, color_level="none"))
    )
    out_inverted = "".join(
        HalfBlockRenderer().render(MatrixSource(matrix), _render_config(invert=True, img_width=2, color_level="none"))
    )
    assert out_default == "██"
    assert out_inverted == "  "


def test_halfblock_renderer_streaming():
    """验证 HalfBlockRenderer 返回生成器分片."""
    renderer = HalfBlockRenderer()
    result = renderer.render(MatrixSource([[True, False], [False, True]]), _render_config(invert=False, img_width=2))
    assert isinstance(result, Generator)
    chunks = list(result)
    assert len(chunks) > 0


def test_kitty_renderer_output():
    """验证 Kitty 协议输出转义序列边界."""
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(KittyRenderer().render(MatrixSource(matrix), RenderConfig()))
    assert output.startswith("\x1b_G")
    assert output.endswith("\x1b\\")
    assert "f=100" in output


def test_kitty_fit_emits_column_constraint(monkeypatch):
    """验证 Kitty fit 输出包含列宽参数 c=."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((18, 24)))
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(KittyRenderer().render(MatrixSource(matrix), _render_config(fit=True)))
    assert "c=" in output


def test_iterm2_renderer_output():
    """验证 iTerm2 协议输出包含 inline image 指令."""
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(ITerm2Renderer().render(MatrixSource(matrix), RenderConfig()))
    assert "\x1b]1337;File=inline=1" in output
    assert output.endswith("\x07")


def test_wezterm_renderer_output():
    """验证 WezTerm 协议输出包含 preserveAspectRatio 参数."""
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(WezTermRenderer().render(MatrixSource(matrix), RenderConfig()))
    assert "preserveAspectRatio=1" in output


def test_sixel_renderer_output():
    """验证 Sixel 协议输出起止转义序列."""
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(SixelRenderer().render(MatrixSource(matrix), RenderConfig()))
    assert output.startswith("\x1bP9q")
    assert output.endswith("\x1b\\")


def test_renderer_registry_get():
    """验证渲染器注册表返回正确实例."""
    assert isinstance(DEFAULT_RENDERER_REGISTRY.get(RendererId.KITTY), KittyRenderer)
    assert isinstance(DEFAULT_RENDERER_REGISTRY.get(RendererId.HALFBLOCK), HalfBlockRenderer)


@patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,123,0"}, clear=False)
@patch("terminal_qrcode.renderers._tmux_allow_passthrough", return_value=False)
def test_kitty_renderer_tmux_auto_disabled_not_wrapped(_mock_allow):
    """验证 Kitty 在 tmux auto 且 passthrough 关闭时不包裹."""
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(KittyRenderer().render(MatrixSource(matrix), _render_config(tmux_passthrough="auto")))
    assert "\x1bPtmux;" not in output


@patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,123,0"}, clear=False)
@patch("terminal_qrcode.renderers._tmux_allow_passthrough", return_value=False)
def test_sixel_renderer_tmux_always_forces_wrap(_mock_allow):
    """验证 Sixel 在 tmux always 时强制包裹."""
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(SixelRenderer().render(MatrixSource(matrix), _render_config(tmux_passthrough="always")))
    assert output.startswith("\x1bPtmux;")
