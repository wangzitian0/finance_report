"""Tests for scripts/analyze_test_ac_coverage.py"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from analyze_test_ac_coverage import (
    suggest_ac,
    extract_test_functions,
    EPIC_MAPPING,
)


class TestSuggestAc:
    """Tests for suggest_ac function - returns AC suggestion based on keywords."""

    def test_accounting_domain_balance_keyword(self):
        epic_info = EPIC_MAPPING["accounting"]
        result = suggest_ac("test_balance_validation", "accounting", epic_info)
        assert "AC2.2.x" in result
        assert "Balance Validation" in result

    def test_accounting_domain_equation_keyword(self):
        epic_info = EPIC_MAPPING["accounting"]
        result = suggest_ac("test_accounting_equation_holds", "accounting", epic_info)
        assert "AC2.2.x" in result

    def test_accounting_domain_void_keyword(self):
        epic_info = EPIC_MAPPING["accounting"]
        result = suggest_ac("test_voided_entry_excluded", "accounting", epic_info)
        assert "AC2.3.x" in result
        assert "Voiding" in result

    def test_accounting_domain_journal_keyword(self):
        epic_info = EPIC_MAPPING["accounting"]
        result = suggest_ac("test_create_journal_entry", "accounting", epic_info)
        assert "AC2.1.x" in result
        assert "Journal Entry" in result

    def test_accounting_domain_default(self):
        epic_info = EPIC_MAPPING["accounting"]
        result = suggest_ac("test_something_unrelated", "accounting", epic_info)
        assert "AC2.x.x" in result
        assert "Accounting Core" in result

    def test_extraction_domain_balance_valid(self):
        epic_info = EPIC_MAPPING["extraction"]
        result = suggest_ac("test_balance_validation_works", "extraction", epic_info)
        assert "AC3.1.x" in result

    def test_extraction_domain_confidence(self):
        epic_info = EPIC_MAPPING["extraction"]
        result = suggest_ac("test_confidence_score_calc", "extraction", epic_info)
        assert "AC3.2.x" in result

    def test_extraction_domain_parse(self):
        epic_info = EPIC_MAPPING["extraction"]
        result = suggest_ac("test_parse_statement", "extraction", epic_info)
        assert "AC3.3.x" in result

    def test_extraction_domain_upload(self):
        epic_info = EPIC_MAPPING["extraction"]
        result = suggest_ac("test_upload_file", "extraction", epic_info)
        assert "AC3.4.x" in result

    def test_reconciliation_domain_score(self):
        epic_info = EPIC_MAPPING["reconciliation"]
        result = suggest_ac("test_score_calculation", "reconciliation", epic_info)
        assert "AC4.2.x" in result

    def test_reconciliation_domain_accept_without_score_in_name(self):
        epic_info = EPIC_MAPPING["reconciliation"]
        result = suggest_ac("test_auto_accept_entry", "reconciliation", epic_info)
        assert "AC4.3.x" in result

    def test_reconciliation_domain_match(self):
        epic_info = EPIC_MAPPING["reconciliation"]
        result = suggest_ac("test_match_transactions", "reconciliation", epic_info)
        assert "AC4.1.x" in result

    def test_reconciliation_domain_anomaly(self):
        epic_info = EPIC_MAPPING["reconciliation"]
        result = suggest_ac("test_anomaly_detection", "reconciliation", epic_info)
        assert "AC4.4.x" in result

    def test_reporting_domain_balance_sheet(self):
        epic_info = EPIC_MAPPING["reporting"]
        result = suggest_ac("test_balance_sheet_report", "reporting", epic_info)
        assert "AC5.1.x" in result

    def test_reporting_domain_income(self):
        epic_info = EPIC_MAPPING["reporting"]
        result = suggest_ac("test_income_statement", "reporting", epic_info)
        assert "AC5.2.x" in result

    def test_reporting_domain_fx(self):
        epic_info = EPIC_MAPPING["reporting"]
        result = suggest_ac("test_fx_conversion", "reporting", epic_info)
        assert "AC5.3.x" in result

    def test_reporting_domain_snapshot(self):
        epic_info = EPIC_MAPPING["reporting"]
        result = suggest_ac("test_financial_snapshot", "reporting", epic_info)
        assert "AC5.4.x" in result

    def test_ai_domain_chat(self):
        epic_info = EPIC_MAPPING["ai"]
        result = suggest_ac("test_chat_response", "ai", epic_info)
        assert "AC6.1.x" in result

    def test_ai_domain_model(self):
        epic_info = EPIC_MAPPING["ai"]
        result = suggest_ac("test_model_selection", "ai", epic_info)
        assert "AC6.2.x" in result

    def test_ai_domain_streaming(self):
        epic_info = EPIC_MAPPING["ai"]
        result = suggest_ac("test_streaming_response", "ai", epic_info)
        assert "AC6.3.x" in result

    def test_ai_domain_advisor(self):
        epic_info = EPIC_MAPPING["ai"]
        result = suggest_ac("test_advisor_recommendation", "ai", epic_info)
        assert "AC6.4.x" in result

    def test_assets_domain_depreciation(self):
        epic_info = EPIC_MAPPING["assets"]
        result = suggest_ac("test_depreciation_calc", "assets", epic_info)
        assert "AC11.2.x" in result

    def test_assets_domain_purchase(self):
        epic_info = EPIC_MAPPING["assets"]
        result = suggest_ac("test_asset_purchase", "assets", epic_info)
        assert "AC11.1.x" in result

    def test_assets_domain_disposal(self):
        epic_info = EPIC_MAPPING["assets"]
        result = suggest_ac("test_asset_disposal", "assets", epic_info)
        assert "AC11.3.x" in result

    def test_auth_domain_login(self):
        epic_info = EPIC_MAPPING["auth"]
        result = suggest_ac("test_user_login", "auth", epic_info)
        assert "AC1.1.x" in result

    def test_infra_domain_config(self):
        epic_info = EPIC_MAPPING["infra"]
        result = suggest_ac("test_config_loading", "infra", epic_info)
        assert "AC1.2.x" in result

    def test_infra_domain_migration(self):
        epic_info = EPIC_MAPPING["infra"]
        result = suggest_ac("test_schema_migration", "infra", epic_info)
        assert "AC1.3.x" in result

    def test_api_domain_rate_limit(self):
        epic_info = EPIC_MAPPING["infra"]
        result = suggest_ac("test_rate_limit_enforced", "api", epic_info)
        assert "AC1.4.x" in result

    def test_unknown_domain_returns_uncategorized(self):
        epic_info = {"epic": "EPIC-999", "ac_prefix": "AC99", "keywords": []}
        result = suggest_ac("test_something", "unknown", epic_info)
        assert "AC99.x.x" in result
        assert "Uncategorized" in result


class TestExtractTestFunctions:
    def test_returns_empty_list_for_missing_file(self, tmp_path, capsys):
        missing_file = tmp_path / "nonexistent.py"
        result = extract_test_functions(missing_file)
        assert result == []
        captured = capsys.readouterr()
        assert "Error parsing" in captured.out
    def test_returns_empty_list_for_syntax_error_file(self, tmp_path, capsys):
        bad_file = tmp_path / "test_bad.py"
        bad_file.write_text("def test_broken(\n")
        result = extract_test_functions(bad_file)

        assert result == []
        captured = capsys.readouterr()
        assert "Error parsing" in captured.out

    def test_returns_empty_for_file_outside_project_root(self, tmp_path, capsys):
        test_file = tmp_path / "test_sample.py"
        test_file.write_text('''
def test_example_one():
    pass
''')

        result = extract_test_functions(test_file)

        assert result == []
        captured = capsys.readouterr()
        assert "Error parsing" in captured.out

    def test_handles_empty_file(self, tmp_path):
        test_file = tmp_path / "test_empty.py"
        test_file.write_text("")
        result = extract_test_functions(test_file)

        assert result == []

    def test_handles_file_with_no_test_functions(self, tmp_path, capsys):
        test_file = tmp_path / "test_no_tests.py"
        test_file.write_text('''
def helper():
    pass
''')

        result = extract_test_functions(test_file)

        assert result == []

    def test_extracts_from_real_project_test_file(self):
        project_root = Path(__file__).parent.parent.parent
        existing_test = project_root / "scripts" / "tests" / "test_merge_lcov.py"

        if not existing_test.exists():
            pytest.skip("No existing test file to test with")

        result = extract_test_functions(existing_test)

        assert len(result) > 0
        assert all(f.function_name.startswith("test_") for f in result)

    def test_ac_pattern_detection_with_real_file(self):
        project_root = Path(__file__).parent.parent.parent
        existing_tests = project_root / "apps" / "backend" / "tests" / "accounting"

        test_files = list(existing_tests.glob("test_*.py")) if existing_tests.exists() else []

        if not test_files:
            pytest.skip("No test files found in accounting tests")

        result = extract_test_functions(test_files[0])

        if result:
            func = result[0]
            assert hasattr(func, "function_name")
            assert hasattr(func, "has_ac")
            assert hasattr(func, "domain")
            assert hasattr(func, "suggested_ac")
            assert isinstance(func.has_ac, bool)


class TestMain:
    def test_main_runs_with_real_tests_dir(self, capsys):
        from analyze_test_ac_coverage import main
        project_root = Path(__file__).parent.parent.parent
        tests_dir = project_root / "apps" / "backend" / "tests"
        if not tests_dir.exists():
            pytest.skip("Backend tests dir not found")
        main()
        captured = capsys.readouterr()
        assert "TEST AC COVERAGE SUMMARY" in captured.out or "Scanning" in captured.out