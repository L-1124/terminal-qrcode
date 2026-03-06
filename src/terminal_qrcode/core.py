"""二维码渲染核心兼容模块."""

import dataclasses
from collections.abc import Generator
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, cast

from terminal_qrcode.contracts import (
    ColorLevelName,
    ImageInput,
    ImageProtocol,
    Matrix,
    RenderConfig,
    Renderer,
    TerminalCapabilities,
    TerminalCapability,
    TerminalColorLevel,
)
from terminal_qrcode.layout import _pad_border
from terminal_qrcode.qr_restore import strict_restore_qr_matrix
from terminal_qrcode.renderers import (
    RendererRegistry,
    build_default_renderer_registry,
)
from terminal_qrcode.simple_image import SimpleImage

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


def _resolve_terminal_capabilities(config: RenderConfig) -> TerminalCapabilities:
    """解析最终终端能力快照."""
    if config.force_renderer and config.color_level != "auto":
        return TerminalCapabilities(
            capability=_resolve_capability(config),
            color_level=TerminalColorLevel[config.color_level.upper()],
        )

    from terminal_qrcode.probe import TerminalProbe

    probe = TerminalProbe()
    if config.force_renderer:
        return TerminalCapabilities(
            capability=_resolve_capability(config),
            color_level=probe.probe_color(timeout=config.timeout),
        )
    if config.color_level != "auto":
        return TerminalCapabilities(
            capability=probe.probe(timeout=config.timeout),
            color_level=TerminalColorLevel[config.color_level.upper()],
        )
    return probe.capabilities(timeout=config.timeout)


def _validate_config(config: RenderConfig) -> None:
    """验证关键渲染配置的合法性."""
    if config.img_width is not None and config.img_width <= 0:
        raise ValueError("img_width must be greater than 0.")
    if config.max_cols is not None and config.max_cols <= 0:
        raise ValueError("max_cols must be greater than 0 when provided.")
    if config.color_level not in {"auto", "none", "ansi16", "ansi256", "truecolor"}:
        raise ValueError("color_level must be one of: auto, none, ansi16, ansi256, truecolor.")
    if config.border < 0:
        raise ValueError("border must be >= 0.")
    if config.finder_variance <= 0:
        raise ValueError("finder_variance must be greater than 0.")
    if config.restore_window < 1 or config.restore_window % 2 == 0:
        raise ValueError("restore_window must be an odd integer greater than or equal to 1.")


def _to_simple_image(payload: ImageInput) -> SimpleImage:
    """将图像输入归一化为 SimpleImage."""
    if isinstance(payload, list):
        raise TypeError("payload must be an image input when converting to SimpleImage.")
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


def _validate_matrix_shape(matrix: Matrix) -> None:
    """验证布尔矩阵输入的合法性."""
    if not matrix:
        raise TypeError("payload matrix must not be empty.")
    width = len(matrix[0])
    if width <= 0:
        raise TypeError("payload matrix rows must not be empty.")
    for row in matrix:
        if len(row) != width:
            raise TypeError("payload matrix rows must have consistent width.")


def _to_render_matrix(payload: ImageInput, config: RenderConfig) -> Matrix:
    """将输入统一转换为渲染矩阵."""
    if isinstance(payload, list):
        _validate_matrix_shape(payload)
        return [list(row) for row in payload]

    image = _to_simple_image(payload)
    matrix = strict_restore_qr_matrix(image, config)
    if matrix is None:
        raise ValueError("Failed to decode QR matrix from image. Input must be a valid machine-generated QR code.")
    return _pad_border(matrix, config.border)


def run_pipeline(
    payload: ImageInput,
    config: RenderConfig | None = None,
    *,
    overrides: dict[str, object] | None = None,
) -> Generator[str, None, None]:
    """执行从输入到渲染输出的完整编排流程."""
    final_config = _merge_config(config, overrides or {})
    _validate_config(final_config)
    terminal_capabilities = _resolve_terminal_capabilities(final_config)
    capability = terminal_capabilities.capability
    color_level = terminal_capabilities.color_level
    if color_level is TerminalColorLevel.TRUECOLOR:
        final_color_level = "truecolor"
    elif color_level is TerminalColorLevel.ANSI256:
        final_color_level = "ansi256"
    elif color_level is TerminalColorLevel.ANSI16:
        final_color_level = "ansi16"
    else:
        final_color_level = "none"
    final_config = dataclasses.replace(final_config, color_level=final_color_level)
    if capability in {
        TerminalCapability.KITTY,
        TerminalCapability.ITERM2,
        TerminalCapability.WEZTERM,
        TerminalCapability.SIXEL,
    } and not isinstance(payload, list):
        image_payload = _to_simple_image(payload)
        if strict_restore_qr_matrix(image_payload, final_config) is None:
            raise ValueError("Failed to decode QR matrix from image. Input must be a valid machine-generated QR code.")
        render_payload: Matrix | SimpleImage = image_payload
    else:
        render_payload = _to_render_matrix(payload, final_config)
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
