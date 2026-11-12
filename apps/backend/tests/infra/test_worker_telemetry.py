from __future__ import annotations; import logging; import threading; from collections import defaultdict; from uuid import uuid4; import pytest; from opentelemetry import metrics as otel_metrics; from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult; import src.observability.worker_telemetry as worker_telemetry; from src.extraction.extension import statement_flow; from src.observability import telemetry_metrics; pytestmark = pytest.mark.no_db; OUTCOME_METRIC = 'finance.statement_parse.outcome'
class CapturingMetricExporter(MetricExporter):
    instances: list[CapturingMetricExporter] = []
    def __init__(self, endpoint: str='', **_kwargs: object) -> None: super().__init__(); self.endpoint = endpoint; self.batches: list[object] = []; self._lock = threading.Lock(); CapturingMetricExporter.instances.append(self)
    def export(self, metrics_data, timeout_millis: float=10000, **_kwargs: object) -> MetricExportResult:
        with self._lock: self.batches.append(metrics_data)
        return MetricExportResult.SUCCESS
    def force_flush(self, timeout_millis: float=10000) -> bool: return True
    def shutdown(self, timeout_millis: float=30000, **_kwargs: object) -> None: return None
    def points(self, name: str) -> list[object]: found = []; [[[[found.extend(metric.data.data_points) if metric.name == name else None for metric in scope_metrics.metrics] for scope_metrics in resource_metrics.scope_metrics] for resource_metrics in batch.resource_metrics] for batch in self.batches]; return found
    def service_names(self) -> set[str]: return {str(rm.resource.attributes.get('service.name')) for batch in self.batches for rm in batch.resource_metrics}
def _fresh_process(monkeypatch) -> None: monkeypatch.setattr(worker_telemetry, '_configured', False); monkeypatch.setattr(otel_metrics._internal, '_METER_PROVIDER', None); monkeypatch.setattr(otel_metrics._internal._METER_PROVIDER_SET_ONCE, '_done', False); telemetry_metrics._clear_metrics_state()
@pytest.fixture
def worker_env(monkeypatch): import opentelemetry.exporter.otlp.proto.http.metric_exporter as metric_exporter_module; CapturingMetricExporter.instances.clear(); monkeypatch.setattr(metric_exporter_module, 'OTLPMetricExporter', CapturingMetricExporter); monkeypatch.setattr(worker_telemetry.settings, 'otel_exporter_otlp_endpoint', 'http://collector:4318'); monkeypatch.setattr(worker_telemetry.settings, 'otel_service_name', 'finance-report-backend'); monkeypatch.setattr(worker_telemetry.settings, 'otel_resource_attributes', 'deployment.environment=development'); _fresh_process(monkeypatch); monkeypatch.setattr(worker_telemetry, 'configure_logging', lambda **_k: None); telemetry_metrics._clear_metrics_state(); yield; telemetry_metrics._clear_metrics_state()
_job = lambda: {'statement_id': str(uuid4()), 'run_id': str(uuid4()), 'filename': 'x.pdf', 'institution': None, 'user_id': str(uuid4()), 'account_id': None, 'file_hash': 'h', 'storage_key': 'k', 'model': None, 'request_id': 'req-1'}
def _install_fake_use_case(monkeypatch, *, fail: bool=False) -> None:
    class FakeUseCase:
        async def execute(self, _job):
            if fail: raise RuntimeError('boom')
            telemetry_metrics.record_statement_parse_outcome(outcome='success')
    monkeypatch.setattr(statement_flow, 'compose_statement_ingestion_use_case', lambda **_k: FakeUseCase())
async def test_flow_run_exports_parse_outcome_point_before_exit(worker_env, monkeypatch) -> None: 'AC-observability.12.4'; monkeypatch.delenv('OTEL_SERVICE_NAME', raising=False); _install_fake_use_case(monkeypatch); await statement_flow.parse_statement_flow.fn(job=_job()); exporter, = CapturingMetricExporter.instances; points = exporter.points(OUTCOME_METRIC); assert {tuple(sorted(p.attributes.items())) for p in points} == {(('outcome', 'success'), ('parser', 'default'))}; assert [p.value for p in sorted(points, key=lambda p: p.time_unix_nano)] == [0, 1]; assert exporter.service_names() == {'finance-report-worker'}
async def test_flow_run_service_name_honours_otel_service_name_env(worker_env, monkeypatch) -> None: monkeypatch.setenv('OTEL_SERVICE_NAME', 'custom-worker'); _install_fake_use_case(monkeypatch); await statement_flow.parse_statement_flow.fn(job=_job()); exporter, = CapturingMetricExporter.instances; assert exporter.service_names() == {'custom-worker'}
async def test_flow_run_flushes_async_failure_counter_when_the_parse_raises(worker_env, monkeypatch) -> None:
    monkeypatch.delenv('OTEL_SERVICE_NAME', raising=False); _install_fake_use_case(monkeypatch, fail=True)
    with pytest.raises(RuntimeError, match='boom'): await statement_flow.parse_statement_flow.fn(job=_job())
    exporter, = CapturingMetricExporter.instances; points = exporter.points('finance.async_parse.failure'); assert {tuple(sorted(p.attributes.items())) for p in points} == {(('error_type', 'RuntimeError'), ('task', 'statement_parse'))}; assert [p.value for p in sorted(points, key=lambda p: p.time_unix_nano)] == [0, 1]
async def test_flow_run_without_endpoint_configures_and_flushes_nothing(worker_env, monkeypatch) -> None: monkeypatch.setattr(worker_telemetry.settings, 'otel_exporter_otlp_endpoint', None); _install_fake_use_case(monkeypatch); await statement_flow.parse_statement_flow.fn(job=_job()); assert CapturingMetricExporter.instances == []; assert telemetry_metrics.is_metrics_export_active() is False
def test_flush_worker_telemetry_flushes_logs_and_traces_providers(monkeypatch) -> None:
    from src.observability import logger as logger_module; calls: list[str] = []
    class Provider:
        def __init__(self, name: str) -> None: self.name = name
        def force_flush(self, _timeout: int) -> None: calls.append(self.name)
    monkeypatch.setattr(logger_module, '_logger_provider', Provider('logs')); monkeypatch.setattr(logger_module, '_tracer_provider', Provider('traces')); monkeypatch.setattr(telemetry_metrics, '_meter_provider', Provider('metrics')); worker_telemetry.flush_worker_telemetry(); assert calls == ['metrics', 'logs', 'traces']
def _prom_increase(exporters, metric: str, **labels: str) -> float:
    series: dict[tuple, list[tuple[int, float]]] = defaultdict(list)
    for exporter in exporters:
        for batch in exporter.batches:
            for resource_metrics in batch.resource_metrics:
                resource = tuple(sorted(((k, str(v)) for k, v in resource_metrics.resource.attributes.items())))
                for scope_metrics in resource_metrics.scope_metrics:
                    for metric_data in scope_metrics.metrics:
                        if metric_data.name != metric: continue
                        for point in metric_data.data.data_points:
                            if any((point.attributes.get(k) != v for k, v in labels.items())): continue
                            key = (resource, tuple(sorted(point.attributes.items()))); series[key].append((point.time_unix_nano, point.value))
    total = 0.0
    for samples in series.values():
        samples.sort(); previous = samples[0][1]
        for (_, value) in samples[1:]: total += value - previous if value >= previous else value; previous = value
    return total
async def test_three_flow_run_processes_each_failing_once_raise_the_p1_alert_increase_to_three(worker_env, monkeypatch) -> None:
    'AC-observability.12.4'; monkeypatch.delenv('OTEL_SERVICE_NAME', raising=False)
    class FailingUseCase:
        async def execute(self, _job): telemetry_metrics.record_statement_parse_outcome(outcome='failure'); raise RuntimeError('boom')
    monkeypatch.setattr(statement_flow, 'compose_statement_ingestion_use_case', lambda **_k: FailingUseCase())
    for _ in range(3):
        _fresh_process(monkeypatch)
        with pytest.raises(RuntimeError, match='boom'): await statement_flow.parse_statement_flow.fn(job=_job())
    assert len(CapturingMetricExporter.instances) == 3; exporters = CapturingMetricExporter.instances; instance_ids = {rm.resource.attributes['service.instance.id'] for e in exporters for b in e.batches for rm in b.resource_metrics}; assert len(instance_ids) == 3; assert _prom_increase(exporters, OUTCOME_METRIC, outcome='failure') == 3; assert _prom_increase(exporters, 'finance.async_parse.failure') == 3
def test_prom_increase_model_sees_no_increase_for_identical_single_sample_series() -> None:
    exporter = CapturingMetricExporter(); point = type('P', (), {'attributes': {'outcome': 'failure'}, 'value': 1, 'time_unix_nano': 0})
    for i in range(3): p = point(); p.time_unix_nano = i; scope = type('S', (), {'metrics': [type('M', (), {'name': OUTCOME_METRIC, 'data': type('D', (), {'data_points': [p]})})]}); resource = type('R', (), {'attributes': {'service.name': 'finance-report-worker'}}); batch = type('B', (), {'resource_metrics': [type('RM', (), {'resource': resource, 'scope_metrics': [scope]})]}); exporter.batches.append(batch)
    assert _prom_increase([exporter], OUTCOME_METRIC, outcome='failure') == 0
class CapturingLogExporter:
    instances: list[CapturingLogExporter] = []
    def __init__(self, *_args: object, **_kwargs: object) -> None: self.bodies: list[str] = []; CapturingLogExporter.instances.append(self)
    def export(self, batch):
        from opentelemetry.sdk._logs.export import LogExportResult
        for item in batch: record = getattr(item, 'log_record', item); self.bodies.append(str(record.body))
        return LogExportResult.SUCCESS
    def force_flush(self, timeout_millis: int=10000) -> bool: return True
    def shutdown(self) -> None: return None
@pytest.fixture
def prefect_logging_env(worker_env, monkeypatch): import opentelemetry.exporter.otlp.proto.http._log_exporter as log_exporter_module; import structlog; from prefect.logging.configuration import setup_logging; from src.observability import logger as logger_module; root = logging.getLogger(); saved_handlers, saved_level = (list(root.handlers), root.level); [root.removeHandler(handler) for handler in saved_handlers]; root.setLevel(logging.WARNING); setup_logging(); CapturingLogExporter.instances.clear(); monkeypatch.setattr(log_exporter_module, 'OTLPLogExporter', CapturingLogExporter); monkeypatch.setattr(worker_telemetry, 'configure_logging', logger_module.configure_logging); monkeypatch.setattr(worker_telemetry.settings, 'debug', False); monkeypatch.setattr(logger_module, '_logger_provider', None); monkeypatch.setattr(logger_module, '_tracer_provider', None); monkeypatch.setattr(worker_telemetry.settings, 'otel_exporter_otlp_endpoint', 'http://collector:4318'); yield; [root.removeHandler(handler) for handler in list(root.handlers)]; [root.addHandler(handler) for handler in saved_handlers]; root.setLevel(saved_level); structlog.reset_defaults()
async def test_flow_run_exports_info_log_events_with_prefect_logging_active(prefect_logging_env, monkeypatch, capsys) -> None: 'AC-observability.12.4'; monkeypatch.delenv('OTEL_SERVICE_NAME', raising=False); _install_fake_use_case(monkeypatch); await statement_flow.parse_statement_flow.fn(job=_job()); log_exporter, = CapturingLogExporter.instances; assert any(('statement.parse.flow_started' in body for body in log_exporter.bodies)); assert 'statement.parse.flow_started' in capsys.readouterr().out
