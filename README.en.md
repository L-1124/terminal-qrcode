# terminal-qrcode

[![Python 3.10+](https://img.shields.io/badge/Python-3.10|3.11|3.12|3.13|3.14-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

English | [简体中文](./README.md)

A terminal image renderer supporting multiple graphic protocols, fallback rendering, and terminal capability detection.

## 📦 Installation

Basic installation:

```bash
uv add terminal-qrcode
```

## ✨ API

```python
from terminal_qrcode import draw, generate

# 1. Render an existing image
out = draw("test.png", renderer="halfblock")
out.print()

# 2. Generate a QR code from text
qr = generate("https://github.com", renderer="auto")
qr.print()
```

When used with **Rich**, `console.print(draw(...))` or `console.print(generate(...))` will force `halfblock` text rendering:

```python
from rich.console import Console
from terminal_qrcode import generate

console = Console()
console.print(generate("https://github.com"))
```

## 🖼️ Supported Image Formats

- PNG
- JPEG
- WEBP

Decoding Backends:

- PNG: `libpng`
- JPEG: `libjpeg-turbo`
- WEBP: `libwebp`

## 🧩 API Input Support

- Local image path: `str` / `pathlib.Path`
- Raw image bytes: `bytes` / `bytearray`
- PIL-compatible Image objects
- `qrcode.image.BaseImage` wrapper objects
- QR Boolean Square Matrix: `list[list[bool]]`

## 💻 Supported Terminal Renderers

- `kitty` (Kitty Graphics Protocol)
- `iterm2` (Inline Image Protocol)
- `wezterm` (iTerm2 compatible protocol)
- `sixel` (DEC Sixel)
- `halfblock` (Unicode half-block fallback)

## 🔧 CLI

```bash
# 1. Generate QR code from text (Default behavior)
$ terminal_qrcode "https://github.com"

# 2. Render an existing image
$ terminal_qrcode -i qrcode.png
```

## 🛠️ Local Development

```bash
# Install development dependencies
$ uv sync

# Run Windows development installation script
$ uv run --no-project python scripts/install-dev.py
uv sync
```

## 📄 License

MIT
