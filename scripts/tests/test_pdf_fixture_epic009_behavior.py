"""Behavior-backed EPIC-009 PDF fixture generation coverage."""

from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pytest
import yaml

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
PDF_FIXTURES = SCRIPTS_ROOT / "pdf_fixtures"
sys.path.insert(0, str(SCRIPTS_ROOT))
sys.path.insert(0, str(PDF_FIXTURES))

from analyzers.template_extractor import TemplateExtractor as SanitizingTemplateExtractor  # noqa: E402
from generators.base_generator import BasePDFGenerator  # noqa: E402
from generators.cmb_generator import CMBGenerator  # noqa: E402
from generators.dbs_generator import DBSGenerator  # noqa: E402
import generators.mari_generator as mari_module  # noqa: E402
from generators.mari_generator import MariGenerator  # noqa: E402


def _load_template(name: str) -> dict:
    return yaml.safe_load((PDF_FIXTURES / "templates" / name).read_text())


def test_AC9_1_2_template_extractor_writes_sanitized_format_yaml(tmp_path: Path) -> None:
    """AC9.1.2: Template extractor writes format YAML while removing sensitive payloads."""
    output_path = tmp_path / "templates" / "safe.yaml"
    result = SanitizingTemplateExtractor().extract(
        {
            "source": "dbs",
            "account_number": "12345678",
            "customer_name": "Jane Realperson",
            "tables": [{"header": ["Date", "Amount"], "row_count": 2}],
            "sample": "Balance 1,234.56 for account 87654321",
        },
        output_path,
    )

    loaded = yaml.safe_load(output_path.read_text())
    assert loaded == result
    assert "account_number" not in loaded
    assert "customer_name" not in loaded
    assert "12345678" not in output_path.read_text()
    assert "[REDACTED_AMOUNT]" in output_path.read_text()
    assert loaded["tables"][0]["header"] == ["Date", "Amount"]


@pytest.mark.parametrize(
    ("ac_id", "template_name", "source", "expected_columns"),
    [
        ("AC9.1.4", "dbs_template.yaml", "dbs", ["Date", "Description", "Withdrawal", "Deposit", "Balance"]),
        ("AC9.1.5", "cmb_template.yaml", "cmb", ["记账日期", "货币", "交易金额", "联机余额", "交易摘要", "对手信息"]),
        ("AC9.1.6", "mari_template.yaml", "mari", ["DATE", "TRANSACTION", "OUTGOING (SGD)", "INCOMING (SGD)"]),
    ],
)
def test_AC9_1_4_AC9_1_5_AC9_1_6_committed_templates_define_source_schemas(
    ac_id: str,
    template_name: str,
    source: str,
    expected_columns: list[str],
) -> None:
    """AC9.1.4 AC9.1.5 AC9.1.6: committed templates define concrete source schemas."""
    template = _load_template(template_name)

    assert ac_id.startswith("AC9.1.")
    assert template["source"] == source
    assert template["page"]["size"] == "A4"
    assert "fonts" in template
    columns = template["tables"]["transaction_details"]["columns"]
    assert [column["name"] for column in columns] == expected_columns
    assert all(column["width"] > 0 for column in columns)
    assert all(column["align"] in {"left", "right", "center"} for column in columns)


def test_AC9_2_1_base_generator_loads_template_and_applies_layout(tmp_path: Path) -> None:
    """AC9.2.1: Base generator loads YAML, margins, fonts, widths, and table style."""
    template_path = tmp_path / "template.yaml"
    template_path.write_text(
        yaml.safe_dump(
            {
                "source": "unit",
                "page": {"size": "A4", "margins": {"left": 11, "bottom": 22, "right": 33, "top": 44}},
                "fonts": {"body": {"family": "MissingFont", "size": 7}, "table_header": {"family": "Helvetica-Bold", "size": 8}},
                "tables": {
                    "transaction_details": {
                        "columns": [
                            {"name": "A", "width": 12, "align": "left"},
                            {"name": "B", "width": 34, "align": "right"},
                        ],
                        "header_style": {"background": "#CCCCCC", "text_color": "#000000"},
                        "row_style": {"background": "#FFFFFF", "border": "1px solid #000000"},
                    }
                },
            }
        )
    )

    generator = BasePDFGenerator(template_path)
    table_config = generator.template["tables"]["transaction_details"]

    assert generator.source == "unit"
    assert generator._get_margins() == (11, 22, 33, 44)
    assert generator._get_font("body") == ("Helvetica", 7)
    assert generator._get_column_widths(table_config) == [12, 34]
    assert generator._create_table_style(table_config).getCommands()
    with pytest.raises(FileNotFoundError):
        BasePDFGenerator(tmp_path / "missing.yaml")


@pytest.mark.parametrize(
    ("klass", "template_name", "expected_source", "ac_id"),
    [
        (DBSGenerator, "dbs_template.yaml", "dbs", "AC9.2.2"),
        (CMBGenerator, "cmb_template.yaml", "cmb", "AC9.2.3"),
        (MariGenerator, "mari_template.yaml", "mari", "AC9.2.4"),
    ],
)
def test_AC9_2_2_AC9_2_3_AC9_2_4_generators_load_committed_templates(
    klass: type[BasePDFGenerator],
    template_name: str,
    expected_source: str,
    ac_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC9.2.2 AC9.2.3 AC9.2.4: bank-specific generators load committed templates."""
    if klass is CMBGenerator:
        monkeypatch.setattr("generators.cmb_generator.register_chinese_fonts", lambda: None)

    generator = klass(PDF_FIXTURES / "templates" / template_name)

    assert ac_id.startswith("AC9.2.")
    assert generator.source == expected_source
    assert generator.template["tables"]["transaction_details"]["columns"]


def test_AC9_2_7_main_script_registers_all_supported_generators() -> None:
    """AC9.2.7: Main script exposes all committed PDF fixture generators."""
    import generate_pdf_fixtures

    text = Path(generate_pdf_fixtures.__file__).read_text()

    for token in (
        "DBSGenerator",
        "CMBGenerator",
        "MariGenerator",
        "MoomooGenerator",
        "FutuGenerator",
        "PinganGenerator",
    ):
        assert token in text
    assert 'choices=["dbs", "cmb", "mari", "moomoo", "futu", "pingan", "all"]' in text


def test_AC9_4_1_AC9_4_2_AC9_4_3_AC9_4_4_readmes_document_analysis_generation_templates_and_examples() -> None:
    """AC9.4.1 AC9.4.2 AC9.4.3 AC9.4.4: README documents analysis, generation, template format, and examples."""
    analyzer_readme = (PDF_FIXTURES / "analyzers" / "README.md").read_text()
    readme = (PDF_FIXTURES / "README.md").read_text()
    font_readme = (PDF_FIXTURES / "FONT_HANDLING.md").read_text()

    assert "PDF Format Analysis" in analyzer_readme
    assert "python analyzers/analyze_pdf.py" in analyzer_readme
    assert "must stay local" in analyzer_readme
    assert "format-only metadata" in analyzer_readme
    assert "Analyze Real PDF" in readme
    assert "Generate Test PDFs" in readme
    assert "Format templates" in readme
    assert "python analyzers/analyze_pdf.py" in readme
    assert "python generate_pdf_fixtures.py --source dbs" in readme
    assert "templates/*.yaml" in readme
    assert "input/" in readme and "gitignored" in readme
    assert "register_chinese_fonts()" in font_readme


def test_AC9_5_1_AC9_5_2_AC9_5_3_AC9_5_4_AC9_5_5_git_contract_tracks_safe_sources_only() -> None:
    """AC9.5.1 AC9.5.2 AC9.5.3 AC9.5.4 AC9.5.5: git contract ignores sensitive PDFs and keeps safe tooling committed."""
    gitignore = (PDF_FIXTURES / ".gitignore").read_text()

    assert "input/**/*.pdf" in gitignore
    assert "input/**/*.PDF" in gitignore
    assert "output/**/*.pdf" in gitignore
    assert "output/**/*.PDF" in gitignore
    for relative_path in (
        "templates/dbs_template.yaml",
        "templates/cmb_template.yaml",
        "templates/mari_template.yaml",
        "generators/dbs_generator.py",
        "generators/cmb_generator.py",
        "generators/mari_generator.py",
        "analyzers/pdf_analyzer.py",
        "analyzers/template_extractor.py",
        "validators/pdf_validator.py",
    ):
        assert (PDF_FIXTURES / relative_path).is_file()


def test_AC9_6_1_AC9_6_2_generators_preserve_template_source_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC9.6.1 AC9.6.2: DBS and CMB generators load their own source templates."""
    monkeypatch.setattr("generators.cmb_generator.register_chinese_fonts", lambda: None)

    dbs = DBSGenerator(PDF_FIXTURES / "templates" / "dbs_template.yaml")
    cmb = CMBGenerator(PDF_FIXTURES / "templates" / "cmb_template.yaml")

    assert dbs.source == "dbs"
    assert dbs.template["text_elements"]["currency"] == "SGD"
    assert cmb.source == "cmb"
    assert cmb.template["text_elements"]["currency"] == "CNY"
    assert cmb.template["fonts"]["body"]["family"] == "SimSun"


def test_AC9_6_3_cmb_generator_uses_registered_chinese_font(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC9.6.3: CMB generator applies registered Chinese fonts to header/body/table."""
    captured_styles: list[object] = []
    captured_table_styles: list[object] = []

    class FakeDoc:
        def build(self, elements: list[object]) -> None:
            captured_styles.extend(getattr(element, "style", None) for element in elements)

    class FakeParagraph:
        def __init__(self, _text: str, style: object) -> None:
            self.style = style

    class FakeTable:
        def __init__(self, _data: list[list[str]], colWidths: list[float]) -> None:
            self.col_widths = colWidths

        def setStyle(self, style: object) -> None:
            captured_table_styles.append(style)

    monkeypatch.setattr("generators.cmb_generator.register_chinese_fonts", lambda: "ChineseFont")
    monkeypatch.setattr("generators.cmb_generator.Paragraph", FakeParagraph)
    monkeypatch.setattr("generators.cmb_generator.Table", FakeTable)
    monkeypatch.setattr(CMBGenerator, "create_document", lambda self, output_path: FakeDoc())

    generator = CMBGenerator(PDF_FIXTURES / "templates" / "cmb_template.yaml")
    generator.generate(tmp_path / "cmb.pdf", datetime(2025, 1, 1), datetime(2025, 1, 31))

    assert generator.chinese_font == "ChineseFont"
    assert any(getattr(style, "fontName", None) == "ChineseFont" for style in captured_styles)
    commands = captured_table_styles[0].getCommands()
    assert ("FONTNAME", (0, 0), (-1, -1), "ChineseFont") in commands


def test_AC9_6_4_mari_generator_renders_interest_details_section(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC9.6.4: Mari generator renders an interest section from interest transactions."""
    rendered_text: list[str] = []
    rendered_tables: list[list[list[str]]] = []

    class FakeDoc:
        def build(self, _elements: list[object]) -> None:
            return None

    class FakeParagraph:
        def __init__(self, text: str, _style: object) -> None:
            rendered_text.append(text)

    class FakeTable:
        def __init__(self, data: list[list[str]], colWidths: list[float]) -> None:
            rendered_tables.append(data)
            self.col_widths = colWidths

        def setStyle(self, _style: object) -> None:
            return None

    def fake_transactions(*_args: object, **_kwargs: object) -> tuple[list[dict[str, object]], Decimal]:
        return (
            [
                {
                    "date": "02 JAN",
                    "description": "Interest Credit",
                    "outgoing": "",
                    "incoming": "1.25",
                    "amount": Decimal("1.25"),
                },
                {
                    "date": "03 JAN",
                    "description": "PayNow Payment",
                    "outgoing": "5.00",
                    "incoming": "",
                    "amount": Decimal("-5.00"),
                },
            ],
            Decimal("2996.25"),
        )

    monkeypatch.setattr(mari_module, "generate_mari_transactions", fake_transactions)
    monkeypatch.setattr(mari_module, "Paragraph", FakeParagraph)
    monkeypatch.setattr(mari_module, "Table", FakeTable)
    monkeypatch.setattr(MariGenerator, "create_document", lambda self, output_path: FakeDoc())

    MariGenerator(PDF_FIXTURES / "templates" / "mari_template.yaml").generate(
        tmp_path / "mari.pdf",
        datetime(2025, 1, 1),
        datetime(2025, 1, 31),
    )

    assert "INTEREST DETAILS" in rendered_text
    interest_table = next(table for table in rendered_tables if table[0] == ["Date", "Interest"])
    assert ["02 JAN", "1.25"] in interest_table
    assert all(row[0] != "03 JAN" for row in interest_table[1:])


def test_AC9_6_5_generators_use_masked_accounts_and_fictional_data(tmp_path: Path) -> None:
    """AC9.6.5: Generators use masked accounts and fictional transaction payloads."""
    output_path = tmp_path / "dbs.pdf"

    DBSGenerator(PDF_FIXTURES / "templates" / "dbs_template.yaml").generate(
        output_path,
        datetime(2025, 1, 1),
        datetime(2025, 1, 31),
        account_last4="9876",
    )

    pdf_bytes = output_path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF")
    pdfplumber = import_module("pdfplumber")
    with pdfplumber.open(output_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "***-****-9876" in text
    assert "***-****-1234" not in text
    assert "12345678" not in text
    source_text = (PDF_FIXTURES / "data" / "fake_data.py").read_text()
    assert "TEST USER" not in source_text
    assert "John Doe" not in source_text
    assert "Jane" not in source_text
    assert "GRAB RIDE" in source_text
