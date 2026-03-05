"""终端二维码渲染库."""

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, overload

from terminal_qrcode import core
from terminal_qrcode.contracts import ColorLevelName, HalfBlockMode, ImageInput, RendererName
from terminal_qrcode.simple_image import SimpleImage

try:
    import qrcode as _qrcode
except ImportError:
    _qrcode = None

qrcode: Any | None = _qrcode
try:
    from pyzbar import pyzbar as _pyzarb
except ImportError:
    _pyzarb = None

pyzarb: Any | None = _pyzarb

__version__ = "0.1.1"


__all__ = [
    "SimpleImage",
    "DrawOutput",
    "decode_and_redraw",
    "draw",
    "generate",
]


def _build_overrides(
    *,
    force_renderer: RendererName | None,
    invert: bool | None,
    color_level: ColorLevelName | None,
    fit: bool | None,
    max_cols: int | None,
    img_width: int | None,
    halfblock_mode: HalfBlockMode | None,
    tmux_passthrough: str | None,
) -> dict[str, object]:
    """构建渲染覆盖参数字典."""
    return {
        "force_renderer": force_renderer,
        "invert": invert,
        "color_level": color_level,
        "fit": fit,
        "max_cols": max_cols,
        "img_width": img_width,
        "halfblock_mode": halfblock_mode,
        "tmux_passthrough": tmux_passthrough,
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
    force_renderer: RendererName | None = None,
    invert: bool | None = None,
    color_level: ColorLevelName | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    halfblock_mode: HalfBlockMode | None = None,
    tmux_passthrough: str | None = None,
) -> DrawOutput: ...


@overload
def draw(
    payload: str | Path,
    *,
    force_renderer: RendererName | None = None,
    invert: bool | None = None,
    color_level: ColorLevelName | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    halfblock_mode: HalfBlockMode | None = None,
    tmux_passthrough: str | None = None,
) -> DrawOutput: ...


@overload
def draw(
    payload: bytes | bytearray,
    *,
    force_renderer: RendererName | None = None,
    invert: bool | None = None,
    color_level: ColorLevelName | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    halfblock_mode: HalfBlockMode | None = None,
    tmux_passthrough: str | None = None,
) -> DrawOutput: ...


def draw(
    payload: ImageInput | str | Path | bytes | bytearray,
    *,
    force_renderer: RendererName | None = None,
    invert: bool | None = None,
    color_level: ColorLevelName | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    halfblock_mode: HalfBlockMode | None = None,
    tmux_passthrough: str | None = None,
) -> DrawOutput:
    """
    探测终端并生成及分片产出二维码渲染流.

    Args:
        payload: 图像对象或本地图片路径（str/Path）.
        force_renderer: 强制指定渲染器(如 "kitty", "iterm2").
        invert: 是否反转颜色.
        color_level: 文本颜色等级(auto/none/ansi16/ansi256/truecolor).
        fit: 是否按终端列宽自动收束.
        max_cols: 最大列宽上限.
        img_width: 渲染宽度（fit=True 时仅显式指定才作为额外上限，fit=False 时未指定默认 40）.
        halfblock_mode: halfblock 严格路径策略（precision/area）.
        tmux_passthrough: tmux 穿透策略(auto/always/never).

    Returns:
        支持分片迭代与直接字符串输出的包装对象.

    Examples:
        直接输出完整结果:

        >>> from terminal_qrcode import draw
        >>> print(draw("qrcode.png"))

        以分片流式处理输出:

        >>> out = draw("qrcode.png", force_renderer="halfblock")
        >>> for chunk in out:
        ...     _ = chunk

        从内存字节输入:

        >>> png_bytes = b"..."
        >>> text = str(draw(png_bytes, force_renderer="halfblock"))

    """
    if isinstance(payload, (str, Path)):
        payload = SimpleImage.open(payload)
    elif isinstance(payload, (bytes, bytearray)):
        payload = SimpleImage.from_bytes(payload)

    overrides = _build_overrides(
        force_renderer=force_renderer,
        invert=invert,
        color_level=color_level,
        fit=fit,
        max_cols=max_cols,
        img_width=img_width,
        halfblock_mode=halfblock_mode,
        tmux_passthrough=tmux_passthrough,
    )
    return DrawOutput(core.run_pipeline(payload, overrides=overrides))


def decode_and_redraw(payload: ImageInput | str | Path | bytes | bytearray) -> ImageInput:
    """先尝试解码二维码内容，再重建高精度二维码图像."""
    if qrcode is None or pyzarb is None:
        raise RuntimeError("decode_and_redraw requires optional dependency group [pyzarb].")
    qrcode_mod = qrcode

    image_input = payload
    if isinstance(image_input, (str, Path)):
        image_input = SimpleImage.open(image_input)
    elif isinstance(image_input, (bytes, bytearray)):
        image_input = SimpleImage.from_bytes(image_input)
    image = image_input if isinstance(image_input, SimpleImage) else core._to_simple_image(image_input)
    luma = image if image.mode == "L" else image.convert("L")
    decoded = pyzarb.decode((bytes(luma._data), luma.width, luma.height))
    if not decoded:
        return image

    result = None
    for item in decoded:
        kind = str(getattr(item, "type", "")).upper()
        if kind in {"", "QRCODE"}:
            result = item
            break
    if result is None:
        return image

    qr = qrcode_mod.QRCode(
        version=None,
        error_correction=qrcode_mod.constants.ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    qr.add_data(getattr(result, "data", b""))
    qr.make(fit=True)
    return SimpleImage.from_qr_matrix(qr.get_matrix())


def generate(
    data: str,
    *,
    ec_level: str = "M",
    border: int = 2,
    force_renderer: RendererName | None = None,
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
        force_renderer: 强制指定渲染器(如 "kitty", "iterm2").
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
    if qrcode is None:
        raise RuntimeError("qrcode dependency is required. Please install terminal-qrcode[qr].")
    if border < 0:
        raise ValueError("border must be >= 0")

    ec_map = {
        "L": qrcode.constants.ERROR_CORRECT_L,
        "M": qrcode.constants.ERROR_CORRECT_M,
        "Q": qrcode.constants.ERROR_CORRECT_Q,
        "H": qrcode.constants.ERROR_CORRECT_H,
    }
    level = ec_level.upper()
    if level not in ec_map:
        raise ValueError("ec_level must be one of: L, M, Q, H")

    qr = qrcode.QRCode(
        version=None,
        error_correction=ec_map[level],
        box_size=1,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    payload = SimpleImage.from_qr_matrix(qr.get_matrix())

    overrides = _build_overrides(
        force_renderer=force_renderer,
        invert=invert,
        color_level=color_level,
        fit=fit,
        max_cols=max_cols,
        img_width=img_width,
        halfblock_mode=halfblock_mode,
        tmux_passthrough=tmux_passthrough,
    )
    return DrawOutput(core.run_pipeline(payload, overrides=overrides))
