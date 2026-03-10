"""渲染相关测试 (canonical, core, selection & images)."""

import os
from collections.abc import Generator
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import pytest

from terminal_qrcode import draw, layout
from terminal_qrcode.contracts import (
    ColorLevelName,
    ImageSource,
    LayoutConfig,
    MatrixSource,
    ProbeConfig,
    QRConfig,
    RendererId,
    TerminalCapabilities,
    TerminalCapability,
    TerminalColorLevel,
)
from terminal_qrcode.core import (
    DEFAULT_RENDERER_REGISTRY,
    RenderConfig,
    RenderRequest,
    _resolve_qr_source,
)
from terminal_qrcode.renderers import (
    HalfBlockRenderer,
    ITerm2Renderer,
    KittyRenderer,
    SixelRenderer,
    WezTermRenderer,
    build_default_renderer_registry,
)
from terminal_qrcode.simple_image import SimpleImage


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


# --- Tests from test_canonical_render.py ---


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


# --- Tests from test_renderers_core.py ---


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


def test_halfblock_color_lines_are_self_contained():
    """验证彩色 halfblock 每一行都会独立重置并重新声明颜色状态."""
    matrix = [
        [True, False],
        [False, True],
        [True, False],
        [False, True],
    ]
    config = _render_config(fit=False, img_width=10, color_level="ansi16")
    output = "".join(HalfBlockRenderer().render(MatrixSource(matrix), config))
    assert "\x1b[0m\n\x1b[" in output
    assert output.endswith("\x1b[0m")


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
    assert output.startswith("\x1bP9;0q")
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


# --- Tests from test_renderer_selection.py ---


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


@patch.dict("os.environ", {"SSH_CONNECTION": "192.168.1.1 12345 192.168.1.2 22"}, clear=False)
@patch("terminal_qrcode.renderers.SixelRenderer.render")
@patch("terminal_qrcode.renderers.ITerm2Renderer.render")
@patch("terminal_qrcode.probe.TerminalProbe.capabilities")
def test_draw_auto_prefers_sixel_when_snapshot_contains_inline_and_sixel(
    mock_capabilities, mock_iterm_render, mock_sixel_render
):
    """验证 auto 渲染会基于完整能力快照在 SSH 下优先选择 Sixel."""
    mock_capabilities.return_value = TerminalCapabilities(
        capability=TerminalCapability.ITERM2,
        color_level=TerminalColorLevel.ANSI256,
        available_capabilities=(TerminalCapability.ITERM2, TerminalCapability.SIXEL),
    )
    mock_iterm_render.return_value = iter(())
    mock_sixel_render.return_value = iter(("sixel",))

    img = SimpleImage.open(_QRCODE_IMAGE_DIR / "qr_url_basic.png")
    output = "".join(draw(img))

    assert output == "sixel"
    assert mock_sixel_render.called
    assert not mock_iterm_render.called


@patch("terminal_qrcode.renderers.SixelRenderer.render")
@patch("terminal_qrcode.renderers.ITerm2Renderer.render")
def test_draw_forced_renderer_ignores_available_capability_order(mock_iterm_render, mock_sixel_render):
    """验证显式 renderer 仍优先于能力集合排序."""
    mock_iterm_render.return_value = iter(("iterm",))
    mock_sixel_render.return_value = iter(())

    img = SimpleImage.open(_QRCODE_IMAGE_DIR / "qr_url_basic.png")
    output = "".join(draw(img, renderer="iterm2"))

    assert output == "iterm"
    assert mock_iterm_render.called
    assert not mock_sixel_render.called


def test_renderer_priority_fallback():
    """验证降级逻辑."""
    registry = build_default_renderer_registry()
    caps = [TerminalCapability.FALLBACK]

    renderer = registry.select_renderer(caps)
    from terminal_qrcode.renderers import HalfBlockRenderer

    assert isinstance(renderer, HalfBlockRenderer)


# --- Tests from test_qrcode_images.py ---

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

    output = "".join(draw(image, renderer="halfblock", fit=False, img_width=80))
    assert any(c in output for c in ("▄", "▀", "█", " "))


def test_draw_accepts_qrcode_base_image_wrapper():
    """验证 draw 支持 qrcode BaseImage 包装对象."""
    qrcode_mod = pytest.importorskip("qrcode")

    qr = qrcode_mod.QRCode(border=4, box_size=4)
    qr.add_data("terminal-qrcode")
    qr.make(fit=True)
    wrapped_image = qr.make_image(fill_color="black", back_color="white")

    output = "".join(draw(wrapped_image, renderer="halfblock", fit=False, img_width=80))
    assert any(c in output for c in ("▄", "▀", "█", " "))
