"""二维码图像处理与终端排版布局模块."""

import os
import sys
from dataclasses import dataclass
from shutil import get_terminal_size
from statistics import median
from typing import Any, Literal, cast

from terminal_qrcode import _cimage
from terminal_qrcode.contracts import RenderConfig
from terminal_qrcode.simple_image import SimpleImage

if sys.platform != "win32":
    import fcntl
    import termios
else:
    fcntl: Any | None = None
    termios: Any | None = None

_MIN_QR_SIZE = 21
_MAX_QR_SIZE = 177
_QR_STEP = 4
_FINDER_SCORE_THRESHOLD = 0.70
_FIT_FALLBACK_COLS = 80
_FIT_FALLBACK_ROWS = 24
_FIT_SAFE_COL_MARGIN = 1
_FIT_SAFE_ROW_MARGIN = 1
_FIT_WIDTH_USAGE = 0.30
_FIT_HEIGHT_USAGE = 0.60
_CELL_ASPECT_W_OVER_H = 0.5
_DEFAULT_IMG_WIDTH = 40
_HALFBLOCK_MAX_SCALE = 10
_HALFBLOCK_HEIGHT_USAGE = 0.60
_DEFAULT_CELL_PX_W = 8
_DEFAULT_CELL_PX_H = 16


@dataclass(frozen=True)
class FitPlan:
    """统一 fit 结果."""

    avail_cols: int
    avail_rows: int
    budget_cols: int
    budget_rows: int
    display_cols: int
    display_rows: int


def _get_terminal_size_cells() -> tuple[int, int]:
    """读取终端字符尺寸，失败时回退默认值."""
    try:
        size = get_terminal_size(fallback=(_FIT_FALLBACK_COLS, _FIT_FALLBACK_ROWS))
        cols, rows = size.columns, size.lines
    except OSError:
        cols, rows = _FIT_FALLBACK_COLS, _FIT_FALLBACK_ROWS
    return max(1, int(cols)), max(1, int(rows))


def _get_available_cells() -> tuple[int, int]:
    """计算适用于 fit 的安全可用字符尺寸."""
    cols, rows = _get_terminal_size_cells()
    avail_cols = max(1, cols - _FIT_SAFE_COL_MARGIN)
    avail_rows = max(1, rows - _FIT_SAFE_ROW_MARGIN)
    return avail_cols, avail_rows


def _resolve_user_width_cap(config: RenderConfig) -> int | None:
    """解析用户显式传入的宽度上限."""
    if config.img_width is None:
        return None
    return max(1, config.img_width)


def _resolve_target_cols(config: RenderConfig, *, include_img_width_cap_in_fit: bool = True) -> int:
    """解析当前配置下的目标列宽."""
    if config.fit:
        cols, rows = _get_available_cells()
        plan = _build_fit_plan(config, cols, rows)
        if include_img_width_cap_in_fit:
            return plan.display_cols
        user_cap = _resolve_user_width_cap(config)
        if user_cap is not None:
            return max(1, min(plan.display_cols, user_cap))
        return plan.display_cols

    cols = max(1, config.img_width if config.img_width is not None else _DEFAULT_IMG_WIDTH)
    if config.max_cols is not None:
        cols = min(cols, config.max_cols)
    return max(1, cols)


def _build_fit_plan(config: RenderConfig, src_w: int, src_h: int) -> FitPlan:
    """基于统一规则构建 fit 规划结果."""
    avail_cols, avail_rows = _get_available_cells()
    src_w = max(1, src_w)
    src_h = max(1, src_h)

    if config.fit:
        budget_cols = max(1, int(avail_cols * _FIT_WIDTH_USAGE))
        budget_rows = max(1, int(avail_rows * _FIT_HEIGHT_USAGE))
        if config.max_cols is not None:
            budget_cols = min(budget_cols, config.max_cols)
        user_cap = _resolve_user_width_cap(config)
        if user_cap is not None:
            budget_cols = min(budget_cols, user_cap)

        cols_by_rows = max(1, int((budget_rows * src_w) / max(1, src_h) / _CELL_ASPECT_W_OVER_H))
        display_cols = max(1, min(budget_cols, cols_by_rows))
        display_rows = max(1, int(round(display_cols * src_h / src_w * _CELL_ASPECT_W_OVER_H)))
        return FitPlan(avail_cols, avail_rows, budget_cols, budget_rows, display_cols, display_rows)

    display_cols = max(1, config.img_width if config.img_width is not None else _DEFAULT_IMG_WIDTH)
    if config.max_cols is not None:
        display_cols = min(display_cols, config.max_cols)
    display_rows = max(1, int(round(display_cols * src_h / src_w * _CELL_ASPECT_W_OVER_H)))
    return FitPlan(avail_cols, avail_rows, display_cols, display_rows, display_cols, display_rows)


def _get_cell_pixel_size() -> tuple[int, int] | None:
    """尝试读取终端单元像素尺寸（失败返回 None）."""
    if fcntl is None or termios is None:
        return None
    try:
        import struct

        if not os.isatty(1):
            return None
        packed = fcntl.ioctl(1, termios.TIOCGWINSZ, struct.pack("HHHH", 0, 0, 0, 0))
        rows, cols, xpixel, ypixel = struct.unpack("HHHH", packed)
        if rows <= 0 or cols <= 0 or xpixel <= 0 or ypixel <= 0:
            return None
        cell_w = max(1, xpixel // cols)
        cell_h = max(1, ypixel // rows)
        return cell_w, cell_h
    except Exception:  # noqa: BLE001
        return None


def _cells_to_pixels(cols: int, rows: int) -> tuple[int, int]:
    """将显示 cells 映射到像素尺寸（查询优先，失败回退经验值）."""
    cell_size = _get_cell_pixel_size()
    if cell_size is None:
        return max(1, cols * _DEFAULT_CELL_PX_W), max(1, rows * _DEFAULT_CELL_PX_H)
    cell_w, cell_h = cell_size
    return max(1, cols * cell_w), max(1, rows * cell_h)


def _matrix_to_image(matrix: list[list[bool]], scale: int, mode: Literal["RGB", "RGBA"]) -> SimpleImage:
    """将二维码矩阵批量栅格化为图像, 避免逐像素 putpixel 开销."""
    width = len(matrix[0]) * scale
    height = len(matrix) * scale
    channels = 4 if mode == "RGBA" else 3

    if mode == "RGBA":
        white = b"\xff\xff\xff\xff"
        black = b"\x00\x00\x00\xff"
    else:
        white = b"\xff\xff\xff"
        black = b"\x00\x00\x00"

    row_stride = width * channels
    out = bytearray(white * (width * height))
    white_block = white * scale
    black_block = black * scale

    for y, row in enumerate(matrix):
        line = bytearray()
        for module in row:
            line.extend(black_block if module else white_block)
        line_bytes = bytes(line)
        row_base = y * scale * row_stride
        for dy in range(scale):
            start = row_base + dy * row_stride
            out[start : start + row_stride] = line_bytes

    return SimpleImage(mode, (width, height), out)


def _resize_image_to_cols(
    image: SimpleImage,
    target_cols: int,
    *,
    resample: SimpleImage.Resampling = SimpleImage.Resampling.LANCZOS,
    allow_upscale: bool = False,
) -> SimpleImage:
    """按目标列宽等比调整图像."""
    if image.width == target_cols:
        return image
    if image.width < target_cols and not allow_upscale:
        return image
    target_h = max(1, round(image.height * target_cols / image.width))
    return image.resize((target_cols, target_h), resample=resample)


def _resize_matrix_to_cols(matrix: list[list[bool]], target_cols: int) -> list[list[bool]]:
    """按目标列宽等比收束布尔矩阵（最近邻）."""
    if not matrix or not matrix[0]:
        return matrix

    src_h = len(matrix)
    src_w = len(matrix[0])
    if src_w <= target_cols:
        return matrix

    dst_w = max(1, target_cols)
    dst_h = max(1, round(src_h * dst_w / src_w))
    out: list[list[bool]] = []

    for y in range(dst_h):
        src_y = min((y * src_h) // dst_h, src_h - 1)
        row: list[bool] = []
        src_row = matrix[src_y]
        for x in range(dst_w):
            src_x = min((x * src_w) // dst_w, src_w - 1)
            row.append(src_row[src_x])
        out.append(row)

    return out


def _choose_halfblock_scale(n: int, b: int, c_avail: int, r_avail: int, s_max: int) -> tuple[int, int]:
    """选择 halfblock 严格路径下的整数放大倍数."""
    w0 = n + 2 * b
    if w0 <= 0:
        return 1, b
    s_w = c_avail // w0
    effective_rows = max(1, int(r_avail * _HALFBLOCK_HEIGHT_USAGE))
    s_h = (2 * effective_rows) // w0
    s = min(s_w, s_h)
    s = max(1, min(s, s_max))
    return s, b


def _pad_border(matrix: list[list[bool]], border: int) -> list[list[bool]]:
    """按模块单位为矩阵添加白边."""
    if border <= 0:
        return [row[:] for row in matrix]
    if not matrix:
        return matrix
    width = len(matrix[0])
    pad_row = [False] * (width + border * 2)
    out = [pad_row[:] for _ in range(border)]
    for row in matrix:
        out.append(([False] * border) + row[:] + ([False] * border))
    out.extend(pad_row[:] for _ in range(border))
    return out


def _upscale_matrix_nn(matrix: list[list[bool]], scale: int) -> list[list[bool]]:
    """按最近邻整数倍放大布尔矩阵."""
    if scale <= 1:
        return [row[:] for row in matrix]
    out: list[list[bool]] = []
    for row in matrix:
        scaled_row: list[bool] = []
        for v in row:
            scaled_row.extend([v] * scale)
        for _ in range(scale):
            out.append(scaled_row[:])
    return out


def _threshold_to_bits(image: SimpleImage, threshold: int = 128) -> bytes:
    """将图像阈值化为 0/1 位图字节."""
    data = bytes(image._data)
    try:
        mode = cast(Literal["L", "RGB", "RGBA"], image.mode)
        out = _cimage.threshold_to_bits(data, mode, image.width, image.height, threshold)
        return bytes(out)
    except Exception:  # noqa: BLE001
        pass

    pixels = image.width * image.height
    bits = bytearray(pixels)
    if image.mode == "L":
        for i in range(pixels):
            bits[i] = 1 if data[i] < threshold else 0
        return bytes(bits)
    if image.mode == "RGB":
        for i in range(pixels):
            r = data[i * 3]
            g = data[i * 3 + 1]
            b = data[i * 3 + 2]
            gray = (299 * r + 587 * g + 114 * b) // 1000
            bits[i] = 1 if gray < threshold else 0
        return bytes(bits)
    for i in range(pixels):
        r = data[i * 4]
        g = data[i * 4 + 1]
        b = data[i * 4 + 2]
        a = data[i * 4 + 3]
        if a <= 127:
            bits[i] = 0
            continue
        gray = (299 * r + 587 * g + 114 * b) // 1000
        bits[i] = 1 if gray < threshold else 0
    return bytes(bits)


def _otsu_threshold_from_luma(data: bytes) -> int:
    """基于灰度直方图计算 Otsu 阈值."""
    if not data:
        return 128

    hist = [0] * 256
    for v in data:
        hist[v] += 1

    total = len(data)
    sum_total = sum(i * hist[i] for i in range(256))
    sum_bg = 0
    weight_bg = 0
    best_threshold = 128
    max_between = -1.0

    for t in range(256):
        weight_bg += hist[t]
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break
        sum_bg += t * hist[t]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg
        between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if between > max_between:
            max_between = between
            best_threshold = t

    return best_threshold


def _to_luma_bits(image: SimpleImage, threshold: int | None) -> tuple[bytes, int]:
    """转换为灰度二值图，返回 bit 图与实际阈值."""
    luma = image if image.mode == "L" else image.convert("L")
    final_threshold = threshold if threshold is not None else _otsu_threshold_from_luma(bytes(luma._data))
    effective_threshold = max(1, final_threshold)
    bits = _threshold_to_bits(luma, threshold=effective_threshold)
    return bits, final_threshold


def _find_black_bbox(bits: bytes, width: int, height: int) -> tuple[int, int, int, int] | None:
    """查找黑像素包围盒（右下边界为开区间）."""
    left = width
    top = height
    right = -1
    bottom = -1

    for y in range(height):
        row_start = y * width
        for x in range(width):
            if bits[row_start + x] == 0:
                continue
            if x < left:
                left = x
            if x > right:
                right = x
            if y < top:
                top = y
            if y > bottom:
                bottom = y

    if right < 0:
        return None
    return (left, top, right + 1, bottom + 1)


def _estimate_module_size(bits: bytes, width: int, height: int, bbox: tuple[int, int, int, int]) -> float | None:
    """通过 run-length 统计估计模块尺寸."""
    left, top, right, bottom = bbox
    if right <= left or bottom <= top:
        return None

    sample_ys = [top + ((bottom - top - 1) * i) // 4 for i in range(5)]
    sample_xs = [left + ((right - left - 1) * i) // 4 for i in range(5)]
    runs: list[int] = []

    for y in sample_ys:
        row_start = y * width
        prev = bits[row_start + left]
        run = 1
        for x in range(left + 1, right):
            cur = bits[row_start + x]
            if cur == prev:
                run += 1
                continue
            runs.append(run)
            run = 1
            prev = cur
        runs.append(run)

    for x in sample_xs:
        prev = bits[top * width + x]
        run = 1
        for y in range(top + 1, bottom):
            cur = bits[y * width + x]
            if cur == prev:
                run += 1
                continue
            runs.append(run)
            run = 1
            prev = cur
        runs.append(run)

    filtered = [r for r in runs if r >= 2]
    if not filtered:
        filtered = [r for r in runs if r >= 1]
    if not filtered:
        return None

    filtered.sort()
    lower_half = filtered[: max(1, len(filtered) // 2)]
    module_size = float(median(lower_half))
    if module_size < 1.0:
        return None
    return module_size


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
    left, top, right, bottom = bbox
    bw = max(1, right - left)
    bh = max(1, bottom - top)
    offsets = (1 / 6, 1 / 2, 5 / 6)
    matrix: list[list[bool]] = []

    for my in range(size):
        y0 = top + (my * bh) / size
        y1 = top + ((my + 1) * bh) / size
        row: list[bool] = []
        for mx in range(size):
            x0 = left + (mx * bw) / size
            x1 = left + ((mx + 1) * bw) / size
            votes = 0
            for oy in offsets:
                py = int(y0 + oy * (y1 - y0))
                py = min(max(py, 0), height - 1)
                for ox in offsets:
                    px = int(x0 + ox * (x1 - x0))
                    px = min(max(px, 0), width - 1)
                    if bits[py * width + px] == 1:
                        votes += 1
            row.append(votes >= 5)
        matrix.append(row)
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


def _sixel_encode_mono(bits: bytes, width: int, height: int) -> str:
    """将 0/1 位图编码为 sixel body."""
    try:
        out = _cimage.sixel_encode_mono(bits, width, height)
        return str(out)
    except Exception:  # noqa: BLE001
        pass

    parts: list[str] = []
    for y in range(0, height, 6):
        max_i = min(6, height - y)
        parts.append("#0")
        line_white: list[str] = []
        for x in range(width):
            byte_val = 0
            for i in range(max_i):
                if bits[(y + i) * width + x] == 0:
                    byte_val |= 1 << i
            line_white.append(chr(byte_val + 63))
        white_str = "".join(line_white).rstrip("?")
        if white_str:
            parts.append(white_str)
        parts.append("$")

        parts.append("#1")
        line_black: list[str] = []
        for x in range(width):
            byte_val = 0
            for i in range(max_i):
                if bits[(y + i) * width + x] == 1:
                    byte_val |= 1 << i
            line_black.append(chr(byte_val + 63))
        black_str = "".join(line_black).rstrip("?")
        if black_str:
            parts.append(black_str)
        parts.append("-")
    return "".join(parts)


__all__ = [
    "FitPlan",
    "_get_terminal_size_cells",
    "_get_available_cells",
    "_resolve_target_cols",
    "_build_fit_plan",
    "_get_cell_pixel_size",
    "_cells_to_pixels",
    "_matrix_to_image",
    "_resize_image_to_cols",
    "_resize_matrix_to_cols",
    "_choose_halfblock_scale",
    "_pad_border",
    "_upscale_matrix_nn",
    "_threshold_to_bits",
    "_otsu_threshold_from_luma",
    "_to_luma_bits",
    "_sixel_encode_mono",
    "strict_restore_qr_matrix",
]
