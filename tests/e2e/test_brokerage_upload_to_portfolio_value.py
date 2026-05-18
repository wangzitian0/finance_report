"""
Tier 3 Browser/API E2E: Multi-brokerage upload to latest portfolio value.

Issue #404 / AC8.13.10:
Upload multiple brokerage PDFs through the configured real OCR path, import
positions from the parsed statements, and verify the latest portfolio value is
visible through product APIs.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from conftest import AuthState, fail_or_skip_ai_ocr_gate

APP_URL: str = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT_MS: int = int(os.getenv("PARSING_TIMEOUT_MS", "480000"))


def _api_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}/api{path}"


def _get_pdf_path(source: str) -> Path:
    from datetime import datetime

    root = Path(__file__).resolve().parents[2]
    source_dir = root / "scripts" / "pdf_fixtures" / "output" / source
    yymm = datetime.now().strftime("%y%m")
    prebuilt = source_dir / f"test_{source}_{yymm}.pdf"
    if prebuilt.exists():
        return prebuilt
    if source_dir.exists():
        pdfs = sorted(source_dir.glob(f"test_{source}_*.pdf"))
        if pdfs:
            return pdfs[-1]

    script = root / "scripts" / "pdf_fixtures" / "generate_pdf_fixtures.py"
    result = subprocess.run(
        [sys.executable, str(script), "--source", source],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(
            f"PDF fixture generation failed for {source}.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    pdfs = sorted(source_dir.glob(f"test_{source}_*.pdf")) if source_dir.exists() else []
    if not pdfs:
        pytest.skip(f"PDF generation for {source} produced no files in {source_dir}")
    return pdfs[-1]


def _unique_pdf_copy(src: Path) -> Path:
    suffix = int(time.time() * 1000) % 1_000_000
    tmp = Path(tempfile.mkdtemp())
    dest = tmp / f"{src.stem}_{suffix}{src.suffix}"
    shutil.copy2(src, dest)
    with open(dest, "ab") as f:
        f.write(f"\n%% E2E test run {uuid.uuid4()}\n".encode())
    return dest


async def _default_image_model(client: httpx.AsyncClient) -> str:
    response = await client.get(_api_url("/ai/models?modality=image"))
    assert response.status_code == 200, (
        f"model catalog request failed: {response.status_code} {response.text}"
    )
    payload = response.json()
    return payload.get("default_model") or payload["models"][0]["id"]


async def _upload_brokerage_pdf(
    client: httpx.AsyncClient,
    *,
    source: str,
    institution: str,
    model: str,
) -> str:
    pdf_path = _unique_pdf_copy(_get_pdf_path(source))
    with pdf_path.open("rb") as fh:
        response = await client.post(
            _api_url("/statements/upload"),
            data={"institution": institution, "model": model},
            files={"file": (pdf_path.name, fh, "application/pdf")},
        )
    assert response.status_code in (200, 201, 202), (
        f"{source} upload failed: {response.status_code} {response.text}"
    )
    statement_id = response.json().get("id")
    assert statement_id, f"{source} upload response missing id: {response.text}"
    return str(statement_id)


async def _wait_for_parsed_statement(client: httpx.AsyncClient, statement_id: str) -> dict:
    deadline = asyncio.get_event_loop().time() + PARSING_TIMEOUT_MS / 1000
    last_payload: dict | None = None
    while asyncio.get_event_loop().time() < deadline:
        response = await client.get(_api_url(f"/statements/{statement_id}"))
        assert response.status_code == 200, (
            f"statement poll failed for {statement_id}: {response.status_code} {response.text}"
        )
        last_payload = response.json()
        status = last_payload.get("status")
        if status == "rejected":
            fail_or_skip_ai_ocr_gate(
                f"brokerage OCR/import gate rejected statement {statement_id}: "
                f"{last_payload.get('validation_error')}"
            )
        if status == "parsed":
            assert last_payload.get("transactions"), (
                f"parsed statement {statement_id} has no transactions: {last_payload}"
            )
            return last_payload
        await asyncio.sleep(5)

    pytest.fail(
        f"statement {statement_id} did not reach parsed within {PARSING_TIMEOUT_MS}ms. "
        f"last payload: {last_payload}"
    )


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_multi_brokerage_pdf_upload_imports_positions_and_updates_latest_portfolio_value(
    shared_auth_state: AuthState,
) -> None:
    """AC8.13.10: two brokerage PDFs → real OCR → positions → balance sheet value."""
    headers = {"Authorization": f"Bearer {shared_auth_state.access_token}"}
    async with httpx.AsyncClient(headers=headers, verify=False, timeout=120.0) as client:
        model = await _default_image_model(client)
        uploads = [
            ("moomoo", "Moomoo E2E Portfolio"),
            ("futu", "Futu E2E Portfolio"),
        ]

        statement_ids = []
        for source, institution in uploads:
            statement_ids.append(
                await _upload_brokerage_pdf(
                    client,
                    source=source,
                    institution=institution,
                    model=model,
                )
            )

        parsed_statements = [
            await _wait_for_parsed_statement(client, statement_id)
            for statement_id in statement_ids
        ]
        assert len(parsed_statements) == 2

        imported_positions = Decimal("0")
        for parsed_statement in parsed_statements:
            response = await client.post(
                _api_url(f"/statements/{parsed_statement['id']}/brokerage/import")
            )
            assert response.status_code == 200, (
                f"brokerage import failed for {parsed_statement['id']}: "
                f"{response.status_code} {response.text}"
            )
            payload = response.json()
            assert payload["parsed_positions"] > 0, (
                f"no positions imported for {parsed_statement['id']}: {payload}"
            )
            imported_positions += Decimal(str(payload["parsed_positions"]))

        holdings_response = await client.get(_api_url("/portfolio/holdings"))
        assert holdings_response.status_code == 200, (
            f"holdings check failed: {holdings_response.status_code} {holdings_response.text}"
        )
        holdings = holdings_response.json()
        assert len(holdings) >= int(imported_positions), f"missing imported holdings: {holdings}"
        total_market_value = sum(Decimal(str(item["market_value"])) for item in holdings)
        assert total_market_value > Decimal("0.00"), f"holdings have no market value: {holdings}"

        balance_response = await client.get(
            _api_url(f"/reports/balance-sheet?as_of_date={date.today().isoformat()}")
        )
        assert balance_response.status_code == 200, (
            f"balance sheet check failed: {balance_response.status_code} {balance_response.text}"
        )
        balance_sheet = balance_response.json()
        assert Decimal(str(balance_sheet["total_assets"])) >= total_market_value, balance_sheet
        assert Decimal(str(balance_sheet["net_worth_adjustment_gain_loss"])) > Decimal("0.00"), (
            balance_sheet
        )
