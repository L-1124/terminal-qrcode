"""可选 C 加速模块的类型声明."""

from typing import Literal, TypeAlias

PixelMode: TypeAlias = Literal["L", "RGB", "RGBA"]

def convert(
    data: bytes,
    src_mode: PixelMode,
    dst_mode: PixelMode,
    width: int,
    height: int,
) -> bytes:
    """转换像素模式并返回目标模式原始字节."""

def getbbox_nonwhite(
    data: bytes,
    mode: PixelMode,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    """计算非白像素包围盒，全白图像返回 None."""

def resize_nearest(
    data: bytes,
    mode: PixelMode,
    src_w: int,
    src_h: int,
    dst_w: int,
    dst_h: int,
) -> bytes:
    """使用最近邻算法缩放图像并返回原始字节."""

def decode_png_8bit(
    data: bytes,
) -> tuple[PixelMode, int, int, bytes]:
    """解码 PNG 并返回 `(mode, width, height, pixels)`."""

def encode_png_8bit(
    data: bytes,
    mode: PixelMode,
    width: int,
    height: int,
) -> bytes:
    """编码 PNG 并返回 PNG 二进制字节."""

def decode_jpeg_turbo(
    data: bytes,
) -> tuple[int, int, bytes]:
    """解码 JPEG 并返回 `(width, height, rgb_bytes)`."""

def decode_webp_lib(
    data: bytes,
) -> tuple[int, int, bytes]:
    """解码 WEBP 并返回 `(width, height, rgba_bytes)`."""

def threshold_to_bits(
    data: bytes,
    mode: PixelMode,
    width: int,
    height: int,
    threshold: int,
) -> bytes:
    """按阈值生成 0/1 位图字节."""

def sixel_encode_mono(
    bits: bytes,
    width: int,
    height: int,
) -> str:
    """将 0/1 位图字节编码为 sixel body 字符串."""
