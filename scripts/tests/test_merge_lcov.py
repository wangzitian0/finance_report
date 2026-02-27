"""Tests for scripts/merge_lcov.py.
LCOV merge correctly unions coverage across test shards.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import merge_lcov as ml  # noqa: E402

LCOV_A = """\
SF:/repo/src/a.py
DA:1,1
DA:2,0
DA:3,2
end_of_record
SF:/repo/src/b.py
DA:10,0
DA:11,0
end_of_record
"""

LCOV_B = """\
SF:/repo/src/a.py
DA:1,0
DA:2,3
DA:3,0
end_of_record
SF:/repo/src/c.py
DA:5,1
end_of_record
"""


class TestParseLcovToRecords:
    """parse_lcov_to_records extracts per-file line hit counts."""

    def test_parses_single_file(self, tmp_path):
        f = tmp_path / "a.lcov"
        f.write_text(LCOV_A)
        records = ml.parse_lcov_to_records(f)
        assert "/repo/src/a.py" in records
        assert records["/repo/src/a.py"]["lines"] == {1: 1, 2: 0, 3: 2}

    def test_parses_multiple_files(self, tmp_path):
        f = tmp_path / "a.lcov"
        f.write_text(LCOV_A)
        records = ml.parse_lcov_to_records(f)
        assert len(records) == 2
        assert "/repo/src/b.py" in records

    def test_deduplicates_within_file(self, tmp_path):
        content = """\
SF:/repo/dup.py
DA:1,2
DA:1,5
end_of_record
"""
        f = tmp_path / "dup.lcov"
        f.write_text(content)
        records = ml.parse_lcov_to_records(f)
        assert records["/repo/dup.py"]["lines"][1] == 5

    def test_handles_malformed_da_line(self, tmp_path):
        content = "SF:/repo/x.py\nDA:bad,line\nDA:1,1\nend_of_record\n"
        f = tmp_path / "bad.lcov"
        f.write_text(content)
        records = ml.parse_lcov_to_records(f)
        assert records["/repo/x.py"]["lines"].get(1) == 1

    def test_handles_last_record_without_end_of_record(self, tmp_path):
        content = "SF:/repo/z.py\nDA:1,1\n"
        f = tmp_path / "partial.lcov"
        f.write_text(content)
        records = ml.parse_lcov_to_records(f)
        assert "/repo/z.py" in records
        assert records["/repo/z.py"]["lines"][1] == 1

    def test_empty_lcov(self, tmp_path):
        f = tmp_path / "empty.lcov"
        f.write_text("")
        records = ml.parse_lcov_to_records(f)
        assert records == {}


class TestMergeRecords:
    """merge_records takes max hit count across shards for same source file."""

    def test_union_of_different_files(self, tmp_path):
        f_a = tmp_path / "a.lcov"
        f_a.write_text(LCOV_A)
        f_b = tmp_path / "b.lcov"
        f_b.write_text(LCOV_B)
        r_a = ml.parse_lcov_to_records(f_a)
        r_b = ml.parse_lcov_to_records(f_b)
        merged = ml.merge_records([r_a, r_b])
        assert "/repo/src/a.py" in merged
        assert "/repo/src/b.py" in merged
        assert "/repo/src/c.py" in merged

    def test_takes_max_hit_count(self, tmp_path):
        f_a = tmp_path / "a.lcov"
        f_a.write_text(LCOV_A)
        f_b = tmp_path / "b.lcov"
        f_b.write_text(LCOV_B)
        r_a = ml.parse_lcov_to_records(f_a)
        r_b = ml.parse_lcov_to_records(f_b)
        merged = ml.merge_records([r_a, r_b])
        lines = merged["/repo/src/a.py"]["lines"]
        assert lines[1] == 1  # max(1, 0)
        assert lines[2] == 3  # max(0, 3)
        assert lines[3] == 2  # max(2, 0)

    def test_empty_list(self):
        assert ml.merge_records([]) == {}

    def test_single_shard(self, tmp_path):
        f = tmp_path / "a.lcov"
        f.write_text(LCOV_A)
        r = ml.parse_lcov_to_records(f)
        merged = ml.merge_records([r])
        assert merged["/repo/src/a.py"]["lines"] == {1: 1, 2: 0, 3: 2}


class TestWriteLcov:
    """write_lcov emits valid LCOV output from merged records."""

    def test_writes_sf_da_lf_lh(self, tmp_path):
        records = {
            "/repo/src/x.py": {"lines": {1: 1, 2: 0, 3: 3}},
        }
        out = tmp_path / "out.lcov"
        ml.write_lcov(records, out)
        content = out.read_text()
        assert "SF:/repo/src/x.py" in content
        assert "DA:1,1" in content
        assert "DA:2,0" in content
        assert "DA:3,3" in content
        assert "LF:3" in content
        assert "LH:2" in content
        assert "end_of_record" in content

    def test_covered_count_correct(self, tmp_path):
        records = {
            "/repo/src/y.py": {"lines": {1: 0, 2: 0, 3: 0}},
        }
        out = tmp_path / "out.lcov"
        ml.write_lcov(records, out)
        content = out.read_text()
        assert "LH:0" in content
        assert "LF:3" in content

    def test_files_sorted_alphabetically(self, tmp_path):
        records = {
            "/z.py": {"lines": {1: 1}},
            "/a.py": {"lines": {1: 1}},
        }
        out = tmp_path / "sorted.lcov"
        ml.write_lcov(records, out)
        content = out.read_text()
        assert content.index("SF:/a.py") < content.index("SF:/z.py")

    def test_round_trip(self, tmp_path):
        f_a = tmp_path / "a.lcov"
        f_a.write_text(LCOV_A)
        records_in = ml.parse_lcov_to_records(f_a)
        out = tmp_path / "out.lcov"
        ml.write_lcov(records_in, out)
        records_out = ml.parse_lcov_to_records(out)
        for sf, rec in records_in.items():
            assert sf in records_out
            for line_num, hit in rec["lines"].items():
                assert records_out[sf]["lines"][line_num] == hit


class TestMain:
    """main() CLI: merges files and writes output."""

    def test_main_merges_two_files(self, tmp_path, monkeypatch):
        f_a = tmp_path / "a.lcov"
        f_a.write_text(LCOV_A)
        f_b = tmp_path / "b.lcov"
        f_b.write_text(LCOV_B)
        out = tmp_path / "merged.lcov"
        monkeypatch.setattr(
            "sys.argv",
            ["merge_lcov.py", str(out), str(f_a), str(f_b)],
        )
        ml.main()
        assert out.exists()
        records = ml.parse_lcov_to_records(out)
        assert len(records) == 3

    def test_main_warns_on_missing_input(self, tmp_path, monkeypatch, capsys):
        out = tmp_path / "merged.lcov"
        missing = tmp_path / "nonexistent.lcov"
        monkeypatch.setattr(
            "sys.argv",
            ["merge_lcov.py", str(out), str(missing)],
        )
        ml.main()
        captured = capsys.readouterr()
        assert "not found" in captured.out or "Warning" in captured.out

    def test_main_exits_on_no_args(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["merge_lcov.py"])
        with pytest.raises(SystemExit) as exc:
            ml.main()
        assert exc.value.code == 1
