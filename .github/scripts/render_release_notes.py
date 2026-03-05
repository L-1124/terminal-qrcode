"""Render structured release notes JSON into GitHub Release markdown."""

import argparse
import json
import sys
from pathlib import Path


def _render_markdown(payload: dict) -> str:
    version = str(payload.get("version", "")).strip()
    overview = str(payload.get("overview", "")).strip()
    sections = payload.get("sections", [])
    install_commands = payload.get("install_commands", [])
    thanks = payload.get("thanks", [])
    compare_link = str(payload.get("compare_link", "")).strip()

    lines: list[str] = [f"# terminal-qrcode v{version}", "", overview, ""]

    for section in sections:
        title = str(section.get("title", "")).strip()
        items = section.get("items", [])
        if not title or not items:
            continue
        lines.append(f"## {title}")
        lines.append("")
        for item in items:
            text = str(item).strip()
            if text:
                lines.append(f"- {text}")
        lines.append("")

    if install_commands:
        has_install_section = any(str(s.get("title", "")).strip() == "📦 安装与升级" for s in sections)
        if not has_install_section:
            lines.append("## 📦 安装与升级")
            lines.append("")
        lines.append("```bash")
        for cmd in install_commands:
            text = str(cmd).strip()
            if text:
                lines.append(text)
        lines.append("```")
        lines.append("")

    if thanks:
        has_thanks_section = any(str(s.get("title", "")).strip() == "🙏 致谢" for s in sections)
        if not has_thanks_section:
            lines.append("## 🙏 致谢")
            lines.append("")
        for item in thanks:
            text = str(item).strip()
            if text:
                lines.append(f"- {text}")
        lines.append("")

    if compare_link:
        lines.append(f"**Compare**: {compare_link}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    """Parse JSON payload and render markdown release notes."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"Invalid JSON from AI output: {exc}\n")
        return 1

    if not isinstance(payload, dict):
        sys.stderr.write("AI output must be a JSON object.\n")
        return 1

    markdown = _render_markdown(payload)
    output_path.write_text(markdown, encoding="utf-8")
    sys.stdout.write(f"Rendered release notes to {output_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
