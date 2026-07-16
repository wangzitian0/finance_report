"""Reconciliation extension layer (domain services + adapters)."""

from src.reconciliation.extension.anomaly import AnomalyResult, detect_anomalies
from src.reconciliation.extension.consistency_checks import (
    detect_anomalies_batch,
    detect_duplicates,
    detect_transfer_pairs,
    has_unresolved_checks,
    list_checks,
    resolve_check,
    run_all_consistency_checks,
)
from src.reconciliation.extension.fx_transfer import (
    DEFAULT_RATE_TOLERANCE,
    DEFAULT_TIME_WINDOW,
    REVALUATION_SOURCE_TYPE,
    FxLegPair,
    FxTransferError,
    TransferClassification,
    TransferLeg,
    build_fx_conversion,
    classify_internal_transfer,
    implied_rate,
    pair_fx_legs,
    round_trip_realized_pnl,
)
from src.reconciliation.extension.fx_transfer_discovery import discover_fx_conversions

__all__ = [
    "AnomalyResult",
    "DEFAULT_RATE_TOLERANCE",
    "DEFAULT_TIME_WINDOW",
    "FxLegPair",
    "FxTransferError",
    "REVALUATION_SOURCE_TYPE",
    "TransferClassification",
    "TransferLeg",
    "build_fx_conversion",
    "classify_internal_transfer",
    "detect_anomalies",
    "detect_anomalies_batch",
    "detect_duplicates",
    "detect_transfer_pairs",
    "discover_fx_conversions",
    "has_unresolved_checks",
    "implied_rate",
    "list_checks",
    "pair_fx_legs",
    "resolve_check",
    "round_trip_realized_pnl",
    "run_all_consistency_checks",
]
