"AC-platform.28.1"

from __future__ import annotations
from pathlib import Path
import pytest
from common.runtime.dev.compact_api_types import compact_api_types, main
from tools.compact_api_types import main as shim_main


def test_compact_empty_headers() -> None:
    raw = "responses: {\n  headers: {\n    [name: string]: unknown;\n  };\n};\n"
    expected = "responses: {\n  headers: { [name: string]: unknown; };\n};\n"
    assert compact_api_types(raw) == expected
    _m1_raw = "parameters: {\n  query?: never;\n  header?: never;\n  path?: never;\n  cookie?: never;\n};\n"
    _m1_expected = "parameters: { query?: never; header?: never; path?: never; cookie?: never; };\n"
    assert compact_api_types(_m1_raw) == _m1_expected
    _m2_raw = '200: {\n  headers: {\n    [name: string]: unknown;\n  };\n  content: {\n    "application/json": components["schemas"]["Item"];\n  };\n};\n'
    _m2_expected = '200: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["Item"]; }; };\n'
    assert compact_api_types(_m2_raw) == _m2_expected
    _m3_raw = '204: {\n  content: {\n    "application/json": unknown;\n  };\n};\n'
    _m3_expected = '204: { content: { "application/json": unknown; }; };\n'
    assert compact_api_types(_m3_raw) == _m3_expected
    _m4_raw = "404: {\n  headers: {\n    [name: string]: unknown;\n  };\n  content?: never;\n};\n"
    _m4_expected = "404: { headers: { [name: string]: unknown; }; content?: never; };\n"
    assert compact_api_types(_m4_raw) == _m4_expected
    _m5_raw = "operations: {\n  get?: never;\n  post?: never;\n  put?: never;\n}\n"
    _m5_expected = "operations: {\n  get?: never; post?: never; put?: never;\n}\n"
    assert compact_api_types(_m5_raw) == _m5_expected
    _m6_raw = (
        "parameters: {\n  header?: never;\n  path?: never;\n  cookie?: never;\n}\n"
    )
    _m6_expected = "parameters: {\n  header?: never; path?: never; cookie?: never;\n}\n"
    assert compact_api_types(_m6_raw) == _m6_expected
    _m7_api_types_path = Path("apps/frontend/src/lib/api-types.ts")
    if _m7_api_types_path.exists():
        _m7_content = _m7_api_types_path.read_text(encoding="utf-8")
        _m7_compacted = compact_api_types(_m7_content)
        assert _m7_compacted == _m7_content, (
            "apps/frontend/src/lib/api-types.ts should be cleanly compacted and idempotent"
        )


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
        "parameters: {\n  query?: never;\n  header?: never;\n  path?: never;\n  cookie?: never;\n};\n",
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


def test_compact_full_openapi_generic_aliases() -> None:
    sample = """/** doc */
export interface paths {
    "/items": {
        parameters: { query?: never; header?: never; path?: never; cookie?: never; };
        /** Get items */
        get: operations["list_items"];
        post: operations["create_item"];
        put?: never; delete?: never; options?: never; head?: never; patch?: never; trace?: never;
    };
    "/items/{id}": {
        parameters: { query?: never; header?: never; path?: never; cookie?: never; };
        delete: operations["delete_item"];
        get: operations["get_item"];
    };
}
export interface components {
    schemas: {
        ListResponse_Item_: { items: components["schemas"]["Item"][]; total: number; };
    };
}
export interface operations {
    list_items: {
        parameters: { query?: { limit?: number }; header?: never; path?: never; cookie?: never; };
        requestBody?: never;
        responses: {
            200: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ListResponse_Item_"]; }; };
            400: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            401: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            403: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            404: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            409: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            422: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["HTTPValidationError"]; }; };
            429: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            500: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
        };
    };
    create_item: {
        parameters: { query: { strict: boolean }; header?: never; path?: never; cookie?: never; };
        requestBody: { content: { "application/json": components["schemas"]["ItemCreate"]; }; };
        responses: {
            201: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["Item"]; }; };
            400: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            401: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            403: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            404: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            409: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            422: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["HTTPValidationError"]; }; };
            429: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            500: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
        };
    };
    get_item: {
        parameters: { query?: { full?: boolean }; header?: never; path: { id: string }; cookie?: never; };
        requestBody?: never;
        responses: {
            200: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["Item"]; }; };
            400: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            401: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            403: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            404: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            409: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            429: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            500: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
        };
    };
    delete_item: {
        parameters: { query?: never; header?: never; path: { id: string }; cookie?: never; };
        requestBody?: { content: { "application/json": components["schemas"]["DeleteBody"]; }; };
        responses: {
            204: { headers: { [name: string]: unknown; }; content?: never; };
            400: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            401: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            403: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            404: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            409: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            422: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["HTTPValidationError"]; }; };
            429: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
            500: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["ErrorResponse"]; }; };
        };
    };
}
"""
    compacted = compact_api_types(sample)
    assert (
        '"/items": _P<{ get: _O["list_items"]; post: _O["create_item"] }>;' in compacted
    )
    assert 'ListResponse_Item_: _LR<_S["Item"]>;' in compacted
    assert (
        'list_items: _Op<_S["ListResponse_Item_"], _QP<{ limit?: number }>>;'
        in compacted
    )
    assert (
        'create_item: _Op<_S["Item"], _QPR<{ strict: boolean }>, _S["ItemCreate"], 201>;'
        in compacted
    )
    assert (
        'get_item: _OpN<_S["Item"], _PQP<{ id: string }, { full?: boolean }>>;'
        in compacted
    )
    assert "responses: _R204;" in compacted
    assert compact_api_types(compacted) == compacted
