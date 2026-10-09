from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

from common.testing.sync_ci_test_durations import (
    case_to_node_id,
    extract_durations_from_xmls,
    update_duration_seed,
)


def test_case_to_node_id_simple() -> None:
    case = ElementTree.Element(
        "testcase",
        {"classname": "tests.api.test_foo", "name": "test_bar", "time": "1.23"},
    )
    assert case_to_node_id(case) == "tests/api/test_foo.py::test_bar"


def test_case_to_node_id_with_test_class() -> None:
    case = ElementTree.Element(
        "testcase",
        {
            "classname": "tests.api.test_foo.TestClass",
            "name": "test_bar",
            "time": "0.5",
        },
    )
    assert case_to_node_id(case) == "tests/api/test_foo.py::TestClass::test_bar"


def test_extract_durations_from_xmls(tmp_path: Path) -> None:
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="2" time="1.5">
  <testcase classname="tests.api.test_demo" name="test_one" time="0.456" />
  <testcase classname="tests.api.test_demo" name="test_two" time="1.000" />
</testsuite>
"""
    xml_file = tmp_path / "test.xml"
    xml_file.write_text(xml_content, encoding="utf-8")

    durations = extract_durations_from_xmls([xml_file])
    assert durations == {
        "tests/api/test_demo.py::test_one": 0.456,
        "tests/api/test_demo.py::test_two": 1.000,
    }


def test_update_duration_seed(tmp_path: Path) -> None:
    seed_file = tmp_path / "seed.json"
    initial = {"tests/a.py::test_1": 0.5, "tests/b.py::test_2": 1.2}
    seed_file.write_text(json.dumps(initial), encoding="utf-8")

    new_durations = {"tests/a.py::test_1": 0.8, "tests/c.py::test_3": 2.0}
    total, updated = update_duration_seed(seed_file, new_durations, dry_run=False)

    assert total == 3
    assert updated == 2

    saved = json.loads(seed_file.read_text(encoding="utf-8"))
    assert saved == {
        "tests/a.py::test_1": 0.8,
        "tests/b.py::test_2": 1.2,
        "tests/c.py::test_3": 2.0,
    }
