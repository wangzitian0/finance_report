"""Brokerage OCR prompt contract tests."""

import importlib.util
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
STATEMENT_PROMPT_PATH = (
    ROOT
    / "apps"
    / "backend"
    / "src"
    / "extraction"
    / "extension"
    / "prompts"
    / "statement.py"
)


def _load_statement_prompt_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "backend_statement_prompt", STATEMENT_PROMPT_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_brokerage_prompt_maps_generated_broker_rows_to_positions() -> None:
    """Generated brokerage fixtures must not yield empty positions."""
    statement_prompt = _load_statement_prompt_module()

    moomoo_prompt = statement_prompt.get_parsing_prompt(
        "Moomoo", document_kind="brokerage"
    )
    futu_prompt = statement_prompt.get_parsing_prompt("Futu", document_kind="brokerage")

    assert "SUBSCRIPTION" in moomoo_prompt
    assert "Fullerton SGD Money Market Fund" in moomoo_prompt
    assert "emit it as a position" in moomoo_prompt
    assert "VALUATION" in futu_prompt
    assert "Stock and options valuation" in futu_prompt
    assert "emit it as a position" in futu_prompt
    assert "do not assume HKD" in futu_prompt
    assert "generated fixtures and some real statements may use SGD" in futu_prompt
