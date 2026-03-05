# terminal-qrcode

[![Python 3.10+](https://img.shields.io/badge/Python-3.10|3.11|3.12|3.13|3.14-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

终端二维码图片渲染工具，支持图形协议与字符降级渲染。

## 📦 安装

```bash
uv add terminal-terminal
```

## ✨ Python API

```python
from terminal_qrcode import draw

a = draw("test.png", force_renderer="halfblock"):
print(a)
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
```

Windows

```bash
uv run --no-project python tools/bootstrap_deps.py
uv sync
```

## 📄 License

MIT
