"""对外 draw API 测试."""

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import terminal_qrcode
from terminal_qrcode import DrawOutput, draw, generate, layout
from terminal_qrcode.contracts import ImageProtocol
from terminal_qrcode.core import TerminalCapability
from terminal_qrcode.simple_image import SimpleImage


@pytest.fixture(autouse=True)
def _mock_terminal_size(monkeypatch):
    monkeypatch.setattr(layout, "get_terminal_size", lambda fallback: os.terminal_size((80, 24)))


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


@patch("terminal_qrcode.renderers.HalfBlockRenderer.render")
@patch("terminal_qrcode.probe.TerminalProbe.probe")
def test_draw_flat_kwargs_api(mock_probe, mock_render):
    """验证 draw 函数是否支持扁平化关键字参数并正确合并到 RenderConfig."""
    mock_probe.return_value = TerminalCapability.FALLBACK

    def dummy_gen(*args, **kwargs):
        yield "dummy_output"

    mock_render.side_effect = dummy_gen
    img = SimpleImage.new("RGB", (2, 2), color=(0, 0, 0))
    list(draw(img, scale=10, invert=True, ascii_only=True, fit=False, max_cols=60, halfblock_mode="area"))

    args, _ = mock_render.call_args
    passed_config = args[1]
    assert passed_config.scale == 10
    assert passed_config.invert is True
    assert passed_config.ascii_only is True
    assert passed_config.fit is False
    assert passed_config.max_cols == 60
    assert passed_config.halfblock_mode == "area"


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


@pytest.mark.parametrize("payload_kind", ["str_path", "path", "bytes", "bytearray"])
def test_draw_accepts_supported_payload_types(tmp_path: Path, payload_kind: str):
    """验证 draw 支持字符串路径、Path、bytes 和 bytearray 输入."""
    image = SimpleImage.new("RGB", (2, 2), color=(0, 0, 0))
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


@patch("terminal_qrcode.core.run_pipeline")
def test_generate_returns_draw_output(mock_run_pipeline, monkeypatch):
    """验证 generate 返回 DrawOutput 并委托到渲染管线."""

    class _FakeQRCode:
        def __init__(self, **_kwargs):
            pass

        def add_data(self, _data: str) -> None:
            pass

        def make(self, fit: bool = True) -> None:
            _ = fit

        def get_matrix(self) -> list[list[bool]]:
            return [[True, False], [False, True]]

    def _gen():
        yield "q"
        yield "r"

    mock_run_pipeline.return_value = _gen()
    fake_qrcode = SimpleNamespace(
        QRCode=_FakeQRCode,
        constants=SimpleNamespace(
            ERROR_CORRECT_L=1,
            ERROR_CORRECT_M=2,
            ERROR_CORRECT_Q=3,
            ERROR_CORRECT_H=4,
        ),
    )
    monkeypatch.setattr(terminal_qrcode, "qrcode", fake_qrcode)

    result = generate("hello", force_renderer="halfblock", img_width=2, halfblock_mode="area")
    assert isinstance(result, DrawOutput)
    assert str(result) == "qr"

    args, kwargs = mock_run_pipeline.call_args
    payload = args[0]
    assert isinstance(payload, SimpleImage)
    assert payload.mode == "L"
    assert payload.width == 2
    assert payload.height == 2
    assert kwargs["overrides"]["force_renderer"] == "halfblock"
    assert kwargs["overrides"]["img_width"] == 2
    assert kwargs["overrides"]["halfblock_mode"] == "area"


def test_generate_rejects_invalid_ec_level(monkeypatch):
    """验证 generate 对非法 ec_level 抛出 ValueError."""

    class _FakeQRCode:
        def __init__(self, **_kwargs):
            pass

        def add_data(self, _data: str) -> None:
            pass

        def make(self, fit: bool = True) -> None:
            _ = fit

        def get_matrix(self) -> list[list[bool]]:
            return [[True]]

    fake_qrcode = SimpleNamespace(
        QRCode=_FakeQRCode,
        constants=SimpleNamespace(
            ERROR_CORRECT_L=1,
            ERROR_CORRECT_M=2,
            ERROR_CORRECT_Q=3,
            ERROR_CORRECT_H=4,
        ),
    )
    monkeypatch.setattr(terminal_qrcode, "qrcode", fake_qrcode)
    with pytest.raises(ValueError, match="ec_level"):
        generate("hello", ec_level="X")


def test_generate_requires_qrcode_dependency(monkeypatch):
    """验证 generate 在缺失 qrcode 依赖时抛出 RuntimeError."""
    monkeypatch.setattr(terminal_qrcode, "qrcode", None)
    with pytest.raises(RuntimeError, match="qrcode dependency is required"):
        generate("hello")


def test_generate_rejects_inconsistent_matrix_width(monkeypatch):
    """验证 generate 对行宽不一致矩阵抛出 ValueError."""

    class _FakeQRCode:
        def __init__(self, **_kwargs):
            pass

        def add_data(self, _data: str) -> None:
            pass

        def make(self, fit: bool = True) -> None:
            _ = fit

        def get_matrix(self) -> list[list[bool]]:
            return [[True, False], [True]]

    fake_qrcode = SimpleNamespace(
        QRCode=_FakeQRCode,
        constants=SimpleNamespace(
            ERROR_CORRECT_L=1,
            ERROR_CORRECT_M=2,
            ERROR_CORRECT_Q=3,
            ERROR_CORRECT_H=4,
        ),
    )
    monkeypatch.setattr(terminal_qrcode, "qrcode", fake_qrcode)
    with pytest.raises(ValueError, match="inconsistent width"):
        generate("hello")


@patch("terminal_qrcode.core.run_pipeline")
def test_draw_decode_first_rebuilds_qr_payload(mock_run_pipeline, monkeypatch):
    """验证 draw(decode_first=True) 会先解码再重建二维码图像."""

    class _FakeDecodeItem:
        type = "QRCODE"
        data = b"decoded"

    class _FakePyzarb:
        @staticmethod
        def decode(_raw):
            return [_FakeDecodeItem()]

    class _FakeQRCode:
        def __init__(self, **_kwargs):
            pass

        def add_data(self, _data):
            pass

        def make(self, fit: bool = True):
            _ = fit

        def get_matrix(self):
            return [[True, False], [False, True]]

    def _gen():
        yield "ok"

    mock_run_pipeline.return_value = _gen()
    fake_qrcode = SimpleNamespace(
        QRCode=_FakeQRCode,
        constants=SimpleNamespace(
            ERROR_CORRECT_L=1,
            ERROR_CORRECT_M=2,
            ERROR_CORRECT_Q=3,
            ERROR_CORRECT_H=4,
        ),
    )
    monkeypatch.setattr(terminal_qrcode, "qrcode", fake_qrcode)
    monkeypatch.setattr(terminal_qrcode, "pyzarb", _FakePyzarb())

    source = SimpleImage.new("L", (3, 3), color=255)
    _ = list(draw(source, decode_first=True, force_renderer="halfblock"))

    args, _kwargs = mock_run_pipeline.call_args
    payload = args[0]
    assert isinstance(payload, SimpleImage)
    assert (payload.width, payload.height) == (2, 2)


@patch("terminal_qrcode.core.run_pipeline")
def test_draw_decode_first_fallback_when_not_decodable(mock_run_pipeline, monkeypatch):
    """验证 draw(decode_first=True) 在无法解码时回退原图渲染."""

    class _FakePyzarb:
        @staticmethod
        def decode(_raw):
            return []

    def _gen():
        yield "ok"

    mock_run_pipeline.return_value = _gen()
    monkeypatch.setattr(terminal_qrcode, "pyzarb", _FakePyzarb())
    source = SimpleImage.new("L", (3, 3), color=255)
    _ = list(draw(source, decode_first=True, force_renderer="halfblock"))
    args, _kwargs = mock_run_pipeline.call_args
    assert args[0] is source


def test_draw_decode_first_requires_pyzarb_dependency(monkeypatch):
    """验证 draw(decode_first=True) 缺少 pyzarb 依赖会报错."""
    monkeypatch.setattr(terminal_qrcode, "pyzarb", None)
    source = SimpleImage.new("L", (1, 1), color=0)
    with pytest.raises(RuntimeError, match="\\[pyzarb\\]"):
        list(draw(source, decode_first=True, force_renderer="halfblock"))
