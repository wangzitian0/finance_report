"""Tests for common.testing.coverage.junit helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SAMPLE_XML_1 = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="shard-1" tests="2" failures="0" errors="0" time="1.5">
    <testcase classname="test_mod1" name="test_one" time="0.5"/>
    <testcase classname="test_mod1" name="test_two" time="1.0"/>
</testsuite>
"""


class TestSharedJunitHelper:
    """Validate common.testing.coverage.junit helper functions."""

    def test_parse_junit_root_handles_missing_and_corrupt(self, tmp_path: Path) -> None:
        from common.testing.coverage import junit

        missing = tmp_path / "missing.xml"
        assert junit.parse_junit_root(missing) is None

        corrupt = tmp_path / "corrupt.xml"
        corrupt.write_text("<invalid-xml>", encoding="utf-8")
        assert junit.parse_junit_root(corrupt) is None

        valid = tmp_path / "valid.xml"
        valid.write_text(SAMPLE_XML_1, encoding="utf-8")
        root = junit.parse_junit_root(valid)
        assert root is not None
        assert root.tag == "testsuite"

    def test_iter_testcases(self, tmp_path: Path) -> None:
        from common.testing.coverage import junit

        f = tmp_path / "s.xml"
        f.write_text(SAMPLE_XML_1, encoding="utf-8")
        cases = junit.iter_testcases(f)
        assert len(cases) == 2
        names = [case.attrib.get("name") for case in cases]
        assert names == ["test_one", "test_two"]
