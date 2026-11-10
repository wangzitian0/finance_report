"""EPIC-025 AC25.2.1: statement Stage-1 workflow owns the transaction + transition.

These checks pin the *contract* — the workflow performs the state-transition
service call, then posts (approve only), then commits as one unit, and the thin
router delegates to it rather than inlining the sequence. The real PARSED→APPROVED
/ PARSED→REJECTED behavior against the database is covered by the existing
``test_statements_router.py`` Stage-1 suite.
"""

from types import SimpleNamespace
from uuid import uuid4

import src.routers.statements as statements_router
from src.extraction.base.source_vocabulary import BankStatementStatus
from src.extraction.base.types import StatementPostingStatus
from src.extraction.extension import statement_workflow


class _FakeResult:
    """The scalar result of the status read that a reject performs before the transition."""

    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _FakeSession:
    """Records the transaction operations the workflow performs, in order."""

    def __init__(self, calls: list) -> None:
        self._calls = calls

    async def execute(self, statement: object, params: dict | None = None) -> _FakeResult | None:
        if "pg_advisory_xact_lock" in str(statement):
            # The release takes the advisory lock of the user before it decides which rows the statement owns (#2888).
            assert params is not None
            self._calls.append(("release_lock", params["key"]))
            return None
        self._calls.append(("read_status",))
        return _FakeResult(BankStatementStatus.PARSED)

    async def commit(self) -> None:
        self._calls.append(("commit",))

    async def refresh(self, obj: object) -> None:
        self._calls.append(("refresh", obj))


async def test_statement_workflow_service(monkeypatch):
    """AC-extraction.2502.1: AC25.2.1: approve/reject workflows own the commit + Stage-1 transition as one
    ordered unit, and the router delegates to them (no inline approve/reject+commit)."""
    statement_id = uuid4()
    user_id = uuid4()

    # --- approve: transition -> post -> commit, returns posting outcome ---
    approve_calls: list = []
    approved_statement = SimpleNamespace(id=statement_id, name="approved")

    async def fake_approve(db, sid, uid):
        assert (sid, uid) == (statement_id, user_id)
        approve_calls.append(("approve_statement",))
        return approved_statement

    async def fake_post(db, statement, uid, *, dependencies):
        assert statement is approved_statement
        assert dependencies is posting_dependencies
        approve_calls.append(("auto_post",))
        return SimpleNamespace(created_count=3, status=StatementPostingStatus.POSTED)

    async def fake_opening(db, statement, uid, *, dependencies):
        assert statement is approved_statement
        assert uid == user_id
        assert dependencies is posting_dependencies
        approve_calls.append(("opening_stock",))

    monkeypatch.setattr(statement_workflow, "try_auto_post_statement_opening_balance", fake_opening)
    monkeypatch.setattr(statement_workflow, "approve_statement", fake_approve)
    monkeypatch.setattr(statement_workflow, "auto_create_posted_entries_for_statement", fake_post)

    posting_dependencies = object()
    outcome = await statement_workflow.approve_statement_workflow(
        _FakeSession(approve_calls),
        statement_id,
        user_id,
        dependencies=posting_dependencies,
    )
    assert outcome.created_count == 3
    assert approve_calls == [("approve_statement",), ("auto_post",), ("opening_stock",), ("commit",)]

    # --- reject: status read -> transition -> release lock -> commit -> refresh, returns refreshed statement ---
    reject_calls: list = []
    rejected_statement = SimpleNamespace(id=statement_id, name="rejected")

    async def fake_reject(db, sid, uid, *, reason):
        assert (sid, uid, reason) == (statement_id, user_id, "looks wrong")
        reject_calls.append(("reject_statement",))
        return rejected_statement

    monkeypatch.setattr(statement_workflow, "reject_statement", fake_reject)

    result = await statement_workflow.reject_statement_workflow(
        _FakeSession(reject_calls), statement_id, user_id, reason="looks wrong"
    )
    assert result is rejected_statement
    assert reject_calls == [
        ("read_status",),
        ("reject_statement",),
        ("release_lock", f"statement-release:{user_id}"),
        ("commit",),
        ("refresh", rejected_statement),
    ]

    # --- delegation: the router uses the workflow contracts, not inline *_svc calls ---
    assert statements_router.approve_statement_workflow is statement_workflow.approve_statement_workflow
    assert statements_router.reject_statement_workflow is statement_workflow.reject_statement_workflow
    assert not hasattr(statements_router, "approve_statement_svc")
    assert not hasattr(statements_router, "reject_statement_svc")
