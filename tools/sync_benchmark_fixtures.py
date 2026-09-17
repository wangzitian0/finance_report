#!/usr/bin/env python3
"""
Sync Benchmark Statement Fixtures.

Downloads and validates external benchmark fixtures defined in
`common/testing/fixtures/benchmarks/manifest.yaml`.
Enforces exact SHA-256 verification and performs on-the-fly page slicing
where necessary to satisfy upload size limits.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    REPO_ROOT / "common" / "testing" / "fixtures" / "benchmarks" / "manifest.yaml"
)


def compute_sha256(data: bytes) -> str:
    """Compute SHA-256 hex digest of bytes."""
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load and parse the benchmark manifest."""
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    with open(manifest_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def verify_fixture(fixture: dict[str, Any], root_dir: Path) -> tuple[bool, str]:
    """Verify an individual fixture against manifest declarations."""
    local_path = root_dir / fixture["local_path"]
    if not local_path.exists():
        return False, f"Missing file: {fixture['local_path']}"

    content = local_path.read_bytes()

    if "slice_pages" in fixture:
        try:
            doc = fitz.open(stream=content, filetype="pdf")
            page_count = doc.page_count
            doc.close()
            expected_pages = fixture["slice_pages"]
            if page_count != expected_pages:
                return (
                    False,
                    f"Page count mismatch for sliced PDF: expected {expected_pages}, got {page_count}",
                )
            if len(content) > 10 * 1024 * 1024:
                return False, f"Sliced file exceeds 10MB limit: {len(content)} bytes"
            return True, f"OK (Sliced {page_count} pages, {len(content):,} bytes)"
        except Exception as exc:
            return False, f"Invalid PDF format: {exc}"

    expected_sha = fixture.get("sha256")
    if expected_sha:
        actual_sha = compute_sha256(content)
        if actual_sha != expected_sha:
            return False, f"SHA-256 mismatch: expected {expected_sha}, got {actual_sha}"

    return True, f"OK ({len(content):,} bytes, SHA-256 verified)"


def download_fixture(
    client: httpx.Client,
    fixture: dict[str, Any],
    root_dir: Path,
    force: bool = False,
) -> bool:
    """Download and process a single fixture."""
    local_path = root_dir / fixture["local_path"]
    if local_path.exists() and not force:
        is_ok, msg = verify_fixture(fixture, root_dir)
        if is_ok:
            print(f"  [EXISTS] {fixture['id']}: {msg}")
            return True

    local_path.parent.mkdir(parents=True, exist_ok=True)
    url = fixture["download_url"]
    print(f"  [DOWNLOADING] {fixture['id']} from {url} ...")

    response = client.get(url)
    if response.status_code != 200:
        print(f"  [ERROR] HTTP {response.status_code} fetching {url}")
        return False

    raw_bytes = response.content

    # Handle page slicing if required (e.g. Fidelity Brokerage)
    if "slice_pages" in fixture:
        expected_raw_sha = fixture.get("raw_sha256")
        if expected_raw_sha:
            actual_raw_sha = compute_sha256(raw_bytes)
            if actual_raw_sha != expected_raw_sha:
                print(
                    f"  [ERROR] Raw SHA-256 mismatch: expected {expected_raw_sha}, got {actual_raw_sha}"
                )
                return False
            print(
                f"  [VERIFIED] Raw payload SHA-256 matched ({len(raw_bytes):,} bytes)"
            )

        slice_pages = fixture["slice_pages"]
        print(f"  [SLICING] Extracting pages 1-{slice_pages} with PyMuPDF...")
        src_doc = fitz.open(stream=raw_bytes, filetype="pdf")
        sliced_doc = fitz.open()
        sliced_doc.insert_pdf(src_doc, from_page=0, to_page=slice_pages - 1)
        sliced_bytes = sliced_doc.tobytes(deflate=True, clean=True)
        src_doc.close()
        sliced_doc.close()

        local_path.write_bytes(sliced_bytes)
        print(
            f"  [SAVED] Sliced {slice_pages} pages -> {local_path} ({len(sliced_bytes):,} bytes)"
        )
        return True

    # Standard fixture verification and write
    expected_sha = fixture.get("sha256")
    if expected_sha:
        actual_sha = compute_sha256(raw_bytes)
        if actual_sha != expected_sha:
            print(
                f"  [ERROR] SHA-256 mismatch: expected {expected_sha}, got {actual_sha}"
            )
            return False

    local_path.write_bytes(raw_bytes)
    print(f"  [SAVED] Verified & written -> {local_path} ({len(raw_bytes):,} bytes)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync and verify external benchmark fixtures."
    )
    parser.add_argument(
        "--manifest", type=Path, default=DEFAULT_MANIFEST, help="Path to manifest.yaml"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Only verify existing fixtures without downloading",
    )
    parser.add_argument(
        "--force", action="store_true", help="Force re-download all fixtures"
    )
    parser.add_argument(
        "--clean", action="store_true", help="Remove all downloaded fixture files"
    )
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    fixtures = manifest.get("fixtures", [])
    print(
        f"Benchmark Manifest: {manifest.get('benchmark_suite')} (v{manifest.get('version')})"
    )
    print(f"Total fixtures declared: {len(fixtures)}")

    if args.clean:
        print("Cleaning downloaded fixture files...")
        for f in fixtures:
            p = REPO_ROOT / f["local_path"]
            if p.exists():
                p.unlink()
                print(f"  Deleted: {p}")
        return 0

    if args.verify:
        print("\nVerifying fixtures...")
        all_ok = True
        for f in fixtures:
            is_ok, msg = verify_fixture(f, REPO_ROOT)
            status = "PASS" if is_ok else "FAIL"
            print(f"  [{status}] {f['id']}: {msg}")
            if not is_ok:
                all_ok = False
        return 0 if all_ok else 1

    print("\nSyncing fixtures...")
    headers = {
        "User-Agent": "Mozilla/5.0 (finance-report-benchmark-sync/1.0)",
    }
    with httpx.Client(follow_redirects=True, timeout=180.0, headers=headers) as client:
        success = True
        for f in fixtures:
            ok = download_fixture(client, f, REPO_ROOT, force=args.force)
            if not ok:
                success = False

    print("\nPost-sync verification...")
    all_ok = True
    for f in fixtures:
        is_ok, msg = verify_fixture(f, REPO_ROOT)
        status = "PASS" if is_ok else "FAIL"
        print(f"  [{status}] {f['id']}: {msg}")
        if not is_ok:
            all_ok = False

    return 0 if (success and all_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
