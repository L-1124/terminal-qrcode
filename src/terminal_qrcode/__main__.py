"""命令行接口模块."""

import argparse
import logging
import os
import sys

from terminal_qrcode import draw, generate


def main():
    """CLI 入口点."""
    parser = argparse.ArgumentParser(description="Terminal Image Renderer")
    parser.add_argument(
        "image_path",
        nargs="?",
        help="图片路径",
    )
    parser.add_argument(
        "-d",
        "--data",
        help="二维码内容；传入 '-' 时从标准输入读取",
    )
    parser.add_argument(
        "-r",
        "--renderer",
        choices=["kitty", "iterm2", "wezterm", "sixel", "halfblock"],
        help="强制指定渲染器类型",
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

    # 初始化日志
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
                "Terminal size: term_cols=%s term_rows=%s avail_cols=%s avail_rows=%s",
                term_cols,
                term_rows,
                avail_cols,
                avail_rows,
            )
        except Exception:  # noqa: BLE001
            pass

    has_image_path = bool(args.image_path)
    has_data = args.data is not None
    if has_image_path and has_data:
        parser.error("image_path 与 --data 不能同时使用")
    if not has_image_path and not has_data:
        parser.error("必须提供 image_path 或 --data/-d")

    try:
        if has_data:
            text = sys.stdin.read() if args.data == "-" else args.data
            output = generate(
                text,
                force_renderer=args.renderer,
                invert=args.invert,
                fit=args.fit,
                max_cols=args.max_cols,
                img_width=args.img_width,
            )
        else:
            image_path = args.image_path
            if not os.path.isfile(image_path):
                sys.stderr.write(f"Error: Image file not found at '{image_path}'\n")
                sys.exit(1)
            output = draw(
                image_path,
                force_renderer=args.renderer,
                invert=args.invert,
                fit=args.fit,
                max_cols=args.max_cols,
                img_width=args.img_width,
            )

        sys.stdout.write(str(output))
        sys.stdout.flush()
    except BrokenPipeError:
        # 针对 Unix 下的 | head -n 1 等场景，优雅退出
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"Error: Failed to parse image. {str(e)}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
