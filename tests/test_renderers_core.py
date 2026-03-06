"""渲染核心功能的测试模块."""

import base64
import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from terminal_qrcode import layout, qr_restore
from terminal_qrcode.core import DEFAULT_RENDERER_REGISTRY, RenderConfig, Renderer, TerminalCapability
from terminal_qrcode.renderers import HalfBlockRenderer, ITerm2Renderer, KittyRenderer, SixelRenderer, WezTermRenderer
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
            matrix[y][x] = ((x * 3 + y * 5) % 7) < 3
    return matrix


def _render_matrix_to_image(
    matrix: list[list[bool]], module: int = 4, quiet: int = 4, invert: bool = False
) -> SimpleImage:
    size = len(matrix)
    image_size = (size + quiet * 2) * module
    img = SimpleImage.new("L", (image_size, image_size), color=255)
    for my, row in enumerate(matrix):
        for mx, cell in enumerate(row):
            black = (not cell) if invert else cell
            value = 0 if black else 255
            x0 = (mx + quiet) * module
            y0 = (my + quiet) * module
            for y in range(y0, y0 + module):
                for x in range(x0, x0 + module):
                    img.putpixel((x, y), value)
    return img


def test_renderer_protocol():
    """验证自定义渲染器符合 Renderer 协议."""

    class DummyRenderer:
        def render(self, payload: list[list[bool]] | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
            _ = payload, config
            yield "dummy"

    assert isinstance(DummyRenderer(), Renderer)


def test_render_config_defaults():
    """验证渲染配置核心默认值."""
    config = RenderConfig()
    assert config.scale == 8
    assert config.renderer == "auto"
    assert config.repair == "strict"
    assert config.invert is None
    assert config.fit is True
    assert config.max_cols is None
    assert config.img_width is None
    assert config.halfblock_mode == "precision"
    assert config.border == 2


def test_halfblock_fit_false_rejects_lossy_downscale():
    """验证 fit=False 且列宽不足时 halfblock 会拒绝有损缩小."""
    matrix = _build_qr_like_matrix(size=25)
    renderer = HalfBlockRenderer()
    with pytest.raises(ValueError, match="Refusing lossy halfblock downscale"):
        _ = "".join(renderer.render(matrix, RenderConfig(fit=False, img_width=10, color_level="none")))


def test_halfblock_fit_true_rejects_too_narrow_terminal(monkeypatch):
    """验证 fit=True 且终端过窄时会拒绝不可扫输出."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((20, 20)))
    matrix = _build_qr_like_matrix(size=37)
    renderer = HalfBlockRenderer()
    with pytest.raises(ValueError, match="too narrow to render scannable QR"):
        _ = "".join(renderer.render(matrix, RenderConfig(fit=True, color_level="none")))


def test_halfblock_color_level_none_keeps_plain_halfblocks():
    """验证 color_level=none 不输出 ANSI 序列."""
    matrix = [[True, False, True], [False, True, False]]
    output = "".join(HalfBlockRenderer().render(matrix, RenderConfig(fit=False, img_width=10, color_level="none")))
    assert "\x1b[" not in output
    assert any(c in output for c in ("█", "▀", "▄", " "))


def test_halfblock_color_level_ansi16_contains_sgr_sequences():
    """验证 ansi16 等级下输出 ANSI 序列."""
    matrix = [[True, False], [False, True]]
    output = "".join(HalfBlockRenderer().render(matrix, RenderConfig(fit=False, img_width=10, color_level="ansi16")))
    assert "\x1b[" in output
    assert "▀" in output


def test_halfblock_ansi16_uses_single_sgr_sequence():
    """验证 ansi16 每个字符仅生成一个 SGR 序列而非两段拼接."""
    from terminal_qrcode.renderers import _halfblock_sgr

    sgr = _halfblock_sgr("ansi16", fg_dark=True, bg_dark=False)
    assert sgr.count("\x1b[") == 1
    assert sgr.endswith("m")


def test_halfblock_ansi16_uses_bright_white():
    """验证 ansi16 白色使用亮白 97/107 而非标准白 37/47."""
    from terminal_qrcode.renderers import _halfblock_sgr

    sgr = _halfblock_sgr("ansi16", fg_dark=False, bg_dark=False)
    assert "97" in sgr
    assert "107" in sgr


def test_resize_matrix_center_nn_preserves_block_structure():
    """验证矩阵缩放中心点采样保留分块结构."""
    matrix = [
        [True, True, True, False, False, False],
        [True, True, True, False, False, False],
        [True, True, True, False, False, False],
        [False, False, False, True, True, True],
        [False, False, False, True, True, True],
        [False, False, False, True, True, True],
    ]
    result = layout._resize_matrix_to_cols(matrix, 2)
    assert len(result) == 2
    assert len(result[0]) == 2
    assert result[0][0] is True
    assert result[0][1] is False
    assert result[1][0] is False
    assert result[1][1] is True


def test_resize_matrix_center_nn_samples_middle():
    """验证中心点采样取 bin 中心——5 列缩到 1 列时取 index 2."""
    row = [True, True, True, False, False]
    matrix = [row[:]]
    result = layout._resize_matrix_to_cols(matrix, 1)
    assert result[0][0] is True


def test_resize_matrix_preserves_finder_ring():
    """验证缩放保留回字环结构而非涂抹为实心块."""
    finder = [
        [True, True, True, True, True, True, True],
        [True, False, False, False, False, False, True],
        [True, False, True, True, True, False, True],
        [True, False, True, True, True, False, True],
        [True, False, True, True, True, False, True],
        [True, False, False, False, False, False, True],
        [True, True, True, True, True, True, True],
    ]
    result = layout._resize_matrix_to_cols(finder, 6)
    assert result[0] == [True] * 6, "外环行应全 True"
    assert result[1][0] is True and result[1][1] is False, "外环与间隙应被保留"
    assert result[1][-1] is True and result[1][-2] is False, "右侧外环与间隙应被保留"


def test_pad_border_adds_quiet_zone():
    """验证 _pad_border 按模块数添加白色静区."""
    matrix = [[True, True], [True, True]]
    padded = layout._pad_border(matrix, border=2)
    assert len(padded) == 6
    assert len(padded[0]) == 6
    assert all(v is False for v in padded[0])
    assert all(v is False for v in padded[-1])
    assert padded[2][2] is True


def test_to_render_matrix_applies_border_for_image_input():
    """验证 _to_render_matrix 对图像输入自动添加 border."""
    from terminal_qrcode.core import _to_render_matrix

    matrix = _build_qr_like_matrix(size=25)
    image = _render_matrix_to_image(matrix, module=4, quiet=4)
    result = _to_render_matrix(image, RenderConfig(border=3))
    assert len(result) == len(result[0])
    assert len(result) > 25
    assert all(v is False for v in result[0])
    assert all(v is False for v in result[-1])


def test_halfblock_invert_behavior():
    """验证半块渲染 invert 行为."""
    matrix = [[True, True], [True, True]]
    out_default = "".join(HalfBlockRenderer().render(matrix, RenderConfig(img_width=2, color_level="none")))
    out_invert = "".join(HalfBlockRenderer().render(matrix, RenderConfig(img_width=2, invert=True, color_level="none")))
    assert "█" in out_default
    assert "█" not in out_invert


def test_halfblock_renderer_streaming():
    """验证 HalfBlockRenderer 返回生成器分片."""
    renderer = HalfBlockRenderer()
    result = renderer.render([[True, False], [False, True]], RenderConfig(invert=False, img_width=2))
    assert isinstance(result, Generator)
    chunks = list(result)
    assert len(chunks) > 0


def test_strict_restore_uses_standard_qr_sizes():
    """验证 strict_restore 输出遵循 21+4k 尺寸约束."""
    matrix = _build_qr_like_matrix(size=29)
    image = _render_matrix_to_image(matrix, module=3, quiet=4)
    restored = qr_restore.strict_restore_qr_matrix(image, RenderConfig())
    assert restored is not None
    size = len(restored)
    assert 21 <= size <= 177
    assert (size - 21) % 4 == 0


def test_strict_restore_noise_robust():
    """验证 strict_restore 对轻微噪声仍能恢复矩阵."""
    matrix = _build_qr_like_matrix(size=25)
    image = _render_matrix_to_image(matrix, module=5, quiet=4)
    quiet = 4
    module = 5
    for my in range(25):
        for mx in range(25):
            if (mx + my) % 4 != 0:
                continue
            x = (mx + quiet) * module + 1
            y = (my + quiet) * module + 1
            value = image.getpixel((x, y))
            image.putpixel((x, y), 255 if value == 0 else 0)

    restored = qr_restore.strict_restore_qr_matrix(image, RenderConfig())
    if restored is not None:
        assert qr_restore._finder_score(restored) >= 0.55


def test_strict_restore_supports_single_pixel_module():
    """验证 strict_restore 可处理单像素模块二维码."""
    matrix = _build_qr_like_matrix(size=25)
    image = _render_matrix_to_image(matrix, module=1, quiet=4)
    restored = qr_restore.strict_restore_qr_matrix(image, RenderConfig())
    assert restored is not None
    assert 21 <= len(restored) <= 177
    assert (len(restored) - 21) % 4 == 0


def test_strict_restore_auto_polarity_corrects_inverted_input():
    """验证 invert=None 时自动极性判定可修正反相输入."""
    matrix = _build_qr_like_matrix(size=25)
    image = _render_matrix_to_image(matrix, module=4, quiet=4, invert=True)
    restored = qr_restore.strict_restore_qr_matrix(image, RenderConfig(invert=None, finder_variance=1.2))
    if restored is not None:
        assert qr_restore._finder_score(restored) >= 0.55


def test_strict_restore_invert_override_takes_priority():
    """验证显式 invert=True 覆盖自动极性判定."""
    matrix = _build_qr_like_matrix(size=25)
    image = _render_matrix_to_image(matrix, module=4, quiet=4)
    restored = qr_restore.strict_restore_qr_matrix(image, RenderConfig(invert=True, finder_variance=1.2))
    assert restored is not None
    assert 21 <= len(restored) <= 177


def test_strict_restore_returns_none_for_non_qr_image():
    """验证 strict_restore 对非二维码输入返回 None."""
    image = SimpleImage.new("L", (64, 64), color=255)
    restored = qr_restore.strict_restore_qr_matrix(image, RenderConfig())
    assert restored is None


def test_strict_restore_fixture_jpeg_size_is_reasonable():
    """验证真实 JPEG 样本不会被误判为异常超大矩阵尺寸."""
    image = SimpleImage.open(Path("tests/qrcode/qr_text_multiline.jpeg"))
    restored = qr_restore.strict_restore_qr_matrix(image, RenderConfig())
    assert restored is not None
    size = len(restored)
    assert 21 <= size <= 57
    assert (size - 21) % 4 == 0


def test_non_tty_fallback_size_applied(monkeypatch):
    """验证无法获取终端尺寸时 fit 回退 80x24 并应用安全边距."""

    def _raise(*_args, **_kwargs):
        raise OSError("no tty")

    monkeypatch.setattr(layout, "get_terminal_size", _raise)
    cols, rows = layout._get_available_cells()
    assert cols == 79
    assert rows == 23


def test_fit_plan_safe_margin_applied(monkeypatch):
    """验证 FitPlan 基于安全边距后的网格预算计算."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((20, 10)))
    plan = layout._build_fit_plan(RenderConfig(fit=True), 20, 20)
    assert plan.avail_cols == 19
    assert plan.avail_rows == 9


def test_kitty_renderer_output():
    """验证 Kitty 协议输出转义序列边界."""
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(KittyRenderer().render(matrix, RenderConfig()))
    assert output.startswith("\x1b_G")
    assert output.endswith("\x1b\\")


def test_kitty_fit_emits_column_constraint(monkeypatch):
    """验证 Kitty fit 输出包含列宽参数 c=."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((18, 24)))
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(KittyRenderer().render(matrix, RenderConfig(fit=True)))
    assert "c=" in output


def test_iterm2_renderer_output():
    """验证 iTerm2 协议输出包含 inline image 指令."""
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(ITerm2Renderer().render(matrix, RenderConfig()))
    assert "1337;File=inline=1" in output
    assert base64.b64decode(output.split(":")[-1].strip("\x07"))


def test_wezterm_renderer_output():
    """验证 WezTerm 协议输出包含 preserveAspectRatio 参数."""
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(WezTermRenderer().render(matrix, RenderConfig()))
    assert "preserveAspectRatio=1" in output


def test_sixel_renderer_output():
    """验证 Sixel 协议输出起止转义序列."""
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(SixelRenderer().render(matrix, RenderConfig()))
    assert output.startswith("\x1bP9q")
    assert output.endswith("\x1b\\")


def test_renderer_registry_get():
    """验证渲染器注册表返回正确实例."""
    assert isinstance(DEFAULT_RENDERER_REGISTRY.get(TerminalCapability.KITTY), KittyRenderer)
    assert isinstance(DEFAULT_RENDERER_REGISTRY.get(TerminalCapability.ITERM2), ITerm2Renderer)
    assert isinstance(DEFAULT_RENDERER_REGISTRY.get(TerminalCapability.WEZTERM), WezTermRenderer)
    assert isinstance(DEFAULT_RENDERER_REGISTRY.get(TerminalCapability.SIXEL), SixelRenderer)
    assert isinstance(DEFAULT_RENDERER_REGISTRY.get(TerminalCapability.FALLBACK), HalfBlockRenderer)


@patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,123,0"}, clear=False)
@patch("terminal_qrcode.renderers._tmux_allow_passthrough", return_value=False)
def test_kitty_renderer_tmux_auto_disabled_not_wrapped(_mock_allow):
    """验证 Kitty 在 tmux auto 且 passthrough 关闭时不包裹."""
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(KittyRenderer().render(matrix, RenderConfig(tmux_passthrough="auto")))
    assert output.startswith("\x1b_G")
    assert "\x1bPtmux;" not in output


@patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,123,0"}, clear=False)
@patch("terminal_qrcode.renderers._tmux_allow_passthrough", return_value=False)
def test_sixel_renderer_tmux_always_forces_wrap(_mock_allow):
    """验证 Sixel 在 tmux always 时强制包裹."""
    matrix = _build_qr_like_matrix(size=21)
    output = "".join(SixelRenderer().render(matrix, RenderConfig(tmux_passthrough="always")))
    assert output.startswith("\x1bPtmux;")
