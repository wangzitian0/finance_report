"""Generate the checked-in OpenAPI spec that drives the typed frontend client (#1004).

The runtime OpenAPI document is the API contract. This module serializes it to a
deterministic ``openapi.json`` under ``apps/frontend`` so the frontend can generate
TypeScript types from it (``openapi-typescript``) and a CI ``--check`` gate fails
when the committed spec drifts from the live FastAPI app — enforcing the FE↔BE
contract at the boundary.

The TS types are a pure function of this JSON: backend changes regenerate the JSON
(this gate), and ``npm run gen:api-types`` turns the JSON into ``src/lib/api-types.ts``.
Splitting it this way keeps each step in its own toolchain (Python here, Node there).
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "apps" / "backend"
OUTPUT_PATH = REPO_ROOT / "apps" / "frontend" / "openapi.json"


def _load_openapi() -> dict[str, Any]:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from src.main import app  # noqa: PLC0415

    return app.openapi()


def render(openapi: dict[str, Any]) -> str:
    """Serialize the OpenAPI document deterministically (sorted keys + trailing NL)."""
    return json.dumps(openapi, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generate() -> str:
    return render(_load_openapi())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="OpenAPI JSON output path.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the generated spec differs from the checked-in file.",
    )
    args = parser.parse_args(argv)

    rendered = generate()
    output = args.output
    if args.check:
        try:
            current = output.read_text(encoding="utf-8")
        except OSError:
            print(
                f"ERROR: generated OpenAPI spec is missing: {output}", file=sys.stderr
            )
            return 1
        if current != rendered:
            diff = list(
                difflib.unified_diff(
                    current.splitlines(),
                    rendered.splitlines(),
                    fromfile=str(output),
                    tofile="generated",
                    lineterm="",
                )
            )
            print(
                "ERROR: committed openapi.json is stale — run tools/generate_openapi_spec.py",
                file=sys.stderr,
            )
            print("\n".join(diff[:60]), file=sys.stderr)
            return 1
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
