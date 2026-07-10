"""Graded field-accuracy eval + drift ratchet over committed cassettes.

EPIC-023 AC-llm.8 / issue #1307. AC-llm.7 (`check_llm_cassettes`) gates cassette
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

import pytest

from common.testing.cassette_graded_eval import (
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
from common.testing.cassette_eval_baseline import DEFAULT_BASELINE, load_jsonl


# --------------------------------------------------------------------------- #
# AC-llm.8.1 — coverage matrix (modality × institution-class × edge-condition)
# --------------------------------------------------------------------------- #
def test_AC23_8_1_eval_set_covers_documented_matrix_to_min_count() -> None:
    """AC-llm.8.1: the committed eval set meets the documented coverage matrix and
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
    """AC-llm.8.1: the eval doc explicitly bounds drift-detection power by breadth."""
    doc = Path(__file__).resolve().parents[2] / "common" / "llm" / "readme.md"
    text = doc.read_text(encoding="utf-8").lower()
    # No overclaiming: the doc must say breadth bounds the power and CI green is
    # not a correctness guarantee on unseen statements.
    assert "bounded" in text or "bound" in text
    assert "unseen" in text


# --------------------------------------------------------------------------- #
# AC-llm.8.2 — per-field scoring (exact / normalised match -> numeric score)
# --------------------------------------------------------------------------- #
def test_AC23_8_2_normalizers_are_exact_value_aware() -> None:
    """AC-llm.8.2: amounts compare as Decimal, dates ISO, descriptions normalised."""
    assert normalize_amount("5.00") == normalize_amount(5) == Decimal("5")
    assert normalize_amount("-5.0") == Decimal("-5")
    assert normalize_date("2026-01-02") == "2026-01-02"
    assert normalize_date("02/01/2026", dayfirst=True) == "2026-01-02"
    assert normalize_description("  Coffee   SHOP ") == normalize_description(
        "coffee shop"
    )


def test_AC23_8_2_case_score_is_fraction_of_correct_fields() -> None:
    """AC-llm.8.2: a perfect extraction scores 1.0; each wrong field lowers it."""
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
# AC-llm.8.3 — ratchet floor only goes UP; gate fails on regression
# --------------------------------------------------------------------------- #
def test_AC23_8_3_committed_cassettes_meet_their_floors() -> None:
    """AC-llm.8.3: every committed cassette scores at/above its persisted floor."""
    findings = evaluate(baseline_path=DEFAULT_BASELINE)
    assert findings["regressions"] == [], findings["regressions"]
    assert findings["missing"] == [], findings["missing"]


def test_AC23_8_3_unbaselined_case_blocks_the_gate(tmp_path: Path) -> None:
    """AC-llm.8.3: an eval case with NO persisted floor blocks the gate (so a deleted
    floor or an unguarded new case cannot silently disable the ratchet)."""
    from common.testing.check_cassette_graded_eval import main as gate_main

    empty_baseline = tmp_path / "empty.jsonl"
    empty_baseline.write_text("", encoding="utf-8")
    # Every committed case is now "new" (no floor) -> gate must FAIL.
    assert gate_main(["--baseline", str(empty_baseline)]) == 1
    # But --update is the sanctioned adopt path -> succeeds and writes floors.
    assert gate_main(["--baseline", str(empty_baseline), "--update"]) == 0
    assert load_jsonl(empty_baseline)["cases"], "expected floors adopted by --update"


def test_AC23_8_3_baseline_is_raise_only() -> None:
    """AC-llm.8.3: ratcheted_baseline keeps the higher floor and never lowers it."""
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
# AC-llm.8.4 — reverse proof: an injected regression is CAUGHT
# --------------------------------------------------------------------------- #
def test_AC23_8_4_injected_regression_fails_the_gate(tmp_path: Path) -> None:
    """AC-llm.8.4: a cassette field flipped below its floor is caught by the gate."""
    cases = load_cases()
    # Pick a statement case with at least one transaction amount to corrupt.
    target = next(c for c in cases if c.extracted.get("transactions"))

    # Build a baseline that records the case's CURRENT (correct) score as the floor.
    correct_score, _ = case_score(target.extracted, target.truth)
    baseline_file = tmp_path / "baseline.jsonl"
    from common.testing.cassette_eval_baseline import write_jsonl

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
# AC-llm.8.5 — catches plausible-but-wrong (invariant passes, accuracy regresses)
# --------------------------------------------------------------------------- #
def test_AC23_8_5_balance_passes_but_field_accuracy_regresses(tmp_path: Path) -> None:
    """AC-llm.8.5: a cassette whose balance chain still reconciles but whose amount
    no longer matches ground truth is flagged by the graded gate (while AC-llm.7 stays green)."""
    from common.testing.check_llm_cassettes import balance_violation

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
    # amounts now mismatch truth. This is the drift AC-llm.7 cannot see.
    plausible = json.loads(json.dumps(target.extracted))
    ti, tj = plausible["transactions"][i], plausible["transactions"][j]
    ti["amount"] = str(Decimal(str(ti["amount"])) + Decimal("1"))
    tj["amount"] = str(Decimal(str(tj["amount"])) - Decimal("1"))

    # AC-llm.7 balance gate: still GREEN (net preserved).
    assert balance_violation(plausible) is None

    # Graded gate: CAUGHT (per-field amounts regressed) given a floor at the
    # correct score.
    correct_score, _ = case_score(target.extracted, target.truth)
    plausible_score, _ = case_score(plausible, target.truth)
    assert plausible_score < correct_score

    baseline_file = tmp_path / "baseline.jsonl"
    from common.testing.cassette_eval_baseline import write_jsonl

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
# AC-llm.8.6 — deterministic, no network / no key; baseline persisted
# --------------------------------------------------------------------------- #
def test_AC23_8_6_runs_on_committed_cassettes_without_network_or_key() -> None:
    """AC-llm.8.6: the eval scores committed cassettes purely from disk (no I/O beyond
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
    """AC-llm.8.6 (data hygiene): every committed cassette is EITHER synthetic, OR a real
    statement that has been STRICTLY PII-masked — and for the real ones the gate proves
    it structurally (not by trusting the recorder), by an ALLOWLIST: every string field
    whose key is not a known PII-free field (flow values, public security symbols, the
    institution/period/currency) must be fully redacted to ``**``. So an unexpected
    free-text key cannot slip through partially masked, and no PII enters git regardless
    of provenance."""
    import re

    from common.testing.cassette_graded_eval import CASSETTE_DIR, _parse_extraction
    from tools._lib.fixtures.extraction_pii_mask import _DESC_KEYS

    # A masked-description token: hash-derived hex + a star run + hex (no real text), or
    # all stars. Lowercase-hex + stars only — a real (cased, spaced) description can't match.
    pseudonym = re.compile(r"[0-9a-f]{2}\*+[0-9a-f]{2}|\*+")
    # Non-PII string fields that may stay verbatim. Description fields may be a pseudonym.
    # ANY other string field MUST be ``**`` — allowlist (deny-by-default), so a new key can't leak.
    safe_string_keys = {
        "institution",
        "currency",
        "period_start",
        "period_end",
        "opening_balance",
        "closing_balance",
        "opening",
        "closing",
        "date",
        "amount",
        "direction",
        "balance_after",
        "suggested_category",
        "symbol",
        "ticker",
        "isin",
        "asset_identifier",
        "asset_type",
        "quantity",
        "market_value",
        "price",
    }
    # Broad CJK / kana / hangul coverage (Han + Ext-A + Hiragana/Katakana + Hangul) so a
    # name in any East-Asian script is caught, not just the basic Han block.
    cjk = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]")

    def _assert_pii_free(name: str, obj: object) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if not isinstance(value, str):
                    _assert_pii_free(name, value)
                elif key in safe_string_keys:
                    continue
                elif key in _DESC_KEYS:
                    assert pseudonym.fullmatch(value), (
                        f"{name}: description {key!r}={value!r} is not an irreversible "
                        f"pseudonym (hex+stars+hex) nor fully redacted"
                    )
                else:
                    assert value == "**", (
                        f"{name}: text field {key!r}={value!r} is neither an allowlisted "
                        f"non-PII field nor fully redacted to '**'"
                    )
        elif isinstance(obj, list):
            for item in obj:
                _assert_pii_free(name, item)

    for path in sorted(GROUND_TRUTH_DIR.glob("*.truth.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("synthetic") is True:
            continue
        assert data.get("synthetic") is False, (
            f"{path.name}: 'synthetic' must be set true or false"
        )
        extraction = _parse_extraction(
            CASSETTE_DIR / f"{path.name[: -len('.truth.json')]}.json"
        )
        assert extraction is not None, (
            f"{path.name}: no scorable cassette to verify PII-masking"
        )
        assert not cjk.search(json.dumps(extraction, ensure_ascii=False)), (
            f"{path.name}: a CJK character (likely a real name) survives in a committed real cassette"
        )
        _assert_pii_free(path.name, extraction)


# --------------------------------------------------------------------------- #
# AC-llm.8.7 — reliability over N samples, single-sample limitation documented
# --------------------------------------------------------------------------- #
def test_AC23_8_7_reliability_aggregates_over_n_samples() -> None:
    """AC-llm.8.7: a case with multiple recordings scores the MEAN over samples."""
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

    from common.testing.cassette_graded_eval import reliability_score

    mean = reliability_score([perfect, wrong], truth)
    assert mean == (s_perfect + s_wrong) / 2


def test_AC23_8_7_single_sample_limitation_documented() -> None:
    """AC-llm.8.7: the doc states a single recording is a point estimate, not reliability."""
    doc = Path(__file__).resolve().parents[2] / "common" / "llm" / "readme.md"
    text = doc.read_text(encoding="utf-8").lower()
    assert "single" in text and "sample" in text


# --------------------------------------------------------------------------- #
# Corpus-count floor (#1681 / #1686): a SEPARATE raise-only ratchet from the
# per-case floors above — catches a corpus SHRINK that "missing" cannot see
# when a case's ground-truth file AND its baseline line are removed together.
# --------------------------------------------------------------------------- #
def test_corpus_shrink_findings_is_empty_at_or_above_the_floor() -> None:
    from common.testing.cassette_graded_eval import EvalCase, corpus_shrink_findings

    cases = [
        EvalCase(
            case_id="a",
            modality="text",
            institution_class="bank",
            edge_condition="happy_path",
            extracted={},
            truth={},
        )
    ]
    assert corpus_shrink_findings(cases, floor=0) == []
    assert corpus_shrink_findings(cases, floor=1) == []


def test_corpus_shrink_findings_flags_a_real_shrink() -> None:
    from common.testing.cassette_graded_eval import EvalCase, corpus_shrink_findings

    cases = [
        EvalCase(
            case_id="a",
            modality="text",
            institution_class="bank",
            edge_condition="happy_path",
            extracted={},
            truth={},
        )
    ]
    floor = 2
    findings = corpus_shrink_findings(cases, floor=floor)
    assert len(findings) == 1
    # Assert on the dynamic values themselves (not a hardcoded message mirror,
    # per the mirror-assertion ratchet in common/testing/mirror_ratchet.py):
    # the reported counts must be the actual case count and floor, not stale text.
    assert str(len(cases)) in findings[0]
    assert str(floor) in findings[0]


def test_corpus_count_floor_round_trips_and_defaults_to_zero(tmp_path: Path) -> None:
    from common.testing.cassette_eval_baseline import (
        load_corpus_count_floor,
        write_corpus_count_floor,
    )

    missing = tmp_path / "does-not-exist.json"
    assert load_corpus_count_floor(missing) == 0

    path = tmp_path / "floor.json"
    write_corpus_count_floor(path, 10)
    assert load_corpus_count_floor(path) == 10


def test_corpus_count_floor_fails_closed_on_malformed_min_cases(tmp_path: Path) -> None:
    """A present-but-invalid min_cases (negative, non-integer, non-numeric) is a
    hard error, not a silent coercion — a bad edit should not weaken the ratchet."""
    from common.testing.cassette_eval_baseline import load_corpus_count_floor

    for bad_value in (-5, 1.5, "not-a-number", True):
        path = tmp_path / f"bad-{bad_value}.json"
        path.write_text(json.dumps({"min_cases": bad_value}), encoding="utf-8")
        with pytest.raises((ValueError, TypeError)):
            load_corpus_count_floor(path)


def test_AC_corpus_count_floor_blocks_the_gate_when_corpus_is_below_it(
    tmp_path: Path,
) -> None:
    """AC-llm.8.8: a floor set ABOVE the real committed corpus size fails the
    gate — proves the check is wired into check_cassette_graded_eval.main(),
    not just a pure function nobody calls."""
    from common.testing.cassette_graded_eval import load_cases
    from common.testing.check_cassette_graded_eval import main as gate_main

    real_count = len(load_cases())
    impossible_floor = tmp_path / "impossible-floor.json"
    impossible_floor.write_text(
        json.dumps({"min_cases": real_count + 1}), encoding="utf-8"
    )

    assert gate_main(["--corpus-count-baseline", str(impossible_floor)]) == 1


def test_AC_corpus_count_floor_passes_when_corpus_meets_it(tmp_path: Path) -> None:
    from common.testing.cassette_graded_eval import load_cases
    from common.testing.check_cassette_graded_eval import main as gate_main

    real_count = len(load_cases())
    ok_floor = tmp_path / "ok-floor.json"
    ok_floor.write_text(json.dumps({"min_cases": real_count}), encoding="utf-8")

    assert gate_main(["--corpus-count-baseline", str(ok_floor)]) == 0


def test_AC_corpus_count_floor_update_raises_to_current_count_never_lowers(
    tmp_path: Path,
) -> None:
    from common.testing.cassette_eval_baseline import load_corpus_count_floor
    from common.testing.cassette_graded_eval import load_cases
    from common.testing.check_cassette_graded_eval import main as gate_main

    real_count = len(load_cases())
    # --baseline points at an ISOLATED tmp per-case file too, so --update never
    # touches the real committed cassette-eval-baseline.jsonl in this test.
    per_case_baseline = tmp_path / "per-case.jsonl"
    per_case_baseline.write_text("", encoding="utf-8")
    floor_path = tmp_path / "floor.json"
    floor_path.write_text(json.dumps({"min_cases": 1}), encoding="utf-8")

    assert (
        gate_main(
            [
                "--baseline",
                str(per_case_baseline),
                "--corpus-count-baseline",
                str(floor_path),
                "--update",
            ]
        )
        == 0
    )
    assert load_corpus_count_floor(floor_path) == real_count

    # A second --update with the corpus unchanged does not lower the floor
    # (idempotent: max(existing, current) == existing == current here).
    assert (
        gate_main(
            [
                "--baseline",
                str(per_case_baseline),
                "--corpus-count-baseline",
                str(floor_path),
                "--update",
            ]
        )
        == 0
    )
    assert load_corpus_count_floor(floor_path) == real_count
