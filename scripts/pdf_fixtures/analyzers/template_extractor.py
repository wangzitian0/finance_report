from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


class TemplateExtractor:
    def extract(self, analysis: dict[str, Any], output_path: Path) -> dict[str, Any]:
        sanitized = self._sanitize(analysis)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as output_file:
            yaml.safe_dump(
                sanitized,
                output_file,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
        return sanitized

    def _sanitize(self, data: dict) -> dict:
        def sanitize_value(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: sanitize_value(item)
                    for key, item in value.items()
                    if not self._is_sensitive_key(str(key))
                }
            if isinstance(value, list):
                return [sanitize_value(item) for item in value]
            if isinstance(value, str):
                return self._mask_sensitive_string(value)
            return value

        return sanitize_value(data)

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        lowered = key.lower()
        sensitive_tokens = {
            "amount",
            "balance",
            "name",
            "account",
            "holder",
            "counterparty",
            "payee",
            "payer",
            "iban",
            "swift",
            "card",
            "number",
            "transaction_id",
            "reference",
        }
        return any(token in lowered for token in sensitive_tokens)

    @staticmethod
    def _mask_sensitive_string(value: str) -> str:
        masked = value
        masked = re.sub(r"\b\d{8,}\b", "[REDACTED_ACCOUNT]", masked)
        masked = re.sub(r"\b\d+[,.]\d{2}\b", "[REDACTED_AMOUNT]", masked)
        return masked
