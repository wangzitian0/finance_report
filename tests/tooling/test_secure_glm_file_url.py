from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    target = ROOT / path
    if target.is_dir():
        # Sentinel separator so substring assertions can't match across a
        # cross-file boundary formed by concatenation.
        return "\n# <<< file-boundary >>>\n".join(
            p.read_text(encoding="utf-8") for p in sorted(target.rglob("*.py"))
        )
    return target.read_text(encoding="utf-8")


def test_zai_pdf_fallback_uses_image_url_and_redacts_presigned_urls() -> None:
    """AC-extraction.105.1: Z.AI PDF fallback uses image_url and treats presigned URLs as secrets."""
    extraction = read("apps/backend/src/extraction/extension")
    storage = read("apps/backend/src/runtime/extension/storage.py")

    assert "def _render_pdf_pages_as_image_payload_batches" in extraction
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
    """AC-extraction.105.1: New statement object keys avoid user and filename leakage."""
    statements = read("apps/backend/src/routers/statements.py")

    assert "def build_statement_storage_key" in statements
    assert (
        'f"statements/{statement_id}/{file_hash[:16]}.{safe_extension}"' in statements
    )
    assert 'f"statements/{user_id}/{statement_id}/{filename}"' not in statements
