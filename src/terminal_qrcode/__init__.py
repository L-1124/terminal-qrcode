"""终端二维码渲染库."""

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import overload

from . import core
from .contracts import (
    ImageInput,
    RendererOption,
)
from .simple_image import SimpleImage

__version__ = "0.2.0"


__all__ = [
    "SimpleImage",
    "DrawOutput",
    "draw",
]


def _build_overrides(
    *,
    renderer: RendererOption | None,
    invert: bool | None,
    fit: bool | None,
    max_cols: int | None,
    img_width: int | None,
    preserve_source: bool | None,
) -> dict[str, object]:
    """构建渲染覆盖参数字典."""
    return {
        "renderer": renderer,
        "invert": invert,
        "fit": fit,
        "max_cols": max_cols,
        "img_width": img_width,
        "preserve_source": preserve_source,
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
    invert: bool | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    preserve_source: bool | None = None,
) -> DrawOutput: ...


@overload
def draw(
    payload: str | Path,
    *,
    renderer: RendererOption = "auto",
    invert: bool | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    preserve_source: bool | None = None,
) -> DrawOutput: ...


@overload
def draw(
    payload: bytes | bytearray,
    *,
    renderer: RendererOption = "auto",
    invert: bool | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    preserve_source: bool | None = None,
) -> DrawOutput: ...


def draw(
    payload: "ImageInput | str | Path | bytes | bytearray",
    *,
    renderer: RendererOption = "auto",
    invert: bool | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    preserve_source: bool | None = None,
) -> DrawOutput:
    """
    探测终端并生成及分片产出二维码渲染流.

    Args:
        payload: 图像对象或本地图片路径（str/Path）.
        renderer: 渲染器类型（auto/kitty/iterm2/wezterm/sixel/halfblock）.
        invert: 是否反转颜色.
        fit: 是否按终端列宽自动收束.
        max_cols: 最大列宽上限.
        img_width: 渲染宽度（fit=True 时仅显式指定才作为额外上限，fit=False 时未指定默认 40）.
        preserve_source: 是否在图形协议终端下尝试保留并直接渲染原始图像.

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
        invert=invert,
        fit=fit,
        max_cols=max_cols,
        img_width=img_width,
        preserve_source=preserve_source,
    )
    request = core._normalize_request(payload, source=source, overrides=overrides)
    return DrawOutput(core.run_pipeline(request))
