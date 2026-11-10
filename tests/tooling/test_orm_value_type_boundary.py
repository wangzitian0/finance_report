'EPIC-012'; import re; from pathlib import Path; from common.testing.ac_proof import ac_proof; REPO = Path(__file__).resolve().parents[2]; MIGRATED_MANAGED_POSITION_FILES = ['apps/backend/src/portfolio/extension/holdings.py', 'apps/backend/src/portfolio/extension/accounting.py', 'apps/backend/src/pricing/extension/valuation.py', 'apps/backend/src/portfolio/extension/positions.py', 'apps/backend/src/portfolio/extension/performance_report.py', 'apps/backend/src/reporting/extension/portfolio_market.py']; _RAW_MANAGED_POSITION_MONEY_READ = re.compile('position\\.(?:cost_basis|unrealized_pnl|realized_pnl)(?!_money|_method)(?!\\s*=(?!=))'); _read = lambda path: (REPO / path).read_text(encoding='utf-8')
@ac_proof(proof_id='test_managed_position_money_accessors', ac_ids=['AC-audit.35.1'], ci_tier='pr_ci')
def test_AC12_35_1_managed_position_exposes_typed_accessors():
    'AC-audit.35.1'; src = _read('apps/backend/src/extraction/orm/layer3.py'); assert 'import src.audit as audit' in src; assert 'from src.audit.quantity import Quantity' in src
    for accessor in ('def cost_basis_money(self) -> audit.Money', 'def unrealized_pnl_money(self) -> audit.Money', 'def realized_pnl_money(self) -> audit.Money', 'def quantity_qty(self) -> Quantity'): assert accessor in src, f'ManagedPosition must expose `{accessor}`'
@ac_proof(proof_id='test_investment_accounting_reads_typed', ac_ids=['AC-audit.35.2'], ci_tier='pr_ci')
def test_AC12_35_2_investment_accounting_reads_position_via_accessors(): 'AC-audit.35.2'; src = _read('apps/backend/src/portfolio/extension/accounting.py'); assert 'position.cost_basis_money' in src; assert 'position.realized_pnl_money' in src; assert 'position.quantity_qty' in src; assert 'to_money(position.cost_basis' not in src; assert 'position.realized_pnl or Decimal' not in src; assert 'Quantity(position.quantity,' not in src
@ac_proof(proof_id='test_portfolio_holdings_money_native', ac_ids=['AC-audit.35.3'], ci_tier='pr_ci')
def test_AC12_35_3_portfolio_holdings_value_flows_as_money(): 'AC-audit.35.3'; fx = _read('apps/backend/src/pricing/extension/fx.py'); assert 'async def convert_money(' in fx, "pricing's fx module must expose a Money-native convert helper"; src = _read('apps/backend/src/portfolio/extension/holdings.py'); assert 'convert_money(' in src; assert 'position.cost_basis_money' in src; assert 'position.quantity_qty' in src; assert 'UnitPrice(latest_price' in src; market = _read('apps/backend/src/reporting/extension/portfolio_market.py'); assert 'from src.pricing import' in market; assert 'await convert_money(' in market; assert 'position.cost_basis_money' in market; assert 'position.quantity_qty' in market
@ac_proof(proof_id='test_managed_position_raw_reads_forbidden', ac_ids=['AC-audit.35.4'], ci_tier='pr_ci')
def test_AC12_35_4_no_raw_managed_position_money_reads_in_migrated_files(): 'AC-audit.35.4'; offenders = {path: _RAW_MANAGED_POSITION_MONEY_READ.findall(_read(path)) for path in MIGRATED_MANAGED_POSITION_FILES if _RAW_MANAGED_POSITION_MONEY_READ.search(_read(path))}; assert not offenders, f'raw ManagedPosition money reads must use accessors: {offenders}'
@ac_proof(proof_id='test_journal_line_money_accessor', ac_ids=['AC-audit.37.1'], ci_tier='pr_ci')
def test_AC12_37_1_journal_line_exposes_money_accessor(): 'AC-audit.37.1'; src = _read('apps/backend/src/ledger/orm/journal.py'); assert re.search('from src\\.audit\\.money import [^\\n]*\\bMoney\\b', src); assert 'def money(self) -> Money' in src
@ac_proof(proof_id='test_reconciliation_config_sums_money', ac_ids=['AC-audit.37.2'], ci_tier='pr_ci')
def test_AC12_37_2_reconciliation_config_sums_lines_as_money(): 'AC-audit.37.2'; src = _read('apps/backend/src/reconciliation/extension/entry_reads.py'); assert 'line.money' in src; assert 'Money.sum(' in src; assert 'sum(line.amount' not in src
@ac_proof(proof_id='test_income_statement_converts_money_native', ac_ids=['AC-audit.37.3'], ci_tier='pr_ci')
def test_AC12_37_3_income_statement_fx_is_money_native(): 'AC-audit.37.3'; src = _read('apps/backend/src/reporting/extension/income_statement.py'); assert 'convert_money(' in src; assert 'line.money' in src; assert 'convert_amount' not in src
_CURRENCY_BLIND_LINE_SUM = re.compile('\\bsum\\([^)]*\\bline\\.amount\\b')
@ac_proof(proof_id='test_journal_line_currency_single_ssot', ac_ids=['AC-audit.38.1'], ci_tier='pr_ci')
def test_AC12_38_1_journal_line_currency_resolves_to_base_ssot(): 'AC-audit.38.1'; src = _read('apps/backend/src/ledger/orm/journal.py'); assert 'from src.config import settings' in src; assert 'else settings.base_currency' in src; assert 'default=lambda: settings.base_currency' in src; assert 'else "SGD"' not in src; assert 'default="SGD"' not in src
@ac_proof(proof_id='test_balance_core_typed_money', ac_ids=['AC-audit.38.2'], ci_tier='pr_ci')
def test_AC12_38_2_balance_core_sums_money(): 'AC-audit.38.2'; src = _read('apps/backend/src/ledger/base/validators.py'); assert 'def _line_base_amount(line: JournalLine, *, base_currency: str | None = None) -> Money' in src; assert 'Money(line.amount, line.currency or base.code)' in src; assert 'Money.sum(' in src
@ac_proof(proof_id='test_annualized_income_line_money', ac_ids=['AC-audit.38.3'], ci_tier='pr_ci')
def test_AC12_38_3_annualized_income_reads_line_money(): 'AC-audit.38.3'; src = _read('apps/backend/src/reporting/extension/annualized_income.py'); assert 'line.money' in src; assert 'or account.currency or' not in src
@ac_proof(proof_id='test_no_currency_blind_line_amount_sum', ac_ids=['AC-audit.38.4'], ci_tier='pr_ci')
def test_AC12_38_4_no_currency_blind_line_amount_sum():
    'AC-audit.38.4'; offenders: dict[str, list[str]] = {}
    for folder in ('apps/backend/src/services', 'apps/backend/src/ledger'):
        for path in sorted((REPO / folder).rglob('*.py')):
            text = path.read_text(encoding='utf-8')
            if _CURRENCY_BLIND_LINE_SUM.search(text): offenders[str(path.relative_to(REPO))] = _CURRENCY_BLIND_LINE_SUM.findall(text)
    assert not offenders, f'currency-blind journal-line sums must use Money.sum: {offenders}'
