"""对外 draw API 测试."""

import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from terminal_qrcode import draw, layout
from terminal_qrcode.contracts import ImageProtocol, TerminalCapabilities, TerminalColorLevel
from terminal_qrcode.core import TerminalCapability
from terminal_qrcode.simple_image import SimpleImage


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


@patch("terminal_qrcode.renderers.HalfBlockRenderer.render")
@patch("terminal_qrcode.probe.TerminalProbe.probe")
def test_draw_flat_kwargs_api(mock_probe, mock_render):
    """验证 draw 扁平参数会合并到 RenderConfig."""
    mock_probe.return_value = TerminalCapability.FALLBACK

    def dummy_gen(*_args, **_kwargs):
        yield "dummy_output"

    mock_render.side_effect = dummy_gen
    img = _render_matrix_to_image(_build_qr_like_matrix())
    list(draw(img, renderer="auto", invert=True, color_level="ansi256", fit=False, max_cols=60, halfblock_mode="area"))

    args, _ = mock_render.call_args
    passed_config = args[1]
    assert passed_config.renderer == "auto"
    assert passed_config.invert is True
    assert passed_config.color_level == "ansi256"
    assert passed_config.fit is False
    assert passed_config.max_cols == 60
    assert passed_config.halfblock_mode == "area"


@patch("terminal_qrcode.core.run_pipeline")
def test_draw_delegates_to_pipeline(mock_run_pipeline):
    """验证 draw 委托给 pipeline."""

    def _gen():
        yield "from_pipeline"

    mock_run_pipeline.return_value = _gen()
    img = _render_matrix_to_image(_build_qr_like_matrix())
    chunks = list(draw(img))

    assert chunks == ["from_pipeline"]
    mock_run_pipeline.assert_called_once()


@patch("terminal_qrcode.core.run_pipeline")
def test_draw_result_supports_str_and_iteration(mock_run_pipeline):
    """验证 draw 返回对象支持字符串化与迭代."""

    def _gen():
        yield "a"
        yield "b"

    mock_run_pipeline.return_value = _gen()
    img = _render_matrix_to_image(_build_qr_like_matrix())
    result = draw(img)

    assert str(result) == "ab"
    assert list(result) == ["a", "b"]


@patch("terminal_qrcode.renderers.HalfBlockRenderer.render")
@patch("terminal_qrcode.probe.TerminalProbe.capabilities")
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
    args, _ = mock_render.call_args
    passed_config = args[1]
    assert passed_config.color_level == "ansi256"


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
        _ = str(draw(image, renderer="halfblock"))


def test_draw_graphic_protocol_rejects_non_qr_image():
    """验证图形协议路径下非二维码图像仍会硬中断."""
    image = SimpleImage.new("RGB", (8, 8), color=(12, 34, 56))
    with pytest.raises(ValueError, match="Failed to decode QR matrix"):
        _ = str(draw(image, renderer="kitty"))


def test_draw_graphic_protocol_can_render_raw_qr_image():
    """验证图形协议路径可直接传输原始二维码图片数据."""
    image = _render_matrix_to_image(_build_qr_like_matrix())
    out = str(draw(image, renderer="kitty"))
    assert out.startswith("\x1b_G")


@patch("terminal_qrcode.core.run_pipeline")
def test_draw_fit_true_without_img_width_uses_none_override(mock_run_pipeline):
    """验证 draw(fit=True) 未显式传 img_width 时透传为 None."""

    def _gen():
        yield "ok"

    mock_run_pipeline.return_value = _gen()
    img = _render_matrix_to_image(_build_qr_like_matrix())
    _ = list(draw(img, fit=True))

    request = mock_run_pipeline.call_args.args[0]
    assert request.config.fit is True
    assert request.config.img_width is None
