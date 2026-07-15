"""LLM cassette integrity gate (EPIC-023 AC23.7 / issue #1307).

Detectable drift for the committed record/replay cassettes: every cassette whose
frozen response is a *statement extraction* (has ``opening_balance`` +
``closing_balance`` + ``transactions``) MUST satisfy the balance-chain invariant
``opening + Σ amounts ≈ closing`` (Decimal, never float). A re-recorded cassette
where the LLM drifted into an inconsistent extraction fails this gate.

This is a pure-Python gate (no key, no network, no DB): it runs in the lint job,
NOT as a pytest step in a shard, so it cannot perturb the AC behavioral-score
aggregator. It complements the replay tests (which assert the same invariant per
scene) by gating cassette integrity for the whole corpus on every PR.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CASSETTE_DIR = REPO_ROOT / "common" / "testing" / "fixtures" / "llm_cassettes"
TOLERANCE = Decimal("0.01")
_STATEMENT_KEYS = ("opening_balance", "closing_balance", "transactions")
# Mirror services/validation.normalize_amount_direction: the canonical extraction
# carries a magnitude ``amount`` plus a ``direction`` (IN credits / OUT debits);
# only when direction is absent do we fall back to the sign of ``amount``.
_IN_DIRECTIONS = {"IN", "CREDIT", "CR", "DEPOSIT", "INFLOW"}
_OUT_DIRECTIONS = {"OUT", "DEBIT", "DR", "WITHDRAWAL", "WITHDRAW", "OUTFLOW", "PAYMENT"}


def _response_text(response: object) -> str | None:
    """Extract the frozen response text across the cassette response shapes."""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        for key in ("stream_text", "text"):
            value = response.get(key)
            if isinstance(value, str):
                return value
        try:
            content = response["choices"][0]["message"]["content"]
            return content if isinstance(content, str) else None
        except (KeyError, IndexError, TypeError):
            return None
    return None


def _as_decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def balance_violation(payload: dict) -> str | None:
    """Return a violation message if the statement payload breaks the chain."""
    opening = _as_decimal(payload.get("opening_balance"))
    closing = _as_decimal(payload.get("closing_balance"))
    txns = payload.get("transactions")
    if opening is None or closing is None or not isinstance(txns, list):
        return "unparseable opening/closing/transactions"
    net = Decimal("0")
    for txn in txns:
        amount = _as_decimal(txn.get("amount")) if isinstance(txn, dict) else None
        if amount is None:
            return "transaction with unparseable amount"
        direction = (
            str(txn.get("direction") or "").strip().upper()
            if isinstance(txn, dict)
            else ""
        )
        if direction in _IN_DIRECTIONS:
            net += abs(amount)
        elif direction in _OUT_DIRECTIONS:
            net -= abs(amount)
        else:
            net += amount  # no direction -> trust the sign of the amount
    diff = abs((opening + net) - closing)
    if diff > TOLERANCE:
        return f"balance chain broken: opening {opening} + net {net} != closing {closing} (diff {diff})"
    return None


def _balance_exempt(cassette_dir: Path, fingerprint: str) -> bool:
    """A cassette is balance-exempt when its sibling ground truth declares the SOURCE
    statement does not reconcile by construction (``balance_reconciles: false``).

    Real statements always reconcile, so this never excuses a real-statement drift; it
    only covers test corpora whose source data has an internally inconsistent balance
    column (e.g. some generated/synthetic statement datasets), where asserting
    ``opening + Σ ≈ closing`` would assert a property the source itself fails. Such
    cassettes are still scored on field accuracy by the graded-eval gate (AC23.8)."""
    truth_path = cassette_dir / "ground_truth" / f"{fingerprint}.truth.json"
    try:
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(truth, dict) and truth.get("balance_reconciles") is False


def check(cassette_dir: Path = CASSETTE_DIR) -> list[str]:
    """Return one message per statement cassette that violates the invariant."""
    violations: list[str] = []
    for path in sorted(cassette_dir.glob("*.json")):
        try:
            cassette = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            violations.append(f"{path.name}: unreadable cassette ({exc})")
            continue
        text = _response_text(cassette.get("response"))
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue  # not a JSON extraction response — out of scope here
        if not (
            isinstance(payload, dict) and all(k in payload for k in _STATEMENT_KEYS)
        ):
            continue  # not a statement-shaped extraction
        if _balance_exempt(cassette_dir, path.stem):
            continue  # non-reconciling source by construction — field-graded only (AC23.8)
        problem = balance_violation(payload)
        if problem is not None:
            violations.append(f"{path.name}: {problem}")
    return violations


def exempt_count(cassette_dir: Path = CASSETTE_DIR) -> int:
    """Count statement cassettes skipped via ``balance_reconciles: false`` (for an
    auditable log line — the exemption is never silent)."""
    return sum(
        1
        for path in cassette_dir.glob("*.json")
        if _balance_exempt(cassette_dir, path.stem)
    )


def statement_cassette_count(cassette_dir: Path = CASSETTE_DIR) -> int:
    """Count statement-shaped cassettes, skipping unreadable ones (never raises)."""
    count = 0
    for path in cassette_dir.glob("*.json"):
        try:
            cassette = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        text = _response_text(cassette.get("response"))
        if text and _is_statement(text):
            count += 1
    return count


def main() -> int:
    if not CASSETTE_DIR.exists():
        print(f"[CASSETTE] no cassette dir at {CASSETTE_DIR}; nothing to check.")
        return 0
    violations = check()
    statement_count = statement_cassette_count()
    if violations:
        for message in violations:
            print(f"::error title=LLM cassette integrity::{message}", file=sys.stderr)
        print(
            f"[CASSETTE] FAILED: {len(violations)} statement cassette(s) break the "
            "balance-chain invariant — a drifted/bad re-record. Re-record correctly "
            "(make llm-record) or fix the source statement.",
            file=sys.stderr,
        )
        return 1
    exempt = exempt_count()
    suffix = (
        f" ({exempt} balance-exempt via balance_reconciles=false — non-reconciling source, field-graded only)"
        if exempt
        else ""
    )
    print(
        f"[CASSETTE] PASSED: {statement_count - exempt} statement cassette(s) satisfy the "
        f"balance-chain invariant{suffix}."
    )
    return 0


def _is_statement(text: str) -> bool:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and all(k in payload for k in _STATEMENT_KEYS)


if __name__ == "__main__":
    raise SystemExit(main())
