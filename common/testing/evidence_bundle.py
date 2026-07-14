"""Shared CI/nightly evidence bundle (#1690, gate re-architecture Phase 4).

ONE generator, TWO producers today:

- main-branch CI (``ci.yml``), after ``unified-coverage`` + ``ac-behavioral-ratchet``
  complete, on every push to ``main``.
- the nightly ``audit-replay.yml`` run, which additionally supplies
  ``provider_health`` from the staging AI/OCR gate's own result.

A future third consumer (#1654's prod SLA report) is expected to reuse this
exact schema rather than build a second aggregation pipeline — see
``docs/project/EPIC-008.testing-strategy.md`` (AC8.13.164/AC8.13.165).

Deliberately reads already-computed CI artifacts (``unified-coverage.json``, the
persisted ratchet baseline files, the committed cassette corpus) rather than
re-running the gates that produced them — those gates already ran earlier in
the same job graph; this module only aggregates their output into one citable
bundle: a gate map (lane -> job -> blocking?), the raise-only ratchet water
lines (coverage / AC behavioural score / AC authority tier / protection floor),
corpus per-field accuracy (from the cassette graded-eval corpus), and —
when the caller supplies it — provider/canary health.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

BUNDLE_VERSION = 1

# Gate map: lane -> job -> blocking?. Hand-maintained mirror of ci.yml's
# `finish` job "Check job status" step, the canonical definition of which jobs
# block merge in this repo (no generator exists for the CI job graph itself,
# unlike common/testing/data/test-execution-matrix.yaml for test-file selection). Keep in
# sync when jobs are added/removed there —
# tests/tooling/test_evidence_bundle.py checks every listed job id still
# exists in ci.yml.
GATE_MAP: tuple[dict[str, Any], ...] = (
    {"lane": "classification", "job": "changes", "blocking": True},
    {"lane": "static", "job": "lint", "blocking": True},
    {"lane": "static", "job": "ac-traceability", "blocking": True},
    {"lane": "schema", "job": "schema-migrations", "blocking": True},
    {"lane": "backend", "job": "backend", "blocking": True},
    {"lane": "backend", "job": "backend-integration", "blocking": True},
    {"lane": "backend", "job": "backend-e2e-tier1", "blocking": True},
    {"lane": "frontend", "job": "frontend-build", "blocking": True},
    {"lane": "frontend", "job": "frontend-vitest", "blocking": True},
    {"lane": "frontend", "job": "frontend-playwright", "blocking": True},
    {"lane": "frontend", "job": "frontend-telemetry-e2e", "blocking": "conditional"},
    {"lane": "tooling", "job": "tooling-coverage", "blocking": True},
    {"lane": "coverage", "job": "unified-coverage", "blocking": True},
    {"lane": "ac-ratchet", "job": "ac-behavioral-ratchet", "blocking": True},
    {"lane": "images", "job": "container-images", "blocking": "conditional"},
)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def coverage_water_line(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """The unified-coverage ratchet: current % + per-component breakdown."""
    payload = _read_json(repo_root / "unified-coverage.json")
    if payload is None:
        return {"available": False}
    return {
        "available": True,
        "coverage_percent": payload.get("coverage_percent"),
        "breakdown": payload.get("breakdown", {}),
    }


def ac_score_water_line(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """The per-AC behavioural-score floor (common/testing/data/ac-score-baseline.jsonl).

    Unlike its cassette_eval_baseline sibling, ac_score_baseline_format.load_jsonl
    does not itself default a missing file to empty — it is a production module
    also called by check_ac_score_baseline's ratchet gate, where a missing
    committed baseline file is a real error, not a normal state. This reader
    guards the missing-file case itself instead of changing that contract.
    """
    from common.testing.ac_score_baseline_format import load_jsonl

    path = repo_root / "common" / "testing" / "data" / "ac-score-baseline.jsonl"
    payload = load_jsonl(path) if path.exists() else {"acs": {}}
    acs = payload.get("acs", {})
    scores = [float(record.get("score", 0.0)) for record in acs.values()]
    return {
        "baselined_ac_count": len(acs),
        "mean_floor_score": round(statistics.fmean(scores), 4) if scores else None,
    }


def ac_tier_water_line(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """The AC authority-tier untagged-debt ratchet (shrink-only)."""
    from common.meta.extension.check_ac_tier_baseline import load_baseline

    untagged = load_baseline(
        repo_root / "common" / "meta" / "data" / "ac-tier-baseline.json"
    )
    return {"untagged_debt_count": len(untagged)}


def protection_water_line(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """The per-type protection count floor (has_real_ref/has_proof/has_score/has_mirror)."""
    from common.testing.protection import load_floor

    return {
        "floor": load_floor(
            repo_root / "common" / "testing" / "data" / "protection-floor.json"
        )
    }


def cassette_eval_water_line() -> dict[str, Any]:
    """Corpus per-field accuracy + the corpus-count floor (#1681/AC-llm.8.8).

    Unlike the other water-lines above, this always reads the REAL committed
    cassette corpus — ``cassette_graded_eval.evaluate()``'s ground-truth/cassette
    directories are not parameterizable by ``repo_root`` (they resolve from
    this repo's own layout), and a synthetic corpus would not be a meaningful
    accuracy figure anyway.
    """
    from common.testing.cassette_eval_baseline import load_corpus_count_floor
    from common.testing.cassette_graded_eval import evaluate

    findings = evaluate()
    current = findings.get("_current", {})
    scores = [float(record.get("score", 0.0)) for record in current.values()]
    return {
        "case_count": len(current),
        "corpus_count_floor": load_corpus_count_floor(),
        "mean_field_accuracy": round(statistics.fmean(scores), 4) if scores else None,
        "regressions": len(findings.get("regressions", [])),
        "missing": len(findings.get("missing", [])),
    }


# Ratchet-baseline discovery (#1826, G-no-silent-baseline-aging). GLOB, not a
# hand-kept list: a NEW baseline/exceptions/floor file under common/ or docs/
# automatically appears in the bundle with zero code changes, so frozen debt
# that nobody is burning becomes visible instead of eternal.
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


def _baseline_entry_count(path: Path) -> int | None:
    """Logical entry count of a ratchet baseline/exceptions file.

    Format-aware but deliberately generic (the point is aging VISIBILITY, not
    per-ratchet semantics): a JSON list counts its items; a JSON dict counts
    the items of its sized values (lists/dicts, after dropping ``_``-prefixed
    meta keys and ``version``), else sums scalar-int counters (e.g. a
    ``{"total": N}`` mirror count), else counts its keys; JSONL counts
    non-empty lines; markdown counts table body rows.
    """
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
        # Each table contributes one header row and one separator row.
        return max(0, len(pipe_rows) - 2 * len(separators))
    return None


def _last_shrink_date(repo_root: Path, rel_path: str) -> str | None:
    """ISO date of the file's last commit (a shrink-only file's last shrink)."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, repo-local
            ["git", "log", "-1", "--format=%cI", "--", rel_path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def ratchet_baseline_inventory(repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    """Every glob-discovered ratchet baseline: path, entry count, last shrink."""
    found = {
        path
        for pattern in _BASELINE_GLOBS
        for path in repo_root.glob(pattern)
        if path.is_file()
    }
    inventory: list[dict[str, Any]] = []
    for path in sorted(found):
        rel = path.relative_to(repo_root).as_posix()
        inventory.append(
            {
                "file": rel,
                "entry_count": _baseline_entry_count(path),
                "last_shrink": _last_shrink_date(repo_root, rel),
            }
        )
    return inventory


def build_evidence_bundle(
    repo_root: Path = REPO_ROOT,
    *,
    gate_results: dict[str, str] | None = None,
    provider_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the shared evidence bundle from already-computed CI artifacts.

    ``gate_results`` (job id -> GitHub Actions job ``.result``, e.g.
    ``"success"``) is supplied by the CI caller from its own job graph — this
    function never re-runs a gate to get it. ``provider_health`` is populated
    by the nightly audit-replay producer (the staging AI/OCR gate's
    ``ai_ocr_status``/``ai_ocr_exit_code``); the main-branch CI producer omits
    it (not available in that context — no provider-backed gate runs there).
    """
    return {
        "version": BUNDLE_VERSION,
        "gate_map": [dict(entry) for entry in GATE_MAP],
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
    """Render the bundle as a GitHub-step-summary-ready markdown document."""
    lines = ["## Evidence Bundle", ""]

    lines.append("### Gate Map")
    lines.append("")
    lines.append("| Lane | Job | Blocking | Result |")
    lines.append("|---|---|---|---|")
    gate_results = bundle.get("gate_results", {})
    for entry in bundle.get("gate_map", []):
        job = entry["job"]
        result = gate_results.get(job, "n/a")
        blocking = entry["blocking"]
        blocking_label = (
            str(blocking).lower() if isinstance(blocking, bool) else blocking
        )
        lines.append(
            f"| `{entry['lane']}` | `{job}` | `{blocking_label}` | `{result}` |"
        )

    lines.append("")
    lines.append("### Ratchet Water Lines")
    lines.append("")
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
    protection = ratchets.get("protection", {}).get("floor", {})
    for ptype, floor in protection.items():
        lines.append(f"  - protection `{ptype}` floor: `{floor}`")

    lines.append("")
    lines.append("### Corpus Per-Field Accuracy")
    lines.append("")
    cassette_eval = bundle.get("cassette_eval", {})
    lines.append(
        f"- `{cassette_eval.get('case_count')}` case(s) "
        f"(floor `{cassette_eval.get('corpus_count_floor')}`), "
        f"mean field-accuracy `{cassette_eval.get('mean_field_accuracy')}`"
    )
    lines.append(
        f"- Regressions: `{cassette_eval.get('regressions')}`, "
        f"Missing: `{cassette_eval.get('missing')}`"
    )

    lines.append("")
    lines.append("### Ratchet Baseline Inventory")
    lines.append("")
    inventory = bundle.get("baseline_inventory", [])
    if inventory:
        lines.append("| Baseline | Entries | Last shrink |")
        lines.append("|---|---|---|")
        for entry in inventory:
            lines.append(
                f"| `{entry['file']}` | `{entry['entry_count']}` "
                f"| `{entry['last_shrink']}` |"
            )
    else:
        lines.append("- No ratchet baseline files discovered")

    provider_health = bundle.get("provider_health")
    lines.append("")
    lines.append("### Provider / Canary Health")
    lines.append("")
    if provider_health:
        for key, value in provider_health.items():
            lines.append(f"- `{key}`: `{value}`")
    else:
        lines.append("- Not available in this run (no provider-backed gate ran)")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the shared CI/nightly evidence bundle (#1690)."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-summary", type=Path, default=None)
    parser.add_argument(
        "--gate-results",
        type=str,
        default=None,
        help="JSON object of job id -> GitHub Actions job .result.",
    )
    parser.add_argument(
        "--provider-status",
        type=str,
        default=None,
        help="Provider/canary health status string (e.g. the staging AI/OCR "
        "gate's ai_ocr_status). Omitted -> provider_health is null.",
    )
    parser.add_argument("--provider-exit-code", type=str, default=None)
    args = parser.parse_args(argv)

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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Evidence bundle written: {args.output}")

    if args.github_summary:
        with args.github_summary.open("a", encoding="utf-8") as fh:
            fh.write(render_markdown(bundle))

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
