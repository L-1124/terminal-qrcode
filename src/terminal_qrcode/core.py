"""二维码渲染核心兼容模块."""

import dataclasses
from collections.abc import Generator
from types import ModuleType
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, cast

from terminal_qrcode.contracts import (
    ColorLevelName,
    ImageInput,
    ImageProtocol,
    Matrix,
    RenderConfig,
    Renderer,
    RenderRequest,
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
    if config.renderer != "auto":
        renderer = config.renderer.lower()
        if renderer == "kitty":
            return TerminalCapability.KITTY
        if renderer == "wezterm":
            return TerminalCapability.WEZTERM
        if renderer == "sixel":
            return TerminalCapability.SIXEL
        if renderer == "iterm2":
            return TerminalCapability.ITERM2
        return TerminalCapability.FALLBACK

    # 延迟导入，避免与 probe.py 形成模块初始化循环。
    from terminal_qrcode.probe import TerminalProbe

    probe = TerminalProbe()
    return probe.probe(timeout=config.timeout)


def _resolve_terminal_capabilities(config: RenderConfig) -> TerminalCapabilities:
    """解析最终终端能力快照."""
    if config.renderer != "auto" and config.color_level != "auto":
        return TerminalCapabilities(
            capability=_resolve_capability(config),
            color_level=TerminalColorLevel[config.color_level.upper()],
        )

    from terminal_qrcode.probe import TerminalProbe

    probe = TerminalProbe()
    if config.renderer != "auto":
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
    if config.renderer not in {"auto", "kitty", "iterm2", "wezterm", "sixel", "halfblock"}:
        raise ValueError("renderer must be one of: auto, kitty, iterm2, wezterm, sixel, halfblock.")
    if config.repair not in {"off", "best_effort", "strict"}:
        raise ValueError("repair must be one of: off, best_effort, strict.")
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
    matrix = _restore_qr_matrix(image, config)
    if matrix is None:
        raise ValueError("Failed to decode QR matrix from image. Input must be a valid machine-generated QR code.")
    return _pad_border(matrix, config.border)


def _restore_qr_matrix(image: SimpleImage, config: RenderConfig) -> Matrix | None:
    """根据 repair 策略恢复二维码矩阵."""
    repair = config.repair
    if repair == "off":
        return strict_restore_qr_matrix(image, config)
    if repair == "best_effort":
        # 当前版本仅预留 best_effort 语义，暂与 strict 共用严格恢复路径。
        return strict_restore_qr_matrix(image, config)
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


def _resolve_render_payload(request: RenderRequest, capability: TerminalCapability) -> Matrix | SimpleImage:
    """根据请求和终端能力解析最终渲染载荷."""
    payload = request.payload
    config = request.config
    if capability in {
        TerminalCapability.KITTY,
        TerminalCapability.ITERM2,
        TerminalCapability.WEZTERM,
        TerminalCapability.SIXEL,
    } and not isinstance(payload, list):
        image_payload = _to_simple_image(payload)
        if _restore_qr_matrix(image_payload, config) is None:
            raise ValueError("Failed to decode QR matrix from image. Input must be a valid machine-generated QR code.")
        return image_payload
    return _to_render_matrix(payload, config)


def decode_request_to_matrix(
    request: RenderRequest,
    *,
    qrcode_module: ModuleType,
    pyzbar_module: ModuleType,
) -> Matrix:
    """先解码二维码内容，再重建二维码矩阵."""
    payload = request.payload
    image = payload if isinstance(payload, SimpleImage) else _to_simple_image(payload)
    luma = image if image.mode == "L" else image.convert("L")
    decoded = pyzbar_module.decode((bytes(luma._data), luma.width, luma.height))
    if not decoded:
        raise ValueError("Failed to decode QR payload from image.")

    result = None
    for item in decoded:
        kind = str(getattr(item, "type", "")).upper()
        if kind in {"", "QRCODE"}:
            result = item
            break
    if result is None:
        raise ValueError("Decoded symbols do not contain a QRCode payload.")

    qr = qrcode_module.QRCode(
        version=None,
        error_correction=qrcode_module.constants.ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    qr.add_data(getattr(result, "data", b""))
    qr.make(fit=True)
    return [list(row) for row in qr.get_matrix()]


def run_pipeline(request: RenderRequest) -> Generator[str, None, None]:
    """执行从输入到渲染输出的完整编排流程."""
    final_config = request.config
    _validate_config(final_config)
    terminal_capabilities = _resolve_terminal_capabilities(final_config)
    capability = terminal_capabilities.capability
    final_color_level = _coerce_color_level(terminal_capabilities.color_level)
    final_config = dataclasses.replace(final_config, color_level=final_color_level)
    request = dataclasses.replace(request, config=final_config)
    render_payload = _resolve_render_payload(request, capability)
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
