"""终端二维码渲染库."""

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Literal, TextIO, overload

from . import core
from .contracts import (
    ImageInput,
    RendererOption,
    RenderRequest,
)
from .simple_image import SimpleImage

__version__ = "1.0.0"


__all__ = [
    "SimpleImage",
    "DrawOutput",
    "draw",
    "generate",
]


ErrorCorrectionLevel = Literal["low", "medium", "quartile", "high"]


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
    """`draw` 的包装结果，支持迭代与直接终端输出."""

    def __init__(self, request: RenderRequest) -> None:
        """
        初始化输出包装器.

        Args:
            request: 延迟执行的统一渲染请求.

        """
        self._request = request
        self._source: Iterator[str] | None = None
        self._cache: list[str] = []
        self._exhausted = False
        self._rich_cache = None

    def _ensure_source(self) -> Iterator[str]:
        """按需启动渲染管线."""
        if self._source is None:
            self._source = iter(core.run_pipeline(self._request))
        return self._source

    def _drain(self) -> None:
        """消费剩余分片并缓存."""
        if self._exhausted:
            return
        for chunk in self._ensure_source():
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
                chunk = next(self._ensure_source())
            except StopIteration:
                self._exhausted = True
                return
            self._cache.append(chunk)
            idx += 1
            yield chunk

    def print(self, *, file: TextIO | None = None, end: str = "", flush: bool = True) -> None:
        """
        将输出原样写入文本流.

        Args:
            file: 目标文本流，未提供时写入标准输出.
            end: 追加在输出末尾的文本.
            flush: 写入后是否立即刷新目标流.

        """
        stream = sys.stdout if file is None else file
        for chunk in self:
            stream.write(chunk)
        if end:
            stream.write(end)
        if flush:
            stream.flush()

    def __rich__(self):
        """为 Rich 返回固定 halfblock 路径的文本渲染结果，不受 renderer 参数影响."""
        from rich.text import Text  # type: ignore[import]

        if self._rich_cache is not None:
            return self._rich_cache

        rich_request = core._normalize_request(
            self._request.payload,
            source=self._request.source,
            config=self._request.config,
            overrides={"renderer": "halfblock", "preserve_source": False},
        )
        output = "".join(core.run_pipeline(rich_request))
        self._rich_cache = Text.from_ansi(output)
        return self._rich_cache

    def __repr__(self) -> str:
        """调试表示."""
        started = self._source is not None
        payload_type = type(self._request.payload).__name__
        renderer = self._request.config.probe.renderer
        source = self._request.source
        return (
            "DrawOutput("
            f"source={source!r}, "
            f"payload_type={payload_type!r}, "
            f"renderer={renderer!r}, "
            f"started={started}, "
            f"exhausted={self._exhausted}, "
            f"cached_chunks={len(self._cache)}"
            ")"
        )


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
        支持分片迭代与直接终端输出的包装对象.

    Examples:
        直接输出完整结果:

        >>> from terminal_qrcode import draw
        >>> draw("qrcode.png").print()

        以分片流式处理输出:

        >>> out = draw("qrcode.png", renderer="halfblock")
        >>> for chunk in out:
        ...     _ = chunk

        从内存字节输入:

        >>> png_bytes = b"..."
        >>> out = draw(png_bytes, renderer="halfblock")
        >>> out.print()

        支持 Rich 渲染（`__rich__` 固定使用 `halfblock`，不受 `renderer` 参数影响）:
        >>> from rich.console import Console
        >>> console = Console()
        >>> console.print(draw("qrcode.png"))

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
    return DrawOutput(request)


def generate(
    data: str,
    *,
    error_correction: ErrorCorrectionLevel = "medium",
    version: int | None = None,
    renderer: RendererOption = "auto",
    invert: bool | None = None,
    fit: bool | None = None,
    max_cols: int | None = None,
    img_width: int | None = None,
    preserve_source: bool | None = None,
) -> DrawOutput:
    """
    根据文本数据直接生成二维码并渲染输出.

    Args:
        data: 二维码文本内容或 URL.
        error_correction: 纠错等级 (low/medium/quartile/high).
        version: 二维码版本 (1-40)，None 表示自动选择.
        renderer: 渲染器类型.
        invert: 是否反转颜色.
        fit: 是否按终端列宽自动收束.
        max_cols: 最大列宽上限.
        img_width: 渲染宽度.
        preserve_source: 是否在图形协议终端下尝试保留并直接渲染原始图像.

    Returns:
        渲染输出包装对象.

    Examples:
        >>> from terminal_qrcode import generate
        >>> generate("https://github.com").print()

    """
    import qrcode
    from qrcode import constants as qrc

    ec_map = {
        "low": qrc.ERROR_CORRECT_L,
        "medium": qrc.ERROR_CORRECT_M,
        "quartile": qrc.ERROR_CORRECT_Q,
        "high": qrc.ERROR_CORRECT_H,
    }

    qr = qrcode.QRCode(
        version=version,
        error_correction=ec_map.get(error_correction, qrc.ERROR_CORRECT_M),
        border=0,  # 由 draw/layout 统一处理边距
    )
    qr.add_data(data)
    matrix = qr.get_matrix()

    return draw(
        matrix,
        renderer=renderer,
        invert=invert,
        fit=fit,
        max_cols=max_cols,
        img_width=img_width,
        preserve_source=preserve_source,
    )
