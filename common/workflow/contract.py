"""Machine-checkable contract for the upload-to-report workflow domain."""

from __future__ import annotations

from common.meta.package_contract import (
    ACRecord,
    ConceptRecord,
    Invariant,
    Kind,
    PackageContract,
    Unit,
)

_VALUE_OBJECTS = [
    "WorkflowEventCountsResponse",
    "WorkflowEventCreate",
    "WorkflowEventFamily",
    "WorkflowEventListResponse",
    "WorkflowEventResponse",
    "WorkflowEventSeverity",
    "WorkflowEventStatus",
    "WorkflowEventStatusUpdate",
    "WorkflowNextActionResponse",
    "WorkflowNextActionType",
    "WorkflowPrimaryState",
    "WorkflowReportImpact",
    "WorkflowReportReadinessResponse",
    "WorkflowReportReadinessState",
    "WorkflowSessionStatus",
    "WorkflowSessionSummaryResponse",
    "WorkflowStatusResponse",
]

CONTRACT = PackageContract(
    name="workflow",
    status="active",
    tier="CODE-ONLY",
    depends_on=["extraction", "platform", "reporting"],
    roles=["base", "extension"],
    units=[
        *[
            Unit(name=name, kind=Kind.VALUE_OBJECT, module="base/types.py")
            for name in _VALUE_OBJECTS
        ],
        Unit(name="WorkflowEvent", kind=Kind.ENTITY),
        Unit(name="WorkflowSession", kind=Kind.AGGREGATE_ROOT),
        Unit(
            name="sync_workflow_events_for_user",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/events.py",
        ),
        Unit(
            name="get_workflow_status",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/events.py",
        ),
    ],
    implementations={"be": "apps/backend/src/workflow", "fe": None},
    interface=[
        "WorkflowEvent",
        "WorkflowEventCountsResponse",
        "WorkflowEventCreate",
        "WorkflowEventFamily",
        "WorkflowEventListResponse",
        "WorkflowEventResponse",
        "WorkflowEventSeverity",
        "WorkflowEventStatus",
        "WorkflowEventStatusUpdate",
        "WorkflowNextActionResponse",
        "WorkflowNextActionType",
        "WorkflowPrimaryState",
        "WorkflowReportImpact",
        "WorkflowReportReadinessResponse",
        "WorkflowReportReadinessState",
        "WorkflowSession",
        "WorkflowSessionSummaryResponse",
        "WorkflowSessionStatus",
        "WorkflowStatusResponse",
        "get_workflow_status",
        "list_workflow_events_response",
        "sync_workflow_events_for_user",
        "update_workflow_event_status",
        "upsert_workflow_event",
    ],
    events=[],
    invariants=[
        Invariant(
            id="package-ownership",
            statement=(
                "Workflow vocabulary, derivation, and ORM models live in the "
                "workflow package; platform retains only generic substrate."
            ),
            test=(
                "tests/tooling/test_s3_pr_d_structure.py"
                "::test_AC_workflow_package_1_owns_contract_and_direct_domain_reads"
            ),
        ),
    ],
    roadmap=[
        ACRecord(
            id="AC-workflow.vocabulary-ownership.1",
            statement=(
                "Workflow event, lifecycle, status, and response payloads are "
                "workflow-owned base value objects; src.schemas.workflow is a "
                "compatibility re-export surface."
            ),
            test=(
                "tests/tooling/test_vocabulary_ownership.py"
                "::test_AC_workflow_vocabulary_ownership_1_workflow_owns_payloads"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-workflow.package.1",
            statement=(
                "Workflow is a governed package and composes published extraction "
                "and reporting reads through imports rather than service locators."
            ),
            test=(
                "tests/tooling/test_s3_pr_d_structure.py"
                "::test_AC_workflow_package_1_owns_contract_and_direct_domain_reads"
            ),
            priority="P0",
            status="done",
        ),
    ],
    concepts=[
        ConceptRecord(
            key="workflow_events",
            owner="common/workflow/workflow-events.md",
            description=(
                "User-facing upload-to-report workflow event read model and "
                "its package-owned request/response vocabulary."
            ),
            cross_refs=[
                "docs/project/EPIC-019.event-driven-upload-to-report-ux.md",
                "common/extraction/confirmation-workflow.md",
                "common/reporting/reporting.md",
            ],
        ),
    ],
)
