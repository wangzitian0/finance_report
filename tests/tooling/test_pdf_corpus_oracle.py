"""AC-testing.benchmarks.7: Unit tests for the 20-PDF benchmark corpus, generators, and 3-statement mathematical oracle (#2852)."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from common.testing.benchmarks import sync_benchmark_fixtures
from common.testing.benchmarks.pdf_corpus_oracle import (
    DEFAULT_MANIFEST_PATH,
    MECE_DIMENSIONS,
    SEVEN_ACCOUNTING_INVARIANTS,
    ZERO,
    CorpusStatementSpec,
    CorpusTransaction,
    compare_oracle_with_platform_reports,
    compute_independent_three_statement_oracle,
    load_pdf_benchmark_corpus,
    main as oracle_cli_main,
    run_live_pdf_statement_verification,
)
from common.testing.fixtures import generate_test_pdfs

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pdf_corpus_manifest_has_20_pdfs_across_5_mece_dimensions() -> None:
    """AC-testing.benchmarks.7: Verify the 20-PDF corpus covers all 5 MECE dimensions with 5 external + 15 generated PDFs."""
    corpus = load_pdf_benchmark_corpus(DEFAULT_MANIFEST_PATH, REPO_ROOT)
    assert len(corpus) == 20

    ids = [s.fixture_id for s in corpus]
    assert len(set(ids)) == 20, "Duplicate fixture_id in corpus"

    by_dim: dict[str, list[str]] = {d: [] for d in MECE_DIMENSIONS}
    for spec in corpus:
        assert spec.dimension in by_dim, f"Unknown dimension: {spec.dimension}"
        by_dim[spec.dimension].append(spec.fixture_id)

    assert len(by_dim["dimension_1_sg_retail_digital_sgd"]) == 6
    assert len(by_dim["dimension_2_china_hk_cny_hkd"]) == 5
    assert len(by_dim["dimension_3_eu_na_multi_locale"]) == 5
    assert len(by_dim["dimension_4_credit_card_liabilities"]) == 2
    assert len(by_dim["dimension_5_brokerage_and_edge_cases"]) == 2

    external = [s for s in corpus if s.source_platform == "github"]
    generated = [s for s in corpus if s.source_platform == "local_generator"]
    assert len(external) == 5
    assert len(generated) == 15

    # Verify all 15 local_generator PDFs exist on disk and match their pinned SHA-256
    for spec in generated:
        pdf_path = REPO_ROOT / spec.local_path
        assert pdf_path.exists(), f"Missing generated PDF: {spec.local_path}"
        actual_sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        assert actual_sha == spec.sha256, (
            f"SHA-256 mismatch for {spec.fixture_id}: {actual_sha} != {spec.sha256}"
        )
        assert len(spec.transactions) == spec.expected_txn_count


def test_all_20_corpus_specs_use_pure_decimal_and_satisfy_balance_chain() -> None:
    """Verify zero float usage and exact Opening + Inflows - Outflows == Closing for all 20 PDFs."""
    corpus = load_pdf_benchmark_corpus(DEFAULT_MANIFEST_PATH, REPO_ROOT)
    for spec in corpus:
        assert isinstance(spec.opening_balance, Decimal)
        assert isinstance(spec.closing_balance, Decimal)
        assert isinstance(spec.expected_inflows, Decimal)
        assert isinstance(spec.expected_outflows, Decimal)
        assert isinstance(spec.net_movement, Decimal)
        assert spec.expected_inflows - spec.expected_outflows == spec.net_movement
        assert spec.balance_chain_delta == ZERO, (
            f"Broken balance chain on {spec.fixture_id}: delta={spec.balance_chain_delta}"
        )
        for txn in spec.transactions:
            assert isinstance(txn.amount, Decimal)

        # Verify single-statement oracle produces accounting_equation_delta == 0.00
        oracle = compute_independent_three_statement_oracle([spec])
        assert oracle.balance_sheet.accounting_equation_delta == ZERO
        assert (
            oracle.balance_sheet.total_assets - oracle.balance_sheet.total_liabilities
            == oracle.balance_sheet.ending_total_equity
        )
        assert (
            oracle.cash_flow_statement.ending_cash == oracle.balance_sheet.ending_cash
        )


def test_oracle_rejects_float_inputs_strictly() -> None:
    """Falsifiable guard: passing float to CorpusTransaction, CorpusStatementSpec, or tolerance raises TypeError."""
    with pytest.raises(TypeError, match="Decimal"):
        CorpusTransaction(
            date="2025-01-01",
            description="Bad float",
            amount=12.34,  # type: ignore[arg-type]
            direction="IN",
        )

    corpus = load_pdf_benchmark_corpus(DEFAULT_MANIFEST_PATH, REPO_ROOT)
    oracle = compute_independent_three_statement_oracle([corpus[0]])
    with pytest.raises(TypeError, match="tolerance must be Decimal"):
        compare_oracle_with_platform_reports(
            oracle,
            balance_sheet={},
            income_statement={},
            cash_flow={},
            tolerance=0.05,  # type: ignore[arg-type]
        )


def test_dbs_gap_creation_and_3198_convergence_to_zero() -> None:
    """Verify 3198 Unexplained Statement Gap Equity is +2757.95 when Feb is missing and 0.00 when filled."""
    corpus = {
        s.fixture_id: s
        for s in load_pdf_benchmark_corpus(DEFAULT_MANIFEST_PATH, REPO_ROOT)
    }
    dbs_jan = corpus["dbs_statement_fixture"]
    dbs_feb = corpus["dbs_feb_gap_filler"]
    dbs_mar = corpus["dbs_mar_jump"]
    gxs_mar = corpus["gxs_statement_fixture"]

    # Phase 1: Upload DBS Jan + DBS Mar + GXS Mar (Feb missing -> +2,757.95 SGD gap)
    phase1_oracle = compute_independent_three_statement_oracle(
        [dbs_jan, dbs_mar, gxs_mar],
        as_of_date="2025-03-31",
        period_start="2025-01-01",
        period_end="2025-03-31",
        report_currency="SGD",
    )
    assert phase1_oracle.balance_sheet.ending_cash == Decimal("29209.21")
    assert phase1_oracle.balance_sheet.opening_balance_equity_3199 == Decimal(
        "20500.00"
    )
    assert phase1_oracle.balance_sheet.unexplained_gap_equity_3198 == Decimal("2757.95")
    assert phase1_oracle.balance_sheet.net_income == Decimal("5951.26")
    assert phase1_oracle.balance_sheet.accounting_equation_delta == ZERO

    # Phase 2: Upload DBS Feb gap-filler -> 3198 converges to 0.00 and Net Income increases by +2757.95
    phase2_oracle = compute_independent_three_statement_oracle(
        [dbs_jan, dbs_feb, dbs_mar, gxs_mar],
        as_of_date="2025-03-31",
        period_start="2025-01-01",
        period_end="2025-03-31",
        report_currency="SGD",
    )
    assert phase2_oracle.balance_sheet.ending_cash == Decimal("29209.21")
    assert phase2_oracle.balance_sheet.opening_balance_equity_3199 == Decimal(
        "20500.00"
    )
    assert phase2_oracle.balance_sheet.unexplained_gap_equity_3198 == ZERO
    assert phase2_oracle.balance_sheet.net_income == Decimal("8709.21")
    assert phase2_oracle.balance_sheet.accounting_equation_delta == ZERO


def test_pingan_investing_and_transfer_clearing_oracle() -> None:
    """Verify PingAn Bank CNY statement separates investing cash flows and transfer clearing assets."""
    corpus = {
        s.fixture_id: s
        for s in load_pdf_benchmark_corpus(DEFAULT_MANIFEST_PATH, REPO_ROOT)
    }
    pingan = corpus["pingan_statement_fixture"]

    oracle = compute_independent_three_statement_oracle(
        [pingan],
        treat_transfers_as_clearing_asset=True,
    )
    # Cash: 8000 -> 31122 CNY
    assert oracle.balance_sheet.ending_cash == Decimal("31122.00")
    assert oracle.balance_sheet.opening_balance_equity_3199 == Decimal("8000.00")
    # Investing: purchases (1661 + 1783 = 3444) - redemptions (3439 + 2451 = 5890) -> -2446 non-cash asset delta, +2446 investing CF
    assert oracle.balance_sheet.non_cash_investing_assets == Decimal("-2446.00")
    assert oracle.cash_flow_statement.investing_cash_flow == Decimal("2446.00")
    # Transfers + Card repayment routed to clearing asset: 1397 + 1967 + 1781 = 5145.00
    assert oracle.balance_sheet.transfer_clearing_assets == Decimal("5145.00")
    # P&L: Salary (26815) + Interest (10) - QuickPay (1004) = 25821.00
    assert oracle.income_statement.total_income == Decimal("26825.00")
    assert oracle.income_statement.total_expenses == Decimal("1004.00")
    assert oracle.income_statement.net_income == Decimal("25821.00")
    assert oracle.balance_sheet.accounting_equation_delta == ZERO


def test_credit_card_liability_and_fx_translation_oracle() -> None:
    """Verify credit card liability statements and multi-currency FX translation preserve equation_delta == 0.00."""
    corpus = {
        s.fixture_id: s
        for s in load_pdf_benchmark_corpus(DEFAULT_MANIFEST_PATH, REPO_ROOT)
    }
    sg_card = corpus["sg_credit_card_sgd"]
    maribank = corpus["maribank_statement_fixture"]
    sparkasse = corpus["de_sparkasse_eur"]

    card_oracle = compute_independent_three_statement_oracle([maribank, sg_card])
    assert card_oracle.balance_sheet.ending_cash == Decimal("3114.29")
    assert card_oracle.balance_sheet.total_liabilities == Decimal("650.00")
    assert card_oracle.balance_sheet.opening_balance_equity_3199 == Decimal("3000.00")
    assert card_oracle.balance_sheet.accounting_equation_delta == ZERO

    fx_oracle = compute_independent_three_statement_oracle(
        [sparkasse],
        report_currency="SGD",
        fx_rates={"EUR/SGD": Decimal("1.45")},
    )
    assert fx_oracle.balance_sheet.currency == "SGD"
    assert fx_oracle.balance_sheet.opening_balance_equity_3199 == Decimal("9280.00")
    assert fx_oracle.balance_sheet.ending_cash == Decimal("11527.86")
    assert fx_oracle.balance_sheet.accounting_equation_delta == ZERO

    # Verify full-precision 4-decimal FX rate (e.g. 0.1850) is NOT truncated to 0.19
    cny_fx_oracle = compute_independent_three_statement_oracle(
        [corpus["pingan_statement_fixture"]],
        report_currency="SGD",
        fx_rates={"CNY/SGD": Decimal("0.1850")},
        treat_transfers_as_clearing_asset=True,
    )
    assert cny_fx_oracle.balance_sheet.opening_balance_equity_3199 == Decimal("1480.00")
    assert cny_fx_oracle.balance_sheet.ending_cash == Decimal("5757.58")
    assert cny_fx_oracle.balance_sheet.accounting_equation_delta == ZERO


def test_compare_oracle_with_platform_reports_verifies_all_7_invariants() -> None:
    """Verify pass and falsifiable failure detection for each of the 7 accounting invariants."""
    corpus = {
        s.fixture_id: s
        for s in load_pdf_benchmark_corpus(DEFAULT_MANIFEST_PATH, REPO_ROOT)
    }
    dbs_jan = corpus["dbs_statement_fixture"]
    oracle = compute_independent_three_statement_oracle([dbs_jan])

    valid_bs = {
        "total_assets": "15242.05",
        "ending_cash": "15242.05",
        "total_liabilities": "0.00",
        "total_equity": "12000.00",
        "opening_balance_equity_3199": "12000.00",
        "unexplained_gap_equity_3198": "0.00",
        "net_income": "3242.05",
        "equation_delta": "0.00",
        "is_balanced": True,
    }
    valid_is = {
        "total_income": "6100.00",
        "total_expenses": "2857.95",
        "net_income": "3242.05",
    }
    valid_cf = {
        "beginning_cash": "0.00",
        "operating_cash_flow": "3242.05",
        "opening_stock_adjustment": "12000.00",
        "ending_cash": "15242.05",
    }

    res = compare_oracle_with_platform_reports(
        oracle,
        balance_sheet=valid_bs,
        income_statement=valid_is,
        cash_flow=valid_cf,
        translated_balance_sheet=valid_bs,
        retirement_cleanup_statuses=[200],
    )
    assert res.passed is True
    assert tuple(v.invariant_id for v in res.invariants) == SEVEN_ACCOUNTING_INVARIANTS
    assert res.to_dict()["passed"] is True

    # Falsify each invariant independently:
    # 1. Unbalanced BS
    r1 = compare_oracle_with_platform_reports(
        oracle,
        balance_sheet={**valid_bs, "total_assets": "16000.00"},
        income_statement=valid_is,
        cash_flow=valid_cf,
    )
    assert not r1.passed
    assert any("fundamental_accounting_equation" in f for f in r1.failures)

    # 2. Cash Flow ending cash mismatch
    r2 = compare_oracle_with_platform_reports(
        oracle,
        balance_sheet=valid_bs,
        income_statement=valid_is,
        cash_flow={**valid_cf, "ending_cash": "14000.00"},
    )
    assert not r2.passed
    assert any("cash_flow_to_balance_sheet_cash" in f for f in r2.failures)

    # 3. Retained earnings vs IS net income mismatch
    r3 = compare_oracle_with_platform_reports(
        oracle,
        balance_sheet=valid_bs,
        income_statement={**valid_is, "net_income": "1000.00"},
        cash_flow=valid_cf,
    )
    assert not r3.passed
    assert any("retained_earnings_to_net_income" in f for f in r3.failures)

    # 4. Statement balance chain mismatch (Opening + Inflows - Outflows != Closing)
    broken_chain_oracle = compute_independent_three_statement_oracle(
        [
            CorpusStatementSpec(
                fixture_id="broken_chain_stmt",
                dimension=dbs_jan.dimension,
                source_platform=dbs_jan.source_platform,
                local_path=dbs_jan.local_path,
                sha256=dbs_jan.sha256,
                institution=dbs_jan.institution,
                account_key=dbs_jan.account_key,
                doc_type=dbs_jan.doc_type,
                currency=dbs_jan.currency,
                period_start=dbs_jan.period_start,
                period_end=dbs_jan.period_end,
                opening_balance=dbs_jan.opening_balance,
                closing_balance=Decimal("15000.00"),
                expected_txn_count=dbs_jan.expected_txn_count,
                expected_inflows=dbs_jan.expected_inflows,
                expected_outflows=dbs_jan.expected_outflows,
                net_movement=dbs_jan.net_movement,
                transactions=dbs_jan.transactions,
            )
        ]
    )
    r4 = compare_oracle_with_platform_reports(
        broken_chain_oracle,
        balance_sheet=valid_bs,
        income_statement=valid_is,
        cash_flow=valid_cf,
    )
    assert not r4.passed
    assert any("statement_balance_chain" in f for f in r4.failures)

    # 5. 3198 gap equity mismatch
    r5 = compare_oracle_with_platform_reports(
        oracle,
        balance_sheet={**valid_bs, "unexplained_gap_equity_3198": "500.00"},
        income_statement=valid_is,
        cash_flow=valid_cf,
    )
    assert not r5.passed
    assert any("gap_equity_3198_convergence" in f for f in r5.failures)

    # 6. 3199 FX round-trip distortion
    r6 = compare_oracle_with_platform_reports(
        oracle,
        balance_sheet={**valid_bs, "opening_balance_equity_3199": "11998.12"},
        income_statement=valid_is,
        cash_flow=valid_cf,
    )
    assert not r6.passed
    assert any("native_vs_translated_fx_consistency" in f for f in r6.failures)

    # 7. Statement DELETE 500 failure
    r7 = compare_oracle_with_platform_reports(
        oracle,
        balance_sheet=valid_bs,
        income_statement=valid_is,
        cash_flow=valid_cf,
        retirement_cleanup_statuses=[500],
    )
    assert not r7.passed
    assert any("statement_retirement_cleanup" in f for f in r7.failures)


def test_live_pdf_statement_verification_and_cli_runner() -> None:
    """Verify run_live_pdf_statement_verification and CLI entrypoint with mocked HTTP client."""
    corpus = {
        s.fixture_id: s
        for s in load_pdf_benchmark_corpus(DEFAULT_MANIFEST_PATH, REPO_ROOT)
    }
    dbs_jan = corpus["dbs_statement_fixture"]

    mock_client = MagicMock()

    def _resp(status_code: int, payload: dict[str, Any]) -> MagicMock:
        r = MagicMock()
        r.status_code = status_code
        r.json.return_value = payload
        r.text = str(payload)
        return r

    mock_client.post.side_effect = [
        _resp(201, {"id": "stmt-dbs-1"}),
        _resp(200, {"status": "confirmed"}),
        _resp(200, {"status": "approved"}),
    ]
    mock_client.get.side_effect = [
        _resp(
            200,
            {
                "id": "stmt-dbs-1",
                "status": "parsed",
                "preclassification_in_progress": False,
                "source_envelope_confirmation_required": True,
                "source_result_digest": "dig-1",
                "account_id": "acc-1",
                "currency": "SGD",
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
                "opening_balance": "12000.00",
                "closing_balance": "15242.05",
            },
        ),
        _resp(
            200,
            {
                "total_assets": "15542.05",
                "ending_cash": "15242.05",
                "total_liabilities": "0.00",
                "total_equity": "12000.00",
                "opening_balance_equity_3199": "12000.00",
                "unexplained_gap_equity_3198": "0.00",
                "net_income": "3542.05",
                "assets": [
                    {"code": "1110", "name": "DBS Bank", "amount": "15242.05"},
                    {
                        "code": "1190",
                        "name": "Transfers in transit",
                        "amount": "300.00",
                    },
                ],
                "equity": [
                    {
                        "code": "3199",
                        "name": "Opening Balance Equity",
                        "amount": "12000.00",
                    },
                    {
                        "code": "3198",
                        "name": "Unexplained Statement Gap Equity",
                        "amount": "0.00",
                    },
                ],
                "equation_delta": "0.00",
                "is_balanced": True,
            },
        ),
        _resp(
            200,
            {
                "total_income": "6100.00",
                "total_expenses": "2557.95",
                "net_income": "3542.05",
            },
        ),
        _resp(
            200,
            {
                "beginning_cash": "0.00",
                "operating_cash_flow": "3242.05",
                "opening_stock_adjustment": "12000.00",
                "ending_cash": "15242.05",
            },
        ),
        _resp(
            200,
            {
                "total_assets": "15542.05",
                "total_liabilities": "0.00",
                "total_equity": "12000.00",
                "net_income": "3542.05",
                "equation_delta": "0.00",
                "is_balanced": True,
            },
        ),
    ]
    mock_client.delete.return_value = _resp(204, {})

    live_res = run_live_pdf_statement_verification(
        mock_client,
        dbs_jan,
        root_dir=REPO_ROOT,
    )
    assert live_res["fixture_id"] == "dbs_statement_fixture"
    assert live_res["delete_status"] == 204
    assert live_res["comparison"]["passed"] is True

    # Offline CLI execution
    assert oracle_cli_main(["--fixture", "dbs_statement_fixture"]) == 0
    assert oracle_cli_main(["--fixture", "nonexistent_fixture"]) == 2


def test_sync_benchmark_fixtures_handles_local_generator_and_draw_tables(
    tmp_path: Path,
) -> None:
    """Verify sync_benchmark_fixtures local_generator branch and new table renderers in generate_test_pdfs."""
    sample_pdf = tmp_path / "local.pdf"
    sample_pdf.write_bytes(b"%PDF-1.4 deterministic bytes")
    sha = sync_benchmark_fixtures.compute_sha256(sample_pdf.read_bytes())

    fixture_entry = {
        "id": "local_test",
        "source_platform": "local_generator",
        "local_path": "local.pdf",
        "sha256": sha,
    }
    dummy_client = MagicMock()
    assert (
        sync_benchmark_fixtures.download_fixture(
            dummy_client, fixture_entry, tmp_path, force=True
        )
        is True
    )
    dummy_client.get.assert_not_called()

    # Verify new format helpers in generate_test_pdfs
    assert generate_test_pdfs.mm_dd_yyyy("2025-03-18") == "03/18/2025"
    assert generate_test_pdfs.de_date_str("2025-03-18") == "18.03.2025"
    assert generate_test_pdfs.money_de_str(Decimal("1234.56")) == "1.234,56"

    # Verify missing local_generator file fails cleanly
    missing_entry = {
        "id": "missing_local",
        "source_platform": "local_generator",
        "local_path": "nonexistent.pdf",
        "sha256": sha,
    }
    assert (
        sync_benchmark_fixtures.download_fixture(
            dummy_client, missing_entry, tmp_path, force=True
        )
        is False
    )

    # Verify existing file without force returns True
    assert (
        sync_benchmark_fixtures.download_fixture(
            dummy_client, fixture_entry, tmp_path, force=False
        )
        is True
    )


def test_sync_benchmark_fixtures_cli_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify sync_benchmark_fixtures.main --verify, --clean, and sync modes."""
    monkeypatch.setattr(sync_benchmark_fixtures, "REPO_ROOT", tmp_path)
    gen_pdf = tmp_path / "gen.pdf"
    gen_pdf.write_bytes(b"%PDF-gen")
    ext_pdf = tmp_path / "ext.pdf"
    ext_pdf.write_bytes(b"%PDF-ext")

    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        f"""
version: "2.2"
benchmark_suite: "test_suite"
fixtures:
  - id: "gen_doc"
    source_platform: "local_generator"
    local_path: "gen.pdf"
    sha256: "{sync_benchmark_fixtures.compute_sha256(b"%PDF-gen")}"
  - id: "ext_doc"
    source_platform: "github"
    local_path: "ext.pdf"
    download_url: "https://example.invalid/ext.pdf"
    sha256: "{sync_benchmark_fixtures.compute_sha256(b"%PDF-ext")}"
""",
        encoding="utf-8",
    )

    # 1. --verify passes when both exist
    assert (
        sync_benchmark_fixtures.main(["--manifest", str(manifest_file), "--verify"])
        == 0
    )

    # 2. default sync passes when files already exist
    assert sync_benchmark_fixtures.main(["--manifest", str(manifest_file)]) == 0

    # 3. --clean deletes ext.pdf but preserves local_generator gen.pdf
    assert (
        sync_benchmark_fixtures.main(["--manifest", str(manifest_file), "--clean"]) == 0
    )
    assert gen_pdf.exists()
    assert not ext_pdf.exists()

    # 4. --verify fails when ext.pdf is missing
    assert (
        sync_benchmark_fixtures.main(["--manifest", str(manifest_file), "--verify"])
        == 1
    )

    # 5. Missing manifest raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        sync_benchmark_fixtures.load_manifest(tmp_path / "missing.yaml")


def test_pdf_corpus_oracle_edge_branches_and_live_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify edge validation branches, BS asset/equity extraction, and --app-url CLI mode."""
    from common.testing.benchmarks import pdf_corpus_oracle as pco

    with pytest.raises(TypeError, match="Monetary value must be Decimal"):
        pco._q2("10.00")  # type: ignore[arg-type]

    # Verify banker's rounding (ROUND_HALF_EVEN) on half-cent ties and float FX rejection
    assert pco._q2(Decimal("2.005")) == Decimal("2.00")
    assert pco._q2(Decimal("2.015")) == Decimal("2.02")
    with pytest.raises(TypeError, match="float is forbidden for FX rates"):
        pco._to_rate_dec(0.185)  # type: ignore[arg-type]
    assert pco._to_rate_dec("0.1850") == Decimal("0.1850")

    with pytest.raises(ValueError, match="Invalid direction"):
        CorpusTransaction(
            date="2025-01-01",
            description="Bad dir",
            amount=Decimal("10.00"),
            direction="SIDEWAYS",
        )

    with pytest.raises(TypeError, match="must be Decimal"):
        CorpusStatementSpec(
            fixture_id="bad",
            dimension=MECE_DIMENSIONS[0],
            source_platform="local_generator",
            local_path="x.pdf",
            sha256="0" * 64,
            institution="DBS",
            account_key="DBS:1",
            doc_type="bank_statement",
            currency="SGD",
            period_start="2025-01-01",
            period_end="2025-01-31",
            opening_balance=100.0,  # type: ignore[arg-type]
            closing_balance=Decimal("100.00"),
            expected_txn_count=1,
            expected_inflows=Decimal("0.00"),
            expected_outflows=Decimal("0.00"),
            net_movement=Decimal("0.00"),
        )

    with pytest.raises(ValueError, match="statements must not be empty"):
        compute_independent_three_statement_oracle([])

    with pytest.raises(ValueError, match="Missing fx_rates"):
        pco._convert_currency(Decimal("10.00"), "EUR", "SGD", None)

    with pytest.raises(ValueError, match="FX rate not found"):
        pco._convert_currency(Decimal("10.00"), "EUR", "SGD", {"USD": Decimal("1.35")})

    assert pco._convert_currency(
        Decimal("10.00"), "EUR", "SGD", {"EUR": Decimal("1.45")}
    ) == Decimal("14.50")

    # Verify _extract_bs_cash and _extract_equity_code_amount when top-level keys are omitted
    bs_with_rows = {
        "total_assets": "15542.05",
        "total_liabilities": "0.00",
        "total_equity": "12000.00",
        "net_income": "3542.05",
        "assets": [
            {"code": "1110", "name": "DBS Bank", "amount": "15242.05"},
            {"code": "1190", "name": "Transfers in transit", "amount": "300.00"},
        ],
        "equity": [
            {"code": "3199", "name": "Opening Balance Equity", "amount": "12000.00"},
        ],
        "equation_delta": "0.00",
        "is_balanced": True,
    }
    assert pco._extract_bs_cash(bs_with_rows) == Decimal("15242.05")
    assert pco._extract_equity_code_amount(bs_with_rows, "3199") == Decimal("12000.00")
    assert pco._extract_equity_code_amount(bs_with_rows, "3198") == ZERO
    assert pco._extract_equity_code_amount({"total_equity": "12000.00"}, "3198") is None

    # Verify multi-month Cash Flow beginning_cash when period_start is after first statement
    corpus = {
        s.fixture_id: s
        for s in load_pdf_benchmark_corpus(DEFAULT_MANIFEST_PATH, REPO_ROOT)
    }
    dbs_jan = corpus["dbs_statement_fixture"]
    dbs_feb = corpus["dbs_feb_gap_filler"]
    mar_only_oracle = compute_independent_three_statement_oracle(
        [dbs_jan, dbs_feb],
        as_of_date="2025-02-28",
        period_start="2025-02-01",
        period_end="2025-02-28",
        report_currency="SGD",
    )
    assert mar_only_oracle.cash_flow_statement.beginning_cash == Decimal("15242.05")
    assert mar_only_oracle.cash_flow_statement.ending_cash == Decimal("18000.00")

    # Verify CLI --app-url with mocked httpx.Client
    class FakeHttpxClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.headers: dict[str, str] = {}

        def __enter__(self) -> FakeHttpxClient:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(self, url: str, **kwargs: object) -> Any:
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {"access_token": "tok-1", "id": "stmt-1"}
            return r

    monkeypatch.setattr(pco.httpx, "Client", FakeHttpxClient)
    monkeypatch.setattr(
        pco,
        "run_live_pdf_statement_verification",
        lambda client, spec, root_dir: {
            "fixture_id": spec.fixture_id,
            "statement_id": "stmt-1",
            "delete_status": 200,
            "comparison": {"passed": True, "failures": []},
        },
    )
    assert (
        oracle_cli_main(
            [
                "--app-url",
                "https://report-staging.zitian.party",
                "--fixture",
                "dbs_statement_fixture",
            ]
        )
        == 0
    )


def test_git_diff_text_handles_non_utf8_pdf_bytes_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify git_diff_text passes encoding='utf-8' and errors='replace' so binary PDF diffs never raise UnicodeDecodeError."""
    import subprocess as sp
    from common.testing.coverage import diff_coverage

    captured_kwargs: dict[str, Any] = {}
    real_run = sp.run

    def _inspecting_run(cmd: list[str], **kwargs: Any) -> Any:
        captured_kwargs.update(kwargs)
        return real_run(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.buffer.write(b'diff --git a/x.pdf b/x.pdf\\n+%PDF-1.4\\n+%\\x93\\x8c\\x8b\\x9e\\n')",
            ],
            **kwargs,
        )

    import sys

    monkeypatch.setattr(diff_coverage.subprocess, "run", _inspecting_run)
    diff_out = diff_coverage.git_diff_text("origin/main", repo_root=tmp_path)
    assert captured_kwargs.get("encoding") == "utf-8"
    assert captured_kwargs.get("errors") == "replace"
    assert "%PDF-1.4" in diff_out
    assert "\ufffd" in diff_out
