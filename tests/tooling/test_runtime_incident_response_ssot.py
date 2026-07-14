from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_AC8_13_126_runtime_incident_response_ssot_centralizes_triage() -> None:
    """AC-testing.governance.6: AC8.13.126: Runtime incident triage has one SSOT and link-only callers."""

    runtime_path = ROOT / "common/runtime/runtime-incident-response.md"
    assert runtime_path.exists()

    runtime = runtime_path.read_text(encoding="utf-8")
    required_runtime_tokens = [
        "# Runtime Incident Response SSOT",
        "`runtime_incident_response`",
        "## Triage Entry Points",
        "## Failure Domain Routing",
        "## Stability Proof",
        "common/runtime/deployment.md",
        "common/observability/observability.md",
        "common/testing/ci-cd.md",
        "common/runtime/ci-cd.md",
        "common/runtime/readme.md",
        "docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md",
        "repo/docs/ssot/ops.alerting.md",
        "repo/docs/ssot/ops.availability-ledger.md",
        "repo/docs/ssot/ops.recovery.md",
        "`route`",
        "`dependency`",
        "`observability`",
        "`secrets`",
        "`stale-version`",
        "`flapping`",
        "production_infra_smoke.py",
        "tools/health_check.sh",
    ]
    for token in required_runtime_tokens:
        assert token in runtime

    manifest = yaml.safe_load(read("common/meta/data/MANIFEST.yaml"))
    concept = manifest["concepts"]["runtime_incident_response"]
    assert concept["owner"] == "common/runtime/runtime-incident-response.md"
    assert concept["family"] == "runtime"
    assert concept["kind"] == "playbook"
    assert "tests/tooling/test_runtime_incident_response_ssot.py" in concept["proofs"]
    assert set(concept["cross_refs"]) >= {
        "common/runtime/deployment.md",
        "common/observability/observability.md",
        "common/testing/ci-cd.md",
        "common/runtime/ci-cd.md",
        "common/runtime/readme.md",
        "docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md",
        "repo/docs/ssot/ops.alerting.md",
        "repo/docs/ssot/ops.availability-ledger.md",
        "repo/docs/ssot/ops.recovery.md",
    }
    assert (
        "tests/tooling/test_runtime_incident_response_ssot.py"
        in manifest["concepts"]["env_smoke_test"]["proofs"]
    )

    # docs/ssot/ (including its README.md tombstone) was retired entirely in
    # #1823 (Package-ization 4/4, terminal) — see
    # tests/tooling/test_terminal_centers_allowlist.py. MANIFEST.yaml (which
    # does own the runtime_incident_response concept, asserted above) now
    # lives at common/meta/data/MANIFEST.yaml.
    deployment = read("common/runtime/deployment.md")
    assert "(./runtime-incident-response.md)" in deployment
    assert (
        "| 502 Bad Gateway | Backend crashed | Check CHECKPOINT-3 in SigNoz logs |"
        not in deployment
    )

    observability = read("common/observability/observability.md")
    assert "(../runtime/runtime-incident-response.md)" in observability
    assert "docker exec finance-report-backend env | grep OTEL" not in observability

    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    assert "(./runtime-incident-response.md)" in ci_cd

    # env_smoke_test.md was retired; its Three-Gates SSOT is internalized into
    # the runtime package readme, which now carries the link-back to this triage
    # SSOT (deployed-service incident routing).
    runtime_readme = read("common/runtime/readme.md")
    assert "(../../common/runtime/runtime-incident-response.md)" in runtime_readme

    recommendation = read("docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md")
    assert "(../../common/runtime/runtime-incident-response.md)" in recommendation
