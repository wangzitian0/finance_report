"""Graded field-accuracy eval + drift ratchet over committed cassettes.

EPIC-023 AC23.8 / issue #1307. AC23.7 (`check_llm_cassettes`) gates cassette
*consistency* (the balance chain reconciles); it cannot see *accuracy* — an LLM
that misreads ``50`` as ``150`` still balances. This graded eval scores each
committed statement cassette per-field against a SYNTHETIC ground-truth artifact
and ratchets a per-case score floor that only ever goes UP, so a refreshed
cassette that regresses a field fails the lint-job gate.

Pure Python: no network, no API key, no DB — runs in `tests/tooling/` (CI-required).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from common.ssot.cassette_graded_eval import (
    GROUND_TRUTH_DIR,
    REQUIRED_EDGE_CONDITIONS,
    REQUIRED_MODALITIES,
    MIN_CASES,
    case_score,
    evaluate,
    load_cases,
    normalize_amount,
    normalize_date,
    normalize_description,
    ratcheted_baseline,
)
from common.ssot.cassette_eval_baseline import DEFAULT_BASELINE, load_jsonl


# --------------------------------------------------------------------------- #
# AC23.8.1 — coverage matrix (modality × institution-class × edge-condition)
# --------------------------------------------------------------------------- #
def test_AC23_8_1_eval_set_covers_documented_matrix_to_min_count() -> None:
    """AC23.8.1: the committed eval set meets the documented coverage matrix and
    minimum case count across modality / institution-class / edge-condition axes."""
    cases = load_cases()
    assert len(cases) >= MIN_CASES, f"need >= {MIN_CASES} eval cases, got {len(cases)}"

    modalities = {c.modality for c in cases}
    institution_classes = {c.institution_class for c in cases}
    edge_conditions = {c.edge_condition for c in cases}

    # Both modalities present (text + vision).
    assert REQUIRED_MODALITIES <= modalities, (
        f"missing modalities: {REQUIRED_MODALITIES - modalities}"
    )
    # At least a generic and a named institution class are represented.
    assert len(institution_classes) >= 2, institution_classes
    # The #1254-class duplicate-row edge condition and a happy path are present.
    assert REQUIRED_EDGE_CONDITIONS <= edge_conditions, (
        f"missing edge conditions: {REQUIRED_EDGE_CONDITIONS - edge_conditions}"
    )


def test_AC23_8_1_matrix_breadth_is_documented_not_overclaimed() -> None:
    """AC23.8.1: the eval doc explicitly bounds drift-detection power by breadth."""
    doc = Path(__file__).resolve().parents[2] / "common" / "llm" / "readme.md"
    text = doc.read_text(encoding="utf-8").lower()
    # No overclaiming: the doc must say breadth bounds the power and CI green is
    # not a correctness guarantee on unseen statements.
    assert "bounded" in text or "bound" in text
    assert "unseen" in text


# --------------------------------------------------------------------------- #
# AC23.8.2 — per-field scoring (exact / normalised match -> numeric score)
# --------------------------------------------------------------------------- #
def test_AC23_8_2_normalizers_are_exact_value_aware() -> None:
    """AC23.8.2: amounts compare as Decimal, dates ISO, descriptions normalised."""
    assert normalize_amount("5.00") == normalize_amount(5) == Decimal("5")
    assert normalize_amount("-5.0") == Decimal("-5")
    assert normalize_date("2026-01-02") == "2026-01-02"
    assert normalize_date("02/01/2026", dayfirst=True) == "2026-01-02"
    assert normalize_description("  Coffee   SHOP ") == normalize_description(
        "coffee shop"
    )


def test_AC23_8_2_case_score_is_fraction_of_correct_fields() -> None:
    """AC23.8.2: a perfect extraction scores 1.0; each wrong field lowers it."""
    truth = {
        "opening_balance": "100.00",
        "closing_balance": "130.00",
        "transactions": [
            {"date": "2026-01-02", "description": "Coffee shop", "amount": "-5.00"},
            {"date": "2026-01-05", "description": "Salary credit", "amount": "50.00"},
        ],
    }
    perfect = json.loads(json.dumps(truth))
    score, detail = case_score(perfect, truth)
    assert score == 1.0
    assert detail["matched"] == detail["total"]

    # Flip one amount -> exactly one field wrong.
    wrong = json.loads(json.dumps(truth))
    wrong["transactions"][0]["amount"] = "-15.00"
    score2, detail2 = case_score(wrong, truth)
    assert 0.0 < score2 < 1.0
    assert detail2["matched"] == detail2["total"] - 1


# --------------------------------------------------------------------------- #
# AC23.8.3 — ratchet floor only goes UP; gate fails on regression
# --------------------------------------------------------------------------- #
def test_AC23_8_3_committed_cassettes_meet_their_floors() -> None:
    """AC23.8.3: every committed cassette scores at/above its persisted floor."""
    findings = evaluate(baseline_path=DEFAULT_BASELINE)
    assert findings["regressions"] == [], findings["regressions"]
    assert findings["missing"] == [], findings["missing"]


def test_AC23_8_3_unbaselined_case_blocks_the_gate(tmp_path: Path) -> None:
    """AC23.8.3: an eval case with NO persisted floor blocks the gate (so a deleted
    floor or an unguarded new case cannot silently disable the ratchet)."""
    from common.ssot.check_cassette_graded_eval import main as gate_main

    empty_baseline = tmp_path / "empty.jsonl"
    empty_baseline.write_text("", encoding="utf-8")
    # Every committed case is now "new" (no floor) -> gate must FAIL.
    assert gate_main(["--baseline", str(empty_baseline)]) == 1
    # But --update is the sanctioned adopt path -> succeeds and writes floors.
    assert gate_main(["--baseline", str(empty_baseline), "--update"]) == 0
    assert load_jsonl(empty_baseline)["cases"], "expected floors adopted by --update"


def test_AC23_8_3_baseline_is_raise_only() -> None:
    """AC23.8.3: ratcheted_baseline keeps the higher floor and never lowers it."""
    baseline = {
        "version": 1,
        "cases": {"c1": {"score": 0.9, "metric": "x", "provenance": "y"}},
    }
    # A higher current score raises the floor.
    raised = ratcheted_baseline(baseline, {"c1": {"score": 0.95}})
    assert raised["cases"]["c1"]["score"] == 0.95
    # A lower current score does NOT lower the floor.
    kept = ratcheted_baseline(baseline, {"c1": {"score": 0.5}})
    assert kept["cases"]["c1"]["score"] == 0.9
    # A brand-new case is adopted.
    added = ratcheted_baseline(baseline, {"c2": {"score": 0.7}})
    assert added["cases"]["c2"]["score"] == 0.7


# --------------------------------------------------------------------------- #
# AC23.8.4 — reverse proof: an injected regression is CAUGHT
# --------------------------------------------------------------------------- #
def test_AC23_8_4_injected_regression_fails_the_gate(tmp_path: Path) -> None:
    """AC23.8.4: a cassette field flipped below its floor is caught by the gate."""
    cases = load_cases()
    # Pick a statement case with at least one transaction amount to corrupt.
    target = next(c for c in cases if c.extracted.get("transactions"))

    # Build a baseline that records the case's CURRENT (correct) score as the floor.
    correct_score, _ = case_score(target.extracted, target.truth)
    baseline_file = tmp_path / "baseline.jsonl"
    from common.ssot.cassette_eval_baseline import write_jsonl

    write_jsonl(
        baseline_file,
        {
            "version": 1,
            "cases": {
                target.case_id: {
                    "score": correct_score,
                    "metric": "field-accuracy",
                    "provenance": "test",
                }
            },
        },
    )

    # Inject a regression: corrupt one transaction amount so the case score drops.
    corrupted = json.loads(json.dumps(target.extracted))
    amt = Decimal(str(corrupted["transactions"][0]["amount"]))
    corrupted["transactions"][0]["amount"] = str(amt + Decimal("999"))
    regressed_score, _ = case_score(corrupted, target.truth)
    assert regressed_score < correct_score  # sanity: the corruption lowered the score

    findings = evaluate(
        baseline_path=baseline_file,
        overrides={target.case_id: [corrupted]},
    )
    assert any(target.case_id in r for r in findings["regressions"]), findings


# --------------------------------------------------------------------------- #
# AC23.8.5 — catches plausible-but-wrong (invariant passes, accuracy regresses)
# --------------------------------------------------------------------------- #
def test_AC23_8_5_balance_passes_but_field_accuracy_regresses(tmp_path: Path) -> None:
    """AC23.8.5: a cassette whose balance chain still reconciles but whose amount
    no longer matches ground truth is flagged by the graded gate (while AC23.7 stays green)."""
    from common.ssot.check_llm_cassettes import balance_violation

    def _same_direction(a: dict, b: dict) -> bool:
        """True when two transactions move money the SAME way (so a compensating
        +δ/−δ on their magnitudes keeps the net — and the balance chain — fixed)."""
        da = str(a.get("direction") or "").strip().upper()
        db = str(b.get("direction") or "").strip().upper()
        if da or db:
            return da == db
        # No direction: same way ⇔ same sign of the signed amount.
        return (Decimal(str(a["amount"])) < 0) == (Decimal(str(b["amount"])) < 0)

    def _pick_pair(case) -> tuple[int, int] | None:
        txns = case.extracted.get("transactions") or []
        for i in range(len(txns)):
            for j in range(i + 1, len(txns)):
                if _same_direction(txns[i], txns[j]):
                    return i, j
        return None

    cases = load_cases()
    # Demonstrate the gap on a case that ALREADY reconciles — skip balance-exempt
    # (non-reconciling-by-construction) corpora like the HF statements.
    target, pair = next(
        (c, p)
        for c in cases
        if balance_violation(c.extracted) is None and (p := _pick_pair(c)) is not None
    )
    i, j = pair

    # Plausible-but-wrong: shift +1 onto txn i and −1 off txn j (same direction), so
    # the NET is unchanged — the balance chain STILL reconciles — but two per-field
    # amounts now mismatch truth. This is the drift AC23.7 cannot see.
    plausible = json.loads(json.dumps(target.extracted))
    ti, tj = plausible["transactions"][i], plausible["transactions"][j]
    ti["amount"] = str(Decimal(str(ti["amount"])) + Decimal("1"))
    tj["amount"] = str(Decimal(str(tj["amount"])) - Decimal("1"))

    # AC23.7 balance gate: still GREEN (net preserved).
    assert balance_violation(plausible) is None

    # Graded gate: CAUGHT (per-field amounts regressed) given a floor at the
    # correct score.
    correct_score, _ = case_score(target.extracted, target.truth)
    plausible_score, _ = case_score(plausible, target.truth)
    assert plausible_score < correct_score

    baseline_file = tmp_path / "baseline.jsonl"
    from common.ssot.cassette_eval_baseline import write_jsonl

    write_jsonl(
        baseline_file,
        {
            "version": 1,
            "cases": {
                target.case_id: {
                    "score": correct_score,
                    "metric": "field-accuracy",
                    "provenance": "test",
                }
            },
        },
    )
    findings = evaluate(
        baseline_path=baseline_file, overrides={target.case_id: [plausible]}
    )
    assert any(target.case_id in r for r in findings["regressions"]), findings


# --------------------------------------------------------------------------- #
# AC23.8.6 — deterministic, no network / no key; baseline persisted
# --------------------------------------------------------------------------- #
def test_AC23_8_6_runs_on_committed_cassettes_without_network_or_key() -> None:
    """AC23.8.6: the eval scores committed cassettes purely from disk (no I/O beyond
    reading the fixtures); a persisted baseline floor exists for the committed cases."""
    cases = load_cases()
    assert cases, "expected committed eval cases"
    # Scoring is pure: same input -> same score, no env/key dependence.
    for case in cases:
        s1, _ = case_score(case.extracted, case.truth)
        s2, _ = case_score(case.extracted, case.truth)
        assert s1 == s2

    baseline = load_jsonl(DEFAULT_BASELINE)
    for case in cases:
        assert case.case_id in baseline["cases"], (
            f"no persisted floor for {case.case_id}"
        )


def test_AC23_8_6_ground_truth_artifacts_are_synthetic() -> None:
    """AC23.8.6 (data hygiene): every ground-truth artifact is flagged synthetic."""
    for path in sorted(GROUND_TRUTH_DIR.glob("*.truth.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("synthetic") is True, f"{path.name} not marked synthetic"


# --------------------------------------------------------------------------- #
# AC23.8.7 — reliability over N samples, single-sample limitation documented
# --------------------------------------------------------------------------- #
def test_AC23_8_7_reliability_aggregates_over_n_samples() -> None:
    """AC23.8.7: a case with multiple recordings scores the MEAN over samples."""
    truth = {
        "opening_balance": "0.00",
        "closing_balance": "0.00",
        "transactions": [{"date": "2026-01-01", "description": "X", "amount": "0.00"}],
    }
    perfect = json.loads(json.dumps(truth))
    wrong = json.loads(json.dumps(truth))
    wrong["transactions"][0]["amount"] = "1.00"
    s_perfect, _ = case_score(perfect, truth)
    s_wrong, _ = case_score(wrong, truth)

    from common.ssot.cassette_graded_eval import reliability_score

    mean = reliability_score([perfect, wrong], truth)
    assert mean == (s_perfect + s_wrong) / 2


def test_AC23_8_7_single_sample_limitation_documented() -> None:
    """AC23.8.7: the doc states a single recording is a point estimate, not reliability."""
    doc = Path(__file__).resolve().parents[2] / "common" / "llm" / "readme.md"
    text = doc.read_text(encoding="utf-8").lower()
    assert "single" in text and "sample" in text
