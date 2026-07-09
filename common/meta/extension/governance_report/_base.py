"""Shared governance constants, yaml guard, gate metadata."""

from __future__ import annotations

from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CLI guard
    yaml = None


REPORT_VERSION = 1
SOURCE_ISSUE = "https://github.com/wangzitian0/finance_report/issues/822"
HLS_ISSUE = "https://github.com/wangzitian0/finance_report/issues/821"
GATE_ISSUE = "https://github.com/wangzitian0/finance_report/issues/823"
GATE_EXCEPTION_PATH = Path("docs/ssot/governance-exceptions.yaml")
GATE_HLS_RULE = (
    "HLS governance loop: promote only incremental and high-risk findings into "
    "CI gates after the report baseline is visible."
)

HIGH_RISK_SUBSTRINGS = (
    "migration",
    "environment",
    "deploy",
    "deployment",
    "secret",
    "secrets",
    "vault",
    "coverage",
    "evidence",
    "pipeline",
)
HIGH_RISK_TOKENS = {"ci", "env"}
MACHINE_OWNER_SUFFIXES = (".yaml", ".yml", ".json")
MACHINE_KINDS = {"machine_table", "baseline", "registry", "matrix"}
PROOF_MARKERS = (
    "tests/",
    "/tests/",
    "tools/",
    "common/",
    ".github/workflows/",
    "apps/",
    "libs/tests/",
    "platform/",
)
SSOT_FILE_SUFFIXES = {".md", ".yaml", ".yml", ".json"}
SSOT_FILE_EXCLUDES = {
    "README.md",
    "MANIFEST.yaml",
    "template.md",
    # Pointer stubs left behind by migration closeout wave 3 (#1664): content
    # moved into the named package readme, but the file stays as a redirect
    # for old relative links. Not orphaned — intentionally unowned by design.
    "reconciliation.md",
    "ai.md",
    "reporting.md",
    "assets.md",
    "market_data.md",
}
RATIO_EPSILON = 1e-9
PROTECTED_RATIO_LABELS = {
    "manifest_family_coverage": "Manifest family coverage",
    "manifest_kind_coverage": "Manifest kind coverage",
    "machine_proof_coverage": "Machine-owned proof coverage",
    "high_risk_proof_coverage": "High-risk proof coverage",
}
PROTECTED_DEBT_LABELS = {
    "missing_family": "Manifest entries missing family",
    "missing_kind": "Manifest entries missing kind",
    "machine_owner_entries_missing_proof": "Machine-owned entries missing proof",
    "high_risk_entries_missing_proof": "High-risk entries missing proof",
}


def _require_yaml() -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required. Run with: uv run --with pyyaml ...")
