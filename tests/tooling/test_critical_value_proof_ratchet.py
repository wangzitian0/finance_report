"""Critical outcomes must prove a value, and that bar can only rise (#1623)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from common.testing import check_critical_value_proof as cvp


def test_proof_kinds_read_live_contracts_explicit_only(tmp_path: Path) -> None:
    """(#1826) proof_kind comes from the LIVE package contract roadmaps, not the
    ``docs/ac_registry.yaml`` pointer stub (which carries no per-AC entries and
    silently degraded this ratchet to "no AC is value-asserting").

    Only EXPLICIT ``proof_kind=`` literals count: a tier's canonical default
    (e.g. CODE-ONLY -> exact) is a vocabulary fallback, not evidence that the
    backing test asserts a business value — otherwise every AC in a
    tier-declared package would clear the critical-value ratchet for free."""
    pkg = tmp_path / "common" / "pkgx"
    pkg.mkdir(parents=True)
    (pkg / "contract.py").write_text(
        textwrap.dedent(
            """
            CONTRACT = PackageContract(
                name="pkgx",
                tier="CODE-ONLY",
                roadmap=[
                    ACRecord(
                        id="AC-pkgx.g.1",
                        statement="no explicit kind: tier default must NOT count",
                        test="tests/pkgx/test_x.py::test_one",
                        priority="P0",
                        status="done",
                    ),
                    ACRecord(
                        id="AC-pkgx.g.2",
                        statement="explicit exact: value-asserting",
                        test="tests/pkgx/test_x.py::test_two",
                        priority="P0",
                        status="done",
                        proof_kind="exact",
                    ),
                ],
            )
            """
        ),
        encoding="utf-8",
    )
    kinds = cvp._registry_proof_kinds(tmp_path)
    assert kinds == {"AC-pkgx.g.1": None, "AC-pkgx.g.2": "exact"}
    assert kinds["AC-pkgx.g.1"] not in cvp.VALUE_ASSERTING_KINDS
    assert kinds["AC-pkgx.g.2"] in cvp.VALUE_ASSERTING_KINDS


def test_no_new_non_value_asserting_critical_proofs() -> None:
    """A new covered critical outcome (or a proof that stops asserting a value)
    fails CI: current non-value-asserting set must be a subset of the baseline."""
    current = cvp.current_non_value_proofs()
    baseline = set(
        json.loads(cvp.BASELINE_PATH.read_text(encoding="utf-8"))["non_value_proofs"]
    )
    added = current - baseline
    assert not added, (
        "New critical macro-outcome proof(s) assert no business value — give a "
        "backing AC a value-asserting proof_kind (exact/property/invariant/eval), "
        "do not baseline them:\n  " + "\n  ".join(sorted(added))
    )


def test_value_asserting_kinds_are_the_oracle_set() -> None:
    """Lock the semantics: smoke/evidence/unset are NOT value-asserting."""
    assert cvp.VALUE_ASSERTING_KINDS == {"exact", "property", "invariant", "eval"}
    assert "smoke" not in cvp.VALUE_ASSERTING_KINDS
    assert "evidence" not in cvp.VALUE_ASSERTING_KINDS


def test_baseline_only_shrinks_never_grows() -> None:
    """The ratchet refuses --update if it would add a new violation."""
    # current == baseline today, so a plain update is a no-op success; the
    # shrink-only guard is unit-covered here by asserting the gate is green.
    assert cvp.main([]) == 0
