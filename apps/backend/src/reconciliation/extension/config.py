"""Runtime YAML/environment configuration and cache for reconciliation."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import src.config
from src.observability import get_logger
from src.reconciliation.base.config import DEFAULT_CONFIG, ReconciliationConfig

logger = get_logger(__name__)

_config_cache: ReconciliationConfig | None = None


def _yaml_boolean(value: object) -> bool:
    """Parse the AI switch explicitly; invalid YAML follows the loader fallback."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValueError("enable_ai_reconciliation must be a boolean")


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
                    enable_ai_reconciliation=_yaml_boolean(
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

    env_settings = src.config.Settings(_env_file=None)
    if env_settings.reconciliation_auto_accept_threshold is not None:
        config = replace(config, auto_accept=env_settings.reconciliation_auto_accept_threshold)
    if env_settings.reconciliation_review_threshold is not None:
        config = replace(config, pending_review=env_settings.reconciliation_review_threshold)
    if "enable_ai_reconciliation" in env_settings.model_fields_set:
        config = replace(config, enable_ai_reconciliation=env_settings.enable_ai_reconciliation)

    _config_cache = config
    return config
