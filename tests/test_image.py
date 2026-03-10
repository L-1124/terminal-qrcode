"""SimpleImage 模块的测试集."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import terminal_qrcode._simple_image as simple_image
from terminal_qrcode import _cimage
from terminal_qrcode._simple_image import SimpleImage


def _png_fixture_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9ccdbf\x01\x00\x00\x18\x00\x07\x10\xe7'\xc4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _flatten_matrix_bits(matrix: list[list[bool]], scale: int = 1) -> bytes:
    """将布尔矩阵按整数 scale 栅格化为 0/1 bit 图."""
    rows: list[int] = []
    for row in matrix:
        scaled_row: list[int] = []
        for cell in row:
            scaled_row.extend([1 if cell else 0] * scale)
        for _ in range(scale):
            rows.extend(scaled_row)
    return bytes(rows)


def _finder_stamp() -> list[list[bool]]:
    """构造 7x7 Finder 样式矩阵."""
    stamp = [[False for _ in range(7)] for _ in range(7)]
    for y in range(7):
        for x in range(7):
            if x in (0, 6) or y in (0, 6):
                stamp[y][x] = True
            elif x in (1, 5) or y in (1, 5):
                stamp[y][x] = False
            else:
                stamp[y][x] = True
    return stamp


def _finder_grid_bits(count_x: int, count_y: int, gap: int = 2) -> tuple[bytes, int, int]:
    """构造包含大量 Finder 候选的 0/1 bit 图."""
    stamp = _finder_stamp()
    tile = 7 + gap
    width = count_x * tile
    height = count_y * tile
    bits = [[False for _ in range(width)] for _ in range(height)]

    for gy in range(count_y):
        for gx in range(count_x):
            ox = gx * tile
            oy = gy * tile
            for sy in range(7):
                for sx in range(7):
                    bits[oy + sy][ox + sx] = stamp[sy][sx]

    return _flatten_matrix_bits(bits), width, height


def test_open_bmp_unsupported_format(tmp_path):
    """验证 BMP 输入直接报不支持格式."""
    path = tmp_path / "x.bmp"
    path.write_bytes(b"BM")
    with pytest.raises(ValueError, match="Supported formats: JPEG, PNG, WEBP"):
        SimpleImage.open(path)


def test_open_gif_unsupported_format(tmp_path):
    """验证 GIF 输入直接报不支持格式."""
    path = tmp_path / "x.gif"
    path.write_bytes(b"GIF89a")
    with pytest.raises(ValueError, match="Supported formats: JPEG, PNG, WEBP"):
        SimpleImage.open(path)


def test_open_png_magic_ignores_file_suffix(monkeypatch, tmp_path):
    """验证打开图片时按魔数识别 PNG, 不依赖文件后缀."""
    monkeypatch.setattr(simple_image, "decode_png_with_libpng", lambda _data: ("RGB", 1, 1, bytes([1, 2, 3])))
    path = tmp_path / "x.bin"
    path.write_bytes(_png_fixture_bytes())
    img = SimpleImage.open(path)
    assert img.mode == "RGB"
    assert img.getpixel((0, 0)) == (1, 2, 3)


def test_from_bytes_rejects_corrupted_png_data():
    """验证损坏 PNG 输入会抛出 Python 异常而不是崩溃."""
    broken_png = _png_fixture_bytes()[:-10]
    with pytest.raises(ValueError, match="PNG decode failed"):
        SimpleImage.from_bytes(broken_png)


def test_convert_rgba_to_l_ignores_alpha_channel():
    """验证 RGBA 转灰度时仅按 RGB 通道计算."""
    img = SimpleImage.new("RGBA", (1, 1), (10, 20, 30, 0))
    gray = img.convert("L")
    assert gray.mode == "L"
    assert gray.getpixel((0, 0)) == (299 * 10 + 587 * 20 + 114 * 30) // 1000


def test_getbbox_nonwhite_rgb_returns_minimal_box():
    """验证 RGB 模式下 nonwhite 包围盒计算正确."""
    img = SimpleImage.new("RGB", (4, 4), (255, 255, 255))
    img.putpixel((2, 1), (0, 0, 0))
    img.putpixel((3, 2), (10, 255, 255))
    assert img.getbbox_nonwhite() == (2, 1, 4, 3)


def test_from_bytes_and_open_consistent_behavior(monkeypatch):
    """验证同一 JPEG 输入在 open 与 from_bytes 的行为一致."""
    jpeg_header = b"\xff\xd8\xff\xe0"
    monkeypatch.setattr(
        simple_image,
        "decode_jpeg_rgb",
        lambda raw: (1, 1, bytes([3, 2, 1])),
    )
    with patch("pathlib.Path.read_bytes", return_value=jpeg_header):
        img_from_open = SimpleImage.open(Path("x.jpg"))
    img_from_bytes = SimpleImage.from_bytes(jpeg_header)
    assert img_from_open.getpixel((0, 0)) == img_from_bytes.getpixel((0, 0))


def test_from_qr_matrix_builds_l_image(monkeypatch):
    """验证 from_qr_matrix 通过 C 接口构造 L 模式图像."""
    monkeypatch.setattr(simple_image._cimage, "qr_matrix_to_luma", lambda _m: (2, 1, bytes([0, 255])))
    img = SimpleImage.from_qr_matrix([[True, False]])
    assert img.mode == "L"
    assert (img.width, img.height) == (2, 1)
    assert img.getpixel((0, 0)) == 0
    assert img.getpixel((1, 0)) == 255


def test_from_qr_matrix_propagates_cimage_error(monkeypatch):
    """验证 from_qr_matrix 透传底层 C 接口异常."""

    def _raise(_m):
        raise ValueError("bad matrix")

    monkeypatch.setattr(simple_image._cimage, "qr_matrix_to_luma", _raise)
    with pytest.raises(ValueError, match="bad matrix"):
        SimpleImage.from_qr_matrix([[True]])


def test_qr_matrix_to_luma_rejects_rectangular_matrix():
    """验证底层 qr_matrix_to_luma 会拒绝矩形矩阵."""
    with pytest.raises(ValueError, match="bool square matrix"):
        _cimage.qr_matrix_to_luma([[True, False], [False, True], [True, False]])


def test_qr_matrix_to_luma_rejects_non_bool_cells():
    """验证底层 qr_matrix_to_luma 会拒绝非 bool 元素."""
    payload: Any = [[True, False], [1, True]]
    with pytest.raises(ValueError, match="only bool values"):
        _cimage.qr_matrix_to_luma(payload)


def test_qr_matrix_to_luma_accepts_bool_square_matrix():
    """验证底层 qr_matrix_to_luma 接受合法布尔方阵."""
    width, height, pixels = _cimage.qr_matrix_to_luma([[True, False], [False, True]])
    assert (width, height) == (2, 2)
    assert pixels == bytes([0, 255, 255, 0])


def test_resize_nearest_preserves_expected_quadrants():
    """验证最近邻缩放保持源像素象限分布."""
    resized = _cimage.resize_nearest(bytes([10, 20, 30, 40]), "L", 2, 2, 4, 4)
    assert resized == bytes(
        [
            10,
            10,
            20,
            20,
            10,
            10,
            20,
            20,
            30,
            30,
            40,
            40,
            30,
            30,
            40,
            40,
        ]
    )


def test_estimate_module_size_returns_scaled_checker_run_width():
    """验证模块尺寸估计在规则棋盘格上返回缩放后的 run 宽度."""
    matrix = [[(x + y) % 2 == 0 for x in range(9)] for y in range(9)]
    scale = 4
    bits = _flatten_matrix_bits(matrix, scale=scale)
    size = len(matrix) * scale
    module_size = _cimage.estimate_module_size(bits, size, size, (0, 0, size, size))
    assert module_size == pytest.approx(float(scale))


def test_sixel_encode_mono_preserves_expected_rle_output():
    """验证 sixel 单色编码的字面量与 RLE 输出保持稳定."""
    assert _cimage.sixel_encode_mono(bytes([0, 1]), 2, 1) == "#0@?$#1?@-"
    assert _cimage.sixel_encode_mono(bytes([1, 1, 1, 1]), 4, 1) == "#0!4?$#1!4@-"


def test_matrix_to_image_expands_rows_sequentially_for_rgb_and_rgba():
    """验证 matrix_to_image 在 RGB 和 RGBA 模式下保持像素展开结果."""
    bits = bytes([0, 1, 1, 0])
    rgb = _cimage.matrix_to_image(bits, 2, 2, 2, "RGB")
    rgba = _cimage.matrix_to_image(bits, 2, 2, 2, "RGBA")

    assert rgb == bytes(
        [
            255,
            255,
            255,
            255,
            255,
            255,
            0,
            0,
            0,
            0,
            0,
            0,
            255,
            255,
            255,
            255,
            255,
            255,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            255,
            255,
            255,
            255,
            255,
            255,
            0,
            0,
            0,
            0,
            0,
            0,
            255,
            255,
            255,
            255,
            255,
            255,
        ]
    )
    assert rgba == bytes(
        [
            255,
            255,
            255,
            255,
            255,
            255,
            255,
            255,
            0,
            0,
            0,
            255,
            0,
            0,
            0,
            255,
            255,
            255,
            255,
            255,
            255,
            255,
            255,
            255,
            0,
            0,
            0,
            255,
            0,
            0,
            0,
            255,
            0,
            0,
            0,
            255,
            0,
            0,
            0,
            255,
            255,
            255,
            255,
            255,
            255,
            255,
            255,
            255,
            0,
            0,
            0,
            255,
            0,
            0,
            0,
            255,
            255,
            255,
            255,
            255,
            255,
            255,
            255,
            255,
        ]
    )


def test_threshold_to_bits_respects_rgb_and_rgba_alpha_semantics():
    """验证 threshold_to_bits 在 RGB 与 RGBA 下保持阈值和透明像素语义."""
    rgb = _cimage.threshold_to_bits(bytes([0, 0, 0, 255, 255, 255]), "RGB", 2, 1, 128)
    rgba = _cimage.threshold_to_bits(
        bytes([0, 0, 0, 255, 0, 0, 0, 127, 255, 255, 255, 255]),
        "RGBA",
        3,
        1,
        128,
    )

    assert rgb == bytes([1, 0])
    assert rgba == bytes([1, 0, 0])


def test_sample_matrix_affine_matches_exact_axis_aligned_grid():
    """验证仿射采样在正常轴对齐网格下可还原原始矩阵."""
    matrix = [
        [True, False, True, False, True, False, True, False, True],
        [False, True, False, True, False, True, False, True, False],
        [True, True, False, False, True, True, False, False, True],
        [False, False, True, True, False, False, True, True, False],
        [True, False, False, True, True, False, False, True, True],
        [False, True, True, False, False, True, True, False, False],
        [True, False, True, False, True, False, True, False, True],
        [False, True, False, True, False, True, False, True, False],
        [True, True, True, False, False, False, True, True, True],
    ]
    scale = 5
    bits = _flatten_matrix_bits(matrix, scale=scale)
    size = len(matrix)
    tl = 3 * scale + (scale - 1) / 2
    h_span = (size - 7) * scale
    sampled = _cimage.sample_matrix_affine(bits, size * scale, size * scale, size, tl, tl, h_span, 0.0, 0.0, h_span, 1)
    assert sampled == _flatten_matrix_bits(matrix)


def test_sample_matrix_affine_handles_large_fixed_point_coordinates():
    """验证仿射采样在大坐标参数下仍稳定返回."""
    bits = bytes([1] * 64)
    sampled = _cimage.sample_matrix_affine(bits, 8, 8, 177, 1_000_000.0, 1_000_000.0, 750_000.0, 0.0, 0.0, 750_000.0, 1)
    assert len(sampled) == 177 * 177
    assert set(sampled) == {1}


def test_find_finder_centers_expands_candidate_capacity():
    """验证 Finder 候选超过初始容量时仍能找到靠近底部的中心."""
    bits, width, height = _finder_grid_bits(20, 20)
    centers = _cimage.find_finder_centers(bits, width, height, 0.8)
    assert centers is not None
    tlx, tly, trx, try_, blx, bly = centers
    assert tlx < 10 and tly < 10
    assert trx > 150 and try_ < 20
    assert blx < 20 and bly > 150
