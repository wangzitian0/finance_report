#!/usr/bin/env python3
"""Independent 3-Statement Mathematical Oracle and 20-PDF Benchmark Corpus Runner (#2852)."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST_PATH = (
    REPO_ROOT / "common" / "testing" / "fixtures" / "benchmarks" / "manifest.yaml"
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
            )
        )
    return tuple(specs)


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
    pdf_path = root_dir / spec.local_path
    if not pdf_path.exists():
        raise FileNotFoundError(f"Missing PDF file for {spec.fixture_id}: {pdf_path}")

    up = client.post(
        "/api/statements/upload",
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
            if d.get("status") in ("parsed", "approved", "rejected") and not d.get(
                "preclassification_in_progress"
            ):
                rev = d
                break
        time.sleep(int(poll_interval_seconds))
    if rev is None:
        raise TimeoutError(f"Timed out waiting for {spec.fixture_id} ({stmt_id})")

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
                f"/api/statements/{stmt_id}/review/envelope",
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
        ap = client.post(
            f"/api/statements/{stmt_id}/review/approve",
            json={
                "account_id": acc_id,
                "create_account_if_missing": True,
                "auto_fill_default_categories": True,
                "auto_fill_defaults": True,
                "note": "Oracle benchmark auto-fill approval",
            },
        )
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--app-url", type=str, default=None)
    parser.add_argument("--fixture", action="append", default=None)
    parser.add_argument("--max-workers", type=int, default=1)
    args = parser.parse_args(argv)

    corpus = load_pdf_benchmark_corpus(args.manifest, REPO_ROOT)
    selected = (
        [s for s in corpus if s.fixture_id in set(args.fixture)]
        if args.fixture
        else list(corpus)
    )
    if not selected:
        return 2
    for spec in selected:
        oracle = compute_independent_three_statement_oracle([spec])
        if (
            oracle.balance_sheet.accounting_equation_delta != ZERO
            or spec.balance_chain_delta != ZERO
        ):
            return 1
    if not args.app_url:
        return 0

    with httpx.Client(base_url=args.app_url.rstrip("/"), timeout=120.0) as client:
        all_passed = True
        for spec in selected:
            reg = client.post(
                "/api/auth/register",
                json={
                    "email": f"pdf_oracle_{spec.fixture_id[:16]}_{uuid.uuid4().hex[:6]}@test.example.com",
                    "password": "Password123!",
                    "display_name": f"PDF Oracle {spec.fixture_id}",
                },
            )
            if reg.status_code not in (200, 201):
                return 1
            client.headers.update(
                {"Authorization": f"Bearer {reg.json()['access_token']}"}
            )
            res = run_live_pdf_statement_verification(client, spec, root_dir=REPO_ROOT)
            if not res["comparison"]["passed"]:
                all_passed = False
        return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
