"""Machine-checkable contract for the upload-to-report workflow domain."""

from __future__ import annotations

from common.meta.package_contract import (
    ac,
    ConceptRecord,
    ContextRelation,
    ContextScope,
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

# fmt: off
CONTRACT = PackageContract(
    name="workflow",
    status="active",
    tier="CODE-ONLY",
    depends_on=["extraction", "platform", "reconciliation", "reporting"],
    context=ContextScope(
        purpose="Own the user-facing upload-to-report process state: workflow sessions, derived event inbox entries, readiness, and next-action guidance.",
        in_scope=[
            "WorkflowSession and WorkflowEvent lifecycle and response vocabulary",
            "derived workflow status, report-readiness state, and next-action projections",
            "cross-context process composition for a user's upload-to-report journey",
        ],
        out_of_scope=[
            "statement parsing/source facts, reconciliation matching, and report-document ownership",
            "generic event bus, outbox, HTTP, persistence substrate, or delivery routing",
            "ledger, valuation, and other business-domain policy ownership",
        ],
    ),
    relationships=[
        ContextRelation(
            provider="extraction",
            consumer="workflow",
            mode="projection",
            reason="Reads published statement event sources to derive workflow lifecycle state.",
        ),
        ContextRelation(
            provider="platform",
            consumer="workflow",
            mode="composition",
            reason="Uses platform ORM mixins while workflow owns the process-state model itself.",
        ),
        ContextRelation(
            provider="reconciliation",
            consumer="workflow",
            mode="projection",
            reason="Reads pending-review counts to derive workflow readiness without making matches.",
        ),
        ContextRelation(
            provider="reporting",
            consumer="workflow",
            mode="projection",
            reason="Reads report-package summary state to derive user next actions without owning reports.",
        ),
    ],
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
        ac('AC-workflow.vocabulary-ownership.1', 'Workflow event, lifecycle, status, and response payloads are workflow-owned base value objects; src.schemas.workflow is a compatibility re-export surface.', 'tests/tooling/test_vocabulary_ownership.py::test_AC_workflow_vocabulary_ownership_1_workflow_owns_payloads', priority='P1'),
        ac('AC-workflow.package.1', 'Workflow is a governed package and composes published extraction and reporting reads through imports rather than service locators.', 'tests/tooling/test_s3_pr_d_structure.py::test_AC_workflow_package_1_owns_contract_and_direct_domain_reads'),
        ac('AC-workflow.sync.1', 'At 1000 journal entries, GET /workflow/status builds no traceability appendix. A repeated read without a source change sends fewer than 40 SQL statements and no write.', 'apps/backend/tests/workflow/test_workflow_sync_gate.py::test_AC_workflow_sync_1_year_scale_status_read_is_bounded_and_write_free'),
        ac('AC-workflow.sync.2', 'An insert or an update of a derivation source row makes the next workflow read derive the events again, so no event stays stale.', 'apps/backend/tests/workflow/test_workflow_sync_gate.py::test_AC_workflow_sync_2_a_source_change_derives_events_again'),
        ac('AC-workflow.sync.3', 'The source fingerprint reads every model table, except tables that an explicit exclusion names with a reason.', 'apps/backend/tests/workflow/test_workflow_sync_gate.py::test_AC_workflow_sync_3_fingerprint_classifies_every_table'),
        ac('AC-workflow.sync.4', 'The source fingerprint changes on a user, child, global, date, or settings change. It does not change on excluded tables or on rows of another user.', 'apps/backend/tests/workflow/test_workflow_sync_gate.py::test_AC_workflow_sync_4_fingerprint_changes_only_with_an_input'),
        ac('AC-workflow.sync.5', 'A workflow read reuses the last derivation only while its state is younger than 15 minutes. An older state derives again, so an external provider recovery reaches the events.', 'apps/backend/tests/workflow/test_workflow_sync_gate.py::test_AC_workflow_sync_5_a_state_older_than_the_max_age_derives_again'),
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
            family="workflow",
            kind="concept",
        ),
    ],
)
# fmt: on
