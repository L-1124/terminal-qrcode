"""对外 draw API 测试."""

import importlib
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import terminal_qrcode
from terminal_qrcode import DrawOutput, decode_and_redraw, draw, generate, layout
from terminal_qrcode.contracts import ImageProtocol, RenderConfig, TerminalCapabilities, TerminalColorLevel
from terminal_qrcode.core import RenderRequest, TerminalCapability
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


class _FakeQrcodeModule(ModuleType):
    """带已知属性的 qrcode 模块桩."""

    QRCode: type
    constants: SimpleNamespace


class _FakePyzbarModule(ModuleType):
    """带已知属性的 pyzbar 模块桩."""

    decode: object


def _make_fake_qrcode_module(qr_class: type) -> ModuleType:
    """构造最小 qrcode 模块桩."""
    module = _FakeQrcodeModule("qrcode")
    module.QRCode = qr_class
    module.constants = SimpleNamespace(ERROR_CORRECT_L=1, ERROR_CORRECT_M=2, ERROR_CORRECT_Q=3, ERROR_CORRECT_H=4)
    return module


def _make_fake_pyzbar_module(decode_func) -> ModuleType:
    """构造最小 pyzbar 模块桩."""
    module = _FakePyzbarModule("pyzbar.pyzbar")
    module.decode = decode_func
    return module


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


def test_optional_dependencies_are_lazy_after_module_reload():
    """验证模块导入后可选依赖仍保持未加载状态."""
    reloaded = importlib.reload(terminal_qrcode)
    assert reloaded._qrcode is reloaded._UNSET
    assert reloaded._pyzbar is reloaded._UNSET
    globals()["DrawOutput"] = reloaded.DrawOutput
    globals()["decode_and_redraw"] = reloaded.decode_and_redraw
    globals()["draw"] = reloaded.draw
    globals()["generate"] = reloaded.generate
    globals()["layout"] = reloaded.layout


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
    assert isinstance(request, RenderRequest)
    assert request.config.fit is True
    assert request.config.img_width is None


@patch("terminal_qrcode.core.run_pipeline")
def test_generate_returns_draw_output(mock_run_pipeline, monkeypatch):
    """验证 generate 返回 DrawOutput 并传递矩阵 payload."""

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
    fake_qrcode = _make_fake_qrcode_module(_FakeQRCode)
    monkeypatch.setattr(terminal_qrcode, "_qrcode", fake_qrcode)

    result = generate("hello", renderer="halfblock", img_width=2)
    assert isinstance(result, DrawOutput)
    assert str(result) == "qr"

    request = mock_run_pipeline.call_args.args[0]
    assert isinstance(request, RenderRequest)
    assert request.payload == [[True, False], [False, True]]
    assert request.config.renderer == "halfblock"


def test_generate_lazy_imports_qrcode(monkeypatch):
    """验证 generate 首次调用时才按需导入 qrcode."""

    class _FakeQRCode:
        def __init__(self, **_kwargs):
            pass

        def add_data(self, _data: str) -> None:
            pass

        def make(self, fit: bool = True) -> None:
            _ = fit

        def get_matrix(self) -> list[list[bool]]:
            return [[True, False], [False, True]]

    fake_qrcode = _make_fake_qrcode_module(_FakeQRCode)
    monkeypatch.setattr(terminal_qrcode, "_qrcode", terminal_qrcode._UNSET)

    def _fake_import(name: str):
        if name == "qrcode":
            return fake_qrcode
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(terminal_qrcode.importlib, "import_module", _fake_import)

    out = generate("hello", renderer="halfblock", img_width=2)
    assert str(out)
    assert terminal_qrcode._qrcode is fake_qrcode


def test_generate_rejects_inconsistent_matrix_width(monkeypatch):
    """验证 generate 对行宽不一致矩阵在渲染时抛 ValueError."""

    class _FakeQRCode:
        def __init__(self, **_kwargs):
            pass

        def add_data(self, _data: str) -> None:
            pass

        def make(self, fit: bool = True) -> None:
            _ = fit

        def get_matrix(self) -> list[list[bool]]:
            return [[True, False], [True]]

    fake_qrcode = _make_fake_qrcode_module(_FakeQRCode)
    monkeypatch.setattr(terminal_qrcode, "_qrcode", fake_qrcode)
    with pytest.raises(TypeError, match="consistent width"):
        _ = str(generate("hello", renderer="halfblock"))


def test_draw_rejects_removed_force_renderer_keyword():
    """验证 draw 不再接受 force_renderer 旧参数."""
    image = _render_matrix_to_image(_build_qr_like_matrix())
    with pytest.raises(TypeError, match="force_renderer"):
        _ = eval("draw(image, force_renderer='halfblock')", {"draw": terminal_qrcode.draw, "image": image})


def test_generate_rejects_removed_force_renderer_keyword():
    """验证 generate 不再接受 force_renderer 旧参数."""
    with pytest.raises(TypeError, match="force_renderer"):
        _ = eval("generate('hello', force_renderer='halfblock')", {"generate": terminal_qrcode.generate})


@patch("terminal_qrcode.core.strict_restore_qr_matrix")
def test_draw_best_effort_repair_uses_current_strict_restore(mock_restore):
    """验证 best_effort 当前临时复用 strict 恢复路径."""
    mock_restore.return_value = _build_qr_like_matrix()

    image = _render_matrix_to_image(_build_qr_like_matrix())
    _ = str(draw(image, renderer="halfblock", repair="best_effort", fit=False, img_width=80))

    args, _ = mock_restore.call_args
    passed_config = args[1]
    assert isinstance(passed_config, RenderConfig)
    assert passed_config.repair == "best_effort"


def test_decode_and_redraw_rebuilds_qr_payload(monkeypatch):
    """验证 decode_and_redraw 会先解码再重建二维码矩阵."""

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

    fake_qrcode = _make_fake_qrcode_module(_FakeQRCode)
    monkeypatch.setattr(terminal_qrcode, "_qrcode", fake_qrcode)
    monkeypatch.setattr(terminal_qrcode, "_pyzbar", _make_fake_pyzbar_module(_FakePyzarb.decode))

    source = _render_matrix_to_image(_build_qr_like_matrix())
    payload = decode_and_redraw(source)
    assert payload == [[True, False], [False, True]]


def test_decode_and_redraw_lazy_imports_optional_dependencies(monkeypatch):
    """验证 decode_and_redraw 首次调用时才按需导入可选依赖."""

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

    fake_qrcode = _make_fake_qrcode_module(_FakeQRCode)
    monkeypatch.setattr(terminal_qrcode, "_qrcode", terminal_qrcode._UNSET)
    monkeypatch.setattr(terminal_qrcode, "_pyzbar", terminal_qrcode._UNSET)

    def _fake_import(name: str):
        if name == "qrcode":
            return fake_qrcode
        if name == "pyzbar.pyzbar":
            return _make_fake_pyzbar_module(_FakePyzarb.decode)
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(terminal_qrcode.importlib, "import_module", _fake_import)

    source = _render_matrix_to_image(_build_qr_like_matrix())
    payload = decode_and_redraw(source)
    assert payload == [[True, False], [False, True]]


def test_decode_and_redraw_raises_when_not_decodable(monkeypatch):
    """验证 decode_and_redraw 在无法解码时抛 ValueError."""

    class _FakeQRCode:
        def __init__(self, **_kwargs):
            pass

        def add_data(self, _data):
            pass

        def make(self, fit: bool = True):
            _ = fit

        def get_matrix(self):
            return [[True, False], [False, True]]

    class _FakePyzarb:
        @staticmethod
        def decode(_raw):
            return []

    monkeypatch.setattr(terminal_qrcode, "_qrcode", _make_fake_qrcode_module(_FakeQRCode))
    monkeypatch.setattr(terminal_qrcode, "_pyzbar", _make_fake_pyzbar_module(_FakePyzarb.decode))
    source = _render_matrix_to_image(_build_qr_like_matrix())
    with pytest.raises(ValueError, match="Failed to decode QR payload"):
        _ = decode_and_redraw(source)


def test_decode_and_redraw_requires_pyzbar_dependency(monkeypatch):
    """验证 decode_and_redraw 缺少 pyzbar 依赖会报错."""

    class _FakeQRCode:
        def __init__(self, **_kwargs):
            pass

        def add_data(self, _data):
            pass

        def make(self, fit: bool = True):
            _ = fit

        def get_matrix(self):
            return [[True, False], [False, True]]

    monkeypatch.setattr(terminal_qrcode, "_qrcode", _make_fake_qrcode_module(_FakeQRCode))
    monkeypatch.setattr(terminal_qrcode, "_pyzbar", None)
    source = _render_matrix_to_image(_build_qr_like_matrix())
    with pytest.raises(RuntimeError, match="\\[pyzbar\\]"):
        _ = decode_and_redraw(source)
