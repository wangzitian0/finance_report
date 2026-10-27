"""SSOT governance report + incremental gate (package)."""

import subprocess  # noqa: F401  (kept for monkeypatch of governance_report.subprocess.run)

from common.meta.extension.governance_report._base import (
    GATE_EXCEPTION_PATH,
    GATE_HLS_RULE,
    GATE_ISSUE,
    HIGH_RISK_SUBSTRINGS,
    HIGH_RISK_TOKENS,
    HLS_ISSUE,
    MACHINE_KINDS,
    MACHINE_OWNER_SUFFIXES,
    PROOF_MARKERS,
    PROTECTED_DEBT_LABELS,
    PROTECTED_RATIO_LABELS,
    RATIO_EPSILON,
    REPORT_VERSION,
    SOURCE_ISSUE,
    SSOT_FILE_EXCLUDES,
    SSOT_FILE_SUFFIXES,
)
from common.meta.extension.governance_report._types import (
    GateViolation,
    GovernanceEntry,
    ManifestSource,
)
from common.meta.extension.governance_report._util import (
    _as_strings,
    _display_ref,
    _file_part,
    _gate_target,
    _has_proof,
    _infer_family,
    _is_high_risk,
    _is_machine_owned,
    _manifest_entry_target,
)
from common.meta.extension.governance_report._metrics import (
    _compare_governance_trends,
    _field_coverage,
    _future_candidate,
)
from common.meta.extension.governance_report._manifest import (
    _load_manifest_entries,
    _load_manifest_entries_from_text,
    _orphan_ssot_files,
)
from common.meta.extension.governance_report._report import (
    _contains_high_risk_terms,
    _manifest_sources,
    build_report,
    build_source_report,
)
from common.meta.extension.governance_report._gate import (
    _changed_ssot_files,
    _load_changed_files,
    _load_exception_targets,
    _read_base_manifest_text,
    _source_changed_files,
    evaluate_incremental_gate,
)
from common.meta.extension.governance_report.cli import (
    main,
    parse_args,
    render_markdown,
)

__all__ = [
    "GATE_EXCEPTION_PATH",
    "GATE_HLS_RULE",
    "GATE_ISSUE",
    "HIGH_RISK_SUBSTRINGS",
    "HIGH_RISK_TOKENS",
    "HLS_ISSUE",
    "MACHINE_KINDS",
    "MACHINE_OWNER_SUFFIXES",
    "PROOF_MARKERS",
    "PROTECTED_DEBT_LABELS",
    "PROTECTED_RATIO_LABELS",
    "RATIO_EPSILON",
    "REPORT_VERSION",
    "SOURCE_ISSUE",
    "SSOT_FILE_EXCLUDES",
    "SSOT_FILE_SUFFIXES",
    "GateViolation",
    "GovernanceEntry",
    "ManifestSource",
    "_as_strings",
    "_changed_ssot_files",
    "_compare_governance_trends",
    "_contains_high_risk_terms",
    "_display_ref",
    "_field_coverage",
    "_file_part",
    "_future_candidate",
    "_gate_target",
    "_has_proof",
    "_infer_family",
    "_is_high_risk",
    "_is_machine_owned",
    "_load_changed_files",
    "_load_exception_targets",
    "_load_manifest_entries",
    "_load_manifest_entries_from_text",
    "_manifest_entry_target",
    "_manifest_sources",
    "_orphan_ssot_files",
    "_read_base_manifest_text",
    "_source_changed_files",
    "build_report",
    "build_source_report",
    "evaluate_incremental_gate",
    "main",
    "parse_args",
    "render_markdown",
]
