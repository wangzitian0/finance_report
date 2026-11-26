"""Verify frontend api-types.ts and api-operations.ts match openapi.json without /tmp races."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from common.meta.extension.generate_api_operations import render as render_operations
from common.runtime.dev.compact_api_types import compact_api_types

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "apps" / "frontend"


def _openapi_typescript_cmd(
    frontend_dir: Path, spec_path: Path, out_path: Path
) -> list[str]:
    local_bin = frontend_dir / "node_modules" / ".bin" / "openapi-typescript"
    if local_bin.is_file():
        return [str(local_bin), str(spec_path), "-o", str(out_path)]
    npx = shutil.which("npx") or "npx"
    return [npx, "openapi-typescript", str(spec_path), "-o", str(out_path)]


def main(argv: Sequence[str] | None = None) -> int:
    _ = argv
    spec_path = FRONTEND_DIR / "openapi.json"
    expected_types_path = FRONTEND_DIR / "src" / "lib" / "api-types.ts"
    expected_ops_path = FRONTEND_DIR / "src" / "lib" / "api-operations.ts"
    with tempfile.TemporaryDirectory(prefix="api-types-check-") as tmpdir:
        generated_types = Path(tmpdir) / "api-types.check.ts"
        cmd = _openapi_typescript_cmd(FRONTEND_DIR, spec_path, generated_types)
        proc = subprocess.run(
            cmd, cwd=FRONTEND_DIR, capture_output=True, text=True, check=False
        )
        if proc.returncode != 0:
            if proc.stdout:
                print(proc.stdout, end="")
            if proc.stderr:
                print(proc.stderr, end="")
            return proc.returncode
        raw_types = generated_types.read_text(encoding="utf-8")
    compacted_types = compact_api_types(raw_types)
    if expected_types_path.read_text(encoding="utf-8") != compacted_types:
        print(
            f"ERROR: {expected_types_path.relative_to(REPO_ROOT)} is out of sync with openapi.json. "
            "Run: npm --prefix apps/frontend run gen:api-types"
        )
        return 1
    rendered_ops = render_operations(spec_path)
    if expected_ops_path.read_text(encoding="utf-8") != rendered_ops:
        print(
            f"ERROR: {expected_ops_path.relative_to(REPO_ROOT)} is out of sync with openapi.json. "
            "Run: npm --prefix apps/frontend run gen:api-operations"
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
