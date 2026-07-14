"""AC-extraction.1913.3: the durable-parse Prefect deployment registers cleanly (EPIC-019).

Staging investigation (2026-07-14): the Prefect server + worker infra was
running and reachable, and the flow code (``statement_flow.py``) was already
correct, but nothing had ever registered a deployment for it — the server's
``/api/deployments/filter`` returned zero results. These tests pin the
registration script's structural correctness so that gap can't silently
reopen (e.g. the flow/deployment name drifting out of sync with
``PARSE_DEPLOYMENT`` in ``statement_pipeline.py``, which the API side uses to
submit runs by name).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_db


def test_AC_extraction_1913_3_registration_script_targets_the_deployment_api_submits_to():
    """The registered (flow_name, deployment_name) pair must equal PARSE_DEPLOYMENT,
    or the API's run_deployment(name=PARSE_DEPLOYMENT, ...) call finds nothing."""
    from scripts import register_prefect_deployment as registration_module
    from src.extraction.extension.statement_flow import parse_statement_flow
    from src.extraction.extension.statement_pipeline import PARSE_DEPLOYMENT

    registered_as = f"{parse_statement_flow.name}/{registration_module.DEPLOYMENT_NAME}"
    assert registered_as == PARSE_DEPLOYMENT
    assert registration_module.WORK_POOL_NAME == "default"


def test_AC_extraction_1913_3_registration_script_deploys_from_local_source(monkeypatch):
    """The script must deploy from LOCAL source (code already baked into the
    worker's own image, per the promote-not-rebuild release model) — not a
    remote git/storage reference, which would need extra infra to host."""
    calls: dict = {}

    class _FakeSourcedFlow:
        def deploy(self, *, name: str, work_pool_name: str):
            calls["name"] = name
            calls["work_pool_name"] = work_pool_name

    def fake_from_source(self, *, source: str, entrypoint: str):
        calls["source"] = source
        calls["entrypoint"] = entrypoint
        return _FakeSourcedFlow()

    import src.extraction.extension.statement_flow as statement_flow_module

    monkeypatch.setattr(statement_flow_module.parse_statement_flow.__class__, "from_source", fake_from_source)

    from scripts import register_prefect_deployment

    assert register_prefect_deployment.main() == 0

    assert calls["source"] == str(register_prefect_deployment.BACKEND_ROOT)
    assert calls["entrypoint"] == "src/extraction/extension/statement_flow.py:parse_statement_flow"
    assert calls["name"] == "parse-statement"
    assert calls["work_pool_name"] == "default"


def test_AC_extraction_1913_3_worker_entrypoint_registers_before_starting_the_worker():
    """The worker container must register the deployment BEFORE polling for
    work — otherwise the worker starts against a server with no matching
    deployment, and every dispatched flow run is silently unrunnable."""
    from pathlib import Path

    entrypoint = Path("scripts/prefect_worker_entrypoint.sh").read_text()
    register_line = entrypoint.index("register_prefect_deployment.py")
    worker_start_line = entrypoint.index("prefect worker start")
    assert register_line < worker_start_line
    assert "--pool default" in entrypoint
