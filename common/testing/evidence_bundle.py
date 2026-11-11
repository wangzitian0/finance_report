"""Shared CI and nightly evidence bundle aggregator (#1690)."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_VERSION = 1

_CI_LANE_BY_JOB: dict[str, str] = {
    "changes": "classification",
    "lint": "static",
    "schema-migrations": "schema",
    "backend": "backend",
    "backend-integration": "backend",
    "frontend-build": "frontend",
    "frontend-vitest": "frontend",
    "frontend-playwright": "frontend",
    "frontend-telemetry-e2e": "frontend",
    "container-images": "images",
    "verify-sha-image-published": "images",
    "tooling-coverage": "tooling",
    "unified-coverage": "coverage",
    "ac-traceability": "static",
    "ac-behavioral-ratchet": "ac-ratchet",
}

_BASELINE_GLOBS: tuple[str, ...] = (
    "common/**/*baseline*.json",
    "common/**/*baseline*.jsonl",
    "common/**/*floor*.json",
    "common/**/*exceptions*.md",
    "docs/**/*baseline*.json",
    "docs/**/*baseline*.jsonl",
    "docs/**/*floor*.json",
    "docs/**/*exceptions*.md",
)


def load_gate_map(repo_root: Path = REPO_ROOT) -> tuple[dict[str, Any], ...]:
    """Load the gate map directly from the .github/workflows/ci.yml SSOT."""
    workflow_path = repo_root / ".github" / "workflows" / "ci.yml"
    if not workflow_path.exists():
        return ()
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return ()

    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(workflow, dict):
        return ()
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return ()
    finish = jobs.get("finish", {})
    if not isinstance(finish, dict) or not isinstance(finish.get("needs", []), list):
        return ()

    required_jobs = {str(job_id) for job_id in finish.get("needs", [])}
    check_script = "\n".join(
        str(step.get("run", ""))
        for step in finish.get("steps", [])
        if isinstance(step, dict)
    )
    return tuple(
        {
            "lane": _CI_LANE_BY_JOB.get(str(job_id), str(job_id).split("-", 1)[0]),
            "job": str(job_id),
            "blocking": (
                "conditional"
                if f'needs.{job_id}.result }}}}" != "skipped"' in check_script
                else True
            ),
        }
        for job_id in jobs
        if str(job_id) in required_jobs
    )


GATE_MAP: tuple[dict[str, Any], ...] = load_gate_map(REPO_ROOT)


def _read_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def coverage_water_line(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    payload = _read_json(repo_root / "unified-coverage.json")
    if payload is None:
        return {"available": False}
    return {
        "available": True,
        "coverage_percent": payload.get("coverage_percent"),
        "breakdown": payload.get("breakdown", {}),
    }


def ac_score_water_line(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    from common.testing.jsonl_baseline import load_jsonl

    path = repo_root / "common" / "testing" / "data" / "ac-score-baseline.jsonl"
    acs = (
        load_jsonl(path, identifier_key="ac_id", collection_key="acs").get("acs", {})
        if path.exists()
        else {}
    )
    scores = [float(r.get("score", 0.0)) for r in acs.values()]
    return {
        "baselined_ac_count": len(acs),
        "mean_floor_score": round(statistics.fmean(scores), 4) if scores else None,
    }


def ac_tier_water_line(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    from common.meta.extension.check_ac_tier_baseline import load_baseline

    untagged = load_baseline(
        repo_root / "common" / "meta" / "data" / "ac-tier-baseline.json"
    )
    return {"untagged_debt_count": len(untagged)}


def protection_water_line(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    from common.testing.protection import PROTECTION_TYPES, load_floor

    path = repo_root / "common" / "testing" / "data" / "protection-floor.json"
    return {
        "floor": load_floor(path)
        if path.exists()
        else dict.fromkeys(PROTECTION_TYPES, 0)
    }


def cassette_eval_water_line() -> dict[str, Any]:
    from common.testing.cassette_eval_baseline import load_corpus_count_floor
    from common.testing.cassette_graded_eval import evaluate

    findings = evaluate()
    current = findings.get("_current", {})
    scores = [float(r.get("score", 0.0)) for r in current.values()]
    return {
        "case_count": len(current),
        "corpus_count_floor": load_corpus_count_floor(),
        "mean_field_accuracy": round(statistics.fmean(scores), 4) if scores else None,
        "regressions": len(findings.get("regressions", [])),
        "missing": len(findings.get("missing", [])),
    }


def _baseline_entry_count(path: Path) -> int | None:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return sum(1 for line in text.splitlines() if line.strip())
    if path.suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            body = {
                k: v
                for k, v in data.items()
                if not k.startswith("_") and k != "version"
            }
            sized = [len(v) for v in body.values() if isinstance(v, (list, dict))]
            if sized:
                return sum(sized)
            if body and all(isinstance(v, int) for v in body.values()):
                return sum(body.values())
            return len(body)
        return None
    if path.suffix == ".md":
        pipe_rows = [
            line
            for line in text.splitlines()
            if line.lstrip().startswith("|") and line.rstrip().endswith("|")
        ]
        separators = [row for row in pipe_rows if set(row.strip()) <= set("|-: ")]
        return max(0, len(pipe_rows) - 2 * len(separators))
    return None


def _last_shrink_date(repo_root: Path, rel_path: str) -> str | None:
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", "log", "-1", "--format=%cI", "--", rel_path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def ratchet_baseline_inventory(repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    found = {
        path
        for pattern in _BASELINE_GLOBS
        for path in repo_root.glob(pattern)
        if path.is_file()
    }
    is_git_repo = (repo_root / ".git").exists()
    return [
        {
            "file": (rel := path.relative_to(repo_root).as_posix()),
            "entry_count": _baseline_entry_count(path),
            "last_shrink": _last_shrink_date(repo_root, rel) if is_git_repo else None,
        }
        for path in sorted(found)
    ]


def build_evidence_bundle(
    repo_root: Path = REPO_ROOT,
    *,
    gate_results: dict[str, str] | None = None,
    provider_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": BUNDLE_VERSION,
        "gate_map": [dict(entry) for entry in load_gate_map(repo_root)],
        "gate_results": dict(gate_results) if gate_results else {},
        "ratchets": {
            "coverage": coverage_water_line(repo_root),
            "ac_score": ac_score_water_line(repo_root),
            "ac_tier": ac_tier_water_line(repo_root),
            "protection": protection_water_line(repo_root),
        },
        "cassette_eval": cassette_eval_water_line(),
        "baseline_inventory": ratchet_baseline_inventory(repo_root),
        "provider_health": dict(provider_health) if provider_health else None,
    }


def render_markdown(bundle: dict[str, Any]) -> str:
    lines = [
        "## Evidence Bundle",
        "",
        "### Gate Map",
        "",
        "| Lane | Job | Blocking | Result |",
        "|---|---|---|---|",
    ]
    gate_results = bundle.get("gate_results", {})
    for entry in bundle.get("gate_map", []):
        job = entry["job"]
        blocking = entry["blocking"]
        blocking_label = (
            str(blocking).lower() if isinstance(blocking, bool) else blocking
        )
        lines.append(
            f"| `{entry['lane']}` | `{job}` | `{blocking_label}` | `{gate_results.get(job, 'n/a')}` |"
        )

    lines.extend(["", "### Ratchet Water Lines", ""])
    ratchets = bundle.get("ratchets", {})
    coverage = ratchets.get("coverage", {})
    if coverage.get("available"):
        lines.append(f"- Coverage: `{coverage.get('coverage_percent')}%` unified")
        for name, data in coverage.get("breakdown", {}).items():
            lines.append(f"  - `{name}`: `{data.get('coverage_percent')}%`")
    else:
        lines.append("- Coverage: not available in this run")

    ac_score = ratchets.get("ac_score", {})
    lines.append(
        f"- AC behavioural score: `{ac_score.get('baselined_ac_count')}` baselined "
        f"AC(s), mean floor `{ac_score.get('mean_floor_score')}`"
    )
    ac_tier = ratchets.get("ac_tier", {})
    lines.append(
        f"- AC authority-tier untagged debt: `{ac_tier.get('untagged_debt_count')}`"
    )
    for ptype, floor in ratchets.get("protection", {}).get("floor", {}).items():
        lines.append(f"  - protection `{ptype}` floor: `{floor}`")

    cassette_eval = bundle.get("cassette_eval", {})
    lines.extend(
        [
            "",
            "### Corpus Per-Field Accuracy",
            "",
            f"- `{cassette_eval.get('case_count')}` case(s) "
            f"(floor `{cassette_eval.get('corpus_count_floor')}`), "
            f"mean field-accuracy `{cassette_eval.get('mean_field_accuracy')}`",
            f"- Regressions: `{cassette_eval.get('regressions')}`, "
            f"Missing: `{cassette_eval.get('missing')}`",
            "",
            "### Ratchet Baseline Inventory",
            "",
        ]
    )
    inventory = bundle.get("baseline_inventory", [])
    if inventory:
        lines.extend(["| Baseline | Entries | Last shrink |", "|---|---|---|"])
        for entry in inventory:
            lines.append(
                f"| `{entry['file']}` | `{entry['entry_count']}` | `{entry['last_shrink']}` |"
            )
    else:
        lines.append("- No ratchet baseline files discovered")

    provider_health = bundle.get("provider_health")
    lines.extend(["", "### Provider / Canary Health", ""])
    if provider_health:
        lines.extend(f"- `{k}`: `{v}`" for k, v in provider_health.items())
    else:
        lines.append("- Not available in this run (no provider-backed gate ran)")

    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the shared CI/nightly evidence bundle (#1690)."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--github-summary", type=Path, default=None)
    parser.add_argument("--gate-results", type=str, default=None)
    parser.add_argument("--provider-status", type=str, default=None)
    parser.add_argument("--provider-exit-code", type=str, default=None)
    args = parser.parse_args(argv)

    if not args.dry_run and args.output is None:
        parser.error("--output is required when --dry-run is not specified")

    gate_results = json.loads(args.gate_results) if args.gate_results else None
    provider_health = (
        {
            "ai_ocr_status": args.provider_status,
            "ai_ocr_exit_code": args.provider_exit_code,
        }
        if args.provider_status is not None
        else None
    )

    bundle = build_evidence_bundle(
        args.repo_root.resolve(),
        gate_results=gate_results,
        provider_health=provider_health,
    )
    rendered = render_markdown(bundle)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Evidence bundle written: {args.output}")
    elif args.dry_run:
        print(
            f"[dry-run] Evidence bundle rehearsal OK: version={bundle.get('version')}, "
            f"gates={len(bundle.get('gate_map', []))}"
        )

    if args.github_summary:
        with args.github_summary.open("a", encoding="utf-8") as fh:
            fh.write(rendered)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
