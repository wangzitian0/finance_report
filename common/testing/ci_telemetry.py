"""Assemble non-blocking ci.post telemetry artifact payloads (#3215 Slice 2B)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, UTC
from pathlib import Path
from typing import Any


def _read_json_or_none(path: Path | None) -> Any:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(
            f"::warning::ignoring unreadable telemetry JSON {path}: {exc}",
            file=sys.stderr,
        )
        return None


def extract_backend_coverage(payload: Any) -> dict[str, Any] | None:
    """Normalize pytest/coverage.py JSON or summary JSON into compact metrics."""
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get("totals") if isinstance(payload.get("totals"), Mapping) else payload
    if not isinstance(raw, Mapping) or "percent_covered" not in raw:
        return None
    try:
        return {
            "percent_covered": round(float(raw["percent_covered"]), 2),
            "covered_lines": int(raw.get("covered_lines") or 0),
            "num_statements": int(raw.get("num_statements") or 0),
            "missing_lines": int(raw.get("missing_lines") or 0),
        }
    except (TypeError, ValueError):
        return None


def extract_frontend_coverage(payload: Any) -> dict[str, float] | None:
    """Extract Vitest `json-summary` totals (`lines`, `statements`, `functions`, `branches`)."""
    if not isinstance(payload, Mapping):
        return None
    total = payload.get("total")
    if not isinstance(total, Mapping):
        return None
    keys = ("lines", "statements", "functions", "branches")
    extracted: dict[str, float] = {}
    for key in keys:
        entry = total.get(key)
        if not isinstance(entry, Mapping) or "pct" not in entry:
            return None
        try:
            extracted[f"{key}_pct"] = round(float(entry["pct"]), 2)
        except (TypeError, ValueError):
            return None
    return extracted


def extract_job_results(raw_needs: Any) -> dict[str, str]:
    """Normalize GitHub Actions `needs` JSON mapping into `{job_id: result}`."""
    if isinstance(raw_needs, str):
        if not raw_needs.strip():
            return {}
        try:
            raw_needs = json.loads(raw_needs)
        except ValueError as exc:
            print(
                f"::warning::ignoring invalid needs JSON: {exc}",
                file=sys.stderr,
            )
            return {}
    if not isinstance(raw_needs, Mapping):
        return {}
    results: dict[str, str] = {}
    for job_id, info in sorted(raw_needs.items()):
        if isinstance(info, Mapping):
            results[str(job_id)] = str(info.get("result") or "unknown")
        elif info is not None:
            results[str(job_id)] = str(info)
    return results


def build_ci_telemetry_payload(
    *,
    sha: str,
    ref: str,
    event_name: str,
    run_id: str,
    run_url: str,
    timing: Any = None,
    backend_coverage: Any = None,
    frontend_coverage: Any = None,
    needs: Any = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Assemble the non-blocking `ci.post` telemetry document."""
    timestamp = generated_at_utc or datetime.now(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return {
        "schema_version": 1,
        "generated_at_utc": timestamp,
        "sha": sha,
        "ref": ref,
        "event_name": event_name,
        "run_id": run_id,
        "run_url": run_url,
        "timing": timing if isinstance(timing, Mapping) else None,
        "coverage": {
            "backend": extract_backend_coverage(backend_coverage),
            "frontend": extract_frontend_coverage(frontend_coverage),
        },
        "jobs": extract_job_results(needs),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble ci-post-telemetry.json from workflow artifacts"
    )
    parser.add_argument("--timing-json", type=Path, default=None)
    parser.add_argument("--backend-coverage-json", type=Path, default=None)
    parser.add_argument("--frontend-coverage-json", type=Path, default=None)
    parser.add_argument("--needs-json", default="")
    parser.add_argument("--needs-json-env", default="")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    needs_raw = args.needs_json
    if not needs_raw and args.needs_json_env:
        needs_raw = os.environ.get(args.needs_json_env, "")

    payload = build_ci_telemetry_payload(
        sha=args.sha,
        ref=args.ref,
        event_name=args.event_name,
        run_id=args.run_id,
        run_url=args.run_url,
        timing=_read_json_or_none(args.timing_json),
        backend_coverage=_read_json_or_none(args.backend_coverage_json),
        frontend_coverage=_read_json_or_none(args.frontend_coverage_json),
        needs=needs_raw,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote CI telemetry JSON to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
