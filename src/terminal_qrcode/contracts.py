"""渲染流程契约定义."""

from collections.abc import Generator
from dataclasses import dataclass
from enum import Enum, auto
from typing import Literal, Protocol, runtime_checkable

from terminal_qrcode.simple_image import SimpleImage

RendererName = Literal["kitty", "iterm2", "wezterm", "sixel", "halfblock"]


@dataclass(frozen=True)
class RenderConfig:
    """渲染配置项."""

    scale: int = 8
    force_renderer: RendererName | None = None
    timeout: float = 0.1
    invert: bool | None = None
    ascii_only: bool = False
    fit: bool = True
    max_cols: int | None = None
    img_width: int | None = None
    tmux_passthrough: Literal["auto", "always", "never"] = "auto"


class TerminalCapability(Enum):
    """终端能力枚举."""

    KITTY = auto()
    ITERM2 = auto()
    WEZTERM = auto()
    SIXEL = auto()
    FALLBACK = auto()


@runtime_checkable
class ImageProtocol(Protocol):
    """外部图像协议（兼容 PIL.Image.Image 等结构化对象）."""

    mode: str
    size: tuple[int, int]

    def tobytes(self) -> bytes:
        """导出原始像素字节."""
        ...

    def convert(self, mode: str) -> "ImageProtocol":
        """转换为指定色彩模式."""
        ...


ImageInput = SimpleImage | ImageProtocol


@runtime_checkable
class Renderer(Protocol):
    """渲染器协议."""

    def render(self, payload: list[list[bool]] | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
        """流式分片渲染二维码矩阵或图像流."""
        ...
