"""Structural locks for #1866 S3 PR-D package ownership."""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

from common.meta.extension.check_package_contract import discover_packages, run
from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "apps/backend"
SRC = BACKEND / "src"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@ac_proof(
    proof_id="counter_async_repository_composition",
    ac_ids=["AC-counter.repository.5"],
    ci_tier="pr_ci",
)
def test_AC_counter_repository_5_async_adapter_and_api_composition() -> None:
    """AC-counter.repository.5: the production adapter drives the async base ops."""
    from src.counter import CounterRepository
    from src.counter.extension.sql import SqlCounterRepository

    assert inspect.iscoroutinefunction(CounterRepository.bump)
    assert inspect.iscoroutinefunction(CounterRepository.total)
    assert inspect.iscoroutinefunction(CounterRepository.for_user)
    assert isinstance(
        SqlCounterRepository.__new__(SqlCounterRepository), CounterRepository
    )

    write_source = (SRC / "counter/extension/api/write.py").read_text(encoding="utf-8")
    read_source = (SRC / "counter/extension/api/insight.py").read_text(encoding="utf-8")
    assert "await increment(repo" in write_source
    assert "await get_count(repo" in read_source
    assert "repo.bump(" not in write_source
    assert "repo.total(" not in read_source
    assert "repo.for_user(" not in read_source


@ac_proof(
    proof_id="typed_fx_ports",
    ac_ids=[
        "AC-advisor.fx-port.1",
        "AC-extraction.fx-port.1",
        "AC-ledger.fx-port.1",
        "AC-reporting.fx-port.1",
    ],
    ci_tier="pr_ci",
)
def test_AC_s3_typed_fx_ports_have_no_erased_registration_or_forwarders() -> None:
    """#1866 G-typed-ports: every FX registry exposes an exact typed call shape."""
    paths = (
        SRC / "reporting/extension/fx_gateway.py",
        SRC / "advisor/extension/app_reads.py",
        SRC / "extraction/extension/review_queue.py",
        SRC / "ledger/extension/fx_revaluation.py",
    )
    failures: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not (
                node.name.startswith("register_fx")
                or node.name
                in {
                    "get_exchange_rate",
                    "get_average_rate",
                    "convert_amount",
                    "convert_money",
                }
            ):
                continue
            rendered = ast.unparse(node)
            if (
                node.args.vararg
                or node.args.kwarg
                or "Callable[...," in rendered
                or ": Any" in rendered
            ):
                failures.append(f"{path.relative_to(REPO)}:{node.lineno}:{node.name}")
    assert not failures, "type-erased FX seams: " + ", ".join(failures)


@ac_proof(
    proof_id="reporting_snapshot_ownership",
    ac_ids=["AC-reporting.snapshot-ownership.1"],
    ci_tier="pr_ci",
)
def test_AC_reporting_snapshot_ownership_and_metadata_registration() -> None:
    """#1866 G-orm-home: reporting owns one mapped ReportSnapshot class."""
    from src.database import Base
    from src.reporting import ReportSnapshot, ReportType
    from src.reporting.orm import ReportSnapshot as OrmReportSnapshot

    assert ReportSnapshot is OrmReportSnapshot
    assert ReportType is OrmReportSnapshot.__table__.c.report_type.type.enum_class
    assert Base.metadata.tables["report_snapshots"] is ReportSnapshot.__table__
    assert not (SRC / "extraction/orm/layer4.py").exists()

    extraction_all = set(__import__("src.extraction", fromlist=["__all__"]).__all__)
    reporting_all = set(__import__("src.reporting", fromlist=["__all__"]).__all__)
    assert {"ReportSnapshot", "ReportType"}.isdisjoint(extraction_all)
    assert {"ReportSnapshot", "ReportType"} <= reporting_all


@ac_proof(
    proof_id="workflow_package_ownership",
    ac_ids=["AC-workflow.package.1"],
    ci_tier="pr_ci",
)
def test_AC_workflow_package_1_owns_contract_and_direct_domain_reads() -> None:
    """AC-workflow.package.1: workflow is governed and no longer uses locators."""
    packages = {package.contract.name: package for package in discover_packages(REPO)}
    assert "workflow" in packages
    ok, messages = run(REPO)
    assert ok, "package contract gate failed:\n" + "\n".join(messages)

    workflow = SRC / "workflow"
    assert (workflow / "base/types.py").exists()
    assert (workflow / "extension/events.py").exists()
    assert (workflow / "extension/builders.py").exists()
    assert (workflow / "orm/models.py").exists()

    source = (workflow / "extension/events.py").read_text(encoding="utf-8")
    assert "from src.extraction import" in source
    assert "from src.reporting import" in source
    assert "register_readiness_provider" not in source
    assert "register_uploaded_document_readers" not in source
    assert "register_statement_reader" not in source
    assert "_require_" not in source

    platform_source = "\n".join(
        path.read_text(encoding="utf-8") for path in (SRC / "platform").rglob("*.py")
    )
    assert "class WorkflowEvent" not in platform_source
    assert "class WorkflowSession" not in platform_source
