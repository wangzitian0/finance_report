'AC18.1.1'; from __future__ import annotations; import fcntl; import hashlib; import importlib; import importlib.util; import json; import subprocess; import sys; from collections.abc import AsyncGenerator; from datetime import date; from pathlib import Path; from typing import Any, Literal; import pytest_asyncio; from pydantic import BaseModel, Field; REPO_ROOT = Path(__file__).resolve().parents[4]; BACKEND_DIR = REPO_ROOT / 'apps/backend'; SCRIPT_PATH = REPO_ROOT / 'tools/generate_test_pdfs.py'; OUTPUT_DIR = REPO_ROOT / 'common/testing/fixtures/pdf/generated'; EXPECTED = {'DBS': (OUTPUT_DIR / 'dbs_statement_fixture.pdf', OUTPUT_DIR / 'dbs_statement_fixture_expected.json'), 'CMB': (OUTPUT_DIR / 'cmb_statement_fixture.pdf', OUTPUT_DIR / 'cmb_statement_fixture_expected.json'), 'GXS': (OUTPUT_DIR / 'gxs_statement_fixture.pdf', OUTPUT_DIR / 'gxs_statement_fixture_expected.json'), 'MariBank': (OUTPUT_DIR / 'maribank_statement_fixture.pdf', OUTPUT_DIR / 'maribank_statement_fixture_expected.json')}
@pytest_asyncio.fixture
async def db_engine() -> AsyncGenerator[None, None]: yield
@pytest_asyncio.fixture(autouse=True)
async def patch_database_connection() -> AsyncGenerator[None, None]: yield
class StatementSchema(BaseModel): period_start: date; period_end: date; opening_balance: str = Field(pattern='^-?\\d+\\.\\d{2}$'); closing_balance: str = Field(pattern='^-?\\d+\\.\\d{2}$'); currency: str = Field(min_length=3, max_length=3); confidence_score: int = Field(ge=0, le=100); balance_validated: bool; account_last4: str = Field(pattern='^[A-Za-z0-9]{4}$')
class EventSchema(BaseModel): date: date; description: str = Field(min_length=1); amount: str = Field(pattern='^\\d+\\.\\d{2}$'); direction: Literal['IN', 'OUT']; reference: str | None; currency: str = Field(min_length=3, max_length=3); balance_after: str = Field(pattern='^-?\\d+\\.\\d{2}$'); confidence: float = Field(ge=0.0, le=1.0); raw_text: str = Field(min_length=1); suggested_category: str = Field(min_length=1); category_confidence: float = Field(ge=0.0, le=1.0)
class FixtureSchema(BaseModel): file: str = Field(pattern='.+\\.pdf$'); institution: str; success: bool; statement: StatementSchema; events: list[EventSchema] = Field(min_length=5, max_length=150)
def _run_generator() -> None:
    OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True); lock_path = OUTPUT_DIR.parent / '.generate_test_pdfs.lock'
    with lock_path.open('w', encoding='utf-8') as lock_file: fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX); subprocess.run([sys.executable, str(SCRIPT_PATH)], cwd=BACKEND_DIR, check=True)
_sha256 = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
def test_generated_pdfs_exist() -> None:
    _run_generator(); assert OUTPUT_DIR.exists()
    for (pdf_path, json_path) in EXPECTED.values(): assert pdf_path.exists(), f'Missing PDF fixture: {pdf_path.name}'; assert json_path.exists(), f'Missing JSON fixture: {json_path.name}'
    _run_generator(); _m1_pypdf_reader: Any | None = None
    if importlib.util.find_spec('pypdf') is not None: _m1_pypdf_module = importlib.import_module('pypdf'); _m1_pypdf_reader = _m1_pypdf_module.PdfReader
    for (_m1_institution, (_m1_pdf_path, _m1__)) in EXPECTED.items():
        _m1_payload = _m1_pdf_path.read_bytes(); assert _m1_payload.startswith(b'%PDF-'), f'Invalid PDF header: {_m1_pdf_path.name}'; assert b'%%EOF' in _m1_payload[-2048:], f'Missing EOF marker: {_m1_pdf_path.name}'
        if _m1_pypdf_reader is not None:
            _m1_reader = _m1_pypdf_reader(str(_m1_pdf_path)); assert len(_m1_reader.pages) >= 1, f'Expected at least one page: {_m1_pdf_path.name}'
            if _m1_institution == 'CMB': assert len(_m1_reader.pages) >= 6, f'CMB fixture must have >= 6 pages to exercise multi-page chunking: got {len(_m1_reader.pages)}'; _m1_first_page_text = _m1_reader.pages[0].extract_text() or ''; assert 'Opening Balance:' not in _m1_first_page_text; assert 'Closing Balance:' not in _m1_first_page_text
    _run_generator()
    for (_m2_institution, (_m2_pdf_path, _m2_json_path)) in EXPECTED.items(): _m2_data = json.loads(_m2_json_path.read_text(encoding='utf-8')); _m2_fixture = FixtureSchema.model_validate(_m2_data); assert _m2_fixture.institution == _m2_institution; assert _m2_fixture.file == _m2_pdf_path.name; assert _m2_fixture.success is True
    _run_generator(); _m3_first_hashes = {_m3_path.name: _sha256(_m3_path) for _m3_paths in EXPECTED.values() for _m3_path in _m3_paths}; _run_generator(); _m3_second_hashes = {_m3_path.name: _sha256(_m3_path) for _m3_paths in EXPECTED.values() for _m3_path in _m3_paths}; assert _m3_first_hashes == _m3_second_hashes
