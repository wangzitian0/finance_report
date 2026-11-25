from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

from common.meta.base.layering import PACKAGE_LAYER
from common.meta.base.user_case_proof import (
    ProofTier,
    derive_evidence_tier,
    derive_proof_tier,
    format_proof_tier_cell,
    summarize_registry_totals,
)

GAP_ISSUE_PATTERN = re.compile(r"#\d+(?:, #\d+)*")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_ssot_registry() -> dict:
    ssot_path = _repo_root() / "common/meta/flows/user_cases_ssot.json"
    assert ssot_path.exists(), f"SSOT registry missing at {ssot_path}"
    with open(ssot_path, encoding="utf-8") as f:
        return json.load(f)


def _all_user_cases() -> list[dict]:
    data = _load_ssot_registry()
    cases: list[dict] = []
    for domain in data.get("domains", []):
        for uc in domain.get("user_cases", []):
            cases.append({**uc, "domain_id": domain["id"], "domain_name": domain["name"]})
    return cases


def _normalize_openapi_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{param}", path)


@lru_cache(maxsize=1)
def _load_normalized_openapi_paths() -> dict[str, set[str]]:
    openapi_path = _repo_root() / "apps/frontend/openapi.json"
    assert openapi_path.exists(), f"OpenAPI spec missing at {openapi_path}"
    spec = json.loads(openapi_path.read_text(encoding="utf-8"))
    normalized: dict[str, set[str]] = {}
    for raw_path, methods in spec.get("paths", {}).items():
        norm_key = _normalize_openapi_path(raw_path)
        normalized.setdefault(norm_key, set()).update(m.lower() for m in methods.keys())
    return normalized


@lru_cache(maxsize=1)
def _load_frontend_component_index() -> tuple[set[str], str]:
    fe_src = _repo_root() / "apps/frontend/src"
    files = list(fe_src.rglob("*.tsx")) + list(fe_src.rglob("*.ts"))
    stems = {p.stem for p in files}
    combined_source = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files)
    return stems, combined_source


def _assert_real_test_file(repo_root: Path, rel_path: str, label: str) -> None:
    target = repo_root / rel_path
    assert target.exists(), f"{label} missing: {rel_path}"
    content = target.read_text(encoding="utf-8")
    if rel_path.endswith(".py"):
        assert re.search(r"^\s*(?:async\s+)?def\s+test_", content, re.MULTILINE), (
            f"{label} contains no Python test definition: {rel_path}"
        )
    else:
        assert re.search(r"\b(?:it|test)\s*\(", content), f"{label} contains no frontend test case: {rel_path}"


def test_ssot_registry_completeness_and_doc_sync() -> None:
    data = _load_ssot_registry()
    domains = data.get("domains", [])
    assert len(domains) == 8, f"Expected 8 domains, got {len(domains)}"
    assert [d["id"] for d in domains] == list(range(1, 9)), "Domain IDs must be contiguous 1..8"

    expected_ranges = [(1, 1, 5), (2, 6, 12), (3, 13, 20), (4, 21, 25), (5, 26, 30), (6, 31, 38), (7, 39, 45), (8, 46, 47)]
    by_domain = {d["id"]: d["user_cases"] for d in domains}
    for domain_id, start, end in expected_ranges:
        assert [u["id"] for u in by_domain[domain_id]] == [f"UC-{i:02d}" for i in range(start, end + 1)]

    cases = _all_user_cases()
    assert len(cases) == 47, f"Expected exactly 47 user cases, got {len(cases)}"
    assert [c["id"] for c in cases] == [f"UC-{i:02d}" for i in range(1, 48)]
    legacy_ids = sorted(c["legacy_flow_id"] for c in cases if c.get("legacy_flow_id") is not None)
    assert legacy_ids == list(range(1, 31)), "Legacy flow IDs 1..30 must be preserved 1:1"

    by_id = {c["id"]: c for c in cases}
    assert by_id["UC-42"]["frontend_test_ref"] == "apps/frontend/src/__tests__/cashFlowPage.test.tsx"
    assert by_id["UC-47"]["backend_test_ref"] == "apps/backend/tests/ai/test_ai_advisor_service.py"
    assert "LowConfidenceReviewModal" in by_id["UC-14"]["component"]
    assert "UnmatchedBoard" in by_id["UC-21"]["component"]
    assert "Stage2ReviewQueue" in by_id["UC-23"]["component"]
    assert "Accounting Equation" in by_id["UC-40"]["name"]
    assert by_id["UC-44"]["backend_endpoint"] == "GET /reports/package/snapshots/{snapshot_id}/exports"
    assert by_id["UC-32"]["gap_issue"] == "#2922" and by_id["UC-32"]["gap_kind"] == "partial"
    assert derive_proof_tier(by_id["UC-32"]) == ProofTier.L1_PARTIAL
    assert by_id["UC-38"]["gap_issue"] == "#2923" and by_id["UC-38"]["gap_kind"] == "partial"
    assert derive_proof_tier(by_id["UC-38"]) == ProofTier.L1_PARTIAL

    md_path = _repo_root() / "docs/reference/user-cases.md"
    assert md_path.exists(), f"Reference doc missing at {md_path}"
    md_text = md_path.read_text(encoding="utf-8")
    row_pattern = re.compile(
        r"^\|\s*\*\*(UC-\d{2})\*\*\s*\|\s*(.*?)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*\[`([^`]+)`\]"
    )
    parsed_rows: dict[str, dict[str, str]] = {}
    for line in md_text.splitlines():
        match = row_pattern.match(line.strip())
        if not match:
            continue
        uc_id = match.group(1)
        name_match = re.match(r"^(.*?)<br>\*\((.*?)\)\*$", match.group(2))
        assert name_match is not None, f"{uc_id} markdown name cell malformed: {match.group(2)}"
        parsed_rows[uc_id] = {
            "name": name_match.group(1),
            "title": name_match.group(2),
            "ui_surface": match.group(3),
            "component": match.group(4),
            "backend_endpoint": match.group(5),
            "invariant": match.group(6),
            "status_cell": match.group(7),
            "backend_test_ref": match.group(8),
        }

    assert set(parsed_rows.keys()) == set(by_id.keys())
    for uc_id, ssot_uc in sorted(by_id.items()):
        md_row = parsed_rows[uc_id]
        for field in ("name", "title", "ui_surface", "component", "backend_endpoint", "invariant", "backend_test_ref"):
            assert md_row[field] == ssot_uc[field], (
                f"{uc_id} markdown field '{field}' drifted: md={md_row[field]!r} vs ssot={ssot_uc[field]!r}"
            )
        expected_tier_cell = format_proof_tier_cell(ssot_uc)
        assert md_row["status_cell"] == expected_tier_cell, (
            f"{uc_id} markdown proof tier drifted: md={md_row['status_cell']!r} vs expected={expected_tier_cell!r}"
        )


def test_user_case_proof_tier_board_and_doc_sync() -> None:
    repo_root = _repo_root()
    data = _load_ssot_registry()
    domains = data.get("domains", [])
    totals = summarize_registry_totals(domains)
    assert totals["total"] == 47
    assert totals[ProofTier.L0_GAP.value] == 0

    assert derive_proof_tier({"gap_issue": "#1", "gap_kind": "gap"}) == ProofTier.L0_GAP
    assert derive_proof_tier({"gap_issue": "#1", "gap_kind": "partial"}) == ProofTier.L1_PARTIAL
    full_with_gap = {
        "gap_issue": "#1",
        "gap_kind": "partial",
        "e2e_test_ref": "tests/e2e/x.py",
        "benchmark_cases": ["1"],
    }
    assert derive_proof_tier(full_with_gap) == ProofTier.L1_PARTIAL
    assert derive_evidence_tier(full_with_gap) == ProofTier.L4_FULL_PROOF
    assert derive_proof_tier({"e2e_test_ref": None, "benchmark_cases": []}) == ProofTier.L2_SURFACE_CONTRACT
    assert derive_proof_tier({"e2e_test_ref": None, "benchmark_cases": ["1"]}) == ProofTier.L3_BENCH_PROVEN
    assert derive_proof_tier({"e2e_test_ref": "tests/e2e/x.py", "benchmark_cases": []}) == ProofTier.L3_E2E_PROVEN
    assert derive_proof_tier({"e2e_test_ref": "tests/e2e/x.py", "benchmark_cases": ["1"]}) == ProofTier.L4_FULL_PROOF

    md_text = (repo_root / "docs/reference/user-cases.md").read_text(encoding="utf-8")
    assert "## 2. Derived Proof-Tier Coverage Matrix" in md_text
    expected_total_row = (
        f"| **Total** | **{totals['total']}** "
        f"| **{totals[ProofTier.L4_FULL_PROOF.value]}** "
        f"| **{totals[ProofTier.L3_E2E_PROVEN.value]}** "
        f"| **{totals[ProofTier.L3_BENCH_PROVEN.value]}** "
        f"| **{totals[ProofTier.L2_SURFACE_CONTRACT.value]}** "
        f"| **{totals[ProofTier.L1_PARTIAL.value]}** "
        f"| **{totals[ProofTier.L0_GAP.value]}** |"
    )
    assert expected_total_row in md_text


@pytest.mark.parametrize("uc", _all_user_cases(), ids=lambda c: f"{c['id']}_{c['name'][:20]}")
def test_each_user_case_has_valid_contracts_and_test_evidence(uc: dict) -> None:
    repo_root = _repo_root()
    assert "test_ref" not in uc, f"{uc['id']} must not carry redundant test_ref key"
    assert "status" not in uc, f"{uc['id']} must not carry hand-authored status key; tier is derived"
    assert uc["name"].strip(), f"{uc['id']} missing name"
    assert uc["title"].strip(), f"{uc['id']} missing title"
    assert uc["ui_surface"].startswith("/"), f"{uc['id']} invalid ui_surface"
    assert uc["backend_endpoint"].strip(), f"{uc['id']} missing backend_endpoint"
    assert uc["invariant"].strip(), f"{uc['id']} missing invariant"
    assert uc["owning_packages"], f"{uc['id']} missing owning_packages"
    assert set(uc["owning_packages"]).issubset(PACKAGE_LAYER), f"{uc['id']} unknown owning_packages"

    gap_issue = uc.get("gap_issue")
    if gap_issue is not None:
        assert isinstance(gap_issue, str) and GAP_ISSUE_PATTERN.fullmatch(gap_issue), (
            f"{uc['id']} gap_issue must read '#N' or '#N, #M': {gap_issue!r}"
        )
        assert uc.get("gap_kind") in {"partial", "gap"}, f"{uc['id']} gap_issue requires gap_kind"
        assert derive_proof_tier(uc) in {ProofTier.L0_GAP, ProofTier.L1_PARTIAL}
    else:
        assert "gap_kind" not in uc, f"{uc['id']} must not set gap_kind without gap_issue"
        assert derive_proof_tier(uc) not in {ProofTier.L0_GAP, ProofTier.L1_PARTIAL}

    method, raw_path = uc["backend_endpoint"].split(" ", 1)
    norm_path = _normalize_openapi_path(raw_path)
    norm_api_path = _normalize_openapi_path(f"/api{raw_path}")
    openapi_paths = _load_normalized_openapi_paths()
    matched_methods = openapi_paths.get(norm_path, set()) | openapi_paths.get(norm_api_path, set())
    assert method.lower() in matched_methods, (
        f"{uc['id']} backend_endpoint '{uc['backend_endpoint']}' not found in apps/frontend/openapi.json"
    )

    comp = uc["component"].strip()
    assert comp, f"{uc['id']} missing component"
    stems, combined_source = _load_frontend_component_index()
    has_component = comp in stems or f"function {comp}" in combined_source or f"const {comp}" in combined_source
    assert has_component, f"{uc['id']} component '{comp}' not found under apps/frontend/src/"

    for ref_key in ("backend_test_ref", "frontend_test_ref"):
        ref_val = uc.get(ref_key)
        assert ref_val and ref_val.strip(), f"{uc['id']} missing {ref_key}"
        _assert_real_test_file(repo_root, ref_val, f"{uc['id']} {ref_key}")

    e2e_ref = uc.get("e2e_test_ref")
    if e2e_ref:
        _assert_real_test_file(repo_root, e2e_ref, f"{uc['id']} e2e_test_ref")

    for bench_case in uc.get("benchmark_cases", []):
        assert isinstance(bench_case, str) and bench_case.strip(), f"{uc['id']} invalid benchmark_cases entry"
        bench_file = repo_root / "tests/benchmarks/cases" / f"case_{bench_case}.py"
        assert bench_file.exists(), f"{uc['id']} benchmark case file missing: {bench_file}"
