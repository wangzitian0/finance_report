"""Tests for tools/_lib/dev/compact_api_types.py and tools/compact_api_types.py.

AC-platform.28.1: Verifies deterministic compaction of OpenAPI TypeScript definitions
and CLI behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools._lib.dev.compact_api_types import compact_api_types, main
from tools.compact_api_types import main as shim_main


def test_compact_empty_headers() -> None:
    raw = "responses: {\n  headers: {\n    [name: string]: unknown;\n  };\n};\n"
    expected = "responses: {\n  headers: { [name: string]: unknown; };\n};\n"
    assert compact_api_types(raw) == expected


def test_compact_empty_parameters() -> None:
    raw = (
        "parameters: {\n"
        "  query?: never;\n"
        "  header?: never;\n"
        "  path?: never;\n"
        "  cookie?: never;\n"
        "};\n"
    )
    expected = "parameters: { query?: never; header?: never; path?: never; cookie?: never; };\n"
    assert compact_api_types(raw) == expected


def test_compact_response_with_headers_and_content() -> None:
    raw = (
        "200: {\n"
        "  headers: {\n"
        "    [name: string]: unknown;\n"
        "  };\n"
        "  content: {\n"
        '    "application/json": components["schemas"]["Item"];\n'
        "  };\n"
        "};\n"
    )
    expected = '200: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["Item"]; }; };\n'
    assert compact_api_types(raw) == expected


def test_compact_response_with_only_content() -> None:
    raw = '204: {\n  content: {\n    "application/json": unknown;\n  };\n};\n'
    expected = '204: { content: { "application/json": unknown; }; };\n'
    assert compact_api_types(raw) == expected


def test_compact_response_with_headers_and_never_content() -> None:
    raw = (
        "404: {\n"
        "  headers: {\n"
        "    [name: string]: unknown;\n"
        "  };\n"
        "  content?: never;\n"
        "};\n"
    )
    expected = "404: { headers: { [name: string]: unknown; }; content?: never; };\n"
    assert compact_api_types(raw) == expected


def test_compact_consecutive_methods() -> None:
    raw = "operations: {\n  get?: never;\n  post?: never;\n  put?: never;\n}\n"
    expected = "operations: {\n  get?: never; post?: never; put?: never;\n}\n"
    assert compact_api_types(raw) == expected


def test_compact_consecutive_params() -> None:
    raw = "parameters: {\n  header?: never;\n  path?: never;\n  cookie?: never;\n}\n"
    expected = "parameters: {\n  header?: never; path?: never; cookie?: never;\n}\n"
    assert compact_api_types(raw) == expected


def test_main_no_args(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([])
    assert rc == 1
    err = capsys.readouterr().err
    expected_usage = "Usage: compact_api_types.py"
    assert err.startswith(expected_usage)


def test_main_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "nonexistent.ts"
    rc = main([str(target)])
    assert rc == 1
    err = capsys.readouterr().err
    expected_err = f"Error: {target} does not exist\n"
    assert err == expected_err


def test_main_compaction_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "test.ts"
    target.write_text(
        "parameters: {\n"
        "  query?: never;\n"
        "  header?: never;\n"
        "  path?: never;\n"
        "  cookie?: never;\n"
        "};\n",
        encoding="utf-8",
    )
    rc = main([str(target)])
    assert rc == 0
    expected_content = "parameters: { query?: never; header?: never; path?: never; cookie?: never; };\n"
    assert target.read_text(encoding="utf-8") == expected_content
    out = capsys.readouterr().out
    assert out.startswith("Compacted ")


def test_shim_main_invocation(tmp_path: Path) -> None:
    target = tmp_path / "test_shim.ts"
    target.write_text("export type X = 1;\n", encoding="utf-8")
    rc = shim_main([str(target)])
    assert rc == 0


def test_idempotent_on_committed_api_types() -> None:
    api_types_path = Path("apps/frontend/src/lib/api-types.ts")
    if api_types_path.exists():
        content = api_types_path.read_text(encoding="utf-8")
        compacted = compact_api_types(content)
        assert compacted == content, (
            "apps/frontend/src/lib/api-types.ts should be cleanly compacted and idempotent"
        )
