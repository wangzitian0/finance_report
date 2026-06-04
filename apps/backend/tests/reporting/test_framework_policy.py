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
    FrameworkPolicyResult,
    PersonalReportingFrameworkId,
    PolicyDimension,
    PolicyFactDomain,
    PolicyProvenance,
    PolicyReviewState,
)
from src.services.framework_policy import derive_framework_policy_result, get_framework_policy_matrix


@pytest.fixture(autouse=True)
def patch_database_connection():
    """Framework policy contract tests do not require a database."""
    yield


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


def test_AC20_3_1_framework_schema_rejects_unsupported_framework_id() -> None:
    """AC20.3.1: Framework policy result schema is closed to unsupported framework IDs."""
    with pytest.raises(ValidationError):
        FrameworkPolicyResult(
            framework_id="cn_cas_like",
            report_period_start=date(2026, 5, 1),
            report_period_end=date(2026, 5, 31),
            generated_at=date(2026, 6, 1),
            required_statements=["balance_sheet"],
            decisions=[],
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
