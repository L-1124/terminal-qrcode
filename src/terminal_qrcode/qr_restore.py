"""二维码严格还原管线模块."""

import math

from . import _cimage
from .contracts import Matrix, RenderConfig
from .layout import _to_luma_bits
from .simple_image import SimpleImage

_MIN_QR_SIZE = 21
_MAX_QR_SIZE = 177
_QR_STEP = 4
_FINDER_SCORE_THRESHOLD = 0.55


def _qr_sizes() -> list[int]:
    return list(range(_MIN_QR_SIZE, _MAX_QR_SIZE + 1, _QR_STEP))


def _nearest_qr_size(n_est: float) -> int | None:
    """将估计网格约束到标准 QR 尺寸集合."""
    candidates = _qr_sizes()
    best = min(candidates, key=lambda n: abs(n - n_est))
    if abs(best - n_est) > 1.5:
        return None
    return best


def _infer_size_from_bbox(bits: bytes, width: int, height: int) -> int | None:
    """由黑像素包围盒推断 QR 模块尺寸."""
    bbox = _cimage.find_black_bbox_bits(bits, width, height)
    if bbox is None:
        return None
    module_size = _cimage.estimate_module_size(bits, width, height, bbox)
    if module_size is None or module_size <= 0:
        return None
    left, top, right, bottom = bbox
    est_w = (right - left) / module_size
    est_h = (bottom - top) / module_size
    return _nearest_qr_size((est_w + est_h) / 2.0)


def _infer_bbox_and_size(bits: bytes, width: int, height: int) -> tuple[tuple[int, int, int, int], int] | None:
    """推断黑像素包围盒及 QR 尺寸."""
    bbox = _cimage.find_black_bbox_bits(bits, width, height)
    if bbox is None:
        return None
    module_size = _cimage.estimate_module_size(bits, width, height, bbox)
    if module_size is None or module_size <= 0:
        return None
    left, top, right, bottom = bbox
    est_w = (right - left) / module_size
    est_h = (bottom - top) / module_size
    size = _nearest_qr_size((est_w + est_h) / 2.0)
    if size is None:
        return None
    return bbox, size


def _infer_qr_size_from_vectors(h_len: float, v_len: float) -> int | None:
    """由 Finder 间向量长度推断 QR 尺寸."""
    best_size: int | None = None
    best_score = float("inf")

    for size in _qr_sizes():
        span = size - 7
        if span <= 0:
            continue
        module_h = h_len / span
        module_v = v_len / span
        if module_h < 0.8 or module_v < 0.8:
            continue
        mismatch = abs(module_h - module_v) / max(module_h, module_v)
        if mismatch < best_score:
            best_score = mismatch
            best_size = size

    if best_size is None or best_score > 0.55:
        return None
    return best_size


def _finder_score(matrix: Matrix) -> float:
    """计算三个 Finder 区域匹配得分 (委托给 C 扩展)."""
    size = len(matrix)
    if size < _MIN_QR_SIZE:
        return 0.0
    # 将 Matrix 展平为 bytes 供 C 调用
    flat_bits = bytes(cell for row in matrix for cell in row)
    return float(_cimage.score_finder(flat_bits, size))


def _invert_matrix(matrix: Matrix) -> Matrix:
    return [[not cell for cell in row] for row in matrix]


def _invert_bits(bits: bytes) -> bytes:
    return bytes(0 if b else 1 for b in bits)


def _auto_polarity(matrix: Matrix, invert_override: bool | None) -> Matrix:
    """按显式配置或 Finder 得分自动选择黑白极性."""
    if invert_override is True:
        return _invert_matrix(matrix)
    if invert_override is False:
        return matrix

    inverted = _invert_matrix(matrix)
    return inverted if _finder_score(inverted) > _finder_score(matrix) else matrix


def _matrix_score(matrix: Matrix) -> float:
    """计算矩阵在两种极性下的最佳 Finder 得分."""
    return max(_finder_score(matrix), _finder_score(_invert_matrix(matrix)))


def strict_restore_qr_matrix(image: SimpleImage, config: RenderConfig) -> Matrix | None:
    """严格还原二维码模块矩阵，失败返回 None."""
    luma = image if image.mode == "L" else image.convert("L")
    bits, _threshold = _to_luma_bits(luma, threshold=None)

    candidates: list[Matrix] = []

    # Legacy bbox+3x3 sampling remains as a deterministic safety baseline.
    bbox_size = _infer_bbox_and_size(bits, luma.width, luma.height)
    if bbox_size is not None:
        bbox, size = bbox_size
        sampled = _cimage.sample_matrix_3x3(bits, luma.width, luma.height, bbox, size)
        matrix_legacy: Matrix = []
        for i in range(size):
            start = i * size
            matrix_legacy.append([b == 1 for b in sampled[start : start + size]])

        # 早期终止：若 Legacy 采样已完美匹配，则直接返回
        if _matrix_score(matrix_legacy) >= 1.0:
            return _auto_polarity(matrix_legacy, config.qr.invert)

        candidates.append(matrix_legacy)

    finder_variance = max(0.1, config.qr.finder_variance)
    for bits_for_scan in (bits, _invert_bits(bits)):
        centers = _cimage.find_finder_centers(bits_for_scan, luma.width, luma.height, finder_variance)
        if centers is None:
            centers = _cimage.find_finder_centers(bits_for_scan, luma.width, luma.height, finder_variance * 1.5)
        if centers is None:
            continue

        tlx, tly, trx, try_, blx, bly = centers
        hx = trx - tlx
        hy = try_ - tly
        vx = blx - tlx
        vy = bly - tly

        h_len = math.hypot(hx, hy)
        v_len = math.hypot(vx, vy)
        if h_len < 7 or v_len < 7:
            continue

        size = _infer_size_from_bbox(bits, luma.width, luma.height)
        if size is None:
            size = _infer_qr_size_from_vectors(h_len, v_len)
        if size is None:
            continue

        sampled = _cimage.sample_matrix_affine(
            bits_for_scan,
            luma.width,
            luma.height,
            size,
            float(tlx),
            float(tly),
            float(hx),
            float(hy),
            float(vx),
            float(vy),
            config.qr.restore_window,
        )
        matrix_affine: Matrix = []
        for i in range(size):
            start = i * size
            matrix_affine.append([b == 1 for b in sampled[start : start + size]])
        candidates.append(matrix_affine)

    if not candidates:
        return None

    best_matrix = max(candidates, key=_matrix_score)
    matrix = _auto_polarity(best_matrix, config.qr.invert)
    if config.qr.invert is None and _finder_score(matrix) < _FINDER_SCORE_THRESHOLD:
        return None
    return matrix
