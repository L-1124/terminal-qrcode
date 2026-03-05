# terminal-qrcode

[![Python 3.10+](https://img.shields.io/badge/Python-3.10|3.11|3.12|3.13|3.14-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

终端二维码图片渲染工具，支持图形协议与字符降级渲染。

## 📦 安装

基础安装：

```bash
uv add terminal-qrcode
```

启用二维码生成功能（`qrcode` 可选依赖）：

```bash
uv add "terminal-qrcode[qr]"
```

启用“先解码再重建”渲染增强（`pyzbar` + `qrcode`）：

```bash
uv add "terminal-qrcode[pyzarb]"
```

## ✨ Python API

```python
from terminal_qrcode import draw, generate

a = draw("test.png", force_renderer="halfblock")
print(a)

b = generate("https://github.com/L-1124/terminal-qrcode", force_renderer="halfblock")
print(b)

c = draw("blurred-qr.png", force_renderer="halfblock", decode_first=True)
print(c)
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

从文本直接生成并渲染二维码：

```bash
python -m terminal_qrcode -d "hello world"
echo "hello world" | python -m terminal_qrcode -d -
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
