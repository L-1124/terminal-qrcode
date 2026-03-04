"""二维码严格还原管线模块."""

import logging

from terminal_qrcode import _cimage
from terminal_qrcode.contracts import RenderConfig
from terminal_qrcode.layout import _to_luma_bits
from terminal_qrcode.simple_image import SimpleImage

logger = logging.getLogger(__name__)

_MIN_QR_SIZE = 21
_MAX_QR_SIZE = 177
_QR_STEP = 4
_FINDER_SCORE_THRESHOLD = 0.70


def _find_black_bbox(bits: bytes, width: int, height: int) -> tuple[int, int, int, int] | None:
    """查找黑像素包围盒（右下边界为开区间）."""
    return _cimage.find_black_bbox_bits(bits, width, height)


def _estimate_module_size(bits: bytes, width: int, height: int, bbox: tuple[int, int, int, int]) -> float | None:
    """通过 run-length 统计估计模块尺寸."""
    return _cimage.estimate_module_size(bits, width, height, bbox)


def _nearest_qr_size(n_est: float) -> int | None:
    """将估计网格约束到标准 QR 尺寸集合."""
    candidates = list(range(_MIN_QR_SIZE, _MAX_QR_SIZE + 1, _QR_STEP))
    best = min(candidates, key=lambda n: abs(n - n_est))
    if abs(best - n_est) > 1.2:
        return None
    return best


def _sample_matrix_3x3(
    bits: bytes, width: int, height: int, bbox: tuple[int, int, int, int], size: int
) -> list[list[bool]]:
    """按模块 3x3 采样，输出 QR 模块矩阵."""
    out_bytes = _cimage.sample_matrix_3x3(bits, width, height, bbox, size)
    matrix: list[list[bool]] = []
    for i in range(size):
        start = i * size
        matrix.append([b == 1 for b in out_bytes[start : start + size]])
    return matrix


def _finder_score(matrix: list[list[bool]]) -> float:
    """计算三个 Finder 区域匹配得分."""
    size = len(matrix)
    if size < _MIN_QR_SIZE or any(len(row) != size for row in matrix):
        return 0.0

    def _expected(x: int, y: int) -> bool:
        if x in (0, 6) or y in (0, 6):
            return True
        if x in (1, 5) or y in (1, 5):
            return False
        return True

    origins = ((0, 0), (size - 7, 0), (0, size - 7))
    matches = 0
    total = 0
    for ox, oy in origins:
        for y in range(7):
            for x in range(7):
                if matrix[oy + y][ox + x] == _expected(x, y):
                    matches += 1
                total += 1
    return matches / total if total else 0.0


def _invert_matrix(matrix: list[list[bool]]) -> list[list[bool]]:
    return [[not cell for cell in row] for row in matrix]


def _auto_polarity(matrix: list[list[bool]], invert_override: bool | None) -> list[list[bool]]:
    """按显式配置或 Finder 得分自动选择黑白极性."""
    if invert_override is True:
        return _invert_matrix(matrix)
    if invert_override is False:
        return matrix

    inverted = _invert_matrix(matrix)
    return inverted if _finder_score(inverted) > _finder_score(matrix) else matrix


def strict_restore_qr_matrix(image: SimpleImage, config: RenderConfig) -> list[list[bool]] | None:
    """严格还原二维码模块矩阵，失败返回 None."""
    luma = image if image.mode == "L" else image.convert("L")
    bits, _threshold = _to_luma_bits(luma, threshold=None)
    bbox = _find_black_bbox(bits, luma.width, luma.height)
    if bbox is None:
        return None

    module_size = _estimate_module_size(bits, luma.width, luma.height, bbox)
    if module_size is None:
        return None

    left, top, right, bottom = bbox
    est_w = (right - left) / module_size
    est_h = (bottom - top) / module_size
    size_est = (est_w + est_h) / 2.0
    size = _nearest_qr_size(size_est)
    if size is None:
        return None

    matrix = _sample_matrix_3x3(bits, luma.width, luma.height, bbox, size)
    matrix = _auto_polarity(matrix, config.invert)
    if config.invert is None and _finder_score(matrix) < _FINDER_SCORE_THRESHOLD:
        return None
    return matrix
