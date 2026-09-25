"""Tests for common.testing.coverage.merge_junit and tools/merge_junit.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.testing.coverage import merge_junit  # noqa: E402

SAMPLE_XML_1 = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="shard-1" tests="2" failures="0" errors="0" time="1.5">
    <testcase classname="test_mod1" name="test_one" time="0.5"/>
    <testcase classname="test_mod1" name="test_two" time="1.0"/>
</testsuite>
"""

SAMPLE_XML_2 = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="shard-2" tests="1" failures="1" errors="0" time="0.8">
    <testcase classname="test_mod2" name="test_three" time="0.8">
        <failure message="assertion failed">Traceback...</failure>
    </testcase>
</testsuite>
"""

SAMPLE_XML_TESTSUITES_ROOT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
    <testsuite name="shard-3a" tests="1" failures="0" errors="0" time="0.2">
        <testcase classname="test_mod3" name="test_four" time="0.2"/>
    </testsuite>
    <testsuite name="shard-3b" tests="1" failures="0" errors="0" time="0.3">
        <testcase classname="test_mod3" name="test_five" time="0.3"/>
    </testsuite>
</testsuites>
"""


def test_merge_junit_files_combines_testsuites(tmp_path: Path) -> None:
    f1 = tmp_path / "shard1.xml"
    f2 = tmp_path / "shard2.xml"
    out = tmp_path / "output" / "merged.xml"

    f1.write_text(SAMPLE_XML_1, encoding="utf-8")
    f2.write_text(SAMPLE_XML_2, encoding="utf-8")

    status = merge_junit.merge_junit_files([f1, f2], out)
    assert status == 0
    assert out.is_file()

    tree = ElementTree.parse(out)
    root = tree.getroot()
    expected_root_tag = "testsuites"
    assert root.tag == expected_root_tag
    assert len(root) == 2
    names = [child.attrib.get("name") for child in root]
    expected_s1 = "shard-1"
    expected_s2 = "shard-2"
    assert expected_s1 in names
    assert expected_s2 in names


def test_merge_junit_files_flattens_nested_testsuites(tmp_path: Path) -> None:
    f1 = tmp_path / "shard1.xml"
    f2 = tmp_path / "shard3.xml"
    out = tmp_path / "merged.xml"

    f1.write_text(SAMPLE_XML_1, encoding="utf-8")
    f2.write_text(SAMPLE_XML_TESTSUITES_ROOT, encoding="utf-8")

    status = merge_junit.merge_junit_files([f1, f2], out)
    assert status == 0

    tree = ElementTree.parse(out)
    root = tree.getroot()
    assert len(root) == 3
    names = [child.attrib.get("name") for child in root]
    expected_s1 = "shard-1"
    expected_s3a = "shard-3a"
    expected_s3b = "shard-3b"
    assert expected_s1 in names
    assert expected_s3a in names
    assert expected_s3b in names


def test_merge_junit_no_valid_files(tmp_path: Path) -> None:
    missing1 = tmp_path / "missing1.xml"
    missing2 = tmp_path / "missing2.xml"
    out = tmp_path / "merged.xml"

    status = merge_junit.merge_junit_files([missing1, missing2], out)
    assert status == 1
    assert not out.exists()


def test_merge_junit_handles_malformed_xml(tmp_path: Path) -> None:
    f1 = tmp_path / "valid.xml"
    f2 = tmp_path / "corrupt.xml"
    out = tmp_path / "merged.xml"

    f1.write_text(SAMPLE_XML_1, encoding="utf-8")
    f2.write_text("<testsuite><not-closed>", encoding="utf-8")

    status = merge_junit.merge_junit_files([f1, f2], out)
    assert status == 0
    tree = ElementTree.parse(out)
    root = tree.getroot()
    assert len(root) == 1
    expected_name = "shard-1"
    assert root[0].attrib.get("name") == expected_name


def test_main_cli_positional_args(tmp_path: Path) -> None:
    f1 = tmp_path / "s1.xml"
    f2 = tmp_path / "s2.xml"
    out = tmp_path / "merged.xml"
    f1.write_text(SAMPLE_XML_1, encoding="utf-8")
    f2.write_text(SAMPLE_XML_2, encoding="utf-8")

    status = merge_junit.main([str(out), str(f1), str(f2)])
    assert status == 0
    assert out.is_file()
    tree = ElementTree.parse(out)
    assert len(tree.getroot()) == 2


def test_main_cli_output_flag(tmp_path: Path) -> None:
    f1 = tmp_path / "s1.xml"
    out = tmp_path / "merged.xml"
    f1.write_text(SAMPLE_XML_1, encoding="utf-8")

    status = merge_junit.main(["--output", str(out), str(f1)])
    assert status == 0
    assert out.is_file()
    tree = ElementTree.parse(out)
    assert len(tree.getroot()) == 1


def test_main_cli_input_dir(tmp_path: Path) -> None:
    shards_dir = tmp_path / "shards"
    shards_dir.mkdir()
    f1 = shards_dir / "tooling-junit-1.xml"
    f2 = shards_dir / "tooling-junit-2.xml"
    f1.write_text(SAMPLE_XML_1, encoding="utf-8")
    f2.write_text(SAMPLE_XML_2, encoding="utf-8")
    out = tmp_path / "merged.xml"

    status = merge_junit.main(
        [
            "--output",
            str(out),
            "--input-dir",
            str(shards_dir),
            "--pattern",
            "tooling-junit-*.xml",
        ]
    )
    assert status == 0
    assert out.is_file()
    tree = ElementTree.parse(out)
    assert len(tree.getroot()) == 2


def test_main_cli_no_args() -> None:
    status = merge_junit.main([])
    assert status == 1


def test_tools_merge_junit_shim(tmp_path: Path) -> None:
    f1 = tmp_path / "s1.xml"
    out = tmp_path / "merged.xml"
    f1.write_text(SAMPLE_XML_1, encoding="utf-8")

    tool_path = Path(__file__).resolve().parents[2] / "tools" / "merge_junit.py"
    res = subprocess.run(
        [sys.executable, str(tool_path), str(out), str(f1)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    assert out.is_file()
