"""Pydantic schemas package (PEP 562 lazy exports)."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.reporting import CashFlowResponse
    from src.schemas.account import AccountCreate, AccountListResponse, AccountResponse, AccountUpdate
    from src.schemas.extraction import (
        AccountCoverageListResponse,
        BankStatementListResponse,
        BankStatementResponse,
        StatementDecisionRequest,
        StatementRunListResponse,
        StatementRunRequest,
    )
    from src.schemas.journal import (
        JournalEntryCreate,
        JournalEntryListResponse,
        JournalEntryResponse,
        JournalLineCreate,
        VoidJournalEntryRequest,
    )
    from src.schemas.reconciliation import (
        ProcessingPendingItem,
        ProcessingPendingListResponse,
        ProcessingSummaryResponse,
    )
    from src.schemas.reporting import (
        AccountLineageResponse,
        AnnualizedIncomeScheduleHolding,
        AnnualizedIncomeScheduleIncome,
        AnnualizedIncomeScheduleNetWorthTreatment,
        AnnualizedIncomeScheduleResponse,
        BalanceSheetResponse,
        IncomeStatementResponse,
        NetWorthAllocationResponse,
        NetWorthGranularity,
        NetWorthTimeSeriesResponse,
        PersonalDataQualityHealthResponse,
        PersonalReportingFrameworkId,
        PersonalReportPackageContractResponse,
        PersonalReportPackageDocument,
        PersonalReportPackageDocumentLifecycle,
        PersonalReportPackageGenerateRequest,
        PersonalReportPackageLineDetailsPage,
        PersonalReportPackageManifestEntriesPage,
        PersonalReportPackageNotesResponse,
        PersonalReportPackagePreview,
        PersonalReportPackageReadinessState,
        PersonalReportPackageSnapshotResponse,
        PersonalReportPackageSnapshotStatus,
        PersonalReportPackageSnapshotSummary,
        PersonalReportPackageTraceabilityAnchorName,
        PersonalReportPackageTraceabilityResponse,
    )

_GROUPS: dict[str, tuple[str, ...]] = {
    "src.reporting": (
        "CashFlowResponse",
    ),
    "src.schemas.account": (
        "AccountCreate",
        "AccountListResponse",
        "AccountResponse",
        "AccountUpdate",
    ),
    "src.schemas.extraction": (
        "AccountCoverageListResponse",
        "BankStatementListResponse",
        "BankStatementResponse",
        "StatementDecisionRequest",
        "StatementRunListResponse",
        "StatementRunRequest",
    ),
    "src.schemas.journal": (
        "JournalEntryCreate",
        "JournalEntryListResponse",
        "JournalEntryResponse",
        "JournalLineCreate",
        "VoidJournalEntryRequest",
    ),
    "src.schemas.reconciliation": (
        "ProcessingPendingItem",
        "ProcessingPendingListResponse",
        "ProcessingSummaryResponse",
    ),
    "src.schemas.reporting": (
        "AccountLineageResponse",
        "AnnualizedIncomeScheduleHolding",
        "AnnualizedIncomeScheduleIncome",
        "AnnualizedIncomeScheduleNetWorthTreatment",
        "AnnualizedIncomeScheduleResponse",
        "BalanceSheetResponse",
        "IncomeStatementResponse",
        "NetWorthAllocationResponse",
        "NetWorthGranularity",
        "NetWorthTimeSeriesResponse",
        "PersonalDataQualityHealthResponse",
        "PersonalReportingFrameworkId",
        "PersonalReportPackageContractResponse",
        "PersonalReportPackageDocument",
        "PersonalReportPackageDocumentLifecycle",
        "PersonalReportPackageGenerateRequest",
        "PersonalReportPackageLineDetailsPage",
        "PersonalReportPackageManifestEntriesPage",
        "PersonalReportPackageNotesResponse",
        "PersonalReportPackagePreview",
        "PersonalReportPackageReadinessState",
        "PersonalReportPackageSnapshotResponse",
        "PersonalReportPackageSnapshotStatus",
        "PersonalReportPackageSnapshotSummary",
        "PersonalReportPackageTraceabilityAnchorName",
        "PersonalReportPackageTraceabilityResponse",
    ),
}

_LAZY = {name: (mod, name) for mod, names in _GROUPS.items() for name in names}
__all__ = [
    "AccountCoverageListResponse",
    "AccountCreate",
    "AccountLineageResponse",
    "AccountListResponse",
    "AccountResponse",
    "AccountUpdate",
    "AnnualizedIncomeScheduleHolding",
    "AnnualizedIncomeScheduleIncome",
    "AnnualizedIncomeScheduleNetWorthTreatment",
    "AnnualizedIncomeScheduleResponse",
    "BalanceSheetResponse",
    "BankStatementListResponse",
    "BankStatementResponse",
    "CashFlowResponse",
    "IncomeStatementResponse",
    "JournalEntryCreate",
    "JournalEntryListResponse",
    "JournalEntryResponse",
    "JournalLineCreate",
    "NetWorthAllocationResponse",
    "NetWorthGranularity",
    "NetWorthTimeSeriesResponse",
    "PersonalDataQualityHealthResponse",
    "PersonalReportPackageContractResponse",
    "PersonalReportPackageDocument",
    "PersonalReportPackageDocumentLifecycle",
    "PersonalReportPackageGenerateRequest",
    "PersonalReportPackageLineDetailsPage",
    "PersonalReportPackageManifestEntriesPage",
    "PersonalReportPackageNotesResponse",
    "PersonalReportPackagePreview",
    "PersonalReportPackageReadinessState",
    "PersonalReportPackageSnapshotResponse",
    "PersonalReportPackageSnapshotStatus",
    "PersonalReportPackageSnapshotSummary",
    "PersonalReportPackageTraceabilityAnchorName",
    "PersonalReportPackageTraceabilityResponse",
    "PersonalReportingFrameworkId",
    "ProcessingPendingItem",
    "ProcessingPendingListResponse",
    "ProcessingSummaryResponse",
    "StatementDecisionRequest",
    "StatementRunListResponse",
    "StatementRunRequest",
    "VoidJournalEntryRequest",
]


def __getattr__(name: str) -> object:
    entry = _LAZY.get(name)
    if entry is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(entry[0]), entry[1])
    globals()[name] = value
    return value
