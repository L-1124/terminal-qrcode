"""二维码图像处理与终端排版布局模块."""

import os
import sys
from dataclasses import dataclass
from shutil import get_terminal_size
from typing import Any, Literal

from terminal_qrcode import _cimage
from terminal_qrcode.contracts import RenderConfig
from terminal_qrcode.simple_image import SimpleImage

if sys.platform != "win32":
    import fcntl
    import termios
else:
    fcntl: Any | None = None
    termios: Any | None = None

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
    """将二维码矩阵批量栅格化为图像."""
    width = len(matrix[0]) * scale
    height = len(matrix) * scale

    flat_bits = bytes([1 if cell else 0 for row in matrix for cell in row])
    out = _cimage.matrix_to_image(flat_bits, len(matrix[0]), len(matrix), scale, mode)
    return SimpleImage(mode, (width, height), out)


def _resize_image_to_cols(
    image: SimpleImage,
    target_cols: int,
    *,
    allow_upscale: bool = False,
) -> SimpleImage:
    """按目标列宽等比调整图像."""
    if image.width == target_cols:
        return image
    if image.width < target_cols and not allow_upscale:
        return image
    target_h = max(1, round(image.height * target_cols / image.width))
    return image.resize((target_cols, target_h))


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
    mode = image.mode
    out = _cimage.threshold_to_bits(data, mode, image.width, image.height, threshold)
    return bytes(out)


def _sixel_encode_mono(bits: bytes, width: int, height: int) -> str:
    """将 0/1 位图编码为 sixel body."""
    out = _cimage.sixel_encode_mono(bits, width, height)
    return str(out)


def _otsu_threshold_from_luma(data: bytes) -> int:
    """基于灰度直方图计算 Otsu 阈值."""
    if not data:
        return 128
    return _cimage.otsu_threshold(data)


def _to_luma_bits(image: SimpleImage, threshold: int | None) -> tuple[bytes, int]:
    """转换为灰度二值图，返回 bit 图与实际阈值."""
    luma = image if image.mode == "L" else image.convert("L")
    final_threshold = threshold if threshold is not None else _otsu_threshold_from_luma(bytes(luma._data))
    effective_threshold = max(1, final_threshold)
    bits = _threshold_to_bits(luma, threshold=effective_threshold)
    return bits, final_threshold


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
]
