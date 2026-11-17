'AC-testing.benchmarks.11'; from __future__ import annotations; from typing import Any; import pytest; from tests.benchmarks.run_financial_scenario_benchmark import ScenarioBenchmarkRunner
class _Resp:
    def __init__(self, status_code: int, body: Any=None, text: str='') -> None: self.status_code = status_code; self._body = body if body is not None else {}; self.text = text
    def json(self) -> Any: return self._body
class _ApprovalClient:
    def __init__(self, statement: dict[str, Any], review_status: int=200, envelope_status: int=200, needs_confirmation: bool=True, statement_statuses: list[int] | None=None) -> None: self.statement = statement; self.review_status = review_status; self.envelope_status = envelope_status; self.needs_confirmation = needs_confirmation; self.statement_statuses = list(statement_statuses or []); self.posts: list[tuple[str, dict[str, Any]]] = []; self.confirmed = False
    def get(self, url: str) -> _Resp:
        if url.endswith('/review'): return _Resp(self.review_status, {'source_result_digest': 'digest-1', 'account_id': 'acc-1'}, 'review text')
        if url.endswith('/runs'): return _Resp(200, {'items': []}, 'runs text')
        status = self.statement_statuses.pop(0) if self.statement_statuses else 200; return _Resp(status, self.statement, 'statement text')
    def post(self, url: str, json: dict[str, Any]) -> _Resp:
        self.posts.append((url, json))
        if url.endswith('/review-envelopes'): self.confirmed = self.envelope_status in (200, 201); return _Resp(self.envelope_status, {}, 'envelope text')
        if self.confirmed or not self.needs_confirmation: return _Resp(200, {'status': 'approved'})
        return _Resp(400, {}, 'Statement requires explicit human confirmation before posting')
def _statement(**overrides: Any) -> dict[str, Any]: base = {'period_start': '2026-02-01', 'period_end': '2026-02-28', 'opening_balance': '1000.00', 'closing_balance': '1250.50', 'currency': 'SGD'}; return {**base, **overrides}
_runner = lambda: ScenarioBenchmarkRunner(base_url='http://localhost:1'); _envelope_posts = lambda client: [body for url, body in client.posts if url.endswith('/review-envelopes')]; _approve_posts = lambda client: sum((url.endswith('/approvals') for url, _ in client.posts))
def test_AC_testing_benchmarks_11_the_envelope_states_the_facts_of_the_parsed_statement() -> None:
    client = _ApprovalClient(_statement()); result = _runner().approve_statement(client, 's-1'); assert result == {'status': 'approved'}; assert _envelope_posts(client) == [{'source_result_digest': 'digest-1', 'account_id': 'acc-1', 'currency': 'SGD', 'period_start': '2026-02-01', 'period_end': '2026-02-28', 'opening_balance': '1000.00', 'closing_balance': '1250.50', 'rationale': 'Benchmark automated review envelope confirmation'}]; assert _approve_posts(client) == 2; _m1_client = _ApprovalClient(_statement(opening_balance='0.00', closing_balance=0)); _runner().approve_statement(_m1_client, 's-1'); _m1_envelope = _envelope_posts(_m1_client)[0]; assert _m1_envelope['opening_balance'] == '0.00'; assert _m1_envelope['closing_balance'] == '0'; _m2_client = _ApprovalClient(_statement(period_start=None, closing_balance=None))
    with pytest.raises(RuntimeError) as _m2_error: _runner().approve_statement(_m2_client, 's-1')
    assert 'period_start' in str(_m2_error.value); assert 'closing_balance' in str(_m2_error.value); _m3_client = _ApprovalClient(_statement(), review_status=500)
    with pytest.raises(RuntimeError, match='Review lookup failed .* 500 review text'): _runner().approve_statement(_m3_client, 's-1')
    assert _envelope_posts(_m3_client) == []; _m4_client = _ApprovalClient(_statement(), statement_statuses=[200, 500])
    with pytest.raises(RuntimeError, match='Failed to fetch statement s-1: 500 statement text'): _runner().approve_statement(_m4_client, 's-1')
    assert _envelope_posts(_m4_client) == []; _m5_client = _ApprovalClient(_statement(), envelope_status=422)
    with pytest.raises(RuntimeError, match='Review envelope confirmation failed .* 422 envelope text'): _runner().approve_statement(_m5_client, 's-1')
    assert _approve_posts(_m5_client) == 1; _m6_client = _ApprovalClient(_statement(), needs_confirmation=False); _m6_result = _runner().approve_statement(_m6_client, 's-1'); assert _m6_result == {'status': 'approved'}; assert _envelope_posts(_m6_client) == []; assert _approve_posts(_m6_client) == 1
@pytest.mark.parametrize('key', ['period_start', 'period_end', 'opening_balance', 'closing_balance', 'currency'])
@pytest.mark.parametrize('empty', [None, ''], ids=['none', 'empty'])
def test_AC_testing_benchmarks_11_a_missing_statement_fact_is_never_replaced_by_a_default(key: str, empty: object) -> None:
    client = _ApprovalClient(_statement(**{key: empty}))
    with pytest.raises(RuntimeError, match=f'has no .*{key}'): _runner().approve_statement(client, 's-1')
    assert _envelope_posts(client) == []
