"""OpenAPI specification, API types, generated references, vectors, and cross-layer contracts."""

from __future__ import annotations

import importlib
import json
import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from sqlalchemy import (
    CheckConstraint,
    Column,
    Enum,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
)

from common.meta.extension import generate_db_schema_reference as gdsr
from common.platform import api_response_vectors as arv_impl
from common.platform import generate_api_reference as gar
from common.platform import generate_openapi_spec as gen
from common.runtime.dev.compact_api_types import compact_api_types, main as compact_main
from tools import api_response_vectors as arv
from tools.compact_api_types import main as compact_shim_main

ROOT = Path(__file__).resolve().parents[2]


def test_AC12_28_1_openapi_generator_emits_deterministic_schema(monkeypatch) -> None:
    """AC-platform.28.1"""
    fake = {
        "openapi": "3.1.0",
        "paths": {"/accounts": {"get": {"responses": {"200": {}}}}},
        "components": {"schemas": {"ErrorResponse": {"type": "object"}}},
    }
    monkeypatch.setattr(gen, "load_openapi", lambda: fake)
    rendered = gen.generate()
    assert rendered == gen.render(fake)
    assert rendered.endswith("\n")
    assert '"ErrorResponse"' in rendered
    assert gen.render(fake) == gen.render(dict(reversed(list(fake.items()))))


def test_AC12_28_1_load_openapi_imports_backend_app(
    monkeypatch, tmp_path: Path
) -> None:
    """AC-platform.28.1"""
    monkeypatch.setattr(sys, "path", list(sys.path))
    fake_main = ModuleType("src.main")
    fake_main.app = SimpleNamespace(openapi=lambda: {"paths": {}})  # type: ignore[attr-defined]
    monkeypatch.setattr(gen, "BACKEND_ROOT", tmp_path)
    monkeypatch.setitem(sys.modules, "src", ModuleType("src"))
    monkeypatch.setitem(sys.modules, "src.main", fake_main)
    while str(tmp_path) in sys.path:
        sys.path.remove(str(tmp_path))
    assert gen.load_openapi() == {"paths": {}}
    assert str(tmp_path) in sys.path


def test_AC12_28_2_openapi_staleness_gate_and_json_pointer_diff(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-platform.28.2"""
    output = tmp_path / "openapi.json"
    monkeypatch.setattr(gen, "generate", lambda: '{"openapi": "3.1.0"}\n')
    output.write_text('{"openapi": "3.1.0"}\n', encoding="utf-8")
    assert gen.main(["--output", str(output), "--check"]) == 0

    output.write_text('{"openapi": "3.0.0"}\n', encoding="utf-8")
    assert gen.main(["--output", str(output), "--check"]) == 1
    assert "stale" in capsys.readouterr().err

    current = {"paths": {"/api/health": {"get": {"description": "old"}}}}
    rendered = {"paths": {"/api/health": {"get": {"description": "new"}}}}
    assert gen.diff_json_paths(current, rendered) == [
        "/paths/~1api~1health/get/description"
    ]

    large_doc = {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            f"/items/{i}": {
                "get": {
                    "description": f"Description for item {i}",
                    "responses": {"200": {"description": f"Success {i}"}},
                }
            }
            for i in range(500)
        },
    }
    large_rendered = gen.render(large_doc)
    assert len(large_rendered) > 50000
    modified_doc = dict(large_doc)
    modified_doc["paths"] = dict(large_doc["paths"])
    modified_doc["paths"]["/items/42"] = {
        "get": {
            "description": "Changed description",
            "responses": {"200": {"description": "Success 42"}},
        }
    }
    output.write_text(gen.render(modified_doc), encoding="utf-8")
    monkeypatch.setattr(gen, "generate", lambda: large_rendered)
    exit_code = gen.main(["--output", str(output), "--check"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "committed openapi.json is stale" in err
    assert "/paths/~1items~142/get/description" in err
    assert len(err) < 1000


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "responses: {\n  headers: {\n    [name: string]: unknown;\n  };\n};\n",
            "responses: {\n  headers: { [name: string]: unknown; };\n};\n",
        ),
        (
            "parameters: {\n  query?: never;\n  header?: never;\n  path?: never;\n  cookie?: never;\n};\n",
            "parameters: { query?: never; header?: never; path?: never; cookie?: never; };\n",
        ),
        (
            '200: {\n  headers: {\n    [name: string]: unknown;\n  };\n  content: {\n    "application/json": components["schemas"]["Item"];\n  };\n};\n',
            '200: { headers: { [name: string]: unknown; }; content: { "application/json": components["schemas"]["Item"]; }; };\n',
        ),
        (
            '204: {\n  content: {\n    "application/json": unknown;\n  };\n};\n',
            '204: { content: { "application/json": unknown; }; };\n',
        ),
        (
            "404: {\n  headers: {\n    [name: string]: unknown;\n  };\n  content?: never;\n};\n",
            "404: { headers: { [name: string]: unknown; }; content?: never; };\n",
        ),
        (
            "operations: {\n  get?: never;\n  post?: never;\n  put?: never;\n}\n",
            "operations: {\n  get?: never; post?: never; put?: never;\n}\n",
        ),
        (
            "parameters: {\n  header?: never;\n  path?: never;\n  cookie?: never;\n}\n",
            "parameters: {\n  header?: never; path?: never; cookie?: never;\n}\n",
        ),
    ],
)
def test_compact_api_types_patterns(raw: str, expected: str) -> None:
    """AC-platform.28.1"""
    assert compact_api_types(raw) == expected


def test_compact_api_types_repo_file_idempotent_and_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-platform.28.1"""
    api_types_path = ROOT / "apps/frontend/src/lib/api-types.ts"
    if api_types_path.exists():
        content = api_types_path.read_text(encoding="utf-8")
        assert compact_api_types(content) == content

    assert compact_main([]) == 1
    assert capsys.readouterr().err.startswith("Usage: compact_api_types.py")

    missing = tmp_path / "nonexistent.ts"
    assert compact_main([str(missing)]) == 1
    assert capsys.readouterr().err == f"Error: {missing} does not exist\n"

    target = tmp_path / "test.ts"
    target.write_text(
        "parameters: {\n  query?: never;\n  header?: never;\n  path?: never;\n  cookie?: never;\n};\n",
        encoding="utf-8",
    )
    assert compact_main([str(target)]) == 0
    assert (
        target.read_text(encoding="utf-8")
        == "parameters: { query?: never; header?: never; path?: never; cookie?: never; };\n"
    )
    assert capsys.readouterr().out.startswith("Compacted ")

    shim_target = tmp_path / "test_shim.ts"
    shim_target.write_text("export type X = 1;\n", encoding="utf-8")
    assert compact_shim_main([str(shim_target)]) == 0


def test_compact_full_openapi_generic_aliases() -> None:
    """AC-platform.28.1"""
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


def test_api_reference_render_and_cli(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC8.13.53"""
    schema = {
        "info": {"title": "Demo API", "version": "1.2.3"},
        "paths": {
            "/journal-entries": {
                "get": {
                    "tags": ["journal-entries"],
                    "summary": "List Journal Entries",
                    "security": [{"OAuth2PasswordBearer": []}],
                    "parameters": [
                        {
                            "name": "status_filter",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/JournalEntryList"
                                    }
                                }
                            }
                        }
                    },
                }
            },
            "/reconciliation/runs": {
                "post": {
                    "tags": ["reconciliation"],
                    "summary": "Run Reconciliation",
                    "security": [],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "$ref": "#/components/schemas/ReconciliationRunRequest"
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"content": {}},
                        "404": {
                            "content": {
                                "application/json": {"schema": {"type": "object"}}
                            }
                        },
                    },
                }
            },
            "/schemas": {
                "get": {
                    "tags": ["untagged"],
                    "summary": "Schema Samples",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "items": {
                                            "anyOf": [
                                                {"$ref": "#/components/schemas/A"},
                                                {
                                                    "allOf": [
                                                        {"type": "string"},
                                                        {"enum": ["x"]},
                                                    ]
                                                },
                                            ]
                                        }
                                    }
                                }
                            }
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {"JournalEntryList": {}, "ReconciliationRunRequest": {}}
        },
    }
    rendered = gar.render_openapi_reference(schema)
    assert "API title: `Demo API`" in rendered
    assert "| `GET` | `/journal-entries` | yes | `status_filter` (query)" in rendered
    assert "`ReconciliationRunRequest`" in rendered
    assert "array[`A` \\| string + enum]" in rendered
    assert "PUT /api/journal-entries" not in rendered

    ordered_schema = {
        "paths": {
            "/p": {m: {"tags": ["t"]} for m in ("trace", "head", "delete", "get")}
        }
    }
    ordered_text = gar.render_openapi_reference(ordered_schema)
    rows = [
        line.split("`")[1] for line in ordered_text.splitlines() if "| `/p` |" in line
    ]
    assert rows == ["GET", "DELETE", "HEAD", "TRACE"]

    committed = gar.OUTPUT_PATH.read_text(encoding="utf-8")
    assert "Generated by `python tools/generate_api_reference.py`" in committed
    assert "| `POST` | `/reconciliation/runs`" in committed
    assert "`ReconciliationRunRequest`" in committed
    assert "`account_id` (query)" not in committed
    assert (
        "`start_date` (query)"
        not in committed.split("`/reconciliation/runs`", 1)[1].split("\n", 1)[0]
    )
    assert "`PUT` | `/journal-entries/{entry_id}`" not in committed

    monkeypatch.setattr(
        gen, "load_openapi", lambda: {"info": {"title": "Loader Probe"}, "paths": {}}
    )
    assert gar.generate() == gar.render_openapi_reference(
        {"info": {"title": "Loader Probe"}, "paths": {}}
    )

    monkeypatch.setattr(gar, "generate", lambda: "# API\n")
    out = tmp_path / "nested" / "api.md"
    assert gar.main(["--output", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == "# API\n"
    assert gar.main(["--output", str(out), "--check"]) == 0

    missing = tmp_path / "missing.md"
    assert gar.main(["--output", str(missing), "--check"]) == 1
    assert "generated API reference is missing" in capsys.readouterr().err

    out.write_text("# Old\n", encoding="utf-8")
    monkeypatch.setattr(gar, "generate", lambda: "# New\n")
    assert gar.main(["--output", str(out), "--check"]) == 1
    stale_err = capsys.readouterr().err
    assert "generated API reference is stale" in stale_err
    assert "---" in stale_err and "+++" in stale_err


def test_AC14_1_17_db_schema_reference_render_and_cli(
    monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-meta.generated-refs.1"""
    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("email", String(255), nullable=False, unique=True, index=True),
    )
    Table(
        "journal_entries",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
        Column("status", Enum("draft", "posted", name="entry_status"), nullable=False),
        CheckConstraint("status <> ''", name="ck_journal_entries_status_non_empty"),
    )
    rendered = gdsr.render_db_schema_reference(metadata)
    assert "Table count: `2`" in rendered
    assert "Column count: `5`" in rendered
    assert "Enum type count: `1`" in rendered
    assert "| `journal_entries` | 3 | `id` | 1 | 1 |" in rendered
    assert "| `status` | `entry_status` | no | no | - | - |" in rendered
    assert (
        "| `entry_status` | yes | `draft`, `posted` | `journal_entries.status` |"
        in rendered
    )
    assert "| `journal_entries.user_id` | `users.id` |" in rendered
    assert "ck_journal_entries_status_non_empty" in rendered

    real_text = gdsr.generate()
    assert "Generated by `python tools/generate_db_schema_reference.py`" in real_text
    assert "Do not edit by hand" in real_text
    assert "| `accounts` |" in real_text
    assert "| `journal_entries` |" in real_text
    assert "`account_type_enum`" in real_text
    assert "`journal_entry_status_enum`" in real_text
    assert "## Foreign Keys" in real_text

    assert "docs/reference/db-schema.md" in (gdsr.REPO_ROOT / ".gitignore").read_text(
        encoding="utf-8"
    )
    mkdocs = (gdsr.REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "hooks:" in mkdocs and "docs/hooks.py" in mkdocs
    assert "generate_db_schema_reference.py" in (
        gdsr.REPO_ROOT / "docs/hooks.py"
    ).read_text(encoding="utf-8")

    real_metadata = gdsr._load_metadata()
    for table_name in ("accounts", "journal_entries", "statement_summaries"):
        assert table_name in real_metadata.tables

    monkeypatch.setattr(gdsr, "generate", lambda: "# DB\n")
    out = tmp_path / "nested" / "db-schema.md"
    assert gdsr.main(["--output", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == "# DB\n"
    assert gdsr.main(["--output", str(out), "--check"]) == 0

    missing = tmp_path / "missing.md"
    assert gdsr.main(["--output", str(missing), "--check"]) == 1
    assert "generated DB schema reference is missing" in capsys.readouterr().err

    out.write_text("# Old\n", encoding="utf-8")
    monkeypatch.setattr(gdsr, "generate", lambda: "# New\n")
    assert gdsr.main(["--output", str(out), "--check"]) == 1
    stale_err = capsys.readouterr().err
    assert "generated DB schema reference is stale" in stale_err
    assert "---" in stale_err and "+++" in stale_err


def test_api_response_vectors_committed_and_cli(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-reporting.api-vectors.1 AC-ledger.api-vectors.1 AC-extraction.api-vectors.1"""
    files = arv_impl.build_vector_files()
    assert arv.main is arv_impl.main
    assert len(files) == 3
    for path, payload in files.items():
        assert path.exists(), f"missing committed vector file: {path}"
        assert json.loads(path.read_text(encoding="utf-8")) == payload, (
            f"{path} drifted from tools/api_response_vectors.py output"
        )

    target = tmp_path / "pkg" / "conformance" / "vectors.json"
    monkeypatch.setattr(arv_impl, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(arv_impl, "build_vector_files", lambda: {target: {"probe": 1}})
    assert arv.main() == 0
    assert json.loads(target.read_text(encoding="utf-8")) == {"probe": 1}
    assert capsys.readouterr().out.strip().startswith("wrote ")

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(arv.__file__), run_name="__main__")
    assert exc.value.code == 0

    backend_root = str(arv.BACKEND_ROOT)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != backend_root])
    importlib.reload(arv)
    assert backend_root in sys.path


def test_retired_package_routes_absent_across_frontend_docs_and_e2e() -> None:
    retired = (
        "/api/reports/package/contract",
        "/api/reports/package/readiness",
        "/api/reports/package/framework-policy",
        "/api/reports/package/annualized-income-schedule",
        "/api/reports/package/notes",
        "/api/reports/package/traceability",
    )
    assert all(
        "/api/reports/package/readiness" not in p.read_text(encoding="utf-8")
        for p in (ROOT / "apps/frontend/src").rglob("*.ts*")
    )
    for rel in (
        "common/reporting/readme.md",
        "common/reporting/framework-reporting.md",
        "common/workflow/workflow-events.md",
        "common/pricing/readme.md",
        "docs/user-guide/reports.md",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for route in retired:
            assert route not in text, f"{rel} still references retired {route}"
    journey = (ROOT / "tests/e2e/test_personal_financial_report_package.py").read_text(
        encoding="utf-8"
    )
    assert all(r.removeprefix("/api") not in journey for r in retired)


def test_cross_layer_next_config_and_ci_contracts() -> None:
    next_cfg = next(
        (
            p
            for p in (
                ROOT / "apps/frontend/next.config.js",
                ROOT / "apps/frontend/next.config.mjs",
            )
            if p.exists()
        ),
        None,
    )
    assert next_cfg is not None and any(
        tok in next_cfg.read_text(encoding="utf-8")
        for tok in ("rewrites", "env", "destination", "BACKEND_URL")
    )
    ci_yml = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert (
        "backend:" in ci_yml
        and "frontend-vitest:" in ci_yml
        and "ac-traceability:" not in ci_yml
    )
    assert (ROOT / "tools/preflight.py").exists()
