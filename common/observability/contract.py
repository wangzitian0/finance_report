"""The ``observability`` package's machine-checkable :class:`PackageContract`.

``observability`` owns two cohesive surfaces. Its **BE implementation**
(``apps/backend/src/observability``) publishes the backend's observability
language: the vendor-neutral OpenTelemetry runtime contract plus the shared
structured audit/security logging helpers (PII + secret redaction) — this is the
home #1428 relocates the shared logging helpers into. The stdlib OpenPanel query
CLI (``openpanel_query``) stays here in ``common/observability`` as a triage tool
run via ``tools/`` wrappers (its invariant is pinned below).

``depends_on=["config"]``: the OTEL runtime reads the backend config singleton via
its bare published root (``import src.config``), the one registered-package edge it
declares (a same-class ``kernel`` -> ``kernel`` edge, acyclic). Its other imports
(``src.services.pii_redaction``, ``src.telemetry_metrics``) are unregistered backend
infrastructure, so they are not governed cross-package edges.
"""

from __future__ import annotations

from common.meta.package_contract import Invariant, PackageContract

CONTRACT = PackageContract(
    name="observability",
    klass="kernel",
    status="active",
    tier="CODE-ONLY",
    depends_on=["config"],
    implementations={"be": "apps/backend/src/observability", "fe": None},
    interface=[
        "current_request_id",
        "get_observability_status",
        "is_fastapi_instrumentation_active",
        "log_financial_mutation",
        "log_observability_startup",
        "log_security_warning",
        "mark_fastapi_instrumentation_active",
        "safe_error_message",
        "safe_log_fields",
    ],
    events=[],
    invariants=[
        Invariant(
            id="api-key-from-env-not-argv",
            statement="The OpenPanel query CLI reads its API key from the environment, never from command-line args (no secret in argv).",
            test="tests/tooling/test_openpanel_query.py::test_AC23_1_4_api_key_read_from_env_not_args",
        ),
    ],
    roadmap=[],
)
