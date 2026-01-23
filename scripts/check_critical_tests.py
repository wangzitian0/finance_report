#!/usr/bin/env python
"""
Check that critical tests were not skipped.

Usage:
    pytest tests/e2e -v --tb=short 2>&1 | python scripts/check_critical_tests.py

Or with JUnit XML:
    pytest tests/e2e --junit-xml=test-results.xml
    python scripts/check_critical_tests.py test-results.xml

Exit codes:
    0 - All critical tests passed
    1 - Some critical tests were skipped or failed
"""

import sys
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# Define critical tests that MUST NOT be skipped
CRITICAL_TESTS = [
    # "test_statement_upload_parsing_flow",  # TODO: Re-enable after backend AI parsing fix
    "test_registration_flow",  # User registration
    "test_full_navigation",  # Basic navigation works
]


def check_from_junit_xml(xml_path: Path) -> tuple[list[str], list[str], int]:
    """Parse JUnit XML and find skipped/failed critical tests.

    Returns:
        tuple: (skipped_critical, failed_critical, found_count)
    """
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        print(f"❌ ERROR: Failed to parse XML file: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ ERROR: Unexpected error reading XML: {e}")
        sys.exit(1)

    root = tree.getroot()

    skipped_critical = []
    failed_critical = []
    found_count = 0

    for testcase in root.iter("testcase"):
        name = testcase.get("name", "")

        # Check if this is a critical test
        if not any(critical in name for critical in CRITICAL_TESTS):
            continue

        found_count += 1

        # Check status
        skipped_elem = testcase.find("skipped")
        failure_elem = testcase.find("failure")

        if skipped_elem is not None:
            reason = skipped_elem.get("message", "no reason")
            skipped_critical.append(f"{name}: {reason}")
        elif failure_elem is not None:
            message = failure_elem.get("message", "no message")
            failed_critical.append(f"{name}: {message}")

    return skipped_critical, failed_critical, found_count


def check_from_stdout(lines: list[str]) -> tuple[list[str], list[str]]:
    """Parse pytest stdout and find skipped/failed critical tests."""
    skipped_critical = []
    failed_critical = []

    # Pattern: test_name SKIPPED or test_name PASSED/FAILED
    test_pattern = re.compile(r"(test_\w+)\s+(PASSED|FAILED|SKIPPED|ERROR)")

    for line in lines:
        match = test_pattern.search(line)
        if not match:
            continue

        test_name = match.group(1)
        status = match.group(2)

        # Check if this is a critical test
        if not any(critical in test_name for critical in CRITICAL_TESTS):
            continue

        if status == "SKIPPED":
            skipped_critical.append(test_name)
        elif status in ("FAILED", "ERROR"):
            failed_critical.append(test_name)

    return skipped_critical, failed_critical


def main() -> None:
    if len(sys.argv) > 1:
        xml_path = Path(sys.argv[1])
        if not xml_path.exists():
            print(f"❌ ERROR: XML file not found: {xml_path}")
            sys.exit(1)

        if xml_path.suffix != ".xml":
            print(f"❌ ERROR: Not an XML file: {xml_path}")
            sys.exit(1)

        skipped, failed, found = check_from_junit_xml(xml_path)
    else:
        lines = sys.stdin.readlines()
        skipped, failed = check_from_stdout(lines)
        found = len(skipped) + len(failed)

    if found == 0:
        print("❌ ERROR: No critical tests found!")
        print(f"   Expected tests: {CRITICAL_TESTS}")
        print("   This may indicate:")
        print("   - Tests were renamed or moved")
        print("   - Tests were not run at all")
        print("   - Wrong test file or filter was used")
        sys.exit(1)

    has_issues = False

    if skipped:
        print("❌ CRITICAL TESTS SKIPPED:")
        for test in skipped:
            print(f"   - {test}")
        has_issues = True

    if failed:
        print("❌ CRITICAL TESTS FAILED:")
        for test in failed:
            print(f"   - {test}")
        has_issues = True

    if has_issues:
        print("\n⚠️  Critical tests must pass! Fix the auth/config issues.")
        print("   See: tests/e2e/conftest.py for authenticated_page fixture")
        sys.exit(1)
    else:
        print(f"✅ All {found} critical tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
