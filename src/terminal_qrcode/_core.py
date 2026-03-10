"""二维码渲染核心兼容模块."""

import dataclasses
from collections.abc import Generator
from typing import Any, cast

from ._contracts import (
    ColorLevelName,
    ImageInput,
    ImageProtocol,
    ImageSource,
    ImageWrapperProtocol,
    Matrix,
    MatrixSource,
    PixelMode,
    QRSource,
    RenderConfig,
    Renderer,
    RendererId,
    RenderRequest,
    TerminalCapabilities,
    TerminalCapability,
    TerminalColorLevel,
)
from ._layout import _pad_border
from ._qr_restore import strict_restore_qr_matrix
from ._renderers import (
    RendererRegistry,
    build_default_renderer_registry,
)
from ._simple_image import SimpleImage

DEFAULT_RENDERER_REGISTRY: RendererRegistry[Renderer] = build_default_renderer_registry()
_MODE_CHANNELS: dict[PixelMode, int] = {"L": 1, "RGB": 3, "RGBA": 4}


def _merge_config(config: RenderConfig | None, overrides: dict[str, object]) -> RenderConfig:
    """合并基础配置与扁平覆盖参数."""
    base = config or RenderConfig()
    cleaned = {k: v for k, v in overrides.items() if v is not None}
    if not cleaned:
        return base

    qr_fields = {"border", "finder_variance", "restore_window", "invert", "preserve_source"}
    layout_fields = {"fit", "max_cols", "img_width", "halfblock_mode"}
    probe_fields = {"renderer", "timeout", "color_level", "tmux_passthrough"}

    qr_overrides = {k: v for k, v in cleaned.items() if k in qr_fields}
    layout_overrides = {k: v for k, v in cleaned.items() if k in layout_fields}
    probe_overrides = {k: v for k, v in cleaned.items() if k in probe_fields}

    new_qr = dataclasses.replace(base.qr, **cast(dict[str, Any], qr_overrides)) if qr_overrides else base.qr
    new_layout = (
        dataclasses.replace(base.layout, **cast(dict[str, Any], layout_overrides)) if layout_overrides else base.layout
    )
    new_probe = (
        dataclasses.replace(base.probe, **cast(dict[str, Any], probe_overrides)) if probe_overrides else base.probe
    )

    return RenderConfig(qr=new_qr, layout=new_layout, probe=new_probe)


def _resolve_capability(config: RenderConfig) -> TerminalCapability:
    """解析最终渲染能力."""
    if config.probe.renderer != "auto":
        renderer = config.probe.renderer.lower()
        if renderer == "kitty":
            return TerminalCapability.KITTY
        if renderer == "wezterm":
            return TerminalCapability.WEZTERM
        if renderer == "sixel":
            return TerminalCapability.SIXEL
        if renderer == "iterm2":
            return TerminalCapability.ITERM2
        return TerminalCapability.FALLBACK

    from ._probe import TerminalProbe

    probe = TerminalProbe()
    return probe.probe(timeout=config.probe.timeout)


def _resolve_terminal_capabilities(config: RenderConfig) -> TerminalCapabilities:
    """解析最终终端能力快照."""
    if config.probe.renderer != "auto" and config.probe.color_level != "auto":
        capability = _resolve_capability(config)
        return TerminalCapabilities(
            capability=capability,
            color_level=TerminalColorLevel[config.probe.color_level.upper()],
            available_capabilities=(capability,),
        )

    from ._probe import TerminalProbe

    probe = TerminalProbe()
    if config.probe.renderer != "auto":
        capability = _resolve_capability(config)
        return TerminalCapabilities(
            capability=capability,
            color_level=probe.probe_color(timeout=config.probe.timeout),
            available_capabilities=(capability,),
        )
    if config.probe.color_level != "auto":
        capabilities = probe.probe_available_capabilities(timeout=config.probe.timeout)
        capability = capabilities[0] if capabilities else TerminalCapability.FALLBACK
        return TerminalCapabilities(
            capability=capability,
            color_level=TerminalColorLevel[config.probe.color_level.upper()],
            available_capabilities=capabilities,
        )
    return probe.capabilities(timeout=config.probe.timeout)


def _validate_config(config: RenderConfig) -> None:
    """验证关键渲染配置的合法性."""
    if config.layout.img_width is not None and config.layout.img_width <= 0:
        raise ValueError("img_width must be greater than 0.")
    if config.layout.max_cols is not None and config.layout.max_cols <= 0:
        raise ValueError("max_cols must be greater than 0 when provided.")
    if config.probe.renderer not in {"auto", "kitty", "iterm2", "wezterm", "sixel", "halfblock"}:
        raise ValueError("renderer must be one of: auto, kitty, iterm2, wezterm, sixel, halfblock.")
    if config.qr.border < 0:
        raise ValueError("border must be >= 0.")
    if config.qr.finder_variance <= 0:
        raise ValueError("finder_variance must be greater than 0.")
    if config.qr.restore_window < 1 or config.qr.restore_window % 2 == 0:
        raise ValueError("restore_window must be an odd integer greater than or equal to 1.")


def _to_simple_image(payload: ImageInput) -> SimpleImage:
    """将图像输入归一化为 SimpleImage."""
    if isinstance(payload, list):
        raise TypeError("payload must be an image input when converting to SimpleImage.")
    if isinstance(payload, SimpleImage):
        return payload
    if not isinstance(payload, ImageProtocol):
        payload = _unwrap_image_payload(payload)
    if isinstance(payload, SimpleImage):
        return payload

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


def _unwrap_image_payload(payload: ImageInput) -> SimpleImage | ImageProtocol:
    """解包包装图像对象."""
    if isinstance(payload, SimpleImage):
        return payload
    if isinstance(payload, ImageProtocol):
        return payload
    if isinstance(payload, ImageWrapperProtocol):
        inner = payload.get_image()
        if isinstance(inner, SimpleImage):
            return inner
        if isinstance(inner, ImageProtocol):
            return inner
        raise TypeError("payload get_image() must return a SimpleImage or ImageProtocol instance.")
    raise TypeError("payload must be a SimpleImage, ImageProtocol, or image wrapper instance.")


def _validate_matrix_shape(matrix: Matrix) -> None:
    """验证布尔矩阵输入的合法性."""
    if not matrix:
        raise TypeError("payload matrix must not be empty.")
    width = len(matrix[0])
    if width <= 0:
        raise TypeError("payload matrix rows must not be empty.")
    if len(matrix) != width:
        raise TypeError("payload matrix must be a square QR matrix.")
    for row in matrix:
        if len(row) != width:
            raise TypeError("payload matrix rows must have consistent width.")
        for cell in row:
            if type(cell) is not bool:
                raise TypeError("payload matrix cells must be bool values.")


def _to_render_matrix(payload: ImageInput, config: RenderConfig) -> Matrix:
    """将输入统一转换为渲染矩阵."""
    if isinstance(payload, list):
        _validate_matrix_shape(payload)
        return [list(row) for row in payload]

    image = _to_simple_image(payload)
    matrix = _restore_qr_matrix(image, config)
    if matrix is None:
        raise ValueError("Failed to decode QR matrix from image. Input must be a valid machine-generated QR code.")
    return _pad_border(matrix, config.qr.border)


def _restore_qr_matrix(image: SimpleImage, config: RenderConfig) -> Matrix | None:
    """恢复二维码矩阵（使用严格模式）."""
    return strict_restore_qr_matrix(image, config)


def _coerce_color_level(level: TerminalColorLevel) -> ColorLevelName:
    """将探测颜色等级转换为配置字面量."""
    if level is TerminalColorLevel.TRUECOLOR:
        return "truecolor"
    if level is TerminalColorLevel.ANSI256:
        return "ansi256"
    if level is TerminalColorLevel.ANSI16:
        return "ansi16"
    return "none"


def _normalize_request(
    payload: ImageInput,
    *,
    source: str,
    config: RenderConfig | None = None,
    overrides: dict[str, object] | None = None,
) -> RenderRequest:
    """构建统一渲染请求."""
    final_config = _merge_config(config, overrides or {})
    return RenderRequest(payload=payload, config=final_config, source=source)


def _resolve_qr_source(request: RenderRequest, capability: TerminalCapability) -> QRSource:
    """根据请求和终端能力解析最终渲染源."""
    payload = request.payload
    config = request.config

    if isinstance(payload, list):
        _validate_matrix_shape(payload)
        return MatrixSource(matrix=_pad_border([list(row) for row in payload], config.qr.border))

    image_payload = _to_simple_image(payload)
    matrix = _restore_qr_matrix(image_payload, config)
    if matrix is None:
        raise ValueError("Failed to decode QR matrix from image. Input must be a valid machine-generated QR code.")

    # 图形终端策略
    if capability in {
        TerminalCapability.KITTY,
        TerminalCapability.ITERM2,
        TerminalCapability.WEZTERM,
        TerminalCapability.SIXEL,
    }:
        if config.qr.preserve_source:
            if config.qr.invert is True:
                raise ValueError(
                    "invert=True is not supported when preserve_source=True uses original image passthrough."
                )
            return ImageSource(image=image_payload, is_original=True)

        # 默认返回补边矩阵源，由渲染器执行规范化重绘
        return MatrixSource(matrix=_pad_border(matrix, config.qr.border))

    # 降级终端策略：强制使用矩阵源以确保 HalfBlock 能正确渲染
    return MatrixSource(matrix=_pad_border(matrix, config.qr.border))


def run_pipeline(request: RenderRequest) -> Generator[str, None, None]:
    """执行完整的探测与渲染管线."""
    final_config = request.config
    _validate_config(final_config)
    terminal_capabilities = _resolve_terminal_capabilities(final_config)
    capability = terminal_capabilities.capability
    final_color_level = _coerce_color_level(terminal_capabilities.color_level)

    # 合并探测到的颜色等级
    new_probe = dataclasses.replace(final_config.probe, color_level=final_color_level)
    final_config = dataclasses.replace(final_config, probe=new_probe)
    request = dataclasses.replace(request, config=final_config)

    # 解析数据源与渲染器
    qr_source = _resolve_qr_source(request, capability)
    registry = DEFAULT_RENDERER_REGISTRY

    if final_config.probe.renderer != "auto":
        try:
            renderer_id = RendererId(final_config.probe.renderer.lower())
        except ValueError:
            renderer_id = RendererId.HALFBLOCK
        renderer = registry.get(renderer_id)
    else:
        available_capabilities = terminal_capabilities.available_capabilities or (capability,)
        renderer = registry.select_renderer(list(available_capabilities))

    yield from renderer.render(qr_source, final_config)


__all__ = [
    "RenderConfig",
    "Renderer",
    "RendererId",
    "QRSource",
    "MatrixSource",
    "ImageSource",
    "TerminalCapability",
    "run_pipeline",
    "RendererRegistry",
    "DEFAULT_RENDERER_REGISTRY",
]
