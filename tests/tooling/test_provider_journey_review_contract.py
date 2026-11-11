from __future__ import annotations; from dataclasses import dataclass; from datetime import date; from decimal import Decimal; import pytest; from common.testing import provider_review; from common.testing.provider_review import FixtureDisposition, FixtureEnvelope, approve_statement_with_fixture_review
@dataclass
class _Response:
    status_code: int; payload: dict
    @property
    def text(self) -> str: return str(self.payload)
    def json(self) -> dict: return self.payload
class _Client:
    def __init__(self) -> None: self.calls: list[tuple[str, str, dict | None]] = []; self.approvals = 0
    async def get(self, path: str) -> _Response:
        self.calls.append(('GET', path, None))
        if path == REVIEW_URL: return _Response(200, {'preclassification_in_progress': False})
        if path == '/api/reconciliation/unmatched?statement_id=statement-1': return _Response(200, {'items': [{'id': 'txn-1', 'description': 'Synthetic refund', 'direction': 'IN', 'currency': 'SGD'}], 'total': 1})
        raise AssertionError(f'Unexpected request: {path}')
    async def post(self, path: str, json: dict | None=None) -> _Response:
        self.calls.append(('POST', path, json))
        if path.endswith('/review/approve'):
            self.approvals += 1
            if self.approvals == 1: return _Response(409, {'detail': 'Economic review required: intent_missing'})
            return _Response(200, {'journal_entries_created': 0, 'status': 'approved'})
        if path == '/api/accounts': return _Response(201, {'id': 'expense-account'})
        if path.endswith('/reviewed-disposition'): return _Response(200, {'id': 'entry-1'})
        raise AssertionError(f'Unexpected request: {path}')
async def test_AC_testing_product_gates_13_retries_after_reviewed_dispositions() -> None:
    'AC-testing.product-gates.13'; client = _Client(); outcome = await approve_statement_with_fixture_review(client, api_url=lambda path: f'/api{path}', statement_id='statement-1', transactions=[{'id': 'txn-1', 'description': 'Synthetic refund', 'direction': 'IN', 'currency': 'SGD'}], dispositions={'Synthetic refund': FixtureDisposition(intent='expense_refund', account_type='EXPENSE', category='REFUND', rationale='The generated fixture explicitly identifies an expense refund.')}); assert outcome == {'status': 'approved', 'journal_entries_created': 0, 'reviewed_dispositions': 1}; reviewed_call = next((call for call in client.calls if call[1].endswith('/reviewed-disposition'))); assert reviewed_call[2] == {'intent': 'expense_refund', 'counter_account_id': 'expense-account', 'category': 'REFUND', 'rationale': 'The generated fixture explicitly identifies an expense refund.'}; assert ('GET', '/api/reconciliation/unmatched?statement_id=statement-1', None) in client.calls; assert client.approvals == 2; _m1_client = _Client(); _m1_client.approvals = 1; _m1_outcome = await approve_statement_with_fixture_review(_m1_client, api_url=lambda path: f'/api{path}', statement_id='statement-1', transactions=[], dispositions={}); assert _m1_outcome == {'status': 'approved', 'journal_entries_created': 0, 'reviewed_dispositions': 0}; assert [(_m1_call[0], _m1_call[1]) for _m1_call in _m1_client.calls] == [('GET', REVIEW_URL), ('POST', APPROVE_URL)]
    with pytest.raises(AssertionError, match='no explicit disposition'): await approve_statement_with_fixture_review(_Client(), api_url=lambda path: f'/api{path}', statement_id='statement-1', transactions=[], dispositions={})
    'AC-testing.e2e-poll-reconnect.2'; 'AC-testing.e2e-poll-reconnect.2'; _m3_client = _ReviewFlowClient(get_allowed=True); _m3_result = await _run_review_flow(_m3_client); assert [_m3_call[1] for _m3_call in _m3_client.calls if _m3_call[0] == 'GET'] == [REVIEW_URL, REVIEW_URL, UNMATCHED_URL]; assert _m3_result['reviewed_dispositions'] == 1
async def test_provider_review_adapter_rejects_non_review_failures() -> None:
    class NonReviewClient(_Client):
        async def post(self, path: str, json: dict | None=None) -> _Response: return _Response(503, {'detail': 'provider unavailable'})
    with pytest.raises(AssertionError, match='outside the review boundary'): await approve_statement_with_fixture_review(NonReviewClient(), api_url=lambda path: f'/api{path}', statement_id='statement-1', transactions=[], dispositions={})
async def test_provider_review_adapter_fails_closed_when_scoped_queue_is_unavailable() -> None:
    class QueueFailureClient(_Client):
        async def get(self, path: str) -> _Response: return _Response(200, {}) if path == REVIEW_URL else _Response(503, {'detail': 'queue unavailable'})
    with pytest.raises(AssertionError, match='statement-scoped unmatched lookup failed'): await approve_statement_with_fixture_review(QueueFailureClient(), api_url=lambda path: f'/api{path}', statement_id='statement-1', transactions=[], dispositions={})
async def test_provider_review_adapter_reuses_account_and_omits_empty_category() -> None:
    class TwoTransactionClient(_Client):
        async def get(self, path: str) -> _Response: self.calls.append(('GET', path, None)); return _Response(200, {'items': [{'id': 'txn-1', 'description': 'Synthetic refund', 'currency': 'SGD'}, {'id': 'txn-2', 'description': 'Synthetic rent', 'currency': 'SGD'}], 'total': 2})
    client = TwoTransactionClient(); outcome = await approve_statement_with_fixture_review(client, api_url=lambda path: f'/api{path}', statement_id='statement-1', transactions=[], dispositions={'Synthetic refund': FixtureDisposition('expense_refund', 'EXPENSE', 'Fixture-owned refund.', 'REFUND'), 'Synthetic rent': FixtureDisposition('expense', 'EXPENSE', 'Fixture-owned rent.')}); assert outcome['reviewed_dispositions'] == 2; assert sum((path == '/api/accounts' for _method, path, _body in client.calls)) == 1; reviewed_payloads = [body for _method, path, body in client.calls if path.endswith('/reviewed-disposition')]; assert reviewed_payloads[1] == {'intent': 'expense', 'counter_account_id': 'expense-account', 'rationale': 'Fixture-owned rent.'}
async def test_provider_review_confirms_only_fixture_owned_envelope() -> None:
    'AC-testing.product-gates.13'; from common.testing.provider_review import FixtureEnvelope; from datetime import date; from decimal import Decimal
    class EnvelopeClient(_Client):
        async def post(self, path, json=None):
            if path.endswith('/review/approve') and (not any((c[1].endswith('/review/envelope') for c in self.calls))): self.calls.append(('POST', path, json)); return _Response(400, {'detail': 'Current source requires explicit human confirmation before posting'})
            if path.endswith('/review/envelope'): self.calls.append(('POST', path, json)); return _Response(200, {'id': 'envelope-1'})
            return await super().post(path, json)
        async def get(self, path):
            if path.endswith('/review'): return _Response(200, {'source_result_digest': 'a' * 64, 'account_id': 'bank-1'})
            return await super().get(path)
    fixture = FixtureEnvelope('SGD', date(2026, 1, 1), date(2026, 1, 31), Decimal('100'), Decimal('110'), 'Generated original facts'); client = EnvelopeClient(); result = await approve_statement_with_fixture_review(client, api_url=lambda p: '/api' + p, statement_id='statement-1', transactions=[], dispositions={'Synthetic refund': FixtureDisposition('expense_refund', 'EXPENSE', 'Fixture refund')}, envelope=fixture); command = next((c[2] for c in client.calls if c[1].endswith('/review/envelope'))); assert command == {'source_result_digest': 'a' * 64, 'account_id': 'bank-1', 'currency': 'SGD', 'period_start': '2026-01-01', 'period_end': '2026-01-31', 'opening_balance': '100', 'closing_balance': '110', 'rationale': 'Generated original facts'}; assert result['reviewed_dispositions'] == 1
    with pytest.raises(AssertionError, match='fixture envelope'): await approve_statement_with_fixture_review(EnvelopeClient(), api_url=lambda p: '/api' + p, statement_id='statement-1', transactions=[], dispositions={})
@pytest.mark.parametrize('digest,confirmation_status', [(None, 200), ('b' * 64, 400), ('b' * 64, 200)])
async def test_fixture_source_confirmation_fails_closed(digest, confirmation_status) -> None:
    'AC-testing.product-gates.13'; from datetime import date; from decimal import Decimal; from common.testing.provider_review import FixtureEnvelope, _confirm_fixture_envelope
    class SourceClient(_Client):
        async def get(self, path): return _Response(200, {'source_result_digest': digest, 'account_id': None})
        async def post(self, path, json=None):
            self.calls.append(('POST', path, json))
            if path == '/api/accounts': return _Response(201, {'id': 'new-custody'})
            return _Response(confirmation_status, {'id': 'envelope', 'detail': 'source mismatch'})
    client = SourceClient(); envelope = FixtureEnvelope('SGD', date(2026, 1, 1), date(2026, 1, 31), Decimal('0'), Decimal('0'), 'Generated source')
    if digest is None or confirmation_status != 200:
        with pytest.raises(AssertionError, match='exact current extraction digest|confirmation failed'): await _confirm_fixture_envelope(client, lambda p: '/api' + p, 'statement-1', envelope)
        assert digest is not None or client.calls == []
    else: await _confirm_fixture_envelope(client, lambda p: '/api' + p, 'statement-1', envelope); assert client.calls[0][2]['type'] == 'ASSET'; assert client.calls[1][2]['account_id'] == 'new-custody'
REVIEW_URL = '/api/statements/statement-1/review'; APPROVE_URL = REVIEW_URL + '/approve'; LIMIT_SECONDS = 240.0; UNMATCHED_URL = '/api/reconciliation/unmatched?statement_id=statement-1'
def _review_flow_lookup(path: str) -> _Response:
    if path == REVIEW_URL: return _Response(200, {'source_result_digest': 'a' * 64, 'account_id': 'bank-1'})
    if path == UNMATCHED_URL: return _Response(200, {'items': [{'id': 'txn-1', 'description': 'Synthetic refund', 'direction': 'IN', 'currency': 'SGD'}], 'total': 1})
    raise AssertionError(f'Unexpected request: {path}')
class _ReviewFlowClient(_Client):
    def __init__(self, *, get_allowed: bool) -> None: super().__init__(); self.get_allowed = get_allowed
    async def get(self, path: str) -> _Response:
        if not self.get_allowed: raise AssertionError(f'client.get must not be called: {path}')
        self.calls.append(('GET', path, None)); return _review_flow_lookup(path)
    async def post(self, path: str, json: dict | None=None) -> _Response:
        if path.endswith('/review/approve') and (not any((call[1].endswith('/review/envelope') for call in self.calls))): self.calls.append(('POST', path, json)); return _Response(400, {'detail': 'Current source requires explicit human confirmation before posting'})
        if path.endswith('/review/envelope'): self.calls.append(('POST', path, json)); return _Response(200, {'id': 'envelope-1'})
        return await super().post(path, json)
async def _run_review_flow(client: _Client, **kwargs) -> dict: return await approve_statement_with_fixture_review(client, api_url=lambda path: f'/api{path}', statement_id='statement-1', transactions=[], dispositions={'Synthetic refund': FixtureDisposition('expense_refund', 'EXPENSE', 'Fixture refund')}, envelope=FixtureEnvelope('SGD', date(2026, 1, 1), date(2026, 1, 31), Decimal('100'), Decimal('110'), 'Generated original facts'), **kwargs)
async def test_AC_testing_e2e_poll_reconnect_2_both_lookups_of_the_review_helper_use_the_injected_getter() -> None:
    'AC-testing.e2e-poll-reconnect.2'; client = _ReviewFlowClient(get_allowed=False); urls: list[str] = []
    async def getter(url: str) -> _Response: urls.append(url); return _review_flow_lookup(url)
    result = await _run_review_flow(client, get=getter); assert urls == [REVIEW_URL, REVIEW_URL, UNMATCHED_URL]; assert result['reviewed_dispositions'] == 1; assert [call for call in client.calls if call[0] == 'GET'] == []; assert client.approvals == 2
class _ClassifyingClient(_Client):
    def __init__(self, *flags: bool, get_allowed: bool = True) -> None: super().__init__(); self.flags = list(flags); self.get_allowed = get_allowed; self.approvals = 1
    async def lookup(self, path: str) -> _Response: self.calls.append(('GET', path, None)); return _Response(200, {'preclassification_in_progress': self.flags.pop(0) if len(self.flags) > 1 else self.flags[0]})
    async def get(self, path: str) -> _Response: assert self.get_allowed, f'client.get must not be called: {path}'; return await self.lookup(path)
@pytest.fixture
def naps(monkeypatch) -> list[float]:
    now = [0.0]; slept: list[float] = []
    async def fake_sleep(seconds: float) -> None: assert now[0] < LIMIT_SECONDS, 'the wait ran past its limit'; slept.append(seconds); now[0] += seconds
    monkeypatch.setattr(provider_review, 'sleep', fake_sleep, raising=False); monkeypatch.setattr(provider_review, 'monotonic', lambda: now[0], raising=False); return slept
async def test_AC_testing_e2e_classification_wait_1_no_approval_is_posted_while_the_classification_pass_runs(naps) -> None:
    'AC-testing.e2e-classification-wait.1'; client = _ClassifyingClient(True, True, False); result = await _run_review_flow(client); assert [(call[0], call[1]) for call in client.calls] == [('GET', REVIEW_URL)] * 3 + [('POST', APPROVE_URL)]; assert naps == [1.0, 1.0]; assert result['reviewed_dispositions'] == 0
async def test_AC_testing_e2e_classification_wait_1_the_wait_ends_at_the_limit_and_the_approval_still_runs(naps) -> None:
    'AC-testing.e2e-classification-wait.1'; client = _ClassifyingClient(True); result = await _run_review_flow(client); assert sum(naps) == LIMIT_SECONDS; assert set(naps) == {1.0}; assert [call[0] for call in client.calls].count('POST') == 1; assert client.calls[-1][:2] == ('POST', APPROVE_URL); assert result['status'] == 'approved'
async def test_AC_testing_e2e_classification_wait_1_a_failed_review_lookup_raises_and_posts_nothing(naps) -> None:
    'AC-testing.e2e-classification-wait.1'
    class FailedLookupClient(_Client):
        async def get(self, path: str) -> _Response: self.calls.append(('GET', path, None)); return _Response(500, {'detail': 'review unavailable'})
    client = FailedLookupClient()
    with pytest.raises(AssertionError, match='classification state lookup failed with HTTP 500'): await _run_review_flow(client)
    assert client.calls == [('GET', REVIEW_URL, None)]
async def test_AC_testing_e2e_classification_wait_1_the_wait_uses_the_injected_getter(naps) -> None:
    'AC-testing.e2e-classification-wait.1'; client = _ClassifyingClient(True, False, get_allowed=False); await _run_review_flow(client, get=client.lookup); assert [(call[0], call[1]) for call in client.calls] == [('GET', REVIEW_URL)] * 2 + [('POST', APPROVE_URL)]
