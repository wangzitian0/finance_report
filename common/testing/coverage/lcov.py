"""LCOV parser, branch filter, and writer single source of truth.

This module provides common utilities to parse, merge, and write LCOV files.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

BRANCH_RECORD_PREFIXES = ("BRDA:", "BRF:", "BRH:")


def is_branch_record(line: str) -> bool:
    """Return True if line starts with a branch coverage prefix."""
    return line.startswith(BRANCH_RECORD_PREFIXES)


def parse_lcov_to_records(lcov_path: Path) -> dict[str, dict]:
    """Parse LCOV file into per-file records dictionary."""
    if not lcov_path.exists():
        return {}

    records: dict[str, dict] = {}
    current_file: str | None = None
    current_record: dict | None = None

    def flush_record() -> None:
        nonlocal current_file, current_record
        if not current_file or not current_record:
            return
        if current_file not in records:
            records[current_file] = current_record
        else:
            for line_num, hit_count in current_record["lines"].items():
                existing = records[current_file]["lines"].get(line_num, 0)
                records[current_file]["lines"][line_num] = max(existing, hit_count)
        current_file = None
        current_record = None

    with open(lcov_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line.startswith("SF:"):
                flush_record()
                current_file = line[3:]
                current_record = {
                    "lines": {},
                    "functions": {},
                    "branches": {},
                }
            elif line.startswith("DA:") and current_record is not None:
                parts = line[3:].split(",")
                if len(parts) >= 2:
                    try:
                        line_num = int(parts[0])
                        hit_count = int(parts[1])
                        current_record["lines"][line_num] = hit_count
                    except ValueError:
                        pass
            elif line == "end_of_record":
                flush_record()

    flush_record()
    return records


def merge_records(records_list: list[dict]) -> dict:
    """Merge multiple record dictionaries by taking the maximum hit count."""
    merged: dict[str, dict] = {}
    for records in records_list:
        for source_file, record in records.items():
            if source_file not in merged:
                merged[source_file] = {"lines": {}}
            for line_num, hit_count in record.get("lines", {}).items():
                existing = merged[source_file]["lines"].get(line_num, 0)
                merged[source_file]["lines"][line_num] = max(existing, hit_count)
    return merged


def write_lcov(records: dict, output_path: Path) -> None:
    """Write records dictionary to an LCOV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for source_file, record in sorted(records.items()):
            f.write(f"SF:{source_file}\n")
            lines = record.get("lines", {})
            for line_num, hit_count in sorted(lines.items()):
                f.write(f"DA:{line_num},{hit_count}\n")
            total_lines = len(lines)
            covered_lines = sum(1 for hit in lines.values() if hit > 0)
            f.write(f"LF:{total_lines}\n")
            f.write(f"LH:{covered_lines}\n")
            f.write("end_of_record\n")


def parse_line_hits(
    lcov_path: Path,
    normalize_source: Callable[[str], str] | None = None,
    accumulate: str = "max",
) -> dict[str, dict[int, int]]:
    """Parse LCOV line hit records per normalized source path."""
    if not lcov_path.exists():
        return {}

    hits: dict[str, dict[int, int]] = {}
    current_source = ""

    with open(lcov_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.strip()
            if line.startswith("SF:"):
                raw_source = line[3:]
                current_source = (
                    normalize_source(raw_source)
                    if normalize_source
                    else raw_source.replace("\\", "/")
                )
                hits.setdefault(current_source, {})
            elif line.startswith("DA:") and current_source:
                fields = line[3:].split(",")
                try:
                    line_no = int(fields[0])
                    hit_count = int(fields[1])
                except (IndexError, ValueError):
                    continue
                file_hits = hits[current_source]
                if accumulate == "sum":
                    file_hits[line_no] = file_hits.get(line_no, 0) + hit_count
                else:
                    file_hits[line_no] = max(file_hits.get(line_no, 0), hit_count)
            elif line == "end_of_record":
                current_source = ""

    return hits


def parse_lcov_summaries(
    lcov_path: Path,
    normalize_source: Callable[[str], str] | None = None,
) -> dict[str, dict[str, int]]:
    """Parse LCOV and return per-source total and covered line counts."""
    if not lcov_path.exists():
        return {}

    records: dict[str, dict[str, int]] = {}
    current_source = ""
    current_covered: int | None = None
    current_total: int | None = None
    da_lines: dict[int, int] = {}
    in_record = False

    def flush_record() -> None:
        nonlocal current_source, current_covered, current_total, da_lines, in_record
        if not in_record or not current_source:
            return
        source = (
            normalize_source(current_source)
            if normalize_source
            else current_source.replace("\\", "/")
        )
        rec = records.setdefault(source, {"covered_lines": 0, "total_lines": 0})
        if current_covered is not None:
            rec["covered_lines"] += current_covered
        elif da_lines:
            rec["covered_lines"] += sum(1 for hit in da_lines.values() if hit > 0)

        if current_total is not None:
            rec["total_lines"] += current_total
        elif da_lines:
            rec["total_lines"] += len(da_lines)

        current_source = ""
        current_covered = None
        current_total = None
        da_lines = {}
        in_record = False

    with open(lcov_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line.startswith("SF:"):
                flush_record()
                in_record = True
                current_source = line[3:]
            elif line.startswith("DA:") and in_record:
                parts = line[3:].split(",")
                if len(parts) >= 2:
                    try:
                        da_lines[int(parts[0])] = int(parts[1])
                    except ValueError:
                        pass
            elif line.startswith("LH:") and in_record:
                try:
                    current_covered = int(line[3:])
                except ValueError:
                    pass
            elif line.startswith("LF:") and in_record:
                try:
                    current_total = int(line[3:])
                except ValueError:
                    pass
            elif line == "end_of_record":
                flush_record()

    flush_record()
    return records


def strip_branches(input_path: Path, output_path: Path) -> int:
    """Copy LCOV input to output path without branch coverage records."""
    if not input_path.exists():
        print(f"LCOV input not found: {input_path}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        open(input_path, "r", encoding="utf-8") as source,
        open(output_path, "w", encoding="utf-8") as target,
    ):
        for line in source:
            if is_branch_record(line):
                continue
            target.write(line)

    print(f"Wrote line-only LCOV to {output_path}")
    return 0
