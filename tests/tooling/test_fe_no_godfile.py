"""No workflow god-file, single `cx` definition (AC-meta.fe-contract-types.5, #1868 S5 PR-C).

`WorkflowNotifications.tsx` was a 769-line file holding 6 components, 3
private hooks, and ~20 helpers, including a private re-implementation of
`cx` that already existed (unexported) in `components/ui/index.tsx`. It is
now split into one file per component/hook under `components/workflow/`,
re-exported as a barrel from the original path. This gate keeps both classes
of regression — the god-file re-forming, and `cx` growing a second
definition — from silently coming back.
"""

from __future__ import annotations

import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
FRONTEND_SRC = (REPO / "apps" / "frontend" / "src").resolve()
WORKFLOW_DIR = FRONTEND_SRC / "components" / "workflow"

_MAX_LINES = 300

# Line-anchored (not raw substring) — the async-aware-regex lesson from
# tests/tooling/test_safe_error_message_ssot.py.
_CX_DEF_PATTERN = re.compile(
    r"^\s*(?:export\s+)?(?:function\s+cx\(|const\s+cx\s*=)", re.MULTILINE
)
_CX_CANONICAL_HOME = "apps/frontend/src/components/ui/index.tsx"


def _frontend_source_files() -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.ts", "*.tsx"):
        for path in FRONTEND_SRC.rglob(pattern):
            if "node_modules" in path.parts:
                continue
            files.append(path)
    return files


@ac_proof(
    proof_id="test_fe_no_godfile_workflow_files_under_300_lines",
    ac_ids=["AC-meta.fe-contract-types.5"],
    ci_tier="pr_ci",
)
def test_AC_fe_no_godfile_1_workflow_files_stay_under_300_lines():
    """AC-meta.fe-contract-types.5: no file under components/workflow/ exceeds 300 lines."""
    scanned = [
        path for pattern in ("*.ts", "*.tsx") for path in WORKFLOW_DIR.rglob(pattern)
    ]
    # A moved/renamed/deleted directory must fail loudly, not pass vacuously
    # via an empty rglob() result (the review comment this addresses).
    assert scanned, f"{WORKFLOW_DIR} has no *.ts(x) files — was it moved or deleted?"

    offenders = [
        f"{path.relative_to(REPO)}: {line_count} lines"
        for path in scanned
        if (line_count := sum(1 for _ in path.read_text(encoding="utf-8").splitlines()))
        > _MAX_LINES
    ]

    assert not offenders, "components/workflow/ god-file regressed:\n" + "\n".join(
        offenders
    )


@ac_proof(
    proof_id="test_fe_no_godfile_cx_single_definition",
    ac_ids=["AC-meta.fe-contract-types.5"],
    ci_tier="pr_ci",
)
def test_AC_fe_no_godfile_2_cx_has_exactly_one_definition():
    """AC-meta.fe-contract-types.5: `cx` is defined exactly once, at its canonical home."""
    hits = [
        str(path.relative_to(REPO))
        for path in _frontend_source_files()
        if _CX_DEF_PATTERN.search(path.read_text(encoding="utf-8"))
    ]

    assert hits == [_CX_CANONICAL_HOME], (
        f"cx must be defined exactly once, at {_CX_CANONICAL_HOME}: found {hits}"
    )
