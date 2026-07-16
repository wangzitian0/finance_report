"""AC-reconciliation.signature-surgery.* structural and behavior locks."""

from __future__ import annotations

import ast
import inspect
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

from src.ledger import Direction
from src.ledger.base.processing import _calculate_pair_confidence
from src.reconciliation import (
    AmountMismatchError,
    CheckResolutionAction,
    MatchNotFoundError,
    ReconciliationError,
    score_description,
)
from src.reconciliation.extension import matching
from src.reconciliation.extension.consistency_checks import resolve_check
from src.reconciliation.extension.phases import run_many_to_one_phase, run_normal_matching_phase
from src.schemas.review import ResolveCheckRequest

score_group = matching.score_group
score_single = matching.score_single

BACKEND_SRC = Path(__file__).resolve().parents[2] / "src"
RECONCILIATION_EXTENSION = BACKEND_SRC / "reconciliation" / "extension"


def _public_functions(path: Path):
    for source_path in path.rglob("*.py"):
        tree = ast.parse(source_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                yield source_path, node


def test_public_reconciliation_signatures_are_typed_and_bounded() -> None:
    """AC-reconciliation.signature-surgery.1."""
    violations: list[str] = []
    for path, node in _public_functions(RECONCILIATION_EXTENSION):
        parameters = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        untyped = [arg.arg for arg in parameters if arg.arg not in {"self", "cls"} and arg.annotation is None]
        count = len(parameters) + int(node.args.vararg is not None) + int(node.args.kwarg is not None)
        if untyped or count > 8:
            violations.append(f"{path.relative_to(BACKEND_SRC)}:{node.lineno} {node.name}: {count=} {untyped=}")
    assert violations == []


def test_matching_phases_return_created_matches() -> None:
    """AC-reconciliation.signature-surgery.2."""
    for phase in (run_many_to_one_phase, run_normal_matching_phase):
        signature = inspect.signature(phase)
        assert "context" in signature.parameters
        assert "matches" not in signature.parameters
        assert get_type_hints(phase)["return"] == list[matching.ReconciliationMatch]

    source = "\n".join(
        inspect.getsource(function)
        for function in (
            matching.execute_matching,
            run_many_to_one_phase,
            run_normal_matching_phase,
        )
    )
    for repository_call in (
        "list_pending_transactions",
        "list_journal_candidates",
        "get_active_match",
        "add_match",
    ):
        assert repository_call in source


def test_scoring_has_explicit_modes_and_no_hidden_environment_switch() -> None:
    """AC-reconciliation.signature-surgery.3."""
    assert "is_multi" not in inspect.signature(score_single).parameters
    assert "is_multi" not in inspect.signature(score_group).parameters
    assert "enable_ai_reconciliation" in matching.ReconciliationConfig.__dataclass_fields__

    for module in (matching, inspect.getmodule(score_single)):
        assert module is not None
        assert "os.getenv" not in inspect.getsource(module)


def test_reconciliation_errors_and_resolve_actions_are_typed() -> None:
    """AC-reconciliation.signature-surgery.4."""
    assert issubclass(MatchNotFoundError, ReconciliationError)
    assert issubclass(AmountMismatchError, ReconciliationError)
    assert set(CheckResolutionAction) == {
        CheckResolutionAction.APPROVE,
        CheckResolutionAction.REJECT,
        CheckResolutionAction.FLAG,
    }

    assert get_type_hints(resolve_check)["action"] is CheckResolutionAction
    assert ResolveCheckRequest.model_fields["action"].annotation is str

    router_source = (BACKEND_SRC / "routers" / "reconciliation.py").read_text()
    assert '"not found" in str(exc).lower()' not in router_source
    review_router_source = (BACKEND_SRC / "routers" / "review.py").read_text()
    assert "CheckResolutionAction(request.action)" in review_router_source


def test_description_similarity_has_one_owner_and_both_consumers_agree() -> None:
    """AC-reconciliation.signature-surgery.5."""
    imports = []
    for package in (BACKEND_SRC / "reconciliation", BACKEND_SRC / "ledger"):
        for path in package.rglob("*.py"):
            if "SequenceMatcher" in path.read_text():
                imports.append(path.relative_to(BACKEND_SRC).as_posix())
    assert imports == ["reconciliation/extension/scoring.py"]

    score = score_description("Transfer to Savings", "transfer to savings")
    processing_id = SimpleNamespace()
    out_entry = SimpleNamespace(
        memo="Transfer to Savings",
        entry_date=date(2024, 1, 1),
        lines=[SimpleNamespace(account_id=processing_id, direction=Direction.DEBIT, amount=Decimal("10"))],
    )
    in_entry = SimpleNamespace(
        memo="transfer to savings",
        entry_date=date(2024, 1, 1),
        lines=[SimpleNamespace(account_id=processing_id, direction=Direction.CREDIT, amount=Decimal("10"))],
    )
    _, breakdown = _calculate_pair_confidence(
        out_entry,
        in_entry,
        processing_id,
        description_scorer=score_description,
    )
    assert breakdown["description"] == score == 100.0
