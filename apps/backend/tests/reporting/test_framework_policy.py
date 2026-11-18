from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.extraction.orm.layer2 import AssetType
from src.pricing import ManualValuationComponentType
from src.reporting.extension.framework_policy import (
    _find_rule,
    _manual_domain_and_instrument,
    _position_domain_and_instrument,
    _result_id,
    _rule,
    derive_framework_policy_result,
    get_framework_policy_matrix,
)
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

pytestmark = pytest.mark.no_db

_PERIOD = {"report_period_start": date(2026, 5, 1), "report_period_end": date(2026, 5, 31)}
_REQUIRED_DOMAINS = {
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
}


def _anchor(identifier: str = "statement:dbs-2026-05") -> FrameworkPolicyEvidenceAnchor:
    return FrameworkPolicyEvidenceAnchor(
        anchor_id=identifier,
        anchor_type="source_record",
        source_system="test_fixture",
        source_id=identifier,
        description="Fixture source evidence",
    )


def _fact(
    domain: PolicyFactDomain, *, instrument_type: str = "fixture", fact_id: str | None = None
) -> FrameworkPolicyFact:
    return FrameworkPolicyFact(
        fact_id=fact_id or f"fact-{domain.value}",
        domain=domain,
        instrument_type=instrument_type,
        amount=Decimal("100.00"),
        currency="SGD",
        event_date=date(2026, 5, 31),
        anchors=[_anchor(f"source:{domain.value}")],
    )


def test_AC20_3_1_policy_schema_validation_errors() -> None:
    with pytest.raises(ValidationError, match="missing required policy dimensions"):
        FrameworkPolicyDecision(
            domain=PolicyFactDomain.CASH,
            recognition="Recognize.",
            measurement="Measure.",
            classification="Cash.",
            presentation="BS cash.",
            disclosure=None,
            line_mappings={"balance_sheet": "assets.cash_and_cash_equivalents"},
            evidence_anchors=[_anchor()],
        )
    incomplete = FrameworkPolicyDecision.model_construct(
        domain=PolicyFactDomain.CASH,
        recognition="R.",
        measurement="M.",
        classification="C.",
        presentation="P.",
        disclosure=None,
        line_mappings={"balance_sheet": "assets.cash"},
    )
    bad_decision = FrameworkPolicyDecision(
        domain=PolicyFactDomain.CASH,
        recognition="R.",
        measurement="M.",
        classification="C.",
        presentation="P.",
        disclosure="D.",
        line_mappings={"balence_sheet": "assets.cash_and_cash_equivalents"},
        evidence_anchors=[_anchor()],
    )
    bad_rule = _rule(
        domain=PolicyFactDomain.CASH,
        supported_instrument_types=["cash"],
        recognition="R.",
        measurement="M.",
        classification="C.",
        presentation="P.",
        disclosure="D.",
        line_mappings={"balence_sheet": "assets.cash_and_cash_equivalents"},
        required_evidence=[],
        disclosure_requirements=[],
        blocker_conditions=[],
    )
    assert bad_rule.required_evidence == bad_rule.disclosure_requirements == bad_rule.blocker_conditions == []
    with pytest.raises(ValidationError, match="unknown statement target 'balence_sheet'"):
        FrameworkPolicyMatrix(framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE, version="test", rules=[bad_rule])
    for kwargs, match in (
        ({"framework_id": PersonalReportingFrameworkId.US_GAAP_LIKE, "decisions": [incomplete]}, "cash.disclosure"),
        ({"framework_id": "cn_cas_like", "decisions": []}, None),
        (
            {"framework_id": PersonalReportingFrameworkId.US_GAAP_LIKE, "decisions": [bad_decision]},
            "unknown statement target",
        ),
    ):
        with pytest.raises(ValidationError, match=match):
            FrameworkPolicyResult(
                result_id="policy-result:test",
                matrix_version="test",
                generated_at=date(2026, 6, 1),
                required_statements=["balance_sheet"],
                **_PERIOD,
                **kwargs,
            )


@pytest.mark.parametrize("framework_id", list(PersonalReportingFrameworkId))
def test_AC20_3_1_policy_matrix_covers_all_domains_and_dimensions(framework_id: PersonalReportingFrameworkId) -> None:
    matrix = get_framework_policy_matrix(framework_id)
    assert _REQUIRED_DOMAINS <= {rule.domain for rule in matrix.rules}
    assert all(
        set(rule.policy_by_dimension) == set(PolicyDimension)
        and rule.line_mappings
        and rule.required_evidence
        and rule.disclosure_requirements
        and rule.blocker_conditions
        for rule in matrix.rules
    )


def test_AC20_3_1_policy_derivation_determinism_and_gaps() -> None:
    facts = [
        _fact(PolicyFactDomain.CASH),
        _fact(PolicyFactDomain.LISTED_SECURITY, instrument_type="listed_equity"),
        _fact(PolicyFactDomain.FX, instrument_type="fx_transaction"),
    ]
    original = deepcopy([f.model_dump(mode="json") for f in facts])
    first = derive_framework_policy_result(PersonalReportingFrameworkId.US_GAAP_LIKE, facts=facts, **_PERIOD)
    second = derive_framework_policy_result(PersonalReportingFrameworkId.US_GAAP_LIKE, facts=facts, **_PERIOD)
    assert [f.model_dump(mode="json") for f in facts] == original
    assert first == second
    assert first.gaps == []
    assert {d.provenance for d in first.decisions} == {PolicyProvenance.DETERMINISTIC_MATRIX}
    assert {d.review_state for d in first.decisions} == {PolicyReviewState.ACCEPTED}

    base_d = first.decisions[0]
    base_id = _result_id(
        PersonalReportingFrameworkId.US_GAAP_LIKE, matrix_version="1.0", decisions=[base_d], gaps=[], **_PERIOD
    )
    assert base_id != _result_id(
        PersonalReportingFrameworkId.US_GAAP_LIKE,
        matrix_version="1.0",
        decisions=[base_d.model_copy(update={"presentation": "Changed."})],
        gaps=[],
        **_PERIOD,
    )
    assert base_id != _result_id(
        PersonalReportingFrameworkId.US_GAAP_LIKE, matrix_version="1.1", decisions=[base_d], gaps=[], **_PERIOD
    )

    gap_res = derive_framework_policy_result(
        PersonalReportingFrameworkId.US_GAAP_LIKE,
        facts=[_fact(PolicyFactDomain.LISTED_SECURITY, instrument_type="private_token", fact_id="fact-private-token")],
        **_PERIOD,
    )
    assert gap_res.decisions == [] and len(gap_res.gaps) == 1
    gap = gap_res.gaps[0]
    assert (gap.code, gap.blocker, gap.fact_id) == ("unsupported_policy_domain", True, "fact-private-token")
    assert "market value" not in gap.remediation.lower()


def test_AC20_7_1_same_settlement_fixture_drives_us_hk_report_policy_outputs() -> None:
    facts = [
        _fact(PolicyFactDomain.CASH, instrument_type="bank_account"),
        _fact(PolicyFactDomain.LISTED_SECURITY, instrument_type="listed_equity"),
        _fact(PolicyFactDomain.DIVIDEND_INTEREST, instrument_type="dividend"),
        _fact(PolicyFactDomain.BROKERAGE_FEE, instrument_type="brokerage_fee"),
        _fact(PolicyFactDomain.RESTRICTED_COMPENSATION, instrument_type="rsu"),
        _fact(PolicyFactDomain.UNSUPPORTED, instrument_type="private_token", fact_id="settlement:private-token"),
    ]
    us_res = derive_framework_policy_result(PersonalReportingFrameworkId.US_GAAP_LIKE, facts=facts, **_PERIOD)
    hk_res = derive_framework_policy_result(PersonalReportingFrameworkId.HKFRS_LIKE, facts=facts, **_PERIOD)
    us_d = {d.domain: d for d in us_res.decisions}
    hk_d = {d.domain: d for d in hk_res.decisions}
    assert us_res.matrix_version == hk_res.matrix_version == "2.0"
    assert (
        us_res.required_statements
        == hk_res.required_statements
        == [
            "balance_sheet",
            "income_statement",
            "cash_flow",
            "notes",
            "traceability_appendix",
        ]
    )
    assert us_d[PolicyFactDomain.LISTED_SECURITY].line_mappings["balance_sheet"] == "assets.marketable_securities"
    assert (
        hk_d[PolicyFactDomain.LISTED_SECURITY].line_mappings["balance_sheet"] == "assets.financial_assets_at_fair_value"
    )
    assert us_d[PolicyFactDomain.LISTED_SECURITY].line_mappings["notes"] == "notes.us_like_market_price_basis"
    assert hk_d[PolicyFactDomain.LISTED_SECURITY].line_mappings["notes"] == "notes.hk_like_fair_value_basis"
    assert "US-like" in us_d[PolicyFactDomain.LISTED_SECURITY].presentation
    assert "HK-like" in hk_d[PolicyFactDomain.LISTED_SECURITY].presentation
    assert "disclose" in us_d[PolicyFactDomain.DIVIDEND_INTEREST].disclosure.lower()
    assert "disclose" in hk_d[PolicyFactDomain.RESTRICTED_COMPENSATION].disclosure.lower()
    assert {g.code for g in us_res.gaps} == {g.code for g in hk_res.gaps} == {"unsupported_policy_domain"}
    assert us_res.result_id != hk_res.result_id


@pytest.mark.parametrize("framework", list(PersonalReportingFrameworkId))
@pytest.mark.parametrize(
    ("resolver", "enum_cls", "attr"),
    [
        (_position_domain_and_instrument, AssetType, "asset_type"),
        (_manual_domain_and_instrument, ManualValuationComponentType, "component_type"),
    ],
)
def test_AC20_8_1_every_instrument_and_component_maps_to_l1_line(
    framework: PersonalReportingFrameworkId, resolver, enum_cls, attr: str
) -> None:
    matrix = get_framework_policy_matrix(framework)
    for member in enum_cls:
        domain, instrument = resolver(SimpleNamespace(**{attr: member}))
        assert domain != PolicyFactDomain.UNSUPPORTED
        rule = _find_rule(matrix, SimpleNamespace(domain=domain, instrument_type=instrument))
        assert rule is not None and rule.line_mappings, (framework.value, member.value, domain, instrument)
