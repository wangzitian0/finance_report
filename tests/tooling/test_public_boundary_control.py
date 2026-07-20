from __future__ import annotations

from pathlib import Path

import pytest

from common.meta.extension import dependency_report


def test_AC_meta_public_boundary_1_snapshot_is_complete_and_single_source(
    tmp_path: Path,
) -> None:
    """AC-meta.public-boundary.1: all boundary kinds share one snapshot."""
    (tmp_path / "apps/frontend/src").mkdir(parents=True)
    (tmp_path / "apps/frontend/openapi.json").write_text(
        '{"paths":{"/things/{thing_id}":{"get":{"operationId":"get_thing"}}}}',
        encoding="utf-8",
    )
    (tmp_path / "apps/frontend/src/things.ts").write_text(
        'apiOperation("get_thing", { path: { thing_id: "1" } });\n',
        encoding="utf-8",
    )

    records = dependency_report.discover_delivery_boundaries(tmp_path)

    assert {(row["kind"], row["id"]) for row in records} == {
        ("openapi-operation", "get_thing"),
        ("frontend-operation-consumer", "get_thing@apps/frontend/src/things.ts:1"),
    }


def test_AC_meta_public_boundary_1_snapshot_projects_delivery_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-meta.public-boundary.1: delivery records are part of the shared snapshot."""
    monkeypatch.setattr(
        dependency_report,
        "_snapshot_packages",
        lambda _root: [dependency_report.SnapshotPackage("demo", (), (), (), None)],
    )
    monkeypatch.setattr(
        dependency_report,
        "discover_delivery_boundaries",
        lambda _root: [{"kind": "openapi-operation", "id": "get_thing"}],
    )

    snapshot = dependency_report.build_dependency_snapshot(tmp_path)

    assert snapshot["delivery_boundaries"] == [
        {"kind": "openapi-operation", "id": "get_thing"}
    ]


def test_AC_meta_public_boundary_2_financial_signatures_fail_closed() -> None:
    """AC-meta.public-boundary.2: dynamic financial command seams are rejected."""
    records = [
        {
            "package": "ledger",
            "symbol": "post_entries",
            "signature": "def(entries: list[dict], currency, posted_at) -> Any",
            "command_boundary": True,
        },
        {
            "package": "extraction",
            "symbol": "approve_statement",
            "signature": "def(command: ApproveStatement) -> ApprovalResult",
            "command_boundary": True,
        },
    ]

    assert dependency_report.financial_signature_findings(records) == [
        {
            "package": "ledger",
            "symbol": "post_entries",
            "codes": [
                "dynamic-mapping",
                "missing-currency-type",
                "missing-date-type",
                "dynamic-return",
            ],
        }
    ]


def test_AC_meta_public_boundary_3_frontend_uses_generated_operations(
    tmp_path: Path,
) -> None:
    """AC-meta.public-boundary.3: production calls cannot assert path/type separately."""
    source = tmp_path / "apps/frontend/src/page.tsx"
    source.parent.mkdir(parents=True)
    source.write_text(
        'apiFetch<Thing>("/api/things/1", { method: "GET" });\n',
        encoding="utf-8",
    )

    records = dependency_report.discover_frontend_operation_consumers(tmp_path)

    assert records[0]["classification"] == "untyped-api-fetch"
    assert records[0]["blocking"] is True


def test_AC_meta_public_boundary_3_scans_all_transports_and_ignores_comments(
    tmp_path: Path,
) -> None:
    """AC-meta.public-boundary.3: every production transport has one operation seam."""
    source = tmp_path / "apps/frontend/src/page.tsx"
    source.parent.mkdir(parents=True)
    source.write_text(
        """// apiFetch('/not-code')
/* apiDownload('/also-not-code') */
apiOperationDownload(
  "download_thing",
  { path: { thing_id: "1" } },
);
useApiQuery(["thing"], "get_thing", {});
apiUpload('/legacy', new FormData());
""",
        encoding="utf-8",
    )

    records = dependency_report.discover_frontend_operation_consumers(tmp_path)

    assert [(row["classification"], row["operation_id"]) for row in records] == [
        ("generated-operation", "download_thing"),
        ("generated-operation", "get_thing"),
        ("untyped-api-fetch", None),
    ]


def test_AC_meta_public_boundary_4_breaking_consumers_block() -> None:
    """AC-meta.public-boundary.4: every impacted consumer needs an exact proof."""
    report = {
        "removed_public_symbols": [
            {"package": "provider", "symbol": "old", "signature": "def() -> str"}
        ],
        "changed_public_symbols": [],
        "affected_consumers": {
            "provider": {
                "direct": ["middle"],
                "transitive": ["app", "middle"],
                "indirect": ["app"],
            }
        },
    }

    result = dependency_report.evaluate_boundary_compatibility(
        report,
        consumer_proofs={"middle": {"result": "passed", "strength": "exact"}},
    )

    assert result["status"] == "blocked"
    assert result["unproved_consumers"] == ["app"]
    assert result["breaking_changes"][0]["kind"] == "removed-public-symbol"


def test_AC_meta_public_boundary_4_openapi_change_requires_frontend_source_proof() -> (
    None
):
    """AC-meta.public-boundary.4: OpenAPI consumers are explicit proof subjects."""
    report = {
        "removed_public_symbols": [],
        "changed_public_symbols": [],
        "removed_delivery_boundaries": [],
        "changed_delivery_boundaries": [
            {"kind": "openapi-operation", "id": "get_thing"}
        ],
        "affected_consumers": {},
        "base": {
            "delivery_boundaries": [
                {
                    "kind": "frontend-operation-consumer",
                    "operation_id": "get_thing",
                    "source": "apps/frontend/src/page.tsx",
                }
            ]
        },
        "head": {"delivery_boundaries": []},
    }

    result = dependency_report.evaluate_boundary_compatibility(
        report, consumer_proofs={}
    )

    assert result["status"] == "blocked"
    assert result["unproved_consumers"] == ["apps/frontend/src/page.tsx"]


def test_AC_meta_public_boundary_4_defaulted_field_and_annotation_propagation_are_compatible() -> (
    None
):
    """AC-meta.public-boundary.4: compatible additions do not create fake migrations."""
    changed_type = {
        "package": "meta",
        "symbol": "Contract",
        "before": "pkg.py::Contract => class(BaseModel){name: str; active: bool=True}",
        "after": (
            "pkg.py::Contract => class(BaseModel){name: str; "
            "labels: list[str]=[]; active: bool=True}"
        ),
    }
    unchanged_declaration = {
        "package": "meta",
        "symbol": "project",
        "before": (
            "pkg.py::project => def(value: Contract) -> str "
            "[annotations: Contract=class(BaseModel){name: str}]"
        ),
        "after": (
            "pkg.py::project => def(value: Contract) -> str "
            "[annotations: Contract=class(BaseModel){name: str; labels: list[str]=[]}]"
        ),
    }
    report = {
        "removed_public_symbols": [],
        "changed_public_symbols": [changed_type, unchanged_declaration],
        "removed_delivery_boundaries": [],
        "changed_delivery_boundaries": [],
        "affected_consumers": {},
        "head": {"delivery_boundaries": [], "public_symbols": []},
    }

    result = dependency_report.evaluate_boundary_compatibility(
        report, consumer_proofs={}
    )

    assert result["status"] == "compatible"
    assert result["breaking_changes"] == []


def test_AC_meta_public_boundary_5_existing_gate_enforces_and_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-meta.public-boundary.5: the report exits red and emits observations."""
    report = {
        "added_edges": [],
        "removed_edges": [],
        "added_public_symbols": [],
        "removed_public_symbols": [],
        "changed_public_symbols": [],
        "affected_consumers": {},
        "compatibility": {
            "status": "blocked",
            "breaking_changes": [{"kind": "untyped-api-fetch", "id": "page.tsx:1"}],
            "unproved_consumers": [],
        },
    }
    monkeypatch.setattr(
        dependency_report, "build_impact_report", lambda _root, base_ref: report
    )
    observations = tmp_path / "observations.json"

    exit_code = dependency_report.main(
        [
            "--repo-root",
            str(tmp_path),
            "--base-ref",
            "base",
            "--fail-on-breaking",
            "--governance-observations-out",
            str(observations),
        ]
    )

    assert exit_code == 1
    payload = observations.read_text(encoding="utf-8")
    assert '"guarantee_id": "meta/one-boundary-graph"' in payload
    assert '"guarantee_id": "meta/enforced-compatibility"' in payload
    assert '"strength": "exact"' in payload


def test_AC_meta_public_boundary_5_untyped_and_unknown_consumers_block() -> None:
    """AC-meta.public-boundary.5: current delivery violations cannot be reported green."""
    report = {
        "removed_public_symbols": [],
        "changed_public_symbols": [],
        "removed_delivery_boundaries": [],
        "changed_delivery_boundaries": [],
        "affected_consumers": {},
        "head": {
            "public_symbols": [],
            "delivery_boundaries": [
                {"kind": "openapi-operation", "id": "known"},
                {
                    "kind": "frontend-operation-consumer",
                    "id": "untyped@app/page.tsx:1",
                    "classification": "untyped-api-fetch",
                },
                {
                    "kind": "frontend-operation-consumer",
                    "id": "missing@app/page.tsx:2",
                    "classification": "generated-operation",
                    "operation_id": "missing",
                },
            ],
        },
    }

    result = dependency_report.evaluate_boundary_compatibility(
        report, consumer_proofs={}
    )

    assert result["status"] == "blocked"
    assert [row["kind"] for row in result["breaking_changes"]] == [
        "untyped-api-fetch",
        "unknown-openapi-operation",
    ]
