from __future__ import annotations

import re
import sys
from importlib import import_module
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "pdf_fixtures"))


DBS_DATE_PATTERN = re.compile(r"^\d{2}/\d{2}/\d{4}$")
CMB_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MARI_DATE_PATTERN = re.compile(r"^\d{2}\s[A-Z]{3}$")


def _parse_decimal(raw: str) -> Decimal:
    match = re.search(r"-?[0-9][0-9,]*\.[0-9]{2}", raw)
    if not match:
        raise ValueError(f"No decimal value found in '{raw}'")
    return Decimal(match.group(0).replace(",", ""))


def _read_pdf_text_and_tables(
    pdf_path: Path,
) -> tuple[str, list[list[list[str | None]]]]:
    all_text: list[str] = []
    all_tables: list[list[list[str | None]]] = []
    pdfplumber = import_module("pdfplumber")
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            all_text.append(page.extract_text() or "")
            all_tables.extend(page.extract_tables() or [])
    return "\n".join(all_text), all_tables


def _get_generator_classes() -> tuple[type, type, type]:
    dbs_cls = import_module("generators.dbs_generator").DBSGenerator
    cmb_cls = import_module("generators.cmb_generator").CMBGenerator
    mari_cls = import_module("generators.mari_generator").MariGenerator
    return dbs_cls, cmb_cls, mari_cls


def _search_decimal(pattern: str, text: str) -> Decimal:
    match = re.search(pattern, text)
    if not match:
        raise AssertionError(f"Missing value for pattern: {pattern}")
    return _parse_decimal(match.group(1))


def _assert_valid_pdf(pdf_path: Path) -> None:
    assert pdf_path.exists(), f"Generated PDF not found: {pdf_path}"
    assert pdf_path.stat().st_size > 0, "Generated PDF is empty"
    assert pdf_path.read_bytes().startswith(b"%PDF"), (
        "Generated file is not a valid PDF"
    )


def _extract_dbs_rows(tables: list[list[list[str | None]]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for table in tables:
        for row in table:
            if not row or len(row) < 5:
                continue
            if row[0] and DBS_DATE_PATTERN.match(row[0].strip()):
                rows.append([cell.strip() if cell else "" for cell in row[:5]])
    return rows


def _extract_cmb_rows(tables: list[list[list[str | None]]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for table in tables:
        for row in table:
            if not row or len(row) < 6:
                continue
            if row[0] and CMB_DATE_PATTERN.match(row[0].strip()):
                rows.append([cell.strip() if cell else "" for cell in row[:6]])
    return rows


def _extract_mari_rows(tables: list[list[list[str | None]]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for table in tables:
        for row in table:
            if not row or len(row) < 4:
                continue
            if row[0] and MARI_DATE_PATTERN.match(row[0].strip()):
                rows.append([cell.strip() if cell else "" for cell in row[:4]])
    return rows


def _extract_mari_summary_balances(
    text: str,
    tables: list[list[list[str | None]]],
) -> tuple[Decimal, Decimal]:
    # First try structured table lookup
    for table in tables:
        if len(table) < 2:
            continue
        header = [cell.strip() if cell else "" for cell in table[0]]
        if "Opening Balance" in header and "Ending Balance" in header:
            values = [cell.strip() if cell else "" for cell in table[1]]
            ob_idx = header.index("Opening Balance")
            eb_idx = header.index("Ending Balance")
            return _parse_decimal(values[ob_idx]), _parse_decimal(values[eb_idx])
    # Fallback: parse from text line containing multiple SGD values
    # Line format: "{account} SGD {opening} SGD {outgoing} SGD {incoming} SGD {closing}"
    sgd_pattern = re.compile(r"SGD\s+([0-9,]+\.[0-9]{2})")
    for line in text.splitlines():
        matches = sgd_pattern.findall(line)
        if len(matches) >= 4:
            # opening=matches[0], outgoing=matches[1], incoming=matches[2], closing=matches[3]
            return Decimal(matches[0].replace(",", "")), Decimal(matches[3].replace(",", ""))
    raise AssertionError(
        "Mari account summary table with opening/ending balance not found"
    )


def test_ac9_3_2_dbs_generated_pdf_parseable(tmp_path: Path) -> None:
    dbs_generator, _, _ = _get_generator_classes()
    output_path = tmp_path / "dbs" / "test_dbs.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    generator = dbs_generator(
        Path(__file__).parent.parent
        / "pdf_fixtures"
        / "templates"
        / "dbs_template.yaml"
    )
    generator.generate(output_path, datetime(2025, 1, 1), datetime(2025, 1, 31))

    _assert_valid_pdf(output_path)
    text, tables = _read_pdf_text_and_tables(output_path)
    rows = _extract_dbs_rows(tables)

    assert "Opening Balance" in text
    assert "Closing Balance" in text
    assert len(rows) > 0
    assert len(rows) == 15
    assert all(DBS_DATE_PATTERN.match(row[0]) for row in rows)
    for row in rows:
        if row[2]:
            _parse_decimal(row[2])
        if row[3]:
            _parse_decimal(row[3])
        _parse_decimal(row[4])


def test_ac9_3_3_cmb_generated_pdf_parseable(tmp_path: Path) -> None:
    _, cmb_generator, _ = _get_generator_classes()
    output_path = tmp_path / "cmb" / "test_cmb.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    generator = cmb_generator(
        Path(__file__).parent.parent
        / "pdf_fixtures"
        / "templates"
        / "cmb_template.yaml"
    )
    generator.generate(output_path, datetime(2025, 1, 1), datetime(2025, 1, 31))

    _assert_valid_pdf(output_path)
    text, tables = _read_pdf_text_and_tables(output_path)
    rows = _extract_cmb_rows(tables)

    # CJK text may render as replacement chars on systems without CJK fonts;
    # check for balance values instead (always ASCII)
    assert "CNY" in text, "CMB statement should contain currency CNY"
    assert len(rows) > 0
    assert len(rows) == 20
    assert all(CMB_DATE_PATTERN.match(row[0]) for row in rows)
    for row in rows:
        _parse_decimal(row[2])
        _parse_decimal(row[3])


def test_ac9_3_4_mari_generated_pdf_parseable(tmp_path: Path) -> None:
    _, _, mari_generator = _get_generator_classes()
    output_path = tmp_path / "mari" / "test_mari.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    generator = mari_generator(
        Path(__file__).parent.parent
        / "pdf_fixtures"
        / "templates"
        / "mari_template.yaml"
    )
    generator.generate(output_path, datetime(2025, 1, 1), datetime(2025, 1, 31))

    _assert_valid_pdf(output_path)
    text, tables = _read_pdf_text_and_tables(output_path)
    rows = _extract_mari_rows(tables)

    assert "TRANSACTION DETAILS" in text
    assert "Opening Balance" in text
    assert "Ending Balance" in text
    assert len(rows) > 0
    assert len(rows) == 12
    assert all(MARI_DATE_PATTERN.match(row[0]) for row in rows)
    for row in rows:
        if row[2]:
            _parse_decimal(row[2])
        if row[3]:
            _parse_decimal(row[3])


def test_ac9_3_5_balance_calculations_correct(tmp_path: Path) -> None:
    dbs_generator, cmb_generator, mari_generator = _get_generator_classes()
    fixtures_root = tmp_path / "fixtures"
    fixtures_root.mkdir(parents=True, exist_ok=True)

    dbs_path = fixtures_root / "dbs.pdf"
    cmb_path = fixtures_root / "cmb.pdf"
    mari_path = fixtures_root / "mari.pdf"

    dbs_generator(
        Path(__file__).parent.parent
        / "pdf_fixtures"
        / "templates"
        / "dbs_template.yaml"
    ).generate(
        dbs_path,
        datetime(2025, 1, 1),
        datetime(2025, 1, 31),
    )
    cmb_generator(
        Path(__file__).parent.parent
        / "pdf_fixtures"
        / "templates"
        / "cmb_template.yaml"
    ).generate(
        cmb_path,
        datetime(2025, 1, 1),
        datetime(2025, 1, 31),
    )
    mari_generator(
        Path(__file__).parent.parent
        / "pdf_fixtures"
        / "templates"
        / "mari_template.yaml"
    ).generate(
        mari_path,
        datetime(2025, 1, 1),
        datetime(2025, 1, 31),
    )

    dbs_text, dbs_tables = _read_pdf_text_and_tables(dbs_path)
    dbs_rows = _extract_dbs_rows(dbs_tables)
    dbs_opening = _search_decimal(
        r"Opening Balance:\s*SGD\s*([0-9,]+\.[0-9]{2})", dbs_text
    )
    dbs_closing = _search_decimal(
        r"Closing Balance:\s*SGD\s*([0-9,]+\.[0-9]{2})", dbs_text
    )
    dbs_delta = sum(
        (_parse_decimal(row[3]) if row[3] else Decimal("0"))
        - (_parse_decimal(row[2]) if row[2] else Decimal("0"))
        for row in dbs_rows
    )
    assert abs((dbs_opening + dbs_delta) - dbs_closing) <= Decimal("0.01")

    _, cmb_tables = _read_pdf_text_and_tables(cmb_path)
    cmb_rows = _extract_cmb_rows(cmb_tables)
    # Opening balance is hardcoded in CMBGenerator; closing = last row's running balance
    # CJK text unreliable on CI (no CJK fonts) - use table data instead
    cmb_opening = Decimal("10000.00")
    cmb_closing = _parse_decimal(cmb_rows[-1][3])  # last row running balance
    cmb_delta = sum(_parse_decimal(row[2]) for row in cmb_rows)
    assert abs((cmb_opening + cmb_delta) - cmb_closing) <= Decimal("0.01")

    mari_text, mari_tables = _read_pdf_text_and_tables(mari_path)
    mari_rows = _extract_mari_rows(mari_tables)
    mari_opening, mari_closing = _extract_mari_summary_balances(mari_text, mari_tables)
    mari_delta = sum(
        (_parse_decimal(row[3]) if row[3] else Decimal("0"))
        - (_parse_decimal(row[2]) if row[2] else Decimal("0"))
        for row in mari_rows
    )
    assert abs((mari_opening + mari_delta) - mari_closing) <= Decimal("0.01")


def test_ac9_3_6_date_formats_correct_per_source(tmp_path: Path) -> None:
    dbs_generator, cmb_generator, mari_generator = _get_generator_classes()
    period_start = datetime(2025, 1, 1)
    period_end = datetime(2025, 1, 31)

    dbs_path = tmp_path / "dbs.pdf"
    cmb_path = tmp_path / "cmb.pdf"
    mari_path = tmp_path / "mari.pdf"

    dbs_generator(
        Path(__file__).parent.parent
        / "pdf_fixtures"
        / "templates"
        / "dbs_template.yaml"
    ).generate(
        dbs_path,
        period_start,
        period_end,
    )
    cmb_generator(
        Path(__file__).parent.parent
        / "pdf_fixtures"
        / "templates"
        / "cmb_template.yaml"
    ).generate(
        cmb_path,
        period_start,
        period_end,
    )
    mari_generator(
        Path(__file__).parent.parent
        / "pdf_fixtures"
        / "templates"
        / "mari_template.yaml"
    ).generate(
        mari_path,
        period_start,
        period_end,
    )

    dbs_rows = _extract_dbs_rows(_read_pdf_text_and_tables(dbs_path)[1])
    cmb_rows = _extract_cmb_rows(_read_pdf_text_and_tables(cmb_path)[1])
    mari_rows = _extract_mari_rows(_read_pdf_text_and_tables(mari_path)[1])

    assert all(DBS_DATE_PATTERN.match(row[0]) for row in dbs_rows)
    assert all(CMB_DATE_PATTERN.match(row[0]) for row in cmb_rows)
    assert all(MARI_DATE_PATTERN.match(row[0]) for row in mari_rows)
