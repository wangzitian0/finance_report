"""AC-meta.txn.4 — the cross-domain-cascade shrink-only ratchet (#1675 D1).

A DB-level ``ondelete="CASCADE"`` is a hidden cross-domain write: one domain's
delete mutates another domain's aggregates below the application, against
one-txn-per-domain (#1416 Decision B) and append-only domains (Axiom A). The
policy (``common/meta/migration-standard.md`` → "Cross-domain reference
policy") grandfathers the existing sites in ``docs/ssot/fk-cascade-baseline.json``
and lets the census only shrink; the end-state is saga-owned deletion
(``identity/extension/account_purge.py`` is the seed).

The baseline is keyed by **target table**, not file path, so package moves
(#1675 D2–D6) do not churn it — only adding or removing a CASCADE does.
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "apps/backend/src"
BASELINE_PATH = REPO / "docs/ssot/fk-cascade-baseline.json"


def _cascade_census() -> Counter[str]:
    """Count ``ForeignKey(..., ondelete="CASCADE")`` calls per target table.

    AST-only (no imports, minimal-env safe), same best-effort posture as the
    cross-domain-FK gate (AC-meta.txn.3): a dynamic first argument is counted
    under ``<dynamic>`` rather than silently skipped.
    """
    counts: Counter[str] = Counter()
    for py in sorted(SRC.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "ForeignKey":
                continue
            ondelete = next((kw.value for kw in node.keywords if kw.arg == "ondelete"), None)
            if not (isinstance(ondelete, ast.Constant) and ondelete.value == "CASCADE"):
                continue
            target = node.args[0] if node.args else None
            if isinstance(target, ast.Constant) and isinstance(target.value, str):
                table = target.value.split(".", 1)[0]
            else:
                table = "<dynamic>"
            counts[table] += 1
    return counts


def test_AC_meta_txn_4_cascade_census_is_nonvacuous() -> None:
    """Guard non-vacuity (#1416 DoD-addition 1): the scan must see the known set.

    ``users`` is the sentinel — the ``UserOwnedMixin`` tenancy anchor declares
    ``ForeignKey("users.id", ondelete="CASCADE")`` on nearly every table, so a
    census that does not see it is scanning the wrong root, not a clean repo.
    """
    counts = _cascade_census()
    assert counts, "cascade census scanned nothing — did apps/backend/src move?"
    assert counts["users"] >= 1, (
        "sentinel missing: no ForeignKey('users.id', ondelete='CASCADE') found; "
        "the census is scanning the wrong set (UserOwnedMixin declares one)"
    )


def test_AC_meta_txn_4_cross_domain_cascade_only_shrinks() -> None:
    baseline: dict[str, int] = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    counts = _cascade_census()

    grown = {
        table: (baseline.get(table, 0), n)
        for table, n in counts.items()
        if n > baseline.get(table, 0)
    }
    assert not grown, (
        "new ondelete=CASCADE ForeignKey(s) — a DB cascade is a hidden "
        "cross-domain write (AC-meta.txn.4; migration-standard.md 'Cross-domain "
        "reference policy'). Prefer saga-owned deletion (purge event + each "
        "domain deletes by its own semantics). If this cascade is genuinely "
        "intra-domain and deliberate, raise the baseline in the same PR so the "
        "choice is reviewed.\n"
        f"grown (baseline, actual): {grown}\n"
        f"full census: {json.dumps(dict(sorted(counts.items())), indent=2)}"
    )

    stale = {
        table: (expected, counts.get(table, 0))
        for table, expected in baseline.items()
        if counts.get(table, 0) < expected
    }
    assert not stale, (
        "the baseline over-counts — CASCADEs were removed (good!); prune "
        "docs/ssot/fk-cascade-baseline.json to match in the same PR so the "
        "ratchet stays tight.\n"
        f"stale (baseline, actual): {stale}\n"
        f"full census: {json.dumps(dict(sorted(counts.items())), indent=2)}"
    )
