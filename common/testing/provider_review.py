"""Provider-journey handoff across the explicit economic-review boundary.

This helper is deliberately fixture-driven: transaction direction is not an
accounting intent, so provider tests must supply the meaning their synthetic
fixture owns before the helper can post reviewed dispositions.
"""

from __future__ import annotations

from asyncio import sleep
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from time import monotonic
from time import sleep as blocking_sleep
from typing import Any, Protocol

# A classify run ends within 180 s (CLASSIFICATION_PHASE_DEADLINE_SECONDS in transaction_classification.py of the
# backend). The limit adds a margin. ``common/`` does not import ``apps/backend``.
RUN_POLL_SECONDS = 1.0
RUN_WAIT_SECONDS = 240.0
ACTIVE_RUN_STATES = frozenset({"requested", "running"})


class _Response(Protocol):
    status_code: int
    text: str

    def json(self) -> dict[str, Any]: ...


# An async function that sends one GET request. A journey passes one that reconnects (#2911).
Getter = Callable[[str], Awaitable[_Response]]


class _Client(Protocol):
    def get(self, path: str) -> Awaitable[_Response]: ...

    def post(
        self, path: str, json: dict[str, Any] | None = None
    ) -> Awaitable[_Response]: ...


async def _send_get(client: _Client, get: Getter | None, url: str) -> _Response:
    """Send one GET request through ``get`` when the caller passes it, and through ``client.get`` otherwise."""
    return await (client.get(url) if get is None else get(url))


@dataclass(frozen=True)
class FixtureDisposition:
    """Explicit economic meaning owned by a synthetic provider fixture."""

    intent: str
    account_type: str
    rationale: str
    category: str | None = None


@dataclass(frozen=True)
class FixtureEnvelope:
    """Independently authored source facts, never copied from extraction output."""

    currency: str
    period_start: date
    period_end: date
    opening_balance: Decimal
    closing_balance: Decimal
    rationale: str


async def _confirm_fixture_envelope(
    client: _Client,
    api_url: Callable[[str], str],
    statement_id: str,
    envelope: FixtureEnvelope,
    *,
    get: Getter | None = None,
) -> None:
    review = _require_success(
        await _send_get(client, get, api_url(f"/statements/{statement_id}/review")),
        action="source review lookup",
    )
    digest = review.get("source_result_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise AssertionError("source review has no exact current extraction digest")
    account_id = review.get("account_id")
    if not account_id:
        account = _require_success(
            await client.post(
                api_url("/accounts"),
                json={
                    "name": f"E2E reviewed source {envelope.currency}",
                    "type": "ASSET",
                    "currency": envelope.currency,
                },
            ),
            action="source custody creation",
        )
        account_id = account["id"]
    response = await client.post(
        api_url(f"/statements/{statement_id}/review/envelope"),
        json={
            "source_result_digest": digest,
            "account_id": account_id,
            "currency": envelope.currency,
            "period_start": envelope.period_start.isoformat(),
            "period_end": envelope.period_end.isoformat(),
            "opening_balance": str(envelope.opening_balance),
            "closing_balance": str(envelope.closing_balance),
            "rationale": envelope.rationale,
        },
    )
    _require_success(response, action="fixture source envelope confirmation")


def _description_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _require_success(response: _Response, *, action: str) -> dict[str, Any]:
    if not 200 <= response.status_code < 300:
        raise AssertionError(
            f"{action} failed with HTTP {response.status_code}: {response.text}"
        )
    return response.json()


def has_active_run(runs: Mapping[str, Any]) -> bool:
    """True when ``GET /statements/{id}/runs`` lists a run that is requested or running."""
    return any(run.get("state") in ACTIVE_RUN_STATES for run in runs.get("items", ()))


async def wait_for_statement_runs(client: _Client, get: Getter | None, runs_url: str) -> None:
    """Poll the runs list until no run is active (#2994).

    The approval answers 409 with ``active_run_id`` while a run is active, for example the classify run that
    follows each extraction. At the limit this returns and does not raise: the approval then gets the honest
    answer of the server.
    """
    deadline = monotonic() + RUN_WAIT_SECONDS
    while True:
        runs = _require_success(await _send_get(client, get, runs_url), action="statement runs lookup")
        if not has_active_run(runs) or monotonic() >= deadline:
            return
        await sleep(RUN_POLL_SECONDS)


def wait_for_statement_runs_sync(client: Any, runs_url: str) -> None:
    """The blocking twin of ``wait_for_statement_runs`` for the scripts that use a synchronous client."""
    deadline = monotonic() + RUN_WAIT_SECONDS
    while True:
        response = client.get(runs_url)
        _require_success(response, action="statement runs lookup")
        if not has_active_run(response.json()) or monotonic() >= deadline:
            return
        blocking_sleep(RUN_POLL_SECONDS)


async def approve_statement_with_fixture_review(
    client: _Client,
    *,
    api_url: Callable[[str], str],
    statement_id: str,
    transactions: Sequence[Mapping[str, Any]],
    dispositions: Mapping[str, FixtureDisposition],
    envelope: FixtureEnvelope | None = None,
    get: Getter | None = None,
) -> dict[str, Any]:
    """Wait for the runs, approve, resolve ``intent_missing`` from fixture facts, retry.

    The helper first polls the runs list until no run is active (at least 1 GET request). It sends
    2 more GET requests when the approval needs them: the source review lookup and the unmatched
    lookup. All of them use ``get`` when the caller passes it, and ``client.get`` otherwise. A POST
    never uses ``get``.
    """

    await wait_for_statement_runs(
        client, get, api_url(f"/statements/{statement_id}/runs")
    )
    approval_path = api_url(f"/statements/{statement_id}/review/approve")
    approval = await client.post(
        approval_path, json={"create_account_if_missing": True}
    )
    if 200 <= approval.status_code < 300:
        return {**approval.json(), "reviewed_dispositions": 0}

    detail = str(approval.json().get("detail", ""))
    if (
        approval.status_code == 400
        and detail
        == "Current source requires explicit human confirmation before posting"
    ):
        if envelope is None:
            raise AssertionError(
                "source confirmation requires an independently authored fixture envelope"
            )
        await _confirm_fixture_envelope(
            client, api_url, statement_id, envelope, get=get
        )
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
    unmatched_response = await _send_get(
        client,
        get,
        api_url(f"/reconciliation/unmatched?statement_id={statement_id}"),
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
