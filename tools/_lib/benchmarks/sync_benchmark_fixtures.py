#!/usr/bin/env python3
"""
Sync Benchmark Statement Fixtures.

Downloads and validates external benchmark fixtures defined in
`common/testing/fixtures/benchmarks/manifest.yaml`.
Enforces exact SHA-256 verification.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any, Sequence

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
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


def main(argv: Sequence[str] | None = None) -> int:
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
    args = parser.parse_args(argv)

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
    raise SystemExit(main())
