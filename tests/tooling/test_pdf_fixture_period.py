"""AC-reporting.package-traceability.3: the brokerage PDF of the report-package journey is dated inside the fixture period (#2332).

A holding needs a snapshot dated on or before the as-of date. The fixture asks for
as-of 2026-05-31, so the brokerage statement must end on or before that date.
"""

from __future__ import annotations

import ast
import importlib
import random
import re
import subprocess
import sys
import types
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pdfplumber
import pytest

from common.testing.fixtures.pdf import generate_pdf_fixtures
from tools._lib.fixtures.personal_report_package import REPRESENTATIVE_PACKAGE_FIXTURE

REPO_ROOT = Path(__file__).resolve().parents[2]
E2E = REPO_ROOT / "tests" / "e2e"


def _pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


# These seeds overflow a 30-day period in the unclamped generator (67 of 200 seeds do).
OVERFLOWING_SEEDS = [0, 3, 6, 10, 11]


@pytest.mark.parametrize("seed", OVERFLOWING_SEEDS)
def test_period_end_option_sets_the_statement_period_and_the_file_name(
    tmp_path: Path, seed: int
) -> None:
    random.seed(seed)
    assert (
        generate_pdf_fixtures.main(
            [
                "--source",
                "moomoo",
                "--output",
                str(tmp_path),
                "--period-end",
                "2026-05-31",
            ]
        )
        == 0
    )

    built = tmp_path / "moomoo" / "test_moomoo_2605.pdf"
    assert built.exists()
    text = _pdf_text(built)
    assert "Statement Period: May 2026" in text
    # Every transaction is dated inside the 30 days that end on --period-end.
    dates = [date.fromisoformat(d) for d in re.findall(r"\d{4}-\d{2}-\d{2}", text)]
    assert dates, "the statement lists no dated transaction"
    assert all(date(2026, 5, 1) <= d <= date(2026, 5, 31) for d in dates), dates


def test_moomoo_transactions_never_postdate_the_statement_period() -> None:
    """Random steps of up to five days ran past a 30-day period in about half of all builds."""
    from common.testing.fixtures.pdf.data.fake_data import generate_moomoo_transactions

    period_end = datetime(2026, 5, 31, 12, tzinfo=UTC)
    period_start = period_end - timedelta(days=30)
    for seed in range(300):
        random.seed(seed)
        rows, _ = generate_moomoo_transactions(
            period_start, count=10, end_date=period_end
        )
        latest = max(date.fromisoformat(row["date"]) for row in rows)
        assert latest <= period_end.date(), f"seed {seed}: {latest}"


def test_without_the_option_the_period_ends_now(tmp_path: Path) -> None:
    before = datetime.now(UTC)
    assert (
        generate_pdf_fixtures.main(["--source", "moomoo", "--output", str(tmp_path)])
        == 0
    )

    built = tmp_path / "moomoo" / f"test_moomoo_{before:%y%m}.pdf"
    assert built.exists()
    assert f"Statement Period: {before:%B %Y}" in _pdf_text(built)


def test_a_bad_period_end_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as stopped:
        generate_pdf_fixtures.main(
            [
                "--source",
                "moomoo",
                "--output",
                str(tmp_path),
                "--period-end",
                "31-05-2026",
            ]
        )
    assert stopped.value.code == 2


def test_the_report_package_brokerage_pdf_ends_inside_the_fixture_period(
    tmp_path: Path,
) -> None:
    """The failing journey asked for as-of = fixture period end and got a PDF dated at run time."""
    fixture_period_end = REPRESENTATIVE_PACKAGE_FIXTURE.expected_outputs.period_end
    assert (
        generate_pdf_fixtures.main(
            [
                "--source",
                REPRESENTATIVE_PACKAGE_FIXTURE.brokerage.source,
                "--output",
                str(tmp_path),
                "--period-end",
                fixture_period_end.isoformat(),
            ]
        )
        == 0
    )

    built = next(
        (tmp_path / REPRESENTATIVE_PACKAGE_FIXTURE.brokerage.source).glob("*.pdf")
    )
    assert f"Statement Period: {fixture_period_end:%B %Y}" in _pdf_text(built)
    assert fixture_period_end < date.today(), "the fixture period must be in the past"


# ---------------------------------------------------------- generated_pdf_path


@pytest.fixture
def pdf_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Import tests/e2e/pdf_fixture_paths with a stub conftest and a temp output directory."""
    state = {"strict": False}
    conftest = types.ModuleType("conftest")
    conftest.is_strict_or_ci = lambda: state["strict"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "conftest", conftest)
    sys.modules.pop("tests.e2e.pdf_fixture_paths", None)
    module = importlib.import_module("tests.e2e.pdf_fixture_paths")
    monkeypatch.setattr(module, "OUTPUT_DIR", tmp_path)
    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True):  # noqa: ANN001
        calls.append([str(part) for part in cmd])
        source = cmd[cmd.index("--source") + 1]
        if "--period-end" in cmd:
            period_end = date.fromisoformat(cmd[cmd.index("--period-end") + 1])
            name = f"test_{source}_{period_end:%y%m}.pdf"
        else:
            name = f"test_{source}_{datetime.now():%y%m}.pdf"
        if state.get("write", True):
            (tmp_path / source).mkdir(parents=True, exist_ok=True)
            (tmp_path / source / name).write_bytes(b"%PDF-1.4 fake")
        return subprocess.CompletedProcess(
            cmd, state.get("returncode", 0), "out", "err"
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    yield types.SimpleNamespace(module=module, calls=calls, state=state, root=tmp_path)
    sys.modules.pop("tests.e2e.pdf_fixture_paths", None)
    import tests.e2e as e2e_package

    if hasattr(e2e_package, "pdf_fixture_paths"):
        delattr(e2e_package, "pdf_fixture_paths")


def test_an_explicit_period_end_rebuilds_the_pdf_for_that_date(pdf_paths) -> None:
    stale = pdf_paths.root / "moomoo" / "test_moomoo_2605.pdf"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale build for another day")

    built = pdf_paths.module.generated_pdf_path("moomoo", period_end=date(2026, 5, 31))

    assert built == stale
    assert built.read_bytes() == b"%PDF-1.4 fake", "the PDF must be rebuilt, not reused"
    assert pdf_paths.calls[0][-2:] == ["--period-end", "2026-05-31"]


def test_without_period_end_the_current_month_build_is_reused(pdf_paths) -> None:
    prebuilt = pdf_paths.root / "dbs" / f"test_dbs_{datetime.now():%y%m}.pdf"
    prebuilt.parent.mkdir(parents=True)
    prebuilt.write_bytes(b"prebuilt")

    assert pdf_paths.module.generated_pdf_path("dbs") == prebuilt
    assert pdf_paths.calls == []


def test_without_period_end_a_missing_pdf_is_generated(pdf_paths) -> None:
    built = pdf_paths.module.generated_pdf_path("dbs")

    assert built.name == f"test_dbs_{datetime.now():%y%m}.pdf"
    assert len(pdf_paths.calls) == 1
    assert "--period-end" not in pdf_paths.calls[0]


def test_a_generator_that_writes_elsewhere_fails_as_path_drift(pdf_paths) -> None:
    pdf_paths.state["write"] = False

    with pytest.raises(pytest.fail.Exception, match="path drift"):
        pdf_paths.module.generated_pdf_path("moomoo", period_end=date(2026, 5, 31))


def test_a_generator_failure_fails_a_strict_gate_and_skips_elsewhere(pdf_paths) -> None:
    pdf_paths.state["returncode"] = 1

    # A skip raised inside pytest.raises(Failed) would turn this whole test into a skip,
    # which exits 0. Catch either outcome and assert which one happened.
    outcome = (pytest.fail.Exception, pytest.skip.Exception)

    pdf_paths.state["strict"] = True
    with pytest.raises(outcome, match="generation failed") as strict:
        pdf_paths.module.generated_pdf_path("moomoo", period_end=date(2026, 5, 31))
    assert strict.type is pytest.fail.Exception

    pdf_paths.state["strict"] = False
    with pytest.raises(outcome, match="generation failed") as lenient:
        pdf_paths.module.generated_pdf_path("moomoo", period_end=date(2026, 5, 31))
    assert lenient.type is pytest.skip.Exception


# ------------------------------------------- the journeys call the helper correctly


def _calls_named(path: Path, name: str) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


def test_the_report_package_journey_asks_for_the_fixture_period() -> None:
    calls = _calls_named(
        E2E / "test_personal_financial_report_package.py", "generated_pdf_path"
    )

    assert calls, "the journey must use generated_pdf_path"
    assert all(any(kw.arg == "period_end" for kw in call.keywords) for call in calls)


def test_the_upload_journeys_use_the_shared_pdf_helper() -> None:
    path = E2E / "test_statement_upload_e2e.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}

    assert "_get_test_pdf" not in defined, (
        "the private copy globbed a retired directory"
    )
    assert len(_calls_named(path, "generated_pdf_path")) == 2


def test_no_e2e_file_reads_the_retired_fixture_directory() -> None:
    retired = "pdf_fixtures" + "/output"
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in E2E.glob("*.py")
        if retired in p.read_text(encoding="utf-8")
        and p.name != "pdf_fixture_paths.py"  # its docstring names the retired path
    ]

    assert offenders == []
