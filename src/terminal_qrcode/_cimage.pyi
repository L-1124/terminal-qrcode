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

def matrix_to_image(
    bits: bytes,
    width: int,
    height: int,
    scale: int,
    mode: PixelMode,
) -> bytes:
    """将 bool 矩阵栅格化为像素字节."""

def qr_matrix_to_luma(
    matrix: list[list[bool]],
) -> tuple[int, int, bytes]:
    """将 QR 布尔矩阵转换为 L 模式像素字节（黑=0，白=255）."""

def otsu_threshold(
    data: bytes,
) -> int:
    """计算最佳 Otsu 阈值."""

def find_black_bbox_bits(
    bits: bytes,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    """在 0/1 位图中查找黑像素包围盒."""

def sample_matrix_3x3(
    bits: bytes,
    width: int,
    height: int,
    bbox: tuple[int, int, int, int],
    size: int,
) -> bytes:
    """按 3x3 多数表决采样 QR 矩阵."""

def estimate_module_size(
    bits: bytes,
    width: int,
    height: int,
    bbox: tuple[int, int, int, int],
) -> float | None:
    """估计 QR 模块尺寸."""

def find_finder_centers(
    bits: bytes,
    width: int,
    height: int,
    variance: float,
) -> tuple[float, float, float, float, float, float] | None:
    """扫描并返回三个 Finder 中心点 `(tlx, tly, trx, try, blx, bly)`."""

def sample_matrix_affine(
    bits: bytes,
    width: int,
    height: int,
    size: int,
    tlx: float,
    tly: float,
    hx: float,
    hy: float,
    vx: float,
    vy: float,
    window: int,
) -> bytes:
    """在仿射坐标系下按窗口多数投票采样矩阵."""

def score_finder(
    matrix: bytes,
    size: int,
) -> float:
    """计算二维码三个 Finder 区域的匹配得分."""
