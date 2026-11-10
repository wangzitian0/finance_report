'AC-testing.benchmarks.16'; from __future__ import annotations; from typing import Any; import pytest; from common.testing.benchmarks.run_financial_scenario_benchmark import ScenarioBenchmarkRunner
class _Response:
    status_code = 202
    def json(self) -> dict[str, str]: return {'id': 'statement-1'}
class _Client:
    def __init__(self) -> None: self.posts: list[dict[str, Any]] = []
    def post(self, url: str, *, files: dict[str, Any], data: dict[str, str]) -> _Response: self.posts.append({'url': url, 'files': files, 'data': data}); return _Response()
@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> ScenarioBenchmarkRunner:
    instance = ScenarioBenchmarkRunner(base_url='https://example.test'); created: list[str] = []
    def create_account(client: Any, name: str, type: str, currency: str='SGD') -> dict[str, str]: created.append(name); return {'id': 'account-1'}
    monkeypatch.setattr(instance, 'create_account', create_account); instance.created_accounts = created; return instance
def test_AC_testing_benchmarks_16_a_csv_without_an_institution_gets_the_default_institution(runner: ScenarioBenchmarkRunner) -> None: client = _Client(); assert runner.upload_statement(client, b'a,b\n', 'operations.csv') == 'statement-1'; assert client.posts[0]['url'] == '/api/statements/upload'; assert client.posts[0]['data'] == {'account_id': 'account-1', 'institution': 'Operating'}; assert runner.created_accounts == ['Operating Cash Account']
def test_AC_testing_benchmarks_16_a_csv_keeps_the_institution_that_the_caller_gives(runner: ScenarioBenchmarkRunner) -> None: client = _Client(); runner.upload_statement(client, b'a,b\n', 'dbs.csv', institution='DBS'); assert client.posts[0]['data'] == {'account_id': 'account-1', 'institution': 'DBS'}; assert runner.created_accounts == ['DBS Cash Account']
def test_AC_testing_benchmarks_16_a_pdf_without_an_institution_sends_no_institution(runner: ScenarioBenchmarkRunner) -> None: client = _Client(); runner.upload_statement(client, b'%PDF', 'statement.pdf'); assert client.posts[0]['data'] == {}; assert runner.created_accounts == []
def test_AC_testing_benchmarks_16_repeated_csv_uploads_for_same_institution_reuse_account(runner: ScenarioBenchmarkRunner) -> None: client = _Client(); runner.upload_statement(client, b'a,b\n', 'scb_jan.csv', institution='Standard Chartered Bank'); runner.upload_statement(client, b'a,b\n', 'scb_feb.csv', institution='Standard Chartered Bank'); assert len(client.posts) == 2; assert client.posts[0]['data'] == {'account_id': 'account-1', 'institution': 'Standard Chartered Bank'}; assert client.posts[1]['data'] == {'account_id': 'account-1', 'institution': 'Standard Chartered Bank'}; assert runner.created_accounts == ['Standard Chartered Bank Cash Account']
