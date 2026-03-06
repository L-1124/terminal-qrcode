"""终端二维码渲染库."""

import importlib
from collections.abc import Iterable, Iterator
from pathlib import Path
from types import ModuleType
from typing import overload

from terminal_qrcode import core
from terminal_qrcode.contracts import (
    ColorLevelName,
    HalfBlockMode,
    ImageInput,
    Matrix,
    RendererOption,
    RepairMode,
)
from terminal_qrcode.simple_image import SimpleImage

_UNSET = object()

_qrcode: ModuleType | None | object = _UNSET
_pyzbar: ModuleType | None | object = _UNSET

__version__ = "0.1.1"


__all__ = [
    "SimpleImage",
    "DrawOutput",
    "decode_and_redraw",
    "draw",
    "generate",
]


def _load_qrcode() -> ModuleType | None:
    """按需加载 qrcode 可选依赖."""
    global _qrcode
    if _qrcode is _UNSET:
        try:
            _qrcode = importlib.import_module("qrcode")
        except ImportError:
            _qrcode = None
    if isinstance(_qrcode, ModuleType):
        return _qrcode
    return None


def _load_pyzbar() -> ModuleType | None:
    """按需加载 pyzbar 可选依赖."""
    global _pyzbar
    if _pyzbar is _UNSET:
        try:
            _pyzbar = importlib.import_module("pyzbar.pyzbar")
        except ImportError:
            _pyzbar = None
    if isinstance(_pyzbar, ModuleType):
        return _pyzbar
    return None


def _build_overrides(
    *,
    renderer: RendererOption | None,
    repair: RepairMode | None,
    invert: bool | None,
    color_level: ColorLevelName | None,
    fit: bool | None,
    max_cols: int | None,
    img_width: int | None,
    halfblock_mode: HalfBlockMode | None,
    tmux_passthrough: str | None,
    border: int | None = None,
) -> dict[str, object]:
    """构建渲染覆盖参数字典."""
    return {
        "renderer": renderer,
        "repair": repair,
        "invert": invert,
        "color_level": color_level,
        "fit": fit,
        "max_cols": max_cols,
        "img_width": img_width,
        "halfblock_mode": halfblock_mode,
        "tmux_passthrough": tmux_passthrough,
        "border": border,
    }


class DrawOutput:
    """`draw` 的包装结果，支持迭代与直接字符串输出."""

    def __init__(self, chunks: Iterable[str]) -> None:
        """初始化输出包装器."""
        self._source: Iterator[str] = iter(chunks)
        self._cache: list[str] = []
        self._exhausted = False

    def _drain(self) -> None:
        """消费剩余分片并缓存."""
        if self._exhausted:
            return
        for chunk in self._source:
            self._cache.append(chunk)
        self._exhausted = True

    def __iter__(self) -> Iterator[str]:
        """按块迭代输出，已消费内容可重复读取."""
        idx = 0
        while True:
            while idx < len(self._cache):
                yield self._cache[idx]
                idx += 1
            if self._exhausted:
                return
            try:
                chunk = next(self._source)
            except StopIteration:
                self._exhausted = True
                return
            self._cache.append(chunk)
            idx += 1
            yield chunk

    def __str__(self) -> str:
        """返回完整输出字符串."""
        self._drain()
        return "".join(self._cache)

    def __repr__(self) -> str:
        """调试表示."""
        return f"DrawOutput(exhausted={self._exhausted}, cached_chunks={len(self._cache)})"


@overload
def draw(
    payload: ImageInput,
    *,
    renderer: RendererOption = "auto",
    repair: RepairMode = "off",
    invert: bool | None = None,
    color_level: ColorLevelName | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    halfblock_mode: HalfBlockMode | None = None,
    tmux_passthrough: str | None = None,
    border: int | None = None,
) -> DrawOutput: ...


@overload
def draw(
    payload: str | Path,
    *,
    renderer: RendererOption = "auto",
    repair: RepairMode = "off",
    invert: bool | None = None,
    color_level: ColorLevelName | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    halfblock_mode: HalfBlockMode | None = None,
    tmux_passthrough: str | None = None,
    border: int | None = None,
) -> DrawOutput: ...


@overload
def draw(
    payload: bytes | bytearray,
    *,
    renderer: RendererOption = "auto",
    repair: RepairMode = "off",
    invert: bool | None = None,
    color_level: ColorLevelName | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    halfblock_mode: HalfBlockMode | None = None,
    tmux_passthrough: str | None = None,
    border: int | None = None,
) -> DrawOutput: ...


def draw(
    payload: ImageInput | str | Path | bytes | bytearray,
    *,
    renderer: RendererOption = "auto",
    repair: RepairMode = "off",
    invert: bool | None = None,
    color_level: ColorLevelName | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    halfblock_mode: HalfBlockMode | None = None,
    tmux_passthrough: str | None = None,
    border: int | None = None,
) -> DrawOutput:
    """
    探测终端并生成及分片产出二维码渲染流.

    Args:
        payload: 图像对象或本地图片路径（str/Path）.
        renderer: 渲染器类型（auto/kitty/iterm2/wezterm/sixel/halfblock）.
        repair: 修复策略（off/best_effort/strict）.
        invert: 是否反转颜色.
        color_level: 文本颜色等级(auto/none/ansi16/ansi256/truecolor).
        fit: 是否按终端列宽自动收束.
        max_cols: 最大列宽上限.
        img_width: 渲染宽度（fit=True 时仅显式指定才作为额外上限，fit=False 时未指定默认 40）.
        halfblock_mode: halfblock 严格路径策略（precision/area）.
        tmux_passthrough: tmux 穿透策略(auto/always/never).
        border: halfblock 渲染时矩阵边距模块数（默认 2）.

    Returns:
        支持分片迭代与直接字符串输出的包装对象.

    Examples:
        直接输出完整结果:

        >>> from terminal_qrcode import draw
        >>> print(draw("qrcode.png"))

        以分片流式处理输出:

        >>> out = draw("qrcode.png", renderer="halfblock")
        >>> for chunk in out:
        ...     _ = chunk

        从内存字节输入:

        >>> png_bytes = b"..."
        >>> text = str(draw(png_bytes, renderer="halfblock"))

    """
    if isinstance(payload, (str, Path)):
        payload = SimpleImage.open(payload)
        source = "path"
    elif isinstance(payload, (bytes, bytearray)):
        payload = SimpleImage.from_bytes(payload)
        source = "bytes"
    elif isinstance(payload, list):
        source = "matrix"
    else:
        source = "image"

    overrides = _build_overrides(
        renderer=renderer,
        repair=repair,
        invert=invert,
        color_level=color_level,
        fit=fit,
        max_cols=max_cols,
        img_width=img_width,
        halfblock_mode=halfblock_mode,
        tmux_passthrough=tmux_passthrough,
        border=border,
    )
    request = core._normalize_request(payload, source=source, overrides=overrides)
    return DrawOutput(core.run_pipeline(request))


def decode_and_redraw(payload: ImageInput | str | Path | bytes | bytearray) -> Matrix:
    """先尝试解码二维码内容，再重建二维码矩阵."""
    qrcode_mod = _load_qrcode()
    pyzbar_mod = _load_pyzbar()
    if qrcode_mod is None or pyzbar_mod is None:
        raise RuntimeError("decode_and_redraw requires optional dependency group [pyzbar].")

    image_input = payload
    if isinstance(image_input, (str, Path)):
        image_input = SimpleImage.open(image_input)
        source = "path"
    elif isinstance(image_input, (bytes, bytearray)):
        image_input = SimpleImage.from_bytes(image_input)
        source = "bytes"
    elif isinstance(image_input, list):
        source = "matrix"
    else:
        source = "image"

    request = core._normalize_request(image_input, source=source)
    return core.decode_request_to_matrix(request, qrcode_module=qrcode_mod, pyzbar_module=pyzbar_mod)


def generate(
    data: str,
    *,
    ec_level: str = "M",
    border: int = 2,
    renderer: RendererOption = "auto",
    repair: RepairMode = "off",
    invert: bool | None = None,
    color_level: ColorLevelName | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    halfblock_mode: HalfBlockMode | None = None,
    tmux_passthrough: str | None = None,
) -> DrawOutput:
    """
    生成二维码并按现有渲染管线输出.

    Args:
        data: 二维码内容.
        ec_level: 容错级别（L/M/Q/H）.
        border: 二维码边距（模块数）.
        renderer: 渲染器类型（auto/kitty/iterm2/wezterm/sixel/halfblock）.
        repair: 修复策略（off/best_effort/strict）.
        invert: 是否反转颜色.
        color_level: 文本颜色等级(auto/none/ansi16/ansi256/truecolor).
        fit: 是否按终端列宽自动收束.
        max_cols: 最大列宽上限.
        img_width: 渲染宽度（fit=True 时仅显式指定才作为额外上限，fit=False 时未指定默认 40）.
        halfblock_mode: halfblock 严格路径策略（precision/area）.
        tmux_passthrough: tmux 穿透策略(auto/always/never).

    Returns:
        支持分片迭代与直接字符串输出的包装对象.

    Raises:
        RuntimeError: 未安装 qrcode 依赖时抛出.
        ValueError: 参数非法时抛出.

    """
    qrcode_mod = _load_qrcode()
    if qrcode_mod is None:
        raise RuntimeError("qrcode dependency is required. Please install terminal-qrcode[qr].")
    if border < 0:
        raise ValueError("border must be >= 0")

    ec_map = {
        "L": qrcode_mod.constants.ERROR_CORRECT_L,
        "M": qrcode_mod.constants.ERROR_CORRECT_M,
        "Q": qrcode_mod.constants.ERROR_CORRECT_Q,
        "H": qrcode_mod.constants.ERROR_CORRECT_H,
    }
    level = ec_level.upper()
    if level not in ec_map:
        raise ValueError("ec_level must be one of: L, M, Q, H")

    qr = qrcode_mod.QRCode(
        version=None,
        error_correction=ec_map[level],
        box_size=1,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    payload = [list(row) for row in qr.get_matrix()]

    overrides = _build_overrides(
        renderer=renderer,
        repair=repair,
        invert=invert,
        color_level=color_level,
        fit=fit,
        max_cols=max_cols,
        img_width=img_width,
        halfblock_mode=halfblock_mode,
        tmux_passthrough=tmux_passthrough,
    )
    request = core._normalize_request(payload, source="generated_matrix", overrides=overrides)
    return DrawOutput(core.run_pipeline(request))
