"""ORM value-type boundary guards (EPIC-012 AC12.35, #3 boundary push).

The read/model layer hands business code typed values (Money/Quantity) so services
stop pulling raw Decimal off rows and wrapping it ad-hoc. Raw columns remain the
storage/write boundary; business reads the typed accessors. This is the pilot on
ManagedPosition + investment_accounting; other models/services follow.
"""

import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]

# Business files where ManagedPosition money is fully migrated to typed accessors.
MIGRATED_MANAGED_POSITION_FILES = [
    "apps/backend/src/portfolio/extension/holdings.py",
    "apps/backend/src/portfolio/extension/accounting.py",
    "apps/backend/src/pricing/extension/valuation.py",
    "apps/backend/src/portfolio/extension/positions.py",
    "apps/backend/src/portfolio/extension/performance_report.py",
    "apps/backend/src/services/reporting/portfolio_market.py",
]
# A raw money-column READ: position.cost_basis / unrealized_pnl / realized_pnl that
# is not the typed accessor (`_money`), not a different column (`_method`), and not
# a write (`position.x = ...`, the allowed storage edge). The write lookahead
# matches a single `=` assignment regardless of whitespace, but not `==`/`!=`
# (those are comparisons, i.e. reads).
_RAW_MANAGED_POSITION_MONEY_READ = re.compile(
    r"position\.(?:cost_basis|unrealized_pnl|realized_pnl)(?!_money|_method)(?!\s*=(?!=))"
)


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


@ac_proof(
    proof_id="test_managed_position_money_accessors",
    ac_ids=["AC-audit.35.1"],
    ci_tier="pr_ci",
)
def test_AC12_35_1_managed_position_exposes_typed_accessors():
    """AC-audit.35.1: ManagedPosition exposes Money/Quantity read accessors at the ORM boundary."""
    src = _read("apps/backend/src/models/layer3.py")
    assert "from src.audit.money import Money" in src
    assert "from src.audit.quantity import Quantity" in src
    for accessor in (
        "def cost_basis_money(self) -> Money",
        "def unrealized_pnl_money(self) -> Money",
        "def realized_pnl_money(self) -> Money",
        "def quantity_qty(self) -> Quantity",
    ):
        assert accessor in src, f"ManagedPosition must expose `{accessor}`"


@ac_proof(
    proof_id="test_investment_accounting_reads_typed",
    ac_ids=["AC-audit.35.2"],
    ci_tier="pr_ci",
)
def test_AC12_35_2_investment_accounting_reads_position_via_accessors():
    """AC-audit.35.2: investment accounting updates position state via the typed accessors,
    not by re-wrapping raw Decimal columns."""
    src = _read("apps/backend/src/portfolio/extension/accounting.py")
    assert "position.cost_basis_money" in src
    assert "position.realized_pnl_money" in src
    assert "position.quantity_qty" in src
    # the raw-Decimal read patterns are gone (writes to the column stay as the boundary)
    assert "to_money(position.cost_basis" not in src
    assert "position.realized_pnl or Decimal" not in src
    assert "Quantity(position.quantity," not in src


@ac_proof(
    proof_id="test_portfolio_holdings_money_native",
    ac_ids=["AC-audit.35.3"],
    ci_tier="pr_ci",
)
def test_AC12_35_3_portfolio_holdings_value_flows_as_money():
    """AC-audit.35.3: portfolio holdings valuation flows as Money end-to-end via a
    Money-native FX convert + the ManagedPosition accessors (no Decimal FX branch)."""
    fx = _read("apps/backend/src/services/fx.py")
    assert "async def convert_money(" in fx, (
        "fx must expose a Money-native convert helper"
    )
    src = _read("apps/backend/src/portfolio/extension/holdings.py")
    # Money-native FX convert via pricing's published surface (#1643).
    assert "convert_money(" in src
    assert "position.cost_basis_money" in src
    assert "position.quantity_qty" in src
    assert "UnitPrice(latest_price" in src

    # reporting's portfolio valuation also flows Money via the same helpers
    market = _read("apps/backend/src/services/reporting/portfolio_market.py")
    assert "fx.convert_money(" in market
    assert "position.cost_basis_money" in market
    assert "position.quantity_qty" in market


@ac_proof(
    proof_id="test_managed_position_raw_reads_forbidden",
    ac_ids=["AC-audit.35.4"],
    ci_tier="pr_ci",
)
def test_AC12_35_4_no_raw_managed_position_money_reads_in_migrated_files():
    """AC-audit.35.4 (ratchet): the migrated business files read ManagedPosition money
    only via the typed accessors — no raw position.cost_basis/unrealized_pnl/
    realized_pnl reads remain (writes `position.x = ...` at the storage edge stay
    allowed). This forbids the old raw-Decimal pattern from creeping back."""
    offenders = {
        path: _RAW_MANAGED_POSITION_MONEY_READ.findall(_read(path))
        for path in MIGRATED_MANAGED_POSITION_FILES
        if _RAW_MANAGED_POSITION_MONEY_READ.search(_read(path))
    }
    assert not offenders, (
        f"raw ManagedPosition money reads must use accessors: {offenders}"
    )


@ac_proof(
    proof_id="test_journal_line_money_accessor",
    ac_ids=["AC-audit.37.1"],
    ci_tier="pr_ci",
)
def test_AC12_37_1_journal_line_exposes_money_accessor():
    """AC-audit.37.1: JournalLine exposes a typed `money` read accessor at the ORM
    boundary (lines are immutable; amount/currency columns stay storage)."""
    src = _read("apps/backend/src/models/journal.py")
    assert "from src.audit.money import Money" in src
    assert "def money(self) -> Money" in src


@ac_proof(
    proof_id="test_reconciliation_config_sums_money",
    ac_ids=["AC-audit.37.2"],
    ci_tier="pr_ci",
)
def test_AC12_37_2_reconciliation_config_sums_lines_as_money():
    """AC-audit.37.2: reconciliation entry-amount helpers sum journal lines via the
    typed `line.money` accessor + `Money.sum` (currency-checked), not a raw
    currency-blind `sum(line.amount)`."""
    src = _read("apps/backend/src/reconciliation/base/config.py")
    assert "line.money" in src
    assert "Money.sum(" in src
    assert "sum(line.amount" not in src


@ac_proof(
    proof_id="test_income_statement_converts_money_native",
    ac_ids=["AC-audit.37.3"],
    ci_tier="pr_ci",
)
def test_AC12_37_3_income_statement_fx_is_money_native():
    """AC-audit.37.3: the income-statement slow-path FX converts journal lines via the
    Money-native `convert_money(line.money, ...)`, not raw `convert_amount(line.amount)`."""
    src = _read("apps/backend/src/services/reporting/income_statement.py")
    assert "convert_money(" in src
    assert "line.money" in src
    # robust: income_statement no longer references raw convert_amount at all
    # (import or call) — catches positional / intermediate-variable regressions
    # that an `amount=line.amount` substring check would miss.
    assert "convert_amount" not in src


# ── Phase C: currency as a single base SSOT, balance core typed, ratchet ──────
# Only a `sum(...)` whose arguments reference a raw `line.amount` (currency-blind
# addition). Does NOT match plain list/generator comprehensions used for
# serialization, nor `Money.sum(_line_base_amount(...))` (the `(` of the inner call
# bounds the `[^)]*` before any `line.amount`).
_CURRENCY_BLIND_LINE_SUM = re.compile(r"\bsum\([^)]*\bline\.amount\b")


@ac_proof(
    proof_id="test_journal_line_currency_single_ssot",
    ac_ids=["AC-audit.38.1"],
    ci_tier="pr_ci",
)
def test_AC12_38_1_journal_line_currency_resolves_to_base_ssot():
    """AC-audit.38.1: JournalLine currency resolves to the single `settings.base_currency`
    SSOT — accessor fallback + column default — with no hard-coded base literal."""
    src = _read("apps/backend/src/models/journal.py")
    assert "from src.config import settings" in src
    assert "else settings.base_currency" in src
    assert "default=lambda: settings.base_currency" in src
    assert 'else "SGD"' not in src
    assert 'default="SGD"' not in src


@ac_proof(
    proof_id="test_balance_core_typed_money",
    ac_ids=["AC-audit.38.2"],
    ci_tier="pr_ci",
)
def test_AC12_38_2_balance_core_sums_money():
    """AC-audit.38.2: the journal balance core computes via `line.money` + `Money.sum`
    (currency-checked), not a raw currency-blind Decimal sum."""
    src = _read("apps/backend/src/ledger/base/validators.py")
    assert "def _line_base_amount(line: JournalLine) -> Money" in src
    assert "line.money" in src
    assert "Money.sum(" in src


@ac_proof(
    proof_id="test_annualized_income_line_money",
    ac_ids=["AC-audit.38.3"],
    ci_tier="pr_ci",
)
def test_AC12_38_3_annualized_income_reads_line_money():
    """AC-audit.38.3: annualized income reads `line.money` (single SSOT) instead of the
    per-site `line.currency or account.currency or target` fallback."""
    src = _read("apps/backend/src/advisor/extension/annualized_income.py")
    assert "line.money" in src
    assert "or account.currency or" not in src


@ac_proof(
    proof_id="test_no_currency_blind_line_amount_sum",
    ac_ids=["AC-audit.38.4"],
    ci_tier="pr_ci",
)
def test_AC12_38_4_no_currency_blind_line_amount_sum():
    """AC-audit.38.4 (ratchet): no service/ledger code performs a raw `sum(...)` over
    `line.amount` — currency-blind cross-currency addition must go through
    `Money.sum`. Scoped to `sum(...)` argument contexts only, so list/generator
    comprehensions built for serialization, manual fast-path rate multiplies, and
    single-value `line.amount` reads stay raw (and `Money.sum(_line_base_amount(...))`
    is not flagged)."""
    offenders: dict[str, list[str]] = {}
    for folder in ("apps/backend/src/services", "apps/backend/src/ledger"):
        for path in sorted((REPO / folder).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if _CURRENCY_BLIND_LINE_SUM.search(text):
                offenders[str(path.relative_to(REPO))] = (
                    _CURRENCY_BLIND_LINE_SUM.findall(text)
                )
    assert not offenders, (
        f"currency-blind journal-line sums must use Money.sum: {offenders}"
    )
