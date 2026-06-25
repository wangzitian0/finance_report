"""Cassette GRADED field-accuracy eval + drift ratchet.

EPIC-023 AC23.8 / issue #1307. The balance-chain gate
(:mod:`common.ssot.check_llm_cassettes`, AC23.7) catches INCONSISTENCY, not
INACCURACY: an LLM that reads ``50`` as ``150`` still passes as long as the chain
balances. This module scores each committed statement cassette PER FIELD against
a sibling SYNTHETIC ground-truth artifact (``<fingerprint>.truth.json``), yields
a numeric ``[0,1]`` score per case, and ratchets a persisted per-case floor that
may only go UP. The gate FAILS when a refreshed cassette regresses a case below
its floor — including the "balance passes but a field is now wrong" case the
AC23.7 gate cannot see.

Pure Python: no network, no API key, no DB. Scoring is deterministic on committed
fixtures; refresh is the local ``make llm-record`` path.

**Scope (anti-overclaim):** drift-detection power is bounded by the eval-set
breadth documented in ``docs/ssot/cassette-graded-eval.md`` — CI green is NOT a
correctness guarantee on an unseen statement (the staging ``-m llm`` gate's job).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from common.ssot.cassette_eval_baseline import DEFAULT_BASELINE, load_jsonl
from common.ssot.check_llm_cassettes import CASSETTE_DIR, _response_text

GROUND_TRUTH_DIR = CASSETTE_DIR / "ground_truth"

# Floating-point slack so an identical re-measurement never trips the ratchet.
EPSILON = 1e-6

# The documented coverage matrix this eval set must satisfy (AC23.8.1). Keeping
# the required axes in code lets the test assert breadth and the doc state it.
REQUIRED_MODALITIES = {"text", "vision"}
REQUIRED_EDGE_CONDITIONS = {"happy_path", "duplicate_rows"}
MIN_CASES = 3

# Transaction fields scored per row (exact/normalised match against truth).
_TXN_FIELDS = ("date", "description", "amount")


# --------------------------------------------------------------------------- #
# Normalisers — exact/normalised match per field type.
# --------------------------------------------------------------------------- #
def normalize_amount(value: object) -> Decimal:
    """Money as ``Decimal`` (never float): ``"5.00"``, ``5``, ``5.0`` all == ``5``."""
    try:
        return Decimal(str(value)).normalize()
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"unparseable amount: {value!r}") from exc


def normalize_date(value: object, *, dayfirst: bool = False) -> str:
    """Dates to ISO ``YYYY-MM-DD``. Accepts ISO directly or ``DD/MM/YYYY`` /
    ``MM/DD/YYYY`` (``dayfirst`` selects the slash-form interpretation)."""
    text = str(value).strip()
    if "/" in text:
        parts = text.split("/")
        if len(parts) == 3:
            a, b, y = (p.zfill(2) for p in parts)
            day, month = (a, b) if dayfirst else (b, a)
            return f"{y}-{month}-{day}"
    return text


def normalize_description(value: object) -> str:
    """Descriptions: case-fold and collapse internal whitespace."""
    return " ".join(str(value).split()).casefold()


# --------------------------------------------------------------------------- #
# Per-field scoring.
# --------------------------------------------------------------------------- #
def _field_matches(field_name: str, got: object, want: object) -> bool:
    try:
        if field_name == "amount" or field_name in ("opening_balance", "closing_balance"):
            return normalize_amount(got) == normalize_amount(want)
        if field_name == "date":
            return normalize_date(got) == normalize_date(want)
        return normalize_description(got) == normalize_description(want)
    except ValueError:
        return False


def case_score(extracted: dict[str, Any], truth: dict[str, Any]) -> tuple[float, dict[str, int]]:
    """Score one extraction against ground truth: fraction of fields matched.

    Scored fields: ``opening_balance``, ``closing_balance``, and per transaction
    its ``date`` / ``description`` / ``amount``. A missing or extra transaction
    row counts against the score (each expected row contributes its fields; an
    extracted row beyond the truth length is penalised as fully wrong).
    """
    matched = 0
    total = 0

    for balance_field in ("opening_balance", "closing_balance"):
        if balance_field in truth:
            total += 1
            if balance_field in extracted and _field_matches(
                balance_field, extracted[balance_field], truth[balance_field]
            ):
                matched += 1

    truth_txns = truth.get("transactions", []) or []
    got_txns = extracted.get("transactions", []) or []
    for i, want in enumerate(truth_txns):
        got = got_txns[i] if i < len(got_txns) else {}
        for fname in _TXN_FIELDS:
            if fname in want:
                total += 1
                if isinstance(got, dict) and fname in got and _field_matches(
                    fname, got[fname], want[fname]
                ):
                    matched += 1
    # Penalise invented extra rows: each extra extracted row beyond truth is wrong.
    extra = max(0, len(got_txns) - len(truth_txns))
    total += extra * len(_TXN_FIELDS)

    score = (matched / total) if total else 1.0
    return score, {"matched": matched, "total": total}


def reliability_score(samples: list[dict[str, Any]], truth: dict[str, Any]) -> float:
    """Mean per-field score over N recordings of the same case (AC23.8.7).

    One recording yields a single point estimate, NOT a reliability measure — the
    limitation is documented in ``docs/ssot/cassette-graded-eval.md``. With N>=2
    samples the case score is the mean, smoothing per-run nondeterminism.
    """
    if not samples:
        return 1.0
    scores = [case_score(s, truth)[0] for s in samples]
    return sum(scores) / len(scores)


# --------------------------------------------------------------------------- #
# Loading cassettes + ground truth into scored cases.
# --------------------------------------------------------------------------- #
@dataclass
class EvalCase:
    """One eval case: a committed cassette paired with its ground truth."""

    case_id: str
    modality: str
    institution_class: str
    edge_condition: str
    extracted: dict[str, Any]
    truth: dict[str, Any]
    samples: list[dict[str, Any]] = field(default_factory=list)

    def score(self) -> float:
        if self.samples:
            return reliability_score(self.samples, self.truth)
        return case_score(self.extracted, self.truth)[0]


def _parse_extraction(cassette_path: Path) -> dict[str, Any] | None:
    """Return the parsed JSON extraction from a cassette response, or None."""
    try:
        cassette = json.loads(cassette_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    text = _response_text(cassette.get("response"))
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def load_cases(
    ground_truth_dir: Path = GROUND_TRUTH_DIR,
    cassette_dir: Path = CASSETTE_DIR,
) -> list[EvalCase]:
    """Load every cassette that has a sibling ``<id>.truth.json`` ground truth.

    The ground-truth file is the case manifest: it carries the coverage-matrix
    metadata (modality / institution_class / edge_condition), the synthetic flag,
    and the known-correct ``expected`` fields. The matching cassette
    (``<id>.json``) supplies the LLM's frozen extraction to score.
    """
    cases: list[EvalCase] = []
    for truth_path in sorted(ground_truth_dir.glob("*.truth.json")):
        case_id = truth_path.name[: -len(".truth.json")]
        truth_doc = json.loads(truth_path.read_text(encoding="utf-8"))
        extracted = _parse_extraction(cassette_dir / f"{case_id}.json")
        if extracted is None:
            raise ValueError(
                f"ground truth {truth_path.name} has no scorable cassette "
                f"{case_id}.json (extraction unreadable)"
            )
        cases.append(
            EvalCase(
                case_id=case_id,
                modality=truth_doc["modality"],
                institution_class=truth_doc["institution_class"],
                edge_condition=truth_doc["edge_condition"],
                extracted=extracted,
                truth=truth_doc["expected"],
            )
        )
    return cases


# --------------------------------------------------------------------------- #
# Ratchet evaluation.
# --------------------------------------------------------------------------- #
def ratcheted_baseline(
    baseline: dict[str, Any], current: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Raise-only merge: new floor = max(old, current) per case, plus new cases."""
    cases = dict(baseline.get("cases", {}))
    for case_id, cur in current.items():
        cur_score = float(cur.get("score", 0.0))
        prev = cases.get(case_id)
        if prev is None or cur_score >= float(prev.get("score", 0.0)):
            cases[case_id] = {
                "score": round(cur_score, 6),
                "metric": cur.get("metric", "field-accuracy"),
                "provenance": cur.get("provenance", ""),
            }
    return {"version": 1, "cases": dict(sorted(cases.items()))}


def evaluate(
    *,
    baseline_path: Path = DEFAULT_BASELINE,
    ground_truth_dir: Path = GROUND_TRUTH_DIR,
    cassette_dir: Path = CASSETTE_DIR,
    overrides: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, list[str]]:
    """Compare current per-case scores to the persisted floors.

    ``overrides`` maps ``case_id`` -> a list of substitute extractions (used by
    the reverse-proof tests to inject a regression without mutating committed
    fixtures); when given, that case is scored from the override samples.
    """
    baseline = load_jsonl(baseline_path)
    base_cases = baseline.get("cases", {})
    cases = load_cases(ground_truth_dir, cassette_dir)
    overrides = overrides or {}

    regressions: list[str] = []
    missing: list[str] = []
    new_cases: list[str] = []
    current: dict[str, dict[str, Any]] = {}

    seen: set[str] = set()
    for case in cases:
        seen.add(case.case_id)
        if case.case_id in overrides:
            cur_score = reliability_score(overrides[case.case_id], case.truth)
        else:
            cur_score = case.score()
        current[case.case_id] = {"score": cur_score}
        floor = base_cases.get(case.case_id)
        if floor is None:
            new_cases.append(f"{case.case_id}: new eval case (adopt via --update)")
            continue
        floor_score = float(floor.get("score", 0.0))
        if cur_score < floor_score - EPSILON:
            regressions.append(
                f"{case.case_id}: score {cur_score:.4f} < floor {floor_score:.4f} "
                f"(delta {cur_score - floor_score:+.4f})"
            )

    for case_id in base_cases:
        if case_id not in seen:
            missing.append(f"{case_id}: baselined case has no cassette/ground-truth in this run")

    return {
        "regressions": regressions,
        "missing": missing,
        "new": new_cases,
        "_current": current,  # type: ignore[dict-item]
    }
