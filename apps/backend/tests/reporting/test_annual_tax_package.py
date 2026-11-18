import hashlib
import json
import zipfile
from datetime import date
from io import BytesIO

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import User
from src.request_context import RequestContext
from src.routers.reports import (
    PackageSnapshotExportFormat,
    export_personal_report_package_snapshot,
    generate_personal_report_package_snapshot,
)
from src.schemas import PersonalReportingFrameworkId, PersonalReportPackageGenerateRequest
from tests.reporting.test_personal_report_package_contract import _patch_package_snapshot_inputs


def _assert_zip_manifest(body: bytes, *, snapshot_id: str, label: str) -> None:
    with zipfile.ZipFile(BytesIO(body), "r") as zf:
        names = zf.namelist()
        assert {"manifest.json", "balance_sheet.csv", "income_statement.csv", "cash_flow.csv"} <= set(names)
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert (
            manifest["package_id"],
            manifest["reporting_currency"],
            manifest["as_of_date"],
            manifest["tax_year"],
        ) == (snapshot_id, "SGD", "2025-12-31", 2025)
        for entry in manifest["files"]:
            assert hashlib.sha256(zf.read(entry["filename"])).hexdigest() == entry["sha256"]
        bs_csv = zf.read("balance_sheet.csv").decode("utf-8")
        assert label in bs_csv or "balance" in bs_csv.lower()


async def test_package_snapshot_export_zip_format_structure_and_checksums(
    db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _patch_package_snapshot_inputs(
        monkeypatch, readiness_state="ready", blocking_count=0, section_label="Annual Tax Audit 2025"
    )
    snap = await generate_personal_report_package_snapshot(
        RequestContext(db, test_user.id),
        request=PersonalReportPackageGenerateRequest(
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            as_of_date=date(2025, 12, 31),
            currency="SGD",
        ),
    )
    zip_resp = await export_personal_report_package_snapshot(
        snapshot_id=snap.id, format=PackageSnapshotExportFormat.ZIP, ctx=RequestContext(db, test_user.id)
    )
    assert zip_resp.media_type == "application/zip" and f"{snap.id}" in zip_resp.headers.get("content-disposition", "")
    chunks = [c.encode("utf-8") if isinstance(c, str) else c async for c in zip_resp.body_iterator]
    _assert_zip_manifest(b"".join(chunks), snapshot_id=str(snap.id), label="Annual Tax Audit 2025")


async def test_annual_tax_archive_via_snapshot_zip_export(monkeypatch: pytest.MonkeyPatch, client: AsyncClient) -> None:
    await _patch_package_snapshot_inputs(
        monkeypatch, readiness_state="ready", blocking_count=0, section_label="Tax Year 2025"
    )
    created = await client.post(
        "/reports/package/snapshots",
        json={
            "framework_id": "personal_us_gaap_like",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "as_of_date": "2025-12-31",
            "currency": "SGD",
        },
    )
    assert created.status_code == 200
    snap_id = created.json()["id"]
    http_zip = await client.get(f"/reports/package/snapshots/{snap_id}/exports", params={"format": "zip"})
    assert http_zip.status_code == 200 and http_zip.headers.get("content-type") == "application/zip"
    _assert_zip_manifest(http_zip.content, snapshot_id=snap_id, label="Tax Year 2025")
    assert (
        await client.post(
            "/reports/package/annual-archive",
            json={"year": 2025, "currency": "SGD", "framework_id": "personal_us_gaap_like"},
        )
    ).status_code == 404
