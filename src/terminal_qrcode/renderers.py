"""渲染器."""

import base64
import logging
import os
import subprocess
from collections.abc import Callable, Generator, Hashable
from functools import lru_cache
from typing import Generic, TypeVar

from terminal_qrcode.contracts import RenderConfig, Renderer, TerminalCapability
from terminal_qrcode.layout import (
    _build_fit_plan,
    _cells_to_pixels,
    _choose_halfblock_scale,
    _matrix_to_image,
    _pad_border,
    _resize_image_to_cols,
    _resize_matrix_to_cols,
    _resolve_target_cols,
    _sixel_encode_mono,
    _threshold_to_bits,
    _to_luma_bits,
    _upscale_matrix_nn,
)
from terminal_qrcode.qr_restore import strict_restore_qr_matrix
from terminal_qrcode.simple_image import SimpleImage

logger = logging.getLogger(__name__)

T = TypeVar("T")
_HALFBLOCK_MAX_SCALE = 10
_KITTY_SUPERSAMPLE = 3


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

    if config.tmux_passthrough == "always":
        return True
    if config.tmux_passthrough == "never":
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


class HalfBlockRenderer:
    """半块字符降级渲染器."""

    def render(self, payload: list[list[bool]] | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
        """将矩阵或图像分块渲染为半块 Unicode 字符流."""
        matrix, invert_for_render = self._normalize_to_matrix(payload, config)
        yield from self._generate_characters(matrix, invert_for_render, config.ascii_only)

    def _normalize_to_matrix(
        self, payload: list[list[bool]] | SimpleImage, config: RenderConfig
    ) -> tuple[list[list[bool]], bool]:
        """将不同类型的输入归一化为 bool 矩阵, 并确定是否需要反色."""
        invert_for_render = bool(config.invert)

        if not isinstance(payload, SimpleImage):
            target_cols = _resolve_target_cols(config)
            matrix = _resize_matrix_to_cols([list(row) for row in payload], target_cols)
            return matrix, invert_for_render

        if self._quick_qr_prior(payload):
            strict_matrix = strict_restore_qr_matrix(payload.copy(), config)
            if strict_matrix is not None:
                matrix = self._resize_strict_matrix(strict_matrix, config)

                return matrix, False

        matrix = self._normalize_image_fallback(payload, config)
        return matrix, invert_for_render

    def _quick_qr_prior(self, image: SimpleImage) -> bool:
        """快速判断图像是否值得走严格二维码还原路径."""
        if min(image.width, image.height) < 21:
            return False
        bbox = image.getbbox_nonwhite()
        if bbox is None:
            return False
        left, top, right, bottom = bbox
        bbox_w = right - left
        bbox_h = bottom - top
        if bbox_w < 21 or bbox_h < 21:
            return False
        ratio = max(bbox_w, bbox_h) / max(1, min(bbox_w, bbox_h))
        return ratio <= 1.8

    def _resize_strict_matrix(self, strict_matrix: list[list[bool]], config: RenderConfig) -> list[list[bool]]:
        """实现严格模式下的尺寸适配逻辑."""
        if not config.fit:
            target_cols = _resolve_target_cols(config)
            return _resize_matrix_to_cols(strict_matrix, target_cols)

        border = 2
        plan = _build_fit_plan(config, len(strict_matrix), len(strict_matrix))

        effective_cols = plan.avail_cols
        if config.max_cols is not None:
            effective_cols = min(effective_cols, config.max_cols)
        if config.img_width is not None:
            effective_cols = min(effective_cols, config.img_width)
        effective_cols = max(1, effective_cols)

        while border > 0 and (len(strict_matrix) + 2 * border) > effective_cols:
            border -= 1

        base_w = len(strict_matrix) + 2 * border
        if base_w > effective_cols:
            return _resize_matrix_to_cols(_pad_border(strict_matrix, border), effective_cols)

        scale, border = _choose_halfblock_scale(
            len(strict_matrix),
            border,
            effective_cols,
            plan.avail_rows,
            _HALFBLOCK_MAX_SCALE,
        )
        return _upscale_matrix_nn(_pad_border(strict_matrix, border), scale)

    def _normalize_image_fallback(self, payload: SimpleImage, config: RenderConfig) -> list[list[bool]]:
        """实现普通图像的回退规约逻辑."""
        img = payload.copy().convert("L")

        bbox = img.getbbox_nonwhite()
        if bbox:
            img = img.crop(bbox)

        plan = _build_fit_plan(config, img.width, img.height)
        img = _resize_image_to_cols(
            img,
            plan.display_cols,
        )
        logger.debug("HalfBlock fallback: constraining image to target cols=%s", plan.display_cols)

        bits, _threshold = _to_luma_bits(img, threshold=None)
        matrix = []
        for y in range(img.height):
            row_start = y * img.width
            row_end = row_start + img.width
            matrix.append([b == 1 for b in bits[row_start:row_end]])
        return matrix

    def _generate_characters(
        self, matrix: list[list[bool]], invert_for_render: bool, ascii_only: bool
    ) -> Generator[str, None, None]:
        """将 bool 矩阵转换为字符串流."""
        if len(matrix) % 2 != 0:
            matrix.append([False] * len(matrix[0]))

        lines_per_chunk = 50
        buffer_pool: list[str] = []

        if ascii_only:
            char_black = "  " if invert_for_render else "██"
            char_white = "██" if invert_for_render else "  "
            for row in matrix:
                line = "".join(char_black if cell else char_white for cell in row)
                buffer_pool.append(line)
                if len(buffer_pool) >= lines_per_chunk:
                    yield "\n".join(buffer_pool) + "\n"
                    buffer_pool.clear()
        else:
            for i in range(0, len(matrix), 2):
                row_top = matrix[i]
                row_bottom = matrix[i + 1]

                line_chars = []
                for top, bottom in zip(row_top, row_bottom, strict=False):
                    if invert_for_render:
                        top, bottom = not top, not bottom

                    if top and bottom:
                        line_chars.append("█")
                    elif top:
                        line_chars.append("▀")
                    elif bottom:
                        line_chars.append("▄")
                    else:
                        line_chars.append(" ")

                buffer_pool.append("".join(line_chars))
                if len(buffer_pool) >= lines_per_chunk:
                    yield "\n".join(buffer_pool) + "\n"
                    buffer_pool.clear()

        if buffer_pool:
            yield "\n".join(buffer_pool)


class KittyRenderer:
    """Kitty 终端图形协议渲染器."""

    def render(self, payload: list[list[bool]] | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
        """根据 Kitty 图形协议渲染矩阵或图像."""
        if isinstance(payload, SimpleImage):
            image = payload.copy().convert("RGBA")
        else:
            image = _matrix_to_image(payload, config.scale, "RGBA")
        plan = _build_fit_plan(config, image.width, image.height)
        display_cols = plan.display_cols
        display_rows = plan.display_rows
        pixel_cols = min(800, display_cols * _KITTY_SUPERSAMPLE) if config.fit else display_cols
        image = _resize_image_to_cols(
            image,
            pixel_cols,
            allow_upscale=True,
        )
        image.thumbnail((800, 800))
        width, height = image.width, image.height
        display_cols = min(display_cols, width)
        logger.debug(
            "Kitty rendering image: target_size=%sx%s, fit=%s display_cols=%s display_rows=%s",
            width,
            height,
            config.fit,
            display_cols,
            display_rows,
        )

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
                if config.fit:
                    sequence = (
                        f"\x1b_Ga=T,f=32,s={width},v={height},c={display_cols},r={display_rows},m={m};{chunk}\x1b\\"
                    )
                else:
                    sequence = f"\x1b_Ga=T,f=32,s={width},v={height},m={m};{chunk}\x1b\\"
            else:
                sequence = f"\x1b_Gm={m};{chunk}\x1b\\"

            if should_wrap:
                sequence = _tmux_wrap(sequence)

            payloads.append(sequence)

        yield "".join(payloads)


class ITerm2Renderer:
    """iTerm2 终端图形协议渲染器."""

    def render(self, payload: list[list[bool]] | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
        """根据 iTerm2 内联图像协议渲染矩阵或图像."""
        if isinstance(payload, SimpleImage):
            image = payload.copy().convert("RGB")
        else:
            image = _matrix_to_image(payload, config.scale, "RGB")
        plan = _build_fit_plan(config, image.width, image.height)
        image = _resize_image_to_cols(
            image,
            plan.display_cols,
            allow_upscale=True,
        )
        image.thumbnail((800, 800))
        width_cells = min(plan.display_cols, image.width) if config.fit else "auto"
        logger.debug(
            "iTerm2 rendering image: target_size=%sx%s, fit=%s display_cols=%s",
            image.width,
            image.height,
            config.fit,
            plan.display_cols,
        )

        png_data = image.to_png_bytes()
        b64_data = base64.b64encode(png_data).decode("ascii")
        payload_seq = f"\x1b]1337;File=inline=1;width={width_cells};height=auto:{b64_data}\x07"

        if _should_tmux_wrap(config):
            yield _tmux_wrap(payload_seq)
            return

        yield payload_seq


class WezTermRenderer(ITerm2Renderer):
    """WezTerm 终端图形协议渲染器 (基于 iTerm2 协议增强)."""

    def render(self, payload: list[list[bool]] | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
        """根据 WezTerm 增强型的 iTerm2 内联图像协议渲染."""
        if isinstance(payload, SimpleImage):
            image = payload.copy().convert("RGB")
        else:
            image = _matrix_to_image(payload, config.scale, "RGB")
        plan = _build_fit_plan(config, image.width, image.height)
        image = _resize_image_to_cols(
            image,
            plan.display_cols,
            allow_upscale=True,
        )
        image.thumbnail((1200, 1200))
        width_cells = min(plan.display_cols, image.width) if config.fit else "auto"
        logger.debug(
            "WezTerm rendering image: target_size=%sx%s, fit=%s display_cols=%s",
            image.width,
            image.height,
            config.fit,
            plan.display_cols,
        )

        png_data = image.to_png_bytes()
        b64_data = base64.b64encode(png_data).decode("ascii")
        payload_seq = f"\x1b]1337;File=inline=1;width={width_cells};height=auto;preserveAspectRatio=1:{b64_data}\x07"

        if _should_tmux_wrap(config):
            yield _tmux_wrap(payload_seq)
            return

        yield payload_seq


class SixelRenderer:
    """DEC Sixel 图形协议渲染器."""

    def render(self, payload: list[list[bool]] | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
        """根据 DEC Sixel 协议渲染矩阵或图像."""
        if isinstance(payload, SimpleImage):
            image = payload.copy()
            plan = _build_fit_plan(config, image.width, image.height)
            target_w_px, target_h_px = _cells_to_pixels(plan.display_cols, plan.display_rows)
            image = image.resize((target_w_px, target_h_px))
            image.thumbnail((800, 800))
            width, height = image.width, image.height
            bits = _threshold_to_bits(image, threshold=128)
            logger.debug("Sixel: using internal encoder, size=%sx%s", width, height)
        else:
            image = _matrix_to_image(payload, config.scale, "RGB").convert("L")
            plan = _build_fit_plan(config, image.width, image.height)
            target_w_px, target_h_px = _cells_to_pixels(plan.display_cols, plan.display_rows)
            image = image.resize((target_w_px, target_h_px))
            width, height = image.width, image.height
            bits = _threshold_to_bits(image, threshold=128)
            logger.debug("Sixel rendering (Matrix): %sx%s, scale=%s", width, height, config.scale)

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
