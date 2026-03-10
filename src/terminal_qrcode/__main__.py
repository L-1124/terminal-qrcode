"""开发测试用命令行工具."""

import argparse
import logging
import os
import sys

from terminal_qrcode import draw, generate


def main():
    """CLI 入口点."""
    parser = argparse.ArgumentParser(description="Terminal QR Code Generator & Renderer")
    parser.add_argument(
        "data",
        nargs="?",
        help="二维码文本内容 (默认行为)",
    )
    parser.add_argument(
        "-i",
        "--img",
        help="待渲染的图片路径",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="开启调试模式",
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

    if not args.data and not args.img:
        parser.error("必须提供文本内容或通过 -i/--img 提供图片路径")

    try:
        if args.img:
            # 渲染图片模式 (使用默认参数)
            if not os.path.isfile(args.img):
                print(f"Error: Image file not found at '{args.img}'", file=sys.stderr)  # noqa: T201
                sys.exit(1)
            output = draw(args.img)
        else:
            # 默认生成模式 (使用默认参数)
            output = generate(args.data)

        output.print()
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(1)
    except Exception as e:
        if args.debug:
            logging.exception("Failed to process request")
        print(f"Error: Failed to process request. {str(e)}", file=sys.stderr)  # noqa: T201
        sys.exit(1)


if __name__ == "__main__":
    main()
