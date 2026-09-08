"""Schema/wire compatibility for the extraction vocabulary cutover (#2018)."""

import json

import pytest
from common.testing.ac_proof import ac_proof
from sqlalchemy.dialects.postgresql import dialect

import src.extraction as extraction

pytestmark = pytest.mark.no_db


@ac_proof(
    proof_id="extraction_source_vocabulary_persistence",
    ac_ids=["AC-extraction.source-vocabulary.2"],
    ci_tier="pr_ci",
)
@pytest.mark.parametrize(
    "name,model,column,type_name,values",
    [
        (
            "DocumentType",
            "UploadedDocument",
            "document_type",
            "document_type_enum",
            ["bank_statement", "brokerage_statement", "esop_grant", "property_appraisal"],
        ),
        (
            "DocumentStatus",
            "UploadedDocument",
            "status",
            "document_status_enum",
            ["uploaded", "processing", "completed", "failed", "retired"],
        ),
        ("TransactionDirection", "AtomicTransaction", "direction", "transaction_direction_enum", ["IN", "OUT"]),
        ("RuleType", "ClassificationRule", "rule_type", "rule_type_enum", ["keyword_match", "regex_match", "ml_model"]),
        (
            "ClassificationStatus",
            "TransactionClassification",
            "status",
            "classification_status_enum",
            ["draft", "applied", "superseded"],
        ),
        (
            "BankStatementStatus",
            "StatementSummary",
            "status",
            "statement_summary_status_enum",
            ["uploaded", "parsing", "parsed", "approved", "rejected", "retired"],
        ),
        (
            "Stage1Status",
            "StatementSummary",
            "stage1_status",
            "statement_summary_stage1_status_enum",
            ["pending_review", "approved", "rejected", "edited"],
        ),
    ],
)
def test_source_enum_persistence_compatibility(name, model, column, type_name, values):
    """AC-extraction.source-vocabulary.2: one type preserves SQL and wire values."""
    from src.extraction.base import source_vocabulary

    enum = getattr(source_vocabulary, name)
    assert getattr(extraction, name) is enum
    sql_type = getattr(extraction, model).__table__.c[column].type
    assert sql_type.enum_class is enum
    assert sql_type.name == type_name
    assert sql_type.enums == values
    bind = sql_type.bind_processor(dialect())
    restore = sql_type.result_processor(dialect(), None)
    for value in values:
        member = enum(value)
        assert bind(member) == value
        assert restore(value) is member
        assert json.loads(json.dumps(member)) == value
