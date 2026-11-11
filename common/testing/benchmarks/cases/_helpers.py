"""Shared helpers for scenario benchmark case modules."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

from common.testing.benchmarks.case_types import CaseResult
from common.testing.benchmarks.oracles import assert_triple_accounting_articulation


def set_verdict(details: dict[str, Any] | None, key: str, passed: bool) -> bool:
    if details is not None:
        details.setdefault("assertion_verdicts", {})[key] = (
            "passed" if passed else "failed"
        )
    return passed


def check_verdict(
    details: dict[str, Any] | None, key: str, passed: bool, message: str = ""
) -> None:
    set_verdict(details, key, passed)
    assert passed, message


def je_line(
    account: dict[str, Any] | str,
    direction: str,
    amount: str,
    currency: str = "SGD",
) -> dict[str, Any]:
    acc_id = account["id"] if isinstance(account, dict) else account
    return {
        "account_id": acc_id,
        "direction": direction,
        "amount": amount,
        "currency": currency,
    }


def articulate(
    bs: dict[str, Any],
    inc: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    verdict_key: str = "equation_delta",
) -> None:
    try:
        assert_triple_accounting_articulation(bs, inc)
    except AssertionError:
        set_verdict(details, verdict_key, False)
        raise


def run_case(
    case_id: str,
    case_name: str,
    verdict_keys: Sequence[str],
    body: Callable[[dict[str, Any]], None],
) -> CaseResult:
    start_time = time.time()
    details: dict[str, Any] = {
        "assertion_verdicts": {k: "not_run" for k in verdict_keys}
    }
    try:
        body(details)
        return CaseResult(
            case_id=case_id,
            case_name=case_name,
            status="PASS",
            duration_seconds=time.time() - start_time,
            details=details,
        )
    except Exception as exc:
        return CaseResult(
            case_id=case_id,
            case_name=case_name,
            status="FAIL",
            duration_seconds=time.time() - start_time,
            details=details,
            error_message=str(exc),
        )
