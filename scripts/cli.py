"""开发测试用命令行工具."""

import argparse
import json
import logging
import os
import sys

from terminal_qrcode import draw
from terminal_qrcode.probe import TerminalProbe


def main():
    """CLI 入口点."""
    parser = argparse.ArgumentParser(description="Terminal Image Renderer")
    parser.add_argument(
        "image_path",
        nargs="?",
        help="图片路径",
    )
    parser.add_argument(
        "--detect",
        action="store_true",
        help="仅输出当前终端探测结果与关键环境参数",
    )
    parser.add_argument(
        "-r",
        "--renderer",
        choices=["auto", "kitty", "iterm2", "wezterm", "sixel", "halfblock"],
        default="auto",
        help="指定渲染器类型；auto 表示按终端能力自动选择",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="反转亮/暗像素点(由于不同终端颜色主题差异, 此选项有助于获得正确视觉效果)",
    )
    parser.add_argument(
        "--fit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="按终端字符列宽自动适配输出宽度",
    )
    parser.add_argument(
        "--max-cols",
        type=int,
        default=None,
        help="最大列宽上限（用于防止输出过宽）",
    )
    parser.add_argument(
        "--img-width",
        type=int,
        default=None,
        help="fit=True 时仅显式指定才作为列宽上限，fit=False 时未指定则使用默认 40 列",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="开启调试模式, 输出详细的环境探测与渲染流程日志",
    )

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
        try:
            from terminal_qrcode import layout

            term_cols, term_rows = layout._get_terminal_size_cells()
            avail_cols, avail_rows = layout._get_available_cells()
            logging.getLogger(__name__).debug(
                "terminal: %dx%d (avail %dx%d)", term_cols, term_rows, avail_cols, avail_rows
            )
        except Exception:  # noqa: BLE001
            pass

    if not args.detect and not args.image_path:
        parser.error("必须提供 image_path")

    try:
        if args.detect:
            probe = TerminalProbe()
            capabilities = probe.capabilities()
            payload = {
                "capability": capabilities.capability.name.lower(),
                "color_level": capabilities.color_level.name.lower(),
                "term": os.environ.get("TERM", ""),
                "term_program": os.environ.get("TERM_PROGRAM", ""),
                "tmux": bool(os.environ.get("TMUX", "")),
                "stdin_isatty": sys.stdin.isatty(),
                "stdout_isatty": sys.stdout.isatty(),
                "platform": sys.platform,
            }
            print(json.dumps(payload, ensure_ascii=False), flush=True)  # noqa: T201
            return

        image_path = args.image_path
        if not os.path.isfile(image_path):
            print(f"Error: Image file not found at '{image_path}'", file=sys.stderr)  # noqa: T201
            sys.exit(1)
        output = draw(
            image_path,
            renderer=args.renderer,
            invert=args.invert,
            fit=args.fit,
            max_cols=args.max_cols,
            img_width=args.img_width,
        )

        print(str(output), end="", flush=True)  # noqa: T201
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to parse image. {str(e)}", file=sys.stderr)  # noqa: T201
        sys.exit(1)


if __name__ == "__main__":
    main()
