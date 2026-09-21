"""TDD Test Suite for Flow 28: Annual Tax & Audit Archive Package Export.

Verifies that personal report package snapshots can be exported as complete,
verifiable ZIP archives containing manifest.json with SHA-256 digests,
individual financial schedule CSVs, and audit trail metadata.
"""

import hashlib
import json
import zipfile
from datetime import date
from io import BytesIO

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import User
from src.routers.reports import (
    PackageSnapshotExportFormat,
    export_personal_report_package_snapshot,
    generate_personal_report_package_snapshot,
)
from src.schemas import (
    PersonalReportingFrameworkId,
    PersonalReportPackageGenerateRequest,
)
from tests.api.test_personal_report_package_contract import _patch_package_snapshot_inputs


async def _read_binary_streaming_body(response) -> bytes:
    """Helper to consume binary bytes from a FastAPI StreamingResponse."""
    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, str):
            chunks.append(chunk.encode("utf-8"))
        else:
            chunks.append(chunk)
    return b"".join(chunks)


@pytest.mark.asyncio
async def test_package_snapshot_export_zip_format_structure_and_checksums(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-reporting.tax-package.1: Snapshot export as ZIP must contain manifest with SHA-256 digests."""
    await _patch_package_snapshot_inputs(
        monkeypatch, readiness_state="ready", blocking_count=0, section_label="Annual Tax Audit 2025"
    )

    snapshot = await generate_personal_report_package_snapshot(
        request=PersonalReportPackageGenerateRequest(
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            as_of_date=date(2025, 12, 31),
            currency="SGD",
        ),
        db=db,
        user_id=test_user.id,
    )

    zip_response = await export_personal_report_package_snapshot(
        snapshot_id=snapshot.id,
        format=PackageSnapshotExportFormat.ZIP,
        db=db,
        user_id=test_user.id,
    )

    # 1. Verify HTTP Response Headers
    assert zip_response.media_type == "application/zip"
    content_disp = zip_response.headers.get("content-disposition", "")
    assert ".zip" in content_disp
    assert f"{snapshot.id}" in content_disp

    # 2. Verify ZIP archive integrity
    body_bytes = await _read_binary_streaming_body(zip_response)
    assert len(body_bytes) > 0

    with zipfile.ZipFile(BytesIO(body_bytes), "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "balance_sheet.csv" in namelist
        assert "income_statement.csv" in namelist
        assert "cash_flow.csv" in namelist

        # 3. Verify manifest structure and SHA-256 digests
        manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest_data["package_id"] == str(snapshot.id)
        assert manifest_data["reporting_currency"] == "SGD"
        assert manifest_data["as_of_date"] == "2025-12-31"
        assert "files" in manifest_data
        assert isinstance(manifest_data["files"], list)

        for entry in manifest_data["files"]:
            filename = entry["filename"]
            expected_sha256 = entry["sha256"]
            assert filename in namelist

            actual_content = zf.read(filename)
            actual_sha256 = hashlib.sha256(actual_content).hexdigest()
            assert actual_sha256 == expected_sha256, f"Checksum mismatch for {filename}"

        # 4. Verify schedule contents
        bs_csv = zf.read("balance_sheet.csv").decode("utf-8")
        assert "Annual Tax Audit 2025" in bs_csv or "balance" in bs_csv.lower()


@pytest.mark.asyncio
async def test_annual_tax_archive_direct_endpoint(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
):
    """AC-reporting.tax-package.2: POST /api/reports/package/annual-archive produces downloadable ZIP."""
    await _patch_package_snapshot_inputs(
        monkeypatch, readiness_state="ready", blocking_count=0, section_label="Tax Year 2025"
    )

    response = await client.post(
        "/reports/package/annual-archive",
        json={
            "year": 2025,
            "currency": "SGD",
            "framework_id": "personal_us_gaap_like",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/zip"
    assert 'filename="annual-tax-archive-2025.zip"' in response.headers.get("content-disposition", "")

    # Check zip contents
    with zipfile.ZipFile(BytesIO(response.content), "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["tax_year"] == 2025
