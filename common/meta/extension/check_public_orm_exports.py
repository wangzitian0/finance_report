"""Fail-closed shrink-only gate for package-root public ORM exports."""

from __future__ import annotations

import argparse
import json
from collections.abc import Collection, Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate
from common.meta.extension.public_orm_exports import discover_public_orm_exports

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_PUBLIC_ORM_EXPORTS: frozenset[str] = frozenset(
    {
        "advisor::ChatMessage",
        "advisor::ChatMessageRole",
        "advisor::ChatSession",
        "advisor::ChatSessionStatus",
        "extraction::AssetType",
        "extraction::AtomicPosition",
        "extraction::AtomicTransaction",
        "extraction::ClassificationRule",
        "extraction::CostBasisMethod",
        "extraction::EvidenceEdge",
        "extraction::EvidenceNode",
        "extraction::ManagedPosition",
        "extraction::PositionStatus",
        "extraction::StatementSummary",
        "extraction::TransactionClassification",
        "extraction::UploadedDocument",
        "ledger::Account",
        "ledger::AccountType",
        "ledger::ConfidenceTier",
        "ledger::Direction",
        "ledger::JournalAuditLog",
        "ledger::JournalEntry",
        "ledger::JournalEntryAuthorityState",
        "ledger::JournalEntryStatus",
        "ledger::JournalLine",
        "ledger::derive_confidence_tier",
        "ledger::worst_confidence_tier",
        "llm::LlmProvider",
        "llm::LlmSceneBinding",
        "platform::AppConfig",
        "platform::BASE_CURRENCY_KEY",
        "platform::PingState",
        "platform::TimestampMixin",
        "platform::UUIDMixin",
        "platform::UserOwnedMixin",
        "portfolio::DividendIncome",
        "portfolio::DividendType",
        "portfolio::InvestmentLot",
        "portfolio::InvestmentTransaction",
        "portfolio::InvestmentTransactionType",
        "pricing::FxConversion",
        "pricing::FxRate",
        "pricing::MarketDataOverride",
        "pricing::MarketDataSyncState",
        "pricing::PriceSource",
        "pricing::StatementPriceObservation",
        "pricing::StockPrice",
        "reconciliation::CheckStatus",
        "reconciliation::CheckType",
        "reconciliation::ConsistencyCheck",
        "reconciliation::ReconciliationMatch",
        "reconciliation::ReconciliationMatchJournalEntry",
        "reconciliation::ReconciliationStatus",
        "workflow::WorkflowEvent",
        "workflow::WorkflowSession",
    }
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def violations(
    repo_root: Path,
    baseline_path: Collection[str] | Path = BASELINE_PUBLIC_ORM_EXPORTS,
) -> list[str]:
    if isinstance(baseline_path, Path):
        try:
            payload = json.loads(baseline_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list) or not all(
                isinstance(item, str) for item in payload
            ):
                raise ValueError("baseline must be a JSON string list")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return [f"cannot read public-ORM baseline: {exc}"]
        baseline = set(payload)
    else:
        baseline = set(baseline_path)
    try:
        current = set(discover_public_orm_exports(repo_root / "apps/backend/src"))
    except ValueError as exc:
        return [f"cannot discover public ORM exports: {exc}"]
    return [
        *(f"new public ORM export: {item}" for item in sorted(current - baseline)),
        *(f"stale public-ORM baseline: {item}" for item in sorted(baseline - current)),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    return run_gate(
        "PUBLIC-ORM",
        lambda repo_root: violations(repo_root, BASELINE_PUBLIC_ORM_EXPORTS),
        argv,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
