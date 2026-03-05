"""渲染核心功能的测试模块."""

import base64
import os
from collections.abc import Generator
from unittest.mock import patch

import pytest

from terminal_qrcode import layout, qr_restore, renderers
from terminal_qrcode.core import (
    DEFAULT_RENDERER_REGISTRY,
    RenderConfig,
    Renderer,
    TerminalCapability,
)
from terminal_qrcode.renderers import (
    HalfBlockRenderer,
    ITerm2Renderer,
    KittyRenderer,
    SixelRenderer,
    WezTermRenderer,
)
from terminal_qrcode.simple_image import SimpleImage


@pytest.fixture(autouse=True)
def _mock_terminal_size(monkeypatch):
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((80, 24)))


def test_renderer_protocol():
    """验证自定义渲染器是否符合 Renderer 协议."""

    class DummyRenderer:
        def render(self, payload: list[list[bool]] | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
            yield "dummy"

    assert isinstance(DummyRenderer(), Renderer)


def test_render_config_defaults():
    """验证渲染配置核心与鲁棒性默认值."""
    config = RenderConfig()
    assert config.scale == 8
    assert config.force_renderer is None
    assert config.invert is None
    assert config.ascii_only is False
    assert config.fit is True
    assert config.max_cols is None
    assert config.img_width is None


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


def test_halfblock_strict_restore_respects_fit_cols():
    """验证严格还原后的网格输出会受 fit 列宽限制."""
    matrix = _build_qr_like_matrix(size=25)
    image = _render_matrix_to_image(matrix, module=4, quiet=4)
    renderer = HalfBlockRenderer()
    output = "".join(renderer.render(image, RenderConfig(img_width=9, fit=True)))
    first_line = output.splitlines()[0]
    assert len(first_line) <= 9


def test_halfblock_fit_true_uses_terminal_columns(monkeypatch):
    """验证 fit=True 时 halfblock 会按终端列宽收束."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((12, 24)))
    img = SimpleImage.new("L", (64, 16), color=0)
    renderer = HalfBlockRenderer()
    output = "".join(renderer.render(img, RenderConfig(img_width=120, fit=True)))
    first_line = output.splitlines()[0]
    assert len(first_line) <= 12


def test_halfblock_fit_respects_max_cols_and_img_width_cap(monkeypatch):
    """验证 fit 模式会同时受终端列宽、max_cols 和 img_width 上限约束."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((100, 24)))
    img = SimpleImage.new("L", (120, 20), color=0)
    renderer = HalfBlockRenderer()
    output = "".join(renderer.render(img, RenderConfig(fit=True, img_width=60, max_cols=30)))
    first_line = output.splitlines()[0]
    assert len(first_line) <= 30


def test_halfblock_fit_false_uses_img_width_as_target():
    """验证 fit=False 时按 img_width 作为目标宽度收束."""
    img = SimpleImage.new("L", (80, 20), color=0)
    renderer = HalfBlockRenderer()
    output = "".join(renderer.render(img, RenderConfig(fit=False, img_width=10)))
    first_line = output.splitlines()[0]
    assert len(first_line) <= 10


def test_halfblock_strict_restore_uses_21_plus_4k_constraint():
    """验证严格还原网格尺寸遵循 21+4k 且位于标准范围."""
    matrix = _build_qr_like_matrix(size=29)
    image = _render_matrix_to_image(matrix, module=3, quiet=4)
    restored = qr_restore.strict_restore_qr_matrix(image, RenderConfig())
    assert restored is not None
    size = len(restored)
    assert 21 <= size <= 177
    assert (size - 21) % 4 == 0


def test_halfblock_strict_restore_3x3_majority_is_noise_robust():
    """验证 3x3 多数采样能抵抗轻微噪声."""
    matrix = _build_qr_like_matrix(size=25)
    image = _render_matrix_to_image(matrix, module=5, quiet=4)
    # 每个模块翻转一个像素，模拟 JPEG/轻微模糊噪声。
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
    assert restored is not None
    assert restored == matrix


def test_halfblock_auto_polarity_corrects_inverted_input():
    """验证 invert=None 时自动极性判定可修正黑白反转输入."""
    matrix = _build_qr_like_matrix(size=25)
    image = _render_matrix_to_image(matrix, module=4, quiet=4, invert=True)
    restored = qr_restore.strict_restore_qr_matrix(image, RenderConfig(invert=None))
    assert restored is not None
    assert restored == matrix


def test_halfblock_invert_override_takes_priority():
    """验证显式 invert=True 会覆盖自动极性判定."""
    matrix = _build_qr_like_matrix(size=25)
    image = _render_matrix_to_image(matrix, module=4, quiet=4)
    restored = qr_restore.strict_restore_qr_matrix(image, RenderConfig(invert=True))
    assert restored is not None
    expected = [[not cell for cell in row] for row in matrix]
    assert restored == expected


def test_halfblock_strict_restore_fallback_on_non_qr(monkeypatch):
    """验证严格还原失败时会回退旧流程."""
    monkeypatch.setattr(renderers, "strict_restore_qr_matrix", lambda *_: None)
    img = SimpleImage.new("L", (100, 100), color=255)
    for y in range(45, 55):
        for x in range(45, 55):
            img.putpixel((x, y), 0)

    renderer = HalfBlockRenderer()
    output = "".join(renderer.render(img, RenderConfig(img_width=8)))
    first_line = output.splitlines()[0]
    assert len(first_line) <= 8


def test_render_config_img_width():
    """验证图片收束宽度的默认值."""
    config = RenderConfig()
    assert config.img_width is None


def test_non_tty_fallback_size_applied(monkeypatch):
    """验证无法获取终端尺寸时 fit 会回退到 80x24 并应用安全边距."""

    def _raise(*_args, **_kwargs):
        raise OSError("no tty")

    monkeypatch.setattr(layout, "get_terminal_size", _raise)
    cols, rows = layout._get_available_cells()
    assert cols == 79
    assert rows == 23


def test_fit_uses_safe_margin_prevents_wrap(monkeypatch):
    """验证 fit 计算会保留一列安全边距以避免换行."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((20, 20)))
    cols, rows = layout._get_available_cells()
    assert cols == 19
    assert rows == 19


def test_fit_plan_safe_margin_applied(monkeypatch):
    """验证 FitPlan 会基于安全边距后的可用网格计算预算."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((20, 10)))
    plan = layout._build_fit_plan(RenderConfig(fit=True), 20, 20)
    assert plan.avail_cols == 19
    assert plan.avail_rows == 9
    assert plan.budget_cols == 5
    assert plan.budget_rows == 5


def test_halfblock_renderer_output():
    """验证半块字符渲染器在终端输出中包含预期的 Unicode 块."""
    config = RenderConfig(img_width=2)
    image = SimpleImage.new("L", (2, 2), 0)
    renderer = HalfBlockRenderer()
    output = "".join(renderer.render(image, config))
    # 半块矩阵渲染通常包含这些 U+2580 系列字符
    assert any(c in output for c in ("▄", "▀", "█", " "))


def test_halfblock_image_binarization():
    """验证半块字符渲染器对图片的灰度二值化逻辑."""
    # 创建一个简单的 2x2 黑白图片
    img = SimpleImage.new("L", (2, 2))
    img.putpixel((0, 0), 0)  # 黑 (True)
    img.putpixel((1, 0), 255)  # 白 (False)
    img.putpixel((0, 1), 255)  # 白 (False)
    img.putpixel((1, 1), 0)  # 黑 (True)

    renderer = HalfBlockRenderer()
    output = "".join(renderer.render(img, RenderConfig()))
    # 预期输出对应的半块字符
    assert any(c in output for c in ("▄", "▀", "█", " "))


def test_halfblock_image_autocrop_and_resize():
    """验证图片的自动裁切与网格收束缩放模块."""
    # 构建一张 100x100 的白底图, 中间只有 10x10 的黑色方块
    img = SimpleImage.new("L", (100, 100), color=255)
    for y in range(45, 55):
        for x in range(45, 55):
            img.putpixel((x, y), 0)

    renderer = HalfBlockRenderer()
    # 期望裁切掉白边后, 收束到宽度 10
    config = RenderConfig(img_width=10)

    output = "".join(renderer.render(img, config))
    lines = output.strip().split("\n")

    # 验证输出宽度符合收束预期, 且去掉了 100 像素量级的冗余空白
    assert len(lines[0]) <= 10


def test_halfblock_invert_and_ascii():
    """验证反色与纯 ASCII 渲染模式的核心逻辑."""
    image = SimpleImage.new("L", (2, 2), 0)
    renderer = HalfBlockRenderer()

    # 1. 默认模式: 应该是半块字符中的全黑符号
    out_default = "".join(renderer.render(image, RenderConfig(img_width=2)))
    assert "█" in out_default

    # 2. 反色模式: 全黑应变成全亮(即背景色，一般为空格)
    out_invert = "".join(renderer.render(image, RenderConfig(img_width=2, invert=True)))
    assert "█" not in out_invert
    assert " " in out_invert

    # 3. ASCII 降级模式: 无垂直压缩, 且不应含半块字符
    out_ascii = "".join(renderer.render(image, RenderConfig(img_width=2, ascii_only=True)))
    assert "▀" not in out_ascii
    assert "▄" not in out_ascii


def test_kitty_renderer_output():
    """验证 Kitty 协议渲染器生成的字符串是否以正确的转义序列开始和结束."""
    config = RenderConfig()
    image = SimpleImage.new("RGB", (2, 2), (0, 0, 0))
    renderer = KittyRenderer()
    output = "".join(renderer.render(image, config))
    # Kitty 协议特征: 以 \x1b_G 开头, 以 \x1b\\ 结尾
    assert output.startswith("\x1b_G")
    assert output.endswith("\x1b\\")


def test_kitty_fit_emits_column_constraint(monkeypatch):
    """验证 Kitty 在 fit 模式下会带 c= 列宽参数."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((18, 24)))
    image = SimpleImage.new("RGB", (100, 20), (0, 0, 0))
    renderer = KittyRenderer()
    output = "".join(renderer.render(image, RenderConfig(fit=True)))
    assert "c=5" in output


def test_kitty_fit_upscales_small_image_to_terminal_cols(monkeypatch):
    """验证 Kitty 在 fit 模式下会放大小图到目标列宽."""
    import re

    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((60, 24)))
    image = SimpleImage.new("RGB", (10, 10), (0, 0, 0))
    renderer = KittyRenderer()
    output = "".join(renderer.render(image, RenderConfig(fit=True)))

    match = re.search(r"s=(\d+),v=(\d+),c=(\d+)", output)
    assert match is not None
    assert int(match.group(1)) == 51
    assert int(match.group(3)) == 17


def test_kitty_fit_supersamples_pixels_for_same_cell_width(monkeypatch):
    """验证 Kitty fit 会提升像素分辨率但保持显示列宽不变."""
    import re

    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((18, 24)))
    image = SimpleImage.new("RGB", (20, 20), (0, 0, 0))
    renderer = KittyRenderer()
    output = "".join(renderer.render(image, RenderConfig(fit=True)))

    match = re.search(r"s=(\d+),v=(\d+),c=(\d+)", output)
    assert match is not None
    s = int(match.group(1))
    c = int(match.group(3))
    assert c == 5
    assert s > c


def test_shared_display_cols_for_kitty_iterm_wezterm(monkeypatch):
    """验证 Kitty/iTerm2/WezTerm 在 fit 下共享同一显示列宽预算."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((50, 30)))
    img = SimpleImage.new("RGB", (100, 20), (0, 0, 0))

    kitty_out = "".join(KittyRenderer().render(img, RenderConfig(fit=True)))
    iterm_out = "".join(ITerm2Renderer().render(img, RenderConfig(fit=True)))
    wez_out = "".join(WezTermRenderer().render(img, RenderConfig(fit=True)))

    import re

    k = re.search(r"c=(\d+)", kitty_out)
    i = re.search(r"width=(\d+);height=auto", iterm_out)
    w = re.search(r"width=(\d+);height=auto;preserveAspectRatio=1", wez_out)
    assert k is not None and i is not None and w is not None
    assert int(k.group(1)) == int(i.group(1)) == int(w.group(1))


def test_halfblock_uses_same_display_budget(monkeypatch):
    """验证 halfblock 严格路径会受统一 FitPlan 显示列宽预算约束."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((120, 40)))
    matrix = _build_qr_like_matrix(size=25)
    monkeypatch.setattr(renderers, "strict_restore_qr_matrix", lambda *_args, **_kwargs: matrix)
    img = SimpleImage.new("L", (10, 10), color=255)

    plan = layout._build_fit_plan(RenderConfig(fit=True), 29, 29)
    out = "".join(HalfBlockRenderer().render(img, RenderConfig(fit=True)))
    first_line = out.splitlines()[0]
    assert len(first_line) <= plan.display_cols


def test_sixel_cells_to_pixels_query_first_fallback_next(monkeypatch):
    """验证 sixel cells->pixels 映射优先查询，失败时回退默认值."""
    monkeypatch.setattr(layout, "_get_cell_pixel_size", lambda: (9, 18))
    assert layout._cells_to_pixels(5, 2) == (45, 36)

    monkeypatch.setattr(layout, "_get_cell_pixel_size", lambda: None)
    assert layout._cells_to_pixels(5, 2) == (40, 32)


def test_graphic_fit_not_capped_by_default_img_width(monkeypatch):
    """验证 fit=True 未显式传 img_width 时不会被 40 限幅."""
    import re

    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((90, 30)))
    image = SimpleImage.new("RGB", (20, 20), (0, 0, 0))
    renderer = KittyRenderer()
    output = "".join(renderer.render(image, RenderConfig(fit=True)))
    match = re.search(r"c=(\d+)", output)
    assert match is not None
    assert int(match.group(1)) == 26


def test_graphic_fit_respects_explicit_img_width_cap(monkeypatch):
    """验证 fit=True 显式传入 img_width 时会生效为上限."""
    import re

    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((120, 30)))
    image = SimpleImage.new("RGB", (20, 20), (0, 0, 0))
    renderer = KittyRenderer()
    output = "".join(renderer.render(image, RenderConfig(fit=True, img_width=40)))
    match = re.search(r"c=(\d+)", output)
    assert match is not None
    assert int(match.group(1)) == 34


def test_graphic_fit_respects_row_limit(monkeypatch):
    """验证图形协议 fit 会受终端行高约束二次收束."""
    import re

    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((120, 10)))
    image = SimpleImage.new("RGB", (10, 100), (0, 0, 0))
    renderer = KittyRenderer()
    output = "".join(renderer.render(image, RenderConfig(fit=True)))
    match = re.search(r"c=(\d+)", output)
    assert match is not None
    assert int(match.group(1)) == 1


def test_kitty_image_bounding():
    """验证 Kitty 渲染器对直传大图的物理尺寸限幅与 scale 隔离逻辑."""
    import re

    # 模拟一张巨大的 4K 原图
    huge_img = SimpleImage.new("RGB", (3840, 2160), color="white")
    renderer = KittyRenderer()
    # 模拟恶意传入超大 scale
    config = RenderConfig(scale=20)

    output = "".join(renderer.render(huge_img, config))

    # 提取 Kitty 转义序列中的 s(宽) 和 v(高) 参数
    match = re.search(r"s=(\d+),v=(\d+)", output)
    assert match is not None
    width, height = int(match.group(1)), int(match.group(2))

    # 图片直传时, 尺寸不应被 scale 放大(38400), 且应收束在 800x800 安全盒内
    assert width <= 800
    assert height <= 800


def test_iterm2_renderer_output():
    """验证 iTerm2 协议渲染器生成的字符串是否包含内联图像指令."""
    config = RenderConfig()
    image = SimpleImage.new("RGB", (2, 2), (0, 0, 0))
    renderer = ITerm2Renderer()
    output = "".join(renderer.render(image, config))
    # iTerm2 协议特征: 包含 1337;File=inline=1
    assert "1337;File=inline=1" in output
    assert base64.b64decode(output.split(":")[-1].strip("\x07"))


def test_iterm2_fit_uses_cell_width(monkeypatch):
    """验证 iTerm2 在 fit 模式下会写入列宽参数."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((22, 24)))
    image = SimpleImage.new("RGB", (120, 30), (0, 0, 0))
    renderer = ITerm2Renderer()
    output = "".join(renderer.render(image, RenderConfig(fit=True)))
    assert "width=6;height=auto" in output


def test_wezterm_fit_uses_cell_width_with_preserve_aspect(monkeypatch):
    """验证 WezTerm 在 fit 模式下同时保留列宽与等比参数."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((16, 24)))
    image = SimpleImage.new("RGB", (100, 30), (0, 0, 0))
    renderer = WezTermRenderer()
    output = "".join(renderer.render(image, RenderConfig(fit=True)))
    assert "width=4;height=auto;preserveAspectRatio=1" in output


def test_sixel_renderer_output():
    """验证 Sixel 协议渲染器生成的字符串是否以正确的转义序列开始和结束."""
    config = RenderConfig()
    image = SimpleImage.new("L", (2, 2), 0)
    renderer = SixelRenderer()
    output = "".join(renderer.render(image, config))
    # Sixel 协议特征: 以 \x1bP9q 开头 (P1=9 强制 1:1), 以 \x1b\\ 结尾
    assert output.startswith("\x1bP9q")
    assert output.endswith("\x1b\\")
    assert "#1" in output  # 黑色调色板


def test_sixel_fit_best_effort_resizes_before_encode(monkeypatch):
    """验证 Sixel 在 fit 模式下会先按列宽约束图像再编码."""
    seen_widths: list[int] = []

    def _fake_sixel_encode(_bits: bytes, width: int, _height: int) -> str:
        seen_widths.append(width)
        return "#0?$#1@-"

    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((14, 24)))
    monkeypatch.setattr(renderers, "_sixel_encode_mono", _fake_sixel_encode)

    img = SimpleImage.new("L", (120, 20), color=0)
    renderer = SixelRenderer()
    output = "".join(renderer.render(img, RenderConfig(fit=True)))

    assert output.startswith("\x1bP9q")
    assert output.endswith("\x1b\\")
    assert seen_widths == [24]


def test_halfblock_strict_uses_integer_scale(monkeypatch):
    """验证 halfblock 严格路径会按整数倍模块放大."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((120, 40)))
    matrix = _build_qr_like_matrix(size=25)
    monkeypatch.setattr(renderers, "strict_restore_qr_matrix", lambda *_args, **_kwargs: matrix)

    img = SimpleImage.new("L", (10, 10), color=255)
    renderer = HalfBlockRenderer()
    output = "".join(renderer.render(img, RenderConfig(fit=True)))
    first_line = output.splitlines()[0]
    assert len(first_line) == 29


def test_halfblock_too_narrow_keeps_current_downscale_behavior(monkeypatch):
    """验证终端过窄时 halfblock 仍保持当前缩小适配行为."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((20, 20)))
    matrix = _build_qr_like_matrix(size=25)
    monkeypatch.setattr(renderers, "strict_restore_qr_matrix", lambda *_args, **_kwargs: matrix)

    img = SimpleImage.new("L", (10, 10), color=255)
    renderer = HalfBlockRenderer()
    output = "".join(renderer.render(img, RenderConfig(fit=True)))
    first_line = output.splitlines()[0]
    assert len(first_line) <= 19


def test_halfblock_strict_never_produces_nonstandard_qr_size(monkeypatch):
    """验证严格路径输出矩阵尺寸始终为标准 QR 尺寸（21+4k）的整数倍放大，不出现 22 等非法尺寸."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((77, 24)))
    matrix = _build_qr_like_matrix(size=21)
    monkeypatch.setattr(renderers, "strict_restore_qr_matrix", lambda *_args, **_kwargs: matrix)

    img = SimpleImage.new("L", (10, 10), color=255)
    renderer = HalfBlockRenderer()
    output = "".join(renderer.render(img, RenderConfig(fit=True)))
    first_line = output.splitlines()[0]
    line_len = len(first_line)
    # 输出宽度必须是 (21 + 2*border) * scale 的合法值，绝不能是 22。
    assert line_len != 22
    assert line_len >= 21


def test_halfblock_strict_wide_terminal_uses_larger_scale(monkeypatch):
    """验证宽终端下严格路径会使用更大的整数放大倍数."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((140, 60)))
    matrix = _build_qr_like_matrix(size=25)
    monkeypatch.setattr(renderers, "strict_restore_qr_matrix", lambda *_args, **_kwargs: matrix)

    img = SimpleImage.new("L", (10, 10), color=255)
    renderer = HalfBlockRenderer()
    output = "".join(renderer.render(img, RenderConfig(fit=True)))
    first_line = output.splitlines()[0]
    # 25 + 2*2 = 29 (scale=1); avail_cols=139 可容纳 scale=4 → 29*4=116。
    # 旧代码只用 30% 预算 → display_cols=41 → scale=1 → 宽度仅 29。
    assert len(first_line) > 29


def test_halfblock_strict_reduces_border_before_resize(monkeypatch):
    """验证终端略窄时先缩 border 而非直接 resize 模块网格."""
    # size=25, border=2 → base_w=29; avail=27 → 放不下。
    # 期望: border 缩到 1 → base_w=27，刚好放下，不触发 resize。
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((28, 24)))
    matrix = _build_qr_like_matrix(size=25)
    monkeypatch.setattr(renderers, "strict_restore_qr_matrix", lambda *_args, **_kwargs: matrix)

    img = SimpleImage.new("L", (10, 10), color=255)
    renderer = HalfBlockRenderer()
    output = "".join(renderer.render(img, RenderConfig(fit=True)))
    first_line = output.splitlines()[0]
    # border=1, scale=1 → 25+2=27
    assert len(first_line) == 27


def test_halfblock_strict_respects_img_width_cap(monkeypatch):
    """验证严格路径仍受 img_width 上限约束."""
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((200, 40)))
    matrix = _build_qr_like_matrix(size=25)
    monkeypatch.setattr(renderers, "strict_restore_qr_matrix", lambda *_args, **_kwargs: matrix)

    img = SimpleImage.new("L", (10, 10), color=255)
    renderer = HalfBlockRenderer()
    output = "".join(renderer.render(img, RenderConfig(fit=True, img_width=30)))
    first_line = output.splitlines()[0]
    assert len(first_line) <= 30


def test_renderer_registry_get():
    """验证注册表是否能根据终端能力返回正确的渲染器实例."""
    assert isinstance(DEFAULT_RENDERER_REGISTRY.get(TerminalCapability.KITTY), KittyRenderer)
    assert isinstance(DEFAULT_RENDERER_REGISTRY.get(TerminalCapability.ITERM2), ITerm2Renderer)
    assert isinstance(DEFAULT_RENDERER_REGISTRY.get(TerminalCapability.WEZTERM), WezTermRenderer)
    assert isinstance(DEFAULT_RENDERER_REGISTRY.get(TerminalCapability.SIXEL), SixelRenderer)
    assert isinstance(DEFAULT_RENDERER_REGISTRY.get(TerminalCapability.FALLBACK), HalfBlockRenderer)


def test_halfblock_renderer_streaming():
    """验证 HalfBlockRenderer 是否以生成器形式产出分片而非单一字符串."""
    from collections.abc import Generator

    renderer = HalfBlockRenderer()
    image = SimpleImage.new("L", (2, 3), 0)
    config = RenderConfig(ascii_only=False, invert=False, img_width=2)

    result = renderer.render(image, config)

    # 此时应返回生成器对象
    assert isinstance(result, Generator)
    chunks = list(result)
    assert len(chunks) > 0
    full_output = "".join(chunks)
    assert any(c in full_output for c in ("▄", "▀", "█", " "))


@patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,123,0"}, clear=False)
@patch("terminal_qrcode.renderers._tmux_allow_passthrough", return_value=False)
def test_kitty_renderer_tmux_auto_disabled_not_wrapped(mock_allow):
    """验证 tmux 穿透策略为 auto 且未启用 allow-passthrough 时不进行包裹."""
    config = RenderConfig(tmux_passthrough="auto")
    image = SimpleImage.new("RGB", (2, 2), (0, 0, 0))
    renderer = KittyRenderer()

    output = "".join(renderer.render(image, config))

    assert output.startswith("\x1b_G")
    assert "\x1bPtmux;" not in output


@patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,123,0"}, clear=False)
@patch("terminal_qrcode.renderers._tmux_allow_passthrough", return_value=False)
def test_sixel_renderer_tmux_auto_disabled_not_wrapped(mock_allow):
    """验证 Sixel 在 tmux auto 且未启用 allow-passthrough 时不进行包裹."""
    config = RenderConfig(tmux_passthrough="auto")
    image = SimpleImage.new("L", (2, 2), 0)
    renderer = SixelRenderer()

    output = "".join(renderer.render(image, config))

    assert output.startswith("\x1bP9q")
    assert "\x1bPtmux;" not in output


@patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,123,0"}, clear=False)
@patch("terminal_qrcode.renderers._tmux_allow_passthrough", return_value=False)
def test_kitty_renderer_tmux_always_forces_wrap(mock_allow):
    """验证 tmux 穿透策略为 always 时即使未启用 allow-passthrough 也强制包裹."""
    config = RenderConfig(tmux_passthrough="always")
    image = SimpleImage.new("RGB", (2, 2), (0, 0, 0))
    renderer = KittyRenderer()

    output = "".join(renderer.render(image, config))

    assert output.startswith("\x1bPtmux;")


@patch.dict("os.environ", {"TMUX": "/tmp/tmux-1000/default,123,0"}, clear=False)
@patch("terminal_qrcode.renderers._tmux_allow_passthrough", return_value=False)
def test_sixel_renderer_tmux_always_forces_wrap(mock_allow):
    """验证 Sixel 在 tmux always 时强制包裹序列."""
    config = RenderConfig(tmux_passthrough="always")
    image = SimpleImage.new("L", (2, 2), 0)
    renderer = SixelRenderer()

    output = "".join(renderer.render(image, config))

    assert output.startswith("\x1bPtmux;")
