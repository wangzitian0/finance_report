"""Prod-snapshot anonymizer — the data boundary of ``deploy(env, code, data)`` (#893)."""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from hashlib import sha256
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

__all__ = [
    "Action",
    "ResidualError",
    "UnclassifiedColumnError",
    "anonymize",
    "classify_columns",
    "scan_for_residuals",
]


class UnclassifiedColumnError(Exception):
    """A live model column has no explicit classification — refuse to run."""


class ResidualError(Exception):
    """An original sensitive value survived anonymization — refuse to commit."""


class Action(str, Enum):
    """What happens to a column's values when the snapshot is anonymized."""

    KEEP = "keep"
    SCALE = "scale"
    PSEUDONYM = "pseudonym"
    REDACT_JSON = "redact_json"
    REDACT_SECRET = "redact_secret"


def _expand(groups: dict[str, str]) -> frozenset[str]:
    return frozenset(f"{table}.{col}" for table, cols in groups.items() for col in cols.split())


MONEY_COLUMNS: frozenset[str] = _expand(
    {
        "atomic_positions": "market_value",
        "atomic_transactions": "amount balance_after",
        "dividend_income": "amount",
        "fx_conversions": "amount_from amount_to fee",
        "investment_lots": "unit_cost",
        "investment_transactions": "cost_basis fees gross_amount realized_pnl unit_price",
        "journal_lines": "amount",
        "opening_position_records": "amount",
        "managed_positions": "cost_basis realized_pnl unrealized_pnl",
        "manual_valuation_snapshots": "value",
        "market_data_override": "price",
        "statement_price_observations": "value",
        "statement_summaries": "closing_balance manual_opening_balance opening_balance",
        "reviewed_statement_envelopes": "closing_balance opening_balance",
        "stock_prices": "price",
    }
)

NUMERIC_KEEP_COLUMNS: frozenset[str] = _expand(
    {
        "atomic_positions": "quantity",
        "fx_conversions": "rate",
        "fx_rates": "rate",
        "investment_lots": "original_quantity remaining_quantity",
        "investment_transactions": "quantity",
        "journal_lines": "fx_rate",
        "opening_position_records": "fx_rate",
        "managed_positions": "quantity",
        "trace_records": "score",
    }
)

JSON_KEEP_COLUMNS: frozenset[str] = _expand(
    {
        "consistency_checks": "related_txn_ids",
        "reconciliation_matches": "journal_entry_ids score_breakdown",
    }
)

STRING_KEEP_COLUMNS: frozenset[str] = _expand(
    {
        "accounts": "currency type",
        "ai_feedback": "action",
        "app_config": "key",
        "atomic_position_source_documents": "doc_type",
        "atomic_positions": "asset_type currency geography sector",
        "atomic_transaction_identities": "currency identity_version",
        "atomic_transaction_source_documents": "doc_type",
        "atomic_transactions": "currency direction",
        "bank_custody_bindings": "currency",
        "chat_messages": "model_name role",
        "chat_sessions": "status",
        "consistency_checks": "check_type run_id severity status",
        "counter_tally": "key",
        "dividend_income": "currency dividend_type",
        "evidence_edges": "relation",
        "evidence_nodes": "entity_type node_kind",
        "fx_conversions": "currency_from currency_to fee_currency",
        "fx_rates": "base_currency quote_currency source",
        "investment_lots": "currency",
        "investment_transactions": "cost_basis_method currency transaction_type",
        "journal_audit_log": "action",
        "journal_entries": "base_currency source_type status",
        "journal_lines": "currency direction event_type",
        "llm_providers": "protocol",
        "llm_scene_bindings": "fallback_model_ids model reasoning scene",
        "managed_positions": "cost_basis_method currency status",
        "manual_valuation_snapshots": "component_type currency liquidity_class valuation_basis",
        "market_data_override": "currency source",
        "market_data_sync_state": "kind scope",
        "opening_position_records": "currency",
        "outbox": "aggregate_id event_type source_pkg status",
        "ping_state": "state",
        "reconciliation_matches": "run_id status",
        "report_snapshots": "report_type",
        "reviewed_statement_envelopes": "currency",
        "statement_extraction_results": "producer_version schema_version",
        "statement_price_observations": "currency subject_kind",
        "statement_summaries": "currency stage1_status status",
        "stock_prices": "currency source",
        "trace_record_parents": "scope_id",
        "trace_records": (
            "assertion_id assertion_kind assertion_owner_digest assertion_version "
            "authority_package authority_tier content_digest evidence_manifest_digest "
            "execution_id execution_stage producer_version proof_kind provenance "
            "reason_code schema_version scope_id target_id target_kind target_version"
        ),
        "transaction_classification": "status",
        "uploaded_documents": "document_type status",
        "users": "base_currency",
        "workflow_events": "action_href family report_impact severity source_type status",
        "workflow_sessions": "report_href status",
        "workflow_sync_states": "source_fingerprint",
    }
)

STRING_PSEUDONYM_COLUMNS: dict[str, str] = {
    **dict.fromkeys(
        _expand(
            {
                "accounts": "code description name",
                "app_config": "value",
                "atomic_positions": "broker",
                "atomic_transaction_identities": "custody_scope",
                "atomic_transactions": "description reference",
                "bank_custody_bindings": "institution",
                "chat_messages": "content",
                "chat_sessions": "title",
                "classification_rules": "rule_name",
                "consistency_checks": "resolution_note",
                "correction_logs": "corrected_category original_category transaction_description",
                "journal_audit_log": "actor",
                "journal_entries": "memo void_reason",
                "llm_providers": "api_base label",
                "manual_valuation_snapshots": "notes source",
                "reviewed_statement_envelopes": "rationale",
                "statement_summaries": "institution validation_error",
                "uploaded_documents": "file_path",
                "users": "name",
                "workflow_events": "summary title",
                "workflow_sessions": "summary title",
            }
        ),
        "generic",
    ),
    **dict.fromkeys(
        _expand(
            {
                "atomic_positions": "asset_identifier",
                "investment_lots": "asset_identifier",
                "investment_transactions": "asset_identifier",
                "managed_positions": "asset_identifier",
                "market_data_override": "asset_identifier",
                "statement_price_observations": "subject_key",
                "stock_prices": "symbol",
            }
        ),
        "asset",
    ),
    **dict.fromkeys(
        _expand(
            {
                "atomic_positions": "dedup_hash",
                "atomic_transactions": "dedup_hash",
                "atomic_transaction_identities": "identity_hash legacy_hash",
                "opening_position_records": "content_digest",
                "reviewed_statement_envelopes": "command_digest",
                "statement_extraction_results": "content_digest source_content_digest",
                "statement_summaries": "file_hash",
                "uploaded_documents": "file_hash",
                "workflow_events": "dedupe_key",
                "workflow_sessions": "dedupe_key",
            }
        ),
        "hash",
    ),
    "bank_custody_bindings.account_last4": "digits4",
    "statement_summaries.account_last4": "digits4",
    "uploaded_documents.original_filename": "filename",
    "users.email": "email",
}

SECRET_COLUMNS: frozenset[str] = frozenset({"llm_providers.api_key_ciphertext", "users.hashed_password"})

REDACTED_JSON = {"anonymized": True}
REDACTED_SECRET = "!anonymized"
_RESIDUAL_MIN_LENGTH = 3
_SHORT_DIGIT_MAX_LENGTH = 6


def _is_json_type(column_type: sa.types.TypeEngine) -> bool:
    return isinstance(column_type, sa.JSON) or type(column_type).__name__ in ("JSON", "JSONB")


def classify_columns(metadata: sa.MetaData) -> dict[str, Action]:
    """Classify every column of ``metadata``; raise on any unclassified one."""
    plan: dict[str, Action] = {}
    unclassified: list[str] = []
    for table in metadata.sorted_tables:
        for column in table.columns:
            key = f"{table.name}.{column.name}"
            ty = column.type
            if key in SECRET_COLUMNS:
                plan[key] = Action.REDACT_SECRET
            elif isinstance(ty, sa.Enum):
                plan[key] = Action.KEEP
            elif isinstance(ty, sa.Numeric):
                if key in MONEY_COLUMNS:
                    plan[key] = Action.SCALE
                elif key in NUMERIC_KEEP_COLUMNS:
                    plan[key] = Action.KEEP
                else:
                    unclassified.append(key)
            elif _is_json_type(ty):
                plan[key] = Action.KEEP if key in JSON_KEEP_COLUMNS else Action.REDACT_JSON
            elif isinstance(ty, sa.String | sa.Text):
                if key in STRING_KEEP_COLUMNS:
                    plan[key] = Action.KEEP
                elif key in STRING_PSEUDONYM_COLUMNS:
                    plan[key] = Action.PSEUDONYM
                else:
                    unclassified.append(key)
            else:
                plan[key] = Action.KEEP
    if unclassified:
        raise UnclassifiedColumnError(
            "Unclassified column(s) — classify them in snapshot_anonymizer.py "
            f"before any snapshot leaves prod (RL-DATA-2): {sorted(unclassified)}"
        )
    return plan


@lru_cache(maxsize=1)
def _digit_suffix_permutation(secret: str) -> dict[str, str]:
    key = secret.encode()
    ordered = sorted(
        (f"{number:04d}" for number in range(10000)),
        key=lambda value: hmac.new(key, f"account-suffix-v1:{value}".encode(), sha256).digest(),
    )
    return dict(zip(ordered, ordered[1:] + ordered[:1], strict=True))


def _pseudonym(secret: str, value: str, shape: str) -> str:
    digest = hmac.new(secret.encode(), value.encode(), sha256).hexdigest()
    if shape == "digits4":
        if len(value) != 4 or not value.isascii() or not value.isdigit():
            raise ValueError("Account suffix pseudonymization requires exactly four ASCII digits")
        return _digit_suffix_permutation(secret)[value]
    formats = {
        "email": f"user-{digest[:24]}@anonymized.invalid",
        "asset": f"AST{digest[:24].upper()}",
        "filename": f"doc-{digest[:24]}.pdf",
        "hash": digest,
    }
    return formats.get(shape, f"anon-{digest[:24]}")


@dataclass
class AnonymizationReport:
    """Counts recorded during an anonymization run."""

    scale_factor: int
    tables_updated: int = 0
    values_pseudonymized: int = 0
    json_redacted: int = 0
    residuals_scanned: int = 0
    original_values: set[str] = field(default_factory=set, repr=False)


def anonymize(
    conn: Connection,
    metadata: sa.MetaData,
    *,
    secret: str,
    scale_factor: int,
) -> AnonymizationReport:
    """Rewrite the connected scratch database in place per the classification plan."""
    if scale_factor < 2:
        raise ValueError("scale_factor must be an integer >= 2 (1 would keep real amounts)")
    plan = classify_columns(metadata)
    report = AnonymizationReport(scale_factor=scale_factor)
    for table in metadata.sorted_tables:
        conn.execute(sa.text(f'ALTER TABLE "{table.name}" DISABLE TRIGGER USER'))
    _transform(conn, metadata, plan, secret, scale_factor, report)
    for table in metadata.sorted_tables:
        conn.execute(sa.text(f'ALTER TABLE "{table.name}" ENABLE TRIGGER USER'))
    return report


def _transform(
    conn: Connection,
    metadata: sa.MetaData,
    plan: dict[str, Action],
    secret: str,
    scale_factor: int,
    report: AnonymizationReport,
) -> None:
    for table in metadata.sorted_tables:
        by_action: dict[Action, list[sa.Column[Any]]] = {
            action: [] for action in (Action.SCALE, Action.PSEUDONYM, Action.REDACT_JSON, Action.REDACT_SECRET)
        }
        for col in table.columns:
            act = plan[f"{table.name}.{col.name}"]
            if act in by_action:
                by_action[act].append(col)
        if not any(by_action.values()):
            continue
        report.tables_updated += 1
        if by_action[Action.SCALE]:
            conn.execute(table.update().values({c.name: c * scale_factor for c in by_action[Action.SCALE]}))
        for col in by_action[Action.REDACT_JSON]:
            report.json_redacted += conn.execute(table.update().where(col.isnot(None)).values({col.name: REDACTED_JSON})).rowcount or 0
        for col in by_action[Action.REDACT_SECRET]:
            conn.execute(table.update().where(col.isnot(None)).values({col.name: REDACTED_SECRET}))
        pseudo_cols = by_action[Action.PSEUDONYM]
        if pseudo_cols:
            pk_cols = list(table.primary_key.columns)
            shapes = {c.name: STRING_PSEUDONYM_COLUMNS[f"{table.name}.{c.name}"] for c in pseudo_cols}
            update_stmt = (
                table.update()
                .where(sa.and_(*(pk == sa.bindparam(f"b_{pk.name}") for pk in pk_cols)))
                .values({c.name: sa.bindparam(f"v_{c.name}") for c in pseudo_cols})
            )
            params: list[dict[str, object]] = []
            for row in conn.execute(sa.select(*pk_cols, *pseudo_cols)).mappings():
                row_params: dict[str, object] = {f"b_{pk.name}": row[pk.name] for pk in pk_cols}
                for col in pseudo_cols:
                    original = row[col.name]
                    if original is None or original == "":
                        row_params[f"v_{col.name}"] = original
                        continue
                    row_params[f"v_{col.name}"] = _pseudonym(secret, original, shapes[col.name])
                    if len(original) >= _RESIDUAL_MIN_LENGTH:
                        report.original_values.add(original)
                    report.values_pseudonymized += 1
                params.append(row_params)
            for chunk_start in range(0, len(params), 5000):
                conn.execute(update_stmt, params[chunk_start : chunk_start + 5000])


def _is_short_digit_original(value: str) -> bool:
    return len(value) <= _SHORT_DIGIT_MAX_LENGTH and value.isascii() and value.isdigit()


def _short_digit_regex(needles: list[str]) -> str:
    return f"(?<![0-9a-zA-Z])(?:{'|'.join(sorted(needles))})(?![0-9a-zA-Z])"


def _column_has_match(conn: Connection, table: sa.Table, target: sa.ColumnElement[str], needles: list[str], *, regex: bool) -> bool:
    for start in range(0, len(needles), 200):
        chunk = needles[start : start + 200]
        cond = target.op("~")(_short_digit_regex(chunk)) if regex else sa.or_(*(target.contains(n, autoescape=True) for n in chunk))
        if conn.execute(sa.select(sa.literal(1)).select_from(table).where(cond).limit(1)).scalar():
            return True
    return False


def scan_for_residuals(
    conn: Connection,
    metadata: sa.MetaData,
    original_values: set[str],
) -> list[str]:
    """Search every text/JSON column for any original sensitive value."""
    needles = sorted(v for v in original_values if len(v) >= _RESIDUAL_MIN_LENGTH)
    if not needles:
        return []
    substring_needles = [n for n in needles if not _is_short_digit_original(n)]
    short_digit_needles = [n for n in needles if _is_short_digit_original(n)]
    residuals: list[str] = []
    for table in metadata.sorted_tables:
        for column in table.columns:
            if not (isinstance(column.type, sa.String | sa.Text) or _is_json_type(column.type)):
                continue
            target = sa.cast(column, sa.Text)
            if (substring_needles and _column_has_match(conn, table, target, substring_needles, regex=False)) or (
                short_digit_needles and _column_has_match(conn, table, target, short_digit_needles, regex=True)
            ):
                residuals.append(f"{table.name}.{column.name}")
    return residuals
