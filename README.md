# terminal-qrcode

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/badge/lint-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Pytest](https://img.shields.io/badge/test-pytest-0A9EDC.svg)](https://docs.pytest.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

终端二维码图片渲染工具，支持图形协议与字符降级渲染。

## 📦 安装

```bash
uv add qrcode-terminal
```

## ✨ Python API

```python
from terminal_qrcode import draw

for chunk in draw("test.png", force_renderer="halfblock"):
    print(chunk, end="")
print()
```

## 🖼️ 支持的输入格式

- PNG
- JPEG
- WEBP

解码后端：

- PNG: `_cimage + libpng`
- JPEG: `_cimage + libjpeg-turbo`
- WEBP: `_cimage + libwebp`

不再包含 `cffi`、`djpeg/dwebp` 命令行回退和手写格式解析链路。

## 💻 支持的终端渲染器

- `kitty`（Kitty Graphics Protocol）
- `iterm2`（Inline Image Protocol）
- `wezterm`（iTerm2 兼容协议）
- `sixel`（DEC Sixel）
- `halfblock`（Unicode 半块字符降级）

自动探测失败时会回退到 `halfblock`。
`--ascii-only` 可进一步降级为纯 ASCII 块字符。
Sixel 渲染使用内置编码器，不依赖 libsixel 或 img2sixel。

## 🔧 CLI（可选）

```bash
python -m terminal_qrcode <image_path> [options]
```

常用参数：

- `-r, --renderer {kitty,iterm2,wezterm,sixel,halfblock}`
- `--fit / --no-fit`（默认 `--fit`）
- `--max-cols <int>`（最大列宽上限）
- `--img-width <int>`（`fit=True` 时作为上限之一；`fit=False` 时作为目标宽度）
- `--invert`
- `--ascii-only`
- `--debug`

## 🛠️ 本地开发依赖（Windows）

```bash
uv sync
uv run python tools/bootstrap_deps.py
```

## 📄 License

MIT
