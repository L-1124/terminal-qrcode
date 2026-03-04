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

- PNG: `libpng`
- JPEG: `libjpeg-turbo`
- WEBP: `libwebp`

## 💻 支持的终端渲染器

- `kitty`（Kitty Graphics Protocol）
- `iterm2`（Inline Image Protocol）
- `wezterm`（iTerm2 兼容协议）
- `sixel`（DEC Sixel）
- `halfblock`（Unicode 半块字符降级）

## 🔧 CLI

```bash
python -m terminal_qrcode <image_path> [options]
```

## 🛠️ 本地开发

```bash
uv sync

# Windows
uv run python tools/bootstrap_deps.py
```

## 📄 License

MIT
