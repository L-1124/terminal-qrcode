"""渲染流程契约定义."""

from collections.abc import Generator
from dataclasses import dataclass
from enum import Enum, auto
from typing import Literal, Protocol, TypeAlias, runtime_checkable

from terminal_qrcode.simple_image import SimpleImage

RendererName = Literal["kitty", "iterm2", "wezterm", "sixel", "halfblock"]
HalfBlockMode = Literal["precision", "area"]
ColorLevelName = Literal["auto", "none", "ansi16", "ansi256", "truecolor"]
Matrix: TypeAlias = list[list[bool]]


@dataclass(frozen=True)
class RenderConfig:
    """渲染配置项."""

    scale: int = 8
    force_renderer: RendererName | None = None
    timeout: float = 0.1
    invert: bool | None = None
    color_level: ColorLevelName = "auto"
    fit: bool = True
    max_cols: int | None = None
    img_width: int | None = None
    halfblock_mode: HalfBlockMode = "precision"
    tmux_passthrough: Literal["auto", "always", "never"] = "auto"
    border: int = 2
    finder_variance: float = 0.8
    restore_window: int = 3


class TerminalCapability(Enum):
    """终端能力枚举."""

    KITTY = auto()
    ITERM2 = auto()
    WEZTERM = auto()
    SIXEL = auto()
    FALLBACK = auto()


class TerminalColorLevel(Enum):
    """终端文本颜色能力枚举."""

    NONE = auto()
    ANSI16 = auto()
    ANSI256 = auto()
    TRUECOLOR = auto()


@dataclass(frozen=True)
class TerminalCapabilities:
    """终端能力快照."""

    capability: TerminalCapability
    color_level: TerminalColorLevel


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


ImageInput = SimpleImage | ImageProtocol | Matrix


@runtime_checkable
class Renderer(Protocol):
    """渲染器协议."""

    def render(self, payload: Matrix | SimpleImage, config: RenderConfig) -> Generator[str, None, None]:
        """流式分片渲染二维码矩阵或图像."""
        ...
