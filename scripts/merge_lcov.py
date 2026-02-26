#!/usr/bin/env python3
"""
Merge multiple LCOV files by taking the UNION of coverage.

For each source file that appears in multiple lcov files,
we merge the coverage by taking the MAX hit count for each line.
This gives us the combined coverage across all test shards.
"""

import sys
from collections import defaultdict
from pathlib import Path


def parse_lcov_to_records(lcov_path: Path) -> dict:
    """Parse LCOV file into per-file records."""
    records = {}
    current_file = None
    current_record = None

    with open(lcov_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if line.startswith("SF:"):
                current_file = line[3:]
                current_record = {
                    "lines": {},  # line_num -> hit_count
                    "functions": {},
                    "branches": {},
                }
            elif line.startswith("DA:"):
                # DA:line_number,hit_count
                parts = line[3:].split(",")
                if len(parts) >= 2:
                    line_num = int(parts[0])
                    hit_count = int(parts[1])
                    current_record["lines"][line_num] = hit_count
            elif line == "end_of_record":
                if current_file and current_record:
                    if current_file not in records:
                        records[current_file] = current_record
                    else:
                        # Merge with existing record (take max hit count)
                        for line_num, hit_count in current_record["lines"].items():
                            existing = records[current_file]["lines"].get(line_num, 0)
                            records[current_file]["lines"][line_num] = max(
                                existing, hit_count
                            )
                current_file = None
                current_record = None

    # Handle last record if no end_of_record
    if current_file and current_record:
        if current_file not in records:
            records[current_file] = current_record
        else:
            for line_num, hit_count in current_record["lines"].items():
                existing = records[current_file]["lines"].get(line_num, 0)
                records[current_file]["lines"][line_num] = max(existing, hit_count)

    return records


def merge_records(records_list: list[dict]) -> dict:
    """Merge multiple record dictionaries."""
    merged = {}

    for records in records_list:
        for source_file, record in records.items():
            if source_file not in merged:
                merged[source_file] = {"lines": {}}

            # Merge lines (take max hit count)
            for line_num, hit_count in record["lines"].items():
                existing = merged[source_file]["lines"].get(line_num, 0)
                merged[source_file]["lines"][line_num] = max(existing, hit_count)

    return merged


def write_lcov(records: dict, output_path: Path):
    """Write merged records to LCOV format."""
    with open(output_path, "w", encoding="utf-8") as f:
        for source_file, record in sorted(records.items()):
            f.write(f"SF:{source_file}\n")

            # Write line coverage
            for line_num, hit_count in sorted(record["lines"].items()):
                f.write(f"DA:{line_num},{hit_count}\n")

            # Write summary
            total_lines = len(record["lines"])
            covered_lines = sum(1 for hit in record["lines"].values() if hit > 0)
            f.write(f"LF:{total_lines}\n")
            f.write(f"LH:{covered_lines}\n")
            f.write("end_of_record\n")


def main():
    if len(sys.argv) < 3:
        print("Usage: merge_lcov.py <output.lcov> <input1.lcov> [input2.lcov ...]")
        sys.exit(1)

    output_path = Path(sys.argv[1])
    input_paths = [Path(p) for p in sys.argv[2:]]

    print(f"Merging {len(input_paths)} LCOV files...")

    all_records = []
    for input_path in input_paths:
        if input_path.exists():
            records = parse_lcov_to_records(input_path)
            all_records.append(records)
            print(f"  {input_path.name}: {len(records)} files")
        else:
            print(f"  Warning: {input_path} not found")

    merged = merge_records(all_records)
    print(f"Merged result: {len(merged)} unique source files")

    write_lcov(merged, output_path)
    print(f"✅ Wrote merged coverage to: {output_path}")


if __name__ == "__main__":
    main()
