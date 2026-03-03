"""对外 draw API 测试."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from terminal_qrcode import draw
from terminal_qrcode.contracts import ImageProtocol
from terminal_qrcode.core import TerminalCapability
from terminal_qrcode.simple_image import SimpleImage


class _PILLikeImage(ImageProtocol):
    """最小 PIL 风格图像桩对象."""

    mode = "RGB"
    size = (2, 2)

    def tobytes(self) -> bytes:
        return bytes(
            [
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
            ]
        )

    def convert(self, mode: str) -> ImageProtocol:
        _ = mode
        return self


@patch("terminal_qrcode.core.HalfBlockRenderer.render")
@patch("terminal_qrcode.probe.TerminalProbe.probe")
def test_draw_flat_kwargs_api(mock_probe, mock_render):
    """验证 draw 函数是否支持扁平化关键字参数并正确合并到 RenderConfig."""
    mock_probe.return_value = TerminalCapability.FALLBACK

    def dummy_gen(*args, **kwargs):
        yield "dummy_output"

    mock_render.side_effect = dummy_gen
    img = SimpleImage.new("RGB", (2, 2), color=(0, 0, 0))
    list(draw(img, scale=10, invert=True, ascii_only=True, fit=False, max_cols=60))

    args, _ = mock_render.call_args
    passed_config = args[1]
    assert passed_config.scale == 10
    assert passed_config.invert is True
    assert passed_config.ascii_only is True
    assert passed_config.fit is False
    assert passed_config.max_cols == 60


def test_draw_signature_hides_render_config():
    """验证 draw 对外签名不暴露内部 RenderConfig 参数."""
    import inspect

    signature = inspect.signature(draw)
    assert "config" not in signature.parameters


def test_draw_force_renderer_uses_literal_hint():
    """验证 draw.force_renderer 使用 Literal 以提供明确 IDE 提示."""
    from typing import get_type_hints

    from terminal_qrcode.contracts import RendererName

    hints = get_type_hints(draw)
    assert hints["force_renderer"] == RendererName | None


@patch("terminal_qrcode.core.run_pipeline")
def test_draw_delegates_to_pipeline(mock_run_pipeline):
    """验证 draw 会把编排委托给 pipeline 入口."""

    def _gen():
        yield "from_pipeline"

    mock_run_pipeline.return_value = _gen()
    img = SimpleImage.new("RGB", (1, 1), color=(0, 0, 0))
    chunks = list(draw(img))

    assert chunks == ["from_pipeline"]
    mock_run_pipeline.assert_called_once()


@patch("terminal_qrcode.core.run_pipeline")
def test_draw_result_supports_str_and_iteration(mock_run_pipeline):
    """验证 draw 返回对象同时支持直接字符串化与迭代."""

    def _gen():
        yield "a"
        yield "b"

    mock_run_pipeline.return_value = _gen()
    img = SimpleImage.new("RGB", (1, 1), color=(0, 0, 0))
    result = draw(img)

    assert str(result) == "ab"
    assert list(result) == ["a", "b"]


@patch("terminal_qrcode.core.run_pipeline")
def test_draw_result_supports_print_and_repeatable_iteration(mock_run_pipeline, capsys):
    """验证 draw 返回对象可直接 print 且可重复迭代."""
    import sys

    def _gen():
        yield "x"
        yield "y"

    mock_run_pipeline.return_value = _gen()
    img = SimpleImage.new("RGB", (1, 1), color=(0, 0, 0))
    result = draw(img)

    sys.stdout.write(str(result))
    out = capsys.readouterr().out
    assert out == "xy"
    assert list(result) == ["x", "y"]


def test_draw_rejects_invalid_payload_type():
    """验证 draw 对非法类型输入抛出异常."""
    payload: Any = 123
    with pytest.raises(TypeError, match="SimpleImage|ImageProtocol"):
        list(draw(payload))


def test_draw_accepts_pil_like_payload():
    """验证 draw 支持 PIL 风格图像协议对象输入."""
    payload = _PILLikeImage()
    chunks = list(draw(payload, force_renderer="halfblock", img_width=2))
    output = "".join(chunks)
    assert any(c in output for c in ("▄", "▀", "█", " "))


def test_draw_accepts_string_path_payload(tmp_path: Path):
    """验证 draw 支持字符串路径输入."""
    path = tmp_path / "x.png"
    image = SimpleImage.new("RGB", (2, 2), color=(0, 0, 0))
    path.write_bytes(image.to_png_bytes())

    chunks = list(draw(str(path), force_renderer="halfblock", img_width=2))
    output = "".join(chunks)
    assert any(c in output for c in ("▄", "▀", "█", " "))


def test_draw_accepts_path_payload(tmp_path: Path):
    """验证 draw 支持 Path 输入."""
    path = tmp_path / "x.png"
    image = SimpleImage.new("RGB", (2, 2), color=(0, 0, 0))
    path.write_bytes(image.to_png_bytes())

    chunks = list(draw(path, force_renderer="halfblock", img_width=2))
    output = "".join(chunks)
    assert any(c in output for c in ("▄", "▀", "█", " "))


def test_draw_accepts_png_bytes_payload():
    """验证 draw 支持 PNG bytes 输入."""
    payload = SimpleImage.new("RGB", (2, 2), color=(0, 0, 0)).to_png_bytes()
    chunks = list(draw(payload, force_renderer="halfblock", img_width=2))
    output = "".join(chunks)
    assert any(c in output for c in ("▄", "▀", "█", " "))


def test_draw_accepts_png_bytearray_payload():
    """验证 draw 支持 PNG bytearray 输入."""
    payload = bytearray(SimpleImage.new("RGB", (2, 2), color=(0, 0, 0)).to_png_bytes())
    chunks = list(draw(payload, force_renderer="halfblock", img_width=2))
    output = "".join(chunks)
    assert any(c in output for c in ("▄", "▀", "█", " "))


@patch("terminal_qrcode.core.run_pipeline")
def test_draw_fit_true_without_img_width_uses_none_override(mock_run_pipeline):
    """验证 draw(fit=True) 未显式传 img_width 时透传为 None."""

    def _gen():
        yield "ok"

    mock_run_pipeline.return_value = _gen()
    img = SimpleImage.new("RGB", (1, 1), color=(0, 0, 0))
    _ = list(draw(img, fit=True))

    _, kwargs = mock_run_pipeline.call_args
    overrides = kwargs["overrides"]
    assert overrides["fit"] is True
    assert overrides["img_width"] is None


@patch("terminal_qrcode.core.run_pipeline")
def test_draw_fit_true_with_explicit_img_width_override(mock_run_pipeline):
    """验证 draw(fit=True,img_width=60) 会显式透传宽度上限."""

    def _gen():
        yield "ok"

    mock_run_pipeline.return_value = _gen()
    img = SimpleImage.new("RGB", (1, 1), color=(0, 0, 0))
    _ = list(draw(img, fit=True, img_width=60))

    _, kwargs = mock_run_pipeline.call_args
    overrides = kwargs["overrides"]
    assert overrides["fit"] is True
    assert overrides["img_width"] == 60


def test_draw_fit_false_no_img_width_uses_internal_default():
    """验证 draw(fit=False) 未传 img_width 时使用内部默认宽度语义."""
    image = SimpleImage.new("L", (80, 20), color=0)
    chunks = list(draw(image, force_renderer="halfblock", fit=False))
    first_line = "".join(chunks).splitlines()[0]
    assert len(first_line) <= 40
