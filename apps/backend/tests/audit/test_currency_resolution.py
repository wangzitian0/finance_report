'EPIC-012'; from __future__ import annotations; from datetime import date; from types import SimpleNamespace; from uuid import uuid4; import pytest; from common.testing.ac_proof import ac_proof; from src.audit.money import InvalidCurrencyError; from src.extraction.extension.currency_resolution import UNRESOLVED_PLACEHOLDER, CurrencyUnresolvedError, resolve_ingest_currency, resolve_transaction_currency; from src.extraction.extension.review_queue import create_entry_from_txn; pytestmark = pytest.mark.no_db
@ac_proof(proof_id='test_ingest_attaches_explicit_currency', ac_ids=['AC-audit.40.1'], ci_tier='pr_ci', issue='#1341')
@pytest.mark.parametrize(('candidates', 'expected'), [(('USD',), 'USD'), (('usd ',), 'USD'), ((None, 'SGD'), 'SGD'), (('ZZZ', 'EUR'), 'EUR')])
def test_AC12_40_1_attaches_explicit_currency(candidates, expected): 'AC-audit.40.1 AC12.40.1'; resolved = resolve_ingest_currency(*candidates); assert resolved.code == expected; assert resolved.unresolved is False
@ac_proof(proof_id='test_ingest_flags_unresolved', ac_ids=['AC-audit.40.2'], ci_tier='pr_ci', issue='#1341')
@pytest.mark.parametrize('candidates', [(), (None,), (None, None), ('ZZZ',), ('US', '')])
def test_AC12_40_2_flags_unresolved_instead_of_silent_default(candidates): 'AC-audit.40.2 AC12.40.2'; resolved = resolve_ingest_currency(*candidates); assert resolved.unresolved is True; assert resolved.code == UNRESOLVED_PLACEHOLDER; assert resolved.code != 'SGD'
@ac_proof(proof_id='test_unresolved_placeholder_is_not_valid', ac_ids=['AC-audit.40.2'], ci_tier='pr_ci', issue='#1341')
def test_AC12_40_2_placeholder_cannot_masquerade_as_real_currency():
    'AC-audit.40.2 AC12.40.2'; from src.audit.money import Currency
    with pytest.raises(InvalidCurrencyError): Currency(UNRESOLVED_PLACEHOLDER)
@ac_proof(proof_id='test_promotion_gate_blocks_unresolved', ac_ids=['AC-audit.40.4'], ci_tier='pr_ci', issue='#1341')
async def test_AC12_40_4_promotion_gate_blocks_unresolved_currency():
    'AC-audit.40.4 AC12.40.4'; user_id = uuid4(); txn = SimpleNamespace(id=uuid4(), user_id=user_id, currency_unresolved=True, currency=UNRESOLVED_PLACEHOLDER, txn_date=date(2024, 1, 1))
    with pytest.raises(CurrencyUnresolvedError): await create_entry_from_txn(None, txn, user_id=user_id)
@ac_proof(proof_id='test_promotion_gate_allows_resolved', ac_ids=['AC-audit.40.4'], ci_tier='pr_ci', issue='#1341')
async def test_AC12_40_4_promotion_gate_passes_guard_when_resolved():
    'AC-audit.40.4 AC12.40.4'; user_id = uuid4(); txn = SimpleNamespace(id=uuid4(), user_id=user_id, currency_unresolved=False, currency='USD', txn_date=date(2024, 1, 1), source_documents=[])
    with pytest.raises(Exception) as exc_info: await create_entry_from_txn(None, txn, user_id=user_id)
    assert not isinstance(exc_info.value, CurrencyUnresolvedError)
class _FakeResult:
    def __init__(self, obj): self._obj = obj
    def scalar_one_or_none(self): return self._obj
class _FakeSession:
    def __init__(self, txn): self._txn = txn; self.flushed = False
    async def execute(self, _stmt): return _FakeResult(self._txn)
    async def flush(self): self.flushed = True
@ac_proof(proof_id='test_reviewer_resolves_currency_audited', ac_ids=['AC-audit.40.3'], ci_tier='pr_ci', issue='#1341')
async def test_AC12_40_3_reviewer_resolves_currency_with_audit(): 'AC-audit.40.3 AC12.40.3'; user_id = uuid4(); txn = SimpleNamespace(id=uuid4(), user_id=user_id, currency=UNRESOLVED_PLACEHOLDER, currency_unresolved=True, currency_resolved_by=None, currency_resolved_at=None); session = _FakeSession(txn); result = await resolve_transaction_currency(session, txn.id, user_id=user_id, currency='usd '); assert result.currency == 'USD'; assert result.currency_unresolved is False; assert result.currency_resolved_by == user_id; assert result.currency_resolved_at is not None; assert session.flushed is True
@ac_proof(proof_id='test_reviewer_rejects_bad_currency', ac_ids=['AC-audit.40.3'], ci_tier='pr_ci', issue='#1341')
async def test_AC12_40_3_reviewer_currency_must_be_iso_4217():
    'AC-audit.40.3 AC12.40.3'; user_id = uuid4(); txn = SimpleNamespace(id=uuid4(), user_id=user_id, currency=UNRESOLVED_PLACEHOLDER, currency_unresolved=True, currency_resolved_by=None, currency_resolved_at=None); session = _FakeSession(txn)
    with pytest.raises(InvalidCurrencyError): await resolve_transaction_currency(session, txn.id, user_id=user_id, currency='ZZZ')
    assert txn.currency_unresolved is True; assert txn.currency_resolved_by is None; assert txn.currency_resolved_at is None
