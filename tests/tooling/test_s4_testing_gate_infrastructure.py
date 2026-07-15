"""Behavioral locks for the CODE-ONLY testing slice of #1867."""

from __future__ import annotations

from pathlib import Path

import pytest

from common.meta.extension.ac_registry_format import sort_key
from common.testing import ac_scan, ac_score_baseline_format, jsonl_baseline
from common.testing import analyze_test_ac_coverage as coverage_analysis
from common.testing import build_ac_traceability, check_ac_traceability


def test_AC_testing_governance_14_jsonl_baseline_bindings_share_parameterized_behavior(
    tmp_path: Path,
) -> None:
    """AC-testing.governance.14: both identifier/collection shapes keep JSONL floors."""

    ac_payload = {
        "version": 1,
        "acs": {"AC-testing.governance.14": {"score": 0.8, "metric": "m"}},
    }
    case_payload = {
        "version": 1,
        "cases": {"synthetic-case": {"score": 0.7, "metric": "field-accuracy"}},
    }

    ac_path = tmp_path / "acs.jsonl"
    ac_score_baseline_format.write_jsonl(ac_path, ac_payload)
    loaded = ac_score_baseline_format.load_jsonl(ac_path)
    assert loaded["acs"]["AC-testing.governance.14"] == {
        "score": 0.8,
        "metric": "m",
        "provenance": "",
    }

    case_path = tmp_path / "cases.jsonl"
    jsonl_baseline.write_jsonl(
        case_path,
        case_payload,
        identifier_key="case_id",
        collection_key="cases",
    )
    assert (
        jsonl_baseline.load_jsonl(
            case_path,
            identifier_key="case_id",
            collection_key="cases",
        )["cases"]["synthetic-case"]["metric"]
        == "field-accuracy"
    )

    lowered = jsonl_baseline.ratcheted_raise_only_merge(
        ac_payload,
        {"version": 1, "acs": {"AC-testing.governance.14": {"score": 0.5}}},
        collection_key="acs",
    )
    assert lowered["acs"]["AC-testing.governance.14"]["score"] == 0.8

    raised = jsonl_baseline.ratcheted_raise_only_merge(
        case_payload,
        {"version": 1, "cases": {"synthetic-case": {"score": 0.9}}},
        collection_key="cases",
        default_metric="field-accuracy",
    )
    assert raised["cases"]["synthetic-case"] == {
        "score": 0.9,
        "metric": "field-accuracy",
        "provenance": "",
    }

    assert (
        jsonl_baseline.render_jsonl(
            {"acs": []}, identifier_key="ac_id", collection_key="acs"
        )
        == ""
    )
    path = tmp_path / "nested" / "normalize.jsonl"
    path.parent.mkdir()
    path.write_text('{"ac_id":"z"}\n\n{"ac_id":"a"}\n', encoding="utf-8")
    normalized = jsonl_baseline.normalize_file(
        path, identifier_key="ac_id", collection_key="acs"
    )
    assert list(normalized["acs"]) == ["z", "a"]
    assert path.read_text(encoding="utf-8").startswith('{"ac_id": "a"')

    for invalid, message in (
        ("not-json\n", "invalid JSONL"),
        ('{"other":"x"}\n', "'ac_id'"),
        ('{"ac_id":"x"}\n{"ac_id":"x"}\n', "duplicate ac_id"),
    ):
        path.write_text(invalid, encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            jsonl_baseline.load_jsonl(
                path, identifier_key="ac_id", collection_key="acs"
            )

    assert jsonl_baseline.ratcheted_raise_only_merge(
        {"acs": []}, {"acs": {"ignored": "not-a-record"}}, collection_key="acs"
    ) == {"version": 1, "acs": {}}


def test_AC_testing_governance_15_traceability_tools_share_scanner_and_canonical_sort(
    tmp_path: Path,
) -> None:
    """AC-testing.governance.15: all tools share discovery and preserve package IDs."""

    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    source = test_dir / "test_references.py"
    source.write_text(
        "def test_reference():\n    assert 'AC-audit.36.1' != 'AC-ledger.36.1'\n",
        encoding="utf-8",
    )

    discovered = ac_scan.find_test_files([test_dir])
    assert discovered == [source]
    assert build_ac_traceability.find_test_files is ac_scan.find_test_files
    assert check_ac_traceability.find_test_files is ac_scan.find_test_files

    references = ac_scan.collect_references(discovered)
    assert set(references) == {"AC-audit.36.1", "AC-ledger.36.1"}
    assert sort_key("AC-audit.36.1") != sort_key("AC-ledger.36.1")
    assert coverage_analysis.ac_scan is ac_scan
