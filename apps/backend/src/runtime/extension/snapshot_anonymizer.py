"""Prod-snapshot anonymizer — the data boundary of ``deploy(env, code, data)`` (#893).

RL-DATA-2 (``common/runtime/environments.md``): real data never leaves the prod
boundary un-anonymized. This module is the mechanism: it rewrites a *scratch
copy* of a prod database in place so the result is safe to load into
staging/rehearsal, then scans its own output for residuals and fails closed.

Design (deliberately minimal, #893):

- **Fail-closed classification.** Every column of the live model metadata must
  be explicitly classified (enums and non-text scalar types are structurally
  safe and auto-KEEP). An unclassified column aborts *before any data is
  read* — a future migration cannot silently leak a new PII column; it breaks
  the coverage test / the run instead.
- **One integer scale factor for all monetary columns.** Multiplying every
  money value by the same secret integer preserves double-entry balance,
  statement open+movement=close arithmetic, and price×quantity derivations
  *exactly* (no rounding), while real amounts do not survive. Quantities,
  FX rates, and ratios are deliberately untouched.
- **Deterministic pseudonyms.** Identity/content-bearing strings are replaced
  via HMAC(secret, value), so the same value maps to the same pseudonym across
  tables — cross-table join keys (e.g. ``atomic_positions.broker`` matching
  ``accounts.name``) stay consistent, and unique constraints stay unique.
- **JSON is redacted, not parsed.** Free-form JSON (extracted documents,
  report snapshots, audit payloads) is replaced with an ``{"anonymized": true}``
  marker; only structurally-safe JSON (UUID lists, score/count breakdowns) is
  kept. Parsing arbitrary document JSON to scrub it selectively is exactly the
  over-engineered path this module refuses.

Blob objects (uploaded statement files) are *not* handled here: the snapshot
pipeline never syncs object storage — non-prod environments hold synthetic
uploads only (RL-DATA-3).
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256

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
    SCALE = "scale"  # money only: value * integer factor, exact
    PSEUDONYM = "pseudonym"  # deterministic HMAC replacement, shape-aware
    REDACT_JSON = "redact_json"  # replaced with {"anonymized": true}
    REDACT_SECRET = "redact_secret"  # constant placeholder, never derivable


# ── Classification ──────────────────────────────────────────────────────────
# Money: every column that carries an amount in some currency. Scaling all of
# them by one integer keeps every cross-column derivation exact.
MONEY_COLUMNS: frozenset[str] = frozenset(
    {
        "atomic_positions.market_value",
        "atomic_transactions.amount",
        "atomic_transactions.balance_after",
        "dividend_income.amount",
        "fx_conversions.amount_from",
        "fx_conversions.amount_to",
        "fx_conversions.fee",
        "investment_lots.unit_cost",
        "investment_transactions.cost_basis",
        "investment_transactions.fees",
        "investment_transactions.gross_amount",
        "investment_transactions.realized_pnl",
        "investment_transactions.unit_price",
        "journal_lines.amount",
        "managed_positions.cost_basis",
        "managed_positions.realized_pnl",
        "managed_positions.unrealized_pnl",
        "manual_valuation_snapshots.value",
        "market_data_override.price",
        "statement_price_observations.value",
        "statement_summaries.closing_balance",
        "statement_summaries.manual_opening_balance",
        "statement_summaries.opening_balance",
        "stock_prices.price",
    }
)

# Quantities, FX rates, and ratios: scaling these would double-scale derived
# money (price×qty, amount×rate) or distort unitless metrics. Kept verbatim.
NUMERIC_KEEP_COLUMNS: frozenset[str] = frozenset(
    {
        "atomic_positions.quantity",
        "confidence_metric_snapshots.low_confidence_proportion",
        "fx_conversions.rate",
        "fx_rates.rate",
        "investment_lots.original_quantity",
        "investment_lots.remaining_quantity",
        "investment_transactions.quantity",
        "journal_lines.fx_rate",
        "managed_positions.quantity",
        # Assurance scores are unitless ratios. TraceRecord identity and digests
        # remain verifiable only when the snapshot preserves this exact value.
        "trace_records.score",
    }
)

# JSON that is structurally safe to keep: UUID id lists and numeric
# score/count breakdowns. Everything JSON that is not listed here is redacted.
JSON_KEEP_COLUMNS: frozenset[str] = frozenset(
    {
        "confidence_metric_snapshots.tier_breakdown",
        "consistency_checks.related_txn_ids",
        "reconciliation_matches.journal_entry_ids",
        "reconciliation_matches.score_breakdown",
    }
)

# Strings that are closed vocabularies, technical keys, currencies, or
# machine identifiers — no personal or document-derived content.
STRING_KEEP_COLUMNS: frozenset[str] = frozenset(
    {
        "accounts.currency",
        "accounts.type",
        "ai_feedback.action",
        "app_config.key",
        "atomic_position_source_documents.doc_type",
        "atomic_positions.asset_type",
        "atomic_positions.currency",
        "atomic_positions.geography",
        "atomic_positions.sector",
        "atomic_transaction_source_documents.doc_type",
        "atomic_transactions.currency",
        "atomic_transactions.direction",
        "chat_messages.model_name",
        "chat_messages.role",
        "chat_sessions.status",
        "consistency_checks.check_type",
        "consistency_checks.run_id",
        "consistency_checks.severity",
        "consistency_checks.status",
        "counter_tally.key",
        "dividend_income.currency",
        "dividend_income.dividend_type",
        "evidence_edges.relation",
        "evidence_nodes.entity_type",
        "evidence_nodes.node_kind",
        "fx_conversions.currency_from",
        "fx_conversions.currency_to",
        "fx_conversions.fee_currency",
        "fx_rates.base_currency",
        "fx_rates.quote_currency",
        "fx_rates.source",
        "investment_lots.currency",
        "investment_transactions.cost_basis_method",
        "investment_transactions.currency",
        "investment_transactions.transaction_type",
        "journal_audit_log.action",
        "journal_entries.source_type",
        "journal_entries.status",
        "journal_lines.currency",
        "journal_lines.direction",
        "journal_lines.event_type",
        "llm_providers.protocol",
        "llm_scene_bindings.fallback_model_ids",
        "llm_scene_bindings.model",
        "llm_scene_bindings.reasoning",
        "llm_scene_bindings.scene",
        "managed_positions.cost_basis_method",
        "managed_positions.currency",
        "managed_positions.status",
        "manual_valuation_snapshots.component_type",
        "manual_valuation_snapshots.currency",
        "manual_valuation_snapshots.liquidity_class",
        "manual_valuation_snapshots.valuation_basis",
        "market_data_override.currency",
        "market_data_override.source",
        "market_data_sync_state.kind",
        "market_data_sync_state.scope",
        "outbox.aggregate_id",
        "outbox.event_type",
        "outbox.source_pkg",
        "outbox.status",
        "ping_state.state",
        "reconciliation_matches.run_id",
        "reconciliation_matches.status",
        "report_snapshots.report_type",
        "statement_price_observations.currency",
        "statement_price_observations.subject_kind",
        "statement_summaries.currency",
        "statement_summaries.stage1_status",
        "statement_summaries.status",
        "stock_prices.currency",
        "stock_prices.source",
        # TraceRecord contains only closed vocabulary, code-owned identifiers,
        # digests, versions, and opaque composition-boundary ids. Raw document,
        # user, and financial payloads are forbidden by the audit contract.
        # Keeping these fields preserves record/content digests and parent graph
        # verification in an anonymized snapshot.
        "trace_record_parents.scope_id",
        "trace_records.assertion_id",
        "trace_records.assertion_kind",
        "trace_records.assertion_owner_digest",
        "trace_records.assertion_version",
        "trace_records.authority_package",
        "trace_records.authority_tier",
        "trace_records.content_digest",
        "trace_records.evidence_manifest_digest",
        "trace_records.execution_id",
        "trace_records.execution_stage",
        "trace_records.producer_version",
        "trace_records.proof_kind",
        "trace_records.provenance",
        "trace_records.reason_code",
        "trace_records.schema_version",
        "trace_records.scope_id",
        "trace_records.target_id",
        "trace_records.target_kind",
        "trace_records.target_version",
        "transaction_classification.status",
        "uploaded_documents.document_type",
        "uploaded_documents.status",
        "workflow_events.action_href",
        "workflow_events.family",
        "workflow_events.report_impact",
        "workflow_events.severity",
        "workflow_events.source_type",
        "workflow_events.status",
        "workflow_sessions.report_href",
        "workflow_sessions.status",
    }
)

# Identity- or content-bearing strings: replaced with deterministic pseudonyms.
# The optional shape keeps app-level format expectations (emails stay emails,
# last4 stays 4 digits) without preserving any original content.
STRING_PSEUDONYM_COLUMNS: dict[str, str] = {
    "accounts.code": "generic",
    "accounts.description": "generic",
    "accounts.name": "generic",
    "app_config.value": "generic",
    "atomic_positions.asset_identifier": "asset",
    "atomic_positions.broker": "generic",
    "atomic_positions.dedup_hash": "hash",
    "atomic_transactions.dedup_hash": "hash",
    "atomic_transactions.description": "generic",
    "atomic_transactions.reference": "generic",
    "chat_messages.content": "generic",
    "chat_sessions.title": "generic",
    "classification_rules.rule_name": "generic",
    "consistency_checks.resolution_note": "generic",
    "correction_logs.corrected_category": "generic",
    "correction_logs.original_category": "generic",
    "correction_logs.transaction_description": "generic",
    "investment_lots.asset_identifier": "asset",
    "investment_transactions.asset_identifier": "asset",
    "journal_audit_log.actor": "generic",
    "journal_entries.memo": "generic",
    "journal_entries.void_reason": "generic",
    "llm_providers.api_base": "generic",
    "llm_providers.label": "generic",
    "managed_positions.asset_identifier": "asset",
    "manual_valuation_snapshots.notes": "generic",
    "manual_valuation_snapshots.source": "generic",
    "market_data_override.asset_identifier": "asset",
    "statement_price_observations.subject_key": "asset",
    "statement_summaries.account_last4": "digits4",
    "statement_summaries.file_hash": "hash",
    "statement_summaries.institution": "generic",
    "statement_summaries.validation_error": "generic",
    "stock_prices.symbol": "asset",
    "uploaded_documents.file_hash": "hash",
    "uploaded_documents.file_path": "generic",
    "uploaded_documents.original_filename": "filename",
    "users.email": "email",
    "users.name": "generic",
    "workflow_events.dedupe_key": "hash",
    "workflow_events.summary": "generic",
    "workflow_events.title": "generic",
    "workflow_sessions.dedupe_key": "hash",
    "workflow_sessions.summary": "generic",
    "workflow_sessions.title": "generic",
}

# Secrets: replaced with a constant unusable placeholder — a pseudonym would
# still admit "this row had a secret of that shape", a constant admits nothing.
SECRET_COLUMNS: frozenset[str] = frozenset(
    {
        "llm_providers.api_key_ciphertext",
        "users.hashed_password",
    }
)

REDACTED_JSON = {"anonymized": True}
REDACTED_SECRET = "!anonymized"

#: Residual scanning ignores values shorter than this — a 1-2 character
#: original (an account code like "01") appears legitimately everywhere and
#: would only produce false positives, while carrying no real information.
_RESIDUAL_MIN_LENGTH = 3


def _is_json_type(column_type: sa.types.TypeEngine) -> bool:
    return isinstance(column_type, sa.JSON) or type(column_type).__name__ in ("JSON", "JSONB")


def classify_columns(metadata: sa.MetaData) -> dict[str, Action]:
    """Classify every column of ``metadata``; raise on any unclassified one.

    This is the fail-closed core (#893 G-classification): a migration that adds
    a column without classifying it here makes this function — and therefore
    the coverage test and every anonymization run — fail before data is read.
    """
    plan: dict[str, Action] = {}
    unclassified: list[str] = []
    for table in metadata.sorted_tables:
        for column in table.columns:
            key = f"{table.name}.{column.name}"
            ty = column.type
            if key in SECRET_COLUMNS:
                plan[key] = Action.REDACT_SECRET
            elif isinstance(ty, sa.Enum):
                # Closed vocabulary owned by code — structurally safe.
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
                # UUIDs, dates, booleans, integers-as-counters, intervals:
                # structurally safe scalar types.
                plan[key] = Action.KEEP
    if unclassified:
        raise UnclassifiedColumnError(
            "Unclassified column(s) — classify them in snapshot_anonymizer.py "
            f"before any snapshot leaves prod (RL-DATA-2): {sorted(unclassified)}"
        )
    return plan


def _pseudonym(secret: str, value: str, shape: str) -> str:
    # 24 hex chars = 96 bits: collision probability stays negligible far past
    # any realistic snapshot size, so HMAC-derived pseudonyms keep unique
    # constraints unique. "digits4" is deliberately lossy — account_last4 is
    # display-only and carries no uniqueness contract.
    digest = hmac.new(secret.encode(), value.encode(), sha256).hexdigest()
    if shape == "email":
        return f"user-{digest[:24]}@anonymized.invalid"
    if shape == "digits4":
        return f"{int(digest[:8], 16) % 10000:04d}"
    if shape == "asset":
        return f"AST{digest[:24].upper()}"
    if shape == "filename":
        return f"doc-{digest[:24]}.pdf"
    if shape == "hash":
        return digest
    return f"anon-{digest[:24]}"


@dataclass
class AnonymizationReport:
    """What a run did — counts only, never values."""

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
    """Rewrite the connected database in place per the classification plan.

    The caller owns the transaction (commit after :func:`scan_for_residuals`
    passes, roll back otherwise) and MUST be connected to a scratch copy,
    never the production database itself.
    """
    if scale_factor < 2:
        raise ValueError("scale_factor must be an integer >= 2 (1 would keep real amounts)")
    plan = classify_columns(metadata)
    report = AnonymizationReport(scale_factor=scale_factor)

    # The ledger's append-only protection (Axiom A) is enforced by DB triggers
    # that reject UPDATEs to posted entries. That guarantee protects the LIVE
    # system; this transform rewrites a scratch copy wholesale, so user
    # triggers are suspended for the duration (table-owner privilege — no
    # superuser needed) and restored before returning.
    # ALTER TABLE is transactional in PostgreSQL: if the transform raises, the
    # caller's rollback restores the triggers along with the data, so they are
    # re-enabled explicitly only on the success path (a finally-block re-enable
    # would run inside an aborted transaction and mask the real error).
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
        scale_cols = [c for c in table.columns if plan[f"{table.name}.{c.name}"] is Action.SCALE]
        pseudo_cols = [c for c in table.columns if plan[f"{table.name}.{c.name}"] is Action.PSEUDONYM]
        json_cols = [c for c in table.columns if plan[f"{table.name}.{c.name}"] is Action.REDACT_JSON]
        secret_cols = [c for c in table.columns if plan[f"{table.name}.{c.name}"] is Action.REDACT_SECRET]
        if not (scale_cols or pseudo_cols or json_cols or secret_cols):
            continue
        report.tables_updated += 1

        if scale_cols:
            conn.execute(table.update().values({c.name: c * scale_factor for c in scale_cols}))
        for c in json_cols:
            result = conn.execute(table.update().where(c.isnot(None)).values({c.name: REDACTED_JSON}))
            report.json_redacted += result.rowcount or 0
        for c in secret_cols:
            conn.execute(table.update().where(c.isnot(None)).values({c.name: REDACTED_SECRET}))

        if pseudo_cols:
            # One narrow read (pk + pseudonym columns only) and batched
            # executemany UPDATEs — never one round-trip per row. Memory is
            # bounded by the pseudonym payload, which the residual scan must
            # retain anyway (report.original_values), so a server-side cursor
            # would buy nothing here — and an open cursor in this transaction
            # would block the ENABLE TRIGGER statements below.
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
                for c in pseudo_cols:
                    original = row[c.name]
                    if original is None or original == "":
                        row_params[f"v_{c.name}"] = original
                        continue
                    row_params[f"v_{c.name}"] = _pseudonym(secret, original, shapes[c.name])
                    if len(original) >= _RESIDUAL_MIN_LENGTH:
                        report.original_values.add(original)
                    report.values_pseudonymized += 1
                params.append(row_params)
            for chunk_start in range(0, len(params), 5000):
                conn.execute(update_stmt, params[chunk_start : chunk_start + 5000])


def scan_for_residuals(
    conn: Connection,
    metadata: sa.MetaData,
    original_values: set[str],
) -> list[str]:
    """Search every text/JSON column for any original sensitive value.

    Returns residual locations as ``table.column`` strings (values are never
    echoed). The pipeline must treat a non-empty result as fatal and roll the
    snapshot back (fail closed) — see :class:`ResidualError`.

    Cost envelope: needles are the DISTINCT pseudonymized originals (min
    length 3), OR-batched 200 per query with a LIMIT 1 short-circuit. This is
    an offline, once-per-snapshot verification on a scratch database of a
    personal-finance instance — completeness is the requirement here, not
    latency; trading scan coverage for speed would hollow out the guarantee
    (Good Taste 5).
    """
    needles = sorted(v for v in original_values if len(v) >= _RESIDUAL_MIN_LENGTH)
    if not needles:
        return []
    residuals: list[str] = []
    for table in metadata.sorted_tables:
        for column in table.columns:
            ty = column.type
            if not (isinstance(ty, sa.String | sa.Text) or _is_json_type(ty)):
                continue
            target = sa.cast(column, sa.Text)
            for chunk_start in range(0, len(needles), 200):
                chunk = needles[chunk_start : chunk_start + 200]
                hit = conn.execute(
                    sa.select(sa.literal(1))
                    .select_from(table)
                    .where(sa.or_(*(target.contains(n, autoescape=True) for n in chunk)))
                    .limit(1)
                ).scalar()
                if hit:
                    residuals.append(f"{table.name}.{column.name}")
                    break
    return residuals
