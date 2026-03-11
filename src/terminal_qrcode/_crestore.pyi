from ._contracts import Matrix, RenderConfig
from ._simple_image import SimpleImage

def strict_restore_qr_matrix(
    image: SimpleImage,
    config: RenderConfig,
) -> Matrix | None:
    """严格还原二维码矩阵，失败时返回 None."""

def find_black_bbox_bits(
    bits: bytes,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    """计算位图中黑色像素包围盒，全白时返回 None."""

def sample_matrix_3x3(
    bits: bytes,
    width: int,
    height: int,
    bbox: tuple[int, int, int, int],
    size: int,
) -> bytes:
    """按 3x3 多点投票从包围盒采样二维码矩阵字节."""

def estimate_module_size(
    bits: bytes,
    width: int,
    height: int,
    bbox: tuple[int, int, int, int],
) -> float | None:
    """基于黑白游程中位数估计二维码模块尺寸."""

def find_finder_centers(
    bits: bytes,
    width: int,
    height: int,
    variance: float,
) -> tuple[float, float, float, float, float, float] | None:
    """扫描 Finder 图形并返回左上、右上、左下中心坐标."""

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
    """使用仿射坐标和窗口投票采样二维码矩阵字节."""

def score_finder(
    matrix: bytes,
    size: int,
) -> float:
    """计算矩阵三个 Finder 区域的匹配得分."""
