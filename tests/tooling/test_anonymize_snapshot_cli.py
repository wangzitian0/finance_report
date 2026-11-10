'AC-runtime.snapshot-anonymizer.1'; from __future__ import annotations; import pytest
def test_check_only_validates_full_classification(capsys) -> None:
    'AC-runtime.snapshot-anonymizer.1'; from common.runtime.dev.anonymize_snapshot import main; assert main(['--check-only']) == 0; capsys.readouterr(); capsys.readouterr(); import common.runtime.dev.anonymize_snapshot as cli; assert not hasattr(cli, '_get_schema_revision'); assert not hasattr(cli, '_get_anonymizer_sha')
    with pytest.raises(SystemExit) as _m3_excinfo: cli.main(['--check-only', '--emit-audit-proof', '/tmp/proof.json'])
    assert _m3_excinfo.value.code == 2; assert '--emit-audit-proof' in capsys.readouterr().err
def test_transform_requires_database_url() -> None:
    from common.runtime.dev.anonymize_snapshot import main
    with pytest.raises(SystemExit) as excinfo: main([])
    assert excinfo.value.code == 2; from common.runtime.dev.anonymize_snapshot import main
    with pytest.raises(SystemExit) as _m1_excinfo: main(['--database-url', 'postgresql+psycopg2://x:y@localhost/scratch'])
    assert _m1_excinfo.value.code == 2; from common.runtime.dev.anonymize_snapshot import _normalize_url; assert _normalize_url('postgresql+asyncpg://u:p@host:5432/db') == 'postgresql+psycopg2://u:p@host:5432/db'; assert _normalize_url('postgresql+psycopg2://u:p@host:5432/db') == 'postgresql+psycopg2://u:p@host:5432/db'
class _FakeEngine:
    def __init__(self): self.conn = object()
    def begin(self):
        from contextlib import contextmanager
        @contextmanager
        def _cm(): yield self.conn
        return _cm()
def test_transform_success_path_reports_counts(monkeypatch, capsys) -> None: import sqlalchemy; import common.runtime.dev.anonymize_snapshot as cli; from src.runtime.extension.snapshot_anonymizer import AnonymizationReport; report = AnonymizationReport(scale_factor=5, tables_updated=3, values_pseudonymized=7); monkeypatch.setattr(sqlalchemy, 'create_engine', lambda url: _FakeEngine()); monkeypatch.setattr(cli, 'anonymize', lambda conn, md, *, secret, scale_factor: report); monkeypatch.setattr(cli, 'scan_for_residuals', lambda conn, md, originals: []); assert cli.main(['--database-url', 'postgresql+asyncpg://u:p@localhost/scratch', '--i-am-on-a-scratch-copy']) == 0; capsys.readouterr()
def test_transform_residuals_fail_closed(monkeypatch) -> None:
    'AC-runtime.snapshot-anonymizer.3'; import sqlalchemy; import common.runtime.dev.anonymize_snapshot as cli; from src.runtime.extension.snapshot_anonymizer import AnonymizationReport, ResidualError; report = AnonymizationReport(scale_factor=5); monkeypatch.setattr(sqlalchemy, 'create_engine', lambda url: _FakeEngine()); monkeypatch.setattr(cli, 'anonymize', lambda conn, md, *, secret, scale_factor: report); monkeypatch.setattr(cli, 'scan_for_residuals', lambda conn, md, originals: ['atomic_transactions.description'])
    with pytest.raises(ResidualError): cli.main(['--database-url', 'postgresql+psycopg2://u:p@localhost/scratch', '--i-am-on-a-scratch-copy'])
