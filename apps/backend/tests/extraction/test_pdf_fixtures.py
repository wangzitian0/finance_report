from __future__ import annotations

import fcntl
import hashlib
import importlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import AsyncGenerator
from datetime import date
from pathlib import Path
from typing import Literal

import pytest_asyncio
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = REPO_ROOT / "tests/fixtures/pdf/generated"
EXPECTED = {
    "DBS": (OUTPUT_DIR / "dbs_statement_fixture.pdf", OUTPUT_DIR / "dbs_statement_fixture_expected.json"),
    "CMB": (OUTPUT_DIR / "cmb_statement_fixture.pdf", OUTPUT_DIR / "cmb_statement_fixture_expected.json"),
    "GXS": (OUTPUT_DIR / "gxs_statement_fixture.pdf", OUTPUT_DIR / "gxs_statement_fixture_expected.json"),
    "MariBank": (
        OUTPUT_DIR / "maribank_statement_fixture.pdf",
        OUTPUT_DIR / "maribank_statement_fixture_expected.json",
    ),
}


@pytest_asyncio.fixture
async def db_engine() -> AsyncGenerator[None, None]:
    yield


@pytest_asyncio.fixture(autouse=True)
async def patch_database_connection() -> AsyncGenerator[None, None]:
    yield


class StatementSchema(BaseModel):
    period_start: date
    period_end: date
    opening_balance: str = Field(pattern=r"^-?\d+\.\d{2}$")
    closing_balance: str = Field(pattern=r"^-?\d+\.\d{2}$")
    currency: str = Field(min_length=3, max_length=3)
    confidence_score: int = Field(ge=0, le=100)
    balance_validated: bool
    account_last4: str = Field(pattern=r"^[A-Za-z0-9]{4}$")


class EventSchema(BaseModel):
    date: date
    description: str = Field(min_length=1)
    amount: str = Field(pattern=r"^\d+\.\d{2}$")
    direction: Literal["IN", "OUT"]
    reference: str | None
    currency: str = Field(min_length=3, max_length=3)
    balance_after: str = Field(pattern=r"^-?\d+\.\d{2}$")
    confidence: float = Field(ge=0.0, le=1.0)
    raw_text: str = Field(min_length=1)
    suggested_category: str = Field(min_length=1)
    category_confidence: float = Field(ge=0.0, le=1.0)


class FixtureSchema(BaseModel):
    file: str = Field(pattern=r".+\.pdf$")
    institution: str
    success: bool
    statement: StatementSchema
    events: list[EventSchema] = Field(min_length=5, max_length=150)


def _run_generator() -> None:
    OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True)
    with (OUTPUT_DIR.parent / ".generate_test_pdfs.lock").open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        subprocess.run(
            [sys.executable, "-m", "tests.fixtures.generate_test_pdfs"],
            cwd=REPO_ROOT,
            check=True,
        )


def _hashes() -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for paths in EXPECTED.values() for p in paths}


def test_generated_pdfs_exist_valid_and_deterministic() -> None:
    _run_generator()
    assert OUTPUT_DIR.exists()
    pypdf_reader = importlib.import_module("pypdf").PdfReader if importlib.util.find_spec("pypdf") is not None else None
    for institution, (pdf_path, json_path) in EXPECTED.items():
        assert pdf_path.exists() and json_path.exists()
        payload = pdf_path.read_bytes()
        assert payload.startswith(b"%PDF-") and b"%%EOF" in payload[-2048:]
        if pypdf_reader is not None:
            reader = pypdf_reader(str(pdf_path))
            assert len(reader.pages) >= (6 if institution == "CMB" else 1)
            if institution == "CMB":
                first_text = reader.pages[0].extract_text() or ""
                assert "Opening Balance:" not in first_text and "Closing Balance:" not in first_text
        fixture = FixtureSchema.model_validate(json.loads(json_path.read_text(encoding="utf-8")))
        assert (fixture.institution, fixture.file, fixture.success) == (institution, pdf_path.name, True)

    first_hashes = _hashes()
    _run_generator()
    assert _hashes() == first_hashes
