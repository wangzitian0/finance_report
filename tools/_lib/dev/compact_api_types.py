"""Deterministic compactor for generated OpenAPI TypeScript definitions.

Compacts repetitive boilerplate (empty parameters, generic headers, uniform
HTTP response mappings, and trailing never method lists) into compact TypeScript
declarations with exact type equivalence.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from pathlib import Path


def compact_api_types(content: str) -> str:
    # 1. Empty headers block
    p_hdr = re.compile(r"headers:\s*\{\s*\[name:\s*string\]:\s*unknown;\s*\};")
    content = p_hdr.sub("headers: { [name: string]: unknown; };", content)

    # 2. Empty parameters block
    p_param = re.compile(
        r"parameters:\s*\{\s*query\?:\s*never;\s*header\?:\s*never;\s*path\?:\s*never;\s*cookie\?:\s*never;\s*\};"
    )
    content = p_param.sub(
        "parameters: { query?: never; header?: never; path?: never; cookie?: never; };",
        content,
    )

    # 3. Response blocks with headers and content
    p_resp1 = re.compile(
        r'(\d+):\s*\{\s*headers:\s*\{\s*\[name:\s*string\]:\s*unknown;\s*\};\s*content:\s*\{\s*"application/json":\s*([^;]+);\s*\};\s*\};'
    )
    content = p_resp1.sub(
        r'\1: { headers: { [name: string]: unknown; }; content: { "application/json": \2; }; };',
        content,
    )

    # 4. Response blocks with only content
    p_resp2 = re.compile(
        r'(\d+):\s*\{\s*content:\s*\{\s*"application/json":\s*([^;]+);\s*\};\s*\};'
    )
    content = p_resp2.sub(r'\1: { content: { "application/json": \2; }; };', content)

    # 5. Response blocks with headers and content?: never
    p_resp3 = re.compile(
        r"(\d+):\s*\{\s*headers:\s*\{\s*\[name:\s*string\]:\s*unknown;\s*\};\s*content\?:\s*never;\s*\};"
    )
    content = p_resp3.sub(
        r"\1: { headers: { [name: string]: unknown; }; content?: never; };",
        content,
    )

    # 6. Consecutive method?: never;
    p_methods = re.compile(
        r"((?:^[ \t]*(?:get|post|put|delete|options|head|patch|trace)\?:\s*never;\r?\n){2,})",
        re.MULTILINE,
    )

    def repl_methods(m: re.Match[str]) -> str:
        lines = [line.strip() for line in m.group(1).splitlines() if line.strip()]
        indent = m.group(1)[: len(m.group(1)) - len(m.group(1).lstrip())]
        return indent + " ".join(lines) + "\n"

    content = p_methods.sub(repl_methods, content)

    # 7. Consecutive param?: never;
    p_params = re.compile(
        r"((?:^[ \t]*(?:header|path|cookie)\?:\s*never;\r?\n){2,})",
        re.MULTILINE,
    )

    def repl_params(m: re.Match[str]) -> str:
        lines = [line.strip() for line in m.group(1).splitlines() if line.strip()]
        indent = m.group(1)[: len(m.group(1)) - len(m.group(1).lstrip())]
        return indent + " ".join(lines) + "\n"

    content = p_params.sub(repl_params, content)
    return content


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: compact_api_types.py <path-to-api-types.ts>", file=sys.stderr)
        return 1

    target = Path(args[0])
    if not target.exists():
        print(f"Error: {target} does not exist", file=sys.stderr)
        return 1

    raw = target.read_text(encoding="utf-8")
    orig_lines = len(raw.splitlines())
    compacted = compact_api_types(raw)
    new_lines = len(compacted.splitlines())

    target.write_text(compacted, encoding="utf-8")
    print(
        f"Compacted {target}: {orig_lines} -> {new_lines} lines (saved {orig_lines - new_lines} LOC)"
    )
    return 0
