"""二维码渲染核心兼容模块."""

import dataclasses
import logging
from collections.abc import Generator
from typing import Any, cast

from terminal_qrcode.contracts import (
    ImageInput,
    ImageProtocol,
    RenderConfig,
    Renderer,
    TerminalCapability,
)
from terminal_qrcode.renderers import (
    HalfBlockRenderer,
    ITerm2Renderer,
    KittyRenderer,
    RendererRegistry,
    SixelRenderer,
    WezTermRenderer,
    _matrix_to_image,
    _should_tmux_wrap,
    _sixel_encode_mono,
    _threshold_to_bits,
    _tmux_allow_passthrough,
    _tmux_wrap,
    build_default_renderer_registry,
)
from terminal_qrcode.simple_image import SimpleImage

logger = logging.getLogger(__name__)

DEFAULT_RENDERER_REGISTRY: RendererRegistry[Renderer] = build_default_renderer_registry()
_MODE_CHANNELS: dict[str, int] = {"L": 1, "RGB": 3, "RGBA": 4}


class RendererFactory:
    """渲染器工厂."""

    @staticmethod
    def get_renderer(cap: TerminalCapability) -> Renderer:
        """根据终端能力返回对应的渲染器实例."""
        return DEFAULT_RENDERER_REGISTRY.get(cap)


def _merge_config(config: RenderConfig | None, overrides: dict[str, object]) -> RenderConfig:
    """合并基础配置与扁平覆盖参数."""
    base_config = config or RenderConfig()
    cleaned = {k: v for k, v in overrides.items() if v is not None}
    if not cleaned:
        return base_config
    return dataclasses.replace(base_config, **cast(dict[str, Any], cleaned))


def _resolve_capability(config: RenderConfig) -> TerminalCapability:
    """解析最终渲染能力."""
    if config.force_renderer:
        force_str = config.force_renderer.lower()
        if force_str == "kitty":
            return TerminalCapability.KITTY
        if force_str == "wezterm":
            return TerminalCapability.WEZTERM
        if force_str == "sixel":
            return TerminalCapability.SIXEL
        if force_str == "iterm2":
            return TerminalCapability.ITERM2
        return TerminalCapability.FALLBACK

    # 延迟导入，避免与 probe.py 形成模块初始化循环。
    from terminal_qrcode.probe import TerminalProbe

    probe = TerminalProbe()
    return probe.probe(timeout=config.timeout)


def _validate_config(config: RenderConfig) -> None:
    """验证关键渲染配置的合法性."""
    if config.img_width is not None and config.img_width <= 0:
        raise ValueError("img_width must be greater than 0.")
    if config.max_cols is not None and config.max_cols <= 0:
        raise ValueError("max_cols must be greater than 0 when provided.")


def _to_simple_image(payload: ImageInput) -> SimpleImage:
    """将输入图像归一化为 SimpleImage."""
    if isinstance(payload, SimpleImage):
        return payload
    if not isinstance(payload, ImageProtocol):
        raise TypeError("payload must be a SimpleImage or ImageProtocol instance.")

    image_obj: ImageProtocol = payload
    mode = image_obj.mode
    if mode not in _MODE_CHANNELS:
        image_obj = image_obj.convert("RGBA")
        mode = image_obj.mode

    if mode not in _MODE_CHANNELS:
        raise TypeError("payload image mode must be one of: L, RGB, RGBA.")

    width, height = image_obj.size
    if width <= 0 or height <= 0:
        raise TypeError("payload image size must be positive.")

    data = image_obj.tobytes()
    expected = width * height * _MODE_CHANNELS[mode]
    if len(data) != expected:
        raise TypeError("payload image bytes length does not match size and mode.")

    return SimpleImage(mode, (width, height), data)


def _normalize_payload(payload: ImageInput, config: RenderConfig) -> list[list[bool]] | SimpleImage:
    """规范化输入载荷为渲染图像."""
    _ = config
    return _to_simple_image(payload)


def run_pipeline(
    payload: ImageInput,
    config: RenderConfig | None = None,
    *,
    overrides: dict[str, object] | None = None,
) -> Generator[str, None, None]:
    """执行从输入到渲染输出的完整编排流程."""
    final_config = _merge_config(config, overrides or {})
    _validate_config(final_config)
    render_payload = _normalize_payload(payload, final_config)
    capability = _resolve_capability(final_config)
    logger.debug("Selected capability: %s", capability.name)
    renderer = RendererFactory.get_renderer(capability)
    yield from renderer.render(render_payload, final_config)


__all__ = [
    "RenderConfig",
    "Renderer",
    "TerminalCapability",
    "RendererFactory",
    "run_pipeline",
    "HalfBlockRenderer",
    "KittyRenderer",
    "ITerm2Renderer",
    "WezTermRenderer",
    "SixelRenderer",
    "RendererRegistry",
    "DEFAULT_RENDERER_REGISTRY",
    "_matrix_to_image",
    "_threshold_to_bits",
    "_sixel_encode_mono",
    "_tmux_allow_passthrough",
    "_should_tmux_wrap",
    "_tmux_wrap",
]
