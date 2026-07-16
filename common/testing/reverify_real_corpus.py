"""Periodic re-verification of the real cassette corpus against LIVE extraction
(#1744 item (c), gate re-architecture Phase 1 residual).

#1681's cassette corpus (9 of 10 cases are the operator's own real statements)
proves DOWNSTREAM logic (posting/reconciliation/report aggregation) is correct
given a correct extraction — it never re-runs extraction, so it cannot detect a
regression in the extraction/prompt/coercion code, or drift in the underlying
provider's real-world behavior, for a document it already has a cassette for.

This module closes that gap for the cases the corpus already has: given the
ORIGINAL real PDF (never committed — RL-6; the operator supplies its local
path), it re-runs the REAL extraction pipeline against the REAL provider,
scores the fresh result against the case's ground truth the same way
``cassette_graded_eval.case_score`` does, and reports a regression/improvement
verdict WITHOUT silently overwriting the committed cassette — a human decides
whether to accept a fresh recording (a real fix/improvement), investigate a
regression, or note provider drift.

Operator-only, like ``make llm-record``: needs a real provider key and the
operator's own local copy of the real PDF (RL-6 — never committed). Pure
comparison logic (``compare_scores``) is unit-testable without either.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from common.testing.cassette_graded_eval import GROUND_TRUTH_DIR, case_score
from common.testing.check_llm_cassettes import CASSETTE_DIR


class LiveExtractor(Protocol):
    """A callable that performs the real extraction (DI seam for testing)."""

    def __call__(self, pdf_path: Path) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class ReverifyResult:
    case_id: str
    old_score: float
    new_score: float | None
    verdict: str  # "no_change" | "improved" | "regressed" | "recording_failed"
    detail: str


def compare_scores(
    case_id: str,
    *,
    old_extracted: dict[str, Any],
    new_extracted: dict[str, Any] | None,
    truth: dict[str, Any],
    epsilon: float = 1e-6,
) -> ReverifyResult:
    """Pure comparison: old committed extraction vs a freshly re-recorded one.

    ``new_extracted`` is ``None`` when the live re-record failed to produce a
    usable response (e.g. no provider key, or an empty/unparseable reply) — a
    distinct, safe-to-ignore outcome from a genuine field-accuracy regression.
    """
    old_score, _ = case_score(old_extracted, truth)
    if new_extracted is None:
        return ReverifyResult(
            case_id=case_id,
            old_score=old_score,
            new_score=None,
            verdict="recording_failed",
            detail="Live re-record produced no usable response (missing key, "
            "empty reply, or unparseable JSON) — old cassette left untouched.",
        )
    new_score, _ = case_score(new_extracted, truth)
    if new_score < old_score - epsilon:
        return ReverifyResult(
            case_id=case_id,
            old_score=old_score,
            new_score=new_score,
            verdict="regressed",
            detail=f"Fresh extraction scores {new_score:.4f} vs committed "
            f"{old_score:.4f} (delta {new_score - old_score:+.4f}) — a code "
            "regression or provider drift; investigate before re-recording.",
        )
    if new_score > old_score + epsilon:
        return ReverifyResult(
            case_id=case_id,
            old_score=old_score,
            new_score=new_score,
            verdict="improved",
            detail=f"Fresh extraction scores {new_score:.4f} vs committed "
            f"{old_score:.4f} — re-record with `make llm-record` to adopt.",
        )
    return ReverifyResult(
        case_id=case_id,
        old_score=old_score,
        new_score=new_score,
        verdict="no_change",
        detail=f"Fresh extraction matches the committed score ({old_score:.4f}).",
    )


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def reverify_case(
    case_id: str,
    pdf_path: Path,
    live_extractor: LiveExtractor,
    *,
    cassette_dir: Path = CASSETTE_DIR,
    ground_truth_dir: Path = GROUND_TRUTH_DIR,
) -> ReverifyResult:
    """Re-verify one committed case against a fresh live extraction of ``pdf_path``.

    Never mutates the committed cassette: reads the current one, calls
    ``live_extractor`` (the real provider call, injected so this function is
    unit-testable without one), scores both, and returns the verdict. Adopting
    an improvement is a separate, explicit `make llm-record` step — this
    function only informs the decision.
    """
    truth_path = ground_truth_dir / f"{case_id}.truth.json"
    cassette_path = cassette_dir / f"{case_id}.json"
    truth_doc = _load_json(truth_path)
    if truth_doc is None:
        raise FileNotFoundError(f"no ground truth for case {case_id!r}: {truth_path}")
    cassette_doc = _load_json(cassette_path)
    if cassette_doc is None:
        raise FileNotFoundError(
            f"no committed cassette for case {case_id!r}: {cassette_path}"
        )

    old_extracted = json.loads(cassette_doc["response"]["stream_text"])
    new_extracted = live_extractor(pdf_path)

    return compare_scores(
        case_id,
        old_extracted=old_extracted,
        new_extracted=new_extracted,
        truth=truth_doc["expected"],
    )


def render_report(results: list[ReverifyResult]) -> str:
    lines = ["## Real-Corpus Re-Verification (#1744 item c)", ""]
    lines.append("| Case | Verdict | Old Score | New Score |")
    lines.append("|---|---|---|---|")
    for result in results:
        new_score_label = (
            f"{result.new_score:.4f}" if result.new_score is not None else "n/a"
        )
        lines.append(
            f"| `{result.case_id}` | `{result.verdict}` | `{result.old_score:.4f}` | "
            f"`{new_score_label}` |"
        )
    lines.append("")
    for result in results:
        if result.verdict != "no_change":
            lines.append(
                f"- **{result.case_id}** (`{result.verdict}`): {result.detail}"
            )
    return "\n".join(lines) + "\n"


def run(argv: list[str] | None = None, *, live_extractor: LiveExtractor) -> int:
    """CLI orchestration only — deliberately domain-agnostic (common/testing is
    infra-tier and must not import a specific domain package's extraction code;
    see tools/reverify_real_corpus.py for the concrete extractor + entrypoint).
    """
    parser = argparse.ArgumentParser(
        description=(
            "Re-verify a real corpus case against a fresh LIVE extraction of its "
            "original PDF (#1744 item c). Operator-only: needs a real provider "
            "key and the original PDF's local path (never committed — RL-6). "
            "Never mutates the committed cassette; a regression or improvement "
            "is reported, not auto-applied."
        )
    )
    parser.add_argument(
        "--case-id",
        required=True,
        help="The cassette fingerprint (case id) to re-verify.",
    )
    parser.add_argument(
        "--pdf",
        required=True,
        type=Path,
        help="Local path to the original PDF (operator-supplied, never committed).",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"::error::PDF not found: {args.pdf}", file=sys.stderr)
        return 2

    result = reverify_case(args.case_id, args.pdf, live_extractor)
    report = render_report([result])
    print(report)
    if args.output:
        args.output.write_text(report, encoding="utf-8")

    if result.verdict == "regressed":
        return 1
    return 0
