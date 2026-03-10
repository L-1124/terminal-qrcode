"""对外 API 测试 (draw & generate)."""

import io
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from terminal_qrcode import _layout as layout
from terminal_qrcode import draw, generate
from terminal_qrcode._contracts import ImageProtocol, TerminalCapabilities, TerminalColorLevel
from terminal_qrcode._core import TerminalCapability
from terminal_qrcode._simple_image import SimpleImage


@pytest.fixture(autouse=True)
def _mock_terminal_size(monkeypatch):
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((80, 24)))


def _build_qr_like_matrix(size: int = 25) -> list[list[bool]]:
    matrix = [[False for _ in range(size)] for _ in range(size)]

    def add_finder(ox: int, oy: int) -> None:
        for y in range(7):
            for x in range(7):
                if x in (0, 6) or y in (0, 6):
                    matrix[oy + y][ox + x] = True
                elif x in (1, 5) or y in (1, 5):
                    matrix[oy + y][ox + x] = False
                else:
                    matrix[oy + y][ox + x] = True

    add_finder(0, 0)
    add_finder(size - 7, 0)
    add_finder(0, size - 7)

    for y in range(size):
        for x in range(size):
            if matrix[y][x]:
                continue
            matrix[y][x] = ((x * 3 + y * 5) % 7) < 3
    return matrix


def _render_matrix_to_image(matrix: list[list[bool]], module: int = 4, quiet: int = 4) -> SimpleImage:
    size = len(matrix)
    image_size = (size + quiet * 2) * module
    img = SimpleImage.new("L", (image_size, image_size), color=255)
    for my, row in enumerate(matrix):
        for mx, cell in enumerate(row):
            value = 0 if cell else 255
            x0 = (mx + quiet) * module
            y0 = (my + quiet) * module
            for y in range(y0, y0 + module):
                for x in range(x0, x0 + module):
                    img.putpixel((x, y), value)
    return img


class _PILLikeImage(ImageProtocol):
    """最小 PIL 风格图像桩对象."""

    def __init__(self, matrix_image: SimpleImage) -> None:
        self._img = matrix_image.convert("RGB")
        self.mode = self._img.mode
        self.size = (self._img.width, self._img.height)

    def tobytes(self) -> bytes:
        return self._img.tobytes()

    def convert(self, mode: str) -> ImageProtocol:
        if mode == "L":
            return _PILLikeImage(self._img.convert("L"))
        if mode == "RGB":
            return _PILLikeImage(self._img.convert("RGB"))
        return _PILLikeImage(self._img.convert("RGBA"))


# --- Tests from test_api_draw.py ---


@patch("terminal_qrcode._renderers.HalfBlockRenderer.render")
@patch("terminal_qrcode._probe.TerminalProbe.probe")
def test_draw_flat_kwargs_api(mock_probe, mock_render):
    """验证 draw 扁平参数会合并到 RenderConfig."""
    mock_probe.return_value = TerminalCapability.FALLBACK

    def dummy_gen(*_args, **_kwargs):
        yield "dummy_output"

    mock_render.side_effect = dummy_gen
    img = _render_matrix_to_image(_build_qr_like_matrix())
    list(draw(img, renderer="auto", invert=True, fit=False, max_cols=60))

    args, _ = mock_render.call_args
    passed_config = args[1]
    assert passed_config.probe.renderer == "auto"
    assert passed_config.qr.invert is True
    assert passed_config.layout.fit is False
    assert passed_config.layout.max_cols == 60


@patch("terminal_qrcode._core.run_pipeline")
def test_draw_delegates_to_pipeline(mock_run_pipeline):
    """验证 draw 委托给 pipeline."""

    def _gen():
        yield "from_pipeline"

    mock_run_pipeline.return_value = _gen()
    img = _render_matrix_to_image(_build_qr_like_matrix())
    chunks = list(draw(img))

    assert chunks == ["from_pipeline"]
    mock_run_pipeline.assert_called_once()


@patch("terminal_qrcode._core.run_pipeline")
def test_draw_defers_pipeline_until_consumed(mock_run_pipeline):
    """验证 draw 在消费输出前不会启动 pipeline."""

    def _gen():
        yield "from_pipeline"

    mock_run_pipeline.return_value = _gen()
    img = _render_matrix_to_image(_build_qr_like_matrix())
    result = draw(img)

    mock_run_pipeline.assert_not_called()
    assert list(result) == ["from_pipeline"]
    mock_run_pipeline.assert_called_once()


@patch("terminal_qrcode._core.run_pipeline")
def test_draw_result_supports_str_and_iteration(mock_run_pipeline):
    """验证 draw 返回对象支持 print 与迭代."""

    def _gen():
        yield "a"
        yield "b"

    mock_run_pipeline.return_value = _gen()
    img = _render_matrix_to_image(_build_qr_like_matrix())
    result = draw(img)
    buffer = io.StringIO()

    result.print(file=buffer, flush=False)
    assert buffer.getvalue() == "ab"
    assert list(result) == ["a", "b"]


@patch("terminal_qrcode._core.run_pipeline")
def test_draw_result_rich_builds_halfblock_request(mock_run_pipeline):
    """验证 __rich__ 会重新构建固定 halfblock 的请求."""
    rich_text_mod = pytest.importorskip("rich.text")

    def _gen():
        yield "\x1b[30;47m▀▀\x1b[0m"

    mock_run_pipeline.return_value = _gen()
    img = _render_matrix_to_image(_build_qr_like_matrix())
    result = draw(img, renderer="kitty", preserve_source=True)

    rich_renderable = result.__rich__()

    assert isinstance(rich_renderable, rich_text_mod.Text)
    request = mock_run_pipeline.call_args.args[0]
    assert request.config.probe.renderer == "halfblock"
    assert request.config.qr.preserve_source is False


@patch("terminal_qrcode._core.run_pipeline")
def test_draw_result_rich_uses_cached_renderable(mock_run_pipeline):
    """验证 __rich__ 重复调用时复用缓存结果."""
    rich_text_mod = pytest.importorskip("rich.text")

    def _gen():
        yield "\x1b[30;47m▀▀\x1b[0m"

    mock_run_pipeline.return_value = _gen()
    img = _render_matrix_to_image(_build_qr_like_matrix())
    result = draw(img, renderer="kitty")

    first = result.__rich__()
    second = result.__rich__()

    assert isinstance(first, rich_text_mod.Text)
    assert first is second
    assert mock_run_pipeline.call_count == 1


@patch("terminal_qrcode._renderers.HalfBlockRenderer.render")
@patch("terminal_qrcode._probe.TerminalProbe.capabilities")
def test_draw_auto_detection_uses_single_capabilities_snapshot(mock_capabilities, mock_render):
    """验证 auto 路径只读取一次统一终端能力快照."""
    mock_capabilities.return_value = TerminalCapabilities(
        capability=TerminalCapability.FALLBACK,
        color_level=TerminalColorLevel.ANSI256,
    )

    def dummy_gen(*_args, **_kwargs):
        yield "dummy_output"

    mock_render.side_effect = dummy_gen
    img = _render_matrix_to_image(_build_qr_like_matrix())
    list(draw(img))

    assert mock_capabilities.call_count == 1


def test_draw_rejects_invalid_payload_type():
    """验证 draw 对非法类型输入抛出异常."""
    payload: Any = 123
    with pytest.raises(TypeError, match="SimpleImage|ImageProtocol"):
        list(draw(payload))


def test_draw_accepts_pil_like_payload():
    """验证 draw 支持 PIL 风格图像协议对象输入."""
    payload = _PILLikeImage(_render_matrix_to_image(_build_qr_like_matrix()))
    chunks = list(draw(payload, renderer="halfblock", fit=False, img_width=80))
    output = "".join(chunks)
    assert any(c in output for c in ("▄", "▀", "█", " "))


def test_draw_accepts_qrcode_base_image_payload():
    """验证 draw 支持 qrcode.image.BaseImage 包装对象输入."""
    base_mod = pytest.importorskip("qrcode.image.base")

    class _WrappedBaseImage(base_mod.BaseImage):
        def drawrect(self, row, col):
            _ = row, col

        def save(self, stream, kind=None):
            _ = stream, kind

        def new_image(self, **kwargs):
            _ = kwargs
            return _render_matrix_to_image(_build_qr_like_matrix())

    payload = _WrappedBaseImage(border=4, width=25, box_size=1, qrcode_modules=_build_qr_like_matrix())
    chunks = list(draw(payload, renderer="halfblock", fit=False, img_width=80))
    output = "".join(chunks)
    assert any(c in output for c in ("▄", "▀", "█", " "))


@pytest.mark.parametrize("payload_kind", ["str_path", "path", "bytes", "bytearray"])
def test_draw_accepts_supported_payload_types(tmp_path: Path, payload_kind: str):
    """验证 draw 支持路径和字节输入."""
    image = _render_matrix_to_image(_build_qr_like_matrix())
    png_bytes = image.to_png_bytes()
    path = tmp_path / "x.png"
    path.write_bytes(png_bytes)

    if payload_kind == "str_path":
        payload: Any = str(path)
    elif payload_kind == "path":
        payload = path
    elif payload_kind == "bytes":
        payload = png_bytes
    else:
        payload = bytearray(png_bytes)

    chunks = list(draw(payload, renderer="halfblock", fit=False, img_width=80))
    output = "".join(chunks)
    assert any(c in output for c in ("▄", "▀", "█", " "))


def test_draw_rejects_non_qr_image_with_value_error():
    """验证非二维码图像输入会硬中断抛 ValueError."""
    image = SimpleImage.new("RGB", (16, 16), color=(255, 255, 255))
    with pytest.raises(ValueError, match="Failed to decode QR matrix"):
        _ = "".join(draw(image, renderer="halfblock"))


def test_draw_graphic_protocol_rejects_non_qr_image():
    """验证图形协议路径下非二维码图像仍会硬中断."""
    image = SimpleImage.new("RGB", (8, 8), color=(12, 34, 56))
    with pytest.raises(ValueError, match="Failed to decode QR matrix"):
        _ = "".join(draw(image, renderer="kitty"))


def test_draw_graphic_protocol_can_render_raw_qr_image():
    """验证图形协议路径可直接传输原始二维码图片数据."""
    image = _render_matrix_to_image(_build_qr_like_matrix())
    out = "".join(draw(image, renderer="kitty"))
    assert out.startswith("\x1b_G")


def test_draw_preserve_source_rejects_invert_for_graphic_renderer():
    """验证 preserve_source 与 invert=True 在图形协议路径下互斥."""
    image = _render_matrix_to_image(_build_qr_like_matrix())
    with pytest.raises(ValueError, match="invert=True is not supported"):
        _ = "".join(draw(image, renderer="kitty", preserve_source=True, invert=True))


def test_draw_rejects_rectangular_matrix_payload():
    """验证 draw 会拒绝非方阵布尔矩阵输入."""
    matrix = [[True, False, True], [False, True, False]]
    with pytest.raises(TypeError, match="square QR matrix"):
        _ = "".join(draw(matrix, renderer="halfblock"))


def test_draw_rejects_non_bool_matrix_cells():
    """验证 draw 会拒绝包含非 bool 元素的矩阵输入."""
    payload: Any = [[True, False], [1, True]]
    with pytest.raises(TypeError, match="cells must be bool"):
        _ = "".join(draw(payload, renderer="halfblock"))


@patch("terminal_qrcode._core.run_pipeline")
def test_draw_fit_true_without_img_width_uses_none_override(mock_run_pipeline):
    """验证 draw(fit=True) 未显式传 img_width 时透传为 None."""

    def _gen():
        yield "ok"

    mock_run_pipeline.return_value = _gen()
    img = _render_matrix_to_image(_build_qr_like_matrix())
    _ = list(draw(img, fit=True))

    request = mock_run_pipeline.call_args.args[0]
    assert request.config.layout.fit is True
    assert request.config.layout.img_width is None


# --- Tests from test_api_generate.py ---


def test_generate_delegates_to_qrcode_and_draw():
    """验证 generate 正确委托给 qrcode 库并最终调用渲染流程."""
    # Mock qrcode 及其产生的矩阵
    mock_matrix = [[True, False], [False, True]]

    with patch("qrcode.QRCode") as mock_qr_class:
        mock_qr_instance = MagicMock()
        mock_qr_instance.get_matrix.return_value = mock_matrix
        mock_qr_class.return_value = mock_qr_instance

        # 调用 generate，使用 halfblock 以简化输出验证
        # 由于我们只验证委托逻辑，可以 mock 掉底层渲染
        with patch("terminal_qrcode._core.run_pipeline") as mock_pipeline:
            mock_pipeline.return_value = ["chunk1", "chunk2"]

            output = generate("test data", renderer="halfblock", error_correction="high", version=5)

            # 验证 qrcode 初始化参数
            mock_qr_class.assert_called_once()
            args, kwargs = mock_qr_class.call_args
            assert kwargs["version"] == 5
            from qrcode import constants

            assert kwargs["error_correction"] == constants.ERROR_CORRECT_H
            assert kwargs["border"] == 0

            # 验证数据添加
            mock_qr_instance.add_data.assert_called_once_with("test data")

            # 验证最终输出了 mock 的内容
            assert "".join(output) == "chunk1chunk2"


@pytest.mark.parametrize(
    "level,expected_const",
    [
        ("low", 1),  # ERROR_CORRECT_L
        ("medium", 0),  # ERROR_CORRECT_M
        ("quartile", 3),  # ERROR_CORRECT_Q
        ("high", 2),  # ERROR_CORRECT_H
    ],
)
def test_generate_error_correction_mapping(level, expected_const):
    """验证纠错等级字符串正确映射到 qrcode 常量."""
    with patch("qrcode.QRCode") as mock_qr_class:
        mock_qr_instance = MagicMock()
        mock_qr_instance.get_matrix.return_value = [[True]]
        mock_qr_class.return_value = mock_qr_instance

        with patch("terminal_qrcode._core.run_pipeline") as mock_pipeline:
            mock_pipeline.return_value = []
            generate("data", error_correction=level)

            _, kwargs = mock_qr_class.call_args
            assert kwargs["error_correction"] == expected_const


def test_generate_invalid_error_correction_raises_value_error():
    """验证非法纠错等级会显式抛出 ValueError."""
    with pytest.raises(ValueError, match="error_correction must be one of"):
        generate("data", error_correction="medum")  # type: ignore[arg-type]
