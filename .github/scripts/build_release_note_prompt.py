"""Build ai-inference YAML prompt file for release notes generation."""

import argparse
import json
from pathlib import Path


def _indent_block(text: str, spaces: int) -> str:
    prefix = " " * spaces
    lines = text.splitlines() or [""]
    return "\n".join(f"{prefix}{line}" for line in lines)


def main() -> int:
    """Assemble YAML prompt consumed by actions/ai-inference."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-date", required=True)
    parser.add_argument("--changes-file", required=True)
    parser.add_argument("--compare-link", required=True)
    args = parser.parse_args()

    rules = Path(args.rules_file).read_text(encoding="utf-8").strip()
    changes_raw = Path(args.changes_file).read_text(encoding="utf-8").strip()
    if not changes_raw:
        changes_raw = "- 无可用提交摘要。"

    user_content = "\n".join(
        [
            f"version: {args.version}",
            f"release_date: {args.release_date}",
            "highlights:",
            "- 本次版本包含以下提交摘要，请按主题归纳后输出。",
            "changes_raw:",
            changes_raw,
            "breaking_changes:",
            "- 未显式提供。若提交中无明确信息，请省略该章节。",
            "deprecations:",
            "- 未显式提供。",
            "fixes:",
            "- 请从提交中提取 bugfix。",
            "perf_notes:",
            "- 请从提交中提取性能相关变更；无数据不要量化。",
            "api_cli_changes:",
            "- 请关注 python API 与 python -m terminal_qrcode CLI 参数/行为变化。",
            "compatibility_notes:",
            "- 请关注 Kitty/iTerm2/WezTerm/Sixel/Halfblock、Windows/POSIX、tmux 行为。",
            "install_cmd: uv add terminal-qrcode",
            "thanks:",
            "- 感谢所有贡献者。",
            f"compare_link: {args.compare_link}",
        ]
    )

    schema = {
        "name": "release_notes",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["version", "overview", "sections", "compare_link"],
            "properties": {
                "version": {"type": "string"},
                "overview": {"type": "string"},
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["title", "items"],
                        "properties": {
                            "title": {"type": "string"},
                            "items": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "install_commands": {"type": "array", "items": {"type": "string"}},
                "thanks": {"type": "array", "items": {"type": "string"}},
                "compare_link": {"type": "string"},
            },
        },
    }
    schema_json = json.dumps(schema, ensure_ascii=False, indent=2)

    yaml_text = "\n".join(
        [
            "messages:",
            "  - role: system",
            "    content: |-",
            _indent_block(rules, 6),
            "  - role: user",
            "    content: |-",
            _indent_block(user_content, 6),
            "model: openai/gpt-4o",
            "modelParameters:",
            "  temperature: 0.2",
            "  maxCompletionTokens: 1800",
            "responseFormat: json_schema",
            "jsonSchema: |-",
            _indent_block(schema_json, 2),
            "",
        ]
    )

    Path(args.output).write_text(yaml_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
