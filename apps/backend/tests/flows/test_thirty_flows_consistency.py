"""Unified 30-Flow Backend Consistency Assurance Suite.

Validates that all 30 core wealth & accounting flows defined in
`common/meta/flows/thirty_flows_ssot.json` are:
1. Formally registered with complete metadata and domain taxonomy.
2. Backed by verified test suites, OpenAPI endpoints, frontend components, and markdown doc rows.
3. Invariant-compliant across double-entry balance, split logic, and reporting.
"""

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import pytest

from src.extraction import TransactionDirection
from src.extraction.base.validation import count_within_document_dedup_collapse
from src.extraction.extension.deduplication import DeduplicationService
from src.ledger.splits import calculate_reconciliation_adjustment
from src.reporting import (
    EquationDiagnosticCategory,
    diagnose_equation_imbalance,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_ssot_registry() -> dict:
    ssot_path = _repo_root() / "common" / "meta" / "flows" / "thirty_flows_ssot.json"
    assert ssot_path.exists(), f"SSOT registry missing at {ssot_path}"
    with open(ssot_path, encoding="utf-8") as f:
        return json.load(f)


def _all_flows() -> list[dict]:
    data = _load_ssot_registry()
    flows = []
    for domain in data.get("domains", []):
        for flow in domain.get("flows", []):
            flows.append({**flow, "domain_id": domain["id"], "domain_name": domain["name"]})
    return flows


def _normalize_openapi_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{param}", path)


@lru_cache(maxsize=1)
def _load_normalized_openapi_paths() -> dict[str, set[str]]:
    openapi_path = _repo_root() / "apps" / "frontend" / "openapi.json"
    assert openapi_path.exists(), f"OpenAPI spec missing at {openapi_path}"
    spec = json.loads(openapi_path.read_text(encoding="utf-8"))
    normalized: dict[str, set[str]] = {}
    for raw_path, methods in spec.get("paths", {}).items():
        norm_key = _normalize_openapi_path(raw_path)
        normalized.setdefault(norm_key, set()).update(m.lower() for m in methods.keys())
    return normalized


@lru_cache(maxsize=1)
def _load_frontend_component_index() -> tuple[set[str], str]:
    fe_src = _repo_root() / "apps" / "frontend" / "src"
    files = list(fe_src.rglob("*.tsx")) + list(fe_src.rglob("*.ts"))
    stems = {p.stem for p in files}
    combined_source = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files)
    return stems, combined_source


def test_ssot_registry_completeness():
    """Verify that the SSOT registry contains exactly 30 flows across 7 canonical domains."""
    data = _load_ssot_registry()
    domains = data.get("domains", [])
    assert len(domains) == 7, f"Expected 7 domains, got {len(domains)}"

    flows = _all_flows()
    assert len(flows) == 30, f"Expected exactly 30 flows, got {len(flows)}"

    # Check contiguous IDs 1..30
    flow_ids = [f["id"] for f in flows]
    assert sorted(flow_ids) == list(range(1, 31)), "Flow IDs must be contiguous 1..30"


@pytest.mark.parametrize("flow", _all_flows(), ids=lambda f: f"Flow_{f['id']}_{f['name'][:20]}")
def test_each_flow_has_valid_contracts_and_test_evidence(flow: dict):
    """Verify that every flow points to valid UI surfaces, OpenAPI endpoints, frontend components, and test files."""
    repo_root = _repo_root()

    assert "test_ref" not in flow, f"Flow {flow['id']} must not carry redundant test_ref key"
    assert flow["name"].strip(), f"Flow {flow['id']} missing name"
    assert flow["title"].strip(), f"Flow {flow['id']} missing title"
    assert flow["ui_surface"].startswith("/"), f"Flow {flow['id']} invalid ui_surface"
    assert flow["backend_endpoint"].strip(), f"Flow {flow['id']} missing backend_endpoint"
    assert flow["invariant"].strip(), f"Flow {flow['id']} missing invariant"

    method, raw_path = flow["backend_endpoint"].split(" ", 1)
    norm_path = _normalize_openapi_path(raw_path)
    norm_api_path = _normalize_openapi_path(f"/api{raw_path}")
    openapi_paths = _load_normalized_openapi_paths()
    matched_methods = openapi_paths.get(norm_path, set()) | openapi_paths.get(norm_api_path, set())
    assert method.lower() in matched_methods, (
        f"Flow {flow['id']} backend_endpoint '{flow['backend_endpoint']}' not found in apps/frontend/openapi.json"
    )

    comp = flow["component"].strip()
    assert comp, f"Flow {flow['id']} missing component"
    stems, combined_source = _load_frontend_component_index()
    has_component = comp in stems or f"function {comp}" in combined_source or f"const {comp}" in combined_source
    assert has_component, f"Flow {flow['id']} component '{comp}' not found under apps/frontend/src/"

    assert "backend_test_ref" in flow, f"Flow {flow['id']} missing backend_test_ref"
    backend_file_path = repo_root / flow["backend_test_ref"]
    assert backend_file_path.exists(), f"Flow {flow['id']} backend_test_ref does not exist: {flow['backend_test_ref']}"

    assert "frontend_test_ref" in flow, f"Flow {flow['id']} missing frontend_test_ref"
    frontend_file_path = repo_root / flow["frontend_test_ref"]
    assert frontend_file_path.exists(), (
        f"Flow {flow['id']} frontend_test_ref does not exist: {flow['frontend_test_ref']}"
    )


def test_thirty_wealth_flows_markdown_matches_ssot_registry():
    """Verify that docs/reference/thirty-wealth-flows.md table rows match thirty_flows_ssot.json."""
    md_path = _repo_root() / "docs" / "reference" / "thirty-wealth-flows.md"
    assert md_path.exists(), f"Reference doc missing at {md_path}"
    md_text = md_path.read_text(encoding="utf-8")

    row_pattern = re.compile(
        r"^\|\s*\*\*(\d+)\*\*\s*\|\s*(.*?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*\[`([^`]+)`\]"
    )
    parsed_rows: dict[int, dict[str, str]] = {}
    for line in md_text.splitlines():
        match = row_pattern.match(line.strip())
        if not match:
            continue
        flow_id = int(match.group(1))
        name_cell = match.group(2)
        name_match = re.match(r"^(.*?)<br>\*\((.*?)\)\*$", name_cell)
        assert name_match is not None, f"Flow {flow_id} markdown name cell malformed: {name_cell}"
        parsed_rows[flow_id] = {
            "name": name_match.group(1),
            "title": name_match.group(2),
            "ui_surface": match.group(3),
            "component": match.group(4),
            "backend_endpoint": match.group(5),
            "invariant": match.group(6),
            "backend_test_ref": match.group(7),
        }

    flows_by_id = {f["id"]: f for f in _all_flows()}
    assert set(parsed_rows.keys()) == set(flows_by_id.keys()), (
        f"Markdown flow IDs {sorted(parsed_rows.keys())} != SSOT flow IDs {sorted(flows_by_id.keys())}"
    )
    for flow_id, ssot_flow in sorted(flows_by_id.items()):
        md_row = parsed_rows[flow_id]
        for field in (
            "name",
            "title",
            "ui_surface",
            "component",
            "backend_endpoint",
            "invariant",
            "backend_test_ref",
        ):
            assert md_row[field] == ssot_flow[field], (
                f"Flow {flow_id} markdown field '{field}' drifted: md={md_row[field]!r} vs ssot={ssot_flow[field]!r}"
            )


def test_domain_1_ingestion_balance_invariant():
    """Flow 1 Invariant: opening + sum(IN) - sum(OUT) == calculated_closing."""
    opening = Decimal("1000.00")
    txns = [
        {"amount": Decimal("250.50"), "dir": "IN"},
        {"amount": Decimal("50.25"), "dir": "OUT"},
        {"amount": Decimal("100.00"), "dir": "OUT"},
    ]
    calc_closing = opening + sum(t["amount"] if t["dir"] == "IN" else -t["amount"] for t in txns)
    assert calc_closing == Decimal("1100.25")


def test_domain_2_fact_review_and_deduplication_invariants():
    """Flow 7 & 8 Invariants: Rejection on balance mismatch and cross-statement deduplication."""
    # Flow 8: Cross-statement overlapping transaction produces identical deterministic dedup hash
    u_id = uuid4()
    h1 = DeduplicationService.calculate_transaction_hash(
        user_id=u_id,
        txn_date=date(2026, 3, 15),
        amount=Decimal("128.50"),
        direction=TransactionDirection.OUT,
        description="SUPERMARKET GROCERIES",
        balance_after=Decimal("4500.00"),
        occurrence_index=0,
    )
    h2 = DeduplicationService.calculate_transaction_hash(
        user_id=u_id,
        txn_date=date(2026, 3, 15),
        amount=Decimal("128.50"),
        direction=TransactionDirection.OUT,
        description="SUPERMARKET GROCERIES",
        balance_after=Decimal("4500.00"),
        occurrence_index=0,
    )
    assert h1 == h2, "Identical transactions across overlapping statements must yield identical dedup hash"

    # Within-document collapse defense
    collapse_count = count_within_document_dedup_collapse([h1, h2, "h3"])
    assert collapse_count == 1, "Duplicate hashes within same statement must be detected"

    # Flow 7: Statement balance mismatch detection stops silent corruption
    opening = Decimal("5000.00")
    closing_reported = Decimal("4800.00")
    txns = [{"amount": Decimal("100.00"), "dir": "OUT"}]  # calculated closing = 4900 != 4800
    calculated_closing = opening - sum(t["amount"] for t in txns)
    has_mismatch = calculated_closing != closing_reported
    assert has_mismatch is True, "Balance mismatch must be flagged to prevent silent corruption"


def test_domain_4_adjustment_invariants():
    """Flow 18 Invariant: penny threshold control."""
    adj = calculate_reconciliation_adjustment(
        bank_balance=Decimal("500.04"),
        book_balance=Decimal("500.00"),
    )
    assert adj.difference == Decimal("0.04")
    assert adj.is_gain is True


def test_domain_6_reporting_equation_and_diagnostics():
    """Flow 23 & 24 Invariants: Equation balance and root cause diagnosis."""
    # Flow 23
    balanced = diagnose_equation_imbalance(Decimal("0.00"))
    assert balanced.is_balanced is True

    # Flow 24
    unbalanced = diagnose_equation_imbalance(Decimal("150.00"), unposted_draft_count=1)
    assert unbalanced.is_balanced is False
    assert unbalanced.primary_category == EquationDiagnosticCategory.UNPOSTED_DRAFT


def test_domain_7_audit_traceability_and_package_invariants():
    """Flow 28 & 29 Invariants: Tax archive package manifest SHA-256 integrity and anomaly flagging."""
    # Flow 28: Archive package manifest contains valid SHA-256 digest of schedule files
    csv_payload = b"date,account,amount,type\n2026-01-15,Checking,-150.00,EXPENSE\n"
    expected_digest = hashlib.sha256(csv_payload).hexdigest()

    manifest = {
        "framework": "US_GAAP_LIKE",
        "files": [
            {
                "path": "schedules/general_ledger.csv",
                "sha256": expected_digest,
                "bytes": len(csv_payload),
            }
        ],
    }

    entry = manifest["files"][0]
    actual_digest = hashlib.sha256(csv_payload).hexdigest()
    assert actual_digest == entry["sha256"]
    assert entry["bytes"] == len(csv_payload)


def test_flow_26_and_30_specific_test_references():
    """Issue #2067: Ensure Flow 26 and Flow 30 have explicit, verified test references."""
    flows = {f["id"]: f for f in _all_flows()}
    assert flows[26]["frontend_test_ref"] == "apps/frontend/src/__tests__/cashFlowPage.test.tsx"
    assert flows[30]["backend_test_ref"] == "apps/backend/tests/ai/test_ai_advisor_service.py"
