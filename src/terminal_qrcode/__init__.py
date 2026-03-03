"""终端二维码渲染库."""

import logging
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import overload

from terminal_qrcode import core
from terminal_qrcode.contracts import ImageInput, RendererName
from terminal_qrcode.simple_image import SimpleImage

logger = logging.getLogger(__name__)

__version__ = "0.1.0"

__all__ = [
    "SimpleImage",
    "DrawOutput",
    "draw",
]


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
    scale: int | None = None,
    force_renderer: RendererName | None = None,
    timeout: float | None = None,
    invert: bool | None = None,
    ascii_only: bool | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    tmux_passthrough: str | None = None,
) -> DrawOutput: ...


@overload
def draw(
    payload: str | Path,
    *,
    scale: int | None = None,
    force_renderer: RendererName | None = None,
    timeout: float | None = None,
    invert: bool | None = None,
    ascii_only: bool | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    tmux_passthrough: str | None = None,
) -> DrawOutput: ...


@overload
def draw(
    payload: bytes | bytearray,
    *,
    scale: int | None = None,
    force_renderer: RendererName | None = None,
    timeout: float | None = None,
    invert: bool | None = None,
    ascii_only: bool | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    tmux_passthrough: str | None = None,
) -> DrawOutput: ...


def draw(
    payload: ImageInput | str | Path | bytes | bytearray,
    *,
    scale: int | None = None,
    force_renderer: RendererName | None = None,
    timeout: float | None = None,
    invert: bool | None = None,
    ascii_only: bool | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    tmux_passthrough: str | None = None,
) -> DrawOutput:
    """
    探测终端并生成及分片产出二维码渲染流.

    Args:
        payload: 图像对象或本地图片路径（str/Path）.
        scale: 渲染缩放倍数.
        force_renderer: 强制指定渲染器(如 "kitty", "iterm2").
        timeout: 终端探测超时时间.
        invert: 是否反转颜色.
        ascii_only: 是否仅使用 ASCII 字符.
        fit: 是否按终端列宽自动收束.
        max_cols: 最大列宽上限.
        img_width: 渲染宽度（fit=True 时仅显式指定才作为额外上限，fit=False 时未指定默认 40）.
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

    overrides: dict[str, object] = {
        "scale": scale,
        "force_renderer": force_renderer,
        "timeout": timeout,
        "invert": invert,
        "ascii_only": ascii_only,
        "fit": fit,
        "max_cols": max_cols,
        "img_width": img_width,
        "tmux_passthrough": tmux_passthrough,
    }
    return DrawOutput(core.run_pipeline(payload, overrides=overrides))
