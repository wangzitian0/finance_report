"""Source vocabulary belongs to extraction's pure core, never its adapters."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "apps/backend/src/extraction"
OWNER = PACKAGE / "base/source_vocabulary.py"
VALUES = {
    "DocumentType": [
        "bank_statement",
        "brokerage_statement",
        "esop_grant",
        "property_appraisal",
    ],
    "DocumentStatus": ["uploaded", "processing", "completed", "failed", "retired"],
    "TransactionDirection": ["IN", "OUT"],
    "RuleType": ["keyword_match", "regex_match", "ml_model"],
    "ClassificationStatus": ["draft", "applied", "superseded"],
    "BankStatementStatus": [
        "uploaded",
        "parsing",
        "parsed",
        "approved",
        "rejected",
        "retired",
    ],
    "Stage1Status": ["pending_review", "approved", "rejected", "edited"],
}


@ac_proof(
    proof_id="extraction_source_vocabulary_values",
    ac_ids=["AC-extraction.source-vocabulary.1"],
    ci_tier="pr_ci",
)
@pytest.mark.parametrize("name,values", VALUES.items())
def test_source_vocabulary_values_are_stable(name: str, values: list[str]) -> None:
    """AC-extraction.source-vocabulary.1: execute the real pure leaf module."""
    spec = importlib.util.spec_from_file_location("source_vocabulary", OWNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    enum = getattr(module, name)
    assert [member.value for member in enum] == values
    assert len(enum.__members__) == len(values)
    for value in values:
        member = enum(value)
        assert member.name == value.upper()
        assert isinstance(member, str)
        assert json.loads(json.dumps(member)) == value
        assert enum(json.loads(json.dumps(member))) is member
    with pytest.raises(ValueError):
        enum("invalid-source-vocabulary-value")
    for node in ast.walk(ast.parse(OWNER.read_text())):
        if isinstance(node, ast.ImportFrom):
            assert node.module in {"enum", "__future__"}
        assert not isinstance(node, ast.Import)


@ac_proof(
    proof_id="extraction_source_vocabulary_single_owner",
    ac_ids=["AC-extraction.source-vocabulary.3"],
    ci_tier="pr_ci",
)
def test_source_vocabulary_has_one_owner() -> None:
    """AC-extraction.source-vocabulary.3: retire the old owner and reverse edges."""
    assert not (PACKAGE / "orm/statement_enums.py").exists()
    owners = {name: [] for name in VALUES}
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef) and node.name in owners:
                owners[node.name].append(path)
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("src.extraction.orm"):
                    assert not (set(VALUES) & {alias.name for alias in node.names}), (
                        path
                    )
                if path.is_relative_to(PACKAGE / "base"):
                    assert not node.module.startswith(
                        ("src.extraction.orm", "sqlalchemy", "src.database")
                    ), path
    assert owners == {name: [OWNER] for name in VALUES}
