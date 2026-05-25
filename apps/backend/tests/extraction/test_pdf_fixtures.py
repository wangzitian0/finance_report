"""AC18.1.1: Generated extraction fixtures include AI category suggestions."""

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
from typing import Any, Literal

import pytest_asyncio
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_DIR = REPO_ROOT / "apps/backend"
SCRIPT_PATH = REPO_ROOT / "scripts/generate_test_pdfs.py"
OUTPUT_DIR = BACKEND_DIR / "tests/fixtures/generated"

EXPECTED = {
    "DBS": (
        OUTPUT_DIR / "dbs_statement_fixture.pdf",
        OUTPUT_DIR / "dbs_statement_fixture_expected.json",
    ),
    "CMB": (
        OUTPUT_DIR / "cmb_statement_fixture.pdf",
        OUTPUT_DIR / "cmb_statement_fixture_expected.json",
    ),
    "GXS": (
        OUTPUT_DIR / "gxs_statement_fixture.pdf",
        OUTPUT_DIR / "gxs_statement_fixture_expected.json",
    ),
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
    events: list[EventSchema] = Field(min_length=5, max_length=10)


def _run_generator() -> None:
    OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True)
    lock_path = OUTPUT_DIR.parent / ".generate_test_pdfs.lock"
    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        subprocess.run([sys.executable, str(SCRIPT_PATH)], cwd=BACKEND_DIR, check=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generated_pdfs_exist() -> None:
    _run_generator()
    assert OUTPUT_DIR.exists()
    for pdf_path, json_path in EXPECTED.values():
        assert pdf_path.exists(), f"Missing PDF fixture: {pdf_path.name}"
        assert json_path.exists(), f"Missing JSON fixture: {json_path.name}"


def test_generated_pdfs_are_valid() -> None:
    _run_generator()

    pypdf_reader: Any | None = None
    if importlib.util.find_spec("pypdf") is not None:
        pypdf_module = importlib.import_module("pypdf")
        pypdf_reader = pypdf_module.PdfReader

    for pdf_path, _ in EXPECTED.values():
        payload = pdf_path.read_bytes()
        assert payload.startswith(b"%PDF-"), f"Invalid PDF header: {pdf_path.name}"
        assert b"%%EOF" in payload[-2048:], f"Missing EOF marker: {pdf_path.name}"

        if pypdf_reader is not None:
            reader = pypdf_reader(str(pdf_path))
            assert len(reader.pages) >= 1, f"Expected at least one page: {pdf_path.name}"


def test_expected_json_matches_schema() -> None:
    _run_generator()
    for institution, (pdf_path, json_path) in EXPECTED.items():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        fixture = FixtureSchema.model_validate(data)

        assert fixture.institution == institution
        assert fixture.file == pdf_path.name
        assert fixture.success is True


def test_generator_is_deterministic() -> None:
    _run_generator()
    first_hashes = {path.name: _sha256(path) for paths in EXPECTED.values() for path in paths}

    _run_generator()
    second_hashes = {path.name: _sha256(path) for paths in EXPECTED.values() for path in paths}

    assert first_hashes == second_hashes
