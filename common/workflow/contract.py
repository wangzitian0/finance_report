"""Machine-checkable PackageContract for ``workflow``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
    PackageContract,
    acs,
    concepts,
    invs,
    rels,
    units,
)

CONTRACT = PackageContract(
    name="workflow",
    status="active",
    tier="CODE-ONLY",
    depends_on="extraction platform reconciliation reporting".split(),
    roles="base extension".split(),
    implementations={"be": "apps/backend/src/workflow", "fe": None},
    context=ContextScope(
        purpose="Own the user-facing upload-to-report process state.",
        in_scope=[
            "WorkflowSession and WorkflowEvent lifecycle and response vocabulary.",
            "Derived workflow status, report-readiness state.",
            "Cross-context process composition for a user's upload-to-report journey.",
        ],
        out_of_scope=[
            "Statement parsing/source facts, reconciliation matching.",
            "Generic event bus, outbox, HTTP, persistence substrate, or delivery routing.",
            "Ledger, valuation, and other business-domain policy ownership.",
        ],
    ),
    relationships=rels(
        "workflow",
        """
extraction|projection|Reads published statement event sources to derive workflow lifecycle state.
platform|composition|Uses platform ORM mixins.
reconciliation|projection|Reads pending-review counts to derive workflow readiness.
reporting|projection|Reads report-package summary state to derive user next actions.
""",
    ),
    units=units(
        """
@vo|base/types.py|WorkflowEventCountsResponse WorkflowEventCreate WorkflowEventFamily WorkflowEventListResponse WorkflowEventResponse WorkflowEventSeverity WorkflowEventStatus WorkflowEventStatusUpdate WorkflowNextActionResponse WorkflowNextActionType WorkflowPrimaryState WorkflowReportImpact WorkflowReportReadinessResponse WorkflowReportReadinessState WorkflowSessionStatus WorkflowSessionSummaryResponse WorkflowStatusResponse
WorkflowEvent|ent
WorkflowSession|agg
@svc|extension/events.py|sync_workflow_events_for_user get_workflow_status
"""
    ),
    interface="""
WorkflowEvent WorkflowEventCountsResponse WorkflowEventCreate WorkflowEventFamily
WorkflowEventListResponse WorkflowEventResponse WorkflowEventSeverity
WorkflowEventStatus WorkflowEventStatusUpdate WorkflowNextActionResponse
WorkflowNextActionType WorkflowPrimaryState WorkflowReportImpact
WorkflowReportReadinessResponse WorkflowReportReadinessState WorkflowSession
WorkflowSessionSummaryResponse WorkflowSessionStatus WorkflowStatusResponse
get_workflow_status list_workflow_events_response stored_package_readiness
sync_workflow_events_for_user update_workflow_event_status upsert_workflow_event
""".split(),
    events=[],
    invariants=invs(
        """
package-ownership|Workflow vocabulary, derivation.|$t/test_s3_pr_d_structure.py::test_AC_workflow_package_1_owns_contract_and_direct_domain_reads
"""
    ),
    roadmap=acs(
        "workflow",
        """
@$be/workflow/test_workflow_sync_gate.py|P0
sync.1|At 1000 journal entries, GET /workflow/status builds no traceability appendix.|test_AC_workflow_sync_1_year_scale_status_read_is_bounded_and_write_free
sync.2|An insert or an update of a derivation source row makes the next workflow read derive the events again.|test_AC_workflow_sync_2_a_source_change_derives_events_again
sync.3|The source fingerprint reads every model table, except tables that an explicit exclusion names with a reason.|test_AC_workflow_sync_3_fingerprint_classifies_every_table
sync.4|The source fingerprint changes on a user, child, global, date, or settings change.|test_AC_workflow_sync_4_fingerprint_changes_only_with_an_input
sync.5|A workflow read reuses the last derivation only.|test_AC_workflow_sync_5_a_state_older_than_the_max_age_derives_again
sync.7|Sync_workflow_events_for_user and get_workflow_status catch ReportError during package readiness evaluation and surface a blocked readiness state.|test_AC_workflow_sync_7_report_error_becomes_blocked_readiness_state|P1
@-|P1
vocabulary-ownership.1|Workflow event, lifecycle, status.|$t/test_vocabulary_ownership.py::test_AC_workflow_vocabulary_ownership_1_workflow_owns_payloads
package.1|Workflow is a governed package and composes published extraction and reporting reads.|$t/test_s3_pr_d_structure.py::test_AC_workflow_package_1_owns_contract_and_direct_domain_reads|P0
sync.6|Stored_package_readiness returns the readiness of the last derivation only.|$be/workflow/test_stored_package_readiness.py::test_AC_workflow_sync_6_stored_readiness_is_returned_only_while_the_derivation_is_reusable
""",
    ),
    concepts=concepts(
        """
workflow_events|common/workflow/workflow-events.md|User-facing upload-to-report workflow event read model and its package-owned request/response vocabulary.|docs/project/EPIC-019.event-driven-upload-to-report-ux.md,common/extraction/confirmation-workflow.md,common/reporting/reporting.md|-|workflow|concept
"""
    ),
)
