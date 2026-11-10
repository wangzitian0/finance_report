'EPIC-012'; from pathlib import Path; from common.testing.ac_proof import ac_proof; REPO = Path(__file__).resolve().parents[2]
def _read(path: Path) -> str:
    target = REPO / path
    if target.is_dir(): return '\n# <<< file-boundary >>>\n'.join((p.read_text(encoding='utf-8') for p in sorted(target.rglob('*.py'))))
    return target.read_text(encoding='utf-8')
@ac_proof(proof_id='test_unit_price_investment_adoption', ac_ids=['AC-audit.32.3'], ci_tier='pr_ci')
def test_AC12_32_3_investment_accounting_uses_unit_price(): 'AC-audit.32.3'; src = _read(Path('apps/backend/src/portfolio/extension/accounting.py')); assert 'from src.audit.unit_price import UnitPrice' in src; assert 'buy_price * trade_quantity' in src; assert 'sell_price * trade_quantity' in src; assert 'UnitPrice.from_total(' in src; assert '_quantized_unit_rate' not in src; assert 'UNIT_RATE_QUANTUM' not in src; assert 'trade_quantity.value * unit_price' not in src
@ac_proof(proof_id='test_unit_price_market_data_adoption', ac_ids=['AC-audit.32.3'], ci_tier='pr_ci')
def test_AC12_32_3_market_data_price_quantum_is_single_sourced(): 'AC-audit.32.3'; src = _read(Path('apps/backend/src/pricing/extension/market_data')); assert 'from src.audit import UNIT_PRICE_QUANTUM' in src; assert '_PRICE_QUANT = UNIT_PRICE_QUANTUM' in src
