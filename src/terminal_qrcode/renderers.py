"""渲染器."""

import base64
import logging
import math
import os
import subprocess
from collections.abc import Callable, Generator, Hashable
from functools import lru_cache
from typing import Generic, TypeVar

from colorama import just_fix_windows_console

from .contracts import ColorLevelName, Matrix, RenderConfig, Renderer, TerminalCapability
from .layout import (
    _build_fit_plan,
    _cells_to_pixels,
    _get_cell_pixel_size,
    _matrix_to_image,
    _resolve_target_cols,
    _sixel_encode_mono,
    _threshold_to_bits,
    _upscale_matrix_nn,
)
from .simple_image import SimpleImage

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
    """将协议序列包裹为 tmux 可转发的 DCS 格式."""
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

    def render(self, payload: Matrix | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
        """将矩阵渲染为半块 Unicode 字符流."""
        if isinstance(payload, SimpleImage):
            raise TypeError("HalfBlockRenderer only accepts matrix payload.")
        matrix = self._normalize_matrix(payload, config)
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

                # 有颜色时统一用 "▀"，无颜色时根据上下选择字符
                if color_enabled:
                    # 对 halfblock "▀" 字符：前景色=上半块，背景色=下半块
                    fg_dark = bool(top)
                    bg_dark = bool(bottom)
                    char = "▀"
                else:
                    # 无颜色时根据 top/bottom 组合选择字符
                    char_idx = (int(top) << 1) | int(bottom)
                    char = _HALFBLOCK_CHARS[char_idx]
                    fg_dark = False
                    bg_dark = False

                # 检查是否需要发送新的 SGR（颜色改变或运行结束）
                if color_enabled and (fg_dark != last_fg_dark or bg_dark != last_bg_dark):
                    # 输出前一个 run 的字符（如果有的话）
                    if run_chars and last_fg_dark is not None and last_bg_dark is not None:
                        sgr = _halfblock_sgr(color_level, last_fg_dark, last_bg_dark)
                        line_parts.append(sgr)
                        line_parts.append("".join(run_chars))
                        run_chars.clear()
                    # 记录新的颜色
                    last_fg_dark = fg_dark
                    last_bg_dark = bg_dark

                run_chars.append(char)

            # 输出最后一个 run
            if run_chars:
                # 仅当颜色启用且之前有 run 时才发送 SGR
                if color_enabled and last_fg_dark is not None and last_bg_dark is not None:
                    sgr = _halfblock_sgr(color_level, last_fg_dark, last_bg_dark)
                    line_parts.append(sgr)
                line_parts.append("".join(run_chars))

            # 添加重置序列
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

    def render(self, payload: Matrix | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
        """根据 Kitty 图形协议渲染矩阵或原始图像."""
        if isinstance(payload, SimpleImage):
            image = payload.convert("RGBA")
            plan = _build_fit_plan(config, image.width, image.height)
            display_cols = max(1, plan.display_cols)
            display_rows = max(1, plan.display_rows)
        else:
            size = len(payload)
            scale, display_cols, display_rows = _resolve_integer_scale(config, size)
            image = _matrix_to_image(payload, scale, "RGBA")
        width, height = image.width, image.height

        rgba_data = image.tobytes()
        b64_data = base64.b64encode(rgba_data).decode("ascii")

        chunk_size = 4096
        payloads: list[str] = []
        should_wrap = _should_tmux_wrap(config)

        for i in range(0, len(b64_data), chunk_size):
            chunk = b64_data[i : i + chunk_size]
            is_last = (i + chunk_size) >= len(b64_data)
            m = 0 if is_last else 1

            if i == 0:
                sequence = f"\x1b_Ga=T,f=32,s={width},v={height},c={display_cols},r={display_rows},m={m};{chunk}\x1b\\"
            else:
                sequence = f"\x1b_Gm={m};{chunk}\x1b\\"

            if should_wrap:
                sequence = _tmux_wrap(sequence)

            payloads.append(sequence)

        yield "".join(payloads)


class ITerm2Renderer:
    """iTerm2 终端图形协议渲染器."""

    def render(self, payload: Matrix | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
        """根据 iTerm2 内联图像协议渲染矩阵或原始图像."""
        if isinstance(payload, SimpleImage):
            image = payload.convert("RGB")
            plan = _build_fit_plan(config, image.width, image.height)
            display_cols = max(1, plan.display_cols)
        else:
            size = len(payload)
            scale, display_cols, _display_rows = _resolve_integer_scale(config, size)
            image = _matrix_to_image(payload, scale, "RGB")

        png_data = image.to_png_bytes()
        b64_data = base64.b64encode(png_data).decode("ascii")
        payload_seq = f"\x1b]1337;File=inline=1;width={display_cols};height=auto:{b64_data}\x07"

        if _should_tmux_wrap(config):
            yield _tmux_wrap(payload_seq)
            return

        yield payload_seq


class WezTermRenderer(ITerm2Renderer):
    """WezTerm 终端图形协议渲染器 (基于 iTerm2 协议增强)."""

    def render(self, payload: Matrix | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
        """根据 WezTerm 增强型的 iTerm2 内联图像协议渲染."""
        if isinstance(payload, SimpleImage):
            image = payload.convert("RGB")
            plan = _build_fit_plan(config, image.width, image.height)
            display_cols = max(1, plan.display_cols)
        else:
            size = len(payload)
            scale, display_cols, _display_rows = _resolve_integer_scale(config, size)
            image = _matrix_to_image(payload, scale, "RGB")

        png_data = image.to_png_bytes()
        b64_data = base64.b64encode(png_data).decode("ascii")
        payload_seq = f"\x1b]1337;File=inline=1;width={display_cols};height=auto;preserveAspectRatio=1:{b64_data}\x07"

        if _should_tmux_wrap(config):
            yield _tmux_wrap(payload_seq)
            return

        yield payload_seq


class SixelRenderer:
    """DEC Sixel 图形协议渲染器."""

    def render(self, payload: Matrix | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
        """根据 DEC Sixel 协议渲染矩阵或原始图像."""
        if isinstance(payload, SimpleImage):
            image = payload.convert("L")
        else:
            size = len(payload)
            scale, _display_cols, _display_rows = _resolve_integer_scale(config, size)
            image = _matrix_to_image(payload, scale, "RGB").convert("L")

        width, height = image.width, image.height
        bits = _threshold_to_bits(image, threshold=128)

        header = f'\x1bP9q"1;1;{width};{height}#0;2;100;100;100#1;2;0;0;0'
        footer = "\x1b\\"

        body = _sixel_encode_mono(bits, width, height)
        payload_seq = header + body + footer
        if _should_tmux_wrap(config):
            yield _tmux_wrap(payload_seq)
            return
        yield payload_seq


class RendererRegistry(Generic[T]):
    """按终端能力映射渲染器工厂."""

    def __init__(
        self,
        factories: dict[Hashable, Callable[[], T]] | None = None,
        *,
        fallback_factory: Callable[[], T],
    ) -> None:
        """初始化渲染器注册表."""
        self._factories: dict[Hashable, Callable[[], T]] = dict(factories or {})
        self._fallback_factory = fallback_factory

    def register(self, capability: Hashable, factory: Callable[[], T]) -> None:
        """注册 capability 对应的渲染器工厂."""
        self._factories[capability] = factory

    def get(self, capability: Hashable) -> T:
        """获取 capability 对应渲染器，不存在时回退默认工厂."""
        factory = self._factories.get(capability, self._fallback_factory)
        return factory()


def build_default_renderer_registry() -> RendererRegistry[Renderer]:
    """创建默认的 capability -> renderer 注册表."""
    factories: dict[Hashable, Callable[[], Renderer]] = {
        TerminalCapability.KITTY: KittyRenderer,
        TerminalCapability.ITERM2: ITerm2Renderer,
        TerminalCapability.WEZTERM: WezTermRenderer,
        TerminalCapability.SIXEL: SixelRenderer,
        TerminalCapability.FALLBACK: HalfBlockRenderer,
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
