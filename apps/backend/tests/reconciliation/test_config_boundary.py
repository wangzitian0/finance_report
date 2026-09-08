"""Behavioral proofs for configuration/entry-reader ownership (#2023)."""

import importlib
import sys
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

import pytest
from common.testing.ac_proof import ac_proof

pytestmark = pytest.mark.no_db


@pytest.fixture
def loader(monkeypatch):
    module = importlib.import_module("src.reconciliation.extension.config")
    monkeypatch.setattr(module, "_config_cache", None)
    for key in ("RECONCILIATION_AUTO_ACCEPT_THRESHOLD", "RECONCILIATION_REVIEW_THRESHOLD", "ENABLE_AI_RECONCILIATION"):
        monkeypatch.delenv(key, raising=False)
    return module


@ac_proof(
    proof_id="reconciliation_runtime_configuration", ac_ids=["AC-reconciliation.config-boundary.2"], ci_tier="pr_ci"
)
def test_runtime_configuration_file_precedence_and_cache(loader, tmp_path, monkeypatch):
    """AC-reconciliation.config-boundary.2: real files expose the old wrong-parent bug."""
    from src.reconciliation import DEFAULT_CONFIG, ReconciliationConfig, load_reconciliation_config

    assert load_reconciliation_config is loader.load_reconciliation_config
    assert load_reconciliation_config(force_reload=True) == DEFAULT_CONFIG  # shipped file preserves defaults
    assert Path(loader.__file__).resolve().parents[3].joinpath("config/reconciliation.yaml").is_file()
    monkeypatch.setattr(loader, "__file__", str(tmp_path / "src/reconciliation/extension/config.py"))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "reconciliation.yaml"
    config_file.write_text(
        "scoring:\n  weights:\n    amount: 0.50\n  thresholds:\n    auto_accept: 88\n    pending_review: 62\n  tolerances:\n    amount_absolute: 0.20\n    date_days: 9\n"
    )
    resolved = load_reconciliation_config(force_reload=True)
    assert isinstance(resolved, ReconciliationConfig)
    assert (resolved.auto_accept, resolved.pending_review, resolved.date_days) == (88, 62, 9)
    assert resolved.weight_amount == Decimal("0.50")
    assert resolved.amount_absolute == Decimal("0.20")
    assert resolved.weight_date == DEFAULT_CONFIG.weight_date
    with pytest.raises(FrozenInstanceError):
        resolved.auto_accept = 1
    monkeypatch.setenv("RECONCILIATION_AUTO_ACCEPT_THRESHOLD", "91")
    monkeypatch.setenv("RECONCILIATION_REVIEW_THRESHOLD", "71")
    monkeypatch.setenv("ENABLE_AI_RECONCILIATION", "true")
    assert load_reconciliation_config() is resolved
    updated = load_reconciliation_config(force_reload=True)
    assert (updated.auto_accept, updated.pending_review, updated.enable_ai_reconciliation) == (91, 71, True)
    assert updated.weight_amount == Decimal("0.50")
    assert load_reconciliation_config() is updated
    assert DEFAULT_CONFIG.auto_accept == 85


@pytest.mark.parametrize("case", ["missing", "malformed", "no_yaml", "empty"])
def test_runtime_configuration_defaults_survive_missing_inputs(loader, tmp_path, monkeypatch, case):
    """AC-reconciliation.config-boundary.2: unavailable/invalid YAML preserves fallback."""
    from src.reconciliation import DEFAULT_CONFIG

    monkeypatch.setattr(loader, "__file__", str(tmp_path / "src/reconciliation/extension/config.py"))
    if case != "missing":
        (tmp_path / "config").mkdir()
        (tmp_path / "config/reconciliation.yaml").write_text("invalid: : yaml" if case == "malformed" else "")
    if case == "no_yaml":
        monkeypatch.setitem(sys.modules, "yaml", None)
    assert loader.load_reconciliation_config(force_reload=True) == DEFAULT_CONFIG


@ac_proof(proof_id="reconciliation_entry_readers", ac_ids=["AC-reconciliation.config-boundary.3"], ci_tier="pr_ci")
def test_entry_readers_preserve_money_and_candidate_semantics():
    """AC-reconciliation.config-boundary.3: real ORM values keep bank-side/caliber rules."""
    import src.reconciliation as public
    from src.audit import JournalEntrySourceType
    from src.ledger import Account, AccountType, Direction, JournalEntry, JournalLine
    from src.reconciliation.extension import entry_reads

    for name in ("entry_total_amount", "entry_bank_side_amount", "is_entry_balanced", "_candidate_is_better"):
        assert getattr(public, name) is getattr(entry_reads, name)

    def line(amount, direction, currency, account_type):
        return JournalLine(
            amount=Decimal(amount), direction=direction, currency=currency, account=Account(type=account_type)
        )

    entry = JournalEntry(
        lines=[
            line("80", Direction.DEBIT, "SGD", AccountType.EXPENSE),
            line("80", Direction.CREDIT, "SGD", AccountType.ASSET),
            line("7", Direction.DEBIT, "USD", AccountType.ASSET),
            line("7", Direction.CREDIT, "USD", AccountType.INCOME),
        ]
    )
    assert public.entry_total_amount(entry, currency="SGD") == Decimal("80")
    assert public.entry_bank_side_amount(entry, "OUT", currency="SGD") == Decimal("80")
    assert public.entry_bank_side_amount(entry, "IN", currency="USD") == Decimal("7")
    assert public.entry_bank_side_amount(entry, None, currency="USD") == Decimal("7")
    assert public.entry_bank_side_amount(entry, "IN", currency="SGD") == Decimal("80")
    balanced = JournalEntry(lines=entry.lines[:2])
    assert public.is_entry_balanced(balanced, base_currency="SGD")
    balanced.lines[0].amount = Decimal("79")
    assert not public.is_entry_balanced(balanced, base_currency="SGD")
    entries = {
        "manual": JournalEntry(source_type=JournalEntrySourceType.MANUAL),
        "parsed": JournalEntry(source_type=JournalEntrySourceType.AUTO_PARSED),
    }
    manual = public.MatchCandidate(["manual"], 80, {})
    parsed = public.MatchCandidate(["parsed"], 80, {})
    assert public._candidate_is_better(manual, None, entries)
    assert public._candidate_is_better(manual, parsed, entries)
    assert not public._candidate_is_better(parsed, manual, entries)
    assert not public._candidate_is_better(public.MatchCandidate(["manual"], 79, {}), parsed, entries)
    assert public._candidate_is_better(public.MatchCandidate(["parsed"], 81, {}), manual, entries)
    assert entry_reads._candidate_source_rank(public.MatchCandidate([], 0, {}), {}) == 0
