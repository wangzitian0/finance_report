from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    target = ROOT / path
    if target.is_dir():
        return "\n".join(
            p.read_text(encoding="utf-8") for p in sorted(target.rglob("*.py"))
        )
    return target.read_text(encoding="utf-8")


def test_finance_report_minio_bucket_is_private_by_default() -> None:
    """AC13.5.1: Finance Report AI URL fallback must not require public buckets."""
    app_deployer = read("repo/finance_report/finance_report/10.app/deploy.py")
    minio_tasks = read("repo/platform/03.minio/shared_tasks.py")

    assert "public_download=False" in app_deployer
    assert "public_download=False" in minio_tasks
    assert "mc anonymous set none local/{bucket_name}" in minio_tasks
    assert "mc anonymous set download local/{bucket_name}" in minio_tasks


def test_zai_pdf_fallback_uses_image_url_and_redacts_presigned_urls() -> None:
    """AC13.5.1: Z.AI PDF fallback uses image_url and treats presigned URLs as secrets."""
    extraction = read("apps/backend/src/services/extraction")
    storage = read("apps/backend/src/services/storage.py")

    assert "def _render_pdf_pages_as_image_payloads" in extraction
    assert "PDF_VISION_MAX_PAGES = 5" in extraction
    assert '"type": "image_url"' in extraction
    assert '"image_url": {"url": data}' in extraction
    assert (
        "Z.AI PDF vision fallback requires file content or an external PDF URL"
        in extraction
    )
    assert "def redact_presigned_url" in storage
    assert "signature=<redacted>" in storage


def test_statement_storage_keys_do_not_include_original_filename_or_user_id() -> None:
    """AC13.5.1: New statement object keys avoid user and filename leakage."""
    statements = read("apps/backend/src/routers/statements.py")

    assert "def build_statement_storage_key" in statements
    assert (
        'f"statements/{statement_id}/{file_hash[:16]}.{safe_extension}"' in statements
    )
    assert 'f"statements/{user_id}/{statement_id}/{filename}"' not in statements
