from __future__ import annotations

import ast
import importlib
import sys
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db


@pytest.fixture
def loader(monkeypatch):
    module = importlib.import_module("src.reconciliation.extension.config")
    monkeypatch.setattr(module, "_config_cache", None)
    for key in ("RECONCILIATION_AUTO_ACCEPT_THRESHOLD", "RECONCILIATION_REVIEW_THRESHOLD", "ENABLE_AI_RECONCILIATION"):
        monkeypatch.delenv(key, raising=False)
    return module


def test_runtime_configuration_file_precedence_and_cache(loader, tmp_path, monkeypatch):
    from src.config import Settings
    from src.reconciliation import DEFAULT_CONFIG, ReconciliationConfig, load_reconciliation_config

    assert load_reconciliation_config is loader.load_reconciliation_config
    assert load_reconciliation_config(force_reload=True) == DEFAULT_CONFIG and DEFAULT_CONFIG.enable_ai_reconciliation is True and Settings(_env_file=None).enable_ai_reconciliation is True
    assert Path(loader.__file__).resolve().parents[3].joinpath("config/reconciliation.yaml").is_file()
    for val, expected in (("false", False), ("true", True)):
        monkeypatch.setenv("ENABLE_AI_RECONCILIATION", val)
        assert load_reconciliation_config(force_reload=True).enable_ai_reconciliation is expected
    tree = ast.parse(Path(loader.__file__).read_text(encoding="utf-8"))
    assert "ENABLE_AI_RECONCILIATION" not in [n.args[0].value for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "getenv" and n.args and isinstance(n.args[0], ast.Constant)]

    monkeypatch.delenv("ENABLE_AI_RECONCILIATION", raising=False)
    monkeypatch.setattr(loader, "__file__", str(tmp_path / "src/reconciliation/extension/config.py"))
    (tmp_path / "config").mkdir()
    (tmp_path / "config/reconciliation.yaml").write_text("scoring:\n  weights:\n    amount: 0.50\n  thresholds:\n    auto_accept: 88\n    pending_review: 62\n  tolerances:\n    amount_absolute: 0.20\n    date_days: 9\n")
    resolved = load_reconciliation_config(force_reload=True)
    assert isinstance(resolved, ReconciliationConfig) and (resolved.auto_accept, resolved.pending_review, resolved.date_days, resolved.weight_amount, resolved.amount_absolute, resolved.weight_date) == (88, 62, 9, Decimal("0.50"), Decimal("0.20"), DEFAULT_CONFIG.weight_date)
    with pytest.raises(FrozenInstanceError):
        resolved.auto_accept = 1
    for k, v in (("RECONCILIATION_AUTO_ACCEPT_THRESHOLD", "91"), ("RECONCILIATION_REVIEW_THRESHOLD", "71"), ("ENABLE_AI_RECONCILIATION", "true")):
        monkeypatch.setenv(k, v)
    assert load_reconciliation_config() is resolved
    updated = load_reconciliation_config(force_reload=True)
    assert (updated.auto_accept, updated.pending_review, updated.enable_ai_reconciliation, updated.weight_amount) == (91, 71, True, Decimal("0.50"))
    assert load_reconciliation_config() is updated and DEFAULT_CONFIG.auto_accept == 85


@pytest.mark.parametrize(("case", "yaml_body", "expected"), [("missing", None, None), ("malformed", "invalid: : yaml", None), ("no_yaml", "", None), ("empty", "", None), ('"false"', None, False), ('"true"', None, True), ("false", None, False), ("true", None, True), ("0", None, False), ("1", None, True), ('"off"', None, False), ('" yes "', None, True), ('"unknown"', None, None), ("2", None, None), ("null", None, None), ("[]", None, None)])
def test_yaml_loading_fallbacks_and_booleans(loader, tmp_path, monkeypatch, case, yaml_body, expected):
    from src.reconciliation import DEFAULT_CONFIG

    monkeypatch.setattr(loader, "__file__", str(tmp_path / "src/reconciliation/extension/config.py"))
    if case != "missing":
        (tmp_path / "config").mkdir()
        body = yaml_body if yaml_body is not None else f"scoring:\n  enable_ai_reconciliation: {case}\n  weights:\n    amount: 0.50\n"
        (tmp_path / "config/reconciliation.yaml").write_text(body)
    if case == "no_yaml":
        monkeypatch.setitem(sys.modules, "yaml", None)
    resolved = loader.load_reconciliation_config(force_reload=True)
    assert resolved == DEFAULT_CONFIG if expected is None else (resolved.enable_ai_reconciliation is expected and resolved.weight_amount == Decimal("0.50"))


def test_entry_readers_preserve_money_and_candidate_semantics():
    import src.reconciliation as public
    from src.audit import JournalEntrySourceType
    from src.ledger import Account, AccountType, Direction, JournalEntry, JournalLine
    from src.reconciliation.extension import entry_reads

    assert all(getattr(public, n) is getattr(entry_reads, n) for n in ("entry_total_amount", "entry_bank_side_amount", "is_entry_balanced", "_candidate_is_better"))
    line = lambda amt, d, cur, at: JournalLine(amount=Decimal(amt), direction=d, currency=cur, account=Account(type=at))
    entry = JournalEntry(lines=[line("80", Direction.DEBIT, "SGD", AccountType.EXPENSE), line("80", Direction.CREDIT, "SGD", AccountType.ASSET), line("7", Direction.DEBIT, "USD", AccountType.ASSET), line("7", Direction.CREDIT, "USD", AccountType.INCOME)])
    assert (public.entry_total_amount(entry, currency="SGD"), public.entry_bank_side_amount(entry, "OUT", currency="SGD"), public.entry_bank_side_amount(entry, "IN", currency="USD"), public.entry_bank_side_amount(entry, None, currency="USD"), public.entry_bank_side_amount(entry, "IN", currency="SGD")) == (Decimal("80"), Decimal("80"), Decimal("7"), Decimal("7"), Decimal("80"))
    balanced = JournalEntry(lines=entry.lines[:2])
    assert public.is_entry_balanced(balanced, base_currency="SGD")
    balanced.lines[0].amount = Decimal("79")
    assert not public.is_entry_balanced(balanced, base_currency="SGD")
    entries = {"manual": JournalEntry(source_type=JournalEntrySourceType.MANUAL), "parsed": JournalEntry(source_type=JournalEntrySourceType.AUTO_PARSED)}
    manual, parsed = public.MatchCandidate(["manual"], 80, {}), public.MatchCandidate(["parsed"], 80, {})
    assert public._candidate_is_better(manual, None, entries) and public._candidate_is_better(manual, parsed, entries)
    assert not public._candidate_is_better(parsed, manual, entries) and not public._candidate_is_better(public.MatchCandidate(["manual"], 79, {}), parsed, entries)
    assert public._candidate_is_better(public.MatchCandidate(["parsed"], 81, {}), manual, entries)
    assert entry_reads._candidate_source_rank(public.MatchCandidate([], 0, {}), {}) == 0
