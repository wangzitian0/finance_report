"""Tests for line-only Coveralls LCOV generation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from common.testing.coverage import strip_lcov_branches as slb  # noqa: E402


def test_AC8_13_66_strip_lcov_branches_preserves_line_records(tmp_path):
    """AC8.13.66: Coveralls uploads use line-only LCOV records."""
    source = tmp_path / "input.lcov"
    output = tmp_path / "nested" / "output.lcov"
    source.write_text(
        "\n".join(
            [
                "SF:src/example.py",
                "DA:10,1",
                "BRDA:10,0,0,1",
                "BRDA:11,0,0,-",
                "BRF:2",
                "BRH:1",
                "LH:1",
                "LF:1",
                "end_of_record",
                "",
            ]
        )
    )

    assert slb.strip_lcov_branches(source, output) == 0
    content = output.read_text()
    assert "SF:src/example.py" in content
    assert "DA:10,1" in content
    assert "LH:1" in content
    assert "LF:1" in content
    assert "BRDA:" not in content
    assert "BRF:" not in content
    assert "BRH:" not in content


def test_AC8_13_66_strip_lcov_branches_reports_missing_input(tmp_path, capsys):
    """AC8.13.66: Missing LCOV inputs fail before misleading upload files exist."""
    result = slb.strip_lcov_branches(
        tmp_path / "missing.lcov", tmp_path / "output.lcov"
    )

    assert result == 1
    assert "LCOV input not found" in capsys.readouterr().err


def test_AC8_13_66_strip_lcov_branches_cli_exits_zero(tmp_path, monkeypatch):
    """AC8.13.66: The command wrapper can be used directly by CI."""
    source = tmp_path / "input.lcov"
    output = tmp_path / "output.lcov"
    source.write_text("SF:src/example.py\nBRF:1\nDA:1,1\nLH:1\nLF:1\n")
    monkeypatch.setattr(
        "sys.argv", ["strip_lcov_branches.py", str(source), str(output)]
    )

    with pytest.raises(SystemExit) as exc:
        slb.main()

    assert exc.value.code == 0
    assert "BRF:" not in output.read_text()
