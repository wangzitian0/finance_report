"""Framework-aware personal reporting policy contract coverage."""

from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.schemas.reporting import (
    FrameworkPolicyDecision,
    FrameworkPolicyEvidenceAnchor,
    FrameworkPolicyFact,
    FrameworkPolicyMatrix,
    FrameworkPolicyResult,
    PersonalReportingFrameworkId,
    PolicyDimension,
    PolicyFactDomain,
    PolicyProvenance,
    PolicyReviewState,
)
from src.services.framework_policy import _result_id, _rule, derive_framework_policy_result, get_framework_policy_matrix

pytestmark = pytest.mark.no_db


def _anchor(identifier: str = "statement:dbs-2026-05") -> FrameworkPolicyEvidenceAnchor:
    return FrameworkPolicyEvidenceAnchor(
        anchor_id=identifier,
        anchor_type="source_record",
        source_system="test_fixture",
        source_id=identifier,
        description="Fixture source evidence",
    )


def _fact(domain: PolicyFactDomain, *, instrument_type: str = "fixture") -> FrameworkPolicyFact:
    return FrameworkPolicyFact(
        fact_id=f"fact-{domain.value}",
        domain=domain,
        instrument_type=instrument_type,
        amount=Decimal("100.00"),
        currency="SGD",
        event_date=date(2026, 5, 31),
        anchors=[_anchor(f"source:{domain.value}")],
    )


def test_AC20_3_1_policy_result_schema_requires_all_policy_dimensions() -> None:
    """AC20.3.1: Framework policy results fail when required decision dimensions are missing."""
    with pytest.raises(ValidationError, match="missing required policy dimensions"):
        FrameworkPolicyDecision(
            domain=PolicyFactDomain.CASH,
            recognition="Recognize on transaction date after source cutoff validation.",
            measurement="Cash is measured at nominal amount with FX translation as needed.",
            classification="Cash and bank account asset.",
            presentation="Balance sheet cash and cash equivalents.",
            disclosure=None,
            line_mappings={"balance_sheet": "assets.cash_and_cash_equivalents"},
            evidence_anchors=[_anchor()],
        )


def test_AC20_3_1_policy_result_validation_names_missing_dimensions() -> None:
    """AC20.3.1: Result-level dimension validation identifies fields, not only domains."""
    incomplete_decision = FrameworkPolicyDecision.model_construct(
        domain=PolicyFactDomain.CASH,
        recognition="Recognize cash from reviewed source evidence.",
        measurement="Measure cash at nominal amount.",
        classification="Cash asset.",
        presentation="Balance sheet cash.",
        disclosure=None,
        line_mappings={"balance_sheet": "assets.cash"},
    )

    with pytest.raises(ValidationError, match="cash.disclosure"):
        FrameworkPolicyResult(
            result_id="policy-result:test",
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            matrix_version="test",
            report_period_start=date(2026, 5, 1),
            report_period_end=date(2026, 5, 31),
            generated_at=date(2026, 6, 1),
            required_statements=["balance_sheet"],
            decisions=[incomplete_decision],
        )


def test_AC20_3_1_framework_schema_rejects_unsupported_framework_id() -> None:
    """AC20.3.1: Framework policy result schema is closed to unsupported framework IDs."""
    with pytest.raises(ValidationError):
        FrameworkPolicyResult(
            result_id="policy-result:test",
            framework_id="cn_cas_like",
            report_period_start=date(2026, 5, 1),
            report_period_end=date(2026, 5, 31),
            generated_at=date(2026, 6, 1),
            required_statements=["balance_sheet"],
            decisions=[],
        )


def test_AC20_4_1_policy_rule_defaults_preserve_explicit_empty_lists() -> None:
    """AC20.4.1: Matrix rule construction preserves explicit empty evidence/disclosure lists."""
    rule = _rule(
        domain=PolicyFactDomain.CASH,
        supported_instrument_types=["cash"],
        recognition="Recognize cash.",
        measurement="Measure cash.",
        classification="Cash asset.",
        presentation="Cash line.",
        disclosure="No additional disclosure.",
        line_mappings={"balance_sheet": "assets.cash"},
        required_evidence=[],
        disclosure_requirements=[],
        blocker_conditions=[],
    )

    assert rule.required_evidence == []
    assert rule.disclosure_requirements == []
    assert rule.blocker_conditions == []


def test_policy_matrix_rejects_unknown_line_mapping_target() -> None:
    rule = _rule(
        domain=PolicyFactDomain.CASH,
        supported_instrument_types=["cash"],
        recognition="Recognize cash.",
        measurement="Measure cash.",
        classification="Cash asset.",
        presentation="Cash line.",
        disclosure="No additional disclosure.",
        line_mappings={"balence_sheet": "assets.cash_and_cash_equivalents"},
        required_evidence=[],
        disclosure_requirements=[],
        blocker_conditions=[],
    )

    with pytest.raises(ValidationError, match="unknown statement target 'balence_sheet'"):
        FrameworkPolicyMatrix(
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            version="test",
            rules=[rule],
        )


def test_policy_result_rejects_unknown_line_mapping_target() -> None:
    decision = FrameworkPolicyDecision(
        domain=PolicyFactDomain.CASH,
        recognition="Recognize cash from reviewed source evidence.",
        measurement="Measure cash at nominal amount.",
        classification="Cash asset.",
        presentation="Balance sheet cash.",
        disclosure="No additional disclosure.",
        line_mappings={"balence_sheet": "assets.cash_and_cash_equivalents"},
        evidence_anchors=[_anchor()],
    )

    with pytest.raises(ValidationError, match="unknown statement target 'balence_sheet'"):
        FrameworkPolicyResult(
            result_id="policy-result:test",
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            matrix_version="test",
            report_period_start=date(2026, 5, 1),
            report_period_end=date(2026, 5, 31),
            generated_at=date(2026, 6, 1),
            required_statements=["balance_sheet"],
            decisions=[decision],
        )


def test_AC20_4_1_policy_matrix_covers_required_v1_domains_and_dimensions() -> None:
    """AC20.4.1: US/HK v1 matrix covers personal finance domains and policy dimensions."""
    for framework_id in PersonalReportingFrameworkId:
        matrix = get_framework_policy_matrix(framework_id)
        domains = {rule.domain for rule in matrix.rules}

        assert {
            PolicyFactDomain.CASH,
            PolicyFactDomain.LISTED_SECURITY,
            PolicyFactDomain.FUND,
            PolicyFactDomain.DIVIDEND_INTEREST,
            PolicyFactDomain.BROKERAGE_FEE,
            PolicyFactDomain.FX,
            PolicyFactDomain.RESTRICTED_COMPENSATION,
            PolicyFactDomain.PROPERTY_MORTGAGE_PRIVATE,
            PolicyFactDomain.LIABILITY,
            PolicyFactDomain.TRANSFER,
            PolicyFactDomain.TAX_NOTE,
        }.issubset(domains)

        for rule in matrix.rules:
            assert set(rule.policy_by_dimension) == set(PolicyDimension)
            assert rule.line_mappings
            assert rule.required_evidence
            assert rule.disclosure_requirements
            assert rule.blocker_conditions


def test_AC20_5_1_policy_derivation_is_deterministic_reviewed_and_read_only() -> None:
    """AC20.5.1: Policy derivation consumes facts without mutating them."""
    facts = [
        _fact(PolicyFactDomain.CASH),
        _fact(PolicyFactDomain.LISTED_SECURITY, instrument_type="listed_equity"),
        _fact(PolicyFactDomain.FX, instrument_type="fx_transaction"),
    ]
    original = deepcopy([fact.model_dump(mode="json") for fact in facts])

    first = derive_framework_policy_result(
        PersonalReportingFrameworkId.US_GAAP_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=date(2026, 5, 31),
        facts=facts,
    )
    second = derive_framework_policy_result(
        PersonalReportingFrameworkId.US_GAAP_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=date(2026, 5, 31),
        facts=facts,
    )

    assert [fact.model_dump(mode="json") for fact in facts] == original
    assert first == second
    assert first.gaps == []
    assert {decision.provenance for decision in first.decisions} == {PolicyProvenance.DETERMINISTIC_MATRIX}
    assert {decision.review_state for decision in first.decisions} == {PolicyReviewState.ACCEPTED}


def test_AC20_5_1_policy_result_id_fingerprints_decision_content_and_matrix_version() -> None:
    """AC20.5.1: Policy result IDs change when decision content or matrix version changes."""
    decision = FrameworkPolicyDecision(
        domain=PolicyFactDomain.CASH,
        recognition="Recognize cash from reviewed source evidence.",
        measurement="Measure cash at nominal amount.",
        classification="Cash asset.",
        presentation="Balance sheet cash.",
        disclosure="Disclose source coverage.",
        line_mappings={"balance_sheet": "assets.cash"},
        evidence_anchors=[_anchor("source:cash")],
    )
    changed_decision = decision.model_copy(update={"presentation": "Changed cash presentation."})

    base_id = _result_id(
        PersonalReportingFrameworkId.US_GAAP_LIKE,
        matrix_version="1.0",
        report_period_start=date(2026, 5, 1),
        report_period_end=date(2026, 5, 31),
        decisions=[decision],
        gaps=[],
    )
    changed_decision_id = _result_id(
        PersonalReportingFrameworkId.US_GAAP_LIKE,
        matrix_version="1.0",
        report_period_start=date(2026, 5, 1),
        report_period_end=date(2026, 5, 31),
        decisions=[changed_decision],
        gaps=[],
    )
    changed_version_id = _result_id(
        PersonalReportingFrameworkId.US_GAAP_LIKE,
        matrix_version="1.1",
        report_period_start=date(2026, 5, 1),
        report_period_end=date(2026, 5, 31),
        decisions=[decision],
        gaps=[],
    )

    assert base_id != changed_decision_id
    assert base_id != changed_version_id


def test_AC20_4_1_us_and_hk_matrix_differ_for_same_listed_security_fixture() -> None:
    """AC20.4.1: The same portfolio fact can produce framework-specific policy output."""
    facts = [_fact(PolicyFactDomain.LISTED_SECURITY, instrument_type="listed_equity")]

    us_result = derive_framework_policy_result(
        PersonalReportingFrameworkId.US_GAAP_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=date(2026, 5, 31),
        facts=facts,
    )
    hk_result = derive_framework_policy_result(
        PersonalReportingFrameworkId.HKFRS_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=date(2026, 5, 31),
        facts=facts,
    )

    us_decision = us_result.decisions[0]
    hk_decision = hk_result.decisions[0]
    assert us_decision.line_mappings["balance_sheet"] != hk_decision.line_mappings["balance_sheet"]
    assert "US-like" in us_decision.presentation
    assert "HK-like" in hk_decision.presentation


def test_AC20_4_1_unsupported_instruments_create_policy_gap_not_market_value_default() -> None:
    """AC20.4.1: Unsupported instruments surface explicit gaps instead of defaulting to market value."""
    facts = [
        FrameworkPolicyFact(
            fact_id="fact-private-token",
            domain=PolicyFactDomain.LISTED_SECURITY,
            instrument_type="private_token",
            amount=Decimal("100.00"),
            currency="SGD",
            event_date=date(2026, 5, 31),
            anchors=[_anchor("source:private-token")],
        )
    ]

    result = derive_framework_policy_result(
        PersonalReportingFrameworkId.US_GAAP_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=date(2026, 5, 31),
        facts=facts,
    )

    assert result.decisions == []
    assert len(result.gaps) == 1
    gap = result.gaps[0]
    assert gap.code == "unsupported_policy_domain"
    assert gap.blocker is True
    assert gap.fact_id == "fact-private-token"
    assert "market value" not in gap.remediation.lower()


def test_AC20_7_1_same_settlement_fixture_drives_us_hk_report_policy_outputs() -> None:
    """AC20.7.1: One settlement fixture produces framework-specific lines, notes, and blockers."""
    facts = [
        _fact(PolicyFactDomain.CASH, instrument_type="bank_account"),
        _fact(PolicyFactDomain.LISTED_SECURITY, instrument_type="listed_equity"),
        _fact(PolicyFactDomain.DIVIDEND_INTEREST, instrument_type="dividend"),
        _fact(PolicyFactDomain.BROKERAGE_FEE, instrument_type="brokerage_fee"),
        _fact(PolicyFactDomain.RESTRICTED_COMPENSATION, instrument_type="rsu"),
        FrameworkPolicyFact(
            fact_id="settlement:private-token",
            domain=PolicyFactDomain.UNSUPPORTED,
            instrument_type="private_token",
            amount=Decimal("25.00"),
            currency="SGD",
            event_date=date(2026, 5, 31),
            anchors=[_anchor("brokerage_settlement:private-token")],
        ),
    ]

    us_result = derive_framework_policy_result(
        PersonalReportingFrameworkId.US_GAAP_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=date(2026, 5, 31),
        facts=facts,
    )
    hk_result = derive_framework_policy_result(
        PersonalReportingFrameworkId.HKFRS_LIKE,
        report_period_start=date(2026, 5, 1),
        report_period_end=date(2026, 5, 31),
        facts=facts,
    )

    us_decisions = {decision.domain: decision for decision in us_result.decisions}
    hk_decisions = {decision.domain: decision for decision in hk_result.decisions}

    assert us_result.matrix_version == "1.0"
    assert hk_result.matrix_version == "1.0"
    assert us_result.required_statements == [
        "balance_sheet",
        "income_statement",
        "cash_flow",
        "notes",
        "traceability_appendix",
    ]
    assert hk_result.required_statements == us_result.required_statements
    assert (
        us_decisions[PolicyFactDomain.LISTED_SECURITY].line_mappings["balance_sheet"] == "assets.marketable_securities"
    )
    assert (
        hk_decisions[PolicyFactDomain.LISTED_SECURITY].line_mappings["balance_sheet"]
        == "assets.financial_assets_at_fair_value"
    )
    assert us_decisions[PolicyFactDomain.LISTED_SECURITY].line_mappings["notes"] == "notes.us_like_market_price_basis"
    assert hk_decisions[PolicyFactDomain.LISTED_SECURITY].line_mappings["notes"] == "notes.hk_like_fair_value_basis"
    assert "disclose" in us_decisions[PolicyFactDomain.DIVIDEND_INTEREST].disclosure.lower()
    assert "disclose" in hk_decisions[PolicyFactDomain.RESTRICTED_COMPENSATION].disclosure.lower()
    assert {gap.code for gap in us_result.gaps} == {"unsupported_policy_domain"}
    assert {gap.code for gap in hk_result.gaps} == {"unsupported_policy_domain"}
    assert us_result.result_id != hk_result.result_id
