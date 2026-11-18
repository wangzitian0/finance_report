from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session

from src.ledger import Account, AccountType, JournalLine, initialize_opening_positions
from src.ledger.orm.opening_position import OpeningPositionRecord
from src.reporting import PackageAssembler, derive_user_framework_policy_result
from src.reporting.extension import package_document
from src.reporting.extension.package_document import _traceability_appendix
from src.schemas.reporting import PersonalReportingFrameworkId, PersonalReportPackageTraceabilityAnchorName
from tests.reporting._report_fixtures import (
    JUNE_PERIOD,
    YEAR_ENTRY_COUNT,
    YEAR_PERIOD,
    all_pages,
    count_sql_statements,
    seed_accounts,
    seed_ready_package_state,
    seed_reviewed_statement,
    seed_year_of_anchored_entries,
)

FRAMEWORK = PersonalReportingFrameworkId.US_GAAP_LIKE
EXPENSE_CATEGORIES = ("GROCERIES", "DINING")
PREVIEW_BYTE_BUDGET = 300000
ANCHORS = ("source_anchor", "ledger_anchor")
SECTIONS = ("operating", "investing", "financing")

_json = lambda v: json.loads(json.dumps(v, default=str))
_size = lambda v: len(json.dumps(v, separators=(",", ":"), default=str))


async def _seed_year_reviewed(db: AsyncSession, user_id, monkeypatch: pytest.MonkeyPatch) -> Account:
    await seed_ready_package_state(db, user_id, monkeypatch)
    bank = (await db.execute(select(Account).where(Account.user_id == user_id, Account.name == "DBS"))).scalar_one()
    await seed_year_of_anchored_entries(db, user_id, bank=bank, categories=EXPENSE_CATEGORIES)
    return bank


async def test_AC_reporting_package_traceability_7_and_9_year_scale_previews_are_bounded(
    client, db: AsyncSession, db_engine, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_year_of_anchored_entries(db, test_user.id)
    with count_sql_statements(db_engine) as counter:
        resp = await client.get("/reports/package", params=YEAR_PERIOD)
    assert resp.status_code == 200 and len(resp.content) < PREVIEW_BYTE_BUDGET and counter["count"] <= 86
    preview = resp.json()
    assert preview["lifecycle"] == "preview" and "input_manifest" not in preview
    doc = await PackageAssembler().assemble(
        db,
        user_id=test_user.id,
        framework_id=FRAMEWORK,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        as_of_date=date(2026, 12, 31),
        currency="SGD",
    )
    assert (
        preview["readiness"] == doc.readiness.model_dump(mode="json")
        and doc.readiness.input_coverage.manifest_decision_count == len(doc.input_manifest) == YEAR_ENTRY_COUNT
    )
    full_lines = {line.line_id: line for line in doc.sections.traceability_appendix.lines}
    prev_lines = preview["sections"]["traceability_appendix"]["lines"]
    assert [item["line_id"] for item in prev_lines] == list(full_lines)
    detail_total = 0
    for line in prev_lines:
        fl = full_lines[line["line_id"]]
        assert (line["anchor_count"], line["blocker_codes"]) == (fl.anchor_count, fl.blocker_codes)
        for a_name in ANCHORS:
            a, fa = line[a_name], getattr(fl, a_name)
            assert (
                "details" not in a
                and "identifiers" not in a
                and a["state"] == fa.state
                and a["detail_count"] == len(fa.details) == len(fa.identifiers)
            )
            detail_total += a["detail_count"]
    assert detail_total >= 2 * YEAR_ENTRY_COUNT
    full_json = doc.model_dump(mode="json")
    assets_ledger = next(
        item["ledger_anchor"]["details"]
        for item in full_json["sections"]["traceability_appendix"]["lines"]
        if item["line_id"] == "balance_sheet.total_assets"
    )
    assert len(assets_ledger) == 2 * YEAR_ENTRY_COUNT
    last_details = await client.get(
        "/reports/package/line-details",
        params={
            **YEAR_PERIOD,
            "line_id": "balance_sheet.total_assets",
            "anchor": "ledger_anchor",
            "limit": 500,
            "offset": 1500,
        },
    )
    assert (last_details.status_code, last_details.json()["total"], last_details.json()["details"]) == (
        200,
        len(assets_ledger),
        assets_ledger[1500:],
    )
    last_entries = await client.get(
        "/reports/package/manifest-entries", params={**YEAR_PERIOD, "limit": 500, "offset": 500}
    )
    assert (last_entries.status_code, last_entries.json()["total"], last_entries.json()["entries"]) == (
        200,
        YEAR_ENTRY_COUNT,
        full_json["input_manifest"][500:],
    )


async def test_AC_reporting_package_traceability_9_and_10_categorized_year_scale_and_policy_pages(
    client, db: AsyncSession, db_engine, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_year_reviewed(db, test_user.id, monkeypatch)
    with count_sql_statements(db_engine) as counter:
        resp = await client.get("/reports/package", params=YEAR_PERIOD)
    assert resp.status_code == 200 and len(resp.content) < PREVIEW_BYTE_BUDGET and counter["count"] <= 105
    preview = resp.json()
    full = (
        await PackageAssembler().assemble(
            db,
            user_id=test_user.id,
            framework_id=FRAMEWORK,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            as_of_date=date(2026, 12, 31),
            currency="SGD",
        )
    ).model_dump(mode="json")
    assert (
        _size(full["framework_policy"]["decisions"]) > 700000
        and _size(full["sections"]["cash_flow"]) > 400000
        and len(full["sections"]["cash_flow"]["event_lineage"]) > 1000
    )
    assert preview["readiness"] == full["readiness"]
    pol, full_pol, page_sz = (
        preview["framework_policy"],
        full["framework_policy"],
        package_document.PACKAGE_POLICY_PREVIEW_DECISIONS,
    )
    assert (
        pol["decision_count"] == len(full_pol["decisions"]) > page_sz
        and pol["decisions"] == full_pol["decisions"][:page_sz]
        and pol["gaps"] == full_pol["gaps"]
    )
    assert all(
        pol[k] == full_pol[k]
        for k in ("result_id", "framework_id", "matrix_version", "required_statements", "generated_at")
    )
    refs = {
        f"{a['anchor_type']}:{a['source_id']}"
        for item in [*full_pol["decisions"], *full_pol["gaps"]]
        for a in item["evidence_anchors"]
    }
    assert pol["evidence_reference_count"] == len(refs) > page_sz
    cf, full_cf = preview["sections"]["cash_flow"], full["sections"]["cash_flow"]
    assert "event_lineage" not in cf and all(
        cf[k] == full_cf[k]
        for k in ("start_date", "end_date", "currency", "summary", "cash_bridge", "proof_state", "proof_reasons")
    )
    reasons = Counter(r["reason_code"] for r in full_cf["event_lineage"])
    assert cf["lineage_summary"] == {
        "event_count": len(full_cf["event_lineage"]),
        "classified_event_count": reasons[None],
        "unclassified_event_count": reasons["cash_event_classification_ambiguous"],
        "opening_stock_event_count": reasons["opening_stock"],
    }
    for sec in SECTIONS:
        expected = defaultdict(lambda: [Decimal("0"), 0])
        for item in full_cf[sec]:
            g = expected[item["description"], item["account_id"]]
            g[0] += Decimal(item["amount"])
            g[1] += 1
        assert {
            (line["description"], line["account_id"]): (Decimal(line["amount"]), line["event_count"])
            for line in cf[sec]
        } == {k: tuple(v) for k, v in expected.items()}
    assert (
        len(cf["operating"]) >= 1 + len(EXPENSE_CATEGORIES)
        and sum(line["event_count"] for sec in SECTIONS for line in cf[sec]) == reasons[None]
    )
    assert all(
        preview["sections"][k] == full["sections"][k]
        for k in ("balance_sheet", "income_statement", "investment_performance", "annualized_income_long_term", "notes")
    )

    derived_pol = await derive_user_framework_policy_result(
        db,
        test_user.id,
        framework_id=FRAMEWORK,
        report_period_start=date(2026, 1, 1),
        report_period_end=date(2026, 12, 31),
        as_of_date=date(2026, 12, 31),
    )
    assert full_pol == _json(derived_pol.model_dump(mode="json")) and len(full_pol["decisions"]) > 1000
    query = {"framework_id": FRAMEWORK.value, **{k: YEAR_PERIOD[k] for k in ("start_date", "end_date", "as_of_date")}}
    decisions, total = await all_pages(
        client, "/reports/package/policy-decisions", query, limit=500, item_key="decisions"
    )
    assert (total, decisions) == (len(full_pol["decisions"]), full_pol["decisions"])
    small = (await client.get("/reports/package/policy-decisions", params={**query, "limit": 7, "offset": 13})).json()
    assert (small["total"], small["decisions"]) == (total, decisions[13:20])
    assert (await client.get("/reports/package/policy-decisions", params={**query, "offset": total + 5})).json()[
        "decisions"
    ] == []


async def test_AC_reporting_package_traceability_8_and_11_evidence_and_snapshot_pages(
    client, db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    stock_price = await seed_reviewed_statement(db, test_user.id, monkeypatch)
    gen = (
        await client.post("/reports/package/snapshots", json={**JUNE_PERIOD, "framework_id": FRAMEWORK.value})
    ).json()
    snapshot = (await client.get(f"/reports/package/snapshots/{gen['id']}")).json()["document"]
    assert snapshot["lifecycle"] == "frozen"
    prev = (await client.get("/reports/package", params=JUNE_PERIOD)).json()
    prev_lines = {item["line_id"]: item for item in prev["sections"]["traceability_appendix"]["lines"]}
    anchors = [
        (item["line_id"], an, item[an]["details"])
        for item in snapshot["sections"]["traceability_appendix"]["lines"]
        for an in ANCHORS
    ]
    db.expire_all()
    evidence = await PackageAssembler()._evidence_contributions(
        db,
        user_id=test_user.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        as_of_date=date(2026, 6, 30),
        currency="SGD",
    )
    built = {
        item["line_id"]: item for item in (await _traceability_appendix(evidence)).model_dump(mode="json")["lines"]
    }
    for lid, an, expected in anchors:
        assert prev_lines[lid][an]["detail_count"] == len(expected) and built[lid][an]["details"] == expected
    largest = max(anchors, key=lambda item: len(item[2]))
    paged = [largest] + [
        next(item for item in anchors if any(d["source_kind"] == kind for d in item[2]))
        for kind in sorted({d["source_kind"] for _, _, dets in anchors for d in dets})
        if not any(d["source_kind"] == kind for d in largest[2])
    ]
    detail_kinds = set()
    for lid, an, expected in paged:
        details, total = await all_pages(
            client,
            "/reports/package/line-details",
            {**JUNE_PERIOD, "line_id": lid, "anchor": an},
            limit=2 if (lid, an) == largest[:2] else 500,
            item_key="details",
        )
        assert (total, details) == (len(expected), expected)
        detail_kinds.update(d["source_kind"] for d in expected)
    entries, total = await all_pages(
        client, "/reports/package/manifest-entries", JUNE_PERIOD, limit=3, item_key="entries"
    )
    assert (total, entries) == (len(snapshot["input_manifest"]), snapshot["input_manifest"]) and total > 3
    mkt = next(
        item
        for item in snapshot["sections"]["traceability_appendix"]["lines"]
        if item["line_id"] == "investment_performance.market_value"
    )
    assert f"pricing_observation:{stock_price.id}" in {d["identifier"] for d in mkt["source_anchor"]["details"]}
    assert detail_kinds == {
        "journal_line",
        "opening_position",
        "package_contract",
        "pricing_valuation_observation",
        "statement_extraction_result",
    }
    decisions = snapshot["framework_policy"]["decisions"]
    pol_pages, pol_total = await all_pages(
        client,
        "/reports/package/policy-decisions",
        {"framework_id": FRAMEWORK.value, **{k: JUNE_PERIOD[k] for k in ("start_date", "end_date", "as_of_date")}},
        limit=3,
        item_key="decisions",
    )
    assert (pol_pages, pol_total) == (decisions, len(decisions)) and len(
        decisions
    ) > package_document.PACKAGE_POLICY_PREVIEW_DECISIONS // 5
    assert sum(line["event_count"] for sec in SECTIONS for line in prev["sections"]["cash_flow"][sec]) == sum(
        len(snapshot["sections"]["cash_flow"][sec]) for sec in SECTIONS
    )


async def test_AC_reporting_package_traceability_8_line_details_reject_unknown_lines(
    client, db: AsyncSession, test_user
) -> None:
    assert (
        await client.get(
            "/reports/package/line-details", params={**JUNE_PERIOD, "line_id": "x.y", "anchor": "ledger_anchor"}
        )
    ).status_code == 404
    assert (
        await client.get(
            "/reports/package/line-details",
            params={**JUNE_PERIOD, "line_id": "balance_sheet.total_assets", "anchor": "other_anchor"},
        )
    ).status_code == 422
    assert (
        await client.get("/reports/package/manifest-entries", params={**JUNE_PERIOD, "limit": 501})
    ).status_code == 422
    static = await client.get(
        "/reports/package/line-details",
        params={**JUNE_PERIOD, "line_id": "notes.non_compliance_statement", "anchor": "source_anchor"},
    )
    assert (static.status_code, static.json()["total"], static.json()["details"][0]["source_kind"]) == (
        200,
        1,
        "package_contract",
    )
    past = await client.get(
        "/reports/package/line-details",
        params={**JUNE_PERIOD, "line_id": "notes.non_compliance_statement", "anchor": "source_anchor", "offset": 5},
    )
    assert (past.status_code, past.json()["total"], past.json()["details"]) == (200, 1, [])


async def test_AC_reporting_package_traceability_8_and_10_deterministic_tiebreak_order(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_ready_package_state(db, test_user.id, monkeypatch)
    accs = await seed_accounts(db, test_user.id, *[(f"Cash {i}", AccountType.ASSET) for i in range(4)])
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={a.id: Decimal(f"{i + 1}000.00") for i, a in enumerate(accs)},
        currency="SGD",
        base_currency="SGD",
    )
    await db.commit()
    detail_orders, policy_orders = [], []
    for direction in ("asc", "desc"):

        def hook(state: ORMExecuteState, _d=direction) -> Result | None:
            stmt = state.statement
            if not state.is_select or not hasattr(stmt, "column_descriptions"):
                return None
            entities = {col.get("entity") for col in stmt.column_descriptions}
            target = next((e for e in (OpeningPositionRecord, JournalLine, Account) if e in entities), None)
            if target is None:
                return None
            return state.invoke_statement(statement=stmt.order_by(target.id.asc() if _d == "asc" else target.id.desc()))

        event.listen(Session, "do_orm_execute", hook)
        try:
            details = await PackageAssembler().line_details(
                db,
                user_id=test_user.id,
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 30),
                as_of_date=date(2026, 6, 30),
                currency="SGD",
                line_id="balance_sheet.total_assets",
                anchor=PersonalReportPackageTraceabilityAnchorName.LEDGER,
            )
            pol = await derive_user_framework_policy_result(
                db,
                test_user.id,
                framework_id=FRAMEWORK,
                report_period_start=date(2026, 6, 1),
                report_period_end=date(2026, 6, 30),
                as_of_date=date(2026, 6, 30),
            )
        finally:
            event.remove(Session, "do_orm_execute", hook)
        detail_orders.append([d["identifier"] for d in details])
        policy_orders.append([a.anchor_id for d in pol.decisions for a in d.evidence_anchors[:1]])
    assert (
        len([i for i in detail_orders[0] if str(i).startswith("opening_position:")]) == 4
        and detail_orders[0] == detail_orders[1]
    )
    assert len(policy_orders[0]) > 5 and policy_orders[0] == policy_orders[1]
