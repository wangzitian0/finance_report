"""LLM valuation-classification contract + gating tests (#1224, EPIC-011 AC11.24).

Deterministic fixtures cover CPF/provident fund, a 401k-style employer plan, a
China social-security personal account, insurance cash value, and an insurance
coverage amount. They prove the bounded schema rejects out-of-contract codes,
that cash value is an asset while coverage is a non-asset excluded from net
worth, that low-confidence output is routed to review, and that prompt/model
versions are persisted.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.constants.valuation_taxonomy import (
    EconomicSide,
    ValuationL1,
    ValuationL2,
    ValuationRole,
)
from src.models.valuation import ValuationReviewStatus
from src.schemas.valuation import ValuationClassificationLLMOutput
from src.services.valuation_classification import (
    REVIEW_CONFIDENCE_THRESHOLD,
    VALUATION_CLASSIFICATION_PROMPT_VERSION,
    build_classification_fields,
    gate_classification,
)


def _payload(**overrides) -> dict:
    base = {
        "raw_label": "CPF Ordinary Account",
        "issuer": "CPF Board",
        "jurisdiction": "SG",
        "scheme_name": "Central Provident Fund",
        "amount": "150000.00",
        "currency": "sgd",
        "as_of_date": "2026-03-31",
        "evidence_spans": [{"page": 1, "text": "OA balance 150,000.00"}],
        "l1": "retirement_and_benefit",
        "l2": "mandatory_retirement",
        "economic_side": "asset",
        "valuation_role": "net_worth_component",
        "liquidity_class": "restricted",
        "confidence": "0.95",
        "rationale": "Statutory retirement balance.",
    }
    base.update(overrides)
    return base


# Deterministic fixtures: (label, overrides, expected (l1, l2, economic_side)).
FIXTURES = {
    "cpf_provident_fund": (
        _payload(),
        (ValuationL1.RETIREMENT_AND_BENEFIT, ValuationL2.MANDATORY_RETIREMENT, EconomicSide.ASSET),
    ),
    "employer_401k": (
        _payload(
            raw_label="Fidelity 401(k)",
            issuer="Fidelity",
            jurisdiction="US",
            scheme_name="401(k)",
            l2="voluntary_retirement",
            confidence="0.93",
        ),
        (ValuationL1.RETIREMENT_AND_BENEFIT, ValuationL2.VOLUNTARY_RETIREMENT, EconomicSide.ASSET),
    ),
    "china_social_security_personal": (
        _payload(
            raw_label="个人社保账户",
            issuer="人力资源和社会保障局",
            jurisdiction="CN",
            scheme_name="社会保险个人账户",
            l2="mandatory_retirement",
            confidence="0.90",
        ),
        (ValuationL1.RETIREMENT_AND_BENEFIT, ValuationL2.MANDATORY_RETIREMENT, EconomicSide.ASSET),
    ),
    "insurance_cash_value": (
        _payload(
            raw_label="Whole-life policy cash value",
            issuer="Prudential",
            scheme_name="WholeLife",
            l2="long_term_benefit",
            confidence="0.88",
        ),
        (ValuationL1.RETIREMENT_AND_BENEFIT, ValuationL2.LONG_TERM_BENEFIT, EconomicSide.ASSET),
    ),
    "insurance_coverage_amount": (
        _payload(
            raw_label="Death benefit coverage",
            issuer="Prudential",
            scheme_name="WholeLife",
            l1="non_asset",
            l2="protection_coverage",
            economic_side="non_asset",
            valuation_role="coverage_amount",
            liquidity_class="illiquid",
            confidence="0.90",
        ),
        (ValuationL1.NON_ASSET, ValuationL2.PROTECTION_COVERAGE, EconomicSide.NON_ASSET),
    ),
}


def test_llm_output_rejects_out_of_contract_codes():
    """AC11.24.1: bounded schema accepts valid output, rejects invented codes."""
    ok = ValuationClassificationLLMOutput.model_validate(_payload())
    assert ok.l1 is ValuationL1.RETIREMENT_AND_BENEFIT
    assert ok.currency == "SGD"  # normalized

    # A jurisdiction/scheme name is not a stable code.
    with pytest.raises(ValidationError):
        ValuationClassificationLLMOutput.model_validate(_payload(l1="cpf"))
    # An L2 that does not roll up to its L1 is rejected.
    with pytest.raises(ValidationError):
        ValuationClassificationLLMOutput.model_validate(_payload(l1="real_estate", l2="mandatory_retirement"))
    # Confidence outside [0, 1] is rejected.
    with pytest.raises(ValidationError):
        ValuationClassificationLLMOutput.model_validate(_payload(confidence="1.4"))


def test_storage_boundary_constraints_are_enforced_at_the_contract():
    """AC11.24.6: amount/currency/confidence/extra match storage so persistence can't fail late."""
    # currency is normalized before the length check ( " usd " -> "USD").
    assert ValuationClassificationLLMOutput.model_validate(_payload(currency=" usd ")).currency == "USD"

    # Negative amount, >2dp amount, non-3-char currency, >4dp confidence, and
    # unknown keys are all rejected at the boundary (match the storage columns).
    for bad in (
        {"amount": "-1.00"},
        {"amount": "10.999"},
        {"currency": "US"},
        {"confidence": "0.95001"},
        {"unexpected_field": "x"},
    ):
        with pytest.raises(ValidationError):
            ValuationClassificationLLMOutput.model_validate(_payload(**bad))


def test_cash_value_is_asset_coverage_amount_excluded_from_net_worth():
    """AC11.24.2: insurance cash value is an asset; coverage is excluded."""
    cash_value = ValuationClassificationLLMOutput.model_validate(FIXTURES["insurance_cash_value"][0])
    cash_gated = gate_classification(cash_value, model_version="glm-4.6v")
    assert cash_value.economic_side is EconomicSide.ASSET
    assert cash_gated.contributes_to_net_worth is True

    coverage = ValuationClassificationLLMOutput.model_validate(FIXTURES["insurance_coverage_amount"][0])
    coverage_gated = gate_classification(coverage, model_version="glm-4.6v")
    assert coverage.economic_side is EconomicSide.NON_ASSET
    assert coverage.valuation_role is ValuationRole.COVERAGE_AMOUNT
    assert coverage_gated.contributes_to_net_worth is False

    # A coverage amount must be non_asset — asset-side coverage is rejected.
    with pytest.raises(ValidationError):
        ValuationClassificationLLMOutput.model_validate(
            _payload(valuation_role="coverage_amount", economic_side="asset")
        )


def test_low_confidence_routes_to_review():
    """AC11.24.3: low confidence enters review; confident output is approved."""
    high = ValuationClassificationLLMOutput.model_validate(_payload(confidence="0.95"))
    assert gate_classification(high, model_version="m").review_status is ValuationReviewStatus.APPROVED

    threshold = str(REVIEW_CONFIDENCE_THRESHOLD - REVIEW_CONFIDENCE_THRESHOLD.__class__("0.10"))
    low = ValuationClassificationLLMOutput.model_validate(_payload(confidence=threshold))
    low_gated = gate_classification(low, model_version="m")
    assert low_gated.review_status is ValuationReviewStatus.PENDING
    assert low_gated.is_trusted_for_reports is False


def test_deterministic_fixtures_classify_to_expected_codes():
    """AC11.24.4: each deterministic fixture parses to its expected stable codes."""
    for label, (payload, expected) in FIXTURES.items():
        output = ValuationClassificationLLMOutput.model_validate(payload)
        assert (output.l1, output.l2, output.economic_side) == expected, label


def test_prompt_and_model_version_persisted():
    """AC11.24.5: prompt + model version flow into the persisted classification."""
    output = ValuationClassificationLLMOutput.model_validate(_payload())
    gated = gate_classification(output, model_version="glm-4.6v")
    fields = build_classification_fields(valuation_fact_id=uuid4(), user_id=uuid4(), gated=gated)
    assert fields["model_version"] == "glm-4.6v"
    assert fields["prompt_version"] == VALUATION_CLASSIFICATION_PROMPT_VERSION
    assert fields["review_status"] is ValuationReviewStatus.APPROVED
    assert fields["l1"] is ValuationL1.RETIREMENT_AND_BENEFIT

    # An over-long version id fails fast at the gate, not at DB flush
    # (matches the String(120) columns).
    with pytest.raises(ValueError):
        gate_classification(output, model_version="x" * 121)
