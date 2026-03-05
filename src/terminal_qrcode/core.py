"""二维码渲染核心兼容模块."""

import dataclasses
import logging
from collections.abc import Generator
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, cast

from terminal_qrcode.contracts import (
    ColorLevelName,
    ImageInput,
    ImageProtocol,
    RenderConfig,
    Renderer,
    TerminalCapability,
    TerminalColorLevel,
)
from terminal_qrcode.renderers import (
    RendererRegistry,
    build_default_renderer_registry,
)
from terminal_qrcode.simple_image import SimpleImage

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from terminal_qrcode._cimage import PixelMode
else:
    PixelMode: TypeAlias = Literal["L", "RGB", "RGBA"]

DEFAULT_RENDERER_REGISTRY: RendererRegistry[Renderer] = build_default_renderer_registry()
_MODE_CHANNELS: dict[PixelMode, int] = {"L": 1, "RGB": 3, "RGBA": 4}


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


def _resolve_color_level(config: RenderConfig) -> ColorLevelName:
    """解析最终文本颜色等级（auto 时走终端探测）."""
    if config.color_level != "auto":
        return config.color_level

    # 延迟导入，避免与 probe.py 形成模块初始化循环。
    from terminal_qrcode.probe import TerminalProbe

    probe = TerminalProbe()
    level = probe.probe_color(timeout=config.timeout)
    if level is TerminalColorLevel.TRUECOLOR:
        return "truecolor"
    if level is TerminalColorLevel.ANSI256:
        return "ansi256"
    if level is TerminalColorLevel.ANSI16:
        return "ansi16"
    return "none"


def _validate_config(config: RenderConfig) -> None:
    """验证关键渲染配置的合法性."""
    if config.img_width is not None and config.img_width <= 0:
        raise ValueError("img_width must be greater than 0.")
    if config.max_cols is not None and config.max_cols <= 0:
        raise ValueError("max_cols must be greater than 0 when provided.")
    if config.color_level not in {"auto", "none", "ansi16", "ansi256", "truecolor"}:
        raise ValueError("color_level must be one of: auto, none, ansi16, ansi256, truecolor.")


def _to_simple_image(payload: ImageInput) -> SimpleImage:
    """将输入图像归一化为 SimpleImage."""
    if isinstance(payload, SimpleImage):
        return payload
    if not isinstance(payload, ImageProtocol):
        raise TypeError("payload must be a SimpleImage or ImageProtocol instance.")

    image_obj: ImageProtocol = payload
    mode_raw = image_obj.mode
    if mode_raw not in _MODE_CHANNELS:
        image_obj = image_obj.convert("RGBA")
        mode_raw = image_obj.mode

    if mode_raw not in _MODE_CHANNELS:
        raise TypeError("payload image mode must be one of: L, RGB, RGBA.")
    mode = cast(PixelMode, mode_raw)

    width, height = image_obj.size
    if width <= 0 or height <= 0:
        raise TypeError("payload image size must be positive.")

    data = image_obj.tobytes()
    expected = width * height * _MODE_CHANNELS[mode]
    if len(data) != expected:
        raise TypeError("payload image bytes length does not match size and mode.")

    return SimpleImage(mode, (width, height), data)


def run_pipeline(
    payload: ImageInput,
    config: RenderConfig | None = None,
    *,
    overrides: dict[str, object] | None = None,
) -> Generator[str, None, None]:
    """执行从输入到渲染输出的完整编排流程."""
    final_config = _merge_config(config, overrides or {})
    _validate_config(final_config)
    final_color_level = _resolve_color_level(final_config)
    final_config = dataclasses.replace(final_config, color_level=final_color_level)
    render_payload = _to_simple_image(payload)
    capability = _resolve_capability(final_config)
    logger.debug("Selected capability: %s", capability.name)
    renderer = DEFAULT_RENDERER_REGISTRY.get(capability)
    yield from renderer.render(render_payload, final_config)


__all__ = [
    "RenderConfig",
    "Renderer",
    "TerminalCapability",
    "run_pipeline",
    "RendererRegistry",
    "DEFAULT_RENDERER_REGISTRY",
]
