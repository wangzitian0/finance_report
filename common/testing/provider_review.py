"""Provider-journey handoff across the explicit economic-review boundary.

This helper is deliberately fixture-driven: transaction direction is not an
accounting intent, so provider tests must supply the meaning their synthetic
fixture owns before the helper can post reviewed dispositions.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class _Response(Protocol):
    status_code: int
    text: str

    def json(self) -> dict[str, Any]: ...


class _Client(Protocol):
    def get(self, path: str) -> Awaitable[_Response]: ...

    def post(
        self, path: str, json: dict[str, Any] | None = None
    ) -> Awaitable[_Response]: ...


@dataclass(frozen=True)
class FixtureDisposition:
    """Explicit economic meaning owned by a synthetic provider fixture."""

    intent: str
    account_type: str
    rationale: str
    category: str | None = None


def _description_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _require_success(response: _Response, *, action: str) -> dict[str, Any]:
    if not 200 <= response.status_code < 300:
        raise AssertionError(
            f"{action} failed with HTTP {response.status_code}: {response.text}"
        )
    return response.json()


async def approve_statement_with_fixture_review(
    client: _Client,
    *,
    api_url: Callable[[str], str],
    statement_id: str,
    transactions: Sequence[Mapping[str, Any]],
    dispositions: Mapping[str, FixtureDisposition],
) -> dict[str, Any]:
    """Approve, resolve ``intent_missing`` from fixture facts, then retry."""

    approval_path = api_url(f"/statements/{statement_id}/review/approve")
    approval = await client.post(
        approval_path, json={"create_account_if_missing": True}
    )
    if 200 <= approval.status_code < 300:
        return {**approval.json(), "reviewed_dispositions": 0}

    detail = str(approval.json().get("detail", ""))
    if approval.status_code != 409 or not detail.startswith(
        "Economic review required:"
    ):
        raise AssertionError(
            f"statement approval failed outside the review boundary: HTTP {approval.status_code}: {approval.text}"
        )

    plans = {
        _description_key(description): plan
        for description, plan in dispositions.items()
    }
    unmatched_response = await client.get(
        api_url(f"/reconciliation/unmatched?statement_id={statement_id}")
    )
    unresolved = _require_success(
        unmatched_response, action="statement-scoped unmatched lookup"
    ).get("items", [])
    account_ids: dict[tuple[str, str], str] = {}
    reviewed = 0
    known_transactions = {
        str(transaction.get("id")): transaction for transaction in transactions
    }
    for unresolved_transaction in unresolved:
        transaction = known_transactions.get(
            str(unresolved_transaction.get("id")), unresolved_transaction
        )
        description = str(transaction.get("description", ""))
        plan = plans.get(_description_key(description))
        if plan is None:
            raise AssertionError(
                f"synthetic fixture has no explicit disposition for {description!r}"
            )

        currency = str(transaction.get("currency") or "SGD")
        account_key = (plan.account_type, currency)
        account_id = account_ids.get(account_key)
        if account_id is None:
            account_response = await client.post(
                api_url("/accounts"),
                json={
                    "name": f"E2E reviewed {plan.account_type.title()} {currency}",
                    "type": plan.account_type,
                    "currency": currency,
                },
            )
            account_id = str(
                _require_success(account_response, action="counter-account creation")[
                    "id"
                ]
            )
            account_ids[account_key] = account_id

        payload: dict[str, Any] = {
            "intent": plan.intent,
            "counter_account_id": account_id,
            "rationale": plan.rationale,
        }
        if plan.category is not None:
            payload["category"] = plan.category
        disposition_response = await client.post(
            api_url(
                f"/reconciliation/unmatched/{transaction['id']}/reviewed-disposition"
            ),
            json=payload,
        )
        _require_success(disposition_response, action="reviewed disposition")
        reviewed += 1

    final_approval = await client.post(
        approval_path, json={"create_account_if_missing": True}
    )
    return {
        **_require_success(final_approval, action="approval after economic review"),
        "reviewed_dispositions": reviewed,
    }
