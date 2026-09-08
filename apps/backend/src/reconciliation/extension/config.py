"""Runtime YAML/environment configuration and cache for reconciliation."""

from __future__ import annotations

import os
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import ModuleType

from src.observability import get_logger
from src.reconciliation.base.config import DEFAULT_CONFIG, ReconciliationConfig

logger = get_logger(__name__)

_config_cache: ReconciliationConfig | None = None


def load_reconciliation_config(force_reload: bool = False) -> ReconciliationConfig:
    """Load reconciliation configuration from YAML if available.

    Caches the result to avoid repeated disk I/O.
    """
    global _config_cache
    if _config_cache is not None and not force_reload:
        return _config_cache

    config = DEFAULT_CONFIG
    config_path = Path(__file__).resolve().parents[3] / "config" / "reconciliation.yaml"

    if config_path.exists():
        _yaml: ModuleType | None
        try:
            import yaml as _yaml
        except ImportError:
            _yaml = None

        if _yaml is not None:
            try:
                raw = _yaml.safe_load(config_path.read_text()) or {}
                scoring = raw.get("scoring", {})
                weights = scoring.get("weights", {})
                thresholds = scoring.get("thresholds", {})
                tolerances = scoring.get("tolerances", {})

                config = ReconciliationConfig(
                    weight_amount=Decimal(str(weights.get("amount", config.weight_amount))),
                    weight_date=Decimal(str(weights.get("date", config.weight_date))),
                    weight_description=Decimal(str(weights.get("description", config.weight_description))),
                    weight_business=Decimal(str(weights.get("business", config.weight_business))),
                    weight_history=Decimal(str(weights.get("history", config.weight_history))),
                    auto_accept=int(thresholds.get("auto_accept", config.auto_accept)),
                    pending_review=int(thresholds.get("pending_review", config.pending_review)),
                    amount_percent=Decimal(str(tolerances.get("amount_percent", config.amount_percent))),
                    amount_absolute=Decimal(str(tolerances.get("amount_absolute", config.amount_absolute))),
                    date_days=int(tolerances.get("date_days", config.date_days)),
                    enable_ai_reconciliation=bool(
                        scoring.get(
                            "enable_ai_reconciliation",
                            config.enable_ai_reconciliation,
                        )
                    ),
                )
            except Exception as e:
                logger.warning(
                    "Failed to load reconciliation config - using defaults",
                    config_path=str(config_path),
                    error=str(e),
                    error_type=type(e).__name__,
                )

    auto_accept_env = os.getenv("RECONCILIATION_AUTO_ACCEPT_THRESHOLD")
    pending_review_env = os.getenv("RECONCILIATION_REVIEW_THRESHOLD")
    enable_ai_env = os.getenv("ENABLE_AI_RECONCILIATION")
    if auto_accept_env:
        config = replace(config, auto_accept=int(auto_accept_env))
    if pending_review_env:
        config = replace(config, pending_review=int(pending_review_env))
    if enable_ai_env is not None:
        config = replace(
            config,
            enable_ai_reconciliation=enable_ai_env.lower() in {"1", "true", "yes", "on"},
        )

    _config_cache = config
    return config
