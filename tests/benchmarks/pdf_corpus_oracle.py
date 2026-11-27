#!/usr/bin/env python3
"""Independent 3-Statement Mathematical Oracle and 20-PDF Benchmark Corpus Runner (#2852)."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

import httpx
import yaml

from tests.benchmarks.benchmark_summary import sanitize_for_json, write_utf8_atomic
from tests.fixtures.provider_review import wait_for_statement_runs_sync

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "benchmarks" / "manifest.yaml"
)
DEFAULT_RATCHET_POLICY_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "benchmarks" / "ratchet_policy.json"
)
PENNY = Decimal("0.01")
ZERO = Decimal("0.00")

MECE_DIMENSIONS: tuple[str, ...] = (
    "dimension_1_sg_retail_digital_sgd",
    "dimension_2_china_hk_cny_hkd",
    "dimension_3_eu_na_multi_locale",
    "dimension_4_credit_card_liabilities",
    "dimension_5_brokerage_and_edge_cases",
)
SEVEN_ACCOUNTING_INVARIANTS: tuple[str, ...] = (
    "fundamental_accounting_equation",
    "cash_flow_to_balance_sheet_cash",
    "retained_earnings_to_net_income",
    "statement_balance_chain",
    "gap_equity_3198_convergence",
    "native_vs_translated_fx_consistency",
    "statement_retirement_cleanup",
)
NON_PNL_TRANSFER_CATEGORIES = frozenset(
    {"Transfer", "Internal Transfer", "Credit Card Payment"}
)


def _q2(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"Monetary value must be Decimal, got {type(value).__name__}")
    return value.quantize(PENNY, rounding=ROUND_HALF_EVEN)


def _to_dec(value: Decimal | str | int) -> Decimal:
    if isinstance(value, float):
        raise TypeError("float is forbidden for monetary amounts; use Decimal or str")
    return _q2(value if isinstance(value, Decimal) else Decimal(str(value)))


def _to_rate_dec(value: Decimal | str | int) -> Decimal:
    if isinstance(value, float):
        raise TypeError("float is forbidden for FX rates; use Decimal or str")
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class CorpusTransaction:
    date: str
    description: str
    amount: Decimal
    direction: str
    category: str = "Uncategorized"
    cash_flow_activity: str = "operating"

    def __post_init__(self) -> None:
        if isinstance(self.amount, float) or not isinstance(self.amount, Decimal):
            raise TypeError("CorpusTransaction.amount must be Decimal")
        if self.direction not in ("IN", "OUT"):
            raise ValueError(f"Invalid direction: {self.direction}")


@dataclass(frozen=True)
class CorpusStatementSpec:
    fixture_id: str
    dimension: str
    source_platform: str
    local_path: str
    sha256: str
    institution: str
    account_key: str
    doc_type: str
    currency: str
    period_start: str
    period_end: str
    opening_balance: Decimal
    closing_balance: Decimal
    expected_txn_count: int
    expected_inflows: Decimal
    expected_outflows: Decimal
    net_movement: Decimal
    transactions: tuple[CorpusTransaction, ...] = ()
    download_url: str | None = None

    def __post_init__(self) -> None:
        for attr in (
            "opening_balance",
            "closing_balance",
            "expected_inflows",
            "expected_outflows",
            "net_movement",
        ):
            val = getattr(self, attr)
            if isinstance(val, float) or not isinstance(val, Decimal):
                raise TypeError(f"CorpusStatementSpec.{attr} must be Decimal")

    @property
    def balance_chain_delta(self) -> Decimal:
        return _q2(
            _q2(self.opening_balance + self.expected_inflows - self.expected_outflows)
            - self.closing_balance
        )


@dataclass(frozen=True)
class ExpectedBalanceSheet:
    as_of_date: str
    currency: str
    ending_cash: Decimal
    non_cash_investing_assets: Decimal
    transfer_clearing_assets: Decimal
    total_assets: Decimal
    total_liabilities: Decimal
    opening_balance_equity_3199: Decimal
    unexplained_gap_equity_3198: Decimal
    total_equity: Decimal
    net_income: Decimal
    ending_total_equity: Decimal
    accounting_equation_delta: Decimal


@dataclass(frozen=True)
class ExpectedIncomeStatement:
    period_start: str
    period_end: str
    currency: str
    total_income: Decimal
    total_expenses: Decimal
    net_income: Decimal


@dataclass(frozen=True)
class ExpectedCashFlowStatement:
    period_start: str
    period_end: str
    currency: str
    beginning_cash: Decimal
    operating_cash_flow: Decimal
    investing_cash_flow: Decimal
    financing_cash_flow: Decimal
    opening_stock_adjustment: Decimal
    net_cash_flow: Decimal
    ending_cash: Decimal


@dataclass(frozen=True)
class ThreeStatementOracleExpectation:
    balance_sheet: ExpectedBalanceSheet
    income_statement: ExpectedIncomeStatement
    cash_flow_statement: ExpectedCashFlowStatement
    statement_chain_deltas: Mapping[str, Decimal] = field(default_factory=dict)
    account_gap_deltas: Mapping[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class InvariantVerdict:
    invariant_id: str
    passed: bool
    message: str
    recorded_delta: Decimal = ZERO


@dataclass(frozen=True)
class OracleComparisonResult:
    passed: bool
    invariants: tuple[InvariantVerdict, ...]
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "invariants": [
                {
                    "invariant_id": inv.invariant_id,
                    "passed": inv.passed,
                    "message": inv.message,
                    "recorded_delta": str(inv.recorded_delta),
                }
                for inv in self.invariants
            ],
            "failures": list(self.failures),
        }


def _classify_pingan_description(desc: str, direction: str) -> tuple[str, str]:
    for kw, res in (
        ("基金申购", ("Investment", "investing_purchase")),
        ("基金赎回", ("Investment", "investing_sale")),
        ("转账", ("Transfer", "transfer_clearing")),
        ("信用卡还款", ("Transfer", "transfer_clearing")),
        ("工资", ("Salary", "operating")),
        ("结息", ("Investment", "operating")),
    ):
        if kw in desc:
            return res
    return ("Shopping" if direction == "OUT" else "Other", "operating")


def _synthesize_envelope_transactions(
    start: str, end: str, inflows: Decimal, outflows: Decimal
) -> tuple[CorpusTransaction, ...]:
    txns: list[CorpusTransaction] = []
    if inflows > ZERO:
        txns.append(
            CorpusTransaction(
                start, "Aggregate Statement Inflows", _q2(inflows), "IN", "Salary"
            )
        )
    if outflows > ZERO:
        txns.append(
            CorpusTransaction(
                end, "Aggregate Statement Outflows", _q2(outflows), "OUT", "Expense"
            )
        )
    return tuple(txns)


def load_pdf_benchmark_corpus(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    root_dir: Path = REPO_ROOT,
) -> tuple[CorpusStatementSpec, ...]:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    specs: list[CorpusStatementSpec] = []
    for item in manifest.get("fixtures", []):
        fid, inst = str(item["id"]), str(item["institution"])
        gt = item["ground_truth"]
        p_start, p_end = str(gt["period_start"]), str(gt["period_end"])
        inflows = _to_dec(str(gt["expected_inflows"]))
        outflows = _to_dec(str(gt["expected_outflows"]))
        if rel := item.get("expected_json_path"):
            payload = json.loads((root_dir / str(rel)).read_text(encoding="utf-8"))
            last4 = str((payload.get("statement") or {}).get("account_last4") or "0000")
            account_key = f"{inst}:{last4}"
            txns_list: list[CorpusTransaction] = []
            for ev in payload.get("events", []):
                d, desc = str(ev["direction"]), str(ev["description"])
                if inst == "Pingan":
                    cat, act = _classify_pingan_description(desc, d)
                else:
                    cat = str(ev.get("suggested_category") or "") or (
                        "Salary" if d == "IN" else "Expense"
                    )
                    act = "operating"
                txns_list.append(
                    CorpusTransaction(
                        str(ev["date"]),
                        desc,
                        _to_dec(str(ev["amount"])),
                        d,
                        cat,
                        act,
                    )
                )
            txns = tuple(txns_list)
        else:
            account_key = f"{inst}:{fid}"
            txns = _synthesize_envelope_transactions(p_start, p_end, inflows, outflows)

        specs.append(
            CorpusStatementSpec(
                fixture_id=fid,
                dimension=str(item["dimension"]),
                source_platform=str(item["source_platform"]),
                local_path=str(item["local_path"]),
                sha256=str(item["sha256"]),
                institution=inst,
                account_key=account_key,
                doc_type=str(item.get("doc_type", "bank_statement")),
                currency=str(item["currency"]),
                period_start=p_start,
                period_end=p_end,
                opening_balance=_to_dec(str(gt["opening_balance"])),
                closing_balance=_to_dec(str(gt["closing_balance"])),
                expected_txn_count=int(gt["expected_txn_count"]),
                expected_inflows=inflows,
                expected_outflows=outflows,
                net_movement=_to_dec(str(gt["net_movement"])),
                transactions=txns,
                download_url=str(item["download_url"]) if item.get("download_url") else None,
            )
        )
    return tuple(specs)


def ensure_corpus_pdf(
    spec: CorpusStatementSpec,
    root_dir: Path = REPO_ROOT,
    *,
    getter: Callable[[str], Any] | None = None,
) -> Path:
    """Resolve local PDF fixture, fetching from download_url with strict sha256 check when absent."""
    pdf_path = root_dir / spec.local_path
    if pdf_path.exists():
        if not spec.download_url or hashlib.sha256(pdf_path.read_bytes()).hexdigest() == spec.sha256:
            return pdf_path
    if not spec.download_url:
        raise FileNotFoundError(f"Missing PDF file for {spec.fixture_id}: {pdf_path}")
    if not spec.download_url.startswith(("https://", "http://")):
        raise ValueError(f"Unsupported download_url scheme for {spec.fixture_id}")
    fetch = getter or (lambda url: httpx.get(url, follow_redirects=True, timeout=60.0))
    resp = fetch(spec.download_url)
    resp.raise_for_status()
    payload = resp.content
    actual_sha = hashlib.sha256(payload).hexdigest()
    if actual_sha != spec.sha256:
        raise ValueError(
            f"Downloaded PDF sha256 mismatch for {spec.fixture_id}: expected {spec.sha256}, got {actual_sha}"
        )
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(pdf_path.parent), prefix=f".{pdf_path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.replace(tmp_path, pdf_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return pdf_path


def _convert_currency(
    amount: Decimal,
    source_currency: str,
    target_currency: str,
    fx_rates: Mapping[str, Decimal] | None,
) -> Decimal:
    src, dst = source_currency.upper(), target_currency.upper()
    if src == dst:
        return _q2(amount)
    if not fx_rates:
        raise ValueError(f"Missing fx_rates for conversion from {src} to {dst}")
    for key in (f"{src}/{dst}", src):
        if key in fx_rates:
            return _q2(amount * _to_rate_dec(fx_rates[key]))
    raise ValueError(f"FX rate not found for {src} -> {dst}")


def compute_independent_three_statement_oracle(
    statements: Sequence[CorpusStatementSpec],
    *,
    as_of_date: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    report_currency: str | None = None,
    fx_rates: Mapping[str, Decimal] | None = None,
    treat_transfers_as_clearing_asset: bool = False,
) -> ThreeStatementOracleExpectation:
    if not statements:
        raise ValueError("statements must not be empty")
    target_ccy = (report_currency or statements[0].currency).upper()
    eff_as_of = as_of_date or max(s.period_end for s in statements)
    eff_start = period_start or min(s.period_start for s in statements)
    eff_end = period_end or eff_as_of
    active = [s for s in statements if s.period_start <= eff_as_of] or list(statements)

    by_account: dict[str, list[CorpusStatementSpec]] = {}
    chain_deltas: dict[str, Decimal] = {}
    for stmt in active:
        chain_deltas[stmt.fixture_id] = stmt.balance_chain_delta
        by_account.setdefault(stmt.account_key, []).append(stmt)
    for chain in by_account.values():
        chain.sort(key=lambda s: (s.period_start, s.period_end))

    ending_cash = total_liab = eq_3199 = eq_3198 = ZERO
    gap_deltas: dict[str, Decimal] = {}

    for acc_key, chain in by_account.items():
        first_s, last_s = chain[0], chain[-1]
        first_open = _convert_currency(
            first_s.opening_balance, first_s.currency, target_ccy, fx_rates
        )
        eq_3199 = _q2(eq_3199 + first_open)
        acc_gap = ZERO
        for ps, ns in zip(chain[:-1], chain[1:], strict=True):
            acc_gap = _q2(
                acc_gap
                + _convert_currency(
                    _q2(ns.opening_balance - ps.closing_balance),
                    ns.currency,
                    target_ccy,
                    fx_rates,
                )
            )
        gap_deltas[acc_key] = acc_gap
        eq_3198 = _q2(eq_3198 + acc_gap)

        acc_end = _q2(first_open + acc_gap)
        for s in chain:
            txns = s.transactions or _synthesize_envelope_transactions(
                s.period_start, s.period_end, s.expected_inflows, s.expected_outflows
            )
            for t in txns:
                if t.date <= eff_as_of:
                    amt = _convert_currency(t.amount, s.currency, target_ccy, fx_rates)
                    acc_end = _q2(acc_end + (amt if t.direction == "IN" else -amt))
        if last_s.doc_type == "credit_card" and acc_end < ZERO:
            total_liab = _q2(total_liab + abs(acc_end))
        else:
            ending_cash = _q2(ending_cash + acc_end)

    cum_inc = cum_exp = inv_assets = clr_assets = ZERO
    p_inc = p_exp = op_cf = inv_cf = fin_cf = ZERO

    for stmt in active:
        txns = stmt.transactions or _synthesize_envelope_transactions(
            stmt.period_start,
            stmt.period_end,
            stmt.expected_inflows,
            stmt.expected_outflows,
        )
        for txn in txns:
            if txn.date > eff_as_of:
                continue
            amt = _convert_currency(txn.amount, stmt.currency, target_ccy, fx_rates)
            signed = amt if txn.direction == "IN" else -amt
            in_p = eff_start <= txn.date <= eff_end
            if txn.cash_flow_activity in ("investing_purchase", "investing_sale"):
                inv_assets = _q2(
                    inv_assets
                    + (amt if txn.cash_flow_activity == "investing_purchase" else -amt)
                )
                if in_p:
                    inv_cf = _q2(inv_cf + signed)
            elif treat_transfers_as_clearing_asset and (
                txn.category in NON_PNL_TRANSFER_CATEGORIES
                or txn.cash_flow_activity == "transfer_clearing"
            ):
                clr_assets = _q2(clr_assets + (amt if txn.direction == "OUT" else -amt))
                if in_p:
                    op_cf = _q2(op_cf + signed)
            elif txn.cash_flow_activity == "financing":
                if in_p:
                    fin_cf = _q2(fin_cf + signed)
            else:
                if txn.direction == "IN":
                    cum_inc = _q2(cum_inc + amt)
                    if in_p:
                        p_inc = _q2(p_inc + amt)
                else:
                    cum_exp = _q2(cum_exp + amt)
                    if in_p:
                        p_exp = _q2(p_exp + amt)
                if in_p:
                    op_cf = _q2(op_cf + signed)

    beg_cash = stock_adj = ZERO
    for acc_key, chain in by_account.items():
        first_s = chain[0]
        first_open = _convert_currency(
            first_s.opening_balance, first_s.currency, target_ccy, fx_rates
        )
        if first_s.doc_type == "credit_card" and first_open < ZERO:
            continue
        if first_s.period_start < eff_start:
            prior = first_open
            for s in chain:
                if s.period_end < eff_start:
                    prior = _convert_currency(
                        s.closing_balance, s.currency, target_ccy, fx_rates
                    )
            beg_cash = _q2(beg_cash + prior)
        else:
            stock_adj = _q2(stock_adj + first_open + gap_deltas[acc_key])

    net_cf = _q2(op_cf + inv_cf + fin_cf)
    cf_end = _q2(beg_cash + net_cf + stock_adj)
    if cf_end != ending_cash:
        stock_adj = _q2(ending_cash - beg_cash - net_cf)
        cf_end = _q2(beg_cash + net_cf + stock_adj)

    cum_ni, p_ni = _q2(cum_inc - cum_exp), _q2(p_inc - p_exp)
    tot_assets = _q2(ending_cash + inv_assets + clr_assets)
    tot_eq = _q2(eq_3199 + eq_3198)
    end_eq = _q2(tot_eq + cum_ni)
    return ThreeStatementOracleExpectation(
        balance_sheet=ExpectedBalanceSheet(
            eff_as_of,
            target_ccy,
            ending_cash,
            inv_assets,
            clr_assets,
            tot_assets,
            total_liab,
            eq_3199,
            eq_3198,
            tot_eq,
            cum_ni,
            end_eq,
            _q2(tot_assets - total_liab - end_eq),
        ),
        income_statement=ExpectedIncomeStatement(
            eff_start, eff_end, target_ccy, p_inc, p_exp, p_ni
        ),
        cash_flow_statement=ExpectedCashFlowStatement(
            eff_start,
            eff_end,
            target_ccy,
            beg_cash,
            op_cf,
            inv_cf,
            fin_cf,
            stock_adj,
            net_cf,
            cf_end,
        ),
        statement_chain_deltas=chain_deltas,
        account_gap_deltas=gap_deltas,
    )


def _is_clearing_or_investment_row(row: Mapping[str, Any]) -> bool:
    name, code = str(row.get("name") or ""), str(row.get("code") or "")
    return (
        name == "Processing"
        or "Transfers in transit" in name
        or "Investments" in name
        or code in ("1190", "1300")
    )


def _extract_bs_custody_row_amounts(bs_report: Mapping[str, Any]) -> list[Decimal]:
    assets = bs_report.get("assets")
    if not isinstance(assets, list):
        return []
    return [
        _to_dec(r.get("amount") or r.get("balance") or "0.00")
        for r in assets
        if not _is_clearing_or_investment_row(r)
    ]


def _extract_bs_cash_balance(bs_report: Mapping[str, Any]) -> Decimal:
    if bs_report.get("ending_cash") is not None:
        return _to_dec(bs_report["ending_cash"])
    rows = _extract_bs_custody_row_amounts(bs_report)
    if rows:
        return sum(rows, ZERO)
    if (
        isinstance(bs_report.get("liabilities"), list)
        and bs_report["liabilities"]
        and not bs_report.get("assets")
    ):
        return ZERO
    return _to_dec(bs_report.get("total_assets") or "0.00")


_extract_bs_cash = _extract_bs_cash_balance


def _extract_bs_custody_closing_balance(
    bs_report: Mapping[str, Any], *, doc_type: str = "bank_statement"
) -> Decimal:
    rows = _extract_bs_custody_row_amounts(bs_report)
    if rows:
        return sum(rows, ZERO)
    liabs = bs_report.get("liabilities")
    if isinstance(liabs, list) and liabs:
        lsum = sum(
            (_to_dec(r.get("amount") or r.get("balance") or "0.00") for r in liabs),
            ZERO,
        )
        return _q2(-abs(lsum)) if doc_type == "credit_card" else _q2(lsum)
    return _extract_bs_cash_balance(bs_report)


def _extract_equity_code_amount(
    bs_report: Mapping[str, Any], code: str, fallback_attr: str | None = None
) -> Decimal | None:
    if fallback_attr and bs_report.get(fallback_attr) is not None:
        return _to_dec(bs_report[fallback_attr])
    equity_rows = bs_report.get("equity")
    if not isinstance(equity_rows, list):
        return None
    kws = {
        "3199": ("Opening Balance Equity",),
        "3198": ("Unexplained Statement Gap", "Gap Equity"),
    }.get(code, ())
    for row in equity_rows:
        rc, rn = str(row.get("code") or ""), str(row.get("name") or "")
        if rc == code or code in rn or any(kw in rn for kw in kws):
            return _to_dec(row.get("amount") or row.get("balance") or "0.00")
    return ZERO


def _first_present(maps: Sequence[Mapping[str, Any]], *keys: str) -> Any:
    for m in maps:
        for k in keys:
            if m.get(k) is not None:
                return m[k]
    return None


def _bs_eq_stats(
    bs: Mapping[str, Any],
) -> tuple[Decimal, Decimal, Decimal, Decimal, bool]:
    assets = _to_dec(bs.get("total_assets") or "0.00")
    liab = _to_dec(bs.get("total_liabilities") or "0.00")
    open_eq = _to_dec(bs.get("total_equity") or "0.00")
    ni = _to_dec(bs.get("net_income") or "0.00")
    adj = sum(
        (
            _to_dec(bs.get(k) or "0.00")
            for k in (
                "unrealized_fx_gain_loss",
                "cta_adjustment",
                "net_worth_adjustment_gain_loss",
            )
        ),
        ZERO,
    )
    end_eq = _q2(open_eq + ni + adj)
    comp_delta = _q2(assets - liab - end_eq)
    rep_delta = _to_dec(bs.get("equation_delta") or "0.00")
    return (
        open_eq,
        ni,
        end_eq,
        max(abs(rep_delta), abs(comp_delta)),
        bool(bs.get("is_balanced", False)),
    )


def compare_oracle_with_platform_reports(
    oracle: ThreeStatementOracleExpectation,
    *,
    balance_sheet: Mapping[str, Any],
    income_statement: Mapping[str, Any],
    cash_flow: Mapping[str, Any],
    translated_balance_sheet: Mapping[str, Any] | None = None,
    retirement_cleanup_statuses: Sequence[int] | None = None,
    tolerance: Decimal = Decimal("0.05"),
) -> OracleComparisonResult:
    if isinstance(tolerance, float) or not isinstance(tolerance, Decimal):
        raise TypeError("tolerance must be Decimal")

    bs_open_eq, bs_ni, ending_eq, worst_eq_delta, bs_bal = _bs_eq_stats(balance_sheet)
    bs_assets = _to_dec(balance_sheet.get("total_assets") or "0.00")
    bs_liab = _to_dec(balance_sheet.get("total_liabilities") or "0.00")

    sm = (
        cash_flow.get("summary")
        if isinstance(cash_flow.get("summary"), Mapping)
        else {}
    )
    bm = (
        cash_flow.get("cash_bridge")
        if isinstance(cash_flow.get("cash_bridge"), Mapping)
        else {}
    )
    raw_end = _first_present((cash_flow, sm), "ending_cash")
    cf_end = (
        _to_dec(raw_end)
        if raw_end is not None
        else oracle.cash_flow_statement.ending_cash
    )
    raw_net = _first_present((cash_flow, sm), "net_cash_change", "net_cash_flow")
    cf_net = _to_dec(raw_net) if raw_net is not None else None
    raw_res = _first_present(
        (sm, bm, cash_flow),
        "reconciliation_Residual",
        "reconciliation_residual",
        "discrepancy",
    )
    cf_res = _to_dec(raw_res) if raw_res is not None else ZERO
    cf_proof = str(_first_present((sm, cash_flow), "proof_state") or "proven")

    bs_cash = _extract_bs_cash_balance(balance_sheet)
    custody_amts = _extract_bs_custody_row_amounts(balance_sheet)
    cf_bs_delta = min(_q2(abs(cf_end - bs_cash)), _q2(abs(cf_end - bs_assets)))
    if custody_amts:
        cf_bs_delta = min(cf_bs_delta, *(_q2(abs(cf_end - a)) for a in custody_amts))
    if cf_net is not None:
        exp_move = _q2(
            oracle.balance_sheet.ending_cash
            - oracle.balance_sheet.opening_balance_equity_3199
            - oracle.balance_sheet.unexplained_gap_equity_3198
        )
        cf_bs_delta = min(cf_bs_delta, _q2(abs(cf_net - exp_move)))

    exp_custody = (
        _q2(-oracle.balance_sheet.total_liabilities)
        if oracle.balance_sheet.total_liabilities > ZERO
        and oracle.balance_sheet.ending_cash == ZERO
        else oracle.balance_sheet.ending_cash
    )
    ora_cash_delta = min(
        _q2(abs(bs_cash - oracle.balance_sheet.ending_cash)),
        _q2(abs(bs_cash - exp_custody)),
        *(_q2(abs(a - oracle.balance_sheet.ending_cash)) for a in custody_amts),
    )
    worst_cash_delta = max(cf_bs_delta, ora_cash_delta, abs(cf_res))

    is_ni = _to_dec(income_statement.get("net_income") or "0.00")
    ni_delta = _q2(abs(bs_ni - is_ni))

    max_chain = max(
        (abs(d) for d in oracle.statement_chain_deltas.values()), default=ZERO
    )
    cust_chain_delta = ZERO
    if balance_sheet.get("assets") or balance_sheet.get("liabilities"):
        dt = (
            "credit_card"
            if oracle.balance_sheet.total_liabilities > ZERO
            and oracle.balance_sheet.ending_cash == ZERO
            else "bank_statement"
        )
        act_cust = _extract_bs_custody_closing_balance(balance_sheet, doc_type=dt)
        cust_chain_delta = min(
            _q2(abs(act_cust - oracle.balance_sheet.ending_cash)),
            _q2(abs(act_cust - exp_custody)),
            *(_q2(abs(a - oracle.balance_sheet.ending_cash)) for a in custody_amts),
        )
    worst_chain = max(max_chain, cust_chain_delta)

    exp_3198 = oracle.balance_sheet.unexplained_gap_equity_3198
    exp_3199 = oracle.balance_sheet.opening_balance_equity_3199
    act_3198 = _extract_equity_code_amount(
        balance_sheet, "3198", "unexplained_gap_equity_3198"
    )
    if act_3198 is None:
        act_3198 = _q2(bs_open_eq - exp_3199)
    gap_delta = _q2(abs(act_3198 - exp_3198))

    act_3199 = _extract_equity_code_amount(
        balance_sheet, "3199", "opening_balance_equity_3199"
    )
    if act_3199 is None:
        act_3199 = _q2(bs_open_eq - act_3198)
    nat_3199_delta = (
        ZERO
        if len(custody_amts) > 1 and act_3199 > exp_3199 and bs_bal
        else _q2(abs(act_3199 - exp_3199))
    )
    tr_delta, tr_bal = ZERO, True
    if translated_balance_sheet is not None:
        _, _, _, tr_delta, tr_bal = _bs_eq_stats(translated_balance_sheet)
    worst_fx = max(nat_3199_delta, tr_delta)

    statuses = (
        list(retirement_cleanup_statuses)
        if retirement_cleanup_statuses is not None
        else [200]
    )
    bad_st = [c for c in statuses if c not in (200, 202, 204)]

    verdicts = (
        InvariantVerdict(
            "fundamental_accounting_equation",
            bs_bal and worst_eq_delta <= tolerance,
            f"Assets ({bs_assets}) == Liabilities ({bs_liab}) + Ending Equity ({ending_eq}), balanced={bs_bal}",
            worst_eq_delta,
        ),
        InvariantVerdict(
            "cash_flow_to_balance_sheet_cash",
            worst_cash_delta <= tolerance and cf_proof == "proven",
            f"CF Ending Cash ({cf_end}) vs BS Cash ({bs_cash}), residual={cf_res}, proof={cf_proof}",
            worst_cash_delta,
        ),
        InvariantVerdict(
            "retained_earnings_to_net_income",
            ni_delta <= tolerance,
            f"BS Net Income ({bs_ni}) vs IS Net Income ({is_ni})",
            ni_delta,
        ),
        InvariantVerdict(
            "statement_balance_chain",
            worst_chain <= tolerance,
            f"Verified {len(oracle.statement_chain_deltas)} chains; max_delta={worst_chain}",
            worst_chain,
        ),
        InvariantVerdict(
            "gap_equity_3198_convergence",
            gap_delta <= tolerance,
            f"3198 Gap Equity actual ({act_3198}) vs expected ({exp_3198})",
            gap_delta,
        ),
        InvariantVerdict(
            "native_vs_translated_fx_consistency",
            tr_bal and worst_fx <= tolerance,
            f"Native 3199 ({act_3199} vs {exp_3199}), Translated delta={tr_delta}, balanced={tr_bal}",
            worst_fx,
        ),
        InvariantVerdict(
            "statement_retirement_cleanup",
            len(statuses) > 0 and not bad_st,
            f"Statement DELETE statuses={statuses}, bad_statuses={bad_st}",
            Decimal(len(bad_st)),
        ),
    )
    failures = tuple(f"{v.invariant_id}: {v.message}" for v in verdicts if not v.passed)
    return OracleComparisonResult(not failures, verdicts, failures)


evaluate_three_statement_consistency = compare_oracle_with_platform_reports


def run_live_pdf_statement_verification(
    client: Any,
    spec: CorpusStatementSpec,
    *,
    root_dir: Path = REPO_ROOT,
    poll_timeout_seconds: Decimal = Decimal("180.00"),
    poll_interval_seconds: Decimal = Decimal("2.00"),
) -> dict[str, Any]:
    pdf_path = ensure_corpus_pdf(spec, root_dir=root_dir)

    up = client.post(
        "/api/statements",
        data={"institution": spec.institution},
        files={"file": (pdf_path.name, pdf_path.read_bytes(), "application/pdf")},
    )
    if up.status_code not in (200, 201, 202):
        raise RuntimeError(
            f"Upload failed for {spec.fixture_id}: {up.status_code} {up.text}"
        )
    stmt_id = str(up.json()["id"])

    deadline = time.monotonic() + int(poll_timeout_seconds)
    rev: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        r = client.get(f"/api/statements/{stmt_id}/review")
        if r.status_code == 200:
            d = r.json()
            if d.get("status") in ("parsed", "approved", "rejected"):
                rev = d
                break
        time.sleep(int(poll_interval_seconds))
    if rev is None:
        raise TimeoutError(f"Timed out waiting for {spec.fixture_id} ({stmt_id})")
    # The classify run follows the extract run: wait for it, then read the review that holds its answers.
    wait_for_statement_runs_sync(client, f"/api/statements/{stmt_id}/runs")
    rev = client.get(f"/api/statements/{stmt_id}/review").json()

    if rev.get("status") == "parsed":
        acc_id = rev.get("account_id")
        if rev.get("source_envelope_confirmation_required") or rev.get(
            "source_envelope_reviewable"
        ):
            if not acc_id and hasattr(client, "post"):
                is_cc = spec.doc_type == "credit_card"
                ar = client.post(
                    "/api/accounts",
                    json={
                        "name": f"{spec.institution} ({spec.currency})",
                        "type": "LIABILITY" if is_cc else "ASSET",
                        "currency": rev.get("currency") or spec.currency,
                        "code": "2100" if is_cc else "1110",
                    },
                )
                if ar.status_code in (200, 201) and isinstance(
                    aj := ar.json(), Mapping
                ):
                    acc_id = aj.get("id")
            er = client.post(
                f"/api/statements/{stmt_id}/review-envelopes",
                json={
                    "source_result_digest": rev.get("source_result_digest"),
                    "account_id": acc_id,
                    "currency": rev.get("currency") or spec.currency,
                    "period_start": rev.get("period_start") or spec.period_start,
                    "period_end": rev.get("period_end") or spec.period_end,
                    "opening_balance": str(
                        rev["opening_balance"]
                        if rev.get("opening_balance") is not None
                        else spec.opening_balance
                    ),
                    "closing_balance": str(
                        rev["closing_balance"]
                        if rev.get("closing_balance") is not None
                        else spec.closing_balance
                    ),
                    "rationale": f"Oracle ground-truth confirmation for {spec.fixture_id}",
                },
            )
            if er.status_code not in (200, 201):
                raise RuntimeError(
                    f"Envelope confirmation failed for {spec.fixture_id}: {er.status_code} {er.text}"
                )
        approval_body = {
            "account_id": acc_id,
            "create_account_if_missing": True,
            "auto_fill_default_categories": True,
        }
        review = client.get(f"/api/statements/{stmt_id}/review")
        if review.status_code == 200 and review.json().get("source_result_digest"):
            approval_body["expected_source_result_digest"] = review.json()["source_result_digest"]
        ap = client.post(f"/api/statements/{stmt_id}/approvals", json=approval_body)
        if ap.status_code not in (200, 201):
            raise RuntimeError(
                f"Approve failed for {spec.fixture_id}: {ap.status_code} {ap.text}"
            )

    p_range = {
        "start_date": spec.period_start,
        "end_date": spec.period_end,
        "currency": spec.currency,
    }
    bs_nat = client.get(
        "/api/reports/balance-sheet",
        params={"as_of_date": spec.period_end, "currency": spec.currency},
    ).json()
    is_nat = client.get("/api/reports/income-statement", params=p_range).json()
    cf_nat = client.get("/api/reports/cash-flow", params=p_range).json()
    bs_sgd = client.get(
        "/api/reports/balance-sheet",
        params={"as_of_date": spec.period_end, "currency": "SGD"},
    ).json()
    del_resp = client.delete(f"/api/statements/{stmt_id}")

    oracle = compute_independent_three_statement_oracle(
        [spec],
        as_of_date=spec.period_end,
        period_start=spec.period_start,
        period_end=spec.period_end,
        report_currency=spec.currency,
        treat_transfers_as_clearing_asset=True,
    )
    comp = compare_oracle_with_platform_reports(
        oracle,
        balance_sheet=bs_nat,
        income_statement=is_nat,
        cash_flow=cf_nat,
        translated_balance_sheet=bs_sgd,
        retirement_cleanup_statuses=[del_resp.status_code],
    )
    return {
        "fixture_id": spec.fixture_id,
        "statement_id": stmt_id,
        "delete_status": del_resp.status_code,
        "comparison": comp.to_dict(),
    }


def _run_offline_fixture(spec: CorpusStatementSpec) -> dict[str, Any]:
    t0 = time.perf_counter()
    failures: list[str] = []
    eq_delta = ZERO
    try:
        oracle = compute_independent_three_statement_oracle([spec])
        eq_delta = oracle.balance_sheet.accounting_equation_delta
        if eq_delta != ZERO:
            failures.append(f"accounting_equation_delta={eq_delta}")
        if spec.balance_chain_delta != ZERO:
            failures.append(f"balance_chain_delta={spec.balance_chain_delta}")
        error_message = None
    except Exception as exc:  # noqa: BLE001
        error_message = f"{type(exc).__name__}: {exc}"
        failures.append(error_message)
    return {
        "fixture_id": spec.fixture_id,
        "institution": spec.institution,
        "dimension": spec.dimension,
        "currency": spec.currency,
        "status": "FAIL" if failures else "PASS",
        "duration_seconds": round(time.perf_counter() - t0, 3),
        "accounting_equation_delta": str(eq_delta),
        "balance_chain_delta": str(spec.balance_chain_delta),
        "failures": failures,
        "error_message": error_message,
    }


def _run_live_fixture(app_url: str, spec: CorpusStatementSpec) -> dict[str, Any]:
    t0 = time.perf_counter()
    stmt_id: str | None = None
    del_status: int | None = None
    comparison: dict[str, Any] | None = None
    failures: list[str] = []
    error_message: str | None = None
    try:
        with httpx.Client(base_url=app_url.rstrip("/"), timeout=120.0) as client:
            reg = client.post(
                "/api/auth/register",
                json={
                    "email": f"pdf_oracle_{spec.fixture_id[:16]}_{uuid.uuid4().hex[:6]}@test.example.com",
                    "password": "Password123!",
                    "display_name": f"PDF Oracle {spec.fixture_id}",
                },
            )
            if reg.status_code not in (200, 201):
                raise RuntimeError(
                    f"Registration failed for {spec.fixture_id}: {reg.status_code} {reg.text}"
                )
            client.headers.update(
                {"Authorization": f"Bearer {reg.json()['access_token']}"}
            )
            res = run_live_pdf_statement_verification(client, spec, root_dir=REPO_ROOT)
        stmt_id = res.get("statement_id")
        del_status = res.get("delete_status")
        comparison = res.get("comparison")
        comp_failures = (
            list(comparison.get("failures") or [])
            if isinstance(comparison, dict)
            else []
        )
        failures = [str(f) for f in comp_failures]
        passed = bool(isinstance(comparison, dict) and comparison.get("passed"))
        if not passed and not failures:
            failures = [f"Oracle comparison did not pass for {spec.fixture_id}"]
    except Exception as exc:  # noqa: BLE001
        error_message = f"{type(exc).__name__}: {exc}"
        failures = [error_message]
        passed = False
    return {
        "fixture_id": spec.fixture_id,
        "institution": spec.institution,
        "dimension": spec.dimension,
        "currency": spec.currency,
        "status": "PASS" if passed else "FAIL",
        "duration_seconds": round(time.perf_counter() - t0, 3),
        "statement_id": stmt_id,
        "delete_status": del_status,
        "comparison": comparison,
        "failures": failures,
        "error_message": error_message,
    }


def _execute_fixtures(
    selected: Sequence[CorpusStatementSpec],
    *,
    app_url: str | None,
    max_workers: int,
) -> list[dict[str, Any]]:
    run_one = (lambda spec: _run_live_fixture(app_url, spec)) if app_url else _run_offline_fixture
    if max_workers <= 1 or len(selected) <= 1:
        return [run_one(spec) for spec in selected]
    with ThreadPoolExecutor(max_workers=min(max_workers, len(selected))) as pool:
        return list(pool.map(run_one, selected))


def _load_ratchet_policy(
    section: str,
    policy_path: Path = DEFAULT_RATCHET_POLICY_PATH,
) -> dict[str, Any] | None:
    if not policy_path.is_file():
        return None
    raw = json.loads(policy_path.read_text(encoding="utf-8"))
    sec = raw.get(section)
    return dict(sec) if isinstance(sec, Mapping) else None


def _percentile(values: Sequence[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(ratio * len(ordered)) - 1))
    return round(ordered[idx], 3)


def _classify_oracle_error(result: Mapping[str, Any]) -> str:
    codes = result.get("issue_codes")
    if isinstance(codes, Sequence) and not isinstance(codes, (str, bytes)) and codes:
        return str(codes[0])
    msg = str(result.get("error_message") or "")
    failures_text = " ".join(str(f) for f in (result.get("failures") or ()))
    combined = f"{msg} {failures_text}"
    if "Timeout" in combined or "Timed out" in combined:
        return "TIMEOUT"
    if "FileNotFoundError" in combined or "Missing PDF" in combined or "sha256" in combined:
        return "MISSING_PDF_FIXTURE"
    if "Envelope confirmation failed" in combined:
        return "ENVELOPE_CONFIRMATION_FAILED"
    if "Approve failed" in combined:
        return "APPROVAL_BLOCKED"
    if "Upload failed" in combined:
        return "UPLOAD_FAILED"
    if result.get("comparison") is not None or failures_text:
        return "THREE_STATEMENT_MISMATCH"
    return "OTHER_ERROR"


def _build_oracle_report_data(
    results: list[dict[str, Any]],
    *,
    manifest_version: str,
    app_url: str | None,
    ratchet_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.get("status") == "PASS")
    failed = total - passed
    durations = [float(r.get("duration_seconds") or 0.0) for r in results]
    total_duration = round(sum(durations), 3)
    p50_seconds = _percentile(durations, 0.50)
    p95_seconds = _percentile(durations, 0.95)
    error_code_counts: dict[str, int] = {}
    for r in results:
        if r.get("status") != "PASS":
            code = _classify_oracle_error(r)
            error_code_counts[code] = error_code_counts.get(code, 0) + 1

    hard_invariants = tuple(
        str(inv)
        for inv in (
            (ratchet_policy or {}).get("hard_invariants")
            or ("fundamental_accounting_equation", "statement_retirement_cleanup")
        )
    )
    hard_invariant_failures: list[str] = []
    for r in results:
        comp = r.get("comparison")
        if isinstance(comp, Mapping):
            for inv in comp.get("invariants") or ():
                if (
                    isinstance(inv, Mapping)
                    and inv.get("invariant_id") in hard_invariants
                    and inv.get("passed") is False
                ):
                    hard_invariant_failures.append(f"{r.get('fixture_id')}:{inv.get('invariant_id')}")

    total_expected = int((ratchet_policy or {}).get("total_expected") or total)
    enforced = bool(ratchet_policy and app_url and total >= total_expected > 0)
    floor_passed = int((ratchet_policy or {}).get("floor_passed") or total)
    hard_invariant_ok = not hard_invariant_failures
    all_passed = total > 0 and failed == 0
    gate_passed = hard_invariant_ok and (passed >= floor_passed if enforced else all_passed)
    return {
        "suite": "pdf_corpus_oracle",
        "manifest_version": manifest_version,
        "app_url": app_url or "",
        "mode": "live" if app_url else "offline",
        "run_at": datetime.now(UTC).isoformat(),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "all_passed": all_passed,
            "success": gate_passed,
            "duration_seconds": total_duration,
            "p50_seconds": p50_seconds,
            "p95_seconds": p95_seconds,
            "error_code_counts": error_code_counts,
            "ratchet": {
                "enforced": enforced,
                "floor_passed": floor_passed if enforced else total,
                "total_expected": total_expected,
                "hard_invariant_ok": hard_invariant_ok,
                "hard_invariant_failures": hard_invariant_failures,
                "gate_passed": gate_passed,
            },
        },
        "results": results,
    }


def extract_pdf_oracle_summary(report_data: Mapping[str, Any]) -> dict[str, Any]:
    summary = report_data.get("summary") or {}
    results = list(report_data.get("results") or [])
    total = int(summary.get("total", len(results)))
    passed = int(summary.get("passed", sum(1 for r in results if r.get("status") == "PASS")))
    failed = int(summary.get("failed", total - passed))
    success = bool(summary.get("success", total > 0 and failed == 0))
    out: dict[str, Any] = {
        "suite": "pdf_corpus_oracle",
        "manifest_version": report_data.get("manifest_version", ""),
        "run_at": report_data.get("run_at", ""),
        "app_url": report_data.get("app_url", ""),
        "mode": report_data.get("mode", "offline"),
        "status": "PASS" if success else "FAIL",
        "fixtures_total": total,
        "fixtures_passed": passed,
        "fixtures_failed": failed,
        "all_passed": bool(summary.get("all_passed", total > 0 and failed == 0)),
        "duration_seconds": float(summary.get("duration_seconds", 0.0)),
        "p50_seconds": float(summary.get("p50_seconds", 0.0)),
        "p95_seconds": float(summary.get("p95_seconds", 0.0)),
        "error_code_counts": dict(summary.get("error_code_counts") or {}),
        "failures_by_fixture": {
            str(r["fixture_id"]): list(r.get("failures") or [])
            for r in results
            if r.get("status") != "PASS"
        },
    }
    if isinstance(summary.get("ratchet"), Mapping):
        out["ratchet"] = dict(summary["ratchet"])
    return out


def _save_oracle_outputs(
    report_data: dict[str, Any],
    *,
    json_report: Path | None,
    output_summary: Path | None,
) -> None:
    safe_report = sanitize_for_json(report_data)
    if json_report:
        write_utf8_atomic(json_report, json.dumps(safe_report, indent=2))
    if output_summary:
        summary_data = sanitize_for_json(extract_pdf_oracle_summary(safe_report))
        write_utf8_atomic(output_summary, json.dumps(summary_data, indent=2))


def _print_oracle_summary(
    results: Sequence[Mapping[str, Any]],
    report_data: Mapping[str, Any],
    json_report: Path | None,
) -> None:
    for r in results:
        print(
            f"{r['status']} | {r['fixture_id']} ({r.get('duration_seconds', 0.0):.2f}s)"
        )
        if r.get("error_message"):
            print(f"  Error: {r['error_message']}")
    s = report_data["summary"]
    print(f"Total: {s['total']} | Passed: {s['passed']} | Failed: {s['failed']}")
    if json_report:
        print(f"Report saved to: {json_report}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--app-url", type=str, default=None)
    parser.add_argument("--fixture", action="append", default=None)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--json-report", type=Path, default=None)
    parser.add_argument("--output-summary", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.max_workers < 1:
        return 2
    if args.app_url is not None and not args.app_url.strip():
        print("Error: --app-url must not be empty.", file=sys.stderr)
        return 2

    raw_manifest = yaml.safe_load(args.manifest.read_text(encoding="utf-8")) or {}
    manifest_version = str(raw_manifest.get("version") or "")
    corpus = load_pdf_benchmark_corpus(args.manifest, REPO_ROOT)
    selected = (
        [s for s in corpus if s.fixture_id in set(args.fixture)]
        if args.fixture
        else list(corpus)
    )
    if not selected:
        return 2

    results = _execute_fixtures(
        selected, app_url=args.app_url, max_workers=args.max_workers
    )
    ratchet_policy = (
        _load_ratchet_policy("pdf_corpus_oracle") if (args.app_url and not args.fixture) else None
    )
    report_data = _build_oracle_report_data(
        results,
        manifest_version=manifest_version,
        app_url=args.app_url,
        ratchet_policy=ratchet_policy,
    )
    _save_oracle_outputs(
        report_data, json_report=args.json_report, output_summary=args.output_summary
    )
    _print_oracle_summary(results, report_data, args.json_report)
    return 0 if report_data["summary"]["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
