"""AC-audit.44.1: the two digest helpers keep the stored bytes of the private copies they replaced (#2768).

Every hex string below came from the OLD code at origin/main ec21172c2, captured before the
helpers existed: the six private `_digest` copies and the inline SHA-256 expressions. The old
copies of one family returned the same bytes on every input (`_digest` of
`extraction/base/reviewed_statement_envelope`, `extraction/extension/reviewed_statement_envelope`
and `pricing/extension/valuation_contribution` for canonical JSON; `_digest` of
`extraction/extension/disposition_trace`, `extraction/extension/extraction_trace` and
`reporting/base/package_decision` for text), so one value per family and input stands for all copies.
A change that breaks either family fails here.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from src.audit import canonical_json_digest, text_digest

UUID1 = UUID("12345678-1234-5678-1234-567812345678")
UUID2 = UUID("87654321-4321-8765-4321-876543218765")
NOW = datetime(2026, 10, 27, 8, 30, tzinfo=UTC)

# (text, text_digest of the text, canonical_json_digest of the text)
TEXT_CASES = [
    (
        "extraction:CODE-ONLY:exact:v1",
        "d1872759bd4bce354e96ebfb86a46ebae4e0210f7601e44c9c24f6ff903b2be6",
        "fe1816f1102c33453f74c0cb9564c809c78ec85eb3c6ac86aa7cfef1a28629f9",
    ),
    (
        "reviewed-statement-envelope:CODE-ONLY:exact:v1",
        "7eada8b15748ac904728c7cf00f0f319063fd4b99c343264ea376b0f7e7af4a0",
        "9cb6e4c92aceede709df2115459de8fa41598190135f00436a221ca1d4a5dfd3",
    ),
    (
        "reporting:personal-report-package:2026-07-18",
        "a3d82d289bffe6128bd51ad4cf83f370f25b4b3cd1af928f5f96c8fee5cef023",
        "215ab480870743f082500762fcaf57527093258a99b8ea9232b6d6f59105d0e6",
    ),
    (
        "Caf\u00e9 \u6771\u4eac \u2603 \u00a51,234.50",
        "db0459a224030556d4bd342aebe35d6a051084042463d60c55fe3c95e70ec532",
        "707617edd7480000330655be68e880f4597a4a68babec8e2ef5c20c6f2834fd4",
    ),
    (
        "",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "12ae32cb1ec02d01eda3581b127c1fee3b0dc53572ed6baf239721a03d82e126",
    ),
    (
        '{"a":1,"b":[1,2]}',
        "8baa73198470c7bb4c3ce142a8fd651affc0310d878bb9bd159e37a573fb4874",
        "479fc50f059e2b3315efd2f5776274eb8bf00b4d8cf42404f5e5f4f84e22c9ea",
    ),
    (
        'line1\nline2\t"quoted" \\ backslash',
        "4ba4863eeb0812d2bd0edbe2a7e3f088083397a603ae71235ccbec6dc3faecd3",
        "549f02fec7f12d8f513fb886c809d339573cafdd57ab2c5eaee5a32e66cb4462",
    ),
    # Outer whitespace, a final newline and decomposed characters are part of the hashed text:
    # a `strip()` or a Unicode normalization inside the helper changes these values (F4 of the review).
    (
        "  padded rationale \t",
        "724ebd68117bee91ea93a97592b8178ecad9bb4f5860d8156485ca410ee39a56",
        "8603ef5d0aba2c572ee599c0da64e7b8ea4bcd66dc64d8e2b4b6c208e73df037",
    ),
    (
        "line one\nline two\n",
        "e9024f1a07d29d52ad3aa5e1a18e94db1f3a9fd32b89e39d47c472cd99071e13",
        "6a10268c3f05a61efc2d5c18bad7f80a325a5ce817c9de2dfcaa29325dd46b4a",
    ),
    (
        "Café au lait",
        "5115efe6f30b1a6a4b510ed44d077697130e474f579db48d74e1c63dd86ead7d",
        "86a1ec2ae8c521a6aaf8e0475843de35797c3a43df8ae9fbd6564f2507d0add0",
    ),
    (
        "Café au lait",
        "793e7643ce558259f6fe71f9ecaaf268acbcd011a2bb4c7f561df05a133d4d08",
        "ec4e3a21f9ed67dd864e66d8fd6e6277e77bb8dbdb7c18e931c70baee9b6ad14",
    ),
]

OBJECTS = {
    "flat": {"package": "pricing", "policy": "valuation-attestation", "producer_version": "1"},
    "flat_reordered": {"producer_version": "1", "policy": "valuation-attestation", "package": "pricing"},
    "nested": {
        "value": "1234.50",
        "note": "Caf\u00e9 \u6771\u4eac \u2603",
        "nested": {"b": ["x", 1, None, True, False], "a": {"z": "0.10", "y": "1e-7"}},
        "empty_str": "",
        "none": None,
        "int": 0,
        "neg": -3,
    },
    "floats": {"value": 0.1 + 0.2, "big": 1e22, "small": 1e-7, "int_like": 1.0},
    "default_str": {
        "id": UUID1,
        "date": date(2026, 10, 27),
        "dt": datetime(2026, 10, 27, 8, 30, tzinfo=UTC),
        "amount": Decimal("10.50"),
    },
    "list_top": [1, "a", None, {"k": "v"}],
    "empty_dict": {},
    "str_value": "extraction:CODE-ONLY:exact:v1",
    "codepoint_order": {"\u00e9": 1, "Z": 2, "a": 3},
}
# canonical_json_digest of each object in OBJECTS
OBJECT_DIGESTS = {
    "flat": "96b00c594009839c762e1049ea37ec68334441826c6e186ce1dca09b6c8fe83b",
    "flat_reordered": "96b00c594009839c762e1049ea37ec68334441826c6e186ce1dca09b6c8fe83b",
    "nested": "f56c8a2a6a8e6c0b0f9f5d1cc223b3aa006fe594fc0bfaa6055d4d5d9f68a289",
    "floats": "5d805e5a4b16d367aa801718bd723dc3834ce4dbf5c9982eb05f59f303520baf",
    "default_str": "9741c3952c78bcd5f60e20dde59dd5d5198bccc8afae3957514904d6bdf4a0ec",
    "list_top": "420f663f3f9b40f4d51bc118151987a6b061aba71b60a0d6273a629650ffde12",
    "empty_dict": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    "str_value": "fe1816f1102c33453f74c0cb9564c809c78ec85eb3c6ac86aa7cfef1a28629f9",
    "codepoint_order": "98d2046520ba4a7caa7dad1c90d3cd522cd01ca5f279fc7b668a2ef13534d820",
}
# `default=str` turns these values into text. Every other object holds JSON values only.
NEEDS_DEFAULT_STR = {"default_str"}


@pytest.mark.parametrize(("text", "expected", "_canonical"), TEXT_CASES)
def test_AC_audit_44_1_text_digest_keeps_the_old_bytes(text: str, expected: str, _canonical: str):
    """AC-audit.44.1: text_digest returns the SHA-256 hex of the raw UTF-8 string."""
    assert text_digest(text) == expected


@pytest.mark.parametrize(("text", "_text_digest", "expected"), TEXT_CASES)
def test_AC_audit_44_1_canonical_digest_of_a_string_keeps_the_quotes(text: str, _text_digest: str, expected: str):
    """AC-audit.44.1: the canonical text of a string has quotes, so its digest differs from text_digest."""
    assert canonical_json_digest(text) == expected
    assert canonical_json_digest(text) == text_digest(json.dumps(text))
    assert canonical_json_digest(text) != text_digest(text)


@pytest.mark.parametrize("name", sorted(OBJECTS))
def test_AC_audit_44_1_canonical_json_digest_keeps_the_old_bytes(name: str):
    """AC-audit.44.1: canonical_json_digest returns the SHA-256 hex of sorted, compact JSON."""
    default = str if name in NEEDS_DEFAULT_STR else None

    assert canonical_json_digest(OBJECTS[name], default=default) == OBJECT_DIGESTS[name]


@pytest.mark.parametrize(
    "value",
    [datetime(2026, 10, 27, 8, 30, tzinfo=UTC), date(2026, 10, 27), UUID1, Decimal("10.50")],
    ids=["datetime", "date", "uuid", "decimal"],
)
def test_AC_audit_44_1_canonical_json_digest_rejects_a_value_json_cannot_encode(value: object):
    """AC-audit.44.1: without `default`, a non-JSON value raises TypeError, as the replaced code did."""
    with pytest.raises(TypeError):
        canonical_json_digest({"value": value})

    assert canonical_json_digest({"value": value}, default=str) == canonical_json_digest({"value": str(value)})


@pytest.mark.parametrize("name", sorted(set(OBJECTS) - NEEDS_DEFAULT_STR))
def test_AC_audit_44_1_text_of_compact_sorted_json_equals_the_canonical_digest(name: str):
    """AC-audit.44.1: both families agree where the old callers combined them."""
    value = OBJECTS[name]
    text = json.dumps(value, sort_keys=True, separators=(",", ":"))

    assert text_digest(text) == canonical_json_digest(value) == OBJECT_DIGESTS[name]


def test_AC_audit_44_1_key_order_does_not_change_the_digest():
    """AC-audit.44.1: reordered keys give the same digest."""
    assert canonical_json_digest(OBJECTS["flat"]) == canonical_json_digest(OBJECTS["flat_reordered"])
    assert list(OBJECTS["flat"]) != list(OBJECTS["flat_reordered"])


def test_AC_audit_44_1_default_str_changes_the_digest_of_a_value_with_text_form():
    """AC-audit.44.1: a UUID, date, datetime and Decimal hash as their `str` form."""
    as_text = {key: str(value) for key, value in OBJECTS["default_str"].items()}

    assert canonical_json_digest(OBJECTS["default_str"], default=str) == canonical_json_digest(as_text)
    with pytest.raises(TypeError):
        canonical_json_digest(OBJECTS["default_str"])


# --- the stored values of the callers (each comes from the real code path) ---


def _envelope_command_digest() -> str:
    from src.extraction.base.reviewed_statement_envelope import ReviewedStatementEnvelopeCommand

    return ReviewedStatementEnvelopeCommand(
        source_result_digest="a" * 64,
        account_id=UUID1,
        currency="sgd",
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1234.50"),
        rationale="Caf\u00e9 \u6771\u4eac statement ok",
    ).digest


def _disposition_authority() -> str:
    from src.extraction.extension.disposition_trace import _authority

    return _authority(
        tier="CODE-ONLY", proof_kind="exact", provenance="deterministic", producer_version="1"
    ).assertion_owner_digest


def _extraction_authority() -> str:
    from src.extraction.extension.extraction_trace import _authority

    return _authority(
        tier="CODE-ONLY", proof_kind="exact", provenance="deterministic", producer_version="1"
    ).assertion_owner_digest


def _envelope_authority() -> str:
    from src.extraction.extension.reviewed_statement_envelope import _authority

    return _authority(
        tier="CODE-ONLY", proof_kind="exact", provenance="deterministic", execution_stage="product.runtime"
    ).assertion_owner_digest


def _package_authority() -> str:
    from src.reporting.base.package_decision import PackageReadinessDecisionPolicy

    return PackageReadinessDecisionPolicy().authority.assertion_owner_digest


def _valuation_authority_manual() -> str:
    from src.pricing.extension.valuation_contribution import _authority

    return _authority(provenance="manual", stage="manual.adjudication", producer_version="1").assertion_owner_digest


def _valuation_authority_system() -> str:
    from src.pricing.extension.valuation_contribution import _system_authority

    return _system_authority().assertion_owner_digest


def _observation():
    from src.pricing.base.observation import Authority, ObservationSource, PriceObservation
    from src.pricing.base.subject import PriceableSubject

    return PriceObservation(
        subject=PriceableSubject.security("ACME"),
        value=Decimal("125.2500"),
        as_of=date(2026, 10, 1),
        observed_at=datetime(2026, 10, 2, 9, 30, tzinfo=UTC),
        source=ObservationSource.MANUAL,
        authority=Authority.MANUAL,
        currency="USD",
        id=UUID1,
    )


def _valuation_observation_version() -> str:
    from src.pricing.extension.valuation_contribution import valuation_observation_version

    return valuation_observation_version(_observation())


def _resolved_market_valuation_target() -> list[str]:
    from src.pricing.base.policy import ResolutionPolicy
    from src.pricing.extension.valuation_contribution import resolved_market_valuation_target

    target = resolved_market_valuation_target(
        subject=_observation().subject,
        requested_as_of=date(2026, 10, 1),
        policy=ResolutionPolicy(),
        observation=_observation(),
    )
    return [target.id, target.version]


def _pricing_valuation_lineage_id() -> str:
    from src.pricing.base.observation import pricing_valuation_lineage_id

    return pricing_valuation_lineage_id(subject=_observation().subject, source="manual", as_of=date(2026, 10, 1))


def _package_target_version() -> str:
    from src.reporting.base.package_decision import personal_report_package_target

    return personal_report_package_target(
        snapshot_id=UUID1,
        context={"currency": "SGD", "note": "Caf\u00e9"},
        framework_policy={"framework": "x", "version": "1"},
        statement_disposition_policy={"mode": "enforce"},
        input_manifest=[{"id": "b", "n": 2}, {"id": "a", "n": 1}],
        sections={"balance_sheet": {"total": "1.00"}},
    ).version


def _journal_command_target() -> str:
    from src.ledger.base.decision_anchor import journal_command_target

    return journal_command_target(
        entry_date=date(2026, 10, 1),
        memo="Caf\u00e9 \u6771\u4eac",
        lines_data=[
            {"account_id": UUID1, "direction": "DEBIT", "amount": "10.50", "currency": "sgd", "fx_rate": "1.0"},
            {"account_id": UUID1, "direction": "CREDIT", "amount": 10.5, "event_type": "x", "tags": ["a"]},
        ],
        base_currency="sgd",
        source_identity="statement:1",
    ).version


def _anchored_owner_manual() -> str:
    from src.ledger.extension.anchored_posting import ManualJournalAttestationPolicy

    return ManualJournalAttestationPolicy().authority.assertion_owner_digest


def _opening_authority() -> str:
    from src.ledger.extension.opening_positions import OpeningPositionPolicy

    return OpeningPositionPolicy().authority.assertion_owner_digest


def _position_digest() -> str:
    from src.ledger.extension.opening_positions import position_digest

    return position_digest(
        account_id=UUID1,
        effective_date=date(2026, 10, 1),
        amount=Decimal("100.50"),
        currency="SGD",
        fx_rate=Decimal("1.3500"),
        journal_entry_id=UUID1,
        source_decision_id=None,
    )


def _reviewed_disposition_command_digest() -> str:
    from src.extraction import EconomicIntent
    from src.reconciliation.base import ReviewedDispositionCommand
    from src.reconciliation.extension.reviewed_disposition import _command_digest

    return _command_digest(
        ReviewedDispositionCommand(
            intent=EconomicIntent.EXPENSE,
            counter_account_id=UUID1,
            category=" Caf\u00e9 ",
            rationale=" because ",
        )
    )


def _policy_snapshot():
    from src.extraction.base.disposition import DispositionMode, StatementDispositionPolicySnapshot

    return StatementDispositionPolicySnapshot(
        schema_version="1",
        policy_version="p1",
        mode=DispositionMode.ENFORCE,
        machine_confidence_threshold=Decimal("0.90"),
        pnl_effect_confidence_threshold=Decimal("0.95"),
        unknown_intent_outcome="review",
        ambiguous_intent_outcome="review",
        live_llm_proposals_enabled=False,
        deployment_git_sha="abc123",
    )


def _decision(*, with_command: bool):
    from src.extraction import EconomicIntent
    from src.extraction.base.disposition import (
        DispositionCommand,
        DispositionDecision,
        DispositionMode,
        DispositionStatus,
    )

    if with_command:
        return DispositionDecision(
            transaction_id=UUID1,
            policy_version="p1",
            status=DispositionStatus.AUTHORITATIVE,
            intent=EconomicIntent.EXPENSE,
            category="Caf\u00e9",
            reason_code="rule",
            command=DispositionCommand(counter_account_id=UUID1, debit_role="counter", credit_role="custody"),
            pnl_effect=True,
            mode=DispositionMode.ENFORCE,
        )
    return DispositionDecision(
        transaction_id=UUID1,
        policy_version="p1",
        status=DispositionStatus.REVIEW,
        intent=EconomicIntent.UNKNOWN,
        category=None,
        reason_code="unknown",
        command=None,
        pnl_effect=False,
        mode=DispositionMode.OBSERVE,
    )


def _snapshot_semantic_digest() -> str:
    return _policy_snapshot().semantic_digest


def _decision_semantic_digest() -> str:
    return _decision(with_command=True).semantic_digest


def _decision_semantic_digest_no_command() -> str:
    return _decision(with_command=False).semantic_digest


def _statement_result():
    from tests.extraction.test_statement_result_contract import _complete_result

    return _complete_result()


def _statement_result_content_digest() -> str:
    return _statement_result().content_digest


def _statement_result_id() -> str:
    return str(_statement_result().result_id)


def _brokerage_snapshot():
    from src.extraction.extension.brokerage_positions import BrokeragePositionSnapshot

    return BrokeragePositionSnapshot(
        snapshot_date=date(2026, 10, 1),
        asset_identifier="ACME",
        broker="Example Broker",
        quantity=Decimal("2.5000"),
        market_value=Decimal("125.25"),
        currency="USD",
    )


def _brokerage_dedup_hash() -> str:
    from src.extraction.extension.brokerage_positions import _dedup_hash

    return _dedup_hash(UUID1, _brokerage_snapshot())


def _result_contract_position_id() -> str:
    from src.extraction.extension.result_contract import _position_id

    return _position_id(_brokerage_snapshot())


def _cash_flow_line_id() -> str:
    from src.reporting.extension.cash_flow import cash_flow_line_id

    return cash_flow_line_id({"category": "OPERATING", "description": "Caf\u00e9 \u6771\u4eac in", "account_id": UUID1})


def _terminal_audit_policy_version() -> str:
    from src.audit.extension.terminal_audit import TERMINAL_AUDIT_POLICY_VERSION

    return TERMINAL_AUDIT_POLICY_VERSION


def _framework_result_id(*, reverse_gaps: bool) -> str:
    from src.reporting.base.types import PersonalReportingFrameworkId
    from src.reporting.extension.framework_policy import _result_id
    from src.schemas.reporting import FrameworkPolicyDecision, FrameworkPolicyGap, PolicyFactDomain

    domain = list(PolicyFactDomain)[0]
    gap_a = FrameworkPolicyGap(
        code="a", fact_id="f2", domain=domain, instrument_type="t", blocker=True, reason="Caf\u00e9", remediation="r"
    )
    gap_b = FrameworkPolicyGap(
        code="b", fact_id="f1", domain=domain, instrument_type="t", blocker=False, reason="r", remediation="r"
    )
    decision = FrameworkPolicyDecision(
        domain=domain,
        recognition="r",
        measurement="m",
        classification="c",
        presentation="p",
        disclosure="d",
        line_mappings={"x": "y"},
    )
    return _result_id(
        list(PersonalReportingFrameworkId)[0],
        matrix_version="v1",
        report_period_start=date(2026, 1, 1),
        report_period_end=date(2026, 12, 31),
        decisions=[decision],
        gaps=[gap_b, gap_a] if reverse_gaps else [gap_a, gap_b],
    )


def _framework_result_id_in_order() -> str:
    return _framework_result_id(reverse_gaps=False)


def _framework_result_id_reversed() -> str:
    return _framework_result_id(reverse_gaps=True)


def _disposition_records(*, with_proposal: bool, execution_id: str):
    from src.extraction import EconomicIntent
    from src.extraction.base.disposition import IntentProposal, IntentProposalOrigin, StatementTransaction
    from src.extraction.base.source_vocabulary import TransactionDirection
    from src.extraction.extension.disposition_trace import build_disposition_trace_records

    transaction = StatementTransaction(
        transaction_id=UUID2,
        transaction_date=date(2026, 10, 1),
        amount=Decimal("10.50"),
        currency="SGD",
        direction=next(iter(TransactionDirection)),
        description="Caf\u00e9 \u6771\u4eac",
    )
    proposal = IntentProposal(
        schema_version="1",
        policy_version="p1",
        origin=IntentProposalOrigin.REVIEWED_RULE,
        intent=EconomicIntent.EXPENSE,
        category="Dining",
        confidence=Decimal("0.97"),
        evidence=("rule:cafe", "merchant:Caf\u00e9"),
    )
    from src.extraction.base.disposition import (
        DispositionCommand,
        DispositionDecision,
        DispositionMode,
        DispositionStatus,
    )

    decision = DispositionDecision(
        transaction_id=UUID2,
        policy_version="p1",
        status=DispositionStatus.AUTHORITATIVE,
        intent=EconomicIntent.EXPENSE,
        category="Dining",
        reason_code="rule",
        command=DispositionCommand(counter_account_id=UUID1, debit_role="counter", credit_role="custody"),
        pnl_effect=True,
        mode=DispositionMode.ENFORCE,
    )
    return build_disposition_trace_records(
        user_id=UUID1,
        execution_id=execution_id,
        occurred_at=NOW,
        transaction=transaction,
        proposal=proposal if with_proposal else None,
        decision=decision,
        policy_snapshot=_policy_snapshot(),
    )


def _disposition_record_ids() -> list[str]:
    return [str(r.record_id) for r in _disposition_records(with_proposal=True, execution_id="exec-1")]


def _disposition_evidence_digests() -> list[str]:
    return [r.evidence_manifest_digest for r in _disposition_records(with_proposal=True, execution_id="exec-1")]


def _disposition_target_version() -> str:
    return _disposition_records(with_proposal=True, execution_id="exec-1")[0].target.version


def _disposition_record_ids_no_proposal() -> list[str]:
    return [str(r.record_id) for r in _disposition_records(with_proposal=False, execution_id="exec-2")]


def _disposition_evidence_digests_no_proposal() -> list[str]:
    return [r.evidence_manifest_digest for r in _disposition_records(with_proposal=False, execution_id="exec-2")]


def _extraction_record_ids() -> list[str]:
    from src.extraction.extension.extraction_trace import build_extraction_trace_records

    records = build_extraction_trace_records(_statement_result(), user_id=UUID1, execution_id="exec-3", occurred_at=NOW)
    return [str(r.record_id) for r in records]


# label -> (function that runs the real code path, value stored before #2768)
CALLER_DIGESTS = {
    "ReviewedStatementEnvelopeCommand.digest": (
        _envelope_command_digest,
        "fae3bd9f48d6667830b154a61cc08f961a870192254a940698e274a1289aeee1",
    ),
    "disposition_trace._authority": (
        _disposition_authority,
        "c624ea40aee27e8970287eeb2b420f1af17bb7c6d775ca47789f7cf44a2427ca",
    ),
    "extraction_trace._authority": (
        _extraction_authority,
        "d1872759bd4bce354e96ebfb86a46ebae4e0210f7601e44c9c24f6ff903b2be6",
    ),
    "reviewed_statement_envelope._authority": (
        _envelope_authority,
        "9cb6e4c92aceede709df2115459de8fa41598190135f00436a221ca1d4a5dfd3",
    ),
    "PackageReadinessDecisionPolicy.authority": (
        _package_authority,
        "a3d82d289bffe6128bd51ad4cf83f370f25b4b3cd1af928f5f96c8fee5cef023",
    ),
    "valuation_contribution._authority": (
        _valuation_authority_manual,
        "96b00c594009839c762e1049ea37ec68334441826c6e186ce1dca09b6c8fe83b",
    ),
    "valuation_contribution._system_authority": (
        _valuation_authority_system,
        "aa819e4610241bb97d9422f681ca9c1e27fab86f740003c7f0da9b41e4a674ea",
    ),
    "valuation_observation_version": (
        _valuation_observation_version,
        "2af5d2f59190908f50f64a93dbd9e058ae9a8a785978cf5ba77ea6fd2c540268",
    ),
    "resolved_market_valuation_target": (
        _resolved_market_valuation_target,
        [
            "pricing-resolution:2fab890b57c5ac0b4ede61c03752c65888134149b3d44c9cb0dcfb097b33b6f0",
            "cd23cb02eeb2169e62eb959c7bcfad0d37c96a0a2bb047fac3e29aa1fed5a72e",
        ],
    ),
    "pricing_valuation_lineage_id": (
        _pricing_valuation_lineage_id,
        "manual-valuation:39f269a23aef0ef3fbdbe16df086776eb17fb16a688dd67e5b5bc9f81f87bbab",
    ),
    "personal_report_package_target": (
        _package_target_version,
        "9add24123abe78359af8056b4e0906a9e0236e3177303e56e757e3c0bd8e0aa9",
    ),
    "journal_command_target": (
        _journal_command_target,
        "ba7b1323ddb62f672b30e8baa1b0c87d050d20e33af2ef51c171f8778656ca5a",
    ),
    "ManualJournalAttestationPolicy.authority": (
        _anchored_owner_manual,
        "24dd1537fc5015acd5c7b5085b560a620100df5c37e2f8d6258fc5884222dea5",
    ),
    "OpeningPositionPolicy.authority": (
        _opening_authority,
        "5242750b6642477bd1a1238d6c48ebe3e4bad6f107fc5ed062cfdbd90852df99",
    ),
    "position_digest": (_position_digest, "51f258c07bb2d4802b27a3b5b7df50c3eb970a0498a2b5e22683a44864ce2efd"),
    "reviewed_disposition._command_digest": (
        _reviewed_disposition_command_digest,
        "875b4bc6c7221561bfdf372cb89cb5ec0972749022d14d16c5627b742228d617",
    ),
    "StatementDispositionPolicySnapshot.semantic_digest": (
        _snapshot_semantic_digest,
        "33e3fa5997187f9f19748ea839ea51dbb02707ae18a60e16a5a9a5a864c91652",
    ),
    "DispositionDecision.semantic_digest": (
        _decision_semantic_digest,
        "c30ca61477b31688041cfb37b689e988ccefcc429d9d8e600cb15b79a4bf8fcd",
    ),
    "DispositionDecision.semantic_digest (no command)": (
        _decision_semantic_digest_no_command,
        "8a3337d219f311c759efeee470e7c2f571a931a7ba7dd29ef87fc1a8657bc58d",
    ),
    "StatementExtractionResult.content_digest": (
        _statement_result_content_digest,
        "30c086c1e1681026d519dd5cf3327cebea418bf3c419b074ca94fc40d2ed5249",
    ),
    "StatementExtractionResult.result_id": (_statement_result_id, "c59d02fe-1398-5bc6-83db-64cbf78184aa"),
    "brokerage_positions._dedup_hash": (
        _brokerage_dedup_hash,
        "4b68676833517ee008dc6ef59d7981b9fba0d2b4404bde78a4ba6294e4341cf9",
    ),
    "result_contract._position_id": (
        _result_contract_position_id,
        "10d4c1fa2c2db642c0996b916f98cb4e3aa1c056e5896db0ea6f9ba2b55ed24a",
    ),
    "cash_flow_line_id": (_cash_flow_line_id, "operating-3fdc557715bad514"),
    "TERMINAL_AUDIT_POLICY_VERSION": (
        _terminal_audit_policy_version,
        "50a4746c0dee2fc94f48c2bbf6c468bcabda0de5797f99f08a9ea25aba1ad039",
    ),
    "framework_policy._result_id": (
        _framework_result_id_in_order,
        "policy-result:personal_us_gaap_like:2026-01-01:2026-12-31:adbe7855d6bb22de",
    ),
    "framework_policy._result_id (gaps reversed)": (
        _framework_result_id_reversed,
        "policy-result:personal_us_gaap_like:2026-01-01:2026-12-31:adbe7855d6bb22de",
    ),
    "build_disposition_trace_records: record ids": (
        _disposition_record_ids,
        [
            "c1efb1d7-80b7-5c44-a3e3-215ebc437e13",
            "676a872d-ecc6-51b8-a81e-cb7e4d52ef9d",
            "4b8e4ff6-d9b7-566c-8e40-9869b207024f",
            "91ccf3d0-b443-5e0f-b9ab-44779bb0defd",
        ],
    ),
    "build_disposition_trace_records: evidence digests": (
        _disposition_evidence_digests,
        [
            "864e73dbdd2135051195a4987ab539ef6fa74d060c5d573e75c59f29998f71ba",
            "1bc35b240b869c56902074c341839bd7f50a578746a42e1b0e142cc90172be53",
            "20305fc37ab0c22210ef92e14e1eb2096ee190966e949a092c3b21b01e2d75b1",
            "1ec6588dc78d0beacfeacd664eb9cdc854a543fd7d5fdfe9b22708073c622c43",
        ],
    ),
    "build_disposition_trace_records: target version": (
        _disposition_target_version,
        "5f84147b44ee17ea21813a198c6f3c6cf054782fb1861bb6d465b5e8cfa759a7",
    ),
    "build_disposition_trace_records: record ids, no proposal": (
        _disposition_record_ids_no_proposal,
        [
            "584ccc29-cd9d-5765-8eb6-00f0c0a2f7da",
            "e4b5e1bb-0342-56e4-af87-4fda7422f8fc",
            "86abbe0b-536c-5431-9735-0f48599b8bf0",
            "220b6cc5-7de7-5b53-80b5-a6df6f32a136",
        ],
    ),
    "build_disposition_trace_records: evidence digests, no proposal": (
        _disposition_evidence_digests_no_proposal,
        [
            "b820ff47b8d2c1c67744d0dfb692bae9bfef1405a435515cc1928af2704ce503",
            "1bc35b240b869c56902074c341839bd7f50a578746a42e1b0e142cc90172be53",
            "0416acf009f66befc781b5169b6bb138796682574c505ced597665f42d6b4c27",
            "b3ff08dcf0c3d63e0651b444e0e9ee3afb394c5130538fccaad398ba399df733",
        ],
    ),
    "build_extraction_trace_records: record ids": (
        _extraction_record_ids,
        [
            "38967b23-9979-5951-9c62-536f8e983c10",
            "09567563-0dd3-53ef-9068-e5b9b3945bee",
            "2b2d44e7-5524-55a6-8dad-0395a2e12db0",
            "c11d91f0-2b33-5c97-bba4-dd5fd751effb",
        ],
    ),
}


@pytest.mark.parametrize("label", sorted(CALLER_DIGESTS))
def test_AC_audit_44_1_callers_keep_their_stored_digests(label: str):
    """AC-audit.44.1: each caller returns the value that it stored before the helpers existed."""
    produce, expected = CALLER_DIGESTS[label]

    assert produce() == expected


def test_AC_audit_44_1_the_reviewed_envelope_owner_digest_stays_json_quoted():
    """AC-audit.44.1: the stored `assertion_owner_digest` of the reviewed envelope hashes the quoted string.

    This path is the only caller that passes a string to the canonical digest. `text_digest` would
    return another value and break every stored reviewed-envelope trace record.
    """
    owner = "reviewed-statement-envelope:CODE-ONLY:exact:v1"

    assert _envelope_authority() == canonical_json_digest(owner)
    assert _envelope_authority() == "9cb6e4c92aceede709df2115459de8fa41598190135f00436a221ca1d4a5dfd3"
    assert _envelope_authority() != text_digest(owner)


# --- the other stored hashes that now use text_digest (F1, F2 and F4 of the review) ---

DEDUP_CASES = {
    "plain": (
        {"description": "Coffee Shop", "amount": Decimal("5.00"), "balance_after": Decimal("100.50")},
        "ef2e4fd4be569298c4d03e07e2e41b250c9e55a696ec7bd112cc06594e1587ad",
    ),
    "no_balance": (
        {"description": "Coffee Shop", "amount": Decimal("5.00"), "balance_after": None},
        "4ab61c2126fe88e9c8f21156fe01ad6fd6adcc17c6af386e22b48df0f2e6582c",
    ),
    "non_ascii": (
        {
            "description": "  Café 東京 MÜNCHEN  ",
            "amount": Decimal("1234.50"),
            "balance_after": Decimal("0"),
        },
        "40cee87c48563352eb9a3122f6bc8ecfef3a0035d476cc1fb861e2727c510217",
    ),
    "second_occurrence": (
        {
            "description": "Coffee Shop",
            "amount": Decimal("5"),
            "balance_after": Decimal("100.5"),
            "occurrence_index": 1,
        },
        "42482422f77450bfbba402eaa3240a782eade24d5cdb8c35218776018ad6e7ed",
    ),
    "third_no_balance": (
        {
            "description": "Coffee Shop",
            "amount": Decimal("5"),
            "balance_after": None,
            "occurrence_index": 2,
            "reference": "REF é 1",
        },
        "c5bdc5008f3d873a5df51ba988aac0a6ce0f919ddc4b3438869b583d3865e054",
    ),
    "other_direction": (
        {
            "description": "Coffee Shop",
            "amount": Decimal("5.00"),
            "balance_after": Decimal("100.50"),
            "direction": "OUT",
        },
        "b59b32ee6e7f9336dc9ebfd086c62b2a67b4e7fb5439c81be786a8b711030f4d",
    ),
    "scoped": (
        {
            "description": "Coffee Shop 東京",
            "amount": Decimal("5.00"),
            "balance_after": Decimal("100.50"),
            "currency": "sgd",
            "custody_scope": "account:12345678-1234-5678-1234-567812345678",
        },
        "7ef90e0389faa745d123f455504faf41a160eca9af4769c9eeada929fecf830a",
    ),
}


@pytest.mark.parametrize("name", sorted(DEDUP_CASES))
def test_AC_audit_44_1_transaction_dedup_hash_keeps_the_stored_bytes(name: str):
    """AC-audit.44.1: the stored `dedup_hash` of an atomic transaction does not change."""
    from src.extraction.base.source_vocabulary import TransactionDirection
    from src.extraction.extension.deduplication import DeduplicationService

    arguments, expected = DEDUP_CASES[name]
    arguments = dict(arguments)
    direction = TransactionDirection(arguments.pop("direction", "IN"))
    amount = arguments.pop("amount")
    description = arguments.pop("description")

    assert (
        DeduplicationService.calculate_transaction_hash(
            UUID1, date(2026, 10, 1), amount, direction, description, **arguments
        )
        == expected
    )


@pytest.mark.parametrize(
    ("currency", "custody_scope", "expected"),
    [
        (" sgd ", "account:abc", "ccaad068344a2a5b78f9ff567b9bf949312bfc2e669062d451316b2ecda9fe58"),
        ("usd", "source:東京-é", "deeddff1add134d094dbe11d994a6de44139fe0be5db5a2aef4b631cac23ac5f"),
    ],
    ids=["ascii", "non_ascii_scope"],
)
def test_AC_audit_44_1_transaction_identity_hash_keeps_the_stored_bytes(
    currency: str, custody_scope: str, expected: str
):
    """AC-audit.44.1: the versioned custody hash of an atomic transaction does not change."""
    from src.extraction.base.normalization_engine import compute_transaction_identity_hash

    legacy_hash = DEDUP_CASES["plain"][1]

    assert compute_transaction_identity_hash(legacy_hash, currency, custody_scope) == expected


@pytest.mark.asyncio
async def test_AC_audit_44_1_workflow_source_fingerprint_keeps_the_settings_digest(monkeypatch: pytest.MonkeyPatch):
    """AC-audit.44.1: the fingerprint keeps its stored bytes: a text digest of the settings, and its own JSON form."""
    from types import SimpleNamespace

    from src.workflow.extension import source_fingerprint

    class _Settings:
        def model_dump_json(self) -> str:
            return '{"env":"test","note":"Café 東京","n":1}'

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 27)

    class _Db:
        async def execute(self, statement):
            return [
                SimpleNamespace(source="accounts", row_count=3, row_stamp="1.5"),
                SimpleNamespace(source="journal", row_count=0, row_stamp="0"),
            ]

    monkeypatch.setattr(source_fingerprint, "settings", _Settings())
    monkeypatch.setattr(source_fingerprint, "date", _FixedDate)

    fingerprint = await source_fingerprint.workflow_source_fingerprint(_Db(), user_id=UUID1)

    assert fingerprint == "c7b46a45505d9c0f2c1cc14042f3ce134af8c2a1b029261bd204fcf5d1a1d76e"


MANUAL_RATIONALE = "  Café verified 東京 \n"


@pytest.mark.asyncio
async def test_AC_audit_44_1_manual_rationale_digest_keeps_outer_whitespace_and_composition(db, test_user):
    """AC-audit.44.1: the stored rationale digest of a manual journal attestation hashes the exact text."""
    from src.audit import SqlTraceRecordRepository, TraceDecisionPolicyRegistry, TraceScope
    from src.ledger.extension.anchored_posting import ManualJournalAttestationPolicy, manual_journal_decision_anchor

    anchor = await manual_journal_decision_anchor(
        db,
        user_id=test_user.id,
        entry_date=date(2026, 10, 1),
        memo="Café",
        rationale=MANUAL_RATIONALE,
        lines_data=[
            {"account_id": UUID1, "direction": "DEBIT", "amount": Decimal("10.50")},
            {"account_id": UUID2, "direction": "CREDIT", "amount": Decimal("10.50")},
        ],
        base_currency="SGD",
    )
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((ManualJournalAttestationPolicy(),)))
    scope = TraceScope.tenant(test_user.id)
    decision = await repository.get(scope, anchor.decision_id)
    attestation = await repository.get(scope, decision.parent_ids[0])

    assert attestation.evidence_manifest_digest == "308a888cbbde99fe49ae0a782a3c168d2f301eb93acf9ad294e98faa4205ba2f"
    assert attestation.evidence_manifest_digest != text_digest(MANUAL_RATIONALE.strip())


def test_AC_audit_44_1_a_site_without_default_rejects_a_raw_datetime():
    """AC-audit.44.1: sites that never had `default=str` still raise TypeError for a value JSON cannot encode."""
    from src.pricing.base.observation import pricing_valuation_lineage_id
    from src.pricing.base.subject import PriceableSubject
    from src.reporting.base.package_decision import personal_report_package_target

    moment = datetime(2026, 10, 27, 8, 30, tzinfo=UTC)

    with pytest.raises(TypeError):
        personal_report_package_target(
            snapshot_id=UUID1,
            context={"generated_at": moment},
            framework_policy={},
            statement_disposition_policy={},
            input_manifest=[],
            sections={},
        )
    with pytest.raises(TypeError):
        pricing_valuation_lineage_id(
            subject=PriceableSubject.security("ACME"),
            source=moment,  # type: ignore[arg-type]
            as_of=date(2026, 10, 1),
        )


def test_AC_audit_44_1_a_site_with_default_str_hashes_the_text_form():
    """AC-audit.44.1: `journal_command_target` kept `default=str`, so a raw datetime tag hashes as its text."""
    from src.ledger.base.decision_anchor import journal_command_target

    moment = datetime(2026, 10, 27, 8, 30, tzinfo=UTC)

    def version(tag: object) -> str:
        return journal_command_target(
            entry_date=date(2026, 10, 1),
            memo="memo",
            lines_data=[{"account_id": UUID1, "direction": "DEBIT", "amount": "1.00", "tags": [tag]}],
            base_currency="SGD",
            source_identity="statement:1",
        ).version

    assert version(moment) == version(str(moment))
    assert version(moment) != version("other")
