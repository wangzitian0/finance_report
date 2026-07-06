from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


FRAMEWORK_SSOT = "docs/ssot/framework-reporting.md"
EPIC_020 = "docs/project/EPIC-020.framework-aware-personal-reporting.md"


def test_AC20_1_1_framework_registry_defines_us_hk_personal_targets() -> None:
    """AC20.1.1: Framework registry defines US/HK personal targets without statutory claims."""
    ssot = read(FRAMEWORK_SSOT)
    epic = read(EPIC_020)

    for text in (ssot, epic):
        assert "personal_us_gaap_like" in text
        assert "personal_hkfrs_like" in text
        assert (
            "not a statutory filing" in text.lower()
            or "does not claim statutory" in text.lower()
        )
    assert "CN/CAS framework output" in ssot
    assert "Explicitly out of scope for v1" in ssot


def test_AC20_2_1_mece_direction_matrix_declares_distinct_owner_lanes() -> None:
    """AC20.2.1: Six-lane fact-forward and target-backward ownership is explicit."""
    ssot = read(FRAMEWORK_SSOT)
    epic = read(EPIC_020)

    for lane in (
        "Source capture",
        "Evidence control",
        "Canonical ledger",
        "Portfolio subledger",
        "Framework policy",
        "Report assembly",
    ):
        assert lane in ssot
        assert lane in epic
    assert ssot.count("Fact-forward") >= 4
    assert ssot.count("Target-backward") >= 2
    assert "mutually exclusive" in epic
    assert "collectively cover" in epic


def test_AC20_3_1_framework_target_contract_is_report_output_backward() -> None:
    """AC20.3.1: Framework target contract works backward from report outputs."""
    ssot = read(FRAMEWORK_SSOT)
    epic = read(EPIC_020)

    assert "required statements and schedules" in ssot
    assert "report line mappings" in ssot
    assert "disclosure requirements and blocker conditions" in ssot
    assert "evidence anchors" in epic
    assert "Target-backward Report Requirements" in epic


def test_AC20_4_1_policy_matrix_covers_personal_finance_domains() -> None:
    """AC20.4.1: Policy matrix covers core personal finance domains and policy dimensions."""
    ssot = read(FRAMEWORK_SSOT)
    epic = read(EPIC_020)

    for domain in (
        "Cash and bank accounts",
        "Listed equities and ETFs",
        "Funds and money-market products",
        "Dividends and interest",
        "Brokerage fees",
        "FX",
        "RSU, ESOP, and options",
        "Property, mortgage, and private/manual assets",
    ):
        assert domain in ssot
    for dimension in (
        "recognition",
        "measurement",
        "classification",
        "presentation",
        "disclosure",
    ):
        assert dimension in ssot.lower()
        assert dimension in epic.lower()


def test_AC20_5_1_policy_layer_is_read_only_between_facts_and_report() -> None:
    """AC20.5.1: Policy consumes facts and must not mutate source ledgers or reports."""
    ssot = read(FRAMEWORK_SSOT)
    epic = read(EPIC_020)

    assert "read-only" in ssot
    for immutable_surface in (
        "source records",
        "journal entries",
        "portfolio lots",
        "market data",
        "report snapshots",
    ):
        assert immutable_surface in ssot
    assert "does not parse settlements" in ssot
    assert "does not parse settlements" in epic


def test_AC20_6_1_ai_suggestions_require_structured_reviewed_policy_fields() -> None:
    """AC20.6.1: AI suggestions need structured fields and review before trusted output."""
    ssot = read(FRAMEWORK_SSOT)
    epic = read(EPIC_020)

    for required_field in (
        "source anchor",
        "confidence tier",
        "review state",
        "policy field name",
        "accepted value",
    ):
        assert required_field in ssot
    assert "must never calculate trusted monetary totals from free-form AI text" in ssot
    assert "AI Measurement and Disclosure Boundary" in epic


def test_AC20_7_1_same_fixture_must_drive_framework_differentiated_reports() -> None:
    """AC20.7.1: Same fixture must support US-like and HK-like differentiated reports."""
    epic = read(EPIC_020)

    assert "same settlement and portfolio fixture" in epic
    assert "US-like and HK-like personal report packages" in epic
    assert "framework-specific line mappings" in epic
    assert "readiness blockers" in epic


def test_AC20_9_1_reporting_pipeline_declares_layer_authority_tiers() -> None:
    """AC20.9.1: The three pipeline layers each declare a locked EPIC-026 tier + proof."""
    epic = read(EPIC_020)

    assert "Reporting Pipeline Authority Tiers" in epic
    # The three layers, named.
    for layer in ("event → L2", "L2 → L1", "L1 → report"):
        assert layer in epic
    # Each layer's locked tier from the EPIC-026 5-tier set.
    for tier in ("**LLM-LED**", "**CODE-LED**", "**CODE-ONLY**"):
        assert tier in epic
    # The tier-appropriate proof obligation per layer.
    assert "no exact-golden" in epic  # LLM-LED
    assert "the **code's** decision" in epic  # CODE-LED
    assert "exact / property test" in epic  # CODE-ONLY
    # LLM authority confined to the LLM-LED layer; CODE-LED is code-authoritative (CODE-ONLY today).
    assert "CODE-ONLY today" in epic
    assert "common/meta/readme.md" in epic


def test_AC2_18_1_canonical_ledger_is_framework_neutral() -> None:
    """AC2.18.1: Canonical ledger remains framework-neutral."""
    epic = read("docs/project/EPIC-002.double-entry-core.md")

    assert "Framework Boundary" in epic
    assert "framework-neutral" in epic
    assert "must not be embedded into posting logic" in epic
    assert "Account codes are canonical user ledger identifiers" in epic


def test_AC3_10_1_statement_parsing_is_source_capture_not_framework_policy() -> None:
    """AC-extraction.10.1: Statement parsing captures evidence and leaves framework policy to EPIC-020."""
    epic = read("docs/project/EPIC-003.statement-parsing.md")

    assert "Framework Boundary" in epic
    assert "source capture" in epic
    assert "period boundaries" in epic
    assert "It does not decide US-like" in epic
    assert "classification, measurement, presentation, or disclosure" in epic


def test_AC5_14_1_reporting_assembles_framework_policy_results_only() -> None:
    """AC5.14.1: Reporting assembles framework policy results without owning policy."""
    epic = read("docs/project/EPIC-005.reporting-visualization.md")

    assert "Framework Policy Result Consumption" in epic
    assert "assembles report packages from framework policy results" in epic
    assert "must not own US/HK" in epic
    assert "recognition, measurement, or classification rules" in epic
    assert "Integration of EPIC-020 framework policy results" in epic


def test_AC17_13_1_portfolio_supplies_facts_not_framework_conclusions() -> None:
    """AC17.13.1: Portfolio supplies facts but not US/HK report conclusions."""
    epic = read("docs/project/EPIC-017.portfolio-management.md")

    assert "Framework boundary" in epic
    assert "supplies portfolio facts" in epic
    assert "inputs to EPIC-020" in epic
    assert "belongs to EPIC-020 and EPIC-005 assembly" in epic
    assert "does not own final US/HK report presentation decisions" in epic


def test_AC18_6_1_ai_suggestions_are_reviewed_before_trusted_framework_use() -> None:
    """AC18.6.1: AI framework suggestions stay structured and reviewed."""
    epic = read("docs/project/EPIC-018.ai-driven-pipeline.md")

    assert "EPIC-020 (Framework-aware reporting)" in epic
    assert "AI may suggest measurement/disclosure evidence" in epic
    assert "AC18.6.1" in epic
    assert "structured, source-anchored, confidence-scored, and reviewed" in epic


def test_AC19_7_1_readiness_consumes_framework_specific_evidence_blockers() -> None:
    """AC19.7.1: Readiness consumes framework-specific blockers before trusted reports."""
    epic = read("docs/project/EPIC-019.event-driven-upload-to-report-ux.md")
    ssot = read(FRAMEWORK_SSOT)

    assert "Framework-Aware Evidence Readiness" in epic
    assert "framework-specific evidence blockers from EPIC-020" in epic
    for blocker in (
        "missing settlement coverage",
        "stale market data",
        "missing valuation basis",
        "AI-only unreviewed policy suggestions",
    ):
        assert blocker in epic
    assert "Framework-aware report readiness must block trusted output" in ssot
