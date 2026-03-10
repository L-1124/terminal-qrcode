"""渲染器."""

import base64
import logging
import math
import os
import subprocess
from collections.abc import Callable, Generator
from functools import lru_cache
from typing import Generic, TypeVar

from colorama import just_fix_windows_console

from ._contracts import (
    ColorLevelName,
    ImageSource,
    Matrix,
    MatrixSource,
    QRSource,
    RenderConfig,
    Renderer,
    RendererId,
    TerminalCapability,
)
from ._layout import (
    _build_fit_plan,
    _cells_to_pixels,
    _get_cell_pixel_size,
    _matrix_to_image,
    _resolve_target_cols,
    _sixel_encode_mono,
    _threshold_to_bits,
    _upscale_matrix_nn,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
_HALFBLOCK_MAX_SCALE = 10


@lru_cache(maxsize=1)
def _ensure_colorama_console() -> None:
    """初始化 Windows ANSI 颜色支持（其它平台无副作用）."""
    just_fix_windows_console()


_SGR_RESET = "\x1b[0m"
_HALFBLOCK_CHARS = (" ", "▄", "▀", "█")


def _halfblock_sgr(color_level: ColorLevelName, fg_dark: bool, bg_dark: bool) -> str:
    """根据颜色等级生成半块字符前景/背景 SGR 片段."""
    if color_level == "ansi16":
        fg_code = 30 if fg_dark else 97
        bg_code = 40 if bg_dark else 107
        return f"\x1b[{fg_code};{bg_code}m"
    if color_level == "ansi256":
        fg = "38;5;16" if fg_dark else "38;5;231"
        bg = "48;5;16" if bg_dark else "48;5;231"
        return f"\x1b[{fg};{bg}m"
    fg = "38;2;0;0;0" if fg_dark else "38;2;255;255;255"
    bg = "48;2;0;0;0" if bg_dark else "48;2;255;255;255"
    return f"\x1b[{fg};{bg}m"


@lru_cache(maxsize=4)
def _halfblock_palette(color_level: ColorLevelName) -> tuple[str, str, str, str]:
    """按颜色等级预计算四种 top/bottom 组合的输出片段."""
    if color_level == "none":
        return _HALFBLOCK_CHARS
    return (
        f"{_halfblock_sgr(color_level, fg_dark=False, bg_dark=False)}▀",
        f"{_halfblock_sgr(color_level, fg_dark=False, bg_dark=True)}▀",
        f"{_halfblock_sgr(color_level, fg_dark=True, bg_dark=False)}▀",
        f"{_halfblock_sgr(color_level, fg_dark=True, bg_dark=True)}▀",
    )


@lru_cache(maxsize=1)
def _tmux_allow_passthrough() -> bool | None:
    """读取 tmux allow-passthrough 配置, 失败时返回 None."""
    if "TMUX" not in os.environ:
        return None

    try:
        result = subprocess.run(
            ["tmux", "show-options", "-gv", "allow-passthrough"],
            capture_output=True,
            check=False,
            text=True,
            timeout=0.3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    value = result.stdout.strip().lower()
    if value in {"on", "1", "yes", "true"}:
        return True
    if value in {"off", "0", "no", "false"}:
        return False
    return None


def _should_tmux_wrap(config: RenderConfig) -> bool:
    """按策略决定是否为图形协议序列添加 tmux DCS 包裹."""
    if "TMUX" not in os.environ:
        return False

    if config.probe.tmux_passthrough == "always":
        return True
    if config.probe.tmux_passthrough == "never":
        return False

    allow = _tmux_allow_passthrough()
    if allow is True:
        return True
    if allow is False:
        logger.warning(
            "TMUX detected but allow-passthrough is off; graphic escape passthrough "
            "is disabled. Enable via `set -g allow-passthrough on`, or set "
            "tmux_passthrough='always' to force wrapping."
        )
        return False

    logger.warning(
        "TMUX detected but allow-passthrough status is unknown; attempting passthrough "
        "wrapping. If rendering fails, enable `set -g allow-passthrough on`."
    )
    return True


def _tmux_wrap(sequence: str) -> str:
    """将协议序列包裹为 tmux 可转发的 DCS格式."""
    inner = sequence.replace("\x1b", "\x1b\x1b")
    return f"\x1bPtmux;{inner}\x1b\\"


def _resolve_integer_scale(config: RenderConfig, matrix_size: int) -> tuple[int, int, int]:
    """根据显示预算计算矩阵图像的整数放大倍率与展示 cell 尺寸."""
    plan = _build_fit_plan(config, matrix_size, matrix_size)
    display_cols_budget = max(1, plan.display_cols)

    cell_size = _get_cell_pixel_size()
    if cell_size is None:
        cell_w, cell_h = _cells_to_pixels(1, 1)
    else:
        cell_w, cell_h = cell_size

    max_pixel_width = display_cols_budget * cell_w
    scale = max(1, max_pixel_width // matrix_size)
    image_px = matrix_size * scale
    display_cols = max(1, math.ceil(image_px / max(1, cell_w)))
    display_rows = max(1, math.ceil(image_px / max(1, cell_h)))
    return scale, display_cols, display_rows


class HalfBlockRenderer:
    """半块字符降级渲染器."""

    def render(self, source: QRSource, config: RenderConfig) -> Generator[str, None, None]:
        """将数据源渲染为半块 Unicode 字符流."""
        if isinstance(source, MatrixSource):
            matrix = self._normalize_matrix(source.matrix, config)
        elif isinstance(source, ImageSource):
            # 即使是 ImageSource，HalfBlock 也会由 core.py 预处理为 MatrixSource
            # 此处加一层稳健性检查
            raise TypeError("HalfBlockRenderer cannot render ImageSource directly.")
        else:
            raise TypeError(f"Unsupported source type: {type(source)}")

        yield from self._generate_characters(matrix, bool(config.qr.invert), config.probe.color_level)

    def _normalize_matrix(self, payload: Matrix, config: RenderConfig) -> Matrix:
        """将输入矩阵归一化并按模式执行尺寸适配."""
        matrix = [list(row) for row in payload]
        if not matrix or not matrix[0]:
            return [[False]]
        base_w = len(matrix[0])

        if not config.layout.fit:
            target_cols = _resolve_target_cols(config)
            if base_w > target_cols:
                raise ValueError(
                    "Terminal width constraint is too small for QR matrix. Refusing lossy halfblock downscale."
                )
            return matrix

        plan = _build_fit_plan(config, len(matrix[0]), len(matrix))
        effective_cols = max(1, plan.avail_cols)
        if config.layout.max_cols is not None:
            effective_cols = min(effective_cols, config.layout.max_cols)
        if config.layout.img_width is not None:
            effective_cols = min(effective_cols, config.layout.img_width)

        if base_w > effective_cols:
            raise ValueError(
                "Terminal is too narrow to render scannable QR in halfblock mode. "
                "Increase width or use a graphic protocol renderer."
            )

        if config.layout.halfblock_mode == "precision":
            return matrix

        scale = self._choose_scale_area_mode(len(matrix[0]), len(matrix), plan.avail_cols, plan.avail_rows)
        return _upscale_matrix_nn(matrix, scale)

    def _choose_scale_area_mode(self, base_w: int, base_h: int, avail_cols: int, avail_rows: int) -> int:
        """为面积优先模式选择可用整数 scale（仅允许偶数，且满足精确行高预算）."""
        if base_w <= 0 or base_h <= 0:
            return 1
        max_by_width = avail_cols // base_w
        max_by_rows = (2 * avail_rows) // base_h
        s_max = max(1, min(max_by_width, max_by_rows, _HALFBLOCK_MAX_SCALE))
        if s_max < 2:
            return 1
        if s_max % 2 != 0:
            s_max -= 1
        while s_max >= 2:
            if (base_w * s_max) <= avail_cols and math.ceil((base_h * s_max) / 2) <= avail_rows:
                return s_max
            s_max -= 2
        return 1

    def _generate_characters(
        self, matrix: Matrix, invert_for_render: bool, color_level: ColorLevelName
    ) -> Generator[str, None, None]:
        """将 bool 矩阵转换为字符串流，按 run 合并相同 SGR."""
        rows = [row[:] for row in matrix]
        if len(rows) % 2 != 0:
            rows.append([False] * len(rows[0]))

        lines_per_chunk = 50
        buffer_pool: list[str] = []
        color_enabled = color_level != "none"
        if color_enabled:
            _ensure_colorama_console()

        for i in range(0, len(rows), 2):
            row_top = rows[i]
            row_bottom = rows[i + 1]

            line_parts: list[str] = []
            last_fg_dark: bool | None = None
            last_bg_dark: bool | None = None
            run_chars: list[str] = []

            for top, bottom in zip(row_top, row_bottom, strict=False):
                if invert_for_render:
                    top, bottom = not top, not bottom

                if color_enabled:
                    fg_dark = bool(top)
                    bg_dark = bool(bottom)
                    char = "▀"
                else:
                    char_idx = (int(top) << 1) | int(bottom)
                    char = _HALFBLOCK_CHARS[char_idx]
                    fg_dark = False
                    bg_dark = False

                if color_enabled and (fg_dark != last_fg_dark or bg_dark != last_bg_dark):
                    if run_chars:
                        if last_fg_dark is not None and last_bg_dark is not None:
                            sgr = _halfblock_sgr(color_level, last_fg_dark, last_bg_dark)
                            line_parts.append(sgr)
                        line_parts.append("".join(run_chars))
                        run_chars.clear()
                    last_fg_dark = fg_dark
                    last_bg_dark = bg_dark

                run_chars.append(char)

            if run_chars:
                if color_enabled and last_fg_dark is not None and last_bg_dark is not None:
                    sgr = _halfblock_sgr(color_level, last_fg_dark, last_bg_dark)
                    line_parts.append(sgr)
                line_parts.append("".join(run_chars))

            if color_enabled:
                line_parts.append(_SGR_RESET)

            line = "".join(line_parts)
            buffer_pool.append(line)
            if len(buffer_pool) >= lines_per_chunk:
                yield "\n".join(buffer_pool) + "\n"
                buffer_pool.clear()

        if buffer_pool:
            yield "\n".join(buffer_pool)


class KittyRenderer:
    """Kitty 终端图形协议渲染器."""

    def render(self, source: QRSource, config: RenderConfig) -> Generator[str, None, None]:
        """根据 Kitty 图形协议渲染源."""
        if isinstance(source, ImageSource):
            image = source.image.convert("RGBA")
            plan = _build_fit_plan(config, image.width, image.height)
            display_cols = max(1, plan.display_cols)
            display_rows = max(1, plan.display_rows)
        elif isinstance(source, MatrixSource):
            size = len(source.matrix)
            scale, display_cols, display_rows = _resolve_integer_scale(config, size)
            image = _matrix_to_image(source.matrix, scale, "RGBA")
        else:
            raise TypeError(f"Unsupported source type: {type(source)}")

        # 优化：流式切片编码，降低内存峰值
        png_data = image.to_png_bytes()

        # 按 3 字节的倍数切分（如 3000 字节），确保生成的每段 Base64 块都没有中途 Padding
        # Kitty 协议允许每块带 Padding，但流式切分更稳健且节省内存
        chunk_size_raw = 3000
        should_wrap = _should_tmux_wrap(config)
        first_chunk = True

        for i in range(0, len(png_data), chunk_size_raw):
            raw_chunk = png_data[i : i + chunk_size_raw]
            b64_chunk = base64.b64encode(raw_chunk).decode("ascii")

            is_last = (i + chunk_size_raw) >= len(png_data)
            m = 0 if is_last else 1

            if first_chunk:
                # f=100 表示 PNG 格式
                sequence = f"\x1b_Ga=T,f=100,c={display_cols},r={display_rows},m={m};{b64_chunk}\x1b\\"
                first_chunk = False
            else:
                sequence = f"\x1b_Gm={m};{b64_chunk}\x1b\\"

            if should_wrap:
                sequence = _tmux_wrap(sequence)

            yield sequence


class ITerm2Renderer:
    """iTerm2 终端图形协议渲染器."""

    def _extra_params(self) -> str:
        """子类可覆盖以追加额外 OSC 参数."""
        return ""

    def render(self, source: QRSource, config: RenderConfig) -> Generator[str, None, None]:
        """根据 iTerm2 内联图像协议渲染源."""
        if isinstance(source, ImageSource):
            image = source.image.convert("RGB")
            plan = _build_fit_plan(config, image.width, image.height)
            display_cols = max(1, plan.display_cols)
        elif isinstance(source, MatrixSource):
            size = len(source.matrix)
            scale, display_cols, _display_rows = _resolve_integer_scale(config, size)
            image = _matrix_to_image(source.matrix, scale, "RGB")
        else:
            raise TypeError(f"Unsupported source type: {type(source)}")

        png_data = image.to_png_bytes()
        b64_data = base64.b64encode(png_data).decode("ascii")
        extra = self._extra_params()
        payload_seq = f"\x1b]1337;File=inline=1;width={display_cols};height=auto{extra}:{b64_data}\x07"

        if _should_tmux_wrap(config):
            yield _tmux_wrap(payload_seq)
            return

        yield payload_seq


class WezTermRenderer(ITerm2Renderer):
    """WezTerm 终端图形协议渲染器 (基于 iTerm2 协议增强)."""

    def _extra_params(self) -> str:
        """追加 preserveAspectRatio 参数."""
        return ";preserveAspectRatio=1"


class SixelRenderer:
    """DEC Sixel 图形协议渲染器."""

    def render(self, source: QRSource, config: RenderConfig) -> Generator[str, None, None]:
        """根据 DEC Sixel 协议渲染源."""
        if isinstance(source, ImageSource):
            image = source.image.convert("L")
        elif isinstance(source, MatrixSource):
            size = len(source.matrix)
            scale, _display_cols, _display_rows = _resolve_integer_scale(config, size)
            image = _matrix_to_image(source.matrix, scale, "RGB").convert("L")
        else:
            raise TypeError(f"Unsupported source type: {type(source)}")

        width, height = image.width, image.height
        bits = _threshold_to_bits(image, threshold=128)

        header = f'\x1bP9;0q"1;1;{width};{height}#0;2;100;100;100#1;2;0;0;0'
        footer = "\x1b\\"

        body = _sixel_encode_mono(bits, width, height)
        payload_seq = header + body + footer
        if _should_tmux_wrap(config):
            yield _tmux_wrap(payload_seq)
            return
        yield payload_seq


def _is_ssh_connection() -> bool:
    """检测当前是否处于 SSH 连接中."""
    return "SSH_CONNECTION" in os.environ or "SSH_CLIENT" in os.environ


class RendererRegistry(Generic[T]):
    """按标识映射渲染器工厂，支持环境自适应排序."""

    def __init__(
        self,
        factories: dict[RendererId, Callable[[], T]] | None = None,
        *,
        fallback_factory: Callable[[], T],
    ) -> None:
        """初始化渲染器注册表."""
        self._factories: dict[RendererId, Callable[[], T]] = dict(factories or {})
        self._fallback_factory = fallback_factory

    def register(self, renderer_id: RendererId, factory: Callable[[], T]) -> None:
        """注册 renderer_id 对应的渲染器工厂."""
        self._factories[renderer_id] = factory

    def get(self, renderer_id: RendererId) -> T:
        """获取 renderer_id 对应渲染器，不存在时回退默认工厂."""
        factory = self._factories.get(renderer_id, self._fallback_factory)
        return factory()

    def select_renderer(self, capabilities: list[TerminalCapability]) -> T:
        """根据能力列表选择最优渲染器 ID 并实例化."""
        if not capabilities:
            return self._fallback_factory()

        # 能力到协议 ID 的映射表
        cap_map = {
            TerminalCapability.KITTY: RendererId.KITTY,
            TerminalCapability.WEZTERM: RendererId.WEZTERM,
            TerminalCapability.ITERM2: RendererId.ITERM2,
            TerminalCapability.SIXEL: RendererId.SIXEL,
            TerminalCapability.FALLBACK: RendererId.HALFBLOCK,
        }

        # 优先级逻辑（支持 SSH 自适应）
        if _is_ssh_connection():
            priority = [
                TerminalCapability.SIXEL,
                TerminalCapability.KITTY,
                TerminalCapability.WEZTERM,
                TerminalCapability.ITERM2,
                TerminalCapability.FALLBACK,
            ]
        else:
            priority = [
                TerminalCapability.KITTY,
                TerminalCapability.WEZTERM,
                TerminalCapability.ITERM2,
                TerminalCapability.SIXEL,
                TerminalCapability.FALLBACK,
            ]

        for cap in priority:
            if cap in capabilities:
                renderer_id = cap_map.get(cap)
                if renderer_id:
                    return self.get(renderer_id)

        return self._fallback_factory()


def build_default_renderer_registry() -> RendererRegistry[Renderer]:
    """创建默认的 RendererId -> renderer 注册表."""
    factories: dict[RendererId, Callable[[], Renderer]] = {
        RendererId.KITTY: KittyRenderer,
        RendererId.ITERM2: ITerm2Renderer,
        RendererId.WEZTERM: WezTermRenderer,
        RendererId.SIXEL: SixelRenderer,
        RendererId.HALFBLOCK: HalfBlockRenderer,
    }
    return RendererRegistry(factories, fallback_factory=HalfBlockRenderer)


__all__ = [
    "RendererRegistry",
    "build_default_renderer_registry",
    "HalfBlockRenderer",
    "KittyRenderer",
    "ITerm2Renderer",
    "WezTermRenderer",
    "SixelRenderer",
    "_tmux_allow_passthrough",
    "_should_tmux_wrap",
    "_tmux_wrap",
]
