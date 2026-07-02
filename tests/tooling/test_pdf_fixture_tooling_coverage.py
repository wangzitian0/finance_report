"""AC-testing.1.1 AC-testing.1.3 AC-testing.2.5 AC-testing.2.6 AC-testing.3.1
AC-testing.7.1 AC-testing.7.2 AC-testing.7.3: PDF fixture tooling behavior
(migrated from EPIC-009 to the `testing` package; see
common/testing/contract.py roadmap)."""

from __future__ import annotations

import sys
import builtins
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from common.testing.fixtures.pdf.analyzers import analyze_pdf as analyze_pdf_cli
from common.testing.fixtures.pdf.analyzers.pdf_analyzer import PDFAnalyzer, TemplateExtractor
from common.testing.fixtures.pdf.data.fake_data import (
    generate_cmb_transactions,
    generate_dbs_transactions,
    generate_mari_transactions,
    generate_moomoo_transactions,
    generate_pingan_transactions,
)
from common.testing.fixtures.pdf import generate_pdf_fixtures
from common.testing.fixtures.pdf.generators import font_utils
from common.testing.fixtures.pdf.validators.pdf_validator import PDFValidator


class _FakePdf:
    def __init__(self, pages: list[object]) -> None:
        self.pages = pages

    def __enter__(self) -> "_FakePdf":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_AC9_1_1_analyzer_extracts_page_table_and_text_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9.1.1: PDF analyzer extracts format metadata without transaction payloads."""
    page = SimpleNamespace(
        width=595.27,
        height=841.89,
        extract_tables=lambda: [
            [["Date", "Description", "Amount"], ["01/01/2025", "Coffee", "5.00"]]
        ],
        extract_text=lambda: "Statement Period\nTransaction Details\nBalance",
    )
    monkeypatch.setattr(
        "common.testing.fixtures.pdf.analyzers.pdf_analyzer.pdfplumber.open",
        lambda _path: _FakePdf([page]),
    )

    analysis = PDFAnalyzer().analyze(Path("statement.pdf"))

    assert analysis["page"] == {"width": 595.27, "height": 841.89, "size": "A4"}
    assert analysis["tables"][0]["header"] == ["Date", "Description", "Amount"]
    assert analysis["tables"][0]["row_count"] == 1
    assert analysis["text_positions"]["Transaction Details"]["found"] is True


def test_AC9_1_1_analyzer_rejects_unreadable_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9.1.1: PDF analyzer reports unreadable PDFs as deterministic errors."""

    def raise_open(_path: Path) -> object:
        raise RuntimeError("cannot parse")

    monkeypatch.setattr(
        "common.testing.fixtures.pdf.analyzers.pdf_analyzer.pdfplumber.open",
        raise_open,
    )

    with pytest.raises(ValueError, match="Failed to analyze PDF"):
        PDFAnalyzer().analyze(Path("bad.pdf"))


@pytest.mark.parametrize(
    ("source", "expected_first_column"),
    [
        ("dbs", "Date"),
        ("cmb", "记账日期"),
        ("mari", "DATE"),
        ("moomoo", "Date"),
        ("pingan", "交易日期"),
    ],
)
def test_AC9_1_3_template_extractor_emits_source_table_schema(
    source: str,
    expected_first_column: str,
) -> None:
    """AC9.1.3: Analyzer CLI template extraction supports each committed source schema."""
    template = TemplateExtractor().extract({"page": {"size": "A4"}}, source)

    assert template["source"] == source
    assert (
        template["tables"]["transaction_details"]["columns"][0]["name"]
        == expected_first_column
    )


def test_AC9_3_1_validator_reports_page_table_and_key_phrase_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9.3.1: PDF validator reports structural mismatches without throwing."""
    page = SimpleNamespace(
        width=612.0,
        height=900.0,
        extract_tables=lambda: [[["Wrong", "Header"], ["v1", "v2"]]],
        extract_text=lambda: "Account Summary",
    )
    monkeypatch.setattr(
        "common.testing.fixtures.pdf.validators.pdf_validator.pdfplumber.open",
        lambda _path: _FakePdf([page]),
    )

    result = PDFValidator().validate_structure(
        Path("generated.pdf"),
        {
            "page": {"width": 595.27, "height": 841.89},
            "tables": {
                "transaction_details": {
                    "key_phrase": "Transaction Details",
                    "columns": [
                        {"name": "Date"},
                        {"name": "Description"},
                        {"name": "Amount"},
                    ],
                }
            },
        },
    )

    assert result["success"] is True
    assert any("Page width mismatch" in warning for warning in result["warnings"])
    assert any("Column count mismatch" in warning for warning in result["warnings"])
    assert any(
        "Key phrase 'Transaction Details' not found" in warning
        for warning in result["warnings"]
    )


def test_AC9_3_1_validator_fails_empty_and_unreadable_pdfs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9.3.1: Empty or unreadable PDFs fail validation explicitly."""
    monkeypatch.setattr(
        "common.testing.fixtures.pdf.validators.pdf_validator.pdfplumber.open",
        lambda _path: _FakePdf([]),
    )
    empty_result = PDFValidator().validate_structure(Path("empty.pdf"), {})
    assert empty_result["success"] is False
    assert empty_result["errors"] == ["PDF has no pages"]

    def raise_open(_path: Path) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "common.testing.fixtures.pdf.validators.pdf_validator.pdfplumber.open",
        raise_open,
    )
    bad_result = PDFValidator().validate_structure(Path("bad.pdf"), {})
    assert bad_result["success"] is False
    assert bad_result["errors"] == ["Validation error: boom"]


def test_AC9_3_1_validator_compares_real_and_generated_structure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9.3.1: Local real/generated comparison surfaces page and table differences."""
    real_page = SimpleNamespace(extract_tables=lambda: [[["Date"]]])
    generated_page = SimpleNamespace(extract_tables=lambda: [])
    opened = iter([_FakePdf([real_page, real_page]), _FakePdf([generated_page])])
    monkeypatch.setattr(
        "common.testing.fixtures.pdf.validators.pdf_validator.pdfplumber.open",
        lambda _path: next(opened),
    )

    result = PDFValidator().compare_structure(Path("real.pdf"), Path("generated.pdf"))

    assert result["success"] is True
    assert "Page count: real=2, generated=1" in result["differences"]
    assert "Table count: real=1, generated=0" in result["differences"]


def test_AC9_3_1_validator_reports_compare_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9.3.1: Local PDF structure comparison reports parser failures."""

    def raise_open(_path: Path) -> object:
        raise RuntimeError("compare failed")

    monkeypatch.setattr(
        "common.testing.fixtures.pdf.validators.pdf_validator.pdfplumber.open",
        raise_open,
    )

    result = PDFValidator().compare_structure(Path("real.pdf"), Path("generated.pdf"))

    assert result == {"success": False, "differences": [], "error": "compare failed"}


def test_AC9_2_5_font_helpers_choose_safe_fonts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9.2.5: Font helpers gracefully fall back when CJK fonts are unavailable."""
    monkeypatch.setattr(font_utils.Path, "exists", lambda _self: False)

    assert font_utils.register_chinese_fonts() is None
    assert font_utils.get_safe_font("SimSun") == "Helvetica"
    assert font_utils.get_safe_font("SimHei-Bold") == "Helvetica-Bold"
    assert (
        font_utils.get_safe_font("UnknownFamily", chinese_font="ChineseFont")
        == "ChineseFont"
    )
    assert font_utils.can_display_chinese("Helvetica") is False
    assert font_utils.can_display_chinese("ChineseFont") is True


def test_AC9_2_5_font_registration_accepts_otf_fonts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9.2.5: Font registration accepts installed OpenType fonts."""
    registered: list[str] = []

    def fake_ttfont(name: str, path: str, **_kwargs: object) -> tuple[str, str]:
        return (name, path)

    fake_pdfmetrics = SimpleNamespace(
        registerFont=lambda font: registered.append(font[0]),
        getRegisteredFontNames=lambda: registered,
    )
    monkeypatch.setattr(
        font_utils.Path,
        "exists",
        lambda self: str(self).endswith("PingFangSC-Regular.otf"),
    )
    monkeypatch.setattr(font_utils, "TTFont", fake_ttfont)
    monkeypatch.setattr(font_utils, "pdfmetrics", fake_pdfmetrics)

    assert font_utils.register_chinese_fonts() == "ChineseFont"


def test_AC9_2_5_font_registration_retries_ttc_subfonts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9.2.5: Font registration retries TTC subfont indexes before falling back."""
    registered: list[str] = []
    attempted_subfonts: list[int | None] = []

    def fake_ttfont(name: str, _path: str, **kwargs: object) -> tuple[str, str]:
        subfont = kwargs.get("subfontIndex")
        attempted_subfonts.append(subfont if isinstance(subfont, int) else None)
        if subfont == 0:
            raise RuntimeError("bad subfont")
        return (name, "font")

    fake_pdfmetrics = SimpleNamespace(
        registerFont=lambda font: registered.append(font[0]),
        getRegisteredFontNames=lambda: registered,
    )
    monkeypatch.setattr(
        font_utils.Path,
        "exists",
        lambda self: str(self).endswith("STHeiti Medium.ttc"),
    )
    monkeypatch.setattr(font_utils, "TTFont", fake_ttfont)
    monkeypatch.setattr(font_utils, "pdfmetrics", fake_pdfmetrics)

    assert font_utils.register_chinese_fonts() == "ChineseFont"
    assert attempted_subfonts == [0, 1]


def test_AC9_2_5_font_registration_continues_after_ttf_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC9.2.5: Font registration logs unusable TTF files and keeps scanning."""

    def raise_ttfont(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("bad font")

    monkeypatch.setattr(
        font_utils.Path,
        "exists",
        lambda self: str(self).endswith("simhei.ttf"),
    )
    monkeypatch.setattr(font_utils, "TTFont", raise_ttfont)

    assert font_utils.register_chinese_fonts() is None
    assert "Warning: Failed to load font" in capsys.readouterr().out


@pytest.mark.parametrize(
    "generator",
    [
        generate_dbs_transactions,
        generate_cmb_transactions,
        generate_mari_transactions,
        generate_moomoo_transactions,
        generate_pingan_transactions,
    ],
)
def test_AC9_2_6_fake_data_generators_keep_running_balances(generator) -> None:
    """AC9.2.6: Fake transaction data returns deterministic counts and matching balances."""
    opening_balance = generator.__defaults__[1]
    transactions, closing_balance = generator(datetime(2025, 1, 1), count=3)

    amount_key = "amount_decimal" if "amount_decimal" in transactions[0] else "amount"
    expected_closing = opening_balance + sum(txn[amount_key] for txn in transactions)

    assert len(transactions) >= 3
    assert closing_balance == expected_closing


def test_AC9_7_1_legacy_dbs_generator_writes_backward_compatible_pdf(
    tmp_path: Path,
) -> None:
    """AC9.7.1: Legacy fixture generation still emits the original DBS PDF shape."""
    output_path = tmp_path / "legacy.pdf"

    generate_pdf_fixtures.generate_legacy_dbs_pdf(output_path)

    assert output_path.read_bytes().startswith(b"%PDF")


def test_AC9_7_1_main_legacy_mode_uses_backward_compatible_filename(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC9.7.1: Legacy CLI mode writes e2e_dbs_statement.pdf for existing E2E callers."""
    generated: list[Path] = []

    def fake_generate(output_path: Path) -> None:
        generated.append(output_path)
        output_path.write_bytes(b"%PDF fake")

    monkeypatch.setattr(sys, "argv", ["generate_pdf_fixtures.py", str(tmp_path)])
    monkeypatch.setattr(generate_pdf_fixtures, "generate_legacy_dbs_pdf", fake_generate)

    generate_pdf_fixtures.main()

    assert generated == [tmp_path / "e2e_dbs_statement.pdf"]
    assert generated[0].read_bytes() == b"%PDF fake"


def test_AC9_7_1_main_legacy_mode_defaults_to_tmp_fixtures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC9.7.1: Legacy CLI mode keeps the tmp/fixtures default for E2E callers."""
    generated: list[Path] = []

    def fake_generate(output_path: Path) -> None:
        generated.append(output_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["generate_pdf_fixtures.py"])
    monkeypatch.setattr(generate_pdf_fixtures, "generate_legacy_dbs_pdf", fake_generate)

    generate_pdf_fixtures.main()

    assert generated == [Path("tmp/fixtures") / "e2e_dbs_statement.pdf"]
    assert (tmp_path / "tmp" / "fixtures").is_dir()


def test_AC9_7_1_AC9_7_2_main_generates_selected_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC9.7.1 AC9.7.2: Main fixture CLI honors --source and --output."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_pdf_fixtures.py",
            "--source",
            "dbs",
            "--output",
            str(tmp_path),
        ],
    )

    generate_pdf_fixtures.main()

    generated = list((tmp_path / "dbs").glob("test_dbs_*.pdf"))
    assert len(generated) == 1
    assert generated[0].read_bytes().startswith(b"%PDF")


def test_AC9_7_1_AC9_7_2_main_generates_all_sources_with_default_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC9.7.1 AC9.7.2: --source all dispatches every generator branch."""
    generated: list[tuple[str, Path, Path]] = []

    def make_generator(source: str):
        class FakeGenerator:
            def __init__(self, template_path: Path) -> None:
                self.template_path = template_path

            def generate(
                self,
                output_path: Path,
                period_start: datetime,
                period_end: datetime,
            ) -> None:
                assert period_start < period_end
                generated.append((source, self.template_path, output_path))

        return FakeGenerator

    import common.testing.fixtures.pdf.generators.cmb_generator as cmb_module
    import common.testing.fixtures.pdf.generators.dbs_generator as dbs_module
    import common.testing.fixtures.pdf.generators.futu_generator as futu_module
    import common.testing.fixtures.pdf.generators.mari_generator as mari_module
    import common.testing.fixtures.pdf.generators.moomoo_generator as moomoo_module
    import common.testing.fixtures.pdf.generators.pingan_generator as pingan_module

    monkeypatch.setattr(cmb_module, "CMBGenerator", make_generator("cmb"))
    monkeypatch.setattr(dbs_module, "DBSGenerator", make_generator("dbs"))
    monkeypatch.setattr(futu_module, "FutuGenerator", make_generator("futu"))
    monkeypatch.setattr(mari_module, "MariGenerator", make_generator("mari"))
    monkeypatch.setattr(moomoo_module, "MoomooGenerator", make_generator("moomoo"))
    monkeypatch.setattr(pingan_module, "PinganGenerator", make_generator("pingan"))
    monkeypatch.setattr(
        generate_pdf_fixtures,
        "__file__",
        str(tmp_path / "generate_pdf_fixtures.py"),
    )
    monkeypatch.setattr(sys, "argv", ["generate_pdf_fixtures.py", "--source", "all"])

    generate_pdf_fixtures.main()

    assert [source for source, _, _ in generated] == [
        "dbs",
        "cmb",
        "mari",
        "moomoo",
        "futu",
        "pingan",
    ]
    for source, template_path, output_path in generated:
        assert template_path == tmp_path / "templates" / f"{source}_template.yaml"
        assert output_path.parent == tmp_path / "output" / source
        assert output_path.name.startswith(f"test_{source}_")


def test_AC9_7_1_main_reports_generator_import_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC9.7.1: Main fixture CLI fails closed when generator imports fail."""
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "generators.cmb_generator" and level == 1:
            raise ImportError("missing cmb generator")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_pdf_fixtures.py", "--source", "dbs", "--output", str(tmp_path)],
    )

    with pytest.raises(SystemExit) as exc:
        generate_pdf_fixtures.main()

    assert exc.value.code == 1
    assert "missing cmb generator" in capsys.readouterr().out


def test_AC9_7_1_main_reports_generator_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC9.7.1: Main fixture CLI fails closed when a selected generator raises."""

    class BrokenGenerator:
        def __init__(self, _template_path: Path) -> None:
            pass

        def generate(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("broken generator")

    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_pdf_fixtures.py", "--source", "dbs", "--output", str(tmp_path)],
    )

    # Patch the imported class inside the real generators module path used by main().
    import common.testing.fixtures.pdf.generators.dbs_generator as dbs_module

    monkeypatch.setattr(dbs_module, "DBSGenerator", BrokenGenerator)

    with pytest.raises(SystemExit) as exc:
        generate_pdf_fixtures.main()

    assert exc.value.code == 1


def test_AC9_1_3_analyzer_cli_writes_template_yaml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC9.1.3 AC9.7.3: Analyzer CLI writes extracted source templates without payload data."""
    input_pdf = tmp_path / "input.pdf"
    output_yaml = tmp_path / "templates" / "dbs.yaml"
    input_pdf.write_bytes(b"%PDF fake")

    class FakeAnalyzer:
        def analyze(self, pdf_path: Path) -> dict[str, object]:
            assert pdf_path == input_pdf
            return {"page": {"size": "A4"}}

    class FakeExtractor:
        def extract(
            self, analysis: dict[str, object], source: str
        ) -> dict[str, object]:
            assert analysis == {"page": {"size": "A4"}}
            return {
                "source": source,
                "tables": {"transaction_details": {"columns": []}},
            }

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "analyze_pdf.py",
            "--input",
            str(input_pdf),
            "--output",
            str(output_yaml),
            "--source",
            "dbs",
        ],
    )
    monkeypatch.setattr(analyze_pdf_cli, "PDFAnalyzer", FakeAnalyzer)
    monkeypatch.setattr(analyze_pdf_cli, "TemplateExtractor", FakeExtractor)

    analyze_pdf_cli.main()

    assert "source: dbs" in output_yaml.read_text()


def test_AC9_1_3_analyzer_cli_rejects_missing_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC9.1.3 AC9.7.3: Analyzer CLI fails before extraction when the local input PDF is missing."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "analyze_pdf.py",
            "--input",
            str(tmp_path / "missing.pdf"),
            "--output",
            str(tmp_path / "out.yaml"),
            "--source",
            "dbs",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        analyze_pdf_cli.main()

    assert exc.value.code == 1


def test_AC9_1_3_analyzer_cli_reports_extraction_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC9.1.3 AC9.7.3: Analyzer CLI exits non-zero when analysis fails."""
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF fake")

    class BrokenAnalyzer:
        def analyze(self, _pdf_path: Path) -> dict[str, object]:
            raise RuntimeError("analysis failed")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "analyze_pdf.py",
            "--input",
            str(input_pdf),
            "--output",
            str(tmp_path / "out.yaml"),
            "--source",
            "dbs",
        ],
    )
    monkeypatch.setattr(analyze_pdf_cli, "PDFAnalyzer", BrokenAnalyzer)

    with pytest.raises(SystemExit) as exc:
        analyze_pdf_cli.main()

    assert exc.value.code == 1
